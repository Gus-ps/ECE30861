"""Phase 4 controlled-audit-failure cases (shared specification §14.1) against the fake target.

Team 9's executable 2.1.0 manifest does not exist yet, so these run from a small test
manifest that uses the Phase 4 catalogs and profile and names the cases as the Phase 4
test plan does, with Team 12's clean_all_six workbook (tester/fixtures/phase4/).
"""

import hashlib
import json
import shutil

import httpx
import pytest

from tester.config import FIXTURES

from .conftest import make_settings
from .test_fixtures_and_record import run, setup

PLAN = json.loads((FIXTURES.parent.parent / "ref" / "Phase4_Agent_Context_Pack" / "phase4-test-plan.json")
                  .read_text(encoding="utf-8"))
CASES = [
    {"test_id": "P4-FAULT-SETUP", "check": "fault_setup", "components": ["C6"]},
    {"test_id": "P3-AUDIT-FAILURE-ENVELOPE", "check": "fault_failure_envelope", "components": ["C3", "C5", "C6"],
     "operations": [2, 4, 5, "S", "R"], "prerequisites": ["P4-FAULT-SETUP"], "parameters": {"fixture": "clean_all_six"}},
    {"test_id": "P4-FAULT-RECOVERY", "check": "fault_recovery", "components": ["C5", "C6"], "acceptance": ["AC-11"],
     "operations": [6, 5, 10], "prerequisites": ["P3-AUDIT-FAILURE-ENVELOPE"]},
    {"test_id": "P4-FAULT-AUTH", "check": "fault_auth", "components": ["C1", "C6"]},
    {"test_id": "P4-FAULT-INVALID", "check": "fault_invalid", "components": ["C1", "C6"]},
]
FAULT_IDS = [case["test_id"] for case in CASES]


