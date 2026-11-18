"""Phase 5 report compatibility and REQ-13 / AC-14 fault coverage."""
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from app import create_app
from phase4_store import encode
from test_phase4_service import workbook
import test_phase5_dispatch as dispatch_tests
import test_phase5_scheduler as scheduler_tests

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
        schedule = self.client.put(wb + '/schedule', headers=fault, json={'enabled': True, 'intervalDays': 7})
        self.assertEqual(schedule.status_code, 200, schedule.text)
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
        retained = self.client.get(wb + '/schedule', headers=fault)
        self.assertEqual(retained.status_code, 200, retained.text)
        self.assertEqual(retained.json(), schedule.json())
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


class ScheduledAuditFaultTests(unittest.TestCase):
    """P5-FAULT-SCHEDULED_AUDIT, P5-SCHEDULE-FAILED-NEXT and P5-FAULT-REJECT-*."""

    setUp = dispatch_tests.DispatchTests.setUp
    prepare = dispatch_tests.DispatchTests.prepare
    upload = dispatch_tests.DispatchTests.upload
    configure = dispatch_tests.DispatchTests.configure
    schedule = dispatch_tests.DispatchTests.schedule
    scheduled_workbook = dispatch_tests.DispatchTests.scheduled_workbook
    advance = dispatch_tests.DispatchTests.advance
    read_audit = dispatch_tests.DispatchTests.read_audit
    assert_error = dispatch_tests.DispatchTests.assert_error
    configured = scheduler_tests.SchedulerTests.configured
    tick_at = scheduler_tests.SchedulerTests.tick_at

    def counter(self):
        with self.app.state.store.connect() as db:
            return db.execute("""SELECT remaining FROM p5_faults
                WHERE session_id='clock' AND kind='scheduled_audit'""").fetchone()[0]

    def scheduled_acceptance(self, instant, session='clock'):
        response = self.advance(instant, session)
        self.assertEqual(response.status_code, 200, response.text)
        aid, = response.json()['triggeredAudits']
        return aid, response.headers['X-Request-ID']

    def test_scheduled_fault_survives_restart_and_next_period_succeeds(self):
        headers = self.prepare(faults={'scheduled_audit_failures': 1})
        ids, path, version = self.scheduled_workbook(headers)
        old_audit = self.read_audit(headers, version, ids['auditId'])
        self.assertIsNone(old_audit['error'])
        source_url = version + '/source'
        original = self.client.get(source_url, headers=headers)
        self.assertEqual(original.status_code, 200, original.text)

        aid, request_id = self.scheduled_acceptance(dispatch_tests.DUE)
        self.assertEqual(self.counter(), 0)
        restarted = create_app(self.app.state.database.path, {'a': 'owner'}, enable_scheduler=False)
        runner = restarted.state.runner
        with patch.object(runner, 'checker') as checker:
            runner.drain()
        checker.assert_not_called()
        failed = self.read_audit(headers, version, aid)
        error = {
            'code': 'TEST_SCHEDULED_AUDIT_FAILURE',
            'message': 'Scheduled audit failure requested by the isolated test session.',
            'requestId': request_id,
            'details': {'stage': 'scheduled_audit', 'testOnly': True},
        }
        self.assertEqual((failed['status'], failed['findings'], failed['error']),
                         ('PROCESSING_FAILED', [], error))
        report = self.client.get(f'{version}/audits/{aid}/report', headers=headers)
        self.assertEqual(report.status_code, 200, report.text)
        self.assertEqual((report.json()['error'], report.json()['checksPerformed']), (error, []))
        self.assertEqual(self.client.get(source_url, headers=headers).content, original.content)
        self.assertEqual(self.read_audit(headers, version, ids['auditId']), old_audit)
        history = self.client.get(path + '/history', headers=headers).json()
        self.assertEqual([v['versionId'] for v in history['versions']], [ids['versionId']])
        self.assertEqual([a['auditId'] for a in history['audits']], [ids['auditId'], aid])

        same = self.advance(dispatch_tests.DUE)
        self.assertEqual(same.status_code, 200, same.text)
        self.assertEqual(same.json()['triggeredAudits'], [])
        next_due = '2027-01-03T00:00:00Z'
        self.assertEqual(self.schedule(headers, path)['nextAuditAt'], next_due)
        next_audit, _ = self.scheduled_acceptance(next_due)
        self.runner.drain()
        completed = self.read_audit(headers, version, next_audit)
        self.assertNotEqual(completed['status'], 'PROCESSING')
        self.assertIsNone(completed['error'])
        manual = self.client.post(version + '/audits', headers=headers, json={})
        self.assertEqual(manual.status_code, 202, manual.text)
        self.assertIsNone(self.read_audit(headers, version, manual.json()['auditId'])['error'])

    def test_fault_stays_armed_after_manual_ordinary_and_other_session_audits(self):
        headers = self.prepare(faults={'scheduled_audit_failures': 1})
        _, _, version = self.scheduled_workbook(headers)
        manual = self.client.post(version + '/audits', headers=headers, json={})
        self.assertEqual(manual.status_code, 202, manual.text)
        self.assertIsNone(self.read_audit(headers, version, manual.json()['auditId'])['error'])
        other = self.prepare('other')
        _, _, foreign_version = self.scheduled_workbook(other)
        foreign_aid, _ = self.scheduled_acceptance(dispatch_tests.DUE, 'other')
        ordinary, path = self.configured(deadline=None)
        audits, _ = self.tick_at(dispatch_tests.DUE)
        ordinary_aid, = audits
        self.runner.drain()
        self.assertIsNone(self.read_audit(other, foreign_version, foreign_aid)['error'])
        ordinary_version = f"{path}/versions/{ordinary['versionId']}"
        self.assertIsNone(self.read_audit(OWNER, ordinary_version, ordinary_aid)['error'])
        self.assertEqual(self.counter(), 1)

    def test_clock_rejections_and_failed_storage_do_not_consume_fault(self):
        headers = self.prepare(faults={'scheduled_audit_failures': 1})
        with patch.object(self.runner, 'drain'):
            self.scheduled_workbook(headers)
        denied = self.client.post(dispatch_tests.CLOCK, headers=headers,
                                  json={'currentTime': dispatch_tests.DUE})
        self.assert_error(denied, 403, 'FORBIDDEN')
        self.assert_error(self.advance('invalid'), 400, 'INVALID_REQUEST')
        self.assert_error(self.advance(dispatch_tests.DUE), 409, 'ACTIVE_OPERATION')
        self.assertEqual(self.counter(), 1)
        self.runner.drain()
        with (patch.object(self.app.state.store, 'job', side_effect=sqlite3.OperationalError('job write')),
              self.assertLogs(level='ERROR')):
            self.assert_error(self.advance(dispatch_tests.DUE), 500, 'STORAGE_FAILED')
        self.assertEqual(self.counter(), 1)
        self.scheduled_acceptance(dispatch_tests.DUE)
        self.assertEqual(self.counter(), 0)

    def test_invalid_and_disabled_setup_leave_no_session_and_duplicate_cannot_rearm(self):
        def setup(faults):
            return self.client.post('/test/setup', headers=ADMIN, json={
                'session_id': 'clock', 'setup': {'faults': faults},
            })

        for faults in ({}, {'scheduled_audit_failure': 1},
                       *({'scheduled_audit_failures': value} for value in (True, 1.0, 0, 2, '1', None))):
            with self.subTest(faults=faults):
                response = setup(faults)
                self.assertEqual(response.status_code, 400, response.text)
                self.assertEqual(set(response.json()), {'message', 'source'})
        with patch.dict(os.environ, {'ENABLE_TEST_FAULTS': 'false'}):
            response = setup({'scheduled_audit_failures': 1})
            self.assertEqual(response.status_code, 403, response.text)
        with self.app.state.store.connect() as db:
            self.assertIsNone(db.execute("SELECT 1 FROM test_sessions WHERE session_id='clock'").fetchone())
            self.assertIsNone(db.execute("SELECT 1 FROM p5_faults WHERE session_id='clock'").fetchone())
        headers = self.prepare(faults={'scheduled_audit_failures': 1})
        self.scheduled_workbook(headers)
        self.scheduled_acceptance(dispatch_tests.DUE)
        self.assertEqual(setup({'scheduled_audit_failures': 1}).status_code, 409)
        self.assertEqual(self.counter(), 0)


