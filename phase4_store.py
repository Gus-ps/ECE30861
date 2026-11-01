"""Additive Phase 4 persistence; existing Phase 3 bytes and audit observations survive."""
import hashlib
import json
from datetime import datetime, timezone


def now():
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def encode(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


class Store:
    def __init__(self, database):
        self.database = database
        self.connect = database.connect
        with self.connect(write=True) as db:
            sequence = 'BIGSERIAL PRIMARY KEY' if database.postgres else 'INTEGER PRIMARY KEY AUTOINCREMENT'
            binary = 'BYTEA' if database.postgres else 'BLOB'
            db.execute(f'''CREATE TABLE IF NOT EXISTS p4_resources (
                seq {sequence}, id TEXT UNIQUE NOT NULL, kind TEXT NOT NULL,
                workbook_id TEXT, version_id TEXT, owner TEXT NOT NULL, namespace TEXT,
                payload TEXT NOT NULL, data {binary})''')
            db.execute('CREATE INDEX IF NOT EXISTS p4_workbook_sequence ON p4_resources(workbook_id,seq)')
            db.execute('''CREATE TABLE IF NOT EXISTS p4_jobs (
                id TEXT PRIMARY KEY, kind TEXT NOT NULL, resource_id TEXT NOT NULL,
                version_id TEXT NOT NULL, namespace TEXT, state TEXT NOT NULL,
                lease TEXT, payload TEXT NOT NULL)''')
            db.execute('''CREATE TABLE IF NOT EXISTS p4_keys (
                scope TEXT NOT NULL, key TEXT NOT NULL, digest TEXT NOT NULL,
                response TEXT NOT NULL, namespace TEXT, workbook_id TEXT NOT NULL,
                PRIMARY KEY(scope,key))''')
            db.execute('CREATE TABLE IF NOT EXISTS p4_meta (key TEXT PRIMARY KEY,value TEXT NOT NULL)')
            db.execute('''CREATE TABLE IF NOT EXISTS p4_faults (
                session_id TEXT PRIMARY KEY, remaining INTEGER NOT NULL)''')
            if not db.execute("SELECT 1 FROM p4_meta WHERE key='legacy_import'").fetchone():
                self.import_legacy(db)
                db.execute("INSERT INTO p4_meta VALUES ('legacy_import','1')")
            if not database.postgres:
                db.execute('''CREATE TRIGGER IF NOT EXISTS p4_immutable_bytes
                    BEFORE UPDATE OF data ON p4_resources WHEN OLD.kind='version'
                    BEGIN SELECT RAISE(ABORT,'Source bytes are immutable'); END''')

    def import_legacy(self, db):
        rows = db.execute('''SELECT v.workbook_id,v.version_id,v.owner,v.filename,v.sha256,
            v.created_at,t.session_id FROM versions v LEFT JOIN test_workbooks t
            ON v.workbook_id=t.workbook_id ORDER BY v.created_at,v.workbook_id''').fetchall()
        for row in rows:
            wb, vid, owner, namespace = row['workbook_id'], row['version_id'], row['owner'], row['session_id']
            self.insert(db, 'workbook', wb, {'workbookId': wb}, owner, namespace, wb)
            audits = db.execute('SELECT * FROM audits WHERE version_id=? ORDER BY started_at,audit_id', (vid,)).fetchall()
            payload = dict(workbookId=wb, versionId=vid, fileName=row['filename'], sha256=row['sha256'],
                           createdAt=row['created_at'], sourceVersionId=None,
                           status=audits[-1]['status'] if audits else 'PROCESSING_FAILED',
                           latestAuditId=audits[-1]['audit_id'] if audits else None)
            self.insert(db, 'version', vid, payload, owner, namespace, wb, vid)
            # Copy BLOB inside SQLite/Postgres rather than loading the whole legacy dataset into Python.
            db.execute('UPDATE p4_resources SET data=(SELECT original FROM versions WHERE version_id=?) WHERE id=?', (vid, vid))
            for audit in audits:
                error = json.loads(audit['error']) if audit['error'] else None
                if error:
                    error.setdefault('requestId', audit['request_id'])
                    error.setdefault('details', {})
                body = dict(auditId=audit['audit_id'], workbookId=wb, versionId=vid,
                            rulesetVersion=audit['ruleset_version'], status=audit['status'],
                            startedAt=audit['started_at'], completedAt=audit['completed_at'],
                            findings=json.loads(audit['findings']), limitations=json.loads(audit['limitations']), error=error)
                self.insert(db, 'audit', audit['audit_id'], body, owner, namespace, wb, vid)

    def insert(self, db, kind, resource_id, payload, owner, namespace=None, workbook_id=None, version_id=None, data=None):
        db.execute('''INSERT INTO p4_resources
            (id,kind,workbook_id,version_id,owner,namespace,payload,data) VALUES (?,?,?,?,?,?,?,?)''',
            (resource_id, kind, workbook_id, version_id, owner, namespace, encode(payload), data))

    def get(self, db, resource_id, kind=None):
        row = db.execute('''SELECT id,kind,workbook_id,version_id,owner,namespace,payload,seq
            FROM p4_resources WHERE id=?''', (resource_id,)).fetchone()
        if row is None or (kind and row['kind'] != kind):
            return None
        result = dict(row)
        result['body'] = json.loads(result.pop('payload'))
        return result

    def update(self, db, resource_id, body):
        db.execute('UPDATE p4_resources SET payload=? WHERE id=?', (encode(body), resource_id))

    def bytes(self, db, version):
        row = db.execute('SELECT data FROM p4_resources WHERE id=?', (version['id'],)).fetchone()
        data = bytes(row['data'])
        if hashlib.sha256(data).hexdigest() != version['body']['sha256']:
            raise ValueError('SOURCE_INTEGRITY_FAILED')
        return data

    def active(self, db, version_id):
        return db.execute("SELECT 1 FROM p4_jobs WHERE version_id=? AND state IN ('PENDING','RUNNING')", (version_id,)).fetchone() is not None

    def job(self, db, job_id, kind, resource_id, version_id, namespace, payload):
        db.execute('INSERT INTO p4_jobs VALUES (?,?,?,?,?,?,?,?)',
                   (job_id, kind, resource_id, version_id, namespace, 'PENDING', None, encode(payload)))
