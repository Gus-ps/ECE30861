"""The test fake's Phase 5 behaviour (tests/fake_phase5.py) against shared specification 3.0.0 and
the pack's frozen policy vectors. The fake is what the WP4 checks are proven against, so it must
itself agree with the calendar oracles before any tester check relies on it."""

import json
from datetime import datetime, timedelta, timezone

import pytest

from tester.config import FIXTURES

from .fake_phase5 import parse_timestamp, show, validate_setup
from .fake_project import FakeProject
from .test_phase4_fixtures import ROOT

VECTORS = json.loads((ROOT / "ref" / "Phase5_Agent_Context_Pack" / "phase5-policy-vectors.json").read_text(encoding="utf-8"))
PACK = FIXTURES / "phase4"
CLEAN, SEEDED = (PACK / "clean_all_six.xlsx").read_bytes(), (PACK / "seeded_all_six.xlsx").read_bytes()


class Project:
    ##  A Phase 5 fake with helpers that go through handle(), so routing, auth and parsing are exercised.
    def __init__(self):
        self.fake = FakeProject(set())
        self.fake.phase5, self.fake.ruleset = True, "2.0.0"

    def prepare(self, session="s1", admin="admin-1", **setup):
        assert validate_setup(setup) is None
        self.fake.prepare(session, setup, admin)
        return session

    def call(self, method, path, token="tok-a", session="s1", body=None, raw=None):
        headers = {"authorization": f"Bearer {token}"} if token else {}
        if session:
            headers["x-test-session"] = session
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else b"")
        return self.fake.handle(method, path, headers, data)[:2]

    def upload(self, content=CLEAN, session="s1", token="tok-a"):
        body = (b'--B\r\nContent-Disposition: form-data; name="file"; filename="book.xlsx"\r\n'
                b"Content-Type: application/octet-stream\r\n\r\n" + content + b"\r\n--B--\r\n")
        status, reply = self.fake.handle("POST", "/api/v1/workbooks", {"authorization": f"Bearer {token}",
                                         "x-test-session": session, "content-type": "multipart/form-data; boundary=B"},
                                         body)[:2]
        assert status == 202, reply
        return reply

    def schedule(self, workbook_id, body, **kwargs):
        return self.call("PUT", f"/api/v1/workbooks/{workbook_id}/schedule", body=body, **kwargs)

    def clock(self, when, token="tok-admin", session="s1"):
        return self.call("POST", "/api/v1/test/clock", token=token, session=session, body={"currentTime": when})

    def notes(self, workbook_id, **kwargs):
        return self.call("GET", f"/api/v1/workbooks/{workbook_id}/notifications", **kwargs)


@pytest.fixture
def p():
    return Project()


##  ---- Clock (spec 3.0.0 §9) ----

def test_clock_starts_at_the_default_or_the_supplied_time_and_never_rewinds(p):
    p.prepare()
    p.prepare("s2", clock={"currentTime": "2027-06-01T12:30:00.5Z"})
    assert p.clock(VECTORS["clock_initial_default"]) == (200, {"currentTime": "2027-01-01T00:00:00Z",
                                                                "triggeredAudits": [], "triggeredNotifications": []})
    assert p.clock("2027-06-01T12:30:00.5Z", session="s2")[0] == 200
    assert p.clock("2026-12-31T23:59:59Z")[1]["code"] == "CLOCK_REWIND"
    for bad in ("2027-01-02T00:00:00+00:00", "2027-01-02", "2027-01-02T00:00:00.1234567Z", 5):
        assert p.clock(bad)[1]["code"] == "INVALID_REQUEST", bad
    assert p.fake.clocks["s1"] == parse_timestamp("2027-01-01T00:00:00Z")


def test_clock_access_follows_the_creating_admin_rules(p):
    p.prepare()
    when = "2027-01-02T00:00:00Z"
    assert p.clock(when, session=None)[1]["code"] == "TEST_CLOCK_DISABLED"
    assert p.clock(when, token=None)[0] == 401 and p.clock(when, token="tok-bogus")[0] == 401
    assert p.clock(when, token="tok-a")[0] == 403 and p.clock(when, token="tok-r")[0] == 403
    assert p.clock(when, token="tok-admin-2")[0] == 403          # a different test-admin
    assert p.clock(when, session="gone")[1]["code"] == "INVALID_TEST_SESSION"
    assert p.clock(when)[0] == 200
    p.fake.phase5 = False
    assert p.clock(when)[1]["code"] == "TEST_CLOCK_DISABLED"