@pytest.fixture
def phase4(tmp_path, fake, make_client):
    ##  build(cases=CASES) -> a client on a Phase 4-style manifest, fast polling and a clean_all_six pack.
    fake.project.ruleset = "2.0.0"
    profile = json.loads((FIXTURES / "pod_profile_phase4.json").read_text(encoding="utf-8"))
    profile["timing"]["poll_interval_seconds"] = 0.01
    (tmp_path / "profile.json").write_text(json.dumps(profile), encoding="utf-8")
    pack = tmp_path / "pack"
    pack.mkdir()
    shutil.copy(FIXTURES / "phase4" / "clean_all_six.xlsx", pack / "clean_all_six.xlsx")
    sha = hashlib.sha256((pack / "clean_all_six.xlsx").read_bytes()).hexdigest()
    (pack / "expectations.json").write_text(json.dumps({"ruleset_version": "2.0.0", "fixtures": {"clean_all_six": {
        "kind": "accepted", "file": "clean_all_six.xlsx", "sha256": sha, "origin": "team12",
        "upload_name": "clean_all_six.xlsx", "expected_status": "AUDIT_COMPLETE", "findings": []}}}), encoding="utf-8")

    def build(cases=CASES, with_pack=True):
        manifest = {"manifest_version": "test-fault-1", "ruleset_version": "2.0.0", "specification_version": "2.1.0",
                    "components": PLAN["components"], "acceptance": PLAN["acceptance"], "tests": cases}
        (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        settings = make_settings(tmp_path, pod_profile_path=tmp_path / "profile.json",
                                 manifest_path=tmp_path / "manifest.json",
                                 expectations_path=pack / "expectations.json" if with_pack else None)
        return make_client(settings=settings)
    return build


def results_of(client):
    session_id = setup(client).json()["session_id"]
    body = run(client, session_id).json()
    return {r["test_id"]: r for r in body["results"]}, session_id


def fault_setups(fake):
    return [r for r in fake.setups() if (r[3] or {}).get("setup", {}).get("faults") is not None]


def project(method, path):
    ##  Matches project calls by method and a path fragment.
    return lambda request: request.method == method and path in request.url.path


def wrap(fake, match, transform):
    ##  Replies to matching project calls with transform(status, body) of the fake project's reply.
    def reply(request):
        if not match(request):
            return None
        status, body, *rest = fake.project.handle(request.method, request.url.path.removeprefix("/system"),
                                                  dict(request.headers), request.content)
        headers = rest[0] if rest else {}
        is_json = headers.get("content-type") == "application/json"
        value = json.loads(body) if is_json else body if isinstance(body, bytes) else json.loads(json.dumps(body))
        status, value = transform(status, value)
        if is_json and isinstance(value, dict) and "reportVersion" in value:
            return status, json.dumps(value).encode(), headers
        return (status, value, headers) if isinstance(value, bytes) else (status, value)
    fake.project_reply = reply


##  ---- Against a conforming target ----

def test_fault_cases_pass_against_a_conforming_target(phase4, fake):
    client = phase4()
    by_id, session_id = results_of(client)
    assert {t: r["outcome"] for t, r in by_id.items()} == dict.fromkeys(FAULT_IDS, "pass"), by_id
    assert by_id["P3-AUDIT-FAILURE-ENVELOPE"]["message"] == (
        "The fault-session audit failed exactly as injected (TEST_AUDIT_FAILURE, no findings), its report lists no "
        "checks, and the source downloads unchanged.")
    armed = fault_setups(fake)
    assert armed[0][2]["authorization"] == "Bearer tok-admin" and armed[0][3]["setup"] == {"faults": {"audit_failures": 1}}
    fault_session = armed[0][3]["session_id"]
    assert fault_session != session_id
    ##  The fault session's work is sent under its own header, and its coverage is never requested.
    uploads = [r for r in fake.requests if r[0] == "POST" and r[1] == "/system/api/v1/workbooks"]
    assert [r[2]["x-test-session"] for r in uploads] == [fault_session]
    assert not any(r[1] == "/system/test/report" and fault_session in str(r) for r in fake.requests)

    record = client.app.state.service.store.get(session_id).record
    assert record["fault_session_ids"] == [fault_session]
    ##  Only the armed session is queued: the refused auth/invalid setups created nothing.
    next_setup = setup(client)
    assert next_setup.status_code == 201
    assert fake.setups()[-1][3]["setup"] == {"cleanup_session_ids": [fault_session]}


def test_parameters_select_single_vectors(phase4, fake):
    cases = [{"test_id": "P4-FAULT-AUTH-NONE", "check": "fault_auth", "components": ["C1", "C6"],
              "parameters": {"credential": "none"}},
             {"test_id": "P4-FAULT-INVALID-TRUE", "check": "fault_invalid", "components": ["C1", "C6"],
              "parameters": {"vector": "true"}}]
    by_id, _ = results_of(phase4(cases))
    assert by_id["P4-FAULT-AUTH-NONE"]["message"] == \
        "Fault setup was refused for none credentials, leaving no runnable session."
    assert by_id["P4-FAULT-INVALID-TRUE"]["outcome"] == "pass"
    sent = [(r[2].get("authorization"), r[3]["setup"]["faults"]) for r in fault_setups(fake)]
    assert sent == [(None, {"audit_failures": 1}), ("Bearer tok-admin", {"audit_failures": True})]


##  ---- Against targets that get it wrong ----

def test_a_disabled_fault_switch_is_a_failure_not_a_skip(phase4, fake):
    fake.fault_switch = False
    by_id, _ = results_of(phase4())
    assert by_id["P4-FAULT-SETUP"]["outcome"] == "fail"
    assert by_id["P4-FAULT-SETUP"]["message"] == \
        "Expected 201 for fault-session setup; received 403 (the fault capability was refused)."
    assert by_id["P3-AUDIT-FAILURE-ENVELOPE"]["outcome"] == "skip"
    assert by_id["P4-FAULT-RECOVERY"]["outcome"] == "skip"


def test_a_target_that_ignores_the_fault(phase4, fake):
    fake.project.armed = type("Never", (set,), {"add": lambda self, item: None})()
    by_id, _ = results_of(phase4())
    result = by_id["P3-AUDIT-FAILURE-ENVELOPE"]
    assert result["outcome"] == "fail" and "status AUDIT_COMPLETE: the armed audit failure was not applied" in \
        result["message"]
    assert "version status is AUDIT_COMPLETE, expected PROCESSING_FAILED" in result["message"]
    assert by_id["P4-FAULT-RECOVERY"]["outcome"] == "skip"


@pytest.mark.parametrize("match, transform, text", [
    (project("GET", "/audits/"), lambda s, b: (s, {**b, "error": {**b["error"], "details": {"stage": "audit"}}})
     if isinstance(b, dict) and b.get("status") == "PROCESSING_FAILED" and "reportVersion" not in b else (s, b),
     "error details is {'stage': 'audit'}, expected {'stage': 'audit', 'testOnly': True}"),
    (project("GET", "/audits/"), lambda s, b: (s, {**b, "error": {**b["error"], "message": "Boom."}})
     if isinstance(b, dict) and b.get("status") == "PROCESSING_FAILED" and "reportVersion" not in b else (s, b),
     "error message is 'Boom.'"),
    (project("GET", "/report"), lambda s, b: (s, {**b, "checksPerformed": ["ALT_TEXT"]}),
     "report checksPerformed is ['ALT_TEXT'], expected []"),
    (project("GET", "/report"), lambda s, b: (404, {"code": "NOT_FOUND", "message": "No.", "requestId": "r1",
                                                           "details": {}}), "the audit report download returned 404"),
    (project("GET", "/source"), lambda s, b: (s, b + b"tampered"), "the downloaded source (SHA256"),
])
def test_the_failure_envelope_reports_each_problem(phase4, fake, match, transform, text):
    wrap(fake, match, transform)
    result = results_of(phase4())[0]["P3-AUDIT-FAILURE-ENVELOPE"]
    assert result["outcome"] == "fail" and text in result["message"], result["message"]


def test_recovery_needs_a_normal_reaudit(phase4, fake):
    original = fake.project._new_audit

    def fails_again(version, session):
        if version["audits"]:                 # the re-audit: arm the session again
            fake.project.armed.add(session)
        return original(version, session)
    fake.project._new_audit = fails_again
    result = results_of(phase4())[0]["P4-FAULT-RECOVERY"]
    assert result["outcome"] == "fail"
    assert "processing failed (TEST_AUDIT_FAILURE), expected AUDIT_COMPLETE" in result["message"], result["message"]


@pytest.mark.parametrize("match, transform, text", [
    (project("GET", "/history"), lambda s, b: (s, {**b, "audits": list(reversed(b["audits"]))}),
     "history lists audits"),
    (project("POST", "/audits"), lambda s, b: (200, b), "Expected 202 for the manual re-audit; received 200"),
    (project("POST", "/audits"), lambda s, b: (s, {**b, "status": "AUDIT_COMPLETE"}),
     "202 body does not match ReauditResponse (status"),
])
def test_recovery_reports_each_problem(phase4, fake, match, transform, text):
    wrap(fake, match, transform)
    result = results_of(phase4())[0]["P4-FAULT-RECOVERY"]
    assert result["outcome"] == "fail" and text in result["message"], result["message"]


def test_a_changed_failed_audit_is_caught_after_recovery(phase4, fake):
    reads = {"after": False}

    def transform(status, body):
        if reads["after"] and body.get("status") == "PROCESSING_FAILED":
            body["completedAt"] = "2099-01-01T00:00:00Z"
        if request_is_reaudit(body):
            reads["after"] = True
        return status, body

    def request_is_reaudit(body):
        return set(body) == {"auditId", "versionId", "rulesetVersion", "status"}
    wrap(fake, lambda r: "/audits" in r.url.path and "/report" not in r.url.path, transform)
    result = results_of(phase4())[0]["P4-FAULT-RECOVERY"]
    assert result["outcome"] == "fail"
    assert "the failed audit changed or could not be read after the re-audit" in result["message"]


def test_a_reviewer_who_can_arm_faults_fails_and_is_queued_for_cleanup(phase4, fake):
    original = fake.system_setup

    def lenient(authorization, body):
        if authorization == "Bearer tok-r":
            authorization = "Bearer tok-admin"
        return original(authorization, body)
    fake.system_setup = lenient
    client = phase4([CASES[3]])
    by_id, session_id = results_of(client)
    result = by_id["P4-FAULT-AUTH"]
    assert result["outcome"] == "fail"
    assert "reviewer credential: expected 403, received 201, creating the session" in result["message"]
    reviewer_session = next(r[3]["session_id"] for r in fault_setups(fake) if r[2].get("authorization") == "Bearer tok-r")
    assert client.app.state.service.store.get(session_id).record["fault_session_ids"] == [reviewer_session]


def test_invalid_faults_must_be_refused_by_the_system(phase4, fake):
    original = fake.system_setup

    def accepts_true(authorization, body):
        faults = body.get("setup", {}).get("faults")
        if faults == {"audit_failures": True}:
            body = {**body, "setup": {"faults": {"audit_failures": 1}}}
        return original(authorization, body)
    fake.system_setup = accepts_true
    result = results_of(phase4([CASES[4]]))[0]["P4-FAULT-INVALID"]
    assert result["outcome"] == "fail" and "true faults: expected 400, received 201" in result["message"]


def test_a_refused_setup_must_not_leave_a_runnable_session(phase4, fake):
    original = fake.system_setup

    def refuses_but_keeps(authorization, body):
        response = original(authorization, body)
        if response.status_code == 400:
            fake.sessions.add(body["session_id"])
        return response
    fake.system_setup = refuses_but_keeps
    result = results_of(phase4([CASES[4]]))[0]["P4-FAULT-INVALID"]
    assert result["outcome"] == "fail"
    assert "a project call naming the refused session returned 404, expected 400" in result["message"]


def test_a_wrong_error_source_is_reported(phase4, fake):
    original = fake.system_setup

    def tester_source(authorization, body):
        response = original(authorization, body)
        if response.status_code == 400:
            return httpx.Response(400, json={"message": "Bad faults.", "source": "tester"})
        return response
    fake.system_setup = tester_source
    result = results_of(phase4([CASES[4]]))[0]["P4-FAULT-INVALID"]
    assert result["outcome"] == "fail" and "source is tester, expected system" in result["message"]


def test_without_a_pack_the_envelope_skips_but_its_session_is_still_cleaned(phase4, fake):
    client = phase4(with_pack=False)
    by_id, session_id = results_of(client)
    assert by_id["P4-FAULT-SETUP"]["outcome"] == "pass"
    assert by_id["P3-AUDIT-FAILURE-ENVELOPE"]["message"] == \
        "Not executed: no fixture pack with a clean_all_six entry was frozen at setup."
    assert by_id["P4-FAULT-RECOVERY"]["outcome"] == "skip"
    assert len(client.app.state.service.store.get(session_id).record["fault_session_ids"]) == 1


def test_phase3_manifest_is_unaffected(make_client, fake):
    ##  The Phase 3 suite never arms a fault and records no fault sessions.
    client = make_client()
    session_id = setup(client).json()["session_id"]
    run(client, session_id)
    assert fault_setups(fake) == []
    assert client.app.state.service.store.get(session_id).record["fault_session_ids"] == []
