"""REQ-12 / AC-12 / AC-13. P5-LOCAL-SCHEDULER-TICK, P5-LOCAL-SCHEDULER-RESTART,
P5-DELETE-CANCEL-FUTURE.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import os
import sqlite3
import threading
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import create_app
from database import Database
from phase4_store import Store
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

    def test_restart_and_concurrent_store_ticks_claim_durable_occurrences_once(self):
        _, path = self.configured()
        db_path = self.app.state.database.path
        # Simulate a restart after missing multiple intervals, then race two independent stores.
        stores = [Store(Database(db_path)), Store(Database(db_path))]
        barrier = threading.Barrier(2, timeout=5)

        def concurrent_tick(store):
            barrier.wait()
            return scheduler.tick(store)

        instant = '2027-01-04T12:00:00Z'
        with patch.object(scheduler, 'datetime', wraps=datetime) as clock, ThreadPoolExecutor(2) as pool:
            clock.now.return_value = datetime.fromisoformat(instant)
            futures = [pool.submit(concurrent_tick, store) for store in stores]
            results = [future.result(timeout=10) for future in futures]
        self.assertEqual(sorted((len(audits), len(notifications)) for audits, notifications in results),
                         [(0, 0), (1, 1)])
        self.assertEqual(self.schedule(OWNER, path)['nextAuditAt'], '2027-01-05T00:00:00Z')
        self.assertEqual(self.tick_at(instant, Store(Database(db_path))), ([], []))

    def test_lifespan_starts_scheduler_with_configured_interval_and_joins_it(self):
        _, path = self.configured()
        started = threading.Event()
        threads = []
        run = scheduler.run_scheduler

        def observe_loop(store, stop, interval):
            threads.append(threading.current_thread())
            run(store, stop, interval)

        original_tick = scheduler.tick

        def observe_tick(store):
            result = original_tick(store)
            started.set()
            return result

        db_path = self.app.state.database.path
        with patch.dict(os.environ, {'SCHEDULER_INTERVAL_SECONDS': '0.05'}):
            app = create_app(db_path, {'a': 'owner'})
        with (patch.object(scheduler, 'run_scheduler', side_effect=observe_loop) as loop,
              patch.object(scheduler, 'tick', side_effect=observe_tick),
              patch.object(scheduler, 'datetime', wraps=datetime) as clock):
            clock.now.return_value = datetime.fromisoformat(DUE)
            with TestClient(app) as client:
                self.assertTrue(started.wait(5), 'No tick within five seconds of startup.')
                self.assertTrue(threads[0].is_alive())
                result = client.get(path + '/notifications', headers=OWNER)
                self.assertEqual(result.status_code, 200, result.text)
                self.assertEqual(len(result.json()['notifications']), 1)
                self.assertEqual(loop.call_args.args[2], 0.05)
            self.assertFalse(threads[0].is_alive())

    def test_lifespan_can_disable_scheduler(self):
        app = create_app(self.app.state.database.path, {'a': 'owner'}, enable_scheduler=False)
        with patch.object(scheduler, 'run_scheduler') as loop:
            with TestClient(app) as client:
                self.assertEqual(client.get('/api/v1/health').status_code, 200)
            loop.assert_not_called()

    def test_loop_recovers_after_tick_exception_and_logs_safe_fields(self):
        store = self.app.state.store
        stop = threading.Event()

        def attempt(*args, **kwargs):
            if dispatch.call_count == 1:
                raise sqlite3.OperationalError('private details')
            stop.set()
            return [], []

        with (patch.object(scheduler, 'dispatch_work', side_effect=attempt) as dispatch,
              self.assertLogs('phase5_scheduler', level='ERROR') as logs):
            scheduler.run_scheduler(store, stop, 0.001)
        self.assertEqual(dispatch.call_count, 2)
        self.assertIn('error_type=OperationalError', logs.output[0])
        self.assertNotIn('private details', logs.output[0])

    def test_interval_defaults_to_one_second_and_rejects_invalid_values(self):
        with patch.dict(os.environ, clear=True):
            self.assertEqual(scheduler.interval_seconds(), 1)
        for value in ('NaN', 'inf', '0', '-1', '6', 'invalid'):
            with self.subTest(value=value), patch.dict(os.environ, {'SCHEDULER_INTERVAL_SECONDS': value}):
                with self.assertRaisesRegex(ValueError, 'SCHEDULER_INTERVAL_SECONDS'):
                    scheduler.interval_seconds()