def test_isolated_clocks_do_not_affect_each_other(p):
    p.prepare()
    p.prepare("s2")
    p.clock("2027-03-01T00:00:00Z")
    assert p.fake.clocks["s2"] == parse_timestamp(VECTORS["clock_initial_default"])


##  ---- Schedules (§6, §7) and the frozen cadence vectors ----

@pytest.mark.parametrize("vector", VECTORS["intervals"], ids=lambda v: v["name"])
def test_interval_vectors(p, vector):
    p.prepare()
    workbook = p.upload()["workbookId"]
    status, _ = p.schedule(workbook, {"enabled": vector["enabled"], "intervalDays": vector["intervalDays"]})
    assert (status == 200) == vector["valid"]


@pytest.mark.parametrize("vector", VECTORS["initial_due"])
def test_first_due_vectors(p, vector):
    p.prepare(clock={"currentTime": vector["now"]})
    workbook = p.upload()["workbookId"]
    reply = p.schedule(workbook, {"enabled": True, "intervalDays": vector["intervalDays"]})[1]
    assert reply["nextAuditAt"] == vector["expected"] and reply["reminderDays"] == [90, 30, 7]


@pytest.mark.parametrize("vector", VECTORS["cadence"], ids=lambda v: v["name"])
def test_cadence_vectors(p, vector):
    ##  Configure so the schedule is due exactly at vector.due, then advance to vector.now.
    configured = parse_timestamp(vector["due"]) - timedelta(days=vector["intervalDays"])
    p.prepare(clock={"currentTime": show(configured)})
    workbook = p.upload()["workbookId"]
    assert p.schedule(workbook, {"enabled": True, "intervalDays": vector["intervalDays"]})[1]["nextAuditAt"] == vector["due"]
    advanced = p.clock(vector["now"])[1]
    assert len(advanced["triggeredAudits"]) == vector["audits"]
    assert p.call("GET", f"/api/v1/workbooks/{workbook}/schedule")[1]["nextAuditAt"] == vector["nextAuditAt"]


def test_unconfigured_schedule_and_replacement_semantics(p):
    p.prepare()
    workbook = p.upload()["workbookId"]
    default = p.call("GET", f"/api/v1/workbooks/{workbook}/schedule")[1]
    assert (default["enabled"], default["intervalDays"], default["complianceDeadline"], default["nextAuditAt"]) == \
        (False, None, None, None)
    due = p.schedule(workbook, {"enabled": True, "intervalDays": 7, "complianceDeadline": "2027-04-26"})[1]["nextAuditAt"]
    p.clock("2027-01-03T00:00:00Z")
    assert p.schedule(workbook, {"enabled": True, "intervalDays": 7, "complianceDeadline": "2027-04-26"})[1]["nextAuditAt"] == due
    assert p.schedule(workbook, {"enabled": True, "intervalDays": 7, "complianceDeadline": "2027-05-01"})[1]["nextAuditAt"] == due
    assert p.schedule(workbook, {"enabled": True, "intervalDays": 3})[1]["nextAuditAt"] == "2027-01-06T00:00:00Z"
    off = p.schedule(workbook, {"enabled": False})[1]
    assert (off["nextAuditAt"], off["intervalDays"], off["complianceDeadline"]) == (None, None, None)


def test_dispatch_follows_the_newest_version_and_replays_add_nothing(p):
    p.prepare()
    workbook = p.upload()["workbookId"]
    p.schedule(workbook, {"enabled": True, "intervalDays": 1})
    newer = p.call("POST", f"/api/v1/workbooks/{workbook}/versions", raw=b"")  # malformed body: refused, no version
    assert newer[0] == 400
    p.clock("2027-01-01T12:00:00Z")
    status, version = p.fake.new_version("userA", workbook, body=(
        b'--B\r\nContent-Disposition: form-data; name="file"; filename="v2.xlsx"\r\n\r\n' + SEEDED + b"\r\n--B--\r\n"),
        session="s1", headers={"content-type": "multipart/form-data; boundary=B"})[:2]
    first = p.clock("2027-01-02T00:00:00Z")[1]["triggeredAudits"]
    assert len(first) == 1 and p.fake.audits[first[0]]["versionId"] == version["versionId"]
    assert p.clock("2027-01-02T00:00:00Z")[1]["triggeredAudits"] == []


