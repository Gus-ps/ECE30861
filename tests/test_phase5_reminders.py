"""REQ-12 / AC-13 / AC-14 / AC-15. Deadline reminder policy and notifications.

P5-REMINDER-90, P5-REMINDER-30, P5-REMINDER-7, P5-REMINDER-BEFORE,
P5-REMINDER-CLEAN, P5-REMINDER-NO-AUDIT, P5-REMINDER-PROCESSING,
P5-REMINDER-FAILED-AUDIT, P5-REMINDER-DECLINED, P5-REMINDER-PERIODIC-OFF,
P5-REMINDER-CLEAR-DEADLINE, P5-REMINDER-NO-BACKFILL, P5-REMINDER-CONFIG-EXACT,
P5-REMINDER-JUMP, P5-REMINDER-DEDUP, P5-REMINDER-CLEAN-THEN-DIRTY,
P5-REMINDER-RETURN-DEADLINE, P5-REMINDER-DEADLINE-EDIT, P5-REMINDER-LATEST-VERSION,
P5-REMINDER-AUDIT-SAME-TICK, P5-REMINDER-LEAP-UTC, P5-REMINDER-EMPTY,
P5-REMINDER-ORDER, P5-REMINDER-FAILED-RECORD, P5-FAULT-NOTIFICATION,
P5-LOCAL-NOTIFICATION-RESTART. P5-ACCESS-NOTIFICATIONS-* is covered by the access matrix.
"""
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from database import Database
from phase4_store import Store
from phase5_clock import format_time
import phase5_reminders as reminders
import phase5_schedule as schedules

DEADLINE = '2027-04-26'
START = '2027-01-01T00:00:00Z'
M90 = '2027-01-26T00:00:00Z'
M30 = '2027-03-27T00:00:00Z'
M7 = '2027-04-19T00:00:00Z'


class ReminderPolicyTests(unittest.TestCase):
    def test_legacy_deadline_uses_last_saved_time(self):
        with TemporaryDirectory() as directory:
            database = Database(Path(directory) / 'service.db')
            database.initialize()
            store = Store(database)
            with store.connect(write=True) as db:
                db.execute("""CREATE TABLE p5_schedules (
                    workbook_id TEXT PRIMARY KEY, namespace TEXT, owner TEXT NOT NULL,
                    enabled INTEGER NOT NULL, interval_days INTEGER, compliance_deadline TEXT,
                    next_audit_at TEXT, updated_at TEXT NOT NULL)""")
                db.execute('INSERT INTO p5_schedules VALUES (?,?,?,?,?,?,?,?)',
                           ('wb', None, 'owner', 0, None, DEADLINE, None, '2027-02-01T00:00:00Z'))
            schedules.initialize(store)
            schedules.initialize(store)
            with store.connect() as db:
                row = db.execute('SELECT * FROM p5_schedules').fetchone()
                self.assertEqual(row['deadline_set_at'], '2027-02-01T00:00:00Z')
                due = reminders.due_thresholds(row, datetime.fromisoformat(M30))
                self.assertEqual([offset for _, offset in due], [30])

    def test_calendar_vectors_and_unrepresentable_thresholds(self):
        for deadline, expected in (
            (DEADLINE, [M90, M30, M7]),
            ('2028-04-26', ['2028-01-27T00:00:00Z', '2028-03-27T00:00:00Z', '2028-04-19T00:00:00Z']),
            ('0001-01-08', ['0001-01-01T00:00:00Z']),
        ):
            with self.subTest(deadline=deadline):
                row = {'compliance_deadline': deadline, 'deadline_set_at': '0001-01-01T00:00:00Z'}
                actual = reminders.due_thresholds(row, datetime.fromisoformat('2028-05-01T00:00:00Z'))
                self.assertEqual([format_time(instant) for instant, _ in actual], expected)

    def test_crossing_vectors(self):
        for configured, advance, expected in (
            ('2027-01-25T00:00:00Z', M90, [90]),
            (START, '2027-04-20T00:00:00Z', [90, 30, 7]),
            ('2027-02-01T00:00:00Z', M30, [30]),
            (M90, M90, [90]),
            (START, '2027-01-25T23:59:59.999999Z', []),
        ):
            with self.subTest(configured=configured, advance=advance):
                row = {'compliance_deadline': DEADLINE, 'deadline_set_at': configured}
                thresholds = reminders.due_thresholds(row, datetime.fromisoformat(advance))
                self.assertEqual([offset for _, offset in thresholds], expected)

    def test_eligibility_vectors(self):
        for status, count, expected in (
            (None, 0, True), ('PROCESSING', 0, True), ('PROCESSING_FAILED', 0, True),
            ('AUDIT_COMPLETE', 0, False), ('REVIEW_REQUIRED', 2, True), ('REMEDIATION_AVAILABLE', 1, True),
        ):
            with self.subTest(status=status):
                audit = None if status is None else {'status': status, 'findings': [{}] * count}
                self.assertEqual(reminders.eligible(audit), expected)

    def test_timestamp_tracks_only_deadline_changes_and_ordinary_dispatch_deduplicates(self):
        with TemporaryDirectory() as directory:
            database = Database(Path(directory) / 'service.db')
            database.initialize()
            store = Store(database)
            schedules.initialize(store)
            reminders.initialize(store)
            with store.connect(write=True) as db:
                store.insert(db, 'workbook', 'wb', {}, 'owner', None, 'wb')
                store.insert(db, 'version', 'ver', {}, 'owner', None, 'wb', 'ver')
                workbook = store.get(db, 'wb')
                body = dict(enabled=False, intervalDays=None, complianceDeadline=DEADLINE)
                for instant, interval in ((START, None), (M90, 1), (M30, 1)):
                    with patch.object(schedules, 'effective_now', return_value=datetime.fromisoformat(instant)):
                        schedules.write(db, workbook, dict(body, intervalDays=interval))
                self.assertEqual(db.execute('SELECT deadline_set_at FROM p5_schedules').fetchone()[0], START)
                instant = datetime.fromisoformat(M90)
                self.assertEqual(len(reminders.dispatch_due_reminders(store, db, None, instant)), 1)
                self.assertEqual(reminders.dispatch_due_reminders(store, db, None, instant), [])
                with patch.object(schedules, 'effective_now', return_value=datetime.fromisoformat(M90)):
                    schedules.write(db, workbook, dict(body, complianceDeadline='2027-05-01'))
                self.assertEqual(db.execute('SELECT deadline_set_at FROM p5_schedules').fetchone()[0], M90)
