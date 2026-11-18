"""REQ-12 / AC-13 / AC-14 / AC-15. Deadline reminder policy and notifications.

P5-REMINDER-90, P5-REMINDER-30, P5-REMINDER-7, P5-REMINDER-BEFORE,
P5-REMINDER-CLEAN, P5-REMINDER-NO-AUDIT, P5-REMINDER-PROCESSING,
P5-REMINDER-FAILED-AUDIT, P5-REMINDER-DECLINED, P5-REMINDER-PERIODIC-OFF,
P5-REMINDER-CLEAR-DEADLINE, P5-REMINDER-NO-BACKFILL, P5-REMINDER-CONFIG-EXACT,
P5-REMINDER-JUMP, P5-REMINDER-DEDUP, P5-REMINDER-CLEAN-THEN-DIRTY,
P5-REMINDER-RETURN-DEADLINE, P5-REMINDER-DEADLINE-EDIT, P5-REMINDER-LATEST-VERSION,
P5-REMINDER-AUDIT-SAME-TICK, P5-REMINDER-LEAP-UTC, P5-REMINDER-EMPTY,
P5-REMINDER-ORDER, P5-REMINDER-FAILED-RECORD, P5-FAULT-NOTIFICATION,
P5-LOCAL-NOTIFICATION-RESTART. The access matrix covers
P5-ACCESS-NOTIFICATIONS-NO-TOKEN, P5-ACCESS-NOTIFICATIONS-INVALID-TOKEN,
P5-ACCESS-NOTIFICATIONS-FOREIGN-OWNER, P5-ACCESS-NOTIFICATIONS-WRONG-NAMESPACE,
P5-ACCESS-NOTIFICATIONS-TEST-ADMIN, P5-ACCESS-NOTIFICATIONS-UNKNOWN-RESOURCE,
P5-ACCESS-NOTIFICATIONS-OWNER, P5-ACCESS-NOTIFICATIONS-GRANTED-REVIEWER,
P5-ACCESS-NOTIFICATIONS-UNGRANTED-REVIEWER.
"""
from datetime import datetime, timedelta
import os
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import create_app

from database import Database
from phase4_store import Store
from phase5_clock import format_time
import phase5_reminders as reminders
import phase5_schedule as schedules
import test_phase5_dispatch as dispatch_tests

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