def test_a_busy_due_version_refuses_the_whole_advance(p):
    p.fake.processing_polls = 10 ** 6
    p.prepare()
    workbook = p.upload()["workbookId"]
    p.schedule(workbook, {"enabled": True, "intervalDays": 1})
    assert p.clock("2027-01-03T00:00:00Z")[1]["code"] == "ACTIVE_OPERATION"
    assert show(p.fake.clocks["s1"]) == "2027-01-01T00:00:00Z"
    assert p.call("GET", f"/api/v1/workbooks/{workbook}/schedule")[1]["nextAuditAt"] == "2027-01-02T00:00:00Z"


##  ---- Reminders (§8) and their vectors ----

def deadline_workbook(p, content, deadline, now="2027-01-01T00:00:00Z"):
    p.prepare(clock={"currentTime": now})
    workbook = p.upload(content)["workbookId"]
    p.schedule(workbook, {"enabled": False, "complianceDeadline": deadline})
    return workbook


@pytest.mark.parametrize("vector", VECTORS["reminder_dates"], ids=lambda v: v["deadline"])
def test_reminder_date_vectors(p, vector):
    start = show(parse_timestamp(vector["expected"]["90"]) - timedelta(days=1))
    workbook = deadline_workbook(p, SEEDED, vector["deadline"], now=start)
    p.clock(f"{vector['deadline']}T00:00:00Z")
    notes = p.notes(workbook)[1]["notifications"]
    assert [n["scheduledFor"] for n in notes] == [vector["expected"][k] for k in ("90", "30", "7")]
    assert {n["status"] for n in notes} == {"DELIVERED"} and {n["type"] for n in notes} == {"COMPLIANCE_DEADLINE_REMINDER"}
    assert all("External workbook changes require a new upload" in n["message"] for n in notes)


@pytest.mark.parametrize("vector", VECTORS["reminder_crossing"], ids=lambda v: v["name"])
def test_reminder_crossing_vectors(p, vector):
    workbook = deadline_workbook(p, SEEDED, vector["deadline"], now=vector["configuredAt"])
    p.fake.considered |= {(workbook, vector["deadline"], o) for o in vector["alreadyConsidered"]}
    if vector["old"] != vector["configuredAt"]:
        p.fake.clocks["s1"] = parse_timestamp(vector["old"])
    ids = p.clock(vector["new"])[1]["triggeredNotifications"]
    offsets = [(parse_timestamp(f"{vector['deadline']}T00:00:00Z") - parse_timestamp(n["scheduledFor"])).days
               for n in p.notes(workbook)[1]["notifications"] if n["notificationId"] in ids]
    assert offsets == vector["expectedOffsets"]


def test_clean_workbooks_are_suppressed_and_never_emitted_later(p):
    workbook = deadline_workbook(p, CLEAN, "2027-04-26")
    p.clock("2027-01-26T00:00:00Z")
    assert p.notes(workbook)[1] == {"notifications": []}
    p.fake.clocks["s1"] = parse_timestamp("2027-01-26T00:00:00Z")
    p.clock("2027-01-27T00:00:00Z")
    assert p.notes(workbook)[1] == {"notifications": []}        # considered clean, not retroactive


def test_eligibility_vectors():
    project = FakeProject(set())
    for vector in VECTORS["reminder_eligibility"]:
        version = {"audits": []}
        if vector["latestStatus"] is not None:
            project.audits["a"] = {"polls_left": 1 if vector["latestStatus"] == "PROCESSING" else 0,
                                   "result": {"status": vector["latestStatus"],
                                              "findings": [{}] * vector["findingCount"]}}
            version["audits"] = ["a"]
        assert project._eligible(version) is vector["eligible"], vector


def test_reminder_keys_are_considered_once_and_deadline_changes_affect_only_future_ones(p):
    workbook = deadline_workbook(p, SEEDED, "2027-04-26")
    p.clock("2027-01-26T00:00:00Z")
    p.clock("2027-01-26T00:00:00Z")
    p.schedule(workbook, {"enabled": False, "complianceDeadline": "2027-04-26"})
    assert len(p.notes(workbook)[1]["notifications"]) == 1
    p.schedule(workbook, {"enabled": False, "complianceDeadline": "2027-05-26"})
    p.clock("2027-02-25T00:00:00Z")                              # 90 days before the new deadline
    p.schedule(workbook, {"enabled": False, "complianceDeadline": "2027-04-26"})
    assert [n["scheduledFor"] for n in p.notes(workbook)[1]["notifications"]] == \
        ["2027-01-26T00:00:00Z", "2027-02-25T00:00:00Z"]


