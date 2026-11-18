from concurrent.futures import ThreadPoolExecutor
import hashlib
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from app import create_app, load_workbook_validator
from database import Database
from test_phase4_service import workbook

OWNER = {'Authorization': 'Bearer a'}
SIDE = dict(OWNER, **{'X-Test-Session': 'side'})


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


if __name__ == '__main__':
    unittest.main()
