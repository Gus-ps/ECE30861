"""Upload site and HTTP operations 1, 2, 4 and 5 from PROMPT.md."""
import asyncio
from datetime import datetime, timezone
import hashlib
import io
import json
import logging
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
from uuid import uuid4
import zipfile

from fastapi import BackgroundTasks, Depends, FastAPI, File, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from starlette.exceptions import HTTPException

from contracts import Audit, Error, Finding, Health, Identifier, UploadResponse, WorkbookVersion
from database import Database

ROOT = Path(__file__).parent
MAX_UPLOAD = 25_000_000
RULESET_VERSION = '1.0'


def utc_now():
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def process_audit(database, audit_id, checker=None):
    """Integration hook only: the team's checker supplies accessibility findings."""
    with database.connect() as db:
        audit = db.execute('SELECT * FROM audits WHERE audit_id=?', (audit_id,)).fetchone()
        version = db.execute('SELECT original FROM versions WHERE version_id=?', (audit['version_id'],)).fetchone()
    findings, limitations, error = [], [], None
    status = 'PROCESSING_FAILED'
    if checker is None:
        # TODO: Pass the team's path-based accessibility checker into create_app.
        # Checker implementations and accessibility rules belong to that teammate.
        limitations = ['Accessibility checker is not integrated.']
        error = {'code': 'CHECKER_NOT_CONFIGURED', 'message': limitations[0],
                 'requestId': audit['request_id'], 'details': {}}
    else:
        try:
            data = bytes(version['original'])
            with tempfile.TemporaryDirectory(prefix='workbook-audit-') as directory:
                path = Path(directory) / 'source.xlsx'
                path.write_bytes(data)
                for raw in checker(str(path)):
                    item = Finding.model_validate(raw).model_dump()
                    identity = [audit['workbook_id'], audit['ruleset_version'],
                                item['ruleId'], item['worksheet'], item['target']]
                    item['findingId'] = hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode()).hexdigest()
                    findings.append(item)
                if path.read_bytes() != data:
                    raise ValueError('Checker modified its input.')
            findings.sort(key=lambda item: (item['ruleId'], item['worksheet'], item['target']))
            status = 'REVIEW_REQUIRED' if findings else 'AUDIT_COMPLETE'
        except Exception:
            logging.exception('Audit failed: %s', audit_id)
            findings = []
            error = {'code': 'AUDIT_FAILED', 'message': 'Accessibility audit could not be completed.',
                     'requestId': audit['request_id'], 'details': {}}
    with database.connect(write=True) as db:
        db.execute('''UPDATE audits SET status=?, completed_at=?, findings=?, limitations=?, error=?
            WHERE audit_id=?''', (status, utc_now(), json.dumps(findings), json.dumps(limitations),
                                 json.dumps(error) if error else None, audit_id))


def load_workbook_validator():
    path = Path(os.getenv('VALIDATOR_PATH', str(ROOT / 'validity_check.py')))
    if not path.is_file():
        return None
    path = path.resolve()

    def validate(filepath):
        # Isolation closes the supplied checker's file handles before Windows
        # removes the temporary file. Keep printed messages separate from JSON.
        completed = subprocess.run(
            [sys.executable, '-c', '''import contextlib, io, json, runpy, sys
output = io.StringIO()
with contextlib.redirect_stdout(output):
    module = runpy.run_path(sys.argv[1])
    checker = module.get("check_validity", module.get("validate_file"))
    result = checker(sys.argv[2])
    errors = result if isinstance(result, list) else []
    if result is False or type(result) is int and result == 0:
        explain = module.get("validate_file")
        if explain is not None and explain is not checker:
            explanation = explain(sys.argv[2])
            if isinstance(explanation, list):
                errors = explanation
print(json.dumps({"result": result, "output": output.getvalue(), "errors": errors}))
''', str(path), filepath], capture_output=True, text=True, timeout=60)
        if completed.stderr:
            print(completed.stderr, end='', file=sys.stderr, flush=True)
        completed.check_returncode()
        payload = json.loads(completed.stdout)
        if payload['output']:
            print(payload['output'], end='', flush=True)
        result = payload['result']
        if isinstance(result, list) and all(isinstance(error, str) for error in result):
            result = not result
        if type(result) in (bool, int) and result in (False, 0):
            errors = payload['errors']
            if not errors and payload['output'].strip():
                errors = [payload['output'].strip()]
            raise ApiError(422, 'INVALID_WORKBOOK', 'Workbook is invalid.', {'valid': False, 'errors': errors})
        return result
    return validate


class ApiError(Exception):
    def __init__(self, status, code, message, details=None):
        self.status, self.code, self.message = status, code, message
        self.details = details or {}


