"""Setup / run / report lifecycle against a fake target."""

import json
import threading
import time
import uuid

import httpx
import pytest

from tester.config import FIXTURES, Settings
from tester.models import SuiteReport
from tester.suite.checks import CHECKS
from tester.suite.runner import CaseResult
from tester.target import CommunicationError

from .conftest import OTHER_OPERATOR, TARGET, TOKENS, auth, make_settings

MANIFEST = json.loads((FIXTURES / "manifest.json").read_text(encoding="utf-8"))
TEST_IDS = [case["test_id"] for case in MANIFEST["tests"]]


def setup_session(client):
    response = client.post("/test/setup", json={"target_url": TARGET}, headers=auth())
    assert response.status_code == 201, response.text
    return response.json()["session_id"]


def run(client, session_id, token=None):
    return client.post("/test/run", json={"session_id": session_id}, headers=auth(token) if token else auth())


def report(client, session_id, token=None):
    return client.get("/test/report", params={"session_id": session_id},
                      headers=auth(token) if token else auth())


def results_by_id(body):
    return {r["test_id"]: r for r in body["results"]}


##  ---- Setup ----

def test_setup_creates_uuid_and_prepares_target(make_client, fake):
    client = make_client()
    session_id = setup_session(client)
    uuid.UUID(session_id)
    [(method, path, headers, body)] = fake.setups()
    assert (method, path) == ("POST", "/system/test/setup")
    assert body == {"session_id": session_id, "setup": {}}
    assert headers["authorization"] == f"Bearer {TOKENS['test-admin']}"
    assert "x-test-session" not in headers


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer wrong"}, {"Authorization": "Basic abc"}])
def test_setup_requires_operator_token(make_client, headers):
    response = make_client().post("/test/setup", json={"target_url": TARGET}, headers=headers)
    assert response.status_code == 401
    assert response.json()["source"] == "tester"


@pytest.mark.parametrize("body", [
    {"target_url": "https://other.example.edu/system"},
    {"target_url": TARGET + "/test"},
    {"target_url": TARGET + "?x=1"},
    {"target_url": "https://user:pw@team12.example.edu/system"},
    {},
    {"target_url": TARGET, "extra": 1},
])
def test_setup_rejects_invalid_requests(make_client, fake, body):
    response = make_client().post("/test/setup", json=body, headers=auth())
    assert response.status_code == 400
    assert response.json()["source"] == "tester" and response.json()["message"].strip()
    assert fake.setups() == []


def test_setup_forwards_system_error_and_session_is_not_runnable(make_client, fake):
    client = make_client()
    fake.setup_reply = (500, {"message": "Could not initialize the session database.", "source": "system"})
    response = client.post("/test/setup", json={"target_url": TARGET}, headers=auth())
    assert response.status_code == 500
    assert response.json() == {"message": "Could not initialize the session database.", "source": "system"}
    failed_id = fake.setups()[0][3]["session_id"]
    assert run(client, failed_id).status_code == 409
    assert report(client, failed_id).status_code == 409


def test_setup_rejects_wrong_echo(make_client, fake):
    fake.echo_other_id = True
    response = make_client().post("/test/setup", json={"target_url": TARGET}, headers=auth())
    assert response.status_code == 500
    assert response.json()["source"] == "system"


def test_setup_without_error_body_is_attributed_to_system(make_client, fake):
    fake.setup_reply = (503, {"detail": "unavailable"})
    response = make_client().post("/test/setup", json={"target_url": TARGET}, headers=auth())
    assert response.status_code == 503
    assert response.json()["source"] == "system"


def test_setup_communication_failure_queues_cleanup(make_client, fake):
    client = make_client()
    fake.setup_raises = httpx.ConnectError("refused")
    response = client.post("/test/setup", json={"target_url": TARGET}, headers=auth())
    assert response.status_code == 500
    assert response.json()["source"] == "communication"
    failed_id = fake.setups()[0][3]["session_id"]

    fake.setup_raises = None
    setup_session(client)
    assert fake.setups()[1][3]["setup"] == {"cleanup_session_ids": [failed_id]}
    setup_session(client)
    assert fake.setups()[2][3]["setup"] == {}


