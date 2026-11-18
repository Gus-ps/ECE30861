"""REQ-12 / AC-12 / AC-15: P5-CLOCK-DEFAULT, P5-CLOCK-CUSTOM, P5-CLOCK-ISOLATION."""
from datetime import datetime, timezone
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import create_app
from phase5_schedule import effective_now

ADMIN = {'Authorization': 'Bearer admin'}
OWNER = {'Authorization': 'Bearer a'}
DEFAULT = '2027-01-01T00:00:00Z'


class ClockTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / 'service.sqlite3'
        self.restart()

    def restart(self, enabled=True):
        with patch.dict(os.environ, {'ENABLE_TEST_CLOCK': 'true' if enabled else 'false'}):
            self.app = create_app(
                self.path, {'a': 'owner', 'r': 'reviewer'}, enable_test_interface=True,
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
