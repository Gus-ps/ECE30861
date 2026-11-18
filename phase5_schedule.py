"""REQ-12 / AC-12, AC-15: configure schedules and accept periodic audits."""
from datetime import datetime, timedelta

from pydantic import Field
from contracts import Contract, Identifier, Timestamp, strict_json
from phase4_jobs import begin_audit
from phase5_clock import effective_now, format_time
from service_errors import ApiError


class ScheduleRequest(Contract):
    model_config = {**Contract.model_config, 'json_schema_extra': {
        'anyOf': [
            {'properties': {'enabled': {'const': False}}},
            {'properties': {'enabled': {'const': True}, 'intervalDays': {
                'type': 'integer', 'minimum': 1, 'maximum': 90}},
             'required': ['intervalDays']}
        ]}}
    enabled: bool
    intervalDays: int | None = Field(default=None, ge=1, le=90)
    complianceDeadline: str | None = Field(default=None, pattern=r'^[0-9]{4}-[0-9]{2}-[0-9]{2}$', json_schema_extra={'format': 'date'})


class ScheduleResponse(Contract):
    workbookId: Identifier
    enabled: bool
    intervalDays: int | None
    complianceDeadline: str | None
    versionId: Identifier
    nextAuditAt: Timestamp | None
    reminderDays: list[int] = Field(json_schema_extra={'const': [90, 30, 7]})


def initialize(store):
    with store.connect(write=True) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS p5_schedules (
            workbook_id TEXT PRIMARY KEY, namespace TEXT, owner TEXT NOT NULL,
            enabled INTEGER NOT NULL, interval_days INTEGER,
            compliance_deadline TEXT, next_audit_at TEXT, updated_at TEXT NOT NULL)""")
        db.execute('CREATE INDEX IF NOT EXISTS p5_schedule_due ON p5_schedules(next_audit_at)')


def parse_body(raw):
    from datetime import date
    try:
        value = ScheduleRequest.model_validate(strict_json(raw))
        if value.enabled and value.intervalDays is None:
            raise ValueError('Interval required')
        if value.complianceDeadline is not None:
            date.fromisoformat(value.complianceDeadline)
        return value.model_dump()
    except (ValueError, UnicodeError, TypeError):
        raise ApiError(400, 'INVALID_REQUEST', 'Invalid schedule configuration.') from None


def latest_version_id(db, workbook_id):
    version = db.execute("""SELECT id FROM p4_resources
        WHERE workbook_id=? AND kind='version' ORDER BY seq DESC LIMIT 1""",
        (workbook_id,)).fetchone()
    return version['id'] if version else None


def read(db, workbook):
    row = db.execute('SELECT * FROM p5_schedules WHERE workbook_id=?',
                     (workbook['id'],)).fetchone()
    return dict(workbookId=workbook['id'], enabled=bool(row['enabled']) if row else False,
        intervalDays=row['interval_days'] if row else None,
        complianceDeadline=row['compliance_deadline'] if row else None,
        versionId=latest_version_id(db, workbook['id']), nextAuditAt=row['next_audit_at'] if row else None,
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


def dispatch_due_audits(store, db, namespace, instant, request_id, *, reject_busy=False, limit=None):
    """Fence and accept due audits within the caller's write transaction."""
    scope, params = ('namespace IS NULL', ()) if namespace is None else ('namespace=?', (namespace,))
    candidates = db.execute(f'''SELECT workbook_id,next_audit_at FROM p5_schedules
        WHERE {scope} AND enabled=1 AND next_audit_at IS NOT NULL''', params)
    workbook_ids = sorted(row['workbook_id'] for row in candidates
                          if datetime.fromisoformat(row['next_audit_at']) <= instant)
    due = []
    for workbook_id in workbook_ids:
        store.fence(db, workbook_id)
        # Re-read under the fence to discard deleted or rescheduled candidates.
        row = db.execute('SELECT * FROM p5_schedules WHERE workbook_id=?', (workbook_id,)).fetchone()
        if not row or row['namespace'] != namespace or not row['enabled'] or row['next_audit_at'] is None:
            continue
        previous = datetime.fromisoformat(row['next_audit_at'])
        if previous <= instant:
            due.append((previous, workbook_id, row['interval_days']))
    if limit is not None and len(due) > limit:
        raise ApiError(409, 'CLOCK_WORK_LIMIT', 'Too many scheduled audits are due.')

    accepted = []
    for previous, workbook_id, interval_days in sorted(due):
        version_id = latest_version_id(db, workbook_id)
        if version_id is None:
            continue
        if store.active(db, version_id):
            if reject_busy:
                raise ApiError(409, 'ACTIVE_OPERATION', 'An operation is already active for this version.')
            continue
        interval = timedelta(days=interval_days)
        try:
            next_due = previous + ((instant - previous) // interval + 1) * interval
        except OverflowError:
            raise ApiError(400, 'TIME_RANGE_EXCEEDED', 'Schedule exceeds supported time range.') from None
        accepted.append((version_id, workbook_id, format_time(next_due)))

    audits = []
    for version_id, workbook_id, next_due in accepted:
        version = store.get(db, version_id, 'version')
        audits.append(begin_audit(store, db, version, request_id, scheduled_at=instant))
        db.execute('UPDATE p5_schedules SET next_audit_at=?, updated_at=? WHERE workbook_id=?',
                   (next_due, format_time(instant), workbook_id))
    return audits