##  ---- Access (§4) ----

def test_schedule_and_notification_access(p):
    p.prepare()
    workbook = p.upload()["workbookId"]
    path = f"/api/v1/workbooks/{workbook}/schedule"
    assert p.call("GET", path, token="tok-r")[0] == 200 and p.notes(workbook, token="tok-r")[0] == 200
    assert p.schedule(workbook, {"enabled": False}, token="tok-r")[0] == 403
    assert p.call("GET", path, token="tok-r2")[0] == 403 and p.call("GET", path, token="tok-b")[0] == 403
    assert p.call("GET", path, token="tok-admin")[0] == 403 and p.call("GET", path, token=None)[0] == 401
    assert p.call("GET", "/api/v1/workbooks/wb-unknown/schedule")[0] == 404
    p.prepare("s2")
    assert p.call("GET", path, session="s2")[0] == 404           # another namespace: not found


##  ---- Deletion (§10) ----

def test_owner_deletion_removes_everything_and_stops_future_work(p):
    p.prepare()
    keep = p.upload()["workbookId"]
    upload = p.upload(SEEDED)
    workbook = upload["workbookId"]
    p.schedule(workbook, {"enabled": True, "intervalDays": 1, "complianceDeadline": "2027-02-05"})
    p.clock("2027-01-02T00:00:00Z")
    base = f"/api/v1/workbooks/{workbook}"
    assert p.call("DELETE", base, token="tok-r")[0] == 403 and p.call("DELETE", base, token="tok-b")[0] == 403
    assert p.call("DELETE", base) == (204, b"")
    for path in (f"{base}/versions/{upload['versionId']}", f"{base}/history", f"{base}/schedule", f"{base}/notifications",
                 f"{base}/versions/{upload['versionId']}/audits/{upload['auditId']}"):
        assert p.call("GET", path)[0] == 404, path
    assert p.call("DELETE", base)[0] == 404
    assert p.clock("2027-03-01T00:00:00Z")[1]["triggeredAudits"] == []
    assert p.call("GET", f"/api/v1/workbooks/{keep}/history")[0] == 200


def test_deletion_waits_for_active_audits(p):
    p.fake.processing_polls = 10 ** 6
    p.prepare()
    workbook = p.upload()["workbookId"]
    assert p.call("DELETE", f"/api/v1/workbooks/{workbook}")[1]["code"] == "ACTIVE_OPERATION"


##  ---- Faults (§11) ----

@pytest.mark.parametrize("setup, status", [
    ({"faults": {}}, 400), ({"faults": {"repeat": 1}}, 400), ({"faults": {"audit_failures": True}}, 400),
    ({"faults": {"audit_failures": 1, "report_failures": 1}}, 400), ({"clock": {"currentTime": "soon"}}, 400),
    ({"clock": {"currentTime": "2027-01-01T00:00:00Z", "x": 1}}, 400), ({"other": 1}, 400),
])
def test_invalid_setups_are_refused(setup, status):
    assert validate_setup(setup)[0] == status
    assert validate_setup({"faults": {"deletion_failures": 1}}, fault_switch=False)[0] == 403
    assert validate_setup({"clock": {"currentTime": "2027-01-01T00:00:00Z"}}, clock_switch=False)[0] == 403
    assert validate_setup({"faults": {k: 1 for k in ("remediation_failures", "storage_failures")}}) is None


def test_storage_report_and_scheduled_faults_are_one_shot(p):
    p.prepare(faults={"storage_failures": 1, "scheduled_audit_failures": 1})
    status, reply = p.fake.handle("POST", "/api/v1/workbooks", {"authorization": "Bearer tok-a", "x-test-session": "s1",
                                  "content-type": "multipart/form-data; boundary=B"},
                                  b'--B\r\nContent-Disposition: form-data; name="file"; filename="b.xlsx"\r\n\r\n'
                                  + CLEAN + b"\r\n--B--\r\n")[:2]
    assert (status, reply["code"]) == (500, "TEST_STORAGE_FAILURE") and p.fake.versions == {}
    workbook = p.upload()["workbookId"]                       # consumed: the next upload works
    p.schedule(workbook, {"enabled": True, "intervalDays": 1})
    failed = p.clock("2027-01-02T00:00:00Z")[1]["triggeredAudits"][0]
    error = p.fake.audits[failed]["result"]["error"]
    assert (error["code"], error["details"]) == ("TEST_SCHEDULED_AUDIT_FAILURE", {"stage": "scheduled_audit", "testOnly": True})
    assert error["message"] == "Scheduled audit failure requested by the isolated test session."
    second = p.clock("2027-01-03T00:00:00Z")[1]["triggeredAudits"][0]
    assert p.fake.audits[second]["result"]["status"] == "AUDIT_COMPLETE"


