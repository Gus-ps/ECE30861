"""REQ-12 / AC-12 / AC-15, Phase 5 clock advancement without dispatch.

P5-CLOCK-DEFAULT, P5-CLOCK-CUSTOM, P5-CLOCK-REWIND, P5-CLOCK-SAME,
P5-CLOCK-UTC, P5-CLOCK-ISOLATION, P5-CLOCK-OWNER, P5-CLOCK-DISABLED,
P5-CLOCK-CLEANED, P5-CLOCK-NOT-READY, P5-CLOCK-STORAGE-ROLLBACK,
P5-CLOCK-LOST-ACK, P5-LOCAL-CLOCK-RESTART (clock persistence).
P5-ACCESS-CLOCK-NO-TOKEN, P5-ACCESS-CLOCK-INVALID-TOKEN,
P5-ACCESS-CLOCK-OWNER-USER, P5-ACCESS-CLOCK-REVIEWER,
P5-ACCESS-CLOCK-FOREIGN-ADMIN, P5-ACCESS-CLOCK-CREATING-ADMIN.
"""
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import create_app
from phase5_schedule import effective_now
from test_phase4_service import workbook

ADMIN = {'Authorization': 'Bearer admin'}
OWNER = {'Authorization': 'Bearer a'}
DEFAULT = '2027-01-01T00:00:00Z'
LATER = '2028-01-01T00:00:00Z'
CLOCK = '/api/v1/test/clock'


class ClockTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / 'service.sqlite3'
        self.restart()

    def restart(self, enabled=True, test_interface=True):
        with patch.dict(os.environ, {'ENABLE_TEST_CLOCK': 'true' if enabled else 'false'}):
            self.app = create_app(
                self.path, {'a': 'owner', 'r': 'reviewer'}, enable_test_interface=test_interface,
                test_admin_tokens={'admin': 'administrator', 'other-admin': 'other'},
                test_session_users={'administrator': ['owner', 'reviewer'], 'other': ['owner']},
                reviewer_grants={'reviewer': ['owner']},
            )
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)

    def setup_session(self, session_id, **setup):
        return self.client.post('/test/setup', headers=ADMIN,
                                json={'session_id': session_id, 'setup': setup})

    def clock_rows(self):
        with self.app.state.database.connect() as db:
            return {row['session_id']: row['current_time'] for row in db.execute('SELECT * FROM p5_clocks')}

    def assert_setup_error(self, session_id, response, status):
        self.assertEqual(response.status_code, status, response.text)
        self.assertEqual(set(response.json()), {'message', 'source'})
        self.assertEqual(response.json()['source'], 'system')
        with self.app.state.database.connect() as db:
            self.assertIsNone(db.execute('SELECT 1 FROM test_sessions WHERE session_id=?',
                                         (session_id,)).fetchone())

    def test_setup_persists_default_and_normalized_custom_time(self):
        self.assertEqual(self.setup_session('default').status_code, 201)
        custom = self.setup_session('custom', clock={'currentTime': '2028-02-29T12:34:56.1Z'})
        self.assertEqual(custom.status_code, 201, custom.text)
        self.assertEqual(self.clock_rows(), {'default': DEFAULT, 'custom': '2028-02-29T12:34:56.100000Z'})
        with self.app.state.database.connect() as db:
            self.assertEqual(effective_now(db, 'custom'), datetime(2028, 2, 29, 12, 34, 56, 100000, timezone.utc))

    def test_invalid_setup_clock_creates_no_session(self):
        invalid = (None, {}, {'currentTime': '2027-02-29T00:00:00Z'},
                   {'currentTime': '2027-01-01T00:00:00+00:00'}, {'currentTime': 123},
                   {'currentTime': DEFAULT, 'extra': True})
        for clock in invalid:
            with self.subTest(clock=clock):
                self.assert_setup_error('bad', self.setup_session('bad', clock=clock), 400)
        duplicate = self.client.post('/test/setup', headers={**ADMIN, 'Content-Type': 'application/json'},
                                    content='{"session_id":"bad","setup":{"clock":{"currentTime":"x",'
                                            '"currentTime":"2027-01-01T00:00:00Z"}}}')
        self.assert_setup_error('bad', duplicate, 400)
        invalid_utf8 = self.client.post('/test/setup', headers={**ADMIN, 'Content-Type': 'application/json'},
                                        content=b'{"session_id":"bad","setup":{"clock":{"currentTime":"\xff"}}}')
        self.assert_setup_error('bad', invalid_utf8, 400)
        self.assertEqual(self.clock_rows(), {})

    def test_disabled_setup_and_effective_time_fallback(self):
        self.restart(enabled=False)
        self.assert_setup_error('rejected', self.setup_session('rejected', clock={'currentTime': DEFAULT}), 403)
        self.assertEqual(self.setup_session('legacy').status_code, 201)
        self.assertEqual(self.clock_rows(), {})
        with self.app.state.database.connect() as db:
            for session_id in (None, 'legacy'):
                with self.subTest(session_id=session_id):
                    before = datetime.now(timezone.utc)
                    instant = effective_now(db, session_id)
                    self.assertLessEqual(before, instant)
                    self.assertLessEqual(instant, datetime.now(timezone.utc))

    def test_cleanup_removes_only_requested_clock(self):
        self.assertEqual(self.setup_session('remove').status_code, 201)
        self.assertEqual(self.setup_session('keep').status_code, 201)
        self.assertEqual(self.setup_session('cleanup', cleanup_session_ids=['remove']).status_code, 201)
        self.assertEqual(self.clock_rows(), {'keep': DEFAULT, 'cleanup': DEFAULT})

    def advance(self, session_id, instant=DEFAULT, headers=ADMIN):
        return self.client.post(CLOCK, headers={**headers, 'X-Test-Session': session_id},
                                json={'currentTime': instant})

    def assert_advanced(self, response, instant):
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {
            'currentTime': instant, 'triggeredAudits': [], 'triggeredNotifications': [],
        })

    def assert_project_error(self, response, status, code):
        self.assertEqual(response.status_code, status, response.text)
        body = response.json()
        self.assertEqual(set(body), {'code', 'message', 'requestId', 'details'})
        self.assertEqual(body['code'], code)
        self.assertEqual(body['requestId'], response.headers['X-Request-ID'])

    def schedule(self, session_id=None, interval=90):
        headers = {**OWNER, 'X-Test-Session': session_id} if session_id else OWNER
        upload = self.client.post('/api/v1/workbooks', headers=headers,
                                  files={'file': ('book.xlsx', workbook())})
        self.assertEqual(upload.status_code, 202, upload.text)
        path = f"/api/v1/workbooks/{upload.json()['workbookId']}/schedule"
        response = self.client.put(path, headers=headers, json={'enabled': True, 'intervalDays': interval})
        return path, headers, response

    def test_default_clock_drives_schedule_due_time(self):
        self.assertEqual(self.setup_session('default').status_code, 201)
        self.assert_advanced(self.advance('default'), DEFAULT)
        _, _, response = self.schedule('default')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['nextAuditAt'], '2027-04-01T00:00:00Z')

    def test_custom_clock_allows_equal_time_and_rejects_rewind(self):
        self.assertEqual(self.setup_session('custom', clock={'currentTime': LATER}).status_code, 201)
        self.assert_advanced(self.advance('custom', '2028-01-01T00:00:00.000Z'), LATER)
        self.assert_project_error(self.advance('custom'), 400, 'CLOCK_REWIND')
        self.assertEqual(self.clock_rows(), {'custom': LATER})

    def test_advance_survives_restart_and_equal_replay(self):
        self.assertEqual(self.setup_session('clock').status_code, 201)
        first = self.advance('clock', '2028-01-01T00:00:00.012Z')
        self.assert_advanced(first, '2028-01-01T00:00:00.012000Z')
        self.restart()
        saved = self.clock_rows()
        self.assertEqual(saved, {'clock': first.json()['currentTime']})
        replay = self.advance('clock', saved['clock'])
        self.assert_advanced(replay, saved['clock'])
        self.assertEqual(replay.json(), first.json())

    def test_rejects_invalid_clock_requests_without_changing_time(self):
        self.assertEqual(self.setup_session('clock').status_code, 201)
        for instant in ('2027-01-01T00:00:00', '2027-01-01T00:00:00+09:00',
                        '2027-01-01T00:00:00.1234567Z', '2027-02-30T00:00:00Z',
                        '0000-01-01T00:00:00Z', '10000-01-01T00:00:00Z', 123):
            with self.subTest(instant=instant):
                self.assert_project_error(self.advance('clock', instant), 400, 'INVALID_REQUEST')
        for raw in (b'{"currentTime":"2027-01-01T00:00:00Z","extra":true}',
                    b'{"currentTime":"x","currentTime":"2027-01-01T00:00:00Z"}',
                    b'{"currentTime":NaN}', b'{"currentTime":"\xff"}', b'{}', b'[]', b'{'):
            with self.subTest(raw=raw):
                response = self.client.post(CLOCK, content=raw,
                                            headers={**ADMIN, 'X-Test-Session': 'clock'})
                self.assert_project_error(response, 400, 'INVALID_REQUEST')
        self.assertEqual(self.clock_rows(), {'clock': DEFAULT})

    def test_size_limit_applies_after_access_and_session_checks(self):
        self.assertEqual(self.setup_session('clock').status_code, 201)
        body = b'x' * (1_048_576 + 1)
        for session_id, status, code in (('unknown', 400, 'INVALID_TEST_SESSION'),
                                         ('clock', 413, 'REQUEST_TOO_LARGE')):
            with self.subTest(session_id=session_id):
                response = self.client.post(CLOCK, content=body, headers={
                    **ADMIN, 'X-Test-Session': session_id, 'Content-Type': 'application/json',
                })
                self.assert_project_error(response, status, code)
        self.assertEqual(self.clock_rows(), {'clock': DEFAULT})

    def test_advance_changes_only_one_clock_and_preserves_schedules(self):
        self.assertEqual(self.setup_session('first').status_code, 201)
        self.assertEqual(self.setup_session('second').status_code, 201)
        before = datetime.now(timezone.utc)
        schedules = [self.schedule(session_id, interval=1) for session_id in ('first', 'second', None)]
        after = datetime.now(timezone.utc)
        for _, _, response in schedules:
            self.assertEqual(response.status_code, 200, response.text)
        ordinary = schedules[-1][2].json()
        ordinary_effective = datetime.fromisoformat(ordinary['nextAuditAt']) - timedelta(days=1)
        self.assertLessEqual(before, ordinary_effective)
        self.assertLessEqual(ordinary_effective, after)

        self.assert_advanced(self.advance('first', LATER), LATER)
        self.assertEqual(self.clock_rows(), {'first': LATER, 'second': DEFAULT})
        for path, headers, response in schedules:
            retained = self.client.get(path, headers=headers)
            self.assertEqual(retained.status_code, 200, retained.text)
            self.assertEqual(retained.json(), response.json())
        _, _, next_schedule = self.schedule('first', interval=1)
        self.assertEqual(next_schedule.status_code, 200, next_schedule.text)
        self.assertEqual(next_schedule.json()['nextAuditAt'], '2028-01-02T00:00:00Z')

    def test_clock_authorization_precedes_body_validation(self):
        self.assertEqual(self.setup_session('clock').status_code, 201)
        for headers, status, code in (
            ({}, 401, 'UNAUTHORIZED'),
            ({'Authorization': 'Bearer invalid'}, 401, 'UNAUTHORIZED'),
            (OWNER, 403, 'FORBIDDEN'),
            ({'Authorization': 'Bearer r'}, 403, 'FORBIDDEN'),
            ({'Authorization': 'Bearer other-admin'}, 403, 'FORBIDDEN'),
        ):
            with self.subTest(headers=headers):
                self.assert_project_error(self.advance('clock', 'invalid', headers), status, code)
        self.assert_advanced(self.advance('clock', LATER), LATER)

    def test_disabled_clock_and_missing_header_precede_authentication(self):
        for enabled, interface in ((False, True), (True, False)):
            with self.subTest(enabled=enabled, interface=interface):
                self.restart(enabled=enabled, test_interface=interface)
                self.assert_project_error(self.advance('missing', 'invalid', {}), 404, 'TEST_CLOCK_DISABLED')
        self.restart()
        response = self.client.post(CLOCK, content=b'x' * (1_048_576 + 1),
                                    headers={'Content-Type': 'application/json'})
        self.assert_project_error(response, 404, 'TEST_CLOCK_DISABLED')

    def test_missing_cleaned_not_ready_and_legacy_sessions_precede_body_validation(self):
        self.restart(enabled=False)
        self.assertEqual(self.setup_session('legacy').status_code, 201)
        self.restart()
        self.assertEqual(self.setup_session('cleaned').status_code, 201)
        self.assertEqual(self.setup_session('not-ready').status_code, 201)
        self.assertEqual(self.setup_session('cleanup', cleanup_session_ids=['cleaned']).status_code, 201)
        with self.app.state.database.connect(write=True) as db:
            db.execute("UPDATE test_sessions SET state='PREPARING' WHERE session_id='not-ready'")
        for session_id, status, code in (
            ('unknown', 400, 'INVALID_TEST_SESSION'), ('bad/id', 400, 'INVALID_TEST_SESSION'),
            ('cleaned', 400, 'INVALID_TEST_SESSION'), ('not-ready', 409, 'SESSION_NOT_READY'),
            ('legacy', 409, 'LEGACY_SESSION_CLOCK'),
        ):
            with self.subTest(session_id=session_id):
                self.assert_project_error(self.advance(session_id, 'invalid'), status, code)
        self.assertEqual(self.clock_rows(), {'cleanup': DEFAULT, 'not-ready': DEFAULT})

    def test_storage_failure_rolls_back_advance(self):
        self.assertEqual(self.setup_session('clock').status_code, 201)
        with patch('phase5_clock.process_due_work', side_effect=sqlite3.OperationalError('write failed')):
            with self.assertLogs(level='ERROR'):
                self.assert_project_error(self.advance('clock', LATER), 500, 'STORAGE_FAILED')
        self.assertEqual(self.clock_rows(), {'clock': DEFAULT})
        self.assert_advanced(self.advance('clock', LATER), LATER)

    def test_schedule_overflow_after_clock_advance_preserves_configuration(self):
        self.assertEqual(self.setup_session('clock').status_code, 201)
        path, headers, created = self.schedule('clock', interval=1)
        self.assertEqual(created.status_code, 200, created.text)
        maximum = '9999-12-31T23:59:59.999999Z'
        self.assert_advanced(self.advance('clock', maximum), maximum)
        response = self.client.put(path, headers=headers, json={'enabled': True, 'intervalDays': 2})
        self.assert_project_error(response, 400, 'TIME_RANGE_EXCEEDED')
        self.assertEqual(self.client.get(path, headers=headers).json(), created.json())
        self.assertEqual(self.clock_rows(), {'clock': maximum})

    def test_openapi_documents_clock_models_and_bearer_security(self):
        schema = self.client.get('/openapi.json').json()
        operation = schema['paths'][CLOCK]['post']
        self.assertIn({'TestAdministrator': []}, operation['security'])
        self.assertEqual(schema['components']['securitySchemes']['TestAdministrator']['scheme'], 'bearer')
        request = operation['requestBody']['content']['application/json']['schema']
        self.assertEqual(request['required'], ['currentTime'])
        self.assertFalse(request['additionalProperties'])
        self.assertEqual(request['properties']['currentTime']['format'], 'date-time')
        for status, model in (('200', 'ClockResponse'), ('400', 'Error'), ('401', 'Error'),
                              ('403', 'Error'), ('404', 'Error'), ('409', 'Error'), ('500', 'Error')):
            response = operation['responses'][status]['content']['application/json']['schema']
            self.assertEqual(response['$ref'], f'#/components/schemas/{model}')
