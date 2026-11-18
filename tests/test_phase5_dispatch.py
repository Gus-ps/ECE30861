"""REQ-12 / AC-12 / AC-14.

P5-SCHEDULE-BEFORE-DUE, P5-SCHEDULE-EXACT-DUE, P5-SCHEDULE-COALESCE,
P5-SCHEDULE-SAME-TIME, P5-SCHEDULE-LATEST-UPLOAD, P5-SCHEDULE-LATEST-OUTPUT,
P5-SCHEDULE-OLD-REAUDIT, P5-SCHEDULE-BUSY-AUDIT, P5-SCHEDULE-BUSY-REMEDIATION,
P5-SCHEDULE-TWO-WORKBOOKS, P5-SCHEDULE-DISABLE, P5-CLOCK-SAME,
P5-CLOCK-WORK-LIMIT, P5-CLOCK-STORAGE-ROLLBACK, P5-CLOCK-LOST-ACK,
P5-CLOCK-REAL-TIME, P5-DELETE-CANCEL-FUTURE.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import sqlite3
import threading
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import create_app
from phase4_jobs import RULESET_VERSION
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

    def configure(self, headers, workbook_path, interval=1, *, enabled=True):
        body = {'enabled': enabled}
        if enabled:
            body['intervalDays'] = interval
        response = self.client.put(workbook_path + '/schedule', headers=headers, json=body)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def schedule(self, headers, workbook_path):
        response = self.client.get(workbook_path + '/schedule', headers=headers)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def assert_advance(self, instant, count):
        response = self.advance(instant)
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(set(body), {'currentTime', 'triggeredAudits', 'triggeredNotifications'})
        self.assertEqual(body['currentTime'], instant)
        self.assertEqual(body['triggeredNotifications'], [])
        self.assertEqual(len(body['triggeredAudits']), count)
        return body['triggeredAudits']

    def assert_error(self, response, status, code):
        self.assertEqual(response.status_code, status, response.text)
        self.assertEqual(response.json()['code'], code)
        self.assertEqual(response.json()['requestId'], response.headers['X-Request-ID'])

    def snapshot(self):
        with self.app.state.database.connect() as db:
            return {
                table: [tuple(row) for row in db.execute(f'SELECT * FROM {table} ORDER BY 1')]
                for table in ('p5_clocks', 'p5_schedules', 'p4_resources', 'p4_jobs')
            }

    def scheduled_workbook(self, headers, interval=1):
        ids, version = self.upload(headers)
        path = version.rsplit('/versions/', 1)[0]
        self.configure(headers, path, interval)
        return ids, path, version

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

    def test_before_due_and_exact_due_preserve_source_and_version(self):
        headers = self.prepare()
        ids, path, version = self.scheduled_workbook(headers)
        source = self.client.get(version + '/source', headers=headers).content
        initial_audit = self.read_audit(headers, version, ids['auditId'])
        report_url = f"{version}/audits/{ids['auditId']}/report"
        old_report = self.client.get(report_url, headers=headers)
        self.assertEqual(old_report.status_code, 200, old_report.text)
        self.assert_advance('2027-01-01T23:59:59.999999Z', 0)
        self.assertEqual(self.schedule(headers, path)['nextAuditAt'], DUE)

        aid, = self.assert_advance(DUE, 1)
        accepted = self.read_audit(headers, version, aid)
        self.assertEqual(accepted['status'], 'PROCESSING')
        self.assertEqual(accepted['rulesetVersion'], RULESET_VERSION)
        self.assertEqual(accepted['startedAt'], DUE)
        self.runner.drain()
        completed = self.read_audit(headers, version, aid)
        self.assertEqual(completed['completedAt'], DUE)
        self.assertEqual(self.client.get(version + '/source', headers=headers).content, source)
        self.assertEqual(self.read_audit(headers, version, ids['auditId']), initial_audit)
        self.assertEqual(self.client.get(report_url, headers=headers).content, old_report.content)
        history = self.client.get(path + '/history', headers=headers).json()
        self.assertEqual([v['versionId'] for v in history['versions']], [ids['versionId']])
        self.assertEqual([a['auditId'] for a in history['audits']], [ids['auditId'], aid])
        self.assertEqual(self.schedule(headers, path)['nextAuditAt'], '2027-01-03T00:00:00Z')

    def test_coalesces_with_original_cadence_and_replay_has_no_effect(self):
        headers = self.prepare()
        _, path, _ = self.scheduled_workbook(headers)
        instant = '2027-01-05T12:00:00Z'
        self.assert_advance(instant, 1)
        self.assertEqual(self.schedule(headers, path)['nextAuditAt'], '2027-01-06T00:00:00Z')
        before = self.snapshot()
        self.assert_advance(instant, 0)
        self.assertEqual(self.snapshot(), before)

    def test_ninety_day_cadence_vector(self):
        headers = self.prepare()
        _, path, _ = self.scheduled_workbook(headers, interval=90)
        self.assert_advance('2027-04-01T00:00:00Z', 1)
        self.assertEqual(self.schedule(headers, path)['nextAuditAt'], '2027-06-30T00:00:00Z')

    def test_latest_upload_wins_even_after_old_version_reaudit(self):
        headers = self.prepare()
        _, path, original = self.scheduled_workbook(headers)
        newest, new_version = self.upload(headers, path + '/versions')
        reaudit = self.client.post(original + '/audits', headers=headers, json={})
        self.assertEqual(reaudit.status_code, 202, reaudit.text)
        self.assertEqual(self.schedule(headers, path)['nextAuditAt'], DUE)
        aid, = self.assert_advance(DUE, 1)
        self.assertEqual(self.read_audit(headers, new_version, aid)['versionId'], newest['versionId'])

    def test_latest_remediation_output_wins_without_delaying_due_time(self):
        headers = self.prepare()
        ids, path, original = self.scheduled_workbook(headers)
        rid = self.remediate(headers, original, ids['auditId'])
        result = self.client.get(f'/api/v1/remediations/{rid}', headers=headers).json()
        self.assertEqual(result['status'], 'REMEDIATED')
        vid = result['outputVersionId']
        self.assertEqual(self.schedule(headers, path)['nextAuditAt'], DUE)
        aid, = self.assert_advance(DUE, 1)
        self.assertEqual(self.read_audit(headers, f'{path}/versions/{vid}', aid)['versionId'], vid)

    def assert_busy_then_retry(self):
        before = self.snapshot()
        self.assert_error(self.advance(DUE), 409, 'ACTIVE_OPERATION')
        self.assertEqual(self.snapshot(), before)
        self.runner.drain()
        return self.assert_advance(DUE, 2)

    def test_busy_audit_rejects_entire_batch_then_retry_succeeds(self):
        headers = self.prepare()
        self.scheduled_workbook(headers)
        with patch.object(self.runner, 'drain'):
            self.scheduled_workbook(headers)
        self.assert_busy_then_retry()

    def test_busy_remediation_rejects_entire_batch_then_selects_output(self):
        headers = self.prepare()
        self.scheduled_workbook(headers)
        ids, path, version = self.scheduled_workbook(headers)
        with patch.object(self.runner, 'drain'):
            rid = self.remediate(headers, version, ids['auditId'])
        audits = self.assert_busy_then_retry()
        result = self.client.get(f'/api/v1/remediations/{rid}', headers=headers).json()
        vid = result['outputVersionId']
        self.assertEqual(self.schedule(headers, path)['versionId'], vid)
        output = self.client.get(f'{path}/versions/{vid}', headers=headers).json()
        self.assertIn(output['latestAuditId'], audits)

    def test_batch_orders_old_due_instants_then_ids_and_keeps_access_isolated(self):
        owner = self.prepare()
        other = {**owner, 'Authorization': 'Bearer b'}
        _, _, later_version = self.scheduled_workbook(owner, interval=2)
        _, earlier, earlier_version = self.scheduled_workbook(other)
        _, tied, tied_version = self.scheduled_workbook(owner)
        foreign = self.prepare('other-clock')
        _, outside, _ = self.scheduled_workbook(foreign)
        with self.app.state.database.connect(write=True) as db:
            # Equivalent timestamp encodings must compare and tie by instant.
            db.execute('UPDATE p5_schedules SET next_audit_at=? WHERE workbook_id=?',
                       ('2027-01-02T00:00:00.000000Z', earlier.rsplit('/', 1)[1]))
        expected = sorted(((earlier_version, other), (tied_version, owner))) + [(later_version, owner)]
        audits = self.assert_advance('2027-01-03T00:00:00Z', 3)
        ids_by_version = {}
        for aid, (version, headers) in zip(audits, expected, strict=True):
            self.assertEqual(self.read_audit(headers, version, aid)['auditId'], aid)
            ids_by_version[version] = aid
        foreign_aid = ids_by_version[earlier_version]
        denied = self.client.get(f'{earlier_version}/audits/{foreign_aid}', headers=owner)
        self.assertEqual(denied.status_code, 403)
        self.assertNotIn(foreign_aid, denied.text)
        self.assertEqual(self.schedule(foreign, outside)['nextAuditAt'], DUE)

    def test_disabled_schedule_keeps_history(self):
        headers = self.prepare()
        _, path, _ = self.scheduled_workbook(headers)
        self.assert_advance(DUE, 1)
        self.runner.drain()
        history = self.client.get(path + '/history', headers=headers).json()
        self.assertIsNone(self.configure(headers, path, enabled=False)['nextAuditAt'])
        self.assert_advance('2027-02-01T00:00:00Z', 0)
        self.assertEqual(self.client.get(path + '/history', headers=headers).json(), history)

    def test_work_limit_rejects_without_changes(self):
        headers = self.prepare()
        for _ in range(2):
            self.scheduled_workbook(headers)
        before = self.snapshot()
        with patch('phase5_clock.AUDIT_WORK_LIMIT', 1):
            self.assert_error(self.advance(DUE), 409, 'CLOCK_WORK_LIMIT')
        self.assertEqual(self.snapshot(), before)

    def test_storage_failure_rolls_back_previously_accepted_audit(self):
        headers = self.prepare()
        for _ in range(2):
            self.scheduled_workbook(headers)
        before = self.snapshot()
        store = self.app.state.store
        write_job = store.job

        def fail_second(*args):
            if job_write.call_count == 2:
                raise sqlite3.OperationalError('simulated job insert failure')
            return write_job(*args)

        with patch.object(store, 'job', side_effect=fail_second) as job_write, self.assertLogs(level='ERROR'):
            self.assert_error(self.advance(DUE), 500, 'STORAGE_FAILED')
        self.assertEqual(job_write.call_count, 2)
        self.assertEqual(self.snapshot(), before)
        self.assert_advance(DUE, 2)

    def test_cadence_overflow_rejects_without_changes(self):
        headers = self.prepare(clock={'currentTime': '9999-12-29T00:00:00Z'})
        self.scheduled_workbook(headers)
        before = self.snapshot()
        self.assert_error(self.advance('9999-12-31T00:00:00Z'), 400, 'TIME_RANGE_EXCEEDED')
        self.assertEqual(self.snapshot(), before)

    def test_scheduled_audit_does_not_consume_manual_fault(self):
        headers = self.prepare(faults={'audit_failures': 1})
        # Upload consumes the configured one-shot fault. Re-arm it locally to
        # exercise a scheduled job with the counter still available.
        _, _, version = self.scheduled_workbook(headers)
        with self.app.state.database.connect(write=True) as db:
            db.execute("UPDATE p4_faults SET remaining=1 WHERE session_id='clock'")
        aid, = self.assert_advance(DUE, 1)
        with self.app.state.database.connect() as db:
            payload = db.execute('SELECT payload FROM p4_jobs WHERE resource_id=?', (aid,)).fetchone()
            self.assertEqual(json.loads(payload['payload'])['trigger'], 'schedule')
        self.runner.drain()
        self.assertIsNone(self.read_audit(headers, version, aid)['error'])
        manual = self.client.post(version + '/audits', headers=headers, json={})
        self.assertEqual(manual.status_code, 202, manual.text)
        audit = self.read_audit(headers, version, manual.json()['auditId'])
        self.assertEqual(audit['error']['code'], 'TEST_AUDIT_FAILURE')

    def test_deletion_before_due_and_during_accepted_scheduled_audit(self):
        headers = self.prepare()
        _, deleted, _ = self.scheduled_workbook(headers)
        _, active, version = self.scheduled_workbook(headers)
        self.assertEqual(self.client.delete(deleted, headers=headers).status_code, 204)
        aid, = self.assert_advance(DUE, 1)
        self.assertEqual(self.read_audit(headers, version, aid)['status'], 'PROCESSING')
        self.assert_error(self.client.delete(active, headers=headers), 409, 'ACTIVE_OPERATION')
        self.runner.drain()
        self.assertEqual(self.client.delete(active, headers=headers).status_code, 204)
        self.assert_advance('2027-02-01T00:00:00Z', 0)

    def test_failed_scheduled_audit_leaves_next_occurrence_due(self):
        headers = self.prepare()
        ids, path, version = self.scheduled_workbook(headers)
        aid, = self.assert_advance(DUE, 1)
        with patch.object(self.runner, 'checker', side_effect=RuntimeError('engine failed')):
            with self.assertLogs(level='ERROR'):
                self.runner.drain()
        failed = self.read_audit(headers, version, aid)
        self.assertEqual(failed['status'], 'PROCESSING_FAILED')
        self.assertEqual(failed['completedAt'], DUE)
        self.assertEqual(failed['findings'], [])
        source = self.client.get(version + '/source', headers=headers)
        self.assertEqual(source.status_code, 200, source.text)
        self.assertNotEqual(self.read_audit(headers, version, ids['auditId'])['status'], 'PROCESSING_FAILED')
        next_due = '2027-01-03T00:00:00Z'
        self.assertEqual(self.schedule(headers, path)['nextAuditAt'], next_due)
        self.assert_advance(DUE, 0)
        self.assert_advance(next_due, 1)

    def test_clock_jump_does_not_change_running_worker_lease(self):
        headers = self.prepare()
        _, _, scheduled = self.scheduled_workbook(headers)
        with patch.object(self.runner, 'drain'):
            running, version = self.upload(headers)
        entered, release = threading.Event(), threading.Event()

        def hold_checker(_):
            entered.set()
            if not release.wait(10):
                raise TimeoutError('Test did not release the checker.')
            return []

        aid = running['auditId']
        with patch.object(self.runner, 'checker', side_effect=hold_checker), ThreadPoolExecutor() as pool:
            worker = pool.submit(self.runner.drain)
            try:
                self.assertTrue(entered.wait(10))
                with self.app.state.database.connect() as db:
                    before = tuple(db.execute('SELECT state,lease FROM p4_jobs WHERE id=?', (aid,)).fetchone())
                self.assertEqual(before[0], 'RUNNING')
                self.assertIsNotNone(before[1])
                instant = '2099-01-01T00:00:00Z'
                due, = self.assert_advance(instant, 1)
                self.assertEqual(self.read_audit(headers, scheduled, due)['status'], 'PROCESSING')
                with self.app.state.database.connect() as db:
                    after = tuple(db.execute('SELECT state,lease FROM p4_jobs WHERE id=?', (aid,)).fetchone())
                self.assertEqual(after, before)
            finally:
                release.set()
            worker.result(timeout=10)
        audit = self.read_audit(headers, version, aid)
        self.assertEqual(audit['status'], 'AUDIT_COMPLETE')
        self.assertEqual((audit['startedAt'], audit['completedAt']), (START, instant))
