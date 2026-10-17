"""Workbook upload API. Run with: python -m uvicorn app:app."""
import hashlib
import io
import json
import logging
import os
from pathlib import Path
import secrets
import tempfile
import subprocess
import sys
from datetime import datetime, timezone
from uuid import uuid4
import zipfile
from database import Database

from fastapi import Depends, FastAPI, File, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from starlette.exceptions import HTTPException

ROOT = Path(__file__).parent
MAX_UPLOAD = 25 * 1024 * 1024


def now():
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def load_workbook_validator():
    path = Path(os.getenv('VALIDATOR_PATH', str(ROOT / 'validity_check.py')))
    if not path.is_file():
        return None
    path = path.resolve()

    def validate(filepath):
        # Process isolation releases handles left open by the supplied checker,
        # including early XML parsing exits, before Windows deletes the temp file.
        completed = subprocess.run(
            [sys.executable, '-c',
             'import json, runpy, sys; module = runpy.run_path(sys.argv[1]); '
             'print(json.dumps(module["validate_file"](sys.argv[2])))',
             str(path), filepath],
            capture_output=True, text=True, check=True, timeout=60,
        )
        result = json.loads(completed.stdout)
        # Jonathan's supplied version returns error strings; keep his file intact.
        # Empty errors mean valid. Boolean-returning versions work unchanged too.
        if isinstance(result, list) and all(isinstance(error, str) for error in result):
            return not result
        return result

    return validate


class ApiError(Exception):
    def __init__(self, status, code, message, details=None):
        self.status, self.code, self.message = status, code, message
        self.details = details or {}