class ReminderClockTests(unittest.TestCase):
    setUp = dispatch_tests.DispatchTests.setUp
    prepare = dispatch_tests.DispatchTests.prepare
    upload = dispatch_tests.DispatchTests.upload
    advance = dispatch_tests.DispatchTests.advance
    read_audit = dispatch_tests.DispatchTests.read_audit
    assert_error = dispatch_tests.DispatchTests.assert_error
    remediate = dispatch_tests.DispatchTests.remediate

    def configure(self, headers, path, deadline=DEADLINE, interval=None):
        body = {'enabled': interval is not None, 'complianceDeadline': deadline}
        if interval is not None:
            body['intervalDays'] = interval
        result = self.client.put(path + '/schedule', headers=headers, json=body)
        self.assertEqual(result.status_code, 200, result.text)
        return result.json()

    def workbook(self, headers, *, clean=False, deadline=DEADLINE, interval=None):
        if clean:
            with patch.object(self.runner, 'checker', return_value=[]):
                ids, version = self.upload(headers)
        else:
            ids, version = self.upload(headers)
        path = version.rsplit('/versions/', 1)[0]
        self.configure(headers, path, deadline, interval)
        return ids, path, version

    def tick(self, instant, session='clock'):
        response = self.advance(instant, session)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['currentTime'], instant)
        return response.json()

    def rows(self, table):
        with self.app.state.store.connect() as db:
            return [dict(row) for row in db.execute(f'SELECT * FROM {table} ORDER BY 1')]

    def notifications(self):
        return sorted(self.rows('p5_notifications'), key=lambda row: row['seq'])

    def snapshot(self):
        return {table: self.rows(table) for table in (
            'p5_clocks', 'p5_schedules', 'p5_notifications', 'p5_reminder_considered',
            'p4_resources', 'p4_jobs', 'p5_faults',
        )}

    def test_threshold_boundaries_and_message(self):
        headers = self.prepare()
        ids, _, _ = self.workbook(headers)
        expected = []
        for instant, offset in ((M90, 90), (M30, 30), (M7, 7)):
            before = datetime.fromisoformat(instant) - timedelta(microseconds=1)
            self.assertEqual(self.tick(format_time(before))['triggeredNotifications'], [])
            result = self.tick(instant)
            self.assertEqual(result['triggeredAudits'], [])
            nid, = result['triggeredNotifications']
            record = self.notifications()[-1]
            self.assertEqual(record['notification_id'], nid)
            self.assertEqual(record['scheduled_for'], instant)
            self.assertEqual(record['status'], 'DELIVERED')
            self.assertEqual(record['type'], 'COMPLIANCE_DEADLINE_REMINDER')
            self.assertEqual(record['version_id'], ids['versionId'])
            for content in (DEADLINE, str(offset), ids['versionId'], reminders.STORED_VERSION_NOTICE):
                self.assertIn(content, record['message'])
            expected.append(nid)
        self.assertEqual([record['notification_id'] for record in self.notifications()], expected)

    def test_jump_and_no_backfill_vectors(self):
        a = self.prepare('jump')
        b = self.prepare('late', clock={'currentTime': '2027-02-01T00:00:00Z'})
        self.workbook(a)
        self.workbook(b)
        ids = self.tick('2027-04-20T00:00:00Z', 'jump')['triggeredNotifications']
        self.assertEqual(ids, [row['notification_id'] for row in self.notifications()])
        self.assertEqual([row['scheduled_for'] for row in self.notifications()], [M90, M30, M7])
        self.assertEqual(len(self.tick(M30, 'late')['triggeredNotifications']), 1)
        self.assertEqual(self.notifications()[-1]['scheduled_for'], M30)
        self.assertEqual(self.tick(M30, 'late')['triggeredNotifications'], [])

    def test_configuration_at_threshold_and_edit_return_clear(self):
        headers = self.prepare(clock={'currentTime': M90})
        _, path, _ = self.workbook(headers)
        first, = self.tick(M90)['triggeredNotifications']
        original = self.notifications()[0]
        self.configure(headers, path)
        self.assertEqual(self.tick(M90)['triggeredNotifications'], [])
        self.configure(headers, path, '2027-05-01')
        self.configure(headers, path)
        self.assertEqual(self.tick(M90)['triggeredNotifications'], [])
        self.configure(headers, path, '2027-05-01')
        self.assertEqual(len(self.tick('2027-01-31T00:00:00Z')['triggeredNotifications']), 1)
        self.assertEqual(self.notifications()[0], original)
        self.configure(headers, path, None)
        self.assertEqual(self.tick('2027-06-01T00:00:00Z')['triggeredNotifications'], [])
        self.assertEqual(len(self.notifications()), 2)
        self.assertEqual(self.notifications()[0]['notification_id'], first)

    def test_clean_considered_and_new_dirty_version_is_used_later(self):
        headers = self.prepare()
        _, path, _ = self.workbook(headers, clean=True)
        self.assertEqual(self.tick(M90)['triggeredNotifications'], [])
        self.assertEqual(len(self.rows('p5_reminder_considered')), 1)
        newest, _ = self.upload(headers, path + '/versions')
        self.assertEqual(self.tick(M90)['triggeredNotifications'], [])
        self.assertEqual(len(self.tick(M30)['triggeredNotifications']), 1)
        self.assertEqual(self.notifications()[0]['version_id'], newest['versionId'])

    def test_audit_same_tick_uses_clean_pre_dispatch_state(self):
        headers = self.prepare()
        _, _, version = self.workbook(headers, clean=True, interval=25)
        result = self.tick(M90)
        aid, = result['triggeredAudits']
        self.assertEqual(result['triggeredNotifications'], [])
        self.assertEqual(self.read_audit(headers, version, aid)['status'], 'PROCESSING')
        self.assertEqual(len(self.rows('p5_reminder_considered')), 1)

    def test_no_audit_processing_failed_and_declined_are_eligible(self):
        headers = self.prepare(faults={'audit_failures': 1})
        failed, _, failed_version = self.workbook(headers)
        self.assertEqual(self.read_audit(headers, failed_version, failed['auditId'])['status'], 'PROCESSING_FAILED')
        absent, _, _ = self.workbook(headers)
        with self.app.state.store.connect(write=True) as db:
            store = self.app.state.store
            row = store.get(db, absent['versionId'])
            store.update(db, row['id'], dict(row['body'], latestAuditId=None))
        original, _, version = self.workbook(headers)
        rid = self.remediate(headers, version, original['auditId'])
        result = self.client.get(f'/api/v1/remediations/{rid}', headers=headers).json()
        self.assertEqual(result['status'], 'REMEDIATED')
        with patch.object(self.runner, 'drain'):
            running, _, running_version = self.workbook(headers)
        processing = self.read_audit(headers, running_version, running['auditId'])
        self.assertEqual((processing['status'], processing['findings']), ('PROCESSING', []))
        ids = self.tick(M90)['triggeredNotifications']
        self.assertEqual(len(ids), 4)
        self.assertEqual({row['version_id'] for row in self.notifications()},
                         {failed['versionId'], running['versionId'], absent['versionId'], result['outputVersionId']})

    def test_fault_is_one_shot_skips_suppression_and_preserves_audit(self):
        headers = self.prepare(faults={'notification_failures': 1})
        _, path, _ = self.workbook(headers, clean=True)
        self.assertEqual(self.tick(M90)['triggeredNotifications'], [])
        self.assertEqual(self.rows('p5_faults')[0]['remaining'], 1)
        other = self.prepare('other')
        self.workbook(other)
        self.tick(M90, 'other')
        owner = dispatch_tests.OWNER
        with patch.object(schedules, 'effective_now', return_value=datetime.fromisoformat(START)):
            self.workbook(owner)
        with self.app.state.store.connect(write=True) as db:
            self.assertEqual(len(reminders.dispatch_due_reminders(
                self.app.state.store, db, None, datetime.fromisoformat(M90))), 1)
        self.assertEqual(self.rows('p5_faults')[0]['remaining'], 1)
        ids, version = self.upload(headers, path + '/versions')
        before = self.read_audit(headers, version, ids['auditId'])
        failed, = self.tick(M30)['triggeredNotifications']
        self.assertEqual(self.notifications()[-1]['notification_id'], failed)
        self.assertEqual(self.notifications()[-1]['status'], 'FAILED')
        self.assertIn('simulated', self.notifications()[-1]['message'])
        self.assertEqual(self.read_audit(headers, version, ids['auditId']), before)
        self.assertEqual(self.rows('p5_faults')[0]['remaining'], 0)
        self.assertEqual(self.tick(M30)['triggeredNotifications'], [])
        self.tick(M7)
        self.assertEqual([r['status'] for r in self.notifications()],
                         ['DELIVERED', 'DELIVERED', 'FAILED', 'DELIVERED'])

    def test_fault_configuration_validation_and_capability(self):
        def setup(value):
            return self.client.post('/test/setup', headers=dispatch_tests.ADMIN, json={
                'session_id': 'fault', 'setup': {'faults': {'notification_failures': value}},
            })
        for value in (True, 1.0, 2, '1', None):
            with self.subTest(value=value):
                response = setup(value)
                self.assertEqual(response.status_code, 400, response.text)
                self.assertEqual(set(response.json()), {'message', 'source'})
        with patch.dict(os.environ, {'ENABLE_TEST_FAULTS': 'false'}):
            response = setup(1)
            self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(setup(1).status_code, 201)
        self.assertEqual(setup(1).status_code, 409)

    def test_work_limit_counts_suppressed_occurrences_and_rolls_back(self):
        headers = self.prepare()
        self.workbook(headers, clean=True)
        before = self.snapshot()
        with patch('phase5_clock.REMINDER_WORK_LIMIT', 2):
            self.assert_error(self.advance(M7), 409, 'CLOCK_WORK_LIMIT')
        self.assertEqual(self.snapshot(), before)

    def test_busy_audit_and_storage_failure_roll_back_reminders(self):
        headers = self.prepare(faults={'notification_failures': 1})
        with patch.object(self.runner, 'drain'):
            self.workbook(headers, interval=25)
        before = self.snapshot()
        self.assert_error(self.advance(M90), 409, 'ACTIVE_OPERATION')
        self.assertEqual(self.snapshot(), before)
        self.runner.drain()
        before = self.snapshot()
        with patch('phase5_schedule.begin_audit', side_effect=sqlite3.OperationalError('audit insert failed')):
            with self.assertLogs(level='ERROR'):
                self.assert_error(self.advance(M90), 500, 'STORAGE_FAILED')
        self.assertEqual(self.snapshot(), before)
        result = self.tick(M90)
        self.assertEqual(len(result['triggeredAudits']), 1)
        self.assertEqual(len(result['triggeredNotifications']), 1)

    def get_notifications(self, headers, path):
        response = self.client.get(path + '/notifications', headers=headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(set(response.json()), {'notifications'})
        return response.json()['notifications']

    def test_empty_contract_invalid_id_and_openapi(self):
        headers = self.prepare()
        _, path, _ = self.workbook(headers)
        self.assertEqual(self.get_notifications(headers, path), [])
        response = self.client.get('/api/v1/workbooks/bad!id/notifications', headers=headers)
        self.assert_error(response, 400, 'INVALID_REQUEST')
        schema = self.client.get('/openapi.json').json()
        operation = schema['paths']['/api/v1/workbooks/{workbook_id}/notifications']['get']
        self.assertIn({'HTTPBearer': []}, operation['security'])
        self.assertEqual(operation['responses']['200']['content']['application/json']['schema']['$ref'],
                         '#/components/schemas/NotificationResponse')

    def test_order_and_terminal_records_survive_restart(self):
        headers = self.prepare(faults={'notification_failures': 1})
        ids, path, _ = self.workbook(headers)
        first, = self.tick(M90)['triggeredNotifications']
        self.configure(headers, path, '2027-02-25')
        second, = self.tick(M90)['triggeredNotifications']
        expected = self.get_notifications(headers, path)
        self.assertEqual([row['notificationId'] for row in expected], [first, second])
        self.assertEqual([row['status'] for row in expected], ['FAILED', 'DELIVERED'])
        for row in expected:
            self.assertEqual(set(row), {'notificationId', 'type', 'workbookId', 'versionId',
                                        'scheduledFor', 'status', 'message'})
            self.assertEqual(row['scheduledFor'], M90)
            self.assertEqual(row['workbookId'], ids['workbookId'])
            self.assertEqual(row['versionId'], ids['versionId'])
            self.assertEqual(row['type'], 'COMPLIANCE_DEADLINE_REMINDER')
            self.assertTrue(1 <= len(row['message']) <= 500)
        considered = self.rows('p5_reminder_considered')
        self.app = create_app(
            self.app.state.database.path, {'a': 'owner', 'b': 'other'},
            enable_test_interface=True, test_admin_tokens={'admin': 'administrator'},
            test_session_users={'administrator': ['owner', 'other']},
        )
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)
        self.assertEqual(self.get_notifications(headers, path), expected)
        self.assertEqual(self.rows('p5_reminder_considered'), considered)
        self.assertEqual(self.tick(M90)['triggeredNotifications'], [])
        self.configure(headers, path)
        self.assertEqual(self.tick(M90)['triggeredNotifications'], [])
        self.assertEqual(self.get_notifications(headers, path), expected)

    def test_clock_returns_notification_ids_in_threshold_and_workbook_order(self):
        headers = self.prepare()
        workbooks = [self.workbook(headers) for _ in range(2)]
        ids = self.tick('2027-04-20T00:00:00Z')['triggeredNotifications']
        notifications = [row for _, path, _ in workbooks for row in self.get_notifications(headers, path)]
        expected = sorted(notifications, key=lambda row: (row['scheduledFor'], row['workbookId']))
        self.assertEqual(len(expected), 6)
        self.assertEqual(ids, [row['notificationId'] for row in expected])

    def test_delete_fault_preserves_rows_and_success_deletes_only_target(self):
        headers = self.prepare(faults={'deletion_failures': 1})
        ids, path, _ = self.workbook(headers)
        _, keep, _ = self.workbook(headers)
        self.tick(M90)
        original = self.snapshot()
        self.assert_error(self.client.delete(path, headers=headers), 500, 'TEST_DELETION_FAILURE')
        for table in ('p5_notifications', 'p5_reminder_considered'):
            self.assertEqual(self.rows(table), original[table])
        self.assertEqual(len(self.get_notifications(headers, path)), 1)
        remaining = self.get_notifications(headers, keep)
        self.assertEqual(self.client.delete(path, headers=headers).status_code, 204)
        self.assert_error(self.client.get(path + '/notifications', headers=headers), 404, 'NOT_FOUND')
        self.assertEqual(self.get_notifications(headers, keep), remaining)
        for table in ('p5_notifications', 'p5_reminder_considered'):
            self.assertEqual(self.rows(table), [row for row in original[table]
                                                if row['workbook_id'] != ids['workbookId']])

    def test_session_cleanup_keeps_other_namespace_rows(self):
        remove = self.prepare('remove')
        keep = self.prepare('keep')
        self.workbook(remove)
        # A suppressed occurrence also has to be removed by cleanup.
        self.workbook(remove, clean=True)
        _, path, _ = self.workbook(keep)
        self.tick(M90, 'remove')
        self.tick(M90, 'keep')
        self.assertEqual(len(self.rows('p5_reminder_considered')), 3)
        remaining = self.get_notifications(keep, path)
        original = self.snapshot()
        self.prepare('cleanup', cleanup_session_ids=['remove'])
        self.assertEqual(self.get_notifications(keep, path), remaining)
        for table in ('p5_notifications', 'p5_reminder_considered'):
            self.assertEqual(self.rows(table), [row for row in original[table] if row['namespace'] == 'keep'])
