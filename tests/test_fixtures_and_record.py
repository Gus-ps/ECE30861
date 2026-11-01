"""Fixture-pack snapshot at setup and the run record kept outside SuiteReport."""

import hashlib
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from tester.config import FIXTURES
from tester.store import Store
from tester.suite.checks import CHECKS
from tester.suite.plan import PlanError, load_plan
from tester.suite.runner import CaseResult

from .conftest import TARGET, auth, make_settings

MANIFEST = FIXTURES / "manifest.json"
PROFILE = FIXTURES / "pod_profile.json"
NAMED = sorted({case["parameters"]["fixture"] for case in json.loads(MANIFEST.read_text(encoding="utf-8"))["tests"]
                if "fixture" in case.get("parameters", {})})
REPO = Path(__file__).resolve().parent.parent


REJECTED = {"corrupt", *(case["parameters"]["fixture"] for case in json.loads(MANIFEST.read_text(encoding="utf-8"))["tests"]
                         if case["check"] == "rejected_fixture")}


def make_pack(folder, **changes):
    ##  A pack covering every fixture the Phase 3 manifest names plus corrupt, with stand-in bytes
    ##  (unreadable as a package, so the fake project rejects each rejected entry with 422).
    folder.mkdir(exist_ok=True)
    (folder / "files").mkdir(exist_ok=True)
    fixtures = {}
    for key in sorted({*NAMED, "corrupt"}):
        data = f"stand-in bytes for {key}".encode()
        (folder / "files" / f"{key}.xlsx").write_bytes(data)
        fixtures[key] = {"kind": "accepted", "file": f"files/{key}.xlsx", "sha256": hashlib.sha256(data).hexdigest(),
                         "origin": "synthetic", "upload_name": f"{key}.xlsx", "expected_status": "AUDIT_COMPLETE"}
        if key in REJECTED:
            fixtures[key].update(kind="rejected", http_status=422, error_code=None)
            del fixtures[key]["expected_status"]
    pack = {"ruleset_version": "1.0.0", "fixtures": fixtures, **changes}
    (folder / "expectations.json").write_text(json.dumps(pack), encoding="utf-8")
    return folder / "expectations.json"


def setup(client):
    return client.post("/test/setup", json={"target_url": TARGET}, headers=auth())


def run(client, session_id):
    return client.post("/test/run", json={"session_id": session_id}, headers=auth())


##  ---- Snapshot at setup ----

def test_pack_is_verified_and_frozen(tmp_path):
    expectations = make_pack(tmp_path / "pack")
    plan = load_plan(MANIFEST, PROFILE, expectations)
    assert set(plan["fixtures"]["entries"]) == {*NAMED, "corrupt"}
    assert plan["fixtures"]["expectations_sha256"] == hashlib.sha256(expectations.read_bytes()).hexdigest()
    assert plan["fixtures"]["entries"]["unicode"]["expected_status"] == "AUDIT_COMPLETE"


def test_no_pack_configured_freezes_none():
    assert load_plan(MANIFEST, PROFILE)["fixtures"] is None


@pytest.mark.parametrize("change, message", [
    (lambda pack: pack.update(ruleset_version="2.0.0"), "does not match manifest ruleset"),
    (lambda pack: pack["fixtures"].pop("unicode"), "no entry for unicode"),
    (lambda pack: pack["fixtures"]["unicode"].update(file="../outside.xlsx"), "outside the fixture pack"),
    (lambda pack: pack["fixtures"]["unicode"].update(file="files/missing.xlsx"), "could not be read"),
    (lambda pack: pack["fixtures"]["unicode"].update(sha256="0" * 64), "unicode .* has SHA256"),
])
def test_unusable_pack_is_refused(tmp_path, change, message):
    expectations = make_pack(tmp_path / "pack")
    pack = json.loads(expectations.read_text(encoding="utf-8"))
    change(pack)
    expectations.write_text(json.dumps(pack), encoding="utf-8")
    with pytest.raises(PlanError, match=message):
        load_plan(MANIFEST, PROFILE, expectations)


def test_changed_fixture_is_rejected_at_setup_before_any_session(tmp_path, make_client, fake):
    pack = make_pack(tmp_path / "pack")
    client = make_client(settings=make_settings(tmp_path, expectations_path=pack))
    (tmp_path / "pack" / "files" / "unicode.xlsx").write_bytes(b"edited after startup")
    response = setup(client)
    assert response.status_code == 500
    assert response.json()["source"] == "tester"
    assert "fixture unicode" in response.json()["message"]
    assert fake.setups() == []


def test_fixture_changed_after_setup_is_a_tester_error(tmp_path, make_client):
    pack = make_pack(tmp_path / "pack")
    seen = {}

    def reads_fixture(case, ctx):
        data, entry = ctx.fixture("unicode")
        seen["bytes"], seen["upload_name"] = data, entry["upload_name"]
        (tmp_path / "pack" / "files" / "repeated_ids.xlsx").write_bytes(b"edited mid-run")
        return CaseResult.passed("read")

    def reads_changed(case, ctx):
        ctx.fixture("repeated_ids")
        return CaseResult.passed("unreachable")

    client = make_client(checks={"health": reads_fixture, "upload_without_token": reads_changed},
                         settings=make_settings(tmp_path, expectations_path=pack))
    results = {r["test_id"]: r for r in run(client, setup(client).json()["session_id"]).json()["results"]}
    assert seen == {"bytes": b"stand-in bytes for unicode", "upload_name": "unicode.xlsx"}
    assert results["P3-HEALTH"]["outcome"] == "pass"
    changed = results["P3-AUTH-UPLOAD"]
    assert changed["outcome"] == "error" and changed["source"] == "tester"
    assert "repeated_ids changed after setup" in changed["message"]


