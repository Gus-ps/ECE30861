from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from app import create_app
from test_phase4_service import workbook

OWNER = {'Authorization': 'Bearer a'}
# caller: (headers, read status, write status, status for unknown IDs)
CALLERS = {
    'granted reviewer': ({'Authorization': 'Bearer r'}, 200, 403, 404),
    'ungranted reviewer': ({'Authorization': 'Bearer u'}, 403, 403, 404),
    'foreign user': ({'Authorization': 'Bearer b'}, 403, 403, 404),
    'no token': ({}, 401, 401, 401),
    'invalid token': ({'Authorization': 'Bearer nope'}, 401, 401, 401),
    'test-admin': ({'Authorization': 'Bearer admin'}, 403, 403, 403),
    'wrong namespace': (dict(OWNER, **{'X-Test-Session': 'elsewhere'}), 404, 404, 404),
    'owner': (OWNER, 200, 202, 404),  # last: its writes change state
}
VERSION = '/api/v1/workbooks/{wb}/versions/{v}'
# Reads first, then writes in an order that keeps each owner write valid.
OPERATIONS = [
    ('4', 'GET', VERSION, {}),
    ('5', 'GET', VERSION + '/audits/{a}', {}),
    ('8', 'GET', '/api/v1/remediations/{rem}', {}),
    ('9', 'GET', '/api/v1/outputs/{out}/workbook', {}),
    ('10', 'GET', '/api/v1/workbooks/{wb}/history', {}),
    ('S', 'GET', VERSION + '/source', {}),
    ('V', 'GET', VERSION + '/audits/{a}/review', {}),
    ('R', 'GET', VERSION + '/audits/{a}/report', {}),
    ('7', 'POST', VERSION + '/remediations', {'remediation': True}),
    ('3', 'POST', '/api/v1/workbooks/{wb}/versions', {'files': {'file': ('next.xlsx', workbook())}}),
    ('6', 'POST', VERSION + '/audits', {'json': {}}),
]


class AccessOrderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.app = create_app(Path(self.temp.name) / 'service.sqlite3',
                              {'a': 'alice', 'b': 'other', 'r': 'reviewer', 'u': 'stranger'},
                              enable_test_interface=True, test_admin_tokens={'admin': 'administrator'},
                              test_session_users={'administrator': ['alice', 'other', 'reviewer', 'stranger']},
                              reviewer_grants={'reviewer': ['alice'], 'stranger': ['nobody']})
        self.client = TestClient(self.app); self.addCleanup(self.client.close)

    def counts(self):
        with self.app.state.database.connect() as db:
            return [db.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0] for t in ('p4_resources', 'p4_keys', 'p4_jobs')]

    def test_access_check_order_for_every_workbook_route(self):
        up = self.client.post('/api/v1/workbooks', headers=OWNER, files={'file': ('book.xlsx', workbook())}).json()
        base = VERSION.format(wb=up['workbookId'], v=up['versionId'])
        audit = self.client.get(base + '/audits/' + up['auditId'], headers=OWNER).json()
        finding = audit['findings'][0]
        body = {'auditId': up['auditId'], 'decisions': [{'findingId': finding['findingId'], 'action': 'DECLINE'}]}
        rem = self.client.post(base + '/remediations', headers=dict(OWNER, **{'Idempotency-Key': 'k'}), json=body).json()
        job = self.client.get('/api/v1/remediations/' + rem['remediationId'], headers=OWNER).json()
        self.assertEqual(job['status'], 'REMEDIATED', job)
        self.assertEqual(self.client.post('/test/setup', headers={'Authorization': 'Bearer admin'},
                                          json={'session_id': 'elsewhere'}).status_code, 201)
        known = dict(wb=up['workbookId'], v=up['versionId'], a=up['auditId'], rem=rem['remediationId'], out=job['outputId'])
        unknown = dict.fromkeys(known, 'missing-id')
        # Nothing identifying the resource may appear in a denial (ACC-3).
        meta, outmeta = (self.client.get(VERSION.format(wb=up['workbookId'], v=v), headers=OWNER).json()
                         for v in (up['versionId'], job['outputVersionId']))
        secrets = {*known.values(), job['outputVersionId'], job['auditId'], finding['findingId'], 'alice',
                   meta['fileName'], audit['startedAt'], audit['completedAt'],
                   *(m[k] for m in (meta, outmeta) for k in ('sha256', 'createdAt'))}
        store = self.app.state.store
        for op, method, path, kwargs in OPERATIONS:
            for caller, (headers, read, write, missing) in CALLERS.items():
                for ids, expected in ((unknown, missing), (known, write if method == 'POST' else read)):
                    with self.subTest(op=op, caller=caller, ids='known' if ids is known else 'unknown'):
                        args = {k: v for k, v in kwargs.items() if k != 'remediation'}
                        if 'remediation' in kwargs:
                            args = {'json': dict(body, auditId=ids['a'])}
                            headers = dict(headers, **{'Idempotency-Key': 'k'})
                        before = self.counts()
                        with patch.object(store, 'bytes', wraps=store.bytes) as reads:
                            response = self.client.request(method, path.format(**ids), headers=headers, **args)
                        self.assertEqual(response.status_code, expected, response.text)
                        if expected >= 400:
                            self.assertEqual(set(response.json()), {'code', 'message', 'requestId', 'details'})
                            exposed = response.text + str(response.headers)
                            self.assertEqual([s for s in secrets if s in exposed], [])
                            reads.assert_not_called()
                            self.assertEqual(self.counts(), before)


if __name__ == '__main__':
    unittest.main()