##  ---- Run and report ----

def test_run_returns_complete_report_and_report_is_identical(make_client, fake):
    client = make_client()
    session_id = setup_session(client)
    response = run(client, session_id)
    assert response.status_code == 200
    body = response.json()
    SuiteReport.model_validate(body)
    assert body["session_id"] == session_id and body["target_url"] == TARGET
    assert [r["test_id"] for r in body["results"]] == TEST_IDS
    results = results_by_id(body)
    assert results["P3-SESSION-DUPLICATE"]["outcome"] == "pass"
    assert results["P3-CODE-REPORT"]["outcome"] == "pass"
    assert results["P3-HEALTH"]["outcome"] == "skip"
    assert "not implemented" in results["P3-HEALTH"]["message"]
    assert results["P3-VERSION-VALID"]["outcome"] == "skip"
    assert body["coverage"]["code"] == {"covered": 40, "total": 50, "basis": "Fake target source lines"}
    assert body["coverage"]["component"]["covered"] == 1 and body["coverage"]["component"]["total"] == 6
    assert body["coverage"]["system"]["covered"] == 0 and body["coverage"]["system"]["total"] == 8

    stored = report(client, session_id)
    assert stored.status_code == 200
    assert stored.content == response.content


def test_run_is_single_use(make_client):
    client = make_client()
    session_id = setup_session(client)
    assert run(client, session_id).status_code == 200
    again = run(client, session_id)
    assert again.status_code == 409 and again.json()["source"] == "tester"


def test_invalid_run_request_does_not_consume_session(make_client):
    client = make_client()
    session_id = setup_session(client)
    assert client.post("/test/run", json={"session_id": "bad id!"}, headers=auth()).status_code == 400
    assert client.post("/test/run", json={}, headers=auth()).status_code == 400
    assert run(client, session_id).status_code == 200


def test_unknown_and_foreign_sessions(make_client):
    client = make_client()
    session_id = setup_session(client)
    assert run(client, "unknown-session").status_code == 404
    assert report(client, "unknown-session").status_code == 404
    assert run(client, session_id, OTHER_OPERATOR).status_code == 403
    assert report(client, session_id, OTHER_OPERATOR).status_code == 403
    assert client.get("/test/report", headers=auth()).status_code == 400


def test_report_before_run_is_409(make_client):
    client = make_client()
    response = report(client, setup_session(client))
    assert response.status_code == 409
    assert response.json() == {"message": "The suite has not ended; retry the report later.", "source": "tester"}


def test_code_coverage_unavailable_is_paired_nulls(make_client, fake):
    fake.report_reply = (200, {"session_id": "x", "coverage": {"code": {"covered": None, "total": None,
                                                                         "basis": "instrumentation unavailable"}}})
    client = make_client()
    body = run(client, setup_session(client)).json()
    assert results_by_id(body)["P3-CODE-REPORT"]["outcome"] == "fail"
    assert body["coverage"]["code"]["covered"] is None and body["coverage"]["code"]["total"] is None


def test_system_report_5xx_is_system_error(make_client, fake):
    fake.report_reply = (503, {"message": "down", "source": "system"})
    client = make_client()
    result = results_by_id(run(client, setup_session(client)).json())["P3-CODE-REPORT"]
    assert result == {"test_id": "P3-CODE-REPORT", "outcome": "error", "source": "system",
                      "message": result["message"]}


##  ---- Outcome classification and prerequisites ----

def test_check_failures_are_classified(make_client):
    def communication(case, ctx):
        raise CommunicationError("GET /api/v1/health timed out after 10s with no response.")

    def broken(case, ctx):
        raise RuntimeError("bug")

    def upload_fails(case, ctx):
        ctx.mark()
        return CaseResult.failed("Expected 202; received 500.")

    client = make_client(checks={"health": communication, "upload_without_token": broken,
                                 "upload_clean": upload_fails})
    results = results_by_id(run(client, setup_session(client)).json())
    assert results["P3-HEALTH"]["outcome"] == "error" and results["P3-HEALTH"]["source"] == "communication"
    assert results["P3-AUTH-UPLOAD"]["outcome"] == "error" and results["P3-AUTH-UPLOAD"]["source"] == "tester"
    assert results["P3-UPLOAD-CLEAN"]["outcome"] == "fail"
    assert results["P3-VERSION-VALID"]["outcome"] == "skip"
    assert "P3-UPLOAD-CLEAN did not produce a usable resource" in results["P3-VERSION-VALID"]["message"]


