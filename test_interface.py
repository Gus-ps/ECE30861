"""Authenticated, durable system test sessions; never reset ordinary user data."""
import logging
import os
import re
import secrets
import sqlite3
from typing import Annotated, Literal

from fastapi import Depends, Request
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, StrictInt
from starlette.concurrency import run_in_threadpool

from contracts import strict_json
import phase5_clock as clocks
from service_errors import ApiError

SESSION_ID_PATTERN = r'^[A-Za-z0-9_-]{1,64}$'
SessionId = Annotated[str, StringConstraints(strict=True, pattern=SESSION_ID_PATTERN)]


class FaultOptions(BaseModel):
    model_config = ConfigDict(extra='forbid')
    audit_failures: StrictInt | None = Field(None, ge=1, le=1)
    deletion_failures: StrictInt | None = Field(None, ge=1, le=1)


class SetupOptions(BaseModel):
    model_config = ConfigDict(extra='forbid')
    cleanup_session_ids: list[SessionId] = Field(default_factory=list, max_length=100)
    faults: FaultOptions | None = None
    clock: clocks.ClockRequest = Field(default_factory=lambda: clocks.ClockRequest(currentTime=clocks.INITIAL_TIME))


class SystemSetup(BaseModel):
    model_config = ConfigDict(extra='forbid')
    session_id: SessionId
    setup: SetupOptions = Field(default_factory=SetupOptions)


class SessionResponse(BaseModel):
    session_id: SessionId


class UnavailableCodeCoverage(BaseModel):
    covered: None = None
    total: None = None
    basis: str = Field(min_length=1)


class CoverageEnvelope(BaseModel):
    code: UnavailableCodeCoverage


class SystemReport(BaseModel):
    session_id: SessionId
    coverage: CoverageEnvelope


class EndpointError(BaseModel):
    message: str
    source: Literal['system']


class TestSessionError(Exception):
    __test__ = False

    def __init__(self, status, message):
        self.status, self.message = status, message


