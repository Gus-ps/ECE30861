"""Transactional job claims and publication; serialize expensive workbook processing."""
import hashlib
import json
import logging
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from uuid import uuid4

from contracts import Finding
from phase4_store import encode, now

RULES = ['ALT_TEXT', 'WORKSHEET_NAME', 'TABLE_HEADER', 'MERGED_CELLS', 'LINK_TEXT', 'COLOR_CONTRAST']
ROOT = Path(__file__).parent


def identifier(kind):
    return kind + '-' + uuid4().hex


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
    completed = subprocess.run(command, capture_output=True, text=True, encoding='utf-8',
                               timeout=180 if mode == 'remediate' else 60)
    if completed.returncode:
        logging.error('Workbook worker failed: %s', completed.stderr[-3000:])
        raise RuntimeError('ENGINE_RESULT_INVALID')
    result = json.loads(completed.stdout)
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
            self.drain()
            self.stop.wait(.25)

    def drain(self):
        if not self.lock.acquire(blocking=False):
            return
        try:
            while not self.stop.is_set():
                with self.store.connect(write=True) as db:
                    row = db.execute("SELECT * FROM p4_jobs WHERE state='PENDING' ORDER BY id LIMIT 1").fetchone()
                    if row is None:
                        return
                    job = dict(row)
                    lease = uuid4().hex
                    claimed = db.execute("UPDATE p4_jobs SET state='RUNNING',lease=? WHERE id=? AND state='PENDING'", (lease, job['id']))
                    if claimed.rowcount != 1:
                        continue
                    job['lease'] = lease
                try:
                    self.execute(job)
                except Exception as error:
                    from remediation import RemediationError
                    logging.exception('Phase 4 job failed: %s', job['id'])
                    code = ('PROCESSING_TIMEOUT' if isinstance(error, subprocess.TimeoutExpired)
                            else error.code if isinstance(error, RemediationError)
                            else 'SOURCE_INTEGRITY_FAILED' if str(error) == 'SOURCE_INTEGRITY_FAILED'
                            else 'ENGINE_RESULT_INVALID')
                    self.fail(job, code, 'Workbook processing could not be completed safely.')
        finally:
            self.lock.release()

    def lease(self, db, job):
        row = db.execute('SELECT state,lease FROM p4_jobs WHERE id=?', (job['id'],)).fetchone()
        return row and row['state'] == 'RUNNING' and row['lease'] == job['lease']

    def report(self, version, audit, provenance=None):
        provenance = provenance or {}
        body = version['body']
        return dict(reportVersion='2.0.0', specificationVersion='2.1.0',
                    workbookId=body['workbookId'], versionId=body['versionId'], auditId=audit['auditId'],
                    fileName=body['fileName'], sha256=body['sha256'], sourceVersionId=body['sourceVersionId'],
                    auditDate=audit['completedAt'], rulesetVersion=audit['rulesetVersion'], status=audit['status'],
                    checksPerformed=[] if audit['error'] else RULES,
                    findings=audit['findings'], decisions=provenance.get('decisions', []),
                    approvedChanges=provenance.get('approvedChanges', []), unresolvedFindings=audit['findings'],
                    manualReviewItems=[f for f in audit['findings'] if f['classification'] == 'MANUAL_REVIEW'],
                    limitations=audit['limitations'], remediationId=provenance.get('remediationId'),
                    outputVersionId=provenance.get('outputVersionId'), outputId=provenance.get('outputId'), error=audit['error'])

    def persist_audit(self, db, version, audit, items=None, provenance=None):
        self.store.update(db, audit['auditId'], audit)
        if items is not None:
            self.store.insert(db, 'review', identifier('context'), {'auditId': audit['auditId'], 'items': items},
                              version['owner'], version['namespace'], version['workbook_id'], version['id'])
        snapshot = self.report(version, audit, provenance)
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
                             completedAt=now(), error=None)
                audit['status'] = status(audit['findings'])
                with self.store.connect(write=True) as db:
                    if not self.lease(db, job):
                        return
                    self.persist_audit(db, version, audit, result['items'], provenance)
                    db.execute("UPDATE p4_jobs SET state='DONE' WHERE id=?", (job['id'],))
            else:
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
                audit = dict(auditId=aid, workbookId=version['workbook_id'], versionId=vid, rulesetVersion='2.0.0',
                             status=status(findings), startedAt=now(), completedAt=now(), findings=findings,
                             limitations=sorted(set(result_audit['limitations'])), error=None)
                response = resource['body']['response']
                response.update(status='REMEDIATED', outputVersionId=vid, outputId=oid, auditId=aid, error=None)
                records = args['records']
                provenance = dict(remediationId=resource['id'], outputVersionId=vid, outputId=oid,
                                  decisions=records, approvedChanges=[d for d in records if d['action'] == 'APPLY'])
                resource['body']['provenance'] = provenance
                with self.store.connect(write=True) as db:
                    if not self.lease(db, job):
                        return
                    self.store.insert(db, 'version', vid, newbody, version['owner'], version['namespace'], version['workbook_id'], vid, output_data)
                    self.store.insert(db, 'audit', aid, audit, version['owner'], version['namespace'], version['workbook_id'], vid)
                    newversion = self.store.get(db, vid)
                    self.persist_audit(db, newversion, audit, result_audit['items'], provenance)
                    self.store.insert(db, 'output', oid, {'versionId': vid}, version['owner'], version['namespace'], version['workbook_id'], vid)
                    self.store.update(db, resource['id'], resource['body'])
                    db.execute("UPDATE p4_jobs SET state='DONE' WHERE id=?", (job['id'],))

    def fail(self, job, code, message, details=None):
        with self.store.connect(write=True) as db:
            if not self.lease(db, job):
                return
            resource = self.store.get(db, job['resource_id'])
            if not resource:
                return
            error = dict(code=code, message=message, requestId=json.loads(job['payload'])['requestId'], details=details or {})
            if job['kind'] == 'audit':
                audit = resource['body']
                audit.update(status='PROCESSING_FAILED', completedAt=now(), findings=[], limitations=[], error=error)
                version = self.store.get(db, job['version_id'])
                self.persist_audit(db, version, audit, provenance=self.provenance(db, version))
            else:
                resource['body']['response'].update(status='PROCESSING_FAILED', outputVersionId=None, outputId=None, auditId=None, error=error)
                self.store.update(db, resource['id'], resource['body'])
            db.execute("UPDATE p4_jobs SET state='FAILED' WHERE id=?", (job['id'],))
