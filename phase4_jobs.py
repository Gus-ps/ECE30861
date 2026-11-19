"""Transactional job claims and publication; serialize expensive workbook processing."""
from datetime import datetime
import hashlib
import json
import logging
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from uuid import uuid4

from accessibility_checker.finding_ids import RULESET_VERSION
from contracts import Finding
from phase4_store import encode, now
from phase5_clock import effective_now, format_time

RULES = ['ALT_TEXT', 'WORKSHEET_NAME', 'TABLE_HEADER', 'MERGED_CELLS', 'LINK_TEXT', 'COLOR_CONTRAST']
ROOT = Path(__file__).parent


def identifier(kind):
    return kind + '-' + uuid4().hex


def begin_audit(store, db, version, request_id, *, scheduled_at=None):
    """Enqueue an audit within the caller's write transaction."""
    namespace = version['namespace']
    started = scheduled_at if scheduled_at is not None else effective_now(db, namespace)
    aid = identifier('audit')
    audit = dict(auditId=aid, workbookId=version['workbook_id'], versionId=version['id'],
                 rulesetVersion=RULESET_VERSION, status='PROCESSING', startedAt=format_time(started),
                 completedAt=None, findings=[], limitations=[], error=None)
    store.insert(db, 'audit', aid, audit, version['owner'], namespace, version['workbook_id'], version['id'])
    version['body'].update(latestAuditId=aid, status='PROCESSING')
    store.update(db, version['id'], version['body'])

    payload = {'requestId': request_id}
    if scheduled_at is not None:
        payload['trigger'] = 'schedule'
        if store.claim_fault(db, namespace, 'scheduled_audit'):
            payload['scheduledFault'] = True
    elif namespace:
        claimed = db.execute('UPDATE p4_faults SET remaining=0 WHERE session_id=? AND remaining=1',
                             (namespace,))
        payload['fault'] = claimed.rowcount == 1
        if not payload['fault'] and store.claim_fault(db, namespace, 'report'):
            payload['reportFault'] = True
    store.job(db, aid, 'audit', aid, version['id'], namespace, payload)
    return aid


def status(findings):
    if not findings:
        return 'AUDIT_COMPLETE'
    if any(f['classification'] in ('REQUIRES_USER_INPUT', 'AUTOMATICALLY_REMEDIABLE') for f in findings):
        return 'REMEDIATION_AVAILABLE'
    return 'REVIEW_REQUIRED'


def child(mode, source, args=None, output=None):
    command = [sys.executable, str(ROOT / 'service_worker.py'), mode, str(source)]
    if args is not None:
        argfile = source.parent / 'request.json'
        argfile.write_text(encode(args), encoding='utf-8')
        command.append(str(argfile))
    if output:
        command.append(str(output))
    # Capture to files rather than unbounded PIPE buffers. Workbook content and
    # exception messages from the engine never enter application logs.
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        started = time.monotonic()
        completed = subprocess.run(command, stdout=stdout, stderr=stderr,
                                   timeout=180 if mode == 'remediate' else 60)
        size = stdout.tell()
        logging.info('worker_result %s', encode({'mode': mode, 'seconds': round(time.monotonic()-started, 4),
                                                'returnCode': completed.returncode, 'responseBytes': size}))
        if size > 64 * 1024 * 1024:
            raise RuntimeError('RESULT_TOO_LARGE')
        if completed.returncode:
            raise RuntimeError('ENGINE_RESULT_INVALID')
        stdout.seek(0)
        result = json.load(stdout)
    if 'error' in result:
        from remediation import RemediationError
        raise RemediationError(result['error']['code'], result['error']['message'])
    return result['result']


def validated_findings(findings):
    return sorted([Finding.model_validate(f).model_dump() for f in findings],
                  key=lambda f: (f['ruleId'], f['worksheet'], f['target']))


