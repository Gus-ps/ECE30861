"""Phase 4 HTTP adapter. Workbook evaluation/editing remains in Jonathan's modules."""
import asyncio
import base64
from contextlib import asynccontextmanager
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import secrets
import tempfile
import threading
import time
from urllib.parse import quote
from zipfile import ZipFile

from fastapi import BackgroundTasks, Depends, FastAPI, File, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.security import HTTPBearer
from starlette.exceptions import HTTPException

from contracts import Audit, Error, Health, Identifier, MAX_JSON_REQUEST_BYTES, UploadResponse, WorkbookVersion
from database import Database, remaining_seconds
from credentials import subject_for, validate as validate_credentials, fingerprint
from phase4_contracts import (AuditReport, HistoryResponse, ReauditRequest, ReauditResponse,
                             RemediationAccepted, RemediationRequest, RemediationResponse, ReviewResponse)
from phase4_jobs import RULESET_VERSION, Runner, begin_audit, child, identifier
from phase4_store import Store, encode, now
import phase5_reminders as reminders
import phase5_schedule as schedules
import phase5_scheduler as scheduler
from phase5_clock import PATH as CLOCK_PATH
import phase5_deletion as deletion
import release_guard
from service_errors import ApiError
from test_interface import SystemTests, TestSessionError

ROOT = Path(__file__).parent
MAX_UPLOAD = 25_000_000