def test_report_fault_keeps_six_checks_and_notification_fault_records_failed(p):
    p.prepare(faults={"report_failures": 1, "notification_failures": 1})
    upload = p.upload(SEEDED)
    record = p.fake.audits[upload["auditId"]]
    assert record["result"]["error"]["code"] == "TEST_REPORT_FAILURE" and len(record["checks"]) == 6
    p.schedule(upload["workbookId"], {"enabled": False, "complianceDeadline": "2027-04-26"})
    p.clock("2027-03-27T00:00:00Z")
    notes = p.notes(upload["workbookId"])[1]["notifications"]
    assert [n["status"] for n in notes] == ["FAILED", "DELIVERED"]
    assert notes[0]["message"] == "Reminder recording failed in the isolated test session."


def test_remediation_fault_fails_without_publishing_anything(p):
    p.prepare(faults={"remediation_failures": 1})
    upload = p.upload(SEEDED)
    finding = p.fake.audits[upload["auditId"]]["result"]["findings"][0]["findingId"]
    body = {"auditId": upload["auditId"], "decisions": [{"findingId": finding, "action": "DECLINE"}]}
    status, accepted = p.fake.handle(
        "POST", f"/api/v1/workbooks/{upload['workbookId']}/versions/{upload['versionId']}/remediations",
        {"authorization": "Bearer tok-a", "x-test-session": "s1", "idempotency-key": "key-0001-abcdef"},
        json.dumps(body).encode())[:2]
    assert status == 202
    result = p.call("GET", f"/api/v1/remediations/{accepted['remediationId']}")[1]
    assert (result["status"], result["outputVersionId"], result["outputId"]) == ("PROCESSING_FAILED", None, None)
    assert result["error"]["code"] == "TEST_REMEDIATION_FAILURE" and p.fake.outputs == {}
    assert len(p.call("GET", f"/api/v1/workbooks/{upload['workbookId']}/history")[1]["versions"]) == 1


def test_deletion_fault_fails_once_and_keeps_the_workbook(p):
    p.prepare(faults={"deletion_failures": 1})
    workbook = p.upload()["workbookId"]
    status, reply = p.call("DELETE", f"/api/v1/workbooks/{workbook}")
    assert (status, reply["code"]) == (500, "TEST_DELETION_FAILURE")
    assert p.call("GET", f"/api/v1/workbooks/{workbook}/history")[0] == 200
    assert p.call("DELETE", f"/api/v1/workbooks/{workbook}")[0] == 204


def test_cleanup_removes_the_clock_and_schedules(p):
    p.prepare()
    workbook = p.upload()["workbookId"]
    p.schedule(workbook, {"enabled": True, "intervalDays": 1})
    p.fake.cleanup(["s1"])
    assert "s1" not in p.fake.clocks and workbook not in p.fake.schedules
    assert p.clock("2027-01-02T00:00:00Z")[1]["code"] == "INVALID_TEST_SESSION"


##  ---- Strict request parsing (§4) ----

@pytest.mark.parametrize("raw", [
    b'{"enabled": true, "intervalDays": 1.0}', b'{"enabled": true, "intervalDays": true}',
    b'{"enabled": true, "enabled": false, "intervalDays": 1}', b'{"enabled": false, "extra": 1}',
    b'{"enabled": false, "complianceDeadline": "2027-02-30"}', b'{"enabled": false, "complianceDeadline": "27-1-1"}',
    b'{"intervalDays": 1}', b'{"enabled": true}', b'{"enabled": true, "intervalDays": NaN}', b"[]",
])
def test_schedule_requests_are_parsed_strictly(p, raw):
    p.prepare()
    workbook = p.upload()["workbookId"]
    before = p.call("GET", f"/api/v1/workbooks/{workbook}/schedule")[1]
    status, reply = p.call("PUT", f"/api/v1/workbooks/{workbook}/schedule", raw=raw)
    assert (status, reply["code"]) == (400, "INVALID_REQUEST")
    assert p.call("GET", f"/api/v1/workbooks/{workbook}/schedule")[1] == before
