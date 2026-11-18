"""REQ-12 / AC-12 / AC-13. P5-LOCAL-SCHEDULER-TICK, P5-LOCAL-SCHEDULER-RESTART,
P5-DELETE-CANCEL-FUTURE.
"""
from datetime import datetime
import unittest
from unittest.mock import patch

import phase5_scheduler as scheduler
import test_phase5_dispatch as dispatch_tests

START = dispatch_tests.START
DUE = dispatch_tests.DUE
OWNER = dispatch_tests.OWNER
DEADLINE = '2027-04-02'


class SchedulerTests(unittest.TestCase):
    setUp = dispatch_tests.DispatchTests.setUp
    prepare = dispatch_tests.DispatchTests.prepare
    upload = dispatch_tests.DispatchTests.upload
    schedule = dispatch_tests.DispatchTests.schedule
    assert_error = dispatch_tests.DispatchTests.assert_error

    def configured(self, headers=OWNER, *, deadline=DEADLINE):
        ids, version = self.upload(headers)
        path = version.rsplit('/versions/', 1)[0]
        with patch('phase5_schedule.effective_now', return_value=datetime.fromisoformat(START)):
            response = self.client.put(path + '/schedule', headers=headers, json={
                'enabled': True, 'intervalDays': 1, 'complianceDeadline': deadline,
            })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['nextAuditAt'], DUE)
        return ids, path

    def tick_at(self, instant, store=None):
        with patch.object(scheduler, 'datetime', wraps=datetime) as clock:
            clock.now.return_value = datetime.fromisoformat(instant)
            return scheduler.tick(store if store is not None else self.app.state.store)

    def test_tick_before_due_then_coalesces_and_records_a_notification(self):
        _, path = self.configured()
        self.assertEqual(self.tick_at('2027-01-01T23:59:59.999999Z'), ([], []))
        instant = '2027-01-04T12:00:00Z'
        with self.assertLogs('phase5_scheduler', level='INFO') as logs:
            audits, notifications = self.tick_at(instant)
        self.assertEqual(len(audits), 1)
        self.assertEqual(len(notifications), 1)
        self.assertIn('accepted_audits=1 recorded_notifications=1 dispatch_lag_seconds=216000.0',
                      logs.output[0])
        self.assertEqual(self.schedule(OWNER, path)['nextAuditAt'], '2027-01-05T00:00:00Z')
        response = self.client.get(path + '/notifications', headers=OWNER)
        self.assertEqual(response.status_code, 200, response.text)
        record, = response.json()['notifications']
        self.assertEqual((record['notificationId'], record['status'], record['scheduledFor']),
                         (notifications[0], 'DELIVERED', DUE))
        self.assertEqual(self.tick_at(instant), ([], []))

    def test_tick_ignores_virtual_and_legacy_test_namespaces(self):
        virtual = self.prepare('virtual')
        legacy = self.prepare('legacy')
        _, virtual_path = self.configured(virtual)
        _, legacy_path = self.configured(legacy)
        with self.app.state.store.connect(write=True) as db:
            db.execute("DELETE FROM p5_clocks WHERE session_id='legacy'")
        self.assertEqual(self.tick_at(DUE), ([], []))
        self.assertEqual(self.schedule(virtual, virtual_path)['nextAuditAt'], DUE)
        self.assertEqual(self.schedule(legacy, legacy_path)['nextAuditAt'], DUE)

    def test_busy_version_stays_due_and_next_tick_accepts_after_completion(self):
        with patch.object(self.runner, 'drain'):
            _, path = self.configured(deadline=None)
        self.assertEqual(self.tick_at(DUE), ([], []))
        self.assertEqual(self.schedule(OWNER, path)['nextAuditAt'], DUE)
        self.runner.drain()
        audits, notifications = self.tick_at(DUE)
        self.assertEqual(len(audits), 1)
        self.assertEqual(notifications, [])
        self.assertEqual(self.schedule(OWNER, path)['nextAuditAt'], '2027-01-03T00:00:00Z')

    def test_delete_prevents_future_work_and_rejects_pending_scheduled_audit(self):
        _, deleted = self.configured()
        _, accepted = self.configured()
        self.assertEqual(self.client.delete(deleted, headers=OWNER).status_code, 204)
        audits, notifications = self.tick_at(DUE)
        self.assertEqual((len(audits), len(notifications)), (1, 1))
        self.assert_error(self.client.delete(accepted, headers=OWNER), 409, 'ACTIVE_OPERATION')
        self.runner.drain()
        self.assertEqual(self.client.delete(accepted, headers=OWNER).status_code, 204)
        self.assertEqual(self.tick_at('2027-06-01T00:00:00Z'), ([], []))
        with self.app.state.store.connect() as db:
            for table in ('p4_jobs', 'p5_notifications', 'p5_reminder_considered'):
                self.assertEqual(db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0], 0)
