import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from app import create_app
from test_phase4_service import workbook

OWNER = {'Authorization': 'Bearer a'}
ADMIN = {'Authorization': 'Bearer admin'}


class DeletionFaultTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        env = patch.dict(os.environ, {'ENABLE_TEST_FAULTS': 'true'}); env.start(); self.addCleanup(env.stop)
        self.client = self.restart()

    def restart(self):
        self.app = create_app(Path(self.temp.name) / 'service.sqlite3', {'a': 'owner', 'b': 'other'},
                              enable_test_interface=True, test_admin_tokens={'admin': 'administrator'},
                              test_session_users={'administrator': ['owner', 'other']})
        client = TestClient(self.app); self.addCleanup(client.close)
        return client

    def setup_session(self, session_id, setup):
        return self.client.post('/test/setup', headers=ADMIN, json={'session_id': session_id, 'setup': setup})

    def upload(self, headers):
        self.data = workbook()
        response = self.client.post('/api/v1/workbooks', headers=headers, files={'file': ('book.xlsx', self.data)})
        self.assertEqual(response.status_code, 202, response.text)
        return '/api/v1/workbooks/' + response.json()['workbookId'], response.json()

    def test_deletion_fault_is_one_shot_durable_and_scoped(self):
        self.assertEqual(self.setup_session('fault', {'faults': {'deletion_failures': 1}}).status_code, 201)
        self.assertEqual(self.setup_session('plain', {}).status_code, 201)
        fault = dict(OWNER, **{'X-Test-Session': 'fault'})
        wb, up = self.upload(fault)
        source, data = f"{wb}/versions/{up['versionId']}/source", self.data
        # Ordinary data and another namespace are never eligible.
        for headers in (OWNER, dict(OWNER, **{'X-Test-Session': 'plain'})):
            other, _ = self.upload(headers)
            self.assertEqual(self.client.delete(other, headers=headers).status_code, 204)
        # Rejected deletions don't consume the fault.
        with patch.object(self.app.state.runner, 'drain'):
            busy, _ = self.upload(fault)
        for path, headers, status in ((wb, {}, 401), (wb, {'Authorization': 'Bearer nope'}, 401), (wb, ADMIN, 403),
                                      (wb, dict(fault, Authorization='Bearer b'), 403), (wb, OWNER, 404),
                                      ('/api/v1/workbooks/missing-id', fault, 404), (busy, fault, 409)):
            self.assertEqual(self.client.delete(path, headers=headers).status_code, status, (path, headers))
        self.client = self.restart()  # the armed counter survives a restart
        response = self.client.delete(wb, headers=fault)
        self.assertEqual(response.status_code, 500, response.text)
        self.assertEqual({k: v for k, v in response.json().items() if k != 'requestId'},
                         {'code': 'TEST_DELETION_FAILURE', 'message': 'Deletion failure requested by the isolated test session.',
                          'details': {'stage': 'deletion', 'testOnly': True}})
        self.assertEqual(self.client.get(source, headers=fault).content, data)
        self.client = self.restart()  # so does its consumption
        self.assertEqual(self.client.delete(wb, headers=fault).status_code, 204)
        self.assertEqual(self.client.get(source, headers=fault).status_code, 404)

    def test_fault_setup_rejections(self):
        for name, faults in {'unknown': {'unknown_failures': 1}, 'boolean': {'deletion_failures': True},
                             'two': {'deletion_failures': 2}, 'decimal': {'deletion_failures': 1.0},
                             'null': {'deletion_failures': None}, 'empty': {},
                             'audit-report': {'audit_failures': 1, 'report_failures': 1}}.items():
            with self.subTest(name):
                response = self.setup_session('rejected-' + name, {'faults': faults})
                self.assertEqual((response.status_code, response.json()['source']), (400, 'system'), response.text)
        with patch.dict(os.environ, {'ENABLE_TEST_FAULTS': 'false'}):
            self.assertEqual(self.setup_session('disabled', {'faults': {'deletion_failures': 1}}).status_code, 403)
        wb, _ = self.upload(OWNER)
        self.assertEqual(self.client.delete(wb, headers=dict(OWNER, **{'X-Test-Session': 'disabled'})).status_code, 400)
        self.assertEqual(self.setup_session('reused', {'faults': {'deletion_failures': 1}}).status_code, 201)
        reused = dict(OWNER, **{'X-Test-Session': 'reused'})
        target, _ = self.upload(reused)
        self.assertEqual(self.client.delete(target, headers=reused).status_code, 500)
        self.assertEqual(self.setup_session('reused', {'faults': {'deletion_failures': 1}}).status_code, 409)
        self.assertEqual(self.client.delete(target, headers=reused).status_code, 204)


if __name__ == '__main__':
    unittest.main()
