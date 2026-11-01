"""Rehearsal-only stand-in target system: system /test/setup and /test/report, plus the
fake project API from tests/fake_project.py (health, upload intake, version reads).

Not part of the tester and never deployed; scripts/rehearsal/rehearse.py starts it on 127.0.0.1.

Mounted under /system so the tester sees a base path, like a real deployment.
POST /control sets delays and canned failures; GET /control/log returns every request seen
(project calls are logged without their bodies).
"""

import asyncio
import sys
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tests.fake_project import USERS, FakeProject  # noqa: E402

ADMIN_TOKEN = "tok-admin"
state = {"sessions": set(), "log": [], "setup_delay": 0, "duplicate_delay": 0, "report_delay": 0,
         "setup_reply": None}
project = FakeProject(state["sessions"])

control = FastAPI()
system = FastAPI()


@control.post("/control")
async def set_control(request: Request):
    ##  Also accepts "ruleset" ("2.0.0" for the Phase 4 rehearsal) and "processing_polls".
    body = await request.json()
    for key in ("ruleset", "processing_polls"):
        if key in body:
            setattr(project, key, body.pop(key))
    state.update(body)
    return {"ok": True}


@control.get("/control/log")
async def get_log():
    return state["log"]


@control.post("/control/reset_log")
async def reset_log():
    state["log"].clear()
    return {"ok": True}


def record(request, body):
    state["log"].append({"method": request.method, "path": request.url.path,
                         "query": dict(request.query_params),
                         "authorization": request.headers.get("authorization"),
                         "x_test_session": request.headers.get("x-test-session"),
                         "content_length": int(request.headers.get("content-length") or 0), "body": body})


def unauthorized(request):
    return request.headers.get("authorization") != f"Bearer {ADMIN_TOKEN}"


@system.post("/test/setup")
async def setup(request: Request):
    body = await request.json()
    record(request, body)

    def refuse(status, message):
        return JSONResponse({"message": message, "source": "system"}, status)
    if unauthorized(request):
        token = (request.headers.get("authorization") or "").removeprefix("Bearer ")
        return refuse(403, "Only test-admin may prepare sessions.") if token in USERS \
            else refuse(401, "test-admin token required.")
    if state["setup_reply"]:
        status, reply = state["setup_reply"]
        return JSONResponse(reply, status)
    setup_body = body.get("setup", {})
    if set(setup_body) - {"cleanup_session_ids", "faults"}:
        return refuse(400, "Unknown setup keys.")
    faults = setup_body.get("faults")
    if "faults" in setup_body:
        count = faults.get("audit_failures") if isinstance(faults, dict) else None
        if set(faults or {}) != {"audit_failures"} or type(count) is not int or count != 1:
            return refuse(400, 'faults must be exactly {"audit_failures": 1}.')
    session_id = body.get("session_id")
    if session_id in state["sessions"]:
        await asyncio.sleep(state["duplicate_delay"])
        return refuse(409, "Session already exists.")
    await asyncio.sleep(state["setup_delay"])
    project.cleanup(setup_body.get("cleanup_session_ids", []))
    state["sessions"].add(session_id)
    if faults:
        project.armed.add(session_id)
    return JSONResponse({"session_id": session_id}, 201)


@system.get("/test/report")
async def report(request: Request, session_id: str):
    record(request, None)
    if unauthorized(request):
        return JSONResponse({"message": "test-admin token required.", "source": "system"}, 401)
    await asyncio.sleep(state["report_delay"])
    if session_id not in state["sessions"]:
        return JSONResponse({"message": "Unknown session.", "source": "system"}, 404)
    return {"session_id": session_id,
            "coverage": {"code": {"covered": 40, "total": 50, "basis": "Stand-in system: fixed test constant"}}}


@system.api_route("/api/v1/{rest:path}", methods=["GET", "POST"])
async def project_api(request: Request, rest: str):
    record(request, None)
    status, reply, *headers = project.handle(request.method, f"/api/v1/{rest}", dict(request.headers),
                                             await request.body())
    if isinstance(reply, bytes):
        return Response(reply, status, headers=headers[0] if headers else {})
    return JSONResponse(reply, status)


control.mount("/system", system)
app = control
