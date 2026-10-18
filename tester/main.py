"""Team 12 tester service: POST /test/setup, POST /test/run, GET /test/report.

Run locally:  uv run uvicorn tester.main:create_app --factory --port 8001
"""

import re
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header
from fastapi.responses import Response

from .auth import operator_subject
from .config import Settings
from .errors import TesterError, install_handlers
from .models import RunRequest, SetupResponse, SuiteReport, TestEndpointError, TesterSetupRequest
from .service import TesterService
from .store import Store

SESSION_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
ERRORS = {status: {"model": TestEndpointError} for status in (400, 401, 403, 404, 409, 500)}


def create_app(settings=None, transport=None, checks=None):
    ##  transport and checks are injection points for tests only.
    settings = settings or Settings()
    store = Store(settings.tester_db_path)
    service = TesterService(settings, store, transport=transport, checks=checks)

    @asynccontextmanager
    async def lifespan(_):
        yield
        store.close()

    app = FastAPI(title="Team 12 tester", version="0.1.0", lifespan=lifespan,
                  description="Instructor cross-team testing interface: setup, single-use run, stored report.")
    app.state.service = service
    install_handlers(app)

    def operator(authorization: str | None = Header(default=None)):
        return operator_subject(authorization, settings.tester_operator_token_hashes_json)

    @app.post("/test/setup", status_code=201, response_model=SetupResponse, responses=ERRORS)
    def setup(body: TesterSetupRequest, subject: str = Depends(operator)):
        return {"session_id": service.setup(subject, body.target_url)}

    @app.post("/test/run", responses={200: {"model": SuiteReport}, **ERRORS})
    def run(body: RunRequest, subject: str = Depends(operator)):
        return Response(content=service.run(subject, body.session_id), media_type="application/json")

    @app.get("/test/report", responses={200: {"model": SuiteReport}, **ERRORS})
    def report(session_id: str | None = None, subject: str = Depends(operator)):
        if session_id is None or not SESSION_ID.match(session_id):
            raise TesterError(400, "Query parameter session_id is required and must be a valid session ID.")
        return Response(content=service.report(subject, session_id), media_type="application/json")

    return app