def test_failed_assertions_still_earn_coverage(make_client):
    def evaluated_but_wrong(case, ctx):
        ctx.mark()
        return CaseResult.failed("wrong status")

    client = make_client(checks={"upload_clean": evaluated_but_wrong})
    coverage = run(client, setup_session(client)).json()["coverage"]
    assert coverage["component"]["covered"] == 2       # C2, C3
    assert coverage["system"]["covered"] == 1          # AC-01


##  ---- Abort, concurrency and recovery ----

def test_deadline_abort_returns_500_and_stores_available_results(make_client):
    def slow(case, ctx):
        time.sleep(1.2)
        ctx.deadline.check()
        return CaseResult.passed("unreachable")

    client = make_client(checks={**CHECKS, "health": slow}, profile_changes={"timing": {"suite_seconds": 1}})
    session_id = setup_session(client)
    response = run(client, session_id)
    assert response.status_code == 500
    assert response.json()["source"] == "tester"
    body = report(client, session_id).json()
    SuiteReport.model_validate(body)
    first, *rest = body["results"]
    assert first["outcome"] == "error" and first["source"] == "tester"
    assert {r["outcome"] for r in rest} == {"skip"}
    assert run(client, session_id).status_code == 409


def test_concurrent_run_and_lost_response_recovery(make_client):
    release = threading.Event()
    started = threading.Event()

    def blocking(case, ctx):
        started.set()
        release.wait(10)
        return CaseResult.passed("released")

    client = make_client(checks={**CHECKS, "health": blocking})
    session_id = setup_session(client)
    first = {}
    caller = threading.Thread(target=lambda: first.update(response=run(client, session_id)))
    caller.start()
    assert started.wait(5)
    assert report(client, session_id).status_code == 409
    assert run(client, session_id).status_code == 409
    release.set()
    caller.join(10)
    assert first["response"].status_code == 200
    assert report(client, session_id).content == first["response"].content


def test_restart_recovers_interrupted_sessions(tmp_path, make_client, fake):
    settings = make_settings(tmp_path)
    client = make_client(settings=settings)
    running_id = setup_session(client)
    service = client.app.state.service
    assert service.store.claim_run(running_id)
    service.store.save_progress(running_id, {
        "results": [{"test_id": "P3-HEALTH", "outcome": "pass", "message": "ok"}],
        "components": [], "acceptance": [], "code": None})
    preparing_id = str(uuid.uuid4())
    service.store.create(preparing_id, "operator-1", TARGET, service.store.get(running_id).plan)

    restarted = make_client(settings=settings)
    body = report(restarted, running_id).json()
    SuiteReport.model_validate(body)
    assert body["results"][0]["outcome"] == "pass"
    assert body["results"][1]["outcome"] == "error" and "restarted" in body["results"][1]["message"]
    assert {r["outcome"] for r in body["results"][2:]} == {"skip"}
    assert restarted.app.state.service.store.get(preparing_id).state == "SETUP_FAILED"
    setup_session(restarted)
    assert fake.setups()[-1][3]["setup"] == {"cleanup_session_ids": [preparing_id]}


##  ---- Configuration ----

def test_allowed_target_needs_all_role_tokens(tmp_path):
    with pytest.raises(ValueError, match="TARGET_AUTH_MAP_JSON"):
        Settings(_env_file=None, tester_db_path=str(tmp_path / "t.db"), allowed_target_urls=[TARGET],
                 target_auth_map_json={TARGET: {"userA": "a"}})


def test_production_requires_https(tmp_path):
    with pytest.raises(ValueError, match="HTTPS"):
        Settings(_env_file=None, app_env="production", allowed_target_urls=["http://team12.example.edu/system"],
                 target_auth_map_json={"http://team12.example.edu/system": TOKENS})
