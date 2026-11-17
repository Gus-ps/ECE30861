import hashlib
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient
from app import create_app
from database import Database
from test_phase4_service import workbook

OWNER = {'Authorization': 'Bearer a'}
SIDE = dict(OWNER, **{'X-Test-Session': 'side'})


class DeleteWorkbookTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'service.sqlite3'

    def start(self):
        app = create_app(self.path, {'a': 'owner'}, enable_test_interface=True,
                         test_admin_tokens={'admin': 'administrator'}, test_session_users={'administrator': ['owner']})
        client = TestClient(app); self.addCleanup(client.close)
        return app, client

    def upload(self, client, headers=OWNER):
        response = client.post('/api/v1/workbooks', headers=headers, files={'file': ('book.xlsx', workbook())})
        self.assertEqual(response.status_code, 202, response.text)
        return response.json()

    def test_delete_removes_the_workbook_and_nothing_else(self):
        app, client = self.start()
        self.assertEqual(client.post('/test/setup', headers={'Authorization': 'Bearer admin'},
                                     json={'session_id': 'side'}).status_code, 201)
        up = self.upload(client); self.upload(client); self.upload(client, SIDE)
        wb = '/api/v1/workbooks/' + up['workbookId']
        base = f"{wb}/versions/{up['versionId']}"
        finding = client.get(base + '/audits/' + up['auditId'], headers=OWNER).json()['findings'][0]
        body = {'auditId': up['auditId'], 'decisions': [{'findingId': finding['findingId'], 'action': 'DECLINE'}]}
        rem = client.post(base + '/remediations', headers=dict(OWNER, **{'Idempotency-Key': 'k'}), json=body).json()
        job = client.get('/api/v1/remediations/' + rem['remediationId'], headers=OWNER).json()
        out = f"{wb}/versions/{job['outputVersionId']}"
        urls = [base, base + '/source', base + '/audits/' + up['auditId'], base + '/audits/' + up['auditId'] + '/review',
                base + '/audits/' + up['auditId'] + '/report', out, out + '/audits/' + job['auditId'] + '/report',
                '/api/v1/remediations/' + rem['remediationId'], '/api/v1/outputs/' + job['outputId'] + '/workbook', wb + '/history']
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
        self.assertEqual(client.post(base + '/audits', headers=OWNER, json={}).status_code, 404)
        self.assertEqual(client.post(wb + '/versions', headers=OWNER, files={'file': ('b.xlsx', workbook())}).status_code, 404)
        self.assertEqual(client.post(base + '/remediations', headers=dict(OWNER, **{'Idempotency-Key': 'k'}), json=body).status_code, 404)
        self.assertEqual(client.delete(wb, headers=OWNER).status_code, 404)
        with app.state.database.connect() as db:
            for table in ('p4_resources', 'p4_keys'):
                self.assertEqual(db.execute(f'SELECT COUNT(*) FROM {table} WHERE workbook_id=?', (up['workbookId'],)).fetchone()[0], 0)
            jobs = db.execute('SELECT COUNT(*) FROM p4_jobs WHERE version_id IN (?,?)', (up['versionId'], job['outputVersionId'])).fetchone()[0]
            self.assertEqual(jobs, 0)
            self.assertEqual([tuple(r) for r in db.execute('SELECT * FROM p4_resources ORDER BY seq')], others)
            self.assertEqual([tuple(r) for r in db.execute('SELECT * FROM test_sessions')], sessions)
        operation = client.get('/openapi.json').json()['paths']['/api/v1/workbooks/{workbook_id}']['delete']
        self.assertLessEqual({'204', '401', '403', '404'}, set(operation['responses']))

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