def create_app(db_path=None, tokens=None, workbook_validator=None):
    if workbook_validator is None:
        workbook_validator = load_workbook_validator()
    app = FastAPI(title='Workbook validation service', version='1.0')
    # Tokens map opaque bearer credentials to stable user identifiers. No default credentials.
    credentials = tokens if tokens is not None else json.loads(os.getenv('API_TOKENS_JSON', '{}'))
    if not isinstance(credentials, dict) or any(
        not isinstance(k, str) or not k or not isinstance(v, str) or not v
        for k, v in credentials.items()
    ):
        raise ValueError('API_TOKENS_JSON must map nonempty token strings to user IDs')
    database = Database(db_path)
    database.initialize()
    connect = database.connect

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

    def error_response(request, status, code, message, details=None):
        return JSONResponse(status_code=status, content={
            'code': code, 'message': message,
            'requestId': request.state.request_id, 'details': details or {},
        })

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

    @app.get('/', include_in_schema=False)
    def index():
        return FileResponse(ROOT / 'static' / 'index.html')

    @app.get('/api/v1/health')
    def health():
        try:
            with connect() as db:
                db.execute('SELECT 1').fetchone()
        except Exception:
            raise ApiError(503, 'SERVICE_UNAVAILABLE', 'Storage is unavailable.')
        return {'status': 'AVAILABLE', 'apiVersion': '1.0', 'rulesetVersion': '1.0'}

    @app.post('/api/v1/workbooks')
    async def upload(identity=Depends(user), file: UploadFile = File(...)):
        try:
            filename = (file.filename or '').replace('\\', '/').rsplit('/', 1)[-1]
            if not filename.lower().endswith('.xlsx'):
                raise ApiError(415, 'UNSUPPORTED_FILE_TYPE', 'Only .xlsx workbooks are supported.')
            data = bytearray()
            while chunk := await file.read(1024 * 1024):
                data.extend(chunk)
                if len(data) > MAX_UPLOAD:
                    raise ApiError(413, 'FILE_TOO_LARGE', 'Workbook exceeds the 25 MiB limit.')
            try:
                with zipfile.ZipFile(io.BytesIO(data)) as archive:
                    entries = archive.infolist()
                    if len(entries) > 10000 or sum(e.file_size for e in entries) > 100 * 1024 * 1024:
                        raise ValueError('Archive exceeds processing limits (10,000 entries / 100 MiB expanded).')
                    if any(e.flag_bits & 1 for e in entries):
                        raise ValueError('Encrypted archives are unsupported.')
                    if any('vbaproject' in e.filename.lower() for e in entries):
                        raise ValueError('Macro-enabled workbooks are unsupported.')
                    content_types = archive.read('[Content_Types].xml')
                    if b'macroEnabled' in content_types or b'vbaProject' in content_types:
                        raise ValueError('Macro-enabled workbooks are unsupported.')
                # Call Jonathan's checker with a real file path, preserving its source.
                if workbook_validator is not None:
                    # Close the file before calling the validator so it can reopen
                    # the path on Windows. Each request gets an isolated directory.
                    with tempfile.TemporaryDirectory(prefix='workbook-validation-') as directory:
                        temporary_path = Path(directory) / 'source.xlsx'
                        temporary_path.write_bytes(data)
                        valid = workbook_validator(str(temporary_path))
                    if type(valid) not in (bool, int) or valid not in (0, 1):
                        raise ApiError(500, 'VALIDATOR_ERROR', 'Validator must return True/1 or False/0.')
                    if not valid:
                        raise ApiError(422, 'INVALID_WORKBOOK', 'Workbook is invalid.',
                                       {'valid': False})
            except (ValueError, zipfile.BadZipFile, KeyError, RuntimeError, NotImplementedError) as exc:
                raise ApiError(422, 'INVALID_WORKBOOK', 'Workbook is invalid.',
                               {'valid': False}) from exc
            if workbook_validator is None:
                raise ApiError(503, 'VALIDATOR_NOT_CONFIGURED', 'Workbook validation is not configured.',
                               {'valid': None})
            workbook_id, version_id = ('workbook-' + uuid4().hex, 'version-' + uuid4().hex)
            timestamp = now()
            with connect() as db:
                db.execute('INSERT INTO versions VALUES (?, ?, ?, ?, ?, ?, ?)',
                           (workbook_id, version_id, identity, filename, hashlib.sha256(data).hexdigest(), timestamp, bytes(data)))
            return {'valid': True, 'workbookId': workbook_id, 'versionId': version_id}
        finally:
            await file.close()

    @app.get('/api/v1/workbooks/{workbook_id}/versions/{version_id}')
    def metadata(workbook_id: str, version_id: str, identity=Depends(user)):
        with connect() as db:
            row = version(db, workbook_id, version_id, identity)
        return {'workbookId': workbook_id, 'versionId': version_id, 'fileName': row['filename'],
                'sha256': row['sha256'], 'createdAt': row['created_at'], 'valid': True}

    # Retained for the later audit phase. Validation uploads do not create audits.
    @app.get('/api/v1/workbooks/{workbook_id}/versions/{version_id}/audits/{audit_id}')
    def audit(workbook_id: str, version_id: str, audit_id: str, identity=Depends(user)):
        with connect() as db:
            version(db, workbook_id, version_id, identity)
            row = db.execute('SELECT * FROM audits WHERE workbook_id=? AND audit_id=?',
                             (workbook_id, audit_id)).fetchone()
        if row is None:
            raise ApiError(404, 'NOT_FOUND', 'Audit does not exist.')
        return {'auditId': audit_id, 'workbookId': workbook_id, 'versionId': version_id,
                'rulesetVersion': '1.0', 'status': row['status'],
                'startedAt': row['started_at'], 'completedAt': row['completed_at'],
                'findings': json.loads(row['findings']), 'limitations': json.loads(row['limitations']),
                'error': json.loads(row['error']) if row['error'] else None}

    @app.get('/api/v1/workbooks/{workbook_id}/versions/{version_id}/original')
    def original(workbook_id: str, version_id: str, identity=Depends(user)):
        from urllib.parse import quote
        with connect() as db:
            row = version(db, workbook_id, version_id, identity)
        return Response(bytes(row['original']), media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                        headers={'Content-Disposition': "attachment; filename*=UTF-8''" + quote(row['filename'], safe='')})

    return app


app = create_app()
