"""System-side instructor interface and namespace isolation over actual API calls."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from fastapi.testclient import TestClient

from app import create_app
from test_api import workbook


class SystemInterfaceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / 'system.sqlite3'
        self.options = {
            'tokens': {'a-token': 'alice', 'b-token': 'bob', 'r-token': 'reviewer', 'c-token': 'charlie'},
            'enable_test_interface': True,
            'test_admin_tokens': {'admin-token': 'admin', 'other-admin': 'other'},
            'test_session_users': {'admin': ['alice', 'bob', 'reviewer'], 'other': ['charlie']},
            'reviewer_grants': {'reviewer': ['alice']},
            'accessibility_checker': lambda path: [],
        }
        self.app = create_app(self.path, **self.options)
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)

    def headers(self, token='admin-token', session=None):
        headers = {'Authorization': f'Bearer {token}'}
        if session is not None:
            headers['X-Test-Session'] = session
        return headers

    def setup_session(self, name, cleanup=(), token='admin-token'):
        return self.client.post('/test/setup', headers=self.headers(token), json={
            'session_id': name, 'setup': {'cleanup_session_ids': list(cleanup)},
        })

    def upload(self, session=None, token='a-token'):
        return self.client.post('/api/v1/workbooks', headers=self.headers(token, session),
                                files={'file': ('sample.xlsx', workbook())})

    @staticmethod
    def version_path(ids):
        return f"/api/v1/workbooks/{ids['workbookId']}/versions/{ids['versionId']}"

    def test_disabled_interface_and_swagger_security(self):
        with TestClient(create_app(self.path, tokens={'a': 'alice'})) as client:
            self.assertEqual(client.post('/test/setup', json={'session_id': 'x', 'setup': {}}).status_code, 404)
        schema = self.client.get('/openapi.json').json()
        self.assertEqual(schema['paths']['/test/setup']['post']['security'], [{'TestAdministrator': []}])
        self.assertEqual(schema['components']['securitySchemes']['TestAdministrator']['scheme'], 'bearer')

    def test_admin_authentication_and_error_shape(self):
        for token, expected in (('incorrect', 401), ('a-token', 403)):
            response = self.setup_session('s', token=token)
            self.assertEqual(response.status_code, expected)
            self.assertEqual(set(response.json()), {'message', 'source'})
            self.assertEqual(response.json()['source'], 'system')
        self.assertEqual(self.client.post('/test/setup', json={'session_id': 's'}).status_code, 401)

    def test_malformed_setup_and_report_return_system_errors(self):
        for body in ({}, {'session_id': 'bad id', 'setup': {}},
                     {'session_id': 's', 'setup': {'wipe_everything': True}}):
            response = self.client.post('/test/setup', headers=self.headers(), json=body)
            self.assertEqual(response.status_code, 400, response.text)
            self.assertEqual(set(response.json()), {'message', 'source'})
        self.assertEqual(self.client.get('/test/report', headers=self.headers()).status_code, 400)
        self.assertEqual(self.client.get('/test/report', headers=self.headers(), params={'session_id': 'missing'}).status_code, 404)

    def test_duplicate_setup_is_atomic_and_report_does_not_fabricate_coverage(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.setup_session('concurrent').status_code, range(2)))
        self.assertEqual(sorted(results), [201, 409])
        report = self.client.get('/test/report', params={'session_id': 'concurrent'}, headers=self.headers())
        self.assertEqual(report.status_code, 200)
        self.assertEqual(report.json()['session_id'], 'concurrent')
        coverage = report.json()['coverage']['code']
        self.assertIsNone(coverage['covered'])
        self.assertIsNone(coverage['total'])
        self.assertTrue(coverage['basis'])
        self.assertEqual(self.client.get('/test/report', params={'session_id': 'concurrent'},
                                        headers=self.headers('other-admin')).status_code, 403)

    def test_namespace_and_user_ownership_are_both_required(self):
        self.setup_session('one')
        self.setup_session('two')
        response = self.upload('one')
        self.assertEqual(response.status_code, 202, response.text)
        path = self.version_path(response.json())
        self.assertEqual(self.client.get(path, headers=self.headers('a-token', 'one')).status_code, 200)
        for token, session in (('a-token', None), ('a-token', 'two'), ('b-token', 'one')):
            self.assertEqual(self.client.get(path, headers=self.headers(token, session)).status_code, 403)
        self.assertEqual(self.upload('one', 'c-token').status_code, 403)
        self.assertEqual(self.upload('unknown').status_code, 400)
        self.assertEqual(self.client.get('/api/v1/health', headers=self.headers('a-token', 'unknown')).status_code, 400)
        self.assertEqual(self.client.get('/api/v1/health', headers=self.headers('a-token', 'one')).status_code, 200)

    def test_cleanup_never_removes_ordinary_data_or_other_sessions(self):
        ordinary = self.upload().json()
        self.setup_session('one')
        self.setup_session('two')
        one = self.upload('one').json()
        two = self.upload('two').json()
        response = self.setup_session('three', cleanup=['one'])
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(self.client.get(self.version_path(ordinary), headers=self.headers('a-token')).status_code, 200)
        self.assertEqual(self.client.get(self.version_path(two), headers=self.headers('a-token', 'two')).status_code, 200)
        self.assertEqual(self.client.get(self.version_path(one), headers=self.headers('a-token')).status_code, 404)
        self.assertEqual(self.setup_session('one').status_code, 409)
        self.assertEqual(self.upload('one').status_code, 400)
        self.assertEqual(self.client.get('/test/report', headers=self.headers(),
                                        params={'session_id': 'one'}).status_code, 409)

    def test_cleanup_checks_all_ownership_before_mutation(self):
        self.setup_session('one')
        self.setup_session('foreign', token='other-admin')
        response = self.setup_session('new', cleanup=['one', 'foreign'])
        self.assertEqual(response.status_code, 403)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT state FROM test_sessions WHERE session_id='one'").fetchone()[0], 'READY')
            self.assertIsNone(db.execute("SELECT 1 FROM test_sessions WHERE session_id='new'").fetchone())

    def test_cleanup_rejects_active_audits(self):
        self.setup_session('one')
        ids = self.upload('one').json()
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("UPDATE audits SET status='PROCESSING' WHERE audit_id=?", (ids['auditId'],))
            db.commit()
        self.assertEqual(self.setup_session('two', cleanup=['one']).status_code, 409)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM versions').fetchone()[0], 1)

    def test_sessions_survive_restart_and_reviewers_cannot_upload(self):
        self.setup_session('one')
        ids = self.upload('one').json()
        with TestClient(create_app(self.path, **self.options)) as client:
            self.assertEqual(client.get('/test/report', headers=self.headers(),
                                        params={'session_id': 'one'}).status_code, 200)
            self.assertEqual(client.get(self.version_path(ids), headers=self.headers('r-token', 'one')).status_code, 200)
        self.assertEqual(self.upload('one', 'r-token').status_code, 403)