class ReportVersionTests(unittest.TestCase):
    setUp = dispatch_tests.DispatchTests.setUp
    upload = dispatch_tests.DispatchTests.upload

    def test_new_report_snapshot_matches_phase5_wire_shape(self):
        ids, version = self.upload(OWNER)
        url = f"{version}/audits/{ids['auditId']}/report"
        response = self.client.get(url, headers=OWNER)
        self.assertEqual(response.status_code, 200, response.text)
        report = response.json()
        self.assertEqual(set(report), {
            'reportVersion', 'specificationVersion', 'workbookId', 'versionId', 'auditId',
            'fileName', 'sha256', 'sourceVersionId', 'auditDate', 'rulesetVersion', 'status',
            'checksPerformed', 'findings', 'decisions', 'approvedChanges', 'unresolvedFindings',
            'manualReviewItems', 'limitations', 'remediationId', 'outputVersionId', 'outputId', 'error',
        })
        self.assertEqual((report['reportVersion'], report['specificationVersion']), ('2.0.0', '3.0.0'))
        self.assertEqual(report['checksPerformed'],
                         ['ALT_TEXT', 'WORKSHEET_NAME', 'TABLE_HEADER', 'MERGED_CELLS', 'LINK_TEXT', 'COLOR_CONTRAST'])
        self.assertEqual(self.client.get(url, headers=OWNER).content, response.content)

    def test_report_download_keeps_the_saved_phase4_snapshot_bytes(self):
        ids, version = self.upload(OWNER)
        store = self.app.state.store
        with store.connect(write=True) as db:
            row = db.execute("SELECT id,payload FROM p4_resources WHERE kind='report' AND version_id=?",
                             (ids['versionId'],)).fetchone()
            payload = json.loads(row['payload'])
            payload['snapshot']['specificationVersion'] = '2.1.0'
            original = encode(payload['snapshot']).encode('utf-8')
            store.update(db, row['id'], payload)
        url = f"{version}/audits/{ids['auditId']}/report"
        for _ in range(2):
            response = self.client.get(url, headers=OWNER)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.content, original)
        with store.connect() as db:
            self.assertEqual(store.get(db, row['id'])['body'], payload)


if __name__ == '__main__':
    unittest.main()
