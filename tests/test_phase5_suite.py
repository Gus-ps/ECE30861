"""Team 12's draft Phase 5 manifest (spec 3.0.0) against the test fake: the profile and manifest
pair, the 215 inherited cases still pass, the 142 new ones skip until built, and the Phase 5
rules that changed for inherited cases (report specificationVersion) are applied."""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from tester.config import FIXTURES
from tester.suite.plan import PlanError, load_plan

from .conftest import PHASE5_TOKENS, TARGET, TOKENS, make_settings
from .fake_phase5 import show
from .test_fixtures_and_record import run, setup

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = FIXTURES / "manifest_phase5.json"
PROFILE = FIXTURES / "pod_profile_phase5.json"
PLAN = ROOT / "ref" / "Phase5_Agent_Context_Pack" / "phase5-test-plan.json"


def manifest():
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def test_manifest_is_generated_from_the_plan():
    result = subprocess.run([sys.executable, str(ROOT / "scripts" / "build_phase5_manifest.py"), "--check"],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    hosted = [c["test_id"] for c in plan["tests"] if c["tier"] == "hosted_http"]
    built = manifest()
    assert [c["test_id"] for c in built["tests"]] == hosted and len(hosted) == 357
    assert (built["manifest_version"], built["specification_version"]) == ("3.0.0-team12-draft", "3.0.0")
    assert list(built["components"]) == [f"C{i}" for i in range(1, 13)]
    assert list(built["acceptance"]) == [f"AC-{i:02}" for i in range(1, 19)]


def test_inherited_cases_keep_the_phase4_mapping_and_new_ones_are_pending():
    phase4 = {c["test_id"]: c for c in json.loads((FIXTURES / "manifest_phase4.json").read_text(encoding="utf-8"))["tests"]}
    keys = ("check", "parameters", "prerequisites", "components", "acceptance", "operations")
    inherited = [c for c in manifest()["tests"] if c["test_id"] in phase4]
    new = [c for c in manifest()["tests"] if c["test_id"] not in phase4]
    assert len(inherited) == 215 and len(new) == 142
    assert all({k: c[k] for k in keys} == {k: phase4[c["test_id"]][k] for k in keys} for c in inherited)
    assert all(c["test_id"].startswith("P5-") for c in new)
    ##  Built families map to their check with the rest of the ID as the case plus the plan's own
    ##  inputs; only the tester self-checks are still pending.
    plan = {c["test_id"]: c for c in json.loads(PLAN.read_text(encoding="utf-8"))["tests"]}
    for case in new:
        group = case["test_id"].split("-")[1]
        if group == "TESTER":
            assert case["check"] == "phase5_pending" and case["parameters"]["family"] == group
        else:
            assert case["check"] == f"phase5_{group.lower()}"
            assert case["parameters"] == {"case": case["test_id"].removeprefix(f"P5-{group}-"),
                                          **plan[case["test_id"]]["inputs"]}


def test_the_draft_design_map_lists_every_requirement_and_only_real_hosted_cases():
    ##  Team 12's design map (draft, built from the Phase 2 specification): REQ-01 to REQ-15 plus the
    ##  23 transitions of its three state machines. Shape per the pack's TeamDesignMap schema.
    design = json.loads((FIXTURES / "design_map_team12.json").read_text(encoding="utf-8"))
    assert set(design) == {"teamId", "designVersion", "mappingUrl", "requirements"}
    assert design["mappingUrl"].startswith("https://")
    ids = [r["requirementId"] for r in design["requirements"]]
    expected = ([f"REQ-{i:02}" for i in range(1, 16)] + [f"M1-T{i}" for i in range(1, 8)]
                + [f"M2-T{i}" for i in range(1, 7)] + [f"M3-T{i}" for i in range(1, 11)])
    assert ids == expected
    hosted = {c["test_id"] for c in manifest()["tests"]}
    for requirement in design["requirements"]:
        assert set(requirement) == {"requirementId", "description", "testIds", "qualifyingAssertion"}
        assert requirement["description"].strip() and requirement["qualifyingAssertion"].strip()
        assert len(requirement["testIds"]) == len(set(requirement["testIds"]))
        assert set(requirement["testIds"]) <= hosted, requirement["requirementId"]


def test_the_phase5_profile_pairs_only_with_a_phase5_manifest():
    load_plan(MANIFEST, PROFILE, FIXTURES / "phase4" / "expectations.json")
    with pytest.raises(PlanError):
        load_plan(FIXTURES / "manifest_phase4.json", PROFILE)
    with pytest.raises(PlanError):
        load_plan(MANIFEST, FIXTURES / "pod_profile_phase4.json")


DESIGN_MAP = FIXTURES / "design_map_team12.json"


def phase5_settings(tmp_path, target_team="team12", **overrides):
    ##  Team 12's tester; TARGET belongs to target_team (team12 = an own-team run).
    profile = json.loads(PROFILE.read_text(encoding="utf-8"))
    profile["timing"]["poll_interval_seconds"] = 0.01
    (tmp_path / "profile.json").write_text(json.dumps(profile), encoding="utf-8")
    values = dict(pod_profile_path=tmp_path / "profile.json", manifest_path=MANIFEST,
                  expectations_path=FIXTURES / "expectations_phase5.json", tester_team_id="team12",
                  target_teams_json={TARGET: target_team}, design_map_path=DESIGN_MAP,
                  target_auth_map_json={TARGET: PHASE5_TOKENS})
    values.update(overrides)
    return make_settings(tmp_path, **values)


@pytest.fixture
def conforming(fake):
    fake.project.ruleset = "2.0.0"
    fake.project.specification = "3.0.0"
    fake.project.processing_polls = 1
    fake.project.phase5 = True           # session clocks and the Phase 5 routes
    return fake


@pytest.fixture
def phase5_client(tmp_path, conforming, make_client):
    return make_client(settings=phase5_settings(tmp_path))


def full_run(client):
    body = run(client, setup(client).json()["session_id"]).json()
    return {r["test_id"]: r for r in body["results"]}, body


##  Built cases that skip against the default stand-in. Never producible over HTTP: a namespace
##  held not ready, a finalized tester report on the target, and a disabled fault switch on a
##  deployment that enables faults. Timing-dependent: the default stand-in finishes audits and
##  remediations before a clock call or DELETE can see them (held running, they pass; see below).
NEVER_PRODUCIBLE = {"P5-CLOCK-NOT-READY", "P5-DELETE-RETAIN-TESTER", "P5-FAULT-REJECT-DISABLED"}
BUSY = {"P5-SCHEDULE-BUSY-AUDIT", "P5-SCHEDULE-BUSY-REMEDIATION", "P5-DELETE-ACTIVE-AUDIT",
        "P5-DELETE-ACTIVE-REMEDIATION"}
EXPECTED_SKIPS = NEVER_PRODUCIBLE | BUSY


def test_inherited_and_built_cases_pass_and_pending_ones_skip_against_a_conforming_target(phase5_client):
    by_id, body = full_run(phase5_client)
    pending = {c["test_id"] for c in manifest()["tests"] if c["check"] == "phase5_pending"}
    assert len(by_id) == 357
    failing = {t: r["message"] for t, r in by_id.items()
               if t not in pending | EXPECTED_SKIPS and r["outcome"] != "pass"}
    assert failing == {}, json.dumps(failing, indent=1)[:4000]
    assert {by_id[t]["outcome"] for t in pending | EXPECTED_SKIPS} == {"skip"}
    assert by_id["P5-TESTER-SELF-MODEL"]["message"] == \
        "Not executed: the tester self-check checks for Phase 5 are not built in this tester yet."
    assert len(pending) == 6
    coverage = body["coverage"]
    assert (coverage["component"]["total"], coverage["system"]["total"]) == (12, 18)
    ##  Skips earn nothing: exactly the components and criteria declared by executed cases count.
    executed = [c for c in manifest()["tests"] if by_id[c["test_id"]]["outcome"] in ("pass", "fail")]
    assert coverage["component"]["covered"] == len({x for c in executed for x in c["components"]}) - ("C9" in {
        x for c in executed for x in c["components"]})
    assert coverage["system"]["covered"] == len({x for c in executed for x in c["acceptance"]})
    assert coverage["model"]["total"] == 38                  # own-team run: Team 12's design map


def test_a_phase4_report_label_fails_the_report_cases_under_phase5(phase5_client, fake):
    fake.project.specification = "2.1.0"
    by_id, _ = full_run(phase5_client)
    result = by_id["P4-REPORT-COMPLETE"]
    assert result["outcome"] == "fail"
    assert "specificationVersion is 2.1.0, expected 3.0.0" in result["message"]


##  ---- WP3: own/cross-team report profiles and model coverage (spec 3.0.0 §14) ----

def design_requirements():
    return json.loads(DESIGN_MAP.read_text(encoding="utf-8"))["requirements"]


def test_an_own_team_report_counts_each_design_requirement_once_from_executed_tests(phase5_client):
    by_id, body = full_run(phase5_client)
    executed = {t for t, r in by_id.items() if r["outcome"] in ("pass", "fail")}
    ##  Independent count from the results: a requirement counts once if any mapped test executed.
    expected = sum(1 for r in design_requirements() if executed & set(r["testIds"]))
    model = body["coverage"]["model"]
    assert (model["covered"], model["total"]) == (expected, 38) and 0 < expected <= 38
    assert "Team team12 design 1.0.0: 38 requirements" in model["basis"]
    digest = __import__("hashlib").sha256(DESIGN_MAP.read_bytes()).hexdigest()
    assert digest in model["basis"] and "design_map_team12.json" in model["basis"]


def test_the_stored_own_team_report_and_record_keep_the_frozen_map(phase5_client):
    session_id = setup(phase5_client).json()["session_id"]
    body = run(phase5_client, session_id).content
    assert phase5_client.get(f"/test/report?session_id={session_id}",
                             headers={"Authorization": "Bearer operator-token"}).content == body
    record = phase5_client.app.state.service.store.get(session_id).record
    assert record["report_profile"] == {"kind": "own", "tester_team": "team12", "target_team": "team12"}
    assert record["design_map"]["design_version"] == "1.0.0" and len(record["design_evidence"]) == 38
    ##  Each requirement's evidence is exactly its mapped tests that executed (pass or fail).
    results = {r["test_id"]: r["outcome"] for r in json.loads(body)["results"]}
    for requirement in design_requirements():
        earned = [t for t in requirement["testIds"] if results.get(t) in ("pass", "fail")]
        assert sorted(record["design_evidence"][requirement["requirementId"]]) == sorted(earned)
    assert record["design_evidence"]["M3-T10"] and record["design_evidence"]["REQ-02"]


def test_a_cross_team_report_omits_the_model_key_entirely(tmp_path, conforming, make_client):
    client = make_client(settings=phase5_settings(tmp_path, target_team="team9", design_map_path=None))
    session_id = setup(client).json()["session_id"]
    raw = run(client, session_id).content
    assert b'"model"' not in raw and "model" not in json.loads(raw)["coverage"]
    record = client.app.state.service.store.get(session_id).record
    assert record["report_profile"]["kind"] == "cross" and "design_map" not in record


def test_earlier_profiles_never_report_model_coverage(tmp_path, conforming, make_client):
    settings = phase5_settings(tmp_path, manifest_path=FIXTURES / "manifest_phase4.json",
                               pod_profile_path=FIXTURES / "pod_profile_phase4.json")
    body = full_run(make_client(settings=settings))[1]
    assert set(body["coverage"]) == {"code", "component", "system"}


def write_map(tmp_path, change):
    design = json.loads(DESIGN_MAP.read_text(encoding="utf-8"))
    change(design)
    path = tmp_path / "design.json"
    path.write_text(json.dumps(design), encoding="utf-8")
    return path


@pytest.mark.parametrize("change, text", [
    (None, "DESIGN_MAP_PATH is not set"),
    (lambda d: d["requirements"].append(dict(d["requirements"][0])), "requirementId values must be unique"),
    (lambda d: d["requirements"][0]["testIds"].append("P9-NOT-A-CASE"), "does not plan: P9-NOT-A-CASE"),
    (lambda d: d.update(mappingUrl="http://example.edu/map"), "is invalid"),
    (lambda d: d.update(requirements=[]), "is invalid"),
    (lambda d: d.update(status="draft"), "is invalid"),
])
def test_an_own_team_setup_without_a_valid_map_fails_500_tester(tmp_path, conforming, make_client, change, text):
    path = None if change is None else write_map(tmp_path, change)
    client = make_client(settings=phase5_settings(tmp_path, design_map_path=path))
    response = setup(client)
    assert response.status_code == 500 and response.json()["source"] == "tester"
    assert text in response.json()["message"], response.json()["message"]
    assert conforming.sessions == set()                      # no system session was prepared


def test_classification_comes_only_from_exact_configured_targets(tmp_path):
    from pydantic import ValidationError as SettingsError
    with pytest.raises(SettingsError, match="must name the team of every approved target"):
        make_settings(tmp_path, tester_team_id="team12")
    with pytest.raises(SettingsError, match="needs TESTER_TEAM_ID"):
        make_settings(tmp_path, target_teams_json={TARGET: "team12"})


def test_a_phase5_suite_without_a_tester_team_cannot_be_set_up(tmp_path, conforming, make_client):
    client = make_client(settings=phase5_settings(tmp_path, tester_team_id=None, target_teams_json={}))
    response = setup(client)
    assert response.status_code == 500 and "TESTER_TEAM_ID is not set" in response.json()["message"]


##  ---- WP4: the new Phase 5 checks ----

def built_run(make_client, tmp_path, settings=None):
    ##  Only the new Phase 5 checks run (inherited cases skip as unimplemented): fast and focused.
    from tester.suite.checks import CHECKS
    checks = {name: check for name, check in CHECKS.items() if name.startswith("phase5_")}
    by_id, _ = full_run(make_client(checks=checks, settings=settings or phase5_settings(tmp_path)))
    return {t: r for t, r in by_id.items() if t.startswith("P5-") and not t.startswith("P5-TESTER")}


def test_busy_work_is_refused_when_held_running(tmp_path, conforming, make_client):
    conforming.project.processing_polls, conforming.project.remediation_polls = 4, 3
    by_id = built_run(make_client, tmp_path)
    for test_id in BUSY:
        assert by_id[test_id]["outcome"] == "pass", by_id[test_id]
    assert {t for t, r in by_id.items() if r["outcome"] != "pass"} == NEVER_PRODUCIBLE


def test_a_disabled_fault_switch_passes_the_disabled_case(tmp_path, conforming, make_client):
    conforming.fault_switch = False
    by_id = built_run(make_client, tmp_path)
    assert by_id["P5-FAULT-REJECT-DISABLED"]["outcome"] == "pass", by_id["P5-FAULT-REJECT-DISABLED"]
    ##  Every case that needs an armed namespace now reports why (the capability is disabled).
    assert by_id["P5-FAULT-AUDIT"]["outcome"] == "error" and "403" in by_id["P5-FAULT-AUDIT"]["message"]


def test_access_cases_needing_an_unconfigured_role_skip_and_say_which(tmp_path, conforming, make_client):
    by_id = built_run(make_client, tmp_path, phase5_settings(tmp_path, target_auth_map_json={TARGET: TOKENS}))
    needing = {t for t in by_id if t.endswith(("UNGRANTED-REVIEWER", "FOREIGN-ADMIN"))}
    assert len(needing) == 5
    for test_id in needing:
        assert by_id[test_id]["outcome"] == "skip" and "TARGET_AUTH_MAP_JSON" in by_id[test_id]["message"]
    others = {t for t, r in by_id.items() if t.startswith("P5-ACCESS") and t not in needing}
    assert {by_id[t]["outcome"] for t in others} == {"pass"}


def test_unknown_role_names_are_refused_at_startup(tmp_path):
    from pydantic import ValidationError as SettingsError
    with pytest.raises(SettingsError, match="unknown roles"):
        make_settings(tmp_path, target_auth_map_json={TARGET: {**TOKENS, "reviewer2": "tok-r2"}})


def break_rewind(project):
    original = project.clock

    def lenient(token, headers, body):
        session, wanted = headers.get("x-test-session"), json.loads(body or b"{}").get("currentTime", "")
        from .fake_phase5 import parse_timestamp
        moment = parse_timestamp(wanted)
        if moment and session in project.clocks and moment < project.clocks[session]:
            project.clocks[session] = moment                    # accepts going backward
        return original(token, headers, body)
    project.clock = lenient


def break_grid(project):
    original = project._advance

    def drifting(session, target):
        before = {w: s["nextAuditAt"] for w, s in project.schedules.items()}
        reply = original(session, target)
        for workbook, state in project.schedules.items():
            if state["nextAuditAt"] != before.get(workbook) and state["enabled"]:
                state["nextAuditAt"] = target + __import__("datetime").timedelta(days=state["intervalDays"])
        return reply
    project._advance = drifting


def break_decimal(project):
    original = project.schedule_put
    project.schedule_put = lambda *a, body=b"", **k: original(*a, body=body.replace(b"7.0", b"7"), **k)


def break_replay(project):
    original = project._advance

    def duplicating(session, target):
        replay = project.clocks.get(session) == target
        status, reply = original(session, target)
        if status == 200 and replay:
            for workbook, state in project.schedules.items():
                if state["session"] == session and state["enabled"]:
                    reply["triggeredAudits"].append(project._new_audit(project._newest(workbook, session), session,
                                                                       kind="scheduled"))
        return status, reply
    project._advance = duplicating


def break_newest(project):
    project._newest = lambda workbook, session: min(
        (v for v in project.versions.values() if v["workbookId"] == workbook and v["session"] == session),
        key=lambda v: v["sequence"])


def break_eligibility(project):
    project._eligible = lambda version: True                    # a clean audit no longer suppresses


def break_scheduled_for(project):
    original = project._advance

    def processing_time(session, target):
        known = {n["notificationId"] for n in project.notifications}
        reply = original(session, target)
        for note in project.notifications:
            if note["notificationId"] not in known:
                note["scheduledFor"] = show(target)             # the processing time, not the threshold
        return reply
    project._advance = processing_time


def break_dedup(project):
    original = project._advance

    def forgetful(session, target):
        project.considered.clear()                              # nothing is remembered as considered
        return original(session, target)
    project._advance = forgetful


def break_remediation_retained(project):
    original = project._forget_workbook

    def keeps_remediations(workbook_id):
        remediations = dict(project.remediations)
        original(workbook_id)
        project.remediations.update(remediations)               # a derived identity survives deletion
    project._forget_workbook = keeps_remediations


def break_report_message(project):
    original = project._new_audit

    def reworded(version, session, kind="ordinary"):
        audit_id = original(version, session, kind)
        error = project.audits[audit_id]["result"]["error"]
        if error and error["code"] == "TEST_REPORT_FAILURE":
            error["message"] = "Report failed."
        return audit_id
    project._new_audit = reworded


def break_fault_isolation(project):
    original = project._new_audit

    def leaky(version, session, kind="ordinary"):
        if kind == "ordinary" and project.armed and session not in project.armed:
            project.armed.discard(next(iter(project.armed)))   # another namespace's fault fires here
            project.armed.add(session)
        return original(version, session, kind)
    project._new_audit = leaky


def break_grants(project):
    project._readable = lambda subject, owner: True             # any reviewer reads any workbook


def break_clock_owner(project):
    original = project.clock

    def any_admin(token, headers, body):
        from .fake_project import ADMINS
        if token in ADMINS and headers.get("x-test-session") in project.session_admins:
            project.session_admins[headers["x-test-session"]] = ADMINS[token]
        return original(token, headers, body)
    project.clock = any_admin


def break_performance(project):
    ##  The first performance audit reports a spurious finding; the other four are correct.
    original = project._audit_result
    pack = json.loads((FIXTURES / "expectations_phase5.json").read_text(encoding="utf-8"))["fixtures"]
    digest = pack["performance_250000_cells"]["sha256"]
    calls = []

    def unstable(content):
        if hashlib.sha256(content).hexdigest() == digest and not calls:
            calls.append(1)
            entry = project.answer_key[digest]
            project.answer_key[digest] = {**entry, "findings": pack["seeded_all_six"]["findings"][:1]}
            try:
                return original(content)
            finally:
                project.answer_key[digest] = entry
        return original(content)
    project._audit_result = unstable


@pytest.mark.parametrize("breakage, test_id, text", [
    (break_rewind, "P5-CLOCK-REWIND", "a backward advance returned 200, expected 400"),
    (break_grid, "P5-SCHEDULE-COALESCE", "nextAuditAt is 2027-01-06T12:00:00Z, expected 2027-01-06T00:00:00Z"),
    (break_decimal, "P5-SCHEDULE-REJECT-DECIMAL", "was accepted"),
    (break_replay, "P5-SCHEDULE-SAME-TIME", "duplicate audit"),
    (break_newest, "P5-SCHEDULE-LATEST-UPLOAD", "dispatched a different version"),
    (break_eligibility, "P5-REMINDER-CLEAN", "latest audit is clean still got a reminder"),
    (break_scheduled_for, "P5-REMINDER-JUMP", "expected the threshold 2027-01-26T00:00:00Z"),
    (break_dedup, "P5-REMINDER-DEDUP", "issued the occurrence again"),
    (break_remediation_retained, "P5-DELETE-OLD-URLS", "remediation returned 200, expected 404"),
    (break_report_message, "P5-FAULT-REPORT", "message 'Report failed.'"),
    (break_fault_isolation, "P5-FAULT-REJECT-OTHER-SESSION", "failed an audit in another fresh namespace"),
    (break_grants, "P5-ACCESS-SCHEDULE-READ-UNGRANTED-REVIEWER", "returned 200, expected 403"),
    (break_clock_owner, "P5-ACCESS-CLOCK-FOREIGN-ADMIN", "returned 200"),
    (break_performance, "P5-PERFORMANCE-COMPARE", "different issue types or locations"),
])
def test_a_target_breaking_one_rule_fails_exactly_that_case(tmp_path, conforming, make_client, breakage, test_id, text):
    breakage(conforming.project)
    result = built_run(make_client, tmp_path)[test_id]
    assert result["outcome"] == "fail" and text in result["message"], result


def test_setup_sends_at_most_100_cleanup_ids_and_keeps_the_rest_queued(tmp_path, conforming, make_client):
    client = make_client(settings=phase5_settings(tmp_path))
    store = client.app.state.service.store
    for number in range(130):
        store.queue_cleanup(TARGET, f"old-{number:03}")
    assert setup(client).status_code == 201
    sent = conforming.setups()[-1][3]["setup"]["cleanup_session_ids"]
    assert len(sent) == 100 and len(store.pending_cleanup(TARGET)) == 30
    assert setup(client).status_code == 201
    assert len(conforming.setups()[-1][3]["setup"]["cleanup_session_ids"]) == 30 and store.pending_cleanup(TARGET) == []


##  ---- WP5: the Phase 5 fixture pack ----

def test_phase5_fixtures_are_generated_and_the_pack_extends_phase4_unchanged():
    result = subprocess.run([sys.executable, str(ROOT / "scripts" / "build_phase5_fixtures.py"), "--check"],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    pack = json.loads((FIXTURES / "expectations_phase5.json").read_text(encoding="utf-8"))
    phase4 = json.loads((FIXTURES / "phase4" / "expectations.json").read_text(encoding="utf-8"))
    for key, entry in phase4["fixtures"].items():
        assert pack["fixtures"][key] == {**entry, "file": f"phase4/{entry['file']}"}
    assert set(pack["fixtures"]) - set(phase4["fixtures"]) == {"performance_250000_cells"}
    plan = load_plan(MANIFEST, PROFILE, FIXTURES / "expectations_phase5.json")
    assert len(plan["fixtures"]["entries"]) == 35


def test_the_performance_workbook_has_exactly_250000_nonempty_cells_in_one_table():
    import io
    import re
    import zipfile
    entry = json.loads((FIXTURES / "expectations_phase5.json").read_text(encoding="utf-8"))["fixtures"][
        "performance_250000_cells"]
    data = (FIXTURES / entry["file"]).read_bytes()
    assert hashlib.sha256(data).hexdigest() == entry["sha256"] and len(data) < 25_000_000
    with zipfile.ZipFile(io.BytesIO(data)) as package:
        sheets = [n for n in package.namelist() if n.startswith("xl/worksheets/sheet")]
        sheet, table = package.read(sheets[0]), package.read("xl/tables/table1.xml")
    assert sheets == ["xl/worksheets/sheet1.xml"]
    assert len(re.findall(rb"<c\b[^>]*>\s*<(?:f|v|is)\b", sheet)) == 250_000
    assert b'ref="A1:J25000"' in table and b"<mergeCell" not in sheet and b"<hyperlink" not in sheet
    assert (entry["expected_status"], entry["findings"], entry["limitation_facts"]) == ("AUDIT_COMPLETE", [], [])


@pytest.mark.parametrize("team, has_model", [("team12", True), ("team9", False)])
def test_abort_and_recovery_reports_keep_the_profile_model_rule(tmp_path, conforming, make_client, team, has_model):
    ##  P5-LOCAL-SCHEMA-PROFILES: the abort builder and the restart-recovery builder include
    ##  coverage.model exactly when the run is own-team, like a completed run.
    import time
    from tester.suite.checks import CHECKS
    from tester.suite.runner import CaseResult
    profile = json.loads(PROFILE.read_text(encoding="utf-8"))
    profile["timing"]["suite_seconds"] = 1
    (tmp_path / "short.json").write_text(json.dumps(profile), encoding="utf-8")
    settings = phase5_settings(tmp_path, target_team=team, pod_profile_path=tmp_path / "short.json")

    def slow(case, ctx):
        time.sleep(1.2)
        ctx.deadline.check()
        return CaseResult.passed("unreachable")

    first = manifest()["tests"][0]["check"]
    client = make_client(checks={**CHECKS, first: slow}, settings=settings)
    headers = {"Authorization": "Bearer operator-token"}

    def coverage(c, session_id):
        return c.get(f"/test/report?session_id={session_id}", headers=headers).json()["coverage"]

    aborted = setup(client).json()["session_id"]
    assert run(client, aborted).status_code == 500
    interrupted = setup(client).json()["session_id"]
    store = client.app.state.service.store
    assert store.claim_run(interrupted)
    store.save_progress(interrupted, {"results": [], "components": [], "acceptance": [], "code": None, "marked": []})
    recovered = coverage(make_client(checks={**CHECKS, first: slow}, settings=settings), interrupted)
    for measured in (coverage(client, aborted), recovered):
        assert ("model" in measured) is has_model, measured
        if has_model:
            assert (measured["model"]["covered"], measured["model"]["total"]) == (0, 38)


def test_the_local_and_manual_map_lists_every_entry_once_and_names_real_tests():
    import re
    doc = (ROOT / "docs" / "phase5-local-and-manual.md").read_text(encoding="utf-8")
    for short, full in (("P4-MANUAL-EXCEL-ALT, -RENAME, -LINK, -HEADER",
                         "P4-MANUAL-EXCEL-ALT P4-MANUAL-EXCEL-RENAME P4-MANUAL-EXCEL-LINK P4-MANUAL-EXCEL-HEADER"),
                        ("P4-MANUAL-REAL-WORKBOOKS, -REAL-DETERMINISM", "P4-MANUAL-REAL-WORKBOOKS P4-MANUAL-REAL-DETERMINISM"),
                        ("P4-MANUAL-UI-REVIEW, -PROSE-REVIEW", "P4-MANUAL-UI-REVIEW P4-MANUAL-PROSE-REVIEW")):
        doc = doc.replace(short, full)
    listed = [i for row in re.findall(r"^\| (P[45]-[A-Z0-9_-]+(?: P[45]-[A-Z0-9_-]+)*)", doc, re.M) for i in row.split()]
    plan = json.loads(PLAN.read_text(encoding="utf-8"))["tests"]
    assert sorted(listed) == sorted(c["test_id"] for c in plan if c["tier"] != "hosted_http")
    ##  Every test the map cites exists: `file.py::name` (a bare `::name` refers to the file named before it).
    current = None
    for path, name in re.findall(r"`(?:tests/)?(test_\w+\.py)?::(test_\w+)`", doc):
        current = path or current
        source = (ROOT / "tests" / current).read_text(encoding="utf-8")
        assert f"def {name}(" in source, f"{current}::{name}"