def create_app(db_path=None, tokens=None, workbook_validator=None, accessibility_checker=None):
    if workbook_validator is None:
        workbook_validator = load_workbook_validator()
    checker = accessibility_checker
    credentials = tokens if tokens is not None else json.loads(os.getenv('API_TOKENS_JSON', '{}'))
    if not isinstance(credentials, dict) or any(
        not isinstance(k, str) or not k or not isinstance(v, str) or not v
        for k, v in credentials.items()
    ):
        raise ValueError('API_TOKENS_JSON must map nonempty token strings to user IDs')
    database = Database(db_path)
    database.initialize()
    connect = database.connect

    app = FastAPI(title='Workbook accessibility service', version='1.0',
                  responses={status: {'model': Error} for status in (400, 401, 403, 404, 409, 413, 415, 422, 500, 503)})
    app.state.database = database

    def error_response(request, status, code, message, details=None):
        body = Error(code=code, message=message, requestId=request.state.request_id, details=details or {})
        return JSONResponse(status_code=status, content=body.model_dump())

    @app.middleware('http')
    async def request_id(request: Request, call_next):
        request.state.request_id = 'request-' + uuid4().hex
        try:
            response = await call_next(request)
        except Exception:
            logging.exception('Unhandled request failure: %s', request.state.request_id)
            response = error_response(request, 500, 'INTERNAL_ERROR', 'An internal failure occurred.')
        response.headers['X-Request-ID'] = request.state.request_id
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.exception_handler(ApiError)
    async def api_error(request, exc):
        return error_response(request, exc.status, exc.code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def malformed(request, exc):
        return error_response(request, 400, 'INVALID_REQUEST', 'Missing or malformed request data.')

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        return error_response(request, exc.status_code, 'HTTP_ERROR', str(exc.detail))

    def user(request: Request):
        scheme, _, token = request.headers.get('authorization', '').partition(' ')
        if scheme.lower() == 'bearer' and token:
            for expected, identity in credentials.items():
                if secrets.compare_digest(token.encode(), expected.encode()):
                    return identity
        raise ApiError(401, 'UNAUTHORIZED', 'A valid bearer token is required.')

    def version(db, workbook_id, version_id, identity):
        row = db.execute('SELECT * FROM versions WHERE workbook_id=? AND version_id=?',
                         (workbook_id, version_id)).fetchone()
        if row is None:
            raise ApiError(404, 'NOT_FOUND', 'Workbook version does not exist.')
        if row['owner'] != identity:
            raise ApiError(403, 'FORBIDDEN', 'You cannot access this workbook.')
        return row

    def insert_audit(db, workbook_id, version_id, request_id):
        audit_id = 'audit-' + uuid4().hex
        db.execute('''INSERT INTO audits (audit_id, workbook_id, version_id, ruleset_version,
            status, started_at, request_id) VALUES (?, ?, ?, ?, 'PROCESSING', ?, ?)''',
            (audit_id, workbook_id, version_id, RULESET_VERSION, utc_now(), request_id))
        return audit_id

    @app.get('/', include_in_schema=False)
    def index():
        return FileResponse(ROOT / 'static' / 'index.html')

    @app.get('/api/v1/health', response_model=Health)
    def health():
        try:
            with connect() as db:
                db.execute('SELECT 1').fetchone()
        except Exception:
            raise ApiError(503, 'SERVICE_UNAVAILABLE', 'Storage is unavailable.')
        return {'status': 'AVAILABLE', 'apiVersion': '1.0', 'rulesetVersion': RULESET_VERSION}

    @app.post('/api/v1/workbooks', status_code=202, response_model=UploadResponse)
    async def upload(request: Request, background: BackgroundTasks, identity=Depends(user), file: UploadFile = File(...)):
        try:
            filename = (file.filename or '').replace('\\', '/').rsplit('/', 1)[-1]
            if not 1 <= len(filename) <= 255:
                raise ApiError(400, 'INVALID_FILENAME', 'File name must contain 1–255 characters.')
            if not filename.lower().endswith('.xlsx'):
                raise ApiError(415, 'UNSUPPORTED_FILE_TYPE', 'Only .xlsx workbooks are supported.')
            data = bytearray()
            while chunk := await file.read(1024 * 1024):
                data.extend(chunk)
                if len(data) > MAX_UPLOAD:
                    raise ApiError(413, 'FILE_TOO_LARGE', 'Workbook exceeds the 25,000,000-byte limit.')
            try:
                with zipfile.ZipFile(io.BytesIO(data)) as archive:
                    entries = archive.infolist()
                    if len(entries) > 10000 or sum(e.file_size for e in entries) > 100 * 1024 * 1024:
                        raise ValueError('Archive exceeds documented processing limits.')
                    if any(e.flag_bits & 1 for e in entries):
                        raise ValueError('Encrypted archives are unsupported.')
                    if any('vbaproject' in e.filename.lower() for e in entries):
                        raise ValueError('Macro-enabled workbooks are unsupported.')
                    content_types = archive.read('[Content_Types].xml')
                    if b'macroEnabled' in content_types or b'vbaProject' in content_types:
                        raise ValueError('Macro-enabled workbooks are unsupported.')
            except (ValueError, zipfile.BadZipFile, KeyError, RuntimeError, NotImplementedError) as exc:
                raise ApiError(422, 'INVALID_WORKBOOK', 'Workbook is invalid.',
                               {'valid': False, 'errors': [str(exc)]}) from exc
            if workbook_validator is None:
                raise ApiError(503, 'VALIDATOR_NOT_CONFIGURED', 'Workbook validation is not configured.')
            with tempfile.TemporaryDirectory(prefix='workbook-validation-') as directory:
                temporary_path = Path(directory) / 'source.xlsx'
                temporary_path.write_bytes(data)
                valid = await asyncio.to_thread(workbook_validator, str(temporary_path))
            if type(valid) not in (bool, int) or valid not in (0, 1):
                raise ApiError(500, 'VALIDATOR_ERROR', 'Validator must return True/1 or False/0.')
            if not valid:
                raise ApiError(422, 'INVALID_WORKBOOK', 'Workbook is invalid.', {'valid': False})
            workbook_id, version_id = 'workbook-' + uuid4().hex, 'version-' + uuid4().hex
            # Source and initial audit commit atomically; rejected uploads leave no records.
            with connect(write=True) as db:
                db.execute('INSERT INTO versions VALUES (?, ?, ?, ?, ?, ?, ?)',
                           (workbook_id, version_id, identity, filename, hashlib.sha256(data).hexdigest(), utc_now(), bytes(data)))
                audit_id = insert_audit(db, workbook_id, version_id, request.state.request_id)
            background.add_task(process_audit, database, audit_id, checker)
            return {'workbookId': workbook_id, 'versionId': version_id, 'auditId': audit_id, 'status': 'PROCESSING'}
        finally:
            await file.close()

    @app.get('/api/v1/workbooks/{workbook_id}/versions/{version_id}', response_model=WorkbookVersion)
    def metadata(workbook_id: Identifier, version_id: Identifier, identity=Depends(user)):
        with connect() as db:
            row = version(db, workbook_id, version_id, identity)
            latest = db.execute('SELECT * FROM audits WHERE version_id=? ORDER BY started_at DESC, audit_id DESC LIMIT 1',
                                (version_id,)).fetchone()
        return {'workbookId': workbook_id, 'versionId': version_id, 'fileName': row['filename'],
                'sha256': row['sha256'], 'createdAt': row['created_at'],
                'status': latest['status'] if latest else 'PROCESSING_FAILED',
                'latestAuditId': latest['audit_id'] if latest else None, 'sourceVersionId': None}

    @app.get('/api/v1/workbooks/{workbook_id}/versions/{version_id}/audits/{audit_id}', response_model=Audit)
    def audit(workbook_id: Identifier, version_id: Identifier, audit_id: Identifier, identity=Depends(user)):
        with connect() as db:
            version(db, workbook_id, version_id, identity)
            row = db.execute('SELECT * FROM audits WHERE version_id=? AND audit_id=?', (version_id, audit_id)).fetchone()
        if row is None:
            raise ApiError(404, 'NOT_FOUND', 'Audit does not exist.')
        error = json.loads(row['error']) if row['error'] else None
        if error is not None:
            # Earlier development audits omitted these common error fields.
            error.setdefault('requestId', row['request_id'])
            error.setdefault('details', {})
        return {'auditId': audit_id, 'workbookId': workbook_id, 'versionId': version_id,
                'rulesetVersion': row['ruleset_version'], 'status': row['status'],
                'startedAt': row['started_at'], 'completedAt': row['completed_at'],
                'findings': json.loads(row['findings']), 'limitations': json.loads(row['limitations']),
                'error': error}

    @app.get('/api/v1/workbooks/{workbook_id}/versions/{version_id}/original')
    def original(workbook_id: Identifier, version_id: Identifier, identity=Depends(user)):
        from urllib.parse import quote
        with connect() as db:
            row = version(db, workbook_id, version_id, identity)
        return Response(bytes(row['original']), media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                        headers={'Content-Disposition': "attachment; filename*=UTF-8''" + quote(row['filename'], safe='')})
    return app


app = create_app()
