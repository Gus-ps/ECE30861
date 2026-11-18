"""Durable in-application deadline reminders."""
from datetime import date, datetime, time, timedelta, timezone
from typing import Literal

from pydantic import Field

from contracts import Contract, Identifier
from phase4_jobs import identifier
from phase5_clock import ClockTimestamp, format_time
from phase5_schedule import latest_version_id, locked_schedules
from service_errors import ApiError

OFFSETS = (90, 30, 7)
STORED_VERSION_NOTICE = (
    'Scheduled audits check the stored version only. '
    'Changes to an external workbook cannot be detected until a new version is uploaded.'
)


class Notification(Contract):
    notificationId: Identifier
    type: Literal['COMPLIANCE_DEADLINE_REMINDER', 'AUDIT_REMINDER']
    workbookId: Identifier
    versionId: Identifier
    scheduledFor: ClockTimestamp
    status: Literal['PENDING', 'DELIVERED', 'FAILED']
    message: str = Field(min_length=1, max_length=500, pattern=r'\S')


class NotificationResponse(Contract):
    notifications: list[Notification]


def initialize(store):
    with store.connect(write=True) as db:
        if store.database.postgres:
            db.execute('SELECT pg_advisory_xact_lock(3086101)')
        sequence = 'BIGSERIAL PRIMARY KEY' if store.database.postgres else 'INTEGER PRIMARY KEY AUTOINCREMENT'
        db.execute(f"""CREATE TABLE IF NOT EXISTS p5_notifications (
            seq {sequence}, notification_id TEXT NOT NULL UNIQUE, namespace TEXT,
            workbook_id TEXT NOT NULL, version_id TEXT NOT NULL, type TEXT NOT NULL,
            scheduled_for TEXT NOT NULL, status TEXT NOT NULL, message TEXT NOT NULL)""")
        db.execute("""CREATE TABLE IF NOT EXISTS p5_reminder_considered (
            workbook_id TEXT NOT NULL, namespace TEXT, deadline TEXT NOT NULL, offset_days INTEGER NOT NULL,
            PRIMARY KEY (workbook_id,deadline,offset_days))""")
        db.execute('CREATE INDEX IF NOT EXISTS p5_notification_workbook ON p5_notifications(workbook_id,scheduled_for,seq)')
        db.execute('CREATE INDEX IF NOT EXISTS p5_notification_namespace ON p5_notifications(namespace)')
        db.execute('CREATE INDEX IF NOT EXISTS p5_reminder_namespace ON p5_reminder_considered(namespace)')


def read_notifications(db, workbook_id):
    rows = db.execute("""SELECT notification_id AS "notificationId", type, workbook_id AS "workbookId",
        version_id AS "versionId", scheduled_for AS "scheduledFor", status, message
        FROM p5_notifications WHERE workbook_id=? ORDER BY scheduled_for, seq""", (workbook_id,))
    return {'notifications': [dict(row) for row in rows]}


def due_thresholds(row, instant):
    if row['compliance_deadline'] is None or row['deadline_set_at'] is None:
        return []
    deadline = date.fromisoformat(row['compliance_deadline'])
    configured = datetime.fromisoformat(row['deadline_set_at'])
    thresholds = []
    for offset in OFFSETS:
        if deadline.toordinal() <= offset:
            continue
        threshold = datetime.combine(deadline - timedelta(days=offset), time.min, timezone.utc)
        if configured <= threshold <= instant:
            thresholds.append((threshold, offset))
    return thresholds


def eligible(audit):
    return audit is None or audit['status'] in ('PROCESSING', 'PROCESSING_FAILED') or bool(audit['findings'])


def create_notification(db, namespace, workbook_id, version_id, deadline, threshold, offset):
    notification_id = identifier('notification')
    message = (f'Compliance deadline {deadline} is {offset} days after this reminder threshold '
               f'for stored version {version_id}. {STORED_VERSION_NOTICE}')
    status = 'DELIVERED'
    if namespace is not None:
        fault = db.execute("""UPDATE p5_faults SET remaining=0
            WHERE session_id=? AND kind='notification' AND remaining=1""", (namespace,))
        if fault.rowcount == 1:
            status = 'FAILED'
            message += ' A simulated in-app notification failure prevented delivery.'
    db.execute("""INSERT INTO p5_notifications
        (notification_id,namespace,workbook_id,version_id,type,scheduled_for,status,message)
        VALUES (?,?,?,?,'COMPLIANCE_DEADLINE_REMINDER',?,?,?)""",
        (notification_id, namespace, workbook_id, version_id, format_time(threshold), status, message))
    return notification_id


def dispatch_due_reminders(store, db, namespace, instant, *, limit=None, schedules=None,
                           recorded_deadlines=None):
    """Consider due thresholds and record eligible notifications in the caller's transaction."""
    if schedules is None:
        schedules = locked_schedules(store, db, namespace, lambda row: due_thresholds(row, instant))
    due = []
    for row in schedules:
        thresholds = due_thresholds(row, instant)
        if not thresholds:
            continue
        workbook_id, deadline = row['workbook_id'], row['compliance_deadline']
        considered = {key['offset_days'] for key in db.execute(
            'SELECT offset_days FROM p5_reminder_considered WHERE workbook_id=? AND deadline=?',
            (workbook_id, deadline))}
        due.extend((threshold, workbook_id, -offset, deadline) for threshold, offset in thresholds
                   if offset not in considered)
    if limit is not None and len(due) > limit:
        raise ApiError(409, 'CLOCK_WORK_LIMIT', 'Too many reminder occurrences are due.')

    notifications, evidence = [], {}
    for threshold, workbook_id, negative_offset, deadline in sorted(due):
        if workbook_id not in evidence:
            version_id = latest_version_id(db, workbook_id)
            if version_id is None:
                evidence[workbook_id] = (None, False)
            else:
                version = store.get(db, version_id, 'version')
                audit = store.get(db, version['body'].get('latestAuditId'), 'audit')
                evidence[workbook_id] = (version_id, eligible(audit['body'] if audit else None))
        version_id, should_notify = evidence[workbook_id]
        if version_id is None:
            continue
        offset = -negative_offset
        claimed = db.execute("""INSERT INTO p5_reminder_considered
            (workbook_id,namespace,deadline,offset_days) VALUES (?,?,?,?)
            ON CONFLICT(workbook_id,deadline,offset_days) DO NOTHING""",
            (workbook_id, namespace, deadline, offset))
        if should_notify and claimed.rowcount == 1:
            notifications.append(create_notification(db, namespace, workbook_id, version_id,
                                                     deadline, threshold, offset))
            if recorded_deadlines is not None:
                recorded_deadlines.append(threshold)
    return notifications