##  ---- Run record ----

def test_run_record_is_stored_with_the_report(tmp_path, make_client):
    pack = FIXTURES / "shared" / "expectations.json"
    settings = make_settings(tmp_path, expectations_path=pack, tester_revision="tester-abc123",
                             target_revisions_json={TARGET: "system-def456"})
    client = make_client(settings=settings)
    session_id = setup(client).json()["session_id"]
    body = run(client, session_id).json()
    assert client.get("/test/report", params={"session_id": session_id}, headers=auth()).status_code == 200
    assert "record" not in body and set(body) == {"session_id", "target_url", "results", "coverage"}

    store = client.app.state.service.store
    row = store.get(session_id)
    record = row.record
    assert record["state"] == "COMPLETE" and record["abort_reason"] is None
    assert record["started_at"] == row.started_at and record["ended_at"] == row.ended_at
    assert row.started_at <= row.ended_at
    assert (record["manifest_version"], record["ruleset_version"]) == ("1.4.0", "1.0.0")
    assert record["profile_version"] == "team9-defaults-1.0.0" and record["pod_approved"] is False
    assert (record["tester_revision"], record["target_revision"]) == ("tester-abc123", "system-def456")
    assert record["fixture_pack"]["fixtures"]["unicode"] == \
        hashlib.sha256((pack.parent / "unicode.xlsx").read_bytes()).hexdigest()
    assert record["counts"] == {"pass": 52, "fail": 0, "error": 0, "skip": 1, "total": 53}
    assert record["coverage"] == body["coverage"]
    assert record["component_evidence"]["C6"] == ["P3-SESSION-UNKNOWN", "P3-SESSION-DUPLICATE", "P3-CODE-REPORT"]
    assert record["acceptance_evidence"]["AC-15"] == [
        "P3-AUTH-UPLOAD", "P3-AUTH-UPLOAD-INVALID", "P3-VERSION-UNAUTHENTICATED", "P3-VERSION-FOREIGN",
        "P3-AUDIT-UNAUTHENTICATED", "P3-AUDIT-FOREIGN", "P3-VERSION-REVIEWER", "P3-AUDIT-REVIEWER"]
    assert record["operation_conformance"]["1"]["pass"] >= 1
    assert record["unresolved_discrepancies"] == []
    assert len(store.retrievals(session_id)) == 1


def test_discrepancies_and_abort_are_recorded(tmp_path, make_client):
    def wrong(case, ctx):
        ctx.mark()
        return CaseResult.failed("Expected 200; received 503.")

    client = make_client(checks={**CHECKS, "health": wrong}, settings=make_settings(tmp_path))
    session_id = setup(client).json()["session_id"]
    run(client, session_id)
    record = client.app.state.service.store.get(session_id).record
    assert record["unresolved_discrepancies"] == [
        {"test_id": "P3-HEALTH", "outcome": "fail", "message": "Expected 200; received 503."}]
    assert record["fixture_pack"] is None and record["target_revision"] is None


def test_restart_abort_gets_a_record(tmp_path, make_client):
    settings = make_settings(tmp_path)
    client = make_client(settings=settings)
    session_id = setup(client).json()["session_id"]
    store = client.app.state.service.store
    assert store.claim_run(session_id)
    restarted = make_client(settings=settings)
    record = restarted.app.state.service.store.get(session_id).record
    assert record["state"] == "ABORTED" and "restarted" in record["abort_reason"]
    assert record["counts"]["error"] == 1 and record["counts"]["total"] == 53


def test_older_store_file_gains_new_columns(tmp_path):
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE sessions (session_id TEXT PRIMARY KEY, owner TEXT NOT NULL, target_url TEXT NOT NULL, "
                   "state TEXT NOT NULL, created_at TEXT NOT NULL, plan TEXT NOT NULL, progress TEXT, report BLOB, "
                   "failure TEXT)")
        db.execute("INSERT INTO sessions VALUES ('old', 'op', ?, 'COMPLETE', 't', '{}', NULL, x'7b7d', NULL)", (TARGET,))
    store = Store(str(path))
    row = store.get("old")
    assert row.state == "COMPLETE" and row.record is None and row.started_at is None
    store.close()


def test_run_record_script_prints_record_and_retrievals(tmp_path, make_client):
    settings = make_settings(tmp_path)
    client = make_client(settings=settings)
    session_id = setup(client).json()["session_id"]
    run(client, session_id)
    client.get("/test/report", params={"session_id": session_id}, headers=auth())
    output = subprocess.run([sys.executable, str(REPO / "scripts" / "run_record.py"), "--db", settings.tester_db_path,
                             "--session", session_id], capture_output=True, text=True, encoding="utf-8", check=True)
    printed = json.loads(output.stdout)
    assert printed["session_id"] == session_id and len(printed["report_retrievals"]) == 1
