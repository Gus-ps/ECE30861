"""REQ-14 / AC-16. P5-DELETE-RECOVER, P5-LOCAL-DELETE-RESTART,
P5-DELETE-RACE, P5-DELETE-CANCEL-FUTURE and P5-DELETE-RESTORE.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime
import hashlib
import json
import os
import sqlite3
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from botocore.exceptions import ClientError
from fastapi.testclient import TestClient
from app import create_app, load_workbook_validator
from database import Database
import phase5_deletion as deletion
import phase5_scheduler as scheduler
from test_phase4_service import workbook

OWNER = {'Authorization': 'Bearer a'}
SIDE = dict(OWNER, **{'X-Test-Session': 'side'})


class FakeS3:
    """In-memory bucket; lists one key per page so pagination is exercised."""
    def __init__(self):
        self.objects, self.fail_puts = {}, 0

    def put_object(self, Bucket, Key, Body):
        if self.fail_puts:
            self.fail_puts -= 1
            raise ClientError({'Error': {'Code': 'InternalError', 'Message': 'sensitive'}}, 'PutObject')
        self.objects[Key] = Body

    def get_paginator(self, name):
        assert name == 'list_objects_v2'
        return self

    def paginate(self, Bucket, Prefix):
        return [{'Contents': [{'Key': key}]} for key in sorted(self.objects) if key.startswith(Prefix)] or [{}]


class DeleteWorkbookTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'service.sqlite3'

    def start(self, validator=None):
        app = create_app(self.path, {'a': 'owner'}, workbook_validator=validator, enable_test_interface=True,
                         test_admin_tokens={'admin': 'administrator'}, test_session_users={'administrator': ['owner']})
        client = TestClient(app); self.addCleanup(client.close)
        return app, client

    def snapshot(self, app):
        with app.state.database.connect() as db:
            return [[tuple(r) for r in db.execute(f'SELECT * FROM {t} ORDER BY 1')] for t in ('p4_resources', 'p4_keys', 'p4_jobs')]

    def assert_refused(self, app, client, wb, base):
        before = self.snapshot(app)
        response = client.delete(wb, headers=OWNER)
        self.assertEqual((response.status_code, response.json()['code']), (409, 'ACTIVE_OPERATION'))
        self.assertEqual(self.snapshot(app), before)
        self.assertEqual(client.get(base + '/source', headers=OWNER).status_code, 200)

    def upload(self, client, headers=OWNER):
        response = client.post('/api/v1/workbooks', headers=headers, files={'file': ('book.xlsx', workbook())})
        self.assertEqual(response.status_code, 202, response.text)
        return response.json()

    def test_delete_removes_the_workbook_and_nothing_else(self):
        app, client = self.start()
        self.assertEqual(client.post('/test/setup', headers={'Authorization': 'Bearer admin'},
                                     json={'session_id': 'side'}).status_code, 201)
        up = self.upload(client)
        schedules = {}
        for record, headers in ((up, OWNER), (self.upload(client), OWNER), (self.upload(client, SIDE), SIDE)):
            path = f"/api/v1/workbooks/{record['workbookId']}/schedule"
            configured = client.put(path, headers=headers, json={'enabled': True, 'intervalDays': 7})
            self.assertEqual(configured.status_code, 200, configured.text)
            schedules[path] = (headers, configured.json())
        wb = '/api/v1/workbooks/' + up['workbookId']
        base = f"{wb}/versions/{up['versionId']}"
        finding = client.get(base + '/audits/' + up['auditId'], headers=OWNER).json()['findings'][0]
        body = {'auditId': up['auditId'], 'decisions': [{'findingId': finding['findingId'], 'action': 'DECLINE'}]}
        rem = client.post(base + '/remediations', headers=dict(OWNER, **{'Idempotency-Key': 'k'}), json=body).json()
        job = client.get('/api/v1/remediations/' + rem['remediationId'], headers=OWNER).json()
        out = f"{wb}/versions/{job['outputVersionId']}"
        urls = [base, base + '/source', base + '/audits/' + up['auditId'], base + '/audits/' + up['auditId'] + '/review',
                base + '/audits/' + up['auditId'] + '/report', out, out + '/audits/' + job['auditId'] + '/report',
                '/api/v1/remediations/' + rem['remediationId'], '/api/v1/outputs/' + job['outputId'] + '/workbook',
                wb + '/history', wb + '/schedule']
        for url in urls:
            self.assertEqual(client.get(url, headers=OWNER).status_code, 200, url)
        with app.state.database.connect() as db:
            others = [tuple(r) for r in db.execute('SELECT * FROM p4_resources WHERE workbook_id<>? ORDER BY seq', (up['workbookId'],))]
            sessions = [tuple(r) for r in db.execute('SELECT * FROM test_sessions')]
        self.assertEqual({r[6] for r in others}, {None, 'side'})  # another ordinary workbook and one in another namespace

        response = client.delete(wb, headers=OWNER)
        self.assertEqual((response.status_code, response.content), (204, b''))
        for url in urls:
            self.assertEqual(client.get(url, headers=OWNER).status_code, 404, url)
        self.assertEqual(client.put(wb + '/schedule', headers=OWNER, json={'enabled': False}).status_code, 404)
        del schedules[wb + '/schedule']
        for path, (headers, schedule) in schedules.items():
            response = client.get(path, headers=headers)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json(), schedule)
        self.assertEqual(client.post(base + '/audits', headers=OWNER, json={}).status_code, 404)
        self.assertEqual(client.post(wb + '/versions', headers=OWNER, files={'file': ('b.xlsx', workbook())}).status_code, 404)
        self.assertEqual(client.post(base + '/remediations', headers=dict(OWNER, **{'Idempotency-Key': 'k'}), json=body).status_code, 404)
        self.assertEqual(client.delete(wb, headers=OWNER).status_code, 404)
        with app.state.database.connect() as db:
            for table in ('p4_resources', 'p4_keys', 'p5_schedules'):
                self.assertEqual(db.execute(f'SELECT COUNT(*) FROM {table} WHERE workbook_id=?', (up['workbookId'],)).fetchone()[0], 0)
            jobs = db.execute('SELECT COUNT(*) FROM p4_jobs WHERE version_id IN (?,?)', (up['versionId'], job['outputVersionId'])).fetchone()[0]
            self.assertEqual(jobs, 0)
            self.assertEqual([tuple(r) for r in db.execute('SELECT * FROM p4_resources ORDER BY seq')], others)
            self.assertEqual([tuple(r) for r in db.execute('SELECT * FROM test_sessions')], sessions)
        operation = client.get('/openapi.json').json()['paths']['/api/v1/workbooks/{workbook_id}']['delete']
        self.assertLessEqual({'204', '401', '403', '404'}, set(operation['responses']))

    def test_delete_refused_during_active_audit_and_remediation(self):
        app, client = self.start(); runner = app.state.runner
        with patch.object(runner, 'drain'):  # leave the audit job PENDING
            up = self.upload(client)
        wb = '/api/v1/workbooks/' + up['workbookId']; base = f"{wb}/versions/{up['versionId']}"
        with self.subTest('audit'):
            self.assert_refused(app, client, wb, base)
        runner.drain()
        finding = client.get(base + '/audits/' + up['auditId'], headers=OWNER).json()['findings'][0]
        body = {'auditId': up['auditId'], 'decisions': [{'findingId': finding['findingId'], 'action': 'DECLINE'}]}
        with patch.object(runner, 'drain'):
            accepted = client.post(base + '/remediations', headers=dict(OWNER, **{'Idempotency-Key': 'k'}), json=body)
        self.assertEqual(accepted.status_code, 202, accepted.text)
        with self.subTest('remediation'):
            self.assert_refused(app, client, wb, base)
        runner.drain()
        self.assertEqual(client.delete(wb, headers=OWNER).status_code, 204)

    def test_delete_refused_during_upload_staging(self):
        real, target, seen = load_workbook_validator(), [], []

        def validator(path):  # runs while Op 3 holds its staging reservation
            if target:
                seen.append(client.delete(target[0], headers=OWNER))
            return real(path)
        app, client = self.start(validator)
        up = self.upload(client); wb = '/api/v1/workbooks/' + up['workbookId']
        target.append(wb)
        response = client.post(wb + '/versions', headers=OWNER, files={'file': ('next.xlsx', workbook())})
        self.assertEqual(response.status_code, 202, response.text)
        self.assertEqual((seen[0].status_code, seen[0].json()['code']), (409, 'ACTIVE_OPERATION'))
        target.clear()
        with app.state.database.connect(write=True) as db:  # an expired reservation no longer blocks
            db.execute('INSERT INTO p5_upload_reservations VALUES (?,?,?)', ('stale', up['workbookId'], time.time() - 1))
        self.assertEqual(client.delete(wb, headers=OWNER).status_code, 204)

    def test_delete_racing_writes_has_one_consistent_winner(self):
        app, client = self.start()
        for attempt in range(5):
            up = self.upload(client)
            wb = '/api/v1/workbooks/' + up['workbookId']; base = f"{wb}/versions/{up['versionId']}"
            calls = {'delete': lambda: client.delete(wb, headers=OWNER),
                     'reaudit': lambda: client.post(base + '/audits', headers=OWNER, json={}),
                     'version': lambda: client.post(wb + '/versions', headers=OWNER, files={'file': ('n.xlsx', workbook())})}
            barrier, results = threading.Barrier(len(calls)), {}

            def run(name):
                barrier.wait(); results[name] = calls[name]().status_code
            threads = [threading.Thread(target=run, args=(n,)) for n in calls]
            for thread in threads: thread.start()
            for thread in threads: thread.join()
            app.state.runner.drain()
            with self.subTest(attempt=attempt, results=results), app.state.database.connect() as db:
                self.assertIn(results['delete'], (204, 409))
                self.assertLessEqual({results['reaudit'], results['version']}, {202, 404})
                left = db.execute('SELECT COUNT(*) FROM p4_resources WHERE workbook_id=?', (up['workbookId'],)).fetchone()[0]
                self.assertEqual(left == 0, results['delete'] == 204)
                orphans = db.execute('SELECT COUNT(*) FROM p4_jobs WHERE version_id NOT IN (SELECT id FROM p4_resources)').fetchone()[0]
                self.assertEqual(orphans, 0)

    def test_delete_racing_schedule_put_leaves_no_schedule(self):
        app, client = self.start()
        for attempt in range(5):
            workbook_id = self.upload(client)['workbookId']
            wb = f'/api/v1/workbooks/{workbook_id}'
            barrier = threading.Barrier(2, timeout=10)

            def put():
                barrier.wait()
                return client.put(wb + '/schedule', headers=OWNER,
                                  json={'enabled': True, 'intervalDays': 7})

            def delete():
                barrier.wait()
                return client.delete(wb, headers=OWNER)

            with ThreadPoolExecutor(max_workers=2) as executor:
                put_result = executor.submit(put)
                delete_result = executor.submit(delete)
                put_response = put_result.result()
                delete_response = delete_result.result()
            with self.subTest(attempt=attempt), app.state.database.connect() as db:
                self.assertEqual(delete_response.status_code, 204, delete_response.text)
                self.assertIn(put_response.status_code, (200, 404), put_response.text)
                row = db.execute('SELECT 1 FROM p5_schedules WHERE workbook_id=?',
                                 (workbook_id,)).fetchone()
                self.assertIsNone(row)

    def test_delete_removes_legacy_phase3_rows(self):
        database = Database(self.path); database.initialize()
        data = workbook()
        with database.connect(write=True) as db:
            db.execute('INSERT INTO versions VALUES (?,?,?,?,?,?,?)', ('old-wb', 'old-v', 'owner', 'old.xlsx',
                       hashlib.sha256(data).hexdigest(), '2026-10-18T00:00:00Z', data))
            db.execute('''INSERT INTO audits (audit_id,workbook_id,version_id,ruleset_version,status,started_at,completed_at,request_id)
                VALUES ('old-a','old-wb','old-v','1.0.0','AUDIT_COMPLETE','2026-10-18T00:00:00Z','2026-10-18T00:00:01Z','old-request')''')
        app, client = self.start()
        self.assertEqual(client.delete('/api/v1/workbooks/old-wb', headers=OWNER).status_code, 204)
        with app.state.database.connect() as db:
            for table in ('versions', 'audits', 'p4_resources'):
                self.assertEqual(db.execute(f"SELECT COUNT(*) FROM {table} WHERE workbook_id='old-wb'").fetchone()[0], 0)


    def fail_after_first_step(self, client, path, headers=OWNER):
        original = deletion.delete_step

        def fail(db, workbook_id, table):
            if table == 'p4_keys':
                raise OSError('simulated failure after committed job deletion')
            original(db, workbook_id, table)

        with patch.object(deletion, 'delete_step', side_effect=fail), self.assertLogs(level='ERROR'):
            response = client.delete(path, headers=headers)
        self.assertEqual((response.status_code, response.json()['code']), (500, 'DELETION_FAILED'))

    def test_partial_delete_hides_resources_and_owner_retry_finishes(self):
        app, client = self.start()
        up = self.upload(client)
        wid, vid = up['workbookId'], up['versionId']
        path = f'/api/v1/workbooks/{wid}'
        version = f'{path}/versions/{vid}'
        self.fail_after_first_step(client, path)
        with app.state.store.connect() as db:
            row = deletion.reservation(db, wid)
            self.assertEqual(set(row.keys()), {'workbook_id', 'owner', 'namespace', 'created'})
            self.assertEqual(row['owner'], 'owner')
            self.assertIsNone(db.execute('SELECT 1 FROM p4_jobs WHERE version_id=?', (vid,)).fetchone())
            self.assertIsNotNone(app.state.store.get(db, vid))
        for suffix in ('/source', f"/audits/{up['auditId']}", f"/audits/{up['auditId']}/report"):
            self.assertEqual(client.get(version + suffix, headers=OWNER).status_code, 404, suffix)
        for url in (path + '/history', path + '/schedule', path + '/notifications'):
            self.assertEqual(client.get(url, headers=OWNER).status_code, 404, url)
        self.assertEqual(client.put(path + '/schedule', headers=OWNER, json={'enabled': False}).status_code, 404)
        self.assertEqual(client.post(path + '/versions', headers=OWNER,
                                     files={'file': ('book.xlsx', workbook())}).status_code, 404)
        foreign_app = create_app(self.path, {'b': 'foreign'}, enable_scheduler=False)
        foreign = TestClient(foreign_app)  # Do not run startup recovery yet.
        self.addCleanup(foreign.close)
        foreign_headers = {'Authorization': 'Bearer b'}
        self.assertEqual(foreign.get(version + '/source', headers=foreign_headers).status_code, 404)
        self.assertEqual(foreign.delete(path, headers=foreign_headers).status_code, 404)
        self.assertEqual(client.delete(path, headers=OWNER).status_code, 204)
        self.assertEqual(client.delete(path, headers=OWNER).status_code, 404)
        with app.state.store.connect() as db:
            self.assertIsNone(deletion.reservation(db, wid))
            self.assertIsNone(app.state.store.get(db, vid))

    def test_startup_finishes_an_interrupted_deletion(self):
        app, client = self.start()
        up = self.upload(client)
        path = f"/api/v1/workbooks/{up['workbookId']}"
        self.fail_after_first_step(client, path)
        new_app, restarted = self.start()
        with restarted:
            self.assertEqual(restarted.get(path + '/history', headers=OWNER).status_code, 404)
            with new_app.state.store.connect() as db:
                self.assertIsNone(deletion.reservation(db, up['workbookId']))
                self.assertIsNone(new_app.state.store.get(db, up['versionId']))

    def test_delete_deadline_retains_reservation_for_retry(self):
        app, client = self.start()
        up = self.upload(client)
        path = f"/api/v1/workbooks/{up['workbookId']}"
        entered, release, ended = threading.Event(), threading.Event(), threading.Event()
        original = deletion.delete_step

        def slow_step(db, workbook_id, table):
            entered.set()
            try:
                if not release.wait(5):
                    raise TimeoutError()
                original(db, workbook_id, table)
            finally:
                ended.set()

        with (client, patch.object(deletion, 'DELETE_SECONDS', 0.3),
              patch.object(deletion, 'delete_step', side_effect=slow_step)):
            try:
                response = client.delete(path, headers=OWNER)
                self.assertTrue(entered.is_set())
                self.assertEqual((response.status_code, response.json()['code']), (500, 'DELETION_FAILED'))
            finally:
                release.set()
            self.assertTrue(ended.wait(5))
        with app.state.store.connect() as db:
            self.assertIsNotNone(deletion.reservation(db, up['workbookId']))
        self.assertEqual(client.delete(path, headers=OWNER).status_code, 204)


    def test_clock_blocks_only_namespace_with_pending_deletion(self):
        with patch.dict(os.environ, {'ENABLE_TEST_CLOCK': 'true'}):
            app, client = self.start()
        admin = {'Authorization': 'Bearer admin'}
        for name in ('side', 'other'):
            self.assertEqual(client.post('/test/setup', headers=admin, json={'session_id': name}).status_code, 201)
        up = self.upload(client, SIDE)
        path = f"/api/v1/workbooks/{up['workbookId']}"
        self.assertEqual(client.put(path + '/schedule', headers=SIDE,
                                    json={'enabled': True, 'intervalDays': 1}).status_code, 200)
        self.fail_after_first_step(client, path, SIDE)
        with app.state.store.connect() as db:
            before = tuple(db.execute('SELECT * FROM p5_schedules').fetchone())
        target = {'currentTime': '2027-01-03T00:00:00Z'}
        rejected = client.post('/api/v1/test/clock', headers={**admin, 'X-Test-Session': 'side'}, json=target)
        self.assertEqual((rejected.status_code, rejected.json()['code']), (409, 'DELETION_IN_PROGRESS'))
        other = client.post('/api/v1/test/clock', headers={**admin, 'X-Test-Session': 'other'}, json=target)
        self.assertEqual(other.status_code, 200, other.text)
        with app.state.store.connect() as db:
            self.assertEqual(db.execute('SELECT "current_time" FROM p5_clocks WHERE session_id=?',
                                        ('side',)).fetchone()[0], '2027-01-01T00:00:00Z')
            self.assertEqual(tuple(db.execute('SELECT * FROM p5_schedules').fetchone()), before)

    def test_real_tick_skips_reserved_workbook_with_a_due_audit_and_reminder(self):
        app, client = self.start()
        up = self.upload(client)
        path = f"/api/v1/workbooks/{up['workbookId']}"
        with patch('phase5_schedule.effective_now', return_value=datetime.fromisoformat('2027-01-01T00:00:00Z')):
            self.assertEqual(client.put(path + '/schedule', headers=OWNER, json={
                'enabled': True, 'intervalDays': 1, 'complianceDeadline': '2027-04-02',
            }).status_code, 200)
        self.fail_after_first_step(client, path)
        with patch.object(scheduler, 'datetime', wraps=datetime) as clock:
            clock.now.return_value = datetime.fromisoformat('2027-01-02T00:00:00Z')
            self.assertEqual(scheduler.tick(app.state.store), ([], []))
        with app.state.store.connect() as db:
            self.assertEqual(db.execute('SELECT next_audit_at FROM p5_schedules').fetchone()[0],
                             '2027-01-02T00:00:00Z')
            self.assertEqual(db.execute('SELECT COUNT(*) FROM p4_jobs').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM p5_notifications').fetchone()[0], 0)

    def test_cleanup_completes_pending_namespace_deletion_between_steps(self):
        app, client = self.start()
        admin = {'Authorization': 'Bearer admin'}
        self.assertEqual(client.post('/test/setup', headers=admin, json={'session_id': 'side'}).status_code, 201)
        up = self.upload(client, SIDE)
        other = self.upload(client)
        path = f"/api/v1/workbooks/{up['workbookId']}"
        entered, proceed = threading.Event(), threading.Event()
        original = deletion.commit_step

        def paused(store, workbook_id, table, deadline):
            result = original(store, workbook_id, table, deadline)
            if table == 'p4_jobs':
                entered.set()
                if not proceed.wait(5):
                    raise TimeoutError('Cleanup did not finish.')
            return result

        with patch.object(deletion, 'commit_step', side_effect=paused), ThreadPoolExecutor(1) as pool:
            future = pool.submit(client.delete, path, headers=SIDE)
            try:
                self.assertTrue(entered.wait(5))
                response = client.post('/test/setup', headers=admin, json={
                    'session_id': 'cleanup', 'setup': {'cleanup_session_ids': ['side']},
                })
                self.assertEqual(response.status_code, 201, response.text)
            finally:
                proceed.set()
            self.assertEqual(future.result(timeout=5).status_code, 204)
        with app.state.store.connect() as db:
            self.assertIsNone(deletion.reservation(db, up['workbookId']))
            self.assertIsNone(app.state.store.get(db, up['versionId']))
            self.assertIsNotNone(app.state.store.get(db, other['versionId']))

    def with_ledger(self, path):
        with patch.dict(os.environ, {'DELETION_LEDGER_PATH': str(path)}):
            return self.start()

    def test_ledger_is_synced_after_reservation_before_first_step(self):
        ledger = Path(self.temp.name) / 'deletions.jsonl'
        app, client = self.with_ledger(ledger)
        up = self.upload(client)
        wid = up['workbookId']
        path = f'/api/v1/workbooks/{wid}'
        original = deletion.commit_step
        recorded = []

        def observe(store, workbook_id, table, deadline):
            if table == 'p4_jobs':
                with store.connect() as db:
                    row = deletion.reservation(db, wid)
                    self.assertIsNotNone(row)
                    record, = [json.loads(line) for line in ledger.read_text().splitlines()]
                    self.assertEqual(record, {'workbook_id': wid, 'timestamp': row['created']})
                    recorded.append(record)
            return original(store, workbook_id, table, deadline)

        with patch.object(deletion, 'commit_step', side_effect=observe), patch.object(
                deletion.os, 'fsync', wraps=os.fsync) as sync:
            self.assertEqual(client.delete(path, headers=OWNER).status_code, 204)
        self.assertEqual(len(recorded), 1)
        self.assertGreaterEqual(sync.call_count, 1)

    def test_ledger_sync_failure_retains_reservation_and_retry_deduplicates(self):
        ledger = Path(self.temp.name) / 'deletions.jsonl'
        app, client = self.with_ledger(ledger)
        up = self.upload(client)
        wid = up['workbookId']
        path = f'/api/v1/workbooks/{wid}'
        with patch.object(deletion.os, 'fsync', side_effect=OSError('sensitive path')), self.assertLogs(level='ERROR') as logs:
            response = client.delete(path, headers=OWNER)
        self.assertEqual((response.status_code, response.json()['code']), (500, 'DELETION_FAILED'))
        self.assertNotIn('sensitive path', ' '.join(logs.output))
        with app.state.store.connect() as db:
            self.assertIsNotNone(deletion.reservation(db, wid))
            self.assertIsNotNone(app.state.store.get(db, up['versionId']))
        self.assertEqual(client.delete(path, headers=OWNER).status_code, 204)
        self.assertEqual(len(ledger.read_text().splitlines()), 1)

    def test_restart_reapplies_ledger_after_sqlite_restore(self):
        ledger = Path(self.temp.name) / 'deletions.jsonl'
        backup = Path(self.temp.name) / 'backup.sqlite3'
        app, client = self.with_ledger(ledger)
        up = self.upload(client)
        other = self.upload(client)
        path = f"/api/v1/workbooks/{up['workbookId']}"
        with closing(sqlite3.connect(self.path)) as live, closing(sqlite3.connect(backup)) as archive:
            live.backup(archive)
        self.assertEqual(client.delete(path, headers=OWNER).status_code, 204)
        before = ledger.read_bytes()
        with closing(sqlite3.connect(self.path)) as live, closing(sqlite3.connect(backup)) as archive:
            archive.backup(live)
        app, restarted = self.with_ledger(ledger)
        with restarted:
            self.assertEqual(restarted.get(path + '/history', headers=OWNER).status_code, 404)
            with app.state.store.connect() as db:
                self.assertIsNone(app.state.store.get(db, up['versionId']))
                self.assertIsNone(deletion.reservation(db, up['workbookId']))
                self.assertIsNotNone(app.state.store.get(db, other['versionId']))
        self.assertEqual(ledger.read_bytes(), before)

    def test_startup_creates_missing_ledger_and_discards_only_torn_tail(self):
        ledger = Path(self.temp.name) / 'deletions.jsonl'
        _, client = self.with_ledger(ledger)
        self.assertFalse(ledger.exists())
        with client:
            self.assertEqual(ledger.read_bytes(), b'')
        complete = b'{"workbook_id":"unrelated","timestamp":"2027-01-01T00:00:00Z"}\n'
        ledger.write_bytes(complete + b'{"workbook_id":"sensitive-fragment')
        _, restarted = self.with_ledger(ledger)
        with self.assertLogs('phase5_deletion', level='WARNING') as logs, restarted:
            self.assertEqual(ledger.read_bytes(), complete)
        self.assertIn('line=2', logs.output[0])
        self.assertNotIn('sensitive-fragment', logs.output[0])

    def test_startup_rejects_corrupt_complete_rows_and_unreadable_paths(self):
        ledger = Path(self.temp.name) / 'deletions.jsonl'
        valid = b'{"workbook_id":"unrelated","timestamp":"2027-01-01T00:00:00Z"}\n'
        for path, line in ((ledger, 2), (ledger.parent, 0)):
            with self.subTest(line=line):
                ledger.write_bytes(valid + b'{"owner":"private"}\n')
                _, client = self.with_ledger(path)
                with (self.assertRaisesRegex(RuntimeError, 'Deletion ledger is unavailable or invalid'),
                      self.assertLogs('phase5_deletion', level='ERROR') as logs):
                    with client:
                        self.fail('The service started with an invalid ledger.')
                self.assertIn(f'line={line}', logs.output[0])
                self.assertNotIn('private', logs.output[0])
                self.assertNotIn(str(ledger), logs.output[0])

    def test_no_ledger_warns_and_sqlite_connections_securely_delete(self):
        with patch.dict(os.environ, {'DELETION_LEDGER_PATH': ''}):
            app, client = self.start()
        with self.assertLogs('phase5_deletion', level='WARNING') as logs, client:
            self.assertEqual(client.get('/api/v1/health').status_code, 200)
            with app.state.database.connect() as db:
                self.assertEqual(db.execute('PRAGMA secure_delete').fetchone()[0], 1)
        self.assertIn('DELETION_LEDGER_PATH', logs.output[0])

    def test_session_cleanup_preserves_an_existing_ledger_entry(self):
        ledger = Path(self.temp.name) / 'deletions.jsonl'
        app, client = self.with_ledger(ledger)
        admin = {'Authorization': 'Bearer admin'}
        self.assertEqual(client.post('/test/setup', headers=admin, json={'session_id': 'side'}).status_code, 201)
        up = self.upload(client, SIDE)
        path = f"/api/v1/workbooks/{up['workbookId']}"
        self.fail_after_first_step(client, path, SIDE)
        before = ledger.read_bytes()
        self.assertTrue(before)
        response = client.post('/test/setup', headers=admin, json={
            'session_id': 'cleanup', 'setup': {'cleanup_session_ids': ['side']},
        })
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(ledger.read_bytes(), before)
        with app.state.store.connect() as db:
            self.assertIsNone(deletion.reservation(db, up['workbookId']))
            self.assertIsNone(app.state.store.get(db, up['versionId']))

    def test_concurrent_owner_retry_finishes_without_duplicate_ledger_row(self):
        ledger = Path(self.temp.name) / 'deletions.jsonl'
        app, client = self.with_ledger(ledger)
        up = self.upload(client)
        path = f"/api/v1/workbooks/{up['workbookId']}"
        entered, proceed = threading.Event(), threading.Event()
        original = deletion.commit_step

        def pause_first(store, workbook_id, table, deadline):
            result = original(store, workbook_id, table, deadline)
            if table == 'p4_jobs' and not entered.is_set():
                entered.set()
                if not proceed.wait(5):
                    raise TimeoutError('Concurrent retry did not finish.')
            return result

        with patch.object(deletion, 'commit_step', side_effect=pause_first), ThreadPoolExecutor(1) as pool:
            first = pool.submit(client.delete, path, headers=OWNER)
            try:
                self.assertTrue(entered.wait(5))
                self.assertEqual(client.delete(path, headers=OWNER).status_code, 204)
            finally:
                proceed.set()
            self.assertEqual(first.result(timeout=5).status_code, 204)
        self.assertEqual(client.delete(path, headers=OWNER).status_code, 404)
        self.assertEqual(len(ledger.read_bytes().splitlines()), 1)
        with app.state.store.connect() as db:
            self.assertIsNone(deletion.reservation(db, up['workbookId']))

    def with_s3(self, fake):
        with (patch.dict(os.environ, {'DELETION_LEDGER_PATH': '', 'DELETION_LEDGER_BUCKET': 'ledger'}),
              patch('boto3.client', return_value=fake) as factory):
            started = self.start()
        factory.assert_called_once_with('s3')
        return started

    def test_s3_ledger_put_precedes_removal_and_put_failure_retries(self):
        fake = FakeS3()
        app, client = self.with_s3(fake)
        up = self.upload(client)
        wid = up['workbookId']
        path, key = f'/api/v1/workbooks/{wid}', f'deletions/{wid}.json'
        fake.fail_puts = 1
        with self.assertLogs('phase5_deletion', level='ERROR') as logs:
            response = client.delete(path, headers=OWNER)
        self.assertEqual((response.status_code, response.json()['code']), (500, 'DELETION_FAILED'))
        self.assertIn('error_type=ClientError', logs.output[0])
        self.assertNotIn('sensitive', ' '.join(logs.output))
        with app.state.store.connect() as db:
            self.assertIsNotNone(deletion.reservation(db, wid))
            self.assertIsNotNone(app.state.store.get(db, up['versionId']))
        original, seen = deletion.commit_step, []

        def observe(store, workbook_id, table, deadline):
            if table == 'p4_jobs':
                with store.connect() as db:
                    created = deletion.reservation(db, wid)['created']
                seen.append(json.loads(fake.objects[key]) == {'workbook_id': wid, 'timestamp': created})
            return original(store, workbook_id, table, deadline)

        with patch.object(deletion, 'commit_step', side_effect=observe):
            self.assertEqual(client.delete(path, headers=OWNER).status_code, 204)
        self.assertEqual(seen, [True])
        self.assertEqual(list(fake.objects), [key])

    def test_s3_ledger_replays_after_sqlite_restore(self):
        fake = FakeS3()
        fake.objects['deletions/unrelated.json'] = b'{}'
        backup = Path(self.temp.name) / 'backup.sqlite3'
        app, client = self.with_s3(fake)
        up = self.upload(client)
        other = self.upload(client)
        path = f"/api/v1/workbooks/{up['workbookId']}"
        with closing(sqlite3.connect(self.path)) as live, closing(sqlite3.connect(backup)) as archive:
            live.backup(archive)
        self.assertEqual(client.delete(path, headers=OWNER).status_code, 204)
        before = dict(fake.objects)
        with closing(sqlite3.connect(self.path)) as live, closing(sqlite3.connect(backup)) as archive:
            archive.backup(live)
        app, restarted = self.with_s3(fake)
        with restarted:
            self.assertEqual(restarted.get(path + '/history', headers=OWNER).status_code, 404)
            with app.state.store.connect() as db:
                self.assertIsNone(app.state.store.get(db, up['versionId']))
                self.assertIsNone(deletion.reservation(db, up['workbookId']))
                self.assertIsNotNone(app.state.store.get(db, other['versionId']))
        self.assertEqual(fake.objects, before)

    def test_s3_ledger_refuses_invalid_keys_and_both_settings(self):
        for bad in ('deletions/bad id.json', 'deletions/x.jsonl', 'deletions/nested/x.json'):
            with self.subTest(key=bad):
                fake = FakeS3()
                fake.objects[bad] = b'{}'
                _, client = self.with_s3(fake)
                with (self.assertRaisesRegex(RuntimeError, 'Deletion ledger is unavailable or invalid'),
                      self.assertLogs('phase5_deletion', level='ERROR')):
                    with client:
                        self.fail('The service started with an invalid ledger key.')
        both = {'DELETION_LEDGER_PATH': str(Path(self.temp.name) / 'deletions.jsonl'), 'DELETION_LEDGER_BUCKET': 'ledger'}
        with (patch.dict(os.environ, both), patch('boto3.client') as factory,
              self.assertRaisesRegex(RuntimeError, r'both set; unset the one .* \(see D11\)')):
            self.start()
        factory.assert_not_called()


if __name__ == '__main__':
    unittest.main()
