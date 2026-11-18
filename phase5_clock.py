"""Persistent effective time for isolated test sessions."""
from datetime import datetime, timezone
from typing import Annotated

from pydantic import Field, StringConstraints, field_validator

from contracts import Contract, Identifier, MAX_JSON_REQUEST_BYTES, strict_json
from service_errors import ApiError

PATH = '/api/v1/test/clock'
INITIAL_TIME = '2027-01-01T00:00:00Z'
AUDIT_WORK_LIMIT = 1000
REMINDER_WORK_LIMIT = 3000
ClockTimestamp = Annotated[str, StringConstraints(
    pattern=r'^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?Z$',
), Field(json_schema_extra={'format': 'date-time'})]


class ClockRequest(Contract):
    currentTime: ClockTimestamp

    @field_validator('currentTime')
    @classmethod
    def normalize_time(cls, value):
        return format_time(datetime.fromisoformat(value))


class ClockResponse(Contract):
    currentTime: ClockTimestamp
    triggeredAudits: list[Identifier] = Field(max_length=1000, json_schema_extra={'uniqueItems': True})
    triggeredNotifications: list[Identifier] = Field(max_length=3000, json_schema_extra={'uniqueItems': True})


def format_time(instant):
    return instant.isoformat().replace('+00:00', 'Z')


def read(db, session_id, *, lock=False):
    query = 'SELECT "current_time" FROM p5_clocks WHERE session_id=?'
    if lock:
        query += ' FOR UPDATE'
    row = db.execute(query, (session_id,)).fetchone()
    return datetime.fromisoformat(row['current_time']) if row else None


def effective_now(db, namespace):
    if namespace is not None:
        simulated = read(db, namespace)
        if simulated is not None:
            return simulated
    return datetime.now(timezone.utc)


def advance(store, db, session_id, current, raw, request_id):
    if raw is None:
        raise ApiError(413, 'REQUEST_TOO_LARGE', 'JSON request exceeds 1 MiB.')
    try:
        request = ClockRequest.model_validate(strict_json(raw))
    except (ValueError, RecursionError):
        raise ApiError(400, 'INVALID_REQUEST', 'Invalid clock request.') from None
    instant = datetime.fromisoformat(request.currentTime)
    if instant < current:
        raise ApiError(400, 'CLOCK_REWIND', 'The test clock cannot move backward.')
    if instant > current:
        db.execute('UPDATE p5_clocks SET "current_time"=? WHERE session_id=?',
                   (request.currentTime, session_id))
    audits, notifications = process_due_work(store, db, session_id, instant, request_id)
    return ClockResponse(currentTime=request.currentTime, triggeredAudits=audits,
                         triggeredNotifications=notifications)


def process_due_work(store, db, session_id, instant, request_id):
    """Accept due work inside the clock transaction and return newly accepted IDs."""
    from phase5_reminders import dispatch_due_reminders, due_thresholds
    from phase5_schedule import audit_due, dispatch_due_audits, locked_schedules

    schedules = locked_schedules(store, db, session_id,
                                 lambda row: audit_due(row, instant) or due_thresholds(row, instant))
    notifications = dispatch_due_reminders(store, db, session_id, instant,
                                          limit=REMINDER_WORK_LIMIT, schedules=schedules)
    audits = dispatch_due_audits(store, db, session_id, instant, request_id,
                                 reject_busy=True, limit=AUDIT_WORK_LIMIT, schedules=schedules)
    return audits, notifications


async def read_request_body(request):
    raw = bytearray()
    async for chunk in request.stream():
        if len(raw) + len(chunk) > MAX_JSON_REQUEST_BYTES:
            return None
        raw.extend(chunk)
    return raw
