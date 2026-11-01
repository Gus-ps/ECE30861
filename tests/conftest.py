"""Test-only fake target system and app factory helpers."""

import hashlib
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from tester.config import FIXTURES, Settings
from tester.main import create_app

from .fake_project import FakeProject

TARGET = "https://team12.example.edu/system"
OPERATOR = "operator-token"
OTHER_OPERATOR = "other-operator-token"
TOKENS = {"userA": "tok-a", "userB": "tok-b", "reviewer": "tok-r", "test-admin": "tok-admin"}


def sha(token):
    return hashlib.sha256(token.encode()).hexdigest()


def auth(token=OPERATOR):
    return {"Authorization": f"Bearer {token}"}


class FakeSystem:
    """A minimal target: system /test/setup and /test/report, plus fake_project's project API."""

    def __init__(self):
        self.requests = []
        self.sessions = set()
        self.project = FakeProject(self.sessions)
        self.setup_reply = None          # (status, json) override for the next setups
        self.setup_raises = None         # exception raised instead of replying
        self.echo_other_id = False
        self.report_reply = None
        self.project_reply = None        # request -> (status, json or raw bytes) or None to use the fake project
        self.fault_switch = True         # the trusted server switch that permits setup.faults (§14.1)

    def __call__(self, request: httpx.Request):
        try:
            body = json.loads(request.content) if request.content else None
        except ValueError:
            body = request.content           # multipart and other non-JSON bodies, kept raw
        self.requests.append((request.method, request.url.path, dict(request.headers), body))
        if request.url.path == "/system/test/setup":
            if self.setup_raises:
                raise self.setup_raises
            if self.setup_reply:
                return httpx.Response(self.setup_reply[0], json=self.setup_reply[1])
            return self.system_setup(request.headers.get("authorization", ""), body)
        if request.url.path == "/system/test/report":
            if self.report_reply:
                return httpx.Response(self.report_reply[0], json=self.report_reply[1])
            return httpx.Response(200, json={"session_id": request.url.params["session_id"], "coverage": {
                "code": {"covered": 40, "total": 50, "basis": "Fake target source lines"}}})
        if request.url.path.startswith("/system/api/v1/"):
            override = self.project_reply and self.project_reply(request)
            if override:
                status, reply = override
                return httpx.Response(status, **({"content": reply} if isinstance(reply, bytes) else {"json": reply}))
            status, reply = self.project.handle(request.method, request.url.path.removeprefix("/system"),
                                                dict(request.headers), request.content)
            return httpx.Response(status, **({"content": reply} if isinstance(reply, bytes) else {"json": reply}))
        return httpx.Response(404, json={"code": "NOT_FOUND", "message": "No route.", "requestId": "r1", "details": {}})

    def system_setup(self, authorization, body):
        ##  Credentials, then the setup shape (§14: cleanup_session_ids and faults only), then the session.
        def refuse(status, message):
            return httpx.Response(status, json={"message": message, "source": "system"})
        token = authorization.removeprefix("Bearer ")
        if token != TOKENS["test-admin"]:
            return refuse(403, "Only test-admin may prepare sessions.") if token in TOKENS.values() \
                else refuse(401, "A valid test-admin token is required.")
        setup = body.get("setup", {})
        if set(setup) - {"cleanup_session_ids", "faults"}:
            return refuse(400, "Unknown setup keys.")
        faults = setup.get("faults")
        if "faults" in setup:
            count = faults.get("audit_failures") if isinstance(faults, dict) else None
            if set(faults or {}) != {"audit_failures"} or type(count) is not int or count != 1:
                return refuse(400, "faults must be exactly {\"audit_failures\": 1}.")
            if not self.fault_switch:
                return refuse(403, "The test fault switch is disabled on this deployment.")
        session_id = body["session_id"]
        if session_id in self.sessions:
            return refuse(409, "Session exists.")
        self.sessions.add(session_id)
        if faults:
            self.project.armed.add(session_id)
        return httpx.Response(201, json={"session_id": "other-id" if self.echo_other_id else session_id})

    def setups(self):
        return [r for r in self.requests if r[1] == "/system/test/setup"]


def make_settings(tmp_path, profile_changes=None, **overrides):
    profile_path = FIXTURES / "pod_profile.json"
    if profile_changes:
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
        for section, values in profile_changes.items():
            profile[section].update(values)
        profile_path = tmp_path / "pod_profile.json"
        profile_path.write_text(json.dumps(profile), encoding="utf-8")
    values = dict(
        tester_db_path=str(tmp_path / "tester.db"),
        tester_operator_token_hashes_json={sha(OPERATOR): "operator-1", sha(OTHER_OPERATOR): "operator-2"},
        allowed_target_urls=[TARGET],
        target_auth_map_json={TARGET: TOKENS},
        pod_profile_path=profile_path,
    )
    values.update(overrides)
    return Settings(_env_file=None, **values)


@pytest.fixture
def fake():
    return FakeSystem()


@pytest.fixture
def make_client(tmp_path, fake):
    clients = []

    def build(checks=None, profile_changes=None, settings=None):
        settings = settings or make_settings(tmp_path, profile_changes)
        client = TestClient(create_app(settings, transport=httpx.MockTransport(fake), checks=checks))
        client.__enter__()
        clients.append(client)
        return client

    yield build
    for client in clients:
        client.__exit__(None, None, None)