class Runner:
    def __init__(self, store, checker=None):
        self.store, self.checker = store, checker
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.pending_failures = {}

    def recover(self):
        # Phase 3 could leave an audit in PROCESSING when its in-process task
        # was killed. Preserve its identity/bytes and record an explicit loss.
        with self.store.connect(write=True) as db:
            orphans = db.execute("""SELECT id,version_id,namespace,payload FROM p4_resources
                WHERE kind='audit' AND id NOT IN (SELECT resource_id FROM p4_jobs)""").fetchall()
            for row in orphans:
                if json.loads(row['payload'])['status'] != 'PROCESSING':
                    continue
                self.store.job(db, row['id'], 'audit', row['id'], row['version_id'], row['namespace'],
                               {'requestId': identifier('request')})
                db.execute("UPDATE p4_jobs SET state='RUNNING',lease=? WHERE id=?", (identifier('lease'),row['id']))
        with self.store.connect() as db:
            rows = db.execute("SELECT * FROM p4_jobs WHERE state='RUNNING'").fetchall()
        for row in rows:
            self.fail(dict(row), 'WORKER_LOST', 'Processing was interrupted; no candidate output was published.')

    def loop(self):
        while not self.stop.is_set():
            self.poll()
            self.stop.wait(.25)

    def poll(self):
        """Keep the durable consumer alive across temporary storage contention.

        A failed claim transaction rolls back, leaving its job PENDING for the
        next poll. Neither a transient failure nor an empty queue ends the loop.
        This wrapper also prevents background-task exceptions after a 202.
        """
        try:
            # A terminal result can itself be blocked by a temporary DB outage.
            # Retain the failure intent until its lease is durably finalized.
            for job_id, (job, code, message) in list(self.pending_failures.items()):
                self.fail(job, code, message)
                self.pending_failures.pop(job_id, None)
            self.drain()
        except Exception as error:
            logging.error('job_poll_failed %s', encode({'stage': 'queue',
                          'errorType': type(error).__name__, 'retrying': True}))

    def drain(self):
        if not self.lock.acquire(blocking=False):
            return
        try:
            while not self.stop.is_set():
                with self.store.connect(write=True) as db:
                    row = db.execute("""SELECT j.* FROM p4_jobs j JOIN p4_resources r ON r.id=j.resource_id
                        WHERE j.state='PENDING' ORDER BY r.seq LIMIT 1""").fetchone()
                    if row is None:
                        return
                    job = dict(row)
                    lease = uuid4().hex
                    claimed = db.execute("UPDATE p4_jobs SET state='RUNNING',lease=? WHERE id=? AND state='PENDING'", (lease, job['id']))
                    if claimed.rowcount != 1:
                        continue
                    job['lease'] = lease
                try:
                    started = time.monotonic()
                    payload = json.loads(job['payload'])
                    queued = max(0, started - payload.get('_queuedMonotonic', started))
                    logging.info('job_started %s', encode({'jobId': job['id'], 'requestId': payload.get('requestId'),
                                                          'stage': job['kind'], 'queueSeconds': round(queued, 4)}))
                    if queued > 15:
                        self.fail(job, 'PROCESSING_TIMEOUT', 'The processing queue deadline was exceeded.')
                        continue
                    self.execute(job)
                    logging.info('job_finished %s', encode({'jobId': job['id'], 'stage': job['kind'],
                                                           'executionSeconds': round(time.monotonic()-started, 4),
                                                           'queueSeconds': round(queued, 4)}))
                except Exception as error:
                    from remediation import RemediationError
                    logging.error('job_failed %s', encode({'jobId': job['id'], 'stage': job['kind'],
                                                          'errorType': type(error).__name__}))
                    code = ('PROCESSING_TIMEOUT' if isinstance(error, subprocess.TimeoutExpired)
                            else error.code if isinstance(error, RemediationError)
                            else 'SOURCE_INTEGRITY_FAILED' if str(error) == 'SOURCE_INTEGRITY_FAILED'
                            else 'RESULT_TOO_LARGE' if str(error) == 'RESULT_TOO_LARGE'
                            else 'ENGINE_RESULT_INVALID')
                    message = 'Workbook processing could not be completed safely.'
                    self.pending_failures[job['id']] = (job, code, message)
                    self.fail(job, code, message)
                    self.pending_failures.pop(job['id'], None)
        finally:
            self.lock.release()

    def lease(self, db, job):
        row = db.execute('SELECT state,lease FROM p4_jobs WHERE id=?', (job['id'],)).fetchone()
        return row and row['state'] == 'RUNNING' and row['lease'] == job['lease']

    def report(self, version, audit, provenance=None, *, checks_performed=None):
        provenance = provenance or {}
        body = version['body']
        if checks_performed is None:
            checks_performed = [] if audit['error'] else RULES
        return dict(reportVersion='2.0.0', specificationVersion='3.0.0',
                    workbookId=body['workbookId'], versionId=body['versionId'], auditId=audit['auditId'],
                    fileName=body['fileName'], sha256=body['sha256'], sourceVersionId=body['sourceVersionId'],
                    auditDate=audit['completedAt'], rulesetVersion=audit['rulesetVersion'], status=audit['status'],
                    checksPerformed=checks_performed,
                    findings=audit['findings'], decisions=provenance.get('decisions', []),
                    approvedChanges=provenance.get('approvedChanges', []), unresolvedFindings=audit['findings'],
                    manualReviewItems=[f for f in audit['findings'] if f['classification'] == 'MANUAL_REVIEW'],
                    limitations=audit['limitations'], remediationId=provenance.get('remediationId'),
                    outputVersionId=provenance.get('outputVersionId'), outputId=provenance.get('outputId'), error=audit['error'])

    def persist_audit(self, db, version, audit, items=None, provenance=None, *,
                      checks_performed=None, store_report=True):
        completed = effective_now(db, version['namespace'])
        audit['completedAt'] = format_time(max(completed, datetime.fromisoformat(audit['startedAt'])))
        self.store.update(db, audit['auditId'], audit)
        if items is not None:
            self.store.insert(db, 'review', identifier('context'), {'auditId': audit['auditId'], 'items': items},
                              version['owner'], version['namespace'], version['workbook_id'], version['id'])
        if store_report:
            snapshot = self.report(version, audit, provenance, checks_performed=checks_performed)
            self.store.insert(db, 'report', identifier('report'), {'auditId': audit['auditId'], 'snapshot': snapshot},
                              version['owner'], version['namespace'], version['workbook_id'], version['id'])
        if version['body']['latestAuditId'] == audit['auditId']:
            version['body']['status'] = ('REMEDIATED' if version['body']['sourceVersionId'] and audit['status'] != 'PROCESSING_FAILED' else audit['status'])
            self.store.update(db, version['id'], version['body'])

    def provenance(self, db, version):
        if not version['body']['sourceVersionId']:
            return None
        rows = db.execute("SELECT payload FROM p4_resources WHERE kind='remediation' AND workbook_id=? ORDER BY seq", (version['workbook_id'],)).fetchall()
        for row in rows:
            body = json.loads(row['payload'])
            if body['response']['outputVersionId'] == version['id']:
                return body['provenance']

    def execute(self, job):
        args = json.loads(job['payload'])
        with self.store.connect() as db:
            version = self.store.get(db, job['version_id'], 'version')
            data = self.store.bytes(db, version)
            resource = self.store.get(db, job['resource_id'])
            provenance = self.provenance(db, version)
        with tempfile.TemporaryDirectory(prefix='workbook-job-') as directory:
            path = Path(directory) / 'source.xlsx'
            path.write_bytes(data)
            if job['kind'] == 'audit':
                if args.get('trigger') == 'schedule' and args.get('scheduledFault'):
                    self.fail(job, 'TEST_SCHEDULED_AUDIT_FAILURE',
                              'Scheduled audit failure requested by the isolated test session.',
                              {'stage': 'scheduled_audit', 'testOnly': True})
                    return
                if args.get('fault'):
                    self.fail(job, 'TEST_AUDIT_FAILURE', 'Audit failure requested by the isolated test session.',
                              {'stage': 'audit', 'testOnly': True})
                    return
                if self.checker:
                    raw = self.checker(str(path))
                    result = {'findings': list(raw), 'limitations': list(getattr(raw, 'limitations', [])), 'items': []}
                else:
                    result = child('audit', path)
                audit = resource['body']
                audit.update(findings=validated_findings(result['findings']), limitations=sorted(set(result['limitations'])),
                             error=None)
                audit['status'] = status(audit['findings'])
                if args.get('reportFault'):
                    self.fail_report(job)
                    return
                with self.store.connect(write=True) as db:
                    if not self.lease(db, job):
                        return
                    self.persist_audit(db, version, audit, result['items'], provenance)
                    db.execute("UPDATE p4_jobs SET state='DONE' WHERE id=?", (job['id'],))
            else:
                if args.get('remediationFault'):
                    self.fail(job, 'TEST_REMEDIATION_FAILURE',
                              'Remediation failure requested by the isolated test session.',
                              {'stage': 'remediation', 'testOnly': True})
                    return
                output = Path(directory) / 'output.xlsx'
                if any(d['action'] == 'APPLY' for d in args['decisions']):
                    result = child('remediate', path, args, output)
                    output_data = output.read_bytes()
                else:
                    output_data = data
                # Always inventory/re-audit the candidate, including identity-copy decisions.
                output.write_bytes(output_data)
                result_audit = child('audit', output)
                findings = validated_findings(result_audit['findings'])
                vid, aid, oid = identifier('version'), identifier('audit'), identifier('output')
                filename = version['body']['fileName'].rsplit('.', 1)[0][:239] + '-remediated.xlsx'
                newbody = dict(workbookId=version['workbook_id'], versionId=vid, fileName=filename,
                               sha256=hashlib.sha256(output_data).hexdigest(), createdAt=now(),
                               status='REMEDIATED', latestAuditId=aid, sourceVersionId=version['id'])
                audit = dict(auditId=aid, workbookId=version['workbook_id'], versionId=vid, rulesetVersion=RULESET_VERSION,
                             status=status(findings), findings=findings,
                             limitations=sorted(set(result_audit['limitations'])), error=None)
                response = resource['body']['response']
                response.update(status='REMEDIATED', outputVersionId=vid, outputId=oid, auditId=aid, error=None)
                records = args['records']
                provenance = dict(remediationId=resource['id'], outputVersionId=vid, outputId=oid,
                                  decisions=records, approvedChanges=[d for d in records if d['action'] == 'APPLY'])
                resource['body']['provenance'] = provenance
                with self.store.connect(write=True) as db:
                    self.store.fence(db, version['workbook_id'])
                    if not self.lease(db, job):
                        return
                    audit['startedAt'] = format_time(effective_now(db, version['namespace']))
                    self.store.insert(db, 'version', vid, newbody, version['owner'], version['namespace'], version['workbook_id'], vid, output_data)
                    self.store.insert(db, 'audit', aid, audit, version['owner'], version['namespace'], version['workbook_id'], vid)
                    newversion = self.store.get(db, vid)
                    self.persist_audit(db, newversion, audit, result_audit['items'], provenance)
                    self.store.insert(db, 'output', oid, {'versionId': vid}, version['owner'], version['namespace'], version['workbook_id'], vid)
                    self.store.update(db, resource['id'], resource['body'])
                    db.execute("UPDATE p4_jobs SET state='DONE' WHERE id=?", (job['id'],))

    def fail_report(self, job):
        persistence_errors = (sqlite3.Error, TypeError, ValueError)
        if self.store.database.postgres:
            from psycopg import Error
            persistence_errors += (Error,)
        try:
            self.fail(job, 'TEST_REPORT_FAILURE',
                      'Report failure requested by the isolated test session.',
                      {'stage': 'report', 'testOnly': True}, checks_performed=RULES)
        except persistence_errors:
            # The first transaction rolled back. Try to retain the true terminal error.
            try:
                self.fail(job, 'STORAGE_FAILED', 'The audit report could not be stored.', store_report=False)
            except persistence_errors:
                logging.error('Could not record STORAGE_FAILED for audit job %s.', job['id'])

    def fail(self, job, code, message, details=None, *, checks_performed=None, store_report=True):
        with self.store.connect(write=True) as db:
            if not self.lease(db, job):
                return
            resource = self.store.get(db, job['resource_id'])
            if not resource:
                return
            error = dict(code=code, message=message, requestId=json.loads(job['payload'])['requestId'], details=details or {})
            if job['kind'] == 'audit':
                audit = resource['body']
                audit.update(status='PROCESSING_FAILED', findings=[], limitations=[], error=error)
                version = self.store.get(db, job['version_id'])
                self.persist_audit(db, version, audit, provenance=self.provenance(db, version),
                                   checks_performed=checks_performed, store_report=store_report)
            else:
                resource['body']['response'].update(status='PROCESSING_FAILED', outputVersionId=None, outputId=None, auditId=None, error=error)
                self.store.update(db, resource['id'], resource['body'])
            db.execute("UPDATE p4_jobs SET state='FAILED' WHERE id=?", (job['id'],))
