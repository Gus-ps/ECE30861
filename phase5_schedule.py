"""REQ-12 / AC-12, AC-15: schedule configuration only; no WCAG checker."""
from datetime import datetime, timedelta, timezone
import json
import re

from pydantic import Field
from contracts import Contract, Identifier, Timestamp
from service_errors import ApiError


class ScheduleRequest(Contract):
    enabled: bool
    intervalDays: int | None = Field(default=None, ge=1, le=90)
    complianceDeadline: str | None = Field(default=None, pattern=r'^[0-9]{4}-[0-9]{2}-[0-9]{2}$')


class ScheduleResponse(Contract):
    workbookId: Identifier
    enabled: bool
    intervalDays: int | None
    complianceDeadline: str | None
    versionId: Identifier
    nextAuditAt: Timestamp | None
    reminderDays: list[int]


def effective_now(db, namespace):
    return datetime.now(timezone.utc)


def initialize(store):
    with store.connect(write=True) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS p5_schedules (
            workbook_id TEXT PRIMARY KEY, namespace TEXT, owner TEXT NOT NULL,
            enabled INTEGER NOT NULL, interval_days INTEGER,
            compliance_deadline TEXT, next_audit_at TEXT, updated_at TEXT NOT NULL)""")
        db.execute('CREATE INDEX IF NOT EXISTS p5_schedule_due ON p5_schedules(next_audit_at)')


def parse_body(raw):
    from datetime import date
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Duplicate key')
            result[key] = value
        return result
    def invalid(value):
        raise ValueError('Nonfinite number')
    try:
        body = json.loads(raw.decode('utf-8'), object_pairs_hook=pairs, parse_constant=invalid)
        value = ScheduleRequest.model_validate(body)
        if value.enabled and value.intervalDays is None:
            raise ValueError('Interval required')
        if value.complianceDeadline is not None:
            date.fromisoformat(value.complianceDeadline)
        return value.model_dump()
    except (ValueError, UnicodeError, TypeError):
        raise ApiError(400, 'INVALID_REQUEST', 'Invalid schedule configuration.') from None


def read(db, workbook):
    row = db.execute('SELECT * FROM p5_schedules WHERE workbook_id=?',
                     (workbook['id'],)).fetchone()
    version = db.execute("""SELECT id FROM p4_resources
        WHERE workbook_id=? AND kind='version' ORDER BY seq DESC LIMIT 1""",
        (workbook['id'],)).fetchone()
    return dict(workbookId=workbook['id'], enabled=bool(row['enabled']) if row else False,
        intervalDays=row['interval_days'] if row else None,
        complianceDeadline=row['compliance_deadline'] if row else None,
        versionId=version['id'], nextAuditAt=row['next_audit_at'] if row else None,
        reminderDays=[90, 30, 7])


def write(db, workbook, body):
    previous = read(db, workbook)
    if all(previous[k] == body[k] for k in body):
        return previous
    instant = effective_now(db, workbook['namespace'])
    due = previous['nextAuditAt']
    try:
        if not body['enabled']:
            due = None
        elif not previous['enabled'] or previous['intervalDays'] != body['intervalDays']:
            due = (instant + timedelta(days=body['intervalDays'])).isoformat().replace('+00:00', 'Z')
    except OverflowError:
        raise ApiError(400, 'TIME_RANGE_EXCEEDED', 'Schedule exceeds supported time range.') from None
    db.execute("""INSERT INTO p5_schedules VALUES (?,?,?,?,?,?,?,?)
        ON CONFLICT(workbook_id) DO UPDATE SET namespace=excluded.namespace,
        owner=excluded.owner, enabled=excluded.enabled, interval_days=excluded.interval_days,
        compliance_deadline=excluded.compliance_deadline, next_audit_at=excluded.next_audit_at,
        updated_at=excluded.updated_at""",
        (workbook['id'], workbook['namespace'], workbook['owner'], int(body['enabled']),
         body['intervalDays'], body['complianceDeadline'], due,
         instant.isoformat().replace('+00:00', 'Z')))
    return read(db, workbook)
