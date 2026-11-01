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
from fastapi.responses import JSONResponse

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tests.fake_project import FakeProject  # noqa: E402

ADMIN_TOKEN = "tok-admin"
state = {"sessions": set(), "log": [], "setup_delay": 0, "duplicate_delay": 0, "report_delay": 0,
         "setup_reply": None}
project = FakeProject(state["sessions"])

control = FastAPI()
system = FastAPI()


@control.post("/control")
async def set_control(request: Request):
    body = await request.json()
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
    if unauthorized(request):
        return JSONResponse({"message": "test-admin token required.", "source": "system"}, 401)
    if state["setup_reply"]:
        status, reply = state["setup_reply"]
        return JSONResponse(reply, status)
    session_id = body.get("session_id")
    if session_id in state["sessions"]:
        await asyncio.sleep(state["duplicate_delay"])
        return JSONResponse({"message": "Session already exists.", "source": "system"}, 409)
    await asyncio.sleep(state["setup_delay"])
    state["sessions"].add(session_id)
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
    status, reply = project.handle(request.method, f"/api/v1/{rest}", dict(request.headers), await request.body())
    return JSONResponse(reply, status)


control.mount("/system", system)
app = control
