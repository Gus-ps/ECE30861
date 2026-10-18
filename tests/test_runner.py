"""Runner behaviour: prerequisites, coverage markers, project calls, polling."""

from tester.suite.runner import CaseResult
from tester.target import CommunicationError

from .test_lifecycle import results_by_id, run, setup_session


def run_with(make_client, checks, profile_changes=None):
    client = make_client(checks=checks, profile_changes=profile_changes)
    body = run(client, setup_session(client)).json()
    return results_by_id(body), body["coverage"]


##  ---- Prerequisites are about resources, not verdicts ----

def test_failed_case_that_provides_its_resource_unblocks_dependants(make_client):
    def upload_wrong_status_but_ids_returned(case, ctx):
        ctx.provide()
        return CaseResult.failed("Expected status PROCESSING; received QUEUED.")

    results, _ = run_with(make_client, {
        "upload_clean": upload_wrong_status_but_ids_returned,
        "version_clean": lambda case, ctx: CaseResult.passed("metadata matches"),
    })
    assert results["P3-UPLOAD-CLEAN"]["outcome"] == "fail"
    assert results["P3-VERSION-VALID"]["outcome"] == "pass"


def test_error_never_provides_a_resource(make_client):
    def provide_then_time_out(case, ctx):
        ctx.provide()
        raise CommunicationError("POST /api/v1/workbooks timed out after 35s with no response.")

    results, _ = run_with(make_client, {"upload_seeded": provide_then_time_out,
                                        "audit_seeded": lambda case, ctx: CaseResult.passed("unreachable")})
    assert results["P3-UPLOAD-SEEDED"]["outcome"] == "error"
    assert results["P3-AUDIT-SEEDED"]["outcome"] == "skip"
    assert "P3-UPLOAD-SEEDED did not produce a usable resource" in results["P3-AUDIT-SEEDED"]["message"]


##  ---- Coverage markers ----

def test_partial_mark_earns_only_the_named_criteria(make_client):
    def audit_reached_only_detection(case, ctx):
        ctx.mark(components=["C4"], acceptance=["AC-04"])
        return CaseResult.failed("Audit status was PROCESSING_FAILED; findings not evaluated.")

    _, coverage = run_with(make_client, {"upload_seeded": lambda case, ctx: CaseResult.passed("accepted"),
                                         "audit_seeded": audit_reached_only_detection})
    assert coverage["component"]["covered"] == 1
    assert coverage["system"]["covered"] == 1


def test_marking_an_undeclared_criterion_is_a_tester_error(make_client):
    def bad_mark(case, ctx):
        ctx.mark(acceptance=["AC-18"])
        return CaseResult.passed("unreachable")

    results, coverage = run_with(make_client, {"health": bad_mark})
    assert results["P3-HEALTH"]["outcome"] == "error" and results["P3-HEALTH"]["source"] == "tester"
    assert coverage["system"]["covered"] == 0


##  ---- Project calls ----

def test_project_call_sends_role_token_and_session_header(make_client, fake):
    def calls(case, ctx):
        ctx.call("GET", "/api/v1/health", role=None)
        ctx.call("GET", "/api/v1/workbooks/w/versions/v", role="userA")
        ctx.call("GET", "/api/v1/workbooks/w/versions/v", role=None, session=False)
        return CaseResult.passed("called")

    run_with(make_client, {"health": calls})
    health, version, bare = [r for r in fake.requests if r[1].startswith("/system/api/v1")]
    session_id = fake.setups()[0][3]["session_id"]
    assert health[2]["x-test-session"] == session_id and "authorization" not in health[2]
    assert version[2]["authorization"] == "Bearer tok-a" and version[2]["x-test-session"] == session_id
    assert "x-test-session" not in bare[2] and "authorization" not in bare[2]


def test_health_session_header_follows_pod_profile(make_client, fake):
    run_with(make_client, {"health": lambda case, ctx: ctx.call("GET", "/api/v1/health", role=None)
                           and CaseResult.passed("called")},
             profile_changes={"session_transport": {"send_on_health": False}})
    [health] = [r for r in fake.requests if r[1] == "/system/api/v1/health"]
    assert "x-test-session" not in health[2]


##  ---- Polling ----

def test_poll_returns_when_finished(make_client):
    states = iter(["PROCESSING", "PROCESSING", "AUDIT_COMPLETE"])

    def poll_audit(case, ctx):
        value, finished = ctx.poll(lambda: next(states), lambda s: s != "PROCESSING")
        return CaseResult.passed(value) if finished else CaseResult.failed("still processing")

    results, _ = run_with(make_client, {"health": poll_audit}, {"timing": {"poll_interval_seconds": 0.01}})
    assert results["P3-HEALTH"] == {"test_id": "P3-HEALTH", "outcome": "pass", "message": "AUDIT_COMPLETE"}


def test_poll_budget_exhaustion_is_reported_to_the_check(make_client):
    def poll_forever(case, ctx):
        value, finished = ctx.poll(lambda: "PROCESSING", lambda s: s != "PROCESSING", budget=0.2)
        return CaseResult.failed(f"Audit still {value} after the poll budget.") if not finished else None

    results, _ = run_with(make_client, {"health": poll_forever}, {"timing": {"poll_interval_seconds": 0.05}})
    assert results["P3-HEALTH"]["outcome"] == "fail"
    assert results["P3-AUTH-UPLOAD"]["outcome"] == "skip"          # later cases still run


def test_poll_past_the_suite_budget_aborts_the_run(make_client):
    def poll_forever(case, ctx):
        ctx.poll(lambda: "PROCESSING", lambda s: s != "PROCESSING")
        return CaseResult.passed("unreachable")

    client = make_client(checks={"health": poll_forever},
                         profile_changes={"timing": {"suite_seconds": 0.5, "poll_interval_seconds": 0.1}})
    session_id = setup_session(client)
    assert run(client, session_id).status_code == 500
    results = results_by_id(client.get("/test/report", params={"session_id": session_id},
                                       headers={"Authorization": "Bearer operator-token"}).json())
    assert results["P3-HEALTH"]["outcome"] == "error" and results["P3-HEALTH"]["source"] == "tester"