class SystemTests:
    def __init__(self, store, enabled, admins, users):
        self.store, self.database = store, store.database
        self.enabled, self.admins, self.users = enabled, admins, users
        self.clock_enabled = enabled and os.getenv('ENABLE_TEST_CLOCK', '').lower() == 'true'
        for mapping in (admins, users):
            if not isinstance(mapping, dict):
                raise ValueError('Test credentials and membership must be JSON objects.')
        if any(not isinstance(token, str) or not token or not isinstance(owner, str) or not owner
               for token, owner in admins.items()):
            raise ValueError('Test administrator credentials must map tokens to subjects.')
        if any(not isinstance(subjects, list) or any(not isinstance(s, str) or not s for s in subjects)
               for subjects in users.values()):
            raise ValueError('Test session memberships must be lists of subjects.')
        if enabled and (not admins or any(owner not in users for owner in admins.values())):
            raise ValueError('Enabled test interface requires administrators and their allowed test users.')

    def session(self, db, session_id, lock=False):
        query = 'SELECT * FROM test_sessions WHERE session_id=?'
        if lock and self.database.postgres:
            query += ' FOR UPDATE'
        return db.execute(query, (session_id,)).fetchone()

    def check(self, db, session_id, subject, lock=False):
        if session_id is None:
            return None
        if not self.enabled or not re.fullmatch(SESSION_ID_PATTERN, session_id):
            raise TestSessionError(400, 'Unknown or invalid test session.')
        row = self.session(db, session_id, lock)
        if row is None or row['state'] == 'CLEANED':
            raise TestSessionError(400, 'Unknown or inactive test session.')
        if row['state'] != 'READY':
            raise TestSessionError(409, 'Test session is not ready.')
        if subject not in self.users.get(row['owner'], []):
            raise TestSessionError(403, 'You are not authorized for this test session.')
        return session_id

    def setup(self, owner, body):
        if 'clock' in body.setup.model_fields_set and not self.clock_enabled:
            raise TestSessionError(403, 'Test clock is disabled.')
        faults = body.setup.faults.model_dump(exclude_unset=True) if body.setup.faults else {}
        if 'faults' in body.setup.model_fields_set:
            if not faults or None in faults.values():
                raise TestSessionError(400, 'faults must name at least one fault with the value 1.')
            if os.getenv('ENABLE_TEST_FAULTS', '').lower() != 'true':
                raise TestSessionError(403, 'Test audit failures are disabled.')
        with self.database.connect(write=True) as db:
            if self.session(db, body.session_id):
                raise TestSessionError(409, 'Test session already exists.')
            cleanup = sorted(set(body.setup.cleanup_session_ids))
            for session_id in cleanup:
                row = self.session(db, session_id, lock=True)
                if row is None:
                    continue
                if row['owner'] != owner:
                    raise TestSessionError(403, 'Cleanup session belongs to another administrator.')
                active = db.execute("SELECT 1 FROM p4_jobs WHERE namespace=? AND state IN ('PENDING','RUNNING') LIMIT 1", (session_id,)).fetchone()
                if active:
                    raise TestSessionError(409, 'Cannot clean a session with an active audit.')
            inserted = db.execute('''INSERT INTO test_sessions (session_id,owner,state)
                VALUES (?,?,'READY') ON CONFLICT(session_id) DO NOTHING''', (body.session_id, owner))
            if inserted.rowcount != 1:
                raise TestSessionError(409, 'Test session already exists.')
            if self.clock_enabled:
                db.execute('INSERT INTO p5_clocks (session_id,"current_time") VALUES (?,?)',
                           (body.session_id, body.setup.clock.currentTime))
            if 'audit_failures' in faults:
                db.execute('INSERT INTO p4_faults VALUES (?,1)', (body.session_id,))
            if 'deletion_failures' in faults:
                db.execute("INSERT INTO p5_faults VALUES (?,'deletion',1)", (body.session_id,))
            for session_id in cleanup:
                db.execute('DELETE FROM p5_clocks WHERE session_id=?', (session_id,))
                db.execute('DELETE FROM p5_schedules WHERE namespace=?', (session_id,))
                db.execute('DELETE FROM p4_keys WHERE namespace=?', (session_id,))
                db.execute('DELETE FROM p4_jobs WHERE namespace=?', (session_id,))
                db.execute('DELETE FROM p4_resources WHERE namespace=?', (session_id,))
                db.execute('DELETE FROM p4_faults WHERE session_id=?', (session_id,))
                db.execute('DELETE FROM p5_faults WHERE session_id=?', (session_id,))
                # Only explicitly tagged resources are eligible; ordinary versions are untouched.
                ids = [row['workbook_id'] for row in db.execute(
                    'SELECT workbook_id FROM test_workbooks WHERE session_id=?', (session_id,)).fetchall()]
                for workbook_id in ids:
                    db.execute('DELETE FROM audits WHERE workbook_id=?', (workbook_id,))
                    db.execute('DELETE FROM test_workbooks WHERE workbook_id=?', (workbook_id,))
                    db.execute('DELETE FROM versions WHERE workbook_id=?', (workbook_id,))
                db.execute("UPDATE test_sessions SET state='CLEANED' WHERE session_id=?", (session_id,))
        return {'session_id': body.session_id}

    def advance_clock(self, owner, session_id, raw, request_id):
        if not re.fullmatch(SESSION_ID_PATTERN, session_id):
            raise ApiError(400, 'INVALID_TEST_SESSION', 'Unknown or invalid test session.')
        storage_errors = (sqlite3.Error,)
        if self.database.postgres:
            from psycopg import Error
            storage_errors += (Error,)
        try:
            with self.database.connect(write=True) as db:
                # Use cleanup's session lock before taking the clock and workbook locks.
                self.require_clock_session(db, owner, session_id)
                current = clocks.read(db, session_id, lock=self.database.postgres)
                if current is None:
                    raise ApiError(409, 'LEGACY_SESSION_CLOCK', 'Prepare a new test session with a clock.')
                return clocks.advance(self.store, db, session_id, current, raw, request_id)
        except storage_errors:
            logging.exception('Test clock transaction failed.')
            raise ApiError(500, 'STORAGE_FAILED', 'The test clock could not be advanced.') from None

    def require_clock_session(self, db, owner, session_id):
        row = self.session(db, session_id, lock=True)
        if row is not None and row['owner'] != owner:
            raise ApiError(403, 'FORBIDDEN', 'Test session belongs to another administrator.')
        if row is None or row['state'] == 'CLEANED':
            raise ApiError(400, 'INVALID_TEST_SESSION', 'Unknown or inactive test session.')
        if row['state'] != 'READY':
            raise ApiError(409, 'SESSION_NOT_READY', 'Test session is not ready.')

    def report(self, owner, session_id):
        with self.database.connect() as db:
            row = self.session(db, session_id)
        if row is None:
            raise TestSessionError(404, 'Test session does not exist.')
        if row['owner'] != owner:
            raise TestSessionError(403, 'Test session belongs to another administrator.')
        if row['state'] != 'READY':
            raise TestSessionError(409, 'Test session report is not available.')
        return {
            'session_id': session_id,
            'coverage': {'code': {
                'covered': None, 'total': None,
                'basis': 'Runtime code coverage is not enabled for this deployment; no coverage percentage is claimed.',
            }},
        }

    def install(self, app, ordinary_credentials):
        @app.exception_handler(TestSessionError)
        async def session_error(request, exc):
            if request.url.path.startswith('/test/'):
                return JSONResponse(status_code=exc.status, content={'message': exc.message, 'source': 'system'})
            return JSONResponse(status_code=exc.status, content={
                'code': 'INVALID_TEST_SESSION' if exc.status == 400 else 'FORBIDDEN',
                'message': exc.message, 'requestId': request.state.request_id, 'details': {},
            })

        security = HTTPBearer(auto_error=False, scheme_name='TestAdministrator')

        def authenticate_admin(credentials):
            if not credentials:
                raise TestSessionError(401, 'A test-administrator bearer token is required.')
            token = credentials.credentials
            for expected, subject in self.admins.items():
                if secrets.compare_digest(expected.encode(), token.encode()):
                    return subject
            if any(secrets.compare_digest(expected.encode(), token.encode()) for expected in ordinary_credentials):
                raise TestSessionError(403, 'Test administrator access is required.')
            raise TestSessionError(401, 'Test administrator token is not recognized.')

        def clock_admin(request: Request, credentials=Depends(security)):
            if not self.clock_enabled or 'x-test-session' not in request.headers:
                raise ApiError(404, 'TEST_CLOCK_DISABLED', 'The test clock requires an enabled test session.')
            try:
                return authenticate_admin(credentials)
            except TestSessionError as exc:
                code = 'UNAUTHORIZED' if exc.status == 401 else 'FORBIDDEN'
                raise ApiError(exc.status, code, exc.message) from None

        @app.post(clocks.PATH, response_model=clocks.ClockResponse, openapi_extra={
            'parameters': [{'in': 'header', 'name': 'X-Test-Session', 'required': True,
                            'schema': {'type': 'string', 'pattern': SESSION_ID_PATTERN}}],
            'requestBody': {'required': True, 'content': {
                'application/json': {'schema': clocks.ClockRequest.model_json_schema()},
            }},
        })
        async def advance_clock(request: Request, owner=Depends(clock_admin)):
            raw = await clocks.read_request_body(request)
            return await run_in_threadpool(
                self.advance_clock, owner, request.headers['x-test-session'], raw, request.state.request_id,
            )

        if not self.enabled:
            return

        def admin(credentials=Depends(security)):
            return authenticate_admin(credentials)

        errors = {status: {'model': EndpointError} for status in (400, 401, 403, 404, 409, 500)}

        async def validate_setup_json(request: Request):
            try:
                strict_json(await request.body())
            except (ValueError, RecursionError):
                raise TestSessionError(400, 'Missing or malformed test request data.') from None

        @app.post('/test/setup', status_code=201, response_model=SessionResponse, responses=errors)
        def setup(body: SystemSetup, owner=Depends(admin), _=Depends(validate_setup_json)):
            return self.setup(owner, body)

        @app.get('/test/report', response_model=SystemReport, responses=errors)
        def report(session_id: SessionId, owner=Depends(admin)):
            return self.report(owner, session_id)