def create_app(db_path=None, tokens=None, workbook_validator=None, accessibility_checker=None,
               enable_test_interface=None, test_admin_tokens=None, test_session_users=None,
               reviewer_grants=None, *, enable_scheduler=True):
    if workbook_validator is None:
        from app import load_workbook_validator
        workbook_validator = load_workbook_validator()
    credentials = tokens if tokens is not None else json.loads(os.getenv('API_TOKENS_JSON', '{}'))
    admins = test_admin_tokens if test_admin_tokens is not None else json.loads(os.getenv('TEST_ADMIN_TOKENS_JSON', '{}'))
    reviewers = reviewer_grants if reviewer_grants is not None else json.loads(os.getenv('REVIEWER_GRANTS_JSON', '{}'))
    validate_credentials(credentials)
    validate_credentials(admins)
    if {fingerprint(key) for key in credentials} & {fingerprint(key) for key in admins}:
        raise ValueError('Business and test-administrator credentials must be distinct.')
    if not isinstance(reviewers, dict) or any(
        not isinstance(subject, str) or not isinstance(owners, list)
        or any(not isinstance(owner, str) or not owner for owner in owners)
        for subject, owners in reviewers.items()
    ):
        raise ValueError('Reviewer grants must map reviewer subjects to owner lists (empty for no grant).')
    scheduler_interval = scheduler.interval_seconds() if enable_scheduler else None
    ledger_setting, ledger_bucket = os.getenv('DELETION_LEDGER_PATH'), os.getenv('DELETION_LEDGER_BUCKET')
    if ledger_setting and ledger_bucket:  # A split ledger lets a restore resurrect deletions (D11).
        raise RuntimeError('DELETION_LEDGER_PATH and DELETION_LEDGER_BUCKET are both set; unset the one '
                           "that is not this deployment's ledger (see D11).")
    if ledger_bucket:
        import boto3
        ledger = deletion.S3Ledger(boto3.client('s3'), ledger_bucket)
    else:
        ledger = Path(ledger_setting) if ledger_setting else None
    database = Database(db_path)
    database.initialize()
    store = Store(database)
    schedules.initialize(store)
    reminders.initialize(store)
    tests = SystemTests(store,
                        enable_test_interface if enable_test_interface is not None else os.getenv('ENABLE_TEST_INTERFACE', '').lower() == 'true',
                        admins, test_session_users if test_session_users is not None else json.loads(os.getenv('TEST_SESSION_USERS_JSON', '{}')))
    runner = Runner(store, accessibility_checker)

    @asynccontextmanager
    async def lifespan(app):
        # Startup is not accepting requests yet. Release the previous process's
        # drain fence before recovery needs to reconstruct any orphaned jobs.
        release_guard.resume(store)
        deletion.recover(store, ledger)
        runner.recover()
        thread = threading.Thread(target=runner.loop, daemon=True)
        thread.start()
        scheduler_stop = threading.Event()
        scheduler_thread = None
        try:
            if scheduler_interval is not None:
                dispatch_thread = threading.Thread(target=scheduler.run_scheduler,
                    args=(store, scheduler_stop, scheduler_interval), name='phase5-scheduler', daemon=True)
                dispatch_thread.start()
                scheduler_thread = dispatch_thread
            yield
        finally:
            if scheduler_thread is not None:
                scheduler_stop.set()
                await asyncio.to_thread(scheduler_thread.join)
            runner.stop.set()
            await asyncio.to_thread(thread.join, 5)

    app = FastAPI(title='Workbook accessibility service', version='1.0', lifespan=lifespan,
                  responses={s: {'model': Error} for s in (400,401,403,404,409,413,415,422,500,503)})
    app.openapi_version = '3.1.1'
    app.state.database = database
    app.state.store = store
    app.state.runner = runner
    tests.install(app, credentials)

    def error(request, code, message, status=400, details=None):
        return JSONResponse(status_code=status, content=dict(code=code, message=message,
                            requestId=request.state.request_id, details=details or {}))

    @app.middleware('http')
    async def headers(request, call_next):
        request.state.request_id = identifier('request')
        try:
            # The clock route applies its body limit after checking access and session state.
            is_clock = request.method == 'POST' and request.url.path == CLOCK_PATH
            if (not is_clock and request.headers.get('content-type', '').startswith('application/json')
                    and len(await request.body()) > MAX_JSON_REQUEST_BYTES):
                raise ApiError(413, 'REQUEST_TOO_LARGE', 'JSON request exceeds 1 MiB.')
            response = await call_next(request)
        except ApiError as exc:
            response = error(request, exc.code, exc.message, exc.status, exc.details)
        except Exception:
            logging.exception('Request failed: %s', request.state.request_id)
            response = (JSONResponse(status_code=500, content={'message':'Test session operation failed.','source':'system'})
                        if request.url.path.startswith('/test/') else error(request, 'INTERNAL_ERROR', 'The operation could not be completed.', 500))
        response.headers['X-Request-ID'] = request.state.request_id
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['X-Frame-Options'] = 'DENY'
        return response

    @app.exception_handler(ApiError)
    async def api_error(request, exc):
        return error(request, exc.code, exc.message, exc.status, exc.details)

    @app.exception_handler(RequestValidationError)
    async def malformed(request, exc):
        if request.url.path.startswith('/test/'):
            return JSONResponse(status_code=400, content={'message':'Missing or malformed test request data.','source':'system'})
        return error(request, 'INVALID_REQUEST', 'Missing or malformed request data.')

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        if request.url.path == '/test/setup' and exc.status_code == 400:
            return JSONResponse(status_code=400, content={'message':'Missing or malformed test request data.','source':'system'})
        return error(request, 'NOT_FOUND' if exc.status_code == 404 else 'INVALID_REQUEST', str(exc.detail), exc.status_code)

    bearer = HTTPBearer(auto_error=False)

    def user(request: Request, auth=Depends(bearer)):
        token = auth.credentials if auth else ''
        subject = subject_for(credentials, token)
        if subject is not None:
            with store.connect(deadline=getattr(request.state, 'delete_deadline', None)) as db:
                request.state.namespace = tests.check(db, request.headers.get('x-test-session'), subject)
                if request.method not in ('GET', 'HEAD', 'OPTIONS') and release_guard.draining(db):
                    raise ApiError(503, 'SERVICE_UNAVAILABLE', 'A release is draining; retry after it completes.')
            return subject
        if subject_for(admins, token) is not None:
            raise ApiError(403, 'FORBIDDEN', 'Test administrators cannot use business operations.')
        raise ApiError(401, 'UNAUTHORIZED', 'A valid bearer token is required.')

    def lookup(db, resource_id, kind, request, identity, wb=None, vid=None, mutate=False):
        row = store.get(db, resource_id, kind, visible=True)
        if row is None or row['namespace'] != request.state.namespace or (wb and row['workbook_id'] != wb) or (vid and row['version_id'] != vid):
            raise ApiError(404, 'NOT_FOUND', 'Resource does not exist in this namespace.')
        if row['owner'] != identity and row['owner'] not in reviewers.get(identity, []):
            raise ApiError(403, 'FORBIDDEN', 'You cannot access this workbook.')
        if mutate and (row['owner'] != identity or identity in reviewers):
            raise ApiError(403, 'FORBIDDEN', 'Only the owner may change this workbook.')
        return row

    @app.get('/api/v1/workbooks/{workbook_id}/schedule',
             response_model=schedules.ScheduleResponse)
    def get_schedule(workbook_id: Identifier, request: Request, identity=Depends(user)):
        with store.connect() as db:
            workbook = lookup(db, workbook_id, 'workbook', request, identity)
            return schedules.read(db, workbook)

    @app.get('/api/v1/workbooks/{workbook_id}/notifications',
             response_model=reminders.NotificationResponse)
    def get_notifications(workbook_id: Identifier, request: Request, identity=Depends(user)):
        with store.connect() as db:
            lookup(db, workbook_id, 'workbook', request, identity)
            return reminders.read_notifications(db, workbook_id)

    @app.put('/api/v1/workbooks/{workbook_id}/schedule',
             response_model=schedules.ScheduleResponse,
             openapi_extra={'requestBody': {'required': True, 'content': {
                 'application/json': {'schema': schedules.ScheduleRequest.model_json_schema()}}}})
    async def put_schedule(workbook_id: Identifier, request: Request, identity=Depends(user)):
        raw = await request.body()
        with store.connect(write=True) as db:
            store.fence(db, workbook_id)
            workbook = lookup(db, workbook_id, 'workbook', request, identity, mutate=True)
            body = schedules.parse_body(raw)
            return schedules.write(db, workbook, body)

    def blob(db, version):
        try:
            return store.bytes(db, version)
        except ValueError:
            raise ApiError(500, 'SOURCE_INTEGRITY_FAILED', 'Stored workbook integrity check failed.')

    def check_active(db, vid):
        if store.active(db, vid):
            raise ApiError(409, 'ACTIVE_OPERATION', 'An operation is already active for this version.')

    async def validate_upload(request, file):
        intake_started = time.monotonic()
        form = await request.form()
        if len(form.multi_items()) != 1 or next(iter(form)) != 'file':
            raise ApiError(400, 'INVALID_REQUEST', 'Supply exactly one binary file field.')
        filename = (file.filename or '').replace('\\','/').rsplit('/',1)[-1]
        if not filename.strip() or len(filename)>255 or any(ord(c)<32 or ord(c)==127 for c in filename):
            raise ApiError(400, 'INVALID_REQUEST', 'The filename is invalid.')
        if filename.lower().endswith('.xlsm'):
            raise ApiError(422, 'MACRO_ENABLED_WORKBOOK_UNSUPPORTED', 'Macro-enabled workbooks are unsupported.')
        if not filename.lower().endswith('.xlsx'):
            raise ApiError(415, 'UNSUPPORTED_FILE_TYPE', 'Only .xlsx workbooks are supported.')
        data = bytearray()
        try:
            while chunk := await file.read(1_048_576):
                data.extend(chunk)
                if len(data)>MAX_UPLOAD:
                    raise ApiError(413, 'FILE_TOO_LARGE', 'Workbook exceeds 25,000,000 bytes.')
        finally:
            await file.close()
        if workbook_validator is None:
            raise ApiError(503, 'SERVICE_UNAVAILABLE', 'Workbook validation is unavailable.')
        with tempfile.TemporaryDirectory(prefix='workbook-validation-') as directory:
            path = Path(directory)/'source.xlsx'
            path.write_bytes(data)
            import subprocess
            try:
                valid = await asyncio.to_thread(workbook_validator, str(path))
            except subprocess.TimeoutExpired:
                raise ApiError(500, 'PROCESSING_TIMEOUT', 'Workbook validation exceeded its processing deadline.') from None
            if valid is True or type(valid) is int and valid == 1:
                from package_checks import check_package
                await asyncio.to_thread(check_package, path)
        if type(valid) not in (bool,int) or valid not in (0,1):
            raise ApiError(500, 'ENGINE_RESULT_INVALID', 'Validator must return a boolean.')
        if not valid:
            raise ApiError(422, 'INVALID_WORKBOOK', 'Workbook is invalid.', {'valid':False})
        logging.info('upload_validated %s', encode({'requestId': request.state.request_id,
                     'validationSeconds': round(time.monotonic()-intake_started, 4), 'bytes': len(data)}))
        return filename, bytes(data)

    @app.get('/', include_in_schema=False)
    def index():
        page = ROOT/'static/index.html'
        source = page.read_text(encoding='utf-8')
        script = source.split('<script>', 1)[1].split('</script>', 1)[0]
        digest = base64.b64encode(hashlib.sha256(script.encode('utf-8')).digest()).decode('ascii')
        policy = ("default-src 'none'; script-src 'sha256-" + digest + "'; "
                  "style-src 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; "
                  "base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
        return FileResponse(page, headers={'Content-Security-Policy': policy})

    @app.get('/api/v1/health', response_model=Health)
    def health():
        if workbook_validator is None:
            raise ApiError(503, 'SERVICE_UNAVAILABLE', 'Validation is unavailable.')
        try:
            with store.connect() as db:
                db.execute('SELECT 1').fetchone()
        except Exception:
            raise ApiError(503, 'SERVICE_UNAVAILABLE', 'Storage is unavailable.')
        return dict(status='AVAILABLE', apiVersion='1.0', rulesetVersion=RULESET_VERSION)

    async def upload_to(request, background, identity, file, wb=None):
        if identity in reviewers and not wb:
            raise ApiError(403, 'FORBIDDEN', 'Reviewers have read-only access.')
        vid = identifier('version')
        namespace = request.state.namespace
        staged = wb is not None
        committed = False
        if staged:
            with store.connect(write=True) as db:
                store.fence(db, wb)
                lookup(db, wb, 'workbook', request, identity, mutate=True)
                # Staging reservation: DELETE returns 409 until it is released or the 35 s upload bound passes.
                db.execute('INSERT INTO p5_upload_reservations VALUES (?,?,?)', (vid, wb, time.time() + 35))
        try:
            filename, data = await validate_upload(request, file)
            with store.connect(write=True) as db:
                tests.check(db, namespace, identity, lock=True)
                if staged:
                    store.fence(db, wb)
                    lookup(db, wb, 'workbook', request, identity, mutate=True)
                injected = store.claim_fault(db, namespace, 'storage')
                if not injected:
                    if not staged:
                        wb = identifier('workbook')
                        store.insert(db, 'workbook', wb, {'workbookId':wb}, identity, namespace, wb)
                    body = dict(workbookId=wb, versionId=vid, fileName=filename, sha256=hashlib.sha256(data).hexdigest(),
                                createdAt=now(), status='PROCESSING', latestAuditId=None, sourceVersionId=None)
                    store.insert(db, 'version', vid, body, identity, namespace, wb, vid, data)
                    version = store.get(db, vid)
                    aid = begin_audit(store, db, version, request.state.request_id)
                if staged:
                    db.execute('DELETE FROM p5_upload_reservations WHERE id=?', (vid,))
            committed = True
        finally:
            if staged and not committed:
                with store.connect(write=True) as db:
                    db.execute('DELETE FROM p5_upload_reservations WHERE id=?', (vid,))
        if injected:
            raise ApiError(500, 'TEST_STORAGE_FAILURE', 'Storage failure requested by the isolated test session.',
                           {'stage': 'storage', 'testOnly': True})
        background.add_task(runner.drain)
        return dict(workbookId=wb, versionId=vid, auditId=aid, status='PROCESSING')

    @app.post('/api/v1/workbooks', status_code=202, response_model=UploadResponse)
    async def upload(request:Request, background:BackgroundTasks, identity=Depends(user), file:UploadFile=File(...)):
        return await upload_to(request, background, identity, file)

    @app.post('/api/v1/workbooks/{workbook_id}/versions', status_code=202, response_model=UploadResponse)
    async def new_version(request:Request, background:BackgroundTasks, workbook_id:Identifier, identity=Depends(user), file:UploadFile=File(...)):
        return await upload_to(request, background, identity, file, workbook_id)

    @app.get('/api/v1/workbooks/{workbook_id}/versions/{version_id}', response_model=WorkbookVersion)
    def metadata(request:Request, response:Response, workbook_id:Identifier, version_id:Identifier, identity=Depends(user)):
        with store.connect() as db:
            row = lookup(db, version_id, 'version', request, identity, wb=workbook_id)
            blob(db,row)
            # UI hint only; every mutation still authorizes on the server. This
            # also identifies clean workbooks whose review has no findings.
            response.headers['X-Workbook-Access'] = ('owner' if row['owner'] == identity
                                                    and identity not in reviewers else 'reviewer')
        return row['body']

    def get_audit(db, request, identity, workbook_id, version_id, audit_id):
        # Resolve every parent before authorizing content, including unknown audit on a known version.
        row = lookup(db, audit_id, 'audit', request, identity, wb=workbook_id, vid=version_id)
        version = lookup(db, version_id, 'version', request, identity, wb=workbook_id)
        blob(db, version)
        return version, row

    @app.get('/api/v1/workbooks/{workbook_id}/versions/{version_id}/audits/{audit_id}', response_model=Audit)
    def audit(request:Request, workbook_id:Identifier, version_id:Identifier, audit_id:Identifier, identity=Depends(user)):
        with store.connect() as db:
            _, row = get_audit(db,request,identity,workbook_id,version_id,audit_id)
        return row['body']

    @app.post('/api/v1/workbooks/{workbook_id}/versions/{version_id}/audits', status_code=202, response_model=ReauditResponse)
    def reaudit(request:Request, background:BackgroundTasks, workbook_id:Identifier, version_id:Identifier,
                body:ReauditRequest|None=None, identity=Depends(user)):
        with store.connect(write=True) as db:
            store.fence(db,workbook_id)
            version = lookup(db,version_id,'version',request,identity,wb=workbook_id,mutate=True)
            check_active(db,version_id)
            blob(db,version)
            aid = begin_audit(store,db,version,request.state.request_id)
        background.add_task(runner.drain)
        return dict(auditId=aid,versionId=version_id,rulesetVersion=RULESET_VERSION,status='PROCESSING')

    def download(data, filename, media):
        safe = ''.join(c if 32<=ord(c)<127 and c not in '\\"/;' else '_' for c in filename)
        return Response(data, media_type=media, headers={'Content-Disposition':f'attachment; filename="{safe}"; filename*=UTF-8\'\''+quote(filename,safe=''),
                                                       'Content-Length':str(len(data)), 'Cache-Control':'no-store'})

    @app.get('/api/v1/workbooks/{workbook_id}/versions/{version_id}/source', responses={200:{'content':{'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet':{}}}})
    @app.get('/api/v1/workbooks/{workbook_id}/versions/{version_id}/original', include_in_schema=False)
    def source(request:Request, workbook_id:Identifier, version_id:Identifier, identity=Depends(user)):
        with store.connect() as db:
            version = lookup(db,version_id,'version',request,identity,wb=workbook_id)
            data = blob(db,version)
        return download(data,version['body']['fileName'],'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

    async def within_delete_deadline(request, function, *args):
        try:
            timeout = remaining_seconds(request.state.delete_deadline)
            return await asyncio.wait_for(asyncio.to_thread(function, *args), timeout=timeout)
        except TimeoutError:
            raise ApiError(500, 'DELETION_FAILED', 'Workbook deletion exceeded its time limit.') from None

    async def delete_user(request: Request, auth=Depends(bearer)):
        request.state.delete_deadline = time.monotonic() + deletion.DELETE_SECONDS
        return await within_delete_deadline(request, user, request, auth)

    def delete_owned(request, workbook_id, identity):
        namespace = request.state.namespace
        deadline = request.state.delete_deadline
        try:
            with store.connect(write=True, deadline=deadline) as db:
                tests.check(db, namespace, identity, lock=True)
                store.fence(db, workbook_id)
                existing = deletion.reservation(db, workbook_id)
                injected = False
                if existing is not None:
                    if existing['owner'] != identity or existing['namespace'] != namespace or identity in reviewers:
                        raise ApiError(404, 'NOT_FOUND', 'Resource does not exist in this namespace.')
                    created = existing['created']
                else:
                    lookup(db, workbook_id, 'workbook', request, identity, mutate=True)
                    if deletion.active(db, workbook_id, time.time()):
                        raise ApiError(409, 'ACTIVE_OPERATION', 'An operation is active for this workbook.')
                    injected = store.claim_fault(db, namespace, 'deletion')
                    if not injected:
                        created = deletion.reserve(db, workbook_id, identity, namespace)
            if not injected:
                deletion.record_intent(store, ledger, workbook_id, created, deadline)
                deletion.finish(store, workbook_id, deadline)
        except (ApiError, TestSessionError):
            raise
        except Exception as exc:
            logging.error('Deletion failed: request_id=%s error_type=%s',
                          request.state.request_id, type(exc).__name__)
            raise ApiError(500, 'DELETION_FAILED', 'Workbook deletion could not be completed.') from None
        if injected:
            raise ApiError(500, 'TEST_DELETION_FAILURE', 'Deletion failure requested by the isolated test session.',
                           {'stage': 'deletion', 'testOnly': True})

    @app.delete('/api/v1/workbooks/{workbook_id}', status_code=204, response_class=Response)
    async def delete_workbook(request: Request, workbook_id: Identifier, identity=Depends(delete_user)):
        await within_delete_deadline(request, delete_owned, request, workbook_id, identity)
        return Response(status_code=204)

    @app.get('/api/v1/workbooks/{workbook_id}/history', response_model=HistoryResponse)
    def history(request:Request, workbook_id:Identifier, identity=Depends(user)):
        with store.connect() as db:
            lookup(db,workbook_id,'workbook',request,identity)
            rows = db.execute('SELECT kind,payload FROM p4_resources WHERE workbook_id=? ORDER BY seq', (workbook_id,)).fetchall()
        versions,audits=[],[]
        for row in rows:
            body=json.loads(row['payload'])
            if row['kind']=='version':
                versions.append({k:body[k] for k in ('versionId','sourceVersionId','status','createdAt')})
            elif row['kind']=='audit':
                audits.append({k:body[k] for k in ('auditId','versionId','rulesetVersion','status')})
        result=dict(workbookId=workbook_id,versions=versions,audits=audits)
        if len(encode(result).encode())>64*1024*1024:
            raise ApiError(500,'RESULT_TOO_LARGE','History exceeds the response limit.')
        return result

    @app.get('/api/v1/workbooks/{workbook_id}/versions/{version_id}/audits/{audit_id}/review', response_model=ReviewResponse)
    def review(request:Request, workbook_id:Identifier, version_id:Identifier, audit_id:Identifier, identity=Depends(user)):
        with store.connect() as db:
            version, audit = get_audit(db,request,identity,workbook_id,version_id,audit_id)
            if version['body']['latestAuditId']!=audit_id:
                raise ApiError(409,'STALE_AUDIT','Request the latest audit review context.')
            if audit['body']['status'] in ('PROCESSING','PROCESSING_FAILED'):
                raise ApiError(409,'AUDIT_NOT_READY','A successful completed audit is required.')
            rows=db.execute("SELECT payload FROM p4_resources WHERE kind='review' AND version_id=? ORDER BY seq",(version_id,)).fetchall()
            context=next((json.loads(r['payload']) for r in rows if json.loads(r['payload'])['auditId']==audit_id),None)
        if context is None:
            raise ApiError(409,'LEGACY_REVIEW_UNAVAILABLE','Request a new audit to create review context.')
        items=context['items']
        if identity in reviewers:
            items=[dict(i,allowedActions=[]) for i in items]
        return dict(workbookId=workbook_id,versionId=version_id,auditId=audit_id,items=items)

    @app.get('/api/v1/workbooks/{workbook_id}/versions/{version_id}/audits/{audit_id}/report', response_model=AuditReport)
    def report(request:Request, workbook_id:Identifier, version_id:Identifier, audit_id:Identifier, identity=Depends(user)):
        with store.connect() as db:
            _, audit = get_audit(db,request,identity,workbook_id,version_id,audit_id)
            if audit['body']['status']=='PROCESSING':
                raise ApiError(409,'REPORT_NOT_READY','The audit report is not ready.')
            rows=db.execute("SELECT payload FROM p4_resources WHERE kind='report' AND version_id=? ORDER BY seq",(version_id,)).fetchall()
            snapshot=next((json.loads(r['payload'])['snapshot'] for r in rows if json.loads(r['payload'])['auditId']==audit_id),None)
        if snapshot is None:
            failure = audit['body'].get('error')
            if failure and failure['code'] == 'STORAGE_FAILED':
                raise ApiError(500, 'STORAGE_FAILED', failure['message'])
            raise ApiError(409,'LEGACY_REPORT_UNAVAILABLE','Request a new audit to produce a report.')
        AuditReport.model_validate(snapshot)
        raw=encode(snapshot).encode('utf-8')
        if len(raw)>64*1024*1024:
            raise ApiError(500,'RESULT_TOO_LARGE','Report exceeds the response limit.')
        return download(raw,'audit-'+audit_id+'.json','application/json')

    @app.post('/api/v1/workbooks/{workbook_id}/versions/{version_id}/remediations', status_code=202, response_model=RemediationAccepted)
    async def submit(request:Request, background:BackgroundTasks, workbook_id:Identifier, version_id:Identifier,
                     body:RemediationRequest, identity=Depends(user)):
        key=request.headers.get('idempotency-key','')
        decisions=[d.model_dump(exclude_unset=True) for d in body.decisions]
        canonical={'auditId':body.auditId,'decisions':sorted(decisions,key=lambda d:d['findingId'])}
        digest=hashlib.sha256(json.dumps(canonical,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        scope=encode([identity,request.state.namespace,request.method,request.url.path])
        with store.connect() as db:
            # Resolve the audit, then authorize the write, before get_audit reads bytes.
            lookup(db,body.auditId,'audit',request,identity,wb=workbook_id,vid=version_id)
            lookup(db,version_id,'version',request,identity,wb=workbook_id,mutate=True)
            version,audit=get_audit(db,request,identity,workbook_id,version_id,body.auditId)
            if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',key):
                raise ApiError(400,'IDEMPOTENCY_KEY_REQUIRED','A valid Idempotency-Key is required.')
            previous=db.execute('SELECT * FROM p4_keys WHERE scope=? AND key=?',(scope,key)).fetchone()
            if previous:
                if previous['digest']!=digest:
                    raise ApiError(409,'IDEMPOTENCY_CONFLICT','This key was used for a different request.')
                return json.loads(previous['response'])
            check_active(db,version_id)
            if version['body']['latestAuditId']!=body.auditId:
                raise ApiError(409,'STALE_AUDIT','Decisions must reference the latest audit.')
            if audit['body']['status'] in ('PROCESSING','PROCESSING_FAILED'):
                raise ApiError(409,'AUDIT_NOT_READY','A successful completed audit is required.')
            data=blob(db,version)
        with tempfile.TemporaryDirectory(prefix='decision-validation-') as directory:
            path=Path(directory)/'source.xlsx'; path.write_bytes(data)
            try:
                records=await asyncio.to_thread(child,'validate',path,{'decisions':decisions,'findings':audit['body']['findings']})
            except Exception as exc:
                from remediation import RemediationError
                if not isinstance(exc,RemediationError):
                    raise
                code=exc.code
                status_code=400 if code in ('INVALID_REQUEST','MISSING_VALUE','DUPLICATE_DECISION') else 404 if code=='FINDING_NOT_FOUND' else 422
                raise ApiError(status_code,code,str(exc))
        for record in records:
            record['sourceAuditId']=body.auditId
        rid=identifier('remediation')
        accepted=dict(remediationId=rid,sourceVersionId=version_id,status='REMEDIATING')
        response=dict(accepted,outputVersionId=None,outputId=None,auditId=None,error=None)
        with store.connect(write=True) as db:
            # Recheck all state under the reservation transaction, including concurrent identical replays.
            store.fence(db,workbook_id)
            version=lookup(db,version_id,'version',request,identity,wb=workbook_id,mutate=True)
            previous=db.execute('SELECT * FROM p4_keys WHERE scope=? AND key=?',(scope,key)).fetchone()
            if previous:
                if previous['digest']!=digest:
                    raise ApiError(409,'IDEMPOTENCY_CONFLICT','This key was used for a different request.')
                return json.loads(previous['response'])
            check_active(db,version_id)
            if version['body']['latestAuditId']!=body.auditId:
                raise ApiError(409,'STALE_AUDIT','The source audit changed while validating decisions.')
            store.insert(db,'remediation',rid,{'response':response,'provenance':{}},identity,request.state.namespace,workbook_id,version_id)
            db.execute('INSERT INTO p4_keys VALUES (?,?,?,?,?,?)',(scope,key,digest,encode(accepted),request.state.namespace,workbook_id))
            payload = {'decisions': decisions, 'findings': audit['body']['findings'],
                       'records': records, 'requestId': request.state.request_id}
            if store.claim_fault(db, request.state.namespace, 'remediation'):
                payload['remediationFault'] = True
            store.job(db,rid,'remediation',rid,version_id,request.state.namespace,payload)
        background.add_task(runner.drain)
        return accepted

    @app.get('/api/v1/remediations/{remediation_id}', response_model=RemediationResponse)
    def remediation_status(request:Request, remediation_id:Identifier, identity=Depends(user)):
        with store.connect() as db:
            row=lookup(db,remediation_id,'remediation',request,identity)
        return row['body']['response']

    @app.get('/api/v1/outputs/{output_id}/workbook', responses={200:{'content':{'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet':{}}}})
    def output(request:Request, output_id:Identifier, identity=Depends(user)):
        with store.connect() as db:
            row=lookup(db,output_id,'output',request,identity)
            version=lookup(db,row['version_id'],'version',request,identity)
            data=blob(db,version)
        return download(data,version['body']['fileName'],'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

    return app
