"""REQ-12 / AC-12 / AC-14. Effective audit timestamps and P5-CLOCK-REAL-TIME."""
from datetime import datetime, timezone
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import create_app
from test_phase4_service import workbook

START = '2027-01-01T00:00:00Z'
DUE = '2027-01-02T00:00:00Z'
ADMIN = {'Authorization': 'Bearer admin'}
OWNER = {'Authorization': 'Bearer a'}
CLOCK = '/api/v1/test/clock'


class DispatchTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        env = patch.dict(os.environ, {'ENABLE_TEST_CLOCK': 'true', 'ENABLE_TEST_FAULTS': 'true'})
        env.start()
        self.addCleanup(env.stop)
        self.app = create_app(
            Path(directory.name) / 'service.sqlite3', {'a': 'owner', 'b': 'other'},
            enable_test_interface=True, test_admin_tokens={'admin': 'administrator'},
            test_session_users={'administrator': ['owner', 'other']},
        )
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)
        self.runner = self.app.state.runner

    def prepare(self, session='clock', **setup):
        response = self.client.post('/test/setup', headers=ADMIN,
                                    json={'session_id': session, 'setup': setup})
        self.assertEqual(response.status_code, 201, response.text)
        return {**OWNER, 'X-Test-Session': session}

    def advance(self, instant, session='clock'):
        return self.client.post(CLOCK, headers={**ADMIN, 'X-Test-Session': session},
                                json={'currentTime': instant})

    def upload(self, headers, path='/api/v1/workbooks'):
        response = self.client.post(path, headers=headers, files={'file': ('book.xlsx', workbook())})
        self.assertEqual(response.status_code, 202, response.text)
        ids = response.json()
        return ids, f"/api/v1/workbooks/{ids['workbookId']}/versions/{ids['versionId']}"

    def read_audit(self, headers, version, audit_id):
        response = self.client.get(f'{version}/audits/{audit_id}', headers=headers)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def remediate(self, headers, version, audit_id):
        finding = self.read_audit(headers, version, audit_id)['findings'][0]
        accepted = self.client.post(version + '/remediations',
                                    headers={**headers, 'Idempotency-Key': 'decline'},
                                    json={'auditId': audit_id, 'decisions': [
                                        {'findingId': finding['findingId'], 'action': 'DECLINE'},
                                    ]})
        self.assertEqual(accepted.status_code, 202, accepted.text)
        return accepted.json()['remediationId']

    def test_manual_and_failed_audits_use_effective_time(self):
        headers = self.prepare(faults={'audit_failures': 1})
        ids, version = self.upload(headers)
        failed = self.read_audit(headers, version, ids['auditId'])
        self.assertEqual(failed['error']['code'], 'TEST_AUDIT_FAILURE')
        self.assertEqual((failed['startedAt'], failed['completedAt']), (START, START))
        self.assertEqual(self.advance(DUE).status_code, 200)
        accepted = self.client.post(version + '/audits', headers=headers, json={})
        self.assertEqual(accepted.status_code, 202, accepted.text)
        audit = self.read_audit(headers, version, accepted.json()['auditId'])
        self.assertEqual((audit['startedAt'], audit['completedAt']), (DUE, DUE))

    def test_remediation_output_audit_uses_effective_time(self):
        headers = self.prepare()
        ids, version = self.upload(headers)
        self.assertEqual(self.advance(DUE).status_code, 200)
        rid = self.remediate(headers, version, ids['auditId'])
        result = self.client.get(f'/api/v1/remediations/{rid}', headers=headers).json()
        self.assertEqual(result['status'], 'REMEDIATED')
        output = f"/api/v1/workbooks/{ids['workbookId']}/versions/{result['outputVersionId']}"
        audit = self.read_audit(headers, output, result['auditId'])
        self.assertEqual((audit['startedAt'], audit['completedAt']), (DUE, DUE))

    def test_ordinary_audit_uses_real_time(self):
        before = datetime.now(timezone.utc)
        ids, version = self.upload(OWNER)
        audit = self.read_audit(OWNER, version, ids['auditId'])
        started = datetime.fromisoformat(audit['startedAt'])
        completed = datetime.fromisoformat(audit['completedAt'])
        self.assertLessEqual(before, started)
        self.assertLessEqual(started, completed)
        self.assertLessEqual(completed, datetime.now(timezone.utc))
