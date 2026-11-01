"""The draft Phase 4 manifest run end to end against the fake target (ruleset 2.0.0).

The fake answers six-rule audits from the pack's answer key and edits outputs with the
comparator's change model, so these tests prove the tester's plumbing and its judgement of
wrong answers, not rule agreement with any real system.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tester.config import FIXTURES

from .conftest import make_settings
from .test_fixtures_and_record import run, setup

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = FIXTURES / "manifest_phase4.json"
BLOCKED = {"P3-UPLOAD-IN-CELL-PICTURE", "P3-AUDIT-IN-CELL-PICTURE", "P3-UPLOAD-IMAGE-FORMULA", "P3-AUDIT-IMAGE-FORMULA",
           "P3-UPLOAD-FORM-CONTROLS", "P3-AUDIT-FORM-CONTROLS", "P3-UPLOAD-VML-COMMENTS", "P3-AUDIT-VML-COMMENTS"}


@pytest.fixture
def phase4_client(tmp_path, fake, make_client):
    fake.project.ruleset = "2.0.0"
    fake.project.processing_polls = 1        # an audit is PROCESSING for one read, as on a real worker
    profile =json.loads((FIXTURES / "pod_profile_phase4.json").read_text(encoding="utf-8"))
    profile["timing"]["poll_interval_seconds"] = 0.01
    (tmp_path / "profile.json").write_text(json.dumps(profile), encoding="utf-8")
    settings = make_settings(tmp_path, pod_profile_path=tmp_path / "profile.json", manifest_path=MANIFEST,
                             expectations_path=FIXTURES / "phase4" / "expectations.json")
    return make_client(settings=settings)


def full_run(client):
    session_id = setup(client).json()["session_id"]
    body = run(client, session_id).json()
    return {r["test_id"]: r for r in body["results"]}, body, session_id


def test_manifest_is_generated_from_the_plan():
    result = subprocess.run([sys.executable, str(ROOT / "scripts" / "build_phase4_manifest.py"), "--check"],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    plan = json.loads((ROOT / "ref" / "Phase4_Agent_Context_Pack" / "phase4-test-plan.json").read_text(encoding="utf-8"))
    hosted = [c["test_id"] for c in plan["tests"] if c["tier"] == "hosted_http"]
    assert [c["test_id"] for c in json.loads(MANIFEST.read_text(encoding="utf-8"))["tests"]] == hosted


def test_every_case_but_the_blocked_fixtures_passes_against_a_conforming_target(phase4_client):
    by_id, body, _ = full_run(phase4_client)
    assert len(by_id) == 215
    failing = {t: r["message"] for t, r in by_id.items() if r["outcome"] != "pass" and t not in BLOCKED}
    assert failing == {}, json.dumps(failing, indent=1)[:6000]
    assert {by_id[t]["outcome"] for t in BLOCKED} == {"skip"}
    assert "pod contract 1.1" in by_id["P3-AUDIT-VML-COMMENTS"]["message"]
    assert body["coverage"]["component"]["covered"] == body["coverage"]["component"]["total"] - 1   # C9 never counts


def test_the_run_record_lists_every_extra_session(phase4_client):
    _, _, session_id = full_run(phase4_client)
    record = phase4_client.app.state.service.store.get(session_id).record
    ##  The main fault session, the failed-audit fault session, the wrong-namespace session and the
    ##  two cleanup-case sessions.
    assert len(record["fault_session_ids"]) == 5


##  ---- Against targets that get Phase 4 wrong: each must fail its own case ----

def patch(fake, name, wrapper):
    original = getattr(fake.project, name)
    setattr(fake.project, name, lambda *args, **kwargs: wrapper(original, *args, **kwargs))


def extra_finding(original, content):
    result = original(content)
    if result["status"] != "PROCESSING_FAILED" and b"Hidden tables" in content:
        result = {**result, "findings": result["findings"] + [{**result["findings"][0], "target": "xl/tables/table1.xml#tableId=1",
                                                               "worksheet": "Declared"}]}
    return result


def accepts_empty(original, subject, *args, body=b"", **kwargs):
    if json.loads(body).get("decisions") == []:
        return 202, {"remediationId": "rem-x", "sourceVersionId": args[1], "status": "REMEDIATING"}
    return original(subject, *args, body=body, **kwargs)


def lenient_reader(original, subject, *args, **kwargs):
    return original("userA" if subject == "userB" else subject, *args, **kwargs)


def reviewer_writes(original, subject, *args, **kwargs):
    return original("userA" if subject == "reviewer" else subject, *args, **kwargs)


def replays_differently(original, subject, *args, headers=None, **kwargs):
    headers = dict(headers or {})
    headers["idempotency-key"] = f"fresh-{len(original.__self__.remediations)}"
    return original(subject, *args, headers=headers, **kwargs)


def no_cleanup(original, ids):
    return None


def reviewer_gets_actions(original, subject, *args, **kwargs):
    return original("userA" if subject == "reviewer" else subject, *args, **kwargs)


def accepts_any_reaudit(original, subject, *args, body=b"", **kwargs):
    return original(subject, *args, body=b"", **kwargs)


@pytest.mark.parametrize("method, wrapper, test_id, text", [
    ("_audit_result", extra_finding, "P4-RULE-HEADER-DECLARED", "unexpected TABLE_HEADER"),
    ("remediate", accepts_empty, "P4-REJECT-EMPTY", "expected 400, received 202, accepting it"),
    ("history", lenient_reader, "P4-ACCESS-HISTORY-FOREIGN", "expected 403, received 200"),
    ("reaudit", reviewer_writes, "P4-ACCESS-REAUDIT-REVIEWER-WRITE-REFUSED", "history changed"),
    ("remediate", replays_differently, "P4-IDEMPOTENCY-REPLAY", "differed"),
    ("cleanup", no_cleanup, "P4-SESSION-CLEANUP", "so its resources remain"),
    ("review", reviewer_gets_actions, "P4-REVIEW-REVIEWER", "the reviewer is offered actions"),
    ("reaudit", accepts_any_reaudit, "P4-REAUDIT-INVALID", "expected 400, received 202"),
])
def test_each_wrong_behaviour_fails_its_case(phase4_client, fake, method, wrapper, test_id, text):
    patch(fake, method, wrapper)
    result = full_run(phase4_client)[0][test_id]
    assert result["outcome"] == "fail" and text in result["message"], result


def test_an_unapproved_output_difference_fails_preservation(phase4_client, fake, monkeypatch):
    from . import fake_phase4
    original = fake_phase4.edit_package

    def sloppy(source, changes):
        import io
        import zipfile
        output, plan = original(source, changes)
        with zipfile.ZipFile(io.BytesIO(output)) as archive:
            parts = {n: archive.read(n) for n in archive.namelist()}
        parts["xl/styles.xml"] = parts["xl/styles.xml"].replace(b'<sz val="11"/>', b'<sz val="12"/>', 1)
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            for name, data in parts.items():
                archive.writestr(name, data)
        return buffer.getvalue(), plan
    monkeypatch.setattr(fake_phase4, "edit_package", sloppy)
    by_id = full_run(phase4_client)[0]
    for test_id in ("P4-APPLY-ALT", "P4-PRESERVATION"):
        assert by_id[test_id]["outcome"] == "fail", by_id[test_id]
        assert "xl/styles.xml changed, but no approved change touches it" in by_id[test_id]["message"]


def test_a_corrected_finding_left_in_the_output_audit_fails(phase4_client, fake):
    original = fake.project._accept

    def keeps_findings(subject, version, request, session):
        response = original(subject, version, request, session)
        remediation = fake.project.remediations[response["remediationId"]]
        audit = fake.project.audits[remediation["auditId"]]
        source = fake.project.audits[request["auditId"]]["result"]["findings"]
        audit["result"] = {**audit["result"], "findings": source}
        return response
    fake.project._accept = keeps_findings
    result = full_run(phase4_client)[0]["P4-APPLY-ALT"]
    assert result["outcome"] == "fail" and "still reports the corrected ALT_TEXT" in result["message"]


def test_missing_download_headers_fail_the_source_download(phase4_client, fake):
    original = fake.project.source

    def bare(*args, **kwargs):
        status, body, headers = original(*args, **kwargs)
        return status, body, {"content-type": headers["content-type"]}
    fake.project.source = bare
    result = full_run(phase4_client)[0]["P4-SOURCE-BEFORE"]
    assert result["outcome"] == "fail" and "Cache-Control does not include no-store" in result["message"]
