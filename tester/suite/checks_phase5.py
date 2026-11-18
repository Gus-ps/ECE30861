"""Phase 5 check functions (shared specification 3.0.0), keyed by the manifest's `check` name.

Built so far: the test clock (P5-CLOCK-*, §9) and schedules (P5-SCHEDULE-*, §6-§7). Each case
that moves time prepares its own fresh namespace through ordinary system setup (§13), so one
case's clock never shifts another's. Expected times come from the tester's own UTC arithmetic,
never from the target; instants are compared parsed, since a timestamp may carry up to six
fractional digits. Cases whose family is not built yet map to phase5_pending and skip with that
reason: spec §18 treats an unbuilt check as an explicit skip and an outstanding task.
"""

import time
from datetime import date, datetime, timedelta, timezone

from pydantic import ValidationError

from ..models import ClockResponse, NotificationResponse, ProjectError, ScheduleResponse, UploadResponse
from .checks import (WORKBOOKS, _audit_path, _audit_problems, _fault_setup_call, _finished_audit,
                     _processing_failure, _refused_setup_problems, _schema_problem, _source_problems, _system_failure,
                     _verdict, _version_path)
from .checks_phase4 import _audited, _decision_spec, _decisions, _history, _poll_remediation, _submit
from .runner import CaseResult

CLOCK = "/api/v1/test/clock"
EPOCH = "2027-01-01T00:00:00Z"            # spec §9: a fresh namespace's default effective time
DAY = timedelta(days=1)
FAMILIES = {"SCHEDULE": "schedule", "REMINDER": "deadline reminder", "CLOCK": "test clock", "DELETE": "deletion",
            "FAULT": "controlled failure", "ACCESS": "access", "PERFORMANCE": "performance",
            "TESTER": "tester self-check"}


def phase5_pending(case, ctx):
    family = case.parameters.get("family", "")
    what = FAMILIES.get(family, family.lower() or "Phase 5")
    return CaseResult("skip", f"Not executed: the {what} checks for Phase 5 are not built in this tester yet.")


##  ---- Time (the tester's own UTC arithmetic) ----

def _ts(text):
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)


def _show(moment):
    text = moment.strftime("%Y-%m-%dT%H:%M:%S")
    return text + (f".{moment.microsecond:06d}" if moment.microsecond else "") + "Z"


def _same(text, moment):
    return text is not None and _ts(text) == moment


##  ---- Namespaces, clock and schedule calls ----

class Stop(Exception):
    ##  Ends a case early with the result to report (a preparation problem or an evaluated failure).
    def __init__(self, result):
        super().__init__(result.message)
        self.result = result


def _namespace(ctx, clock=None, faults=None):
    ##  A fresh prepared namespace with its own clock (spec §9, §13); queued for cleanup after the run.
    setup = {}
    if clock:
        setup["clock"] = {"currentTime": clock}
    if faults:
        setup["faults"] = faults
    session_id, response = _fault_setup_call(ctx, setup)
    if response.status != 201:
        raise Stop(CaseResult.error("system", f"A fresh Phase 5 namespace could not be prepared: system setup "
                                              f"returned {response.status}."))
    return session_id


def _advance(ctx, session, when, role="test-admin", **kwargs):
    return ctx.call("POST", CLOCK, role=role, session=session, json_body={"currentTime": when}, **kwargs)


def _clock(ctx, session, when, what="The clock advance"):
    ##  A ClockResponse for a clock call the case relies on succeeding.
    response = _advance(ctx, session, when)
    if response.status >= 500:
        raise Stop(_system_failure(what, response))
    if response.status != 200:
        raise Stop(CaseResult.failed(f"{what} to {when} returned {response.status}, expected 200."))
    try:
        return ClockResponse.model_validate(response.json())
    except ValidationError as problem:
        raise Stop(CaseResult.failed(f"{what} body does not match ClockResponse ({_schema_problem(problem)}).")) from None


def _rejection(response, status, code, what):
    ##  Problems with an expected ProjectError rejection (empty when it conforms).
    if response.status != status:
        return [f"{what} returned {response.status}, expected {status}"]
    try:
        error = ProjectError.model_validate(response.json())
    except (ValidationError, ValueError):
        return [f"{what}: the {status} body is not a ProjectError"]
    return [] if code is None or error.code == code else [f"{what}: code {error.code}, expected {code}"]


def _workbook(ctx, session, key="clean_all_six"):
    ##  A fresh workbook for this case, uploaded and audited in its namespace.
    record, result = _audited(ctx, key, ctx.case.test_id, session)
    if result:
        raise Stop(result)
    return record


def _schedule_path(upload):
    return f"{WORKBOOKS}/{upload['workbookId']}/schedule"


def _put(ctx, upload, body, session, role="userA", raw=None):
    return ctx.call("PUT", _schedule_path(upload), role=role, session=session,
                    **({"raw_json": raw} if raw is not None else {"json_body": body}))


def _schedule(ctx, upload, session, body=None, what="The schedule"):
    ##  A ScheduleResponse from a PUT (body) or GET (no body) the case relies on succeeding.
    response = _put(ctx, upload, body, session) if body is not None else \
        ctx.call("GET", _schedule_path(upload), role="userA", session=session)
    verb = "PUT" if body is not None else "GET"
    if response.status >= 500:
        raise Stop(_system_failure(f"{what} {verb}", response))
    if response.status != 200:
        raise Stop(CaseResult.failed(f"{what} {verb} returned {response.status}, expected 200."))
    try:
        schedule = ScheduleResponse.model_validate(response.json())
    except ValidationError as problem:
        raise Stop(CaseResult.failed(f"{what} {verb} body does not match ScheduleResponse "
                                     f"({_schema_problem(problem)}).")) from None
    if schedule.workbookId != upload["workbookId"]:
        raise Stop(CaseResult.failed(f"{what} {verb} names workbook {schedule.workbookId}, not {upload['workbookId']}."))
    return schedule


def _audit_count(ctx, upload, session):
    history, problem = _history(ctx, upload["workbookId"], session)
    if problem:
        raise Stop(CaseResult.failed(f"The history needed to count audits failed: {problem}."))
    return len(history["audits"])


def _scheduled_audit(ctx, upload, version_id, audit_id, session, what):
    ##  The finished AuditResponse of a scheduled audit expected on version_id. An audit that is
    ##  not found under that version ran on a different one: say so instead of reporting a bare 404.
    located = {**upload, "versionId": version_id, "auditId": audit_id}
    if ctx.call("GET", _audit_path(located), role="userA", session=session).status == 404:
        raise Stop(CaseResult.failed(f"{what}: triggered audit {audit_id} is not on version {version_id} "
                                     f"(not found under it), so the schedule dispatched a different version."))
    audit, result = _finished_audit(ctx, located, what, session=session, mark=False)
    if result:
        raise Stop(result)
    return audit


def _run(case, ctx, cases):
    try:
        return cases[case.parameters["case"]](case, ctx)
    except Stop as stop:
        return stop.result


##  ---- P5-CLOCK-* (spec §9) ----

def _clock_at(ctx, session, moment, label):
    ##  Problems if the namespace's effective time is not exactly `moment`: a microsecond earlier
    ##  is a rewind (400) and `moment` itself is an allowed equal-time call (200, nothing due).
    problems = _rejection(_advance(ctx, session, _show(moment - timedelta(microseconds=1))), 400, "CLOCK_REWIND",
                          f"{label}: advancing to just before {_show(moment)}")
    response = _advance(ctx, session, _show(moment))
    if response.status != 200:
        return problems + [f"{label}: an equal-time advance to {_show(moment)} returned {response.status}"]
    body = ClockResponse.model_validate(response.json())
    if not _same(body.currentTime, moment):
        problems.append(f"{label}: the clock reports {body.currentTime}, expected {_show(moment)}")
    return problems


def _clock_default(case, ctx):
    session = _namespace(ctx)
    ctx.mark()
    return _verdict("Default clock", _clock_at(ctx, session, _ts(EPOCH), "an empty setup"),
                    f"A fresh namespace prepared with empty setup starts at {EPOCH}.")


def _clock_custom(case, ctx):
    start = "2027-06-01T12:00:00Z"
    session = _namespace(ctx, clock=start)
    ctx.mark()
    return _verdict("Custom clock", _clock_at(ctx, session, _ts(start), "setup.clock"),
                    f"A fresh namespace prepared with setup.clock starts at {start}.")


def _clock_rewind(case, ctx):
    session = _namespace(ctx)
    later = _ts(EPOCH) + DAY
    _clock(ctx, session, _show(later))
    ctx.mark()
    problems = _rejection(_advance(ctx, session, EPOCH), 400, "CLOCK_REWIND", "a backward advance")
    problems += _clock_at(ctx, session, later, "after the refused rewind")
    return _verdict("Clock rewind", problems, "A backward advance was 400 CLOCK_REWIND and left the time unchanged.")


def _clock_same(case, ctx):
    session = _namespace(ctx)
    upload = _workbook(ctx, session)["upload"]
    due = _ts(EPOCH) + DAY
    _schedule(ctx, upload, session, {"enabled": True, "intervalDays": 1})
    first = _clock(ctx, session, _show(due))
    count = _audit_count(ctx, upload, session)
    ctx.mark()
    replay = _clock(ctx, session, _show(due), "The repeated clock advance")
    problems = [] if len(first.triggeredAudits) == 1 else [f"the due advance triggered {len(first.triggeredAudits)} audits"]
    if replay.triggeredAudits or replay.triggeredNotifications:
        problems.append("repeating the same timestamp triggered work again")
    if _audit_count(ctx, upload, session) != count:
        problems.append("repeating the same timestamp added an audit")
    return _verdict("Same-time clock", problems, "Repeating a timestamp returned empty arrays and added nothing.")


def _clock_utc(case, ctx):
    session = _namespace(ctx)
    ctx.mark()
    problems = []
    for bad in ("2027-01-02T00:00:00+00:00", "2027-01-02T00:00:00", "2027-01-02", "2027-01-02T00:00:00.1234567Z",
                "tomorrow"):
        problems += _rejection(_advance(ctx, session, bad), 400, None, f"timestamp {bad!r}")
    problems += _clock_at(ctx, session, _ts(EPOCH), "after the refused timestamps")
    return _verdict("Clock timestamp format", problems, "Non-Z and malformed timestamps were refused with 400 and "
                                                         "left the time unchanged.")


def _clock_isolation(case, ctx):
    first, second = _namespace(ctx), _namespace(ctx)
    _clock(ctx, first, _show(_ts(EPOCH) + 10 * DAY))
    ctx.mark()
    return _verdict("Clock isolation", _clock_at(ctx, second, _ts(EPOCH), "the other namespace"),
                    "Advancing one namespace's clock left another fresh namespace at its own time.")


def _clock_owner(case, ctx):
    session = _namespace(ctx)
    body = _clock(ctx, session, _show(_ts(EPOCH) + DAY), "The creating test-admin's clock advance")
    ctx.mark()
    problems = [] if _same(body.currentTime, _ts(EPOCH) + DAY) else [f"the clock reports {body.currentTime}"]
    return _verdict("Clock owner", problems, "The creating test-admin advanced its own ready namespace (200).")


def _clock_disabled(case, ctx):
    response = _advance(ctx, False, _show(_ts(EPOCH) + DAY))
    if response.status >= 500:
        return _system_failure("The clock call without a namespace", response)
    ctx.mark()
    return _verdict("Clock without a namespace", _rejection(response, 404, "TEST_CLOCK_DISABLED", "the clock call"),
                    "A clock call without X-Test-Session was 404 TEST_CLOCK_DISABLED.")


def _clock_cleaned(case, ctx):
    response = _advance(ctx, f"unknown-{ctx.new_idempotency_key()[7:23]}", _show(_ts(EPOCH) + DAY))
    if response.status >= 500:
        return _system_failure("The clock call on an unknown namespace", response)
    ctx.mark()
    return _verdict("Clock on an unknown namespace", _rejection(response, 400, "INVALID_TEST_SESSION", "the clock call"),
                    "A clock call naming an unknown namespace was 400 INVALID_TEST_SESSION.")


def _clock_not_ready(case, ctx):
    return CaseResult("skip", "Not executed: no hosted request can hold a namespace in a not-ready state (a refused "
                              "setup leaves no session at all), so the 409 SESSION_NOT_READY condition cannot be produced.")


CLOCK_CASES = {"DEFAULT": _clock_default, "CUSTOM": _clock_custom, "REWIND": _clock_rewind, "SAME": _clock_same,
               "UTC": _clock_utc, "ISOLATION": _clock_isolation, "OWNER": _clock_owner, "DISABLED": _clock_disabled,
               "CLEANED": _clock_cleaned, "NOT-READY": _clock_not_ready}


def phase5_clock(case, ctx):
    return _run(case, ctx, CLOCK_CASES)


##  ---- P5-SCHEDULE-* (spec §6, §7) ----

def _expect_due(schedule, moment, label):
    if not _same(schedule.nextAuditAt, moment):
        return [f"{label}: nextAuditAt is {schedule.nextAuditAt}, expected {_show(moment)}"]
    return []


def _schedule_default(case, ctx):
    upload = _workbook(ctx, True)["upload"]
    first = _schedule(ctx, upload, True, what="The unconfigured schedule")
    second = _schedule(ctx, upload, True, what="The repeated unconfigured schedule")
    ctx.mark()
    problems = []
    if (first.enabled, first.intervalDays, first.complianceDeadline, first.nextAuditAt) != (False, None, None, None):
        problems.append(f"the unconfigured policy is {first.model_dump()}")
    if first.versionId != upload["versionId"]:
        problems.append(f"versionId is {first.versionId}, not the uploaded {upload['versionId']}")
    if second != first:
        problems.append("a second read differs, so reading created or changed something")
    return _verdict("Unconfigured schedule", problems, "GET returned the disabled null policy with the latest version "
                                                       "and fixed reminderDays, and created nothing.")


def _first_due(ctx, start, interval, label):
    session = _namespace(ctx, clock=start)
    upload = _workbook(ctx, session)["upload"]
    schedule = _schedule(ctx, upload, session, {"enabled": True, "intervalDays": interval})
    ctx.mark()
    return _expect_due(schedule, _ts(start) + interval * DAY, label)


def _schedule_min(case, ctx):
    return _verdict("Interval 1", _first_due(ctx, EPOCH, 1, "interval 1"),
                    "Enabling interval 1 set nextAuditAt to the effective time plus one day.")


def _schedule_max(case, ctx):
    problems = _first_due(ctx, EPOCH, 90, "interval 90") + _first_due(ctx, "2028-01-01T00:00:00Z", 90,
                                                                      "interval 90 across 29 February 2028")
    return _verdict("Interval 90", problems, "Enabling interval 90 set nextAuditAt 90 UTC days ahead, "
                                             "including across a leap day.")


def _schedule_put_replay(case, ctx):
    session = _namespace(ctx)
    upload = _workbook(ctx, session)["upload"]
    body = {"enabled": True, "intervalDays": 3, "complianceDeadline": "2027-04-26"}
    _schedule(ctx, upload, session, body)
    _clock(ctx, session, _show(_ts(EPOCH) + DAY / 4))
    count = _audit_count(ctx, upload, session)
    replay = _schedule(ctx, upload, session, body, "The replayed schedule")
    ctx.mark()
    problems = _expect_due(replay, _ts(EPOCH) + 3 * DAY, "after the identical PUT")
    if _audit_count(ctx, upload, session) != count:
        problems.append("the replayed PUT created an audit")
    return _verdict("Schedule replay", problems, "An identical PUT kept the due time and created no work.")


def _schedule_deadline_only(case, ctx):
    session = _namespace(ctx)
    upload = _workbook(ctx, session)["upload"]
    _schedule(ctx, upload, session, {"enabled": True, "intervalDays": 7, "complianceDeadline": "2027-04-26"})
    _clock(ctx, session, _show(_ts(EPOCH) + DAY))
    changed = _schedule(ctx, upload, session, {"enabled": True, "intervalDays": 7, "complianceDeadline": "2027-05-26"})
    read = _schedule(ctx, upload, session)
    ctx.mark()
    problems = _expect_due(changed, _ts(EPOCH) + 7 * DAY, "after a deadline-only change")
    if read.complianceDeadline != "2027-05-26":
        problems.append(f"the stored deadline is {read.complianceDeadline}, expected 2027-05-26")
    return _verdict("Deadline-only change", problems, "Changing only the deadline kept the periodic due time.")


def _schedule_interval_change(case, ctx):
    session = _namespace(ctx)
    upload = _workbook(ctx, session)["upload"]
    _schedule(ctx, upload, session, {"enabled": True, "intervalDays": 7})
    moved = _ts(EPOCH) + DAY
    _clock(ctx, session, _show(moved))
    changed = _schedule(ctx, upload, session, {"enabled": True, "intervalDays": 3})
    ctx.mark()
    return _verdict("Interval change", _expect_due(changed, moved + 3 * DAY, "after the interval change"),
                    "Changing the interval restarted the cadence from the current effective time.")


def _schedule_disable(case, ctx):
    session = _namespace(ctx)
    upload = _workbook(ctx, session)["upload"]
    _schedule(ctx, upload, session, {"enabled": True, "intervalDays": 1})
    disabled = _schedule(ctx, upload, session, {"enabled": False})
    count = _audit_count(ctx, upload, session)
    advanced = _clock(ctx, session, _show(_ts(EPOCH) + 3 * DAY))
    ctx.mark()
    problems = [] if disabled.nextAuditAt is None else ["a disabled schedule still has a nextAuditAt"]
    if advanced.triggeredAudits or _audit_count(ctx, upload, session) != count:
        problems.append("a disabled schedule still dispatched an audit")
    return _verdict("Disabled schedule", problems, "Disabling cancelled future periodic audits and kept history.")


def _schedule_reenable(case, ctx):
    session = _namespace(ctx)
    upload = _workbook(ctx, session)["upload"]
    _schedule(ctx, upload, session, {"enabled": True, "intervalDays": 1})
    _schedule(ctx, upload, session, {"enabled": False})
    moved = _ts(EPOCH) + 5 * DAY
    _clock(ctx, session, _show(moved))
    again = _schedule(ctx, upload, session, {"enabled": True, "intervalDays": 1})
    ctx.mark()
    return _verdict("Re-enabled schedule", _expect_due(again, moved + DAY, "after re-enabling"),
                    "Re-enabling started the cadence from the re-enable time.")


def _due_namespace(ctx, faults=None, key="clean_all_six"):
    ##  A namespace with one workbook scheduled every day from EPOCH; (session, record, due).
    session = _namespace(ctx, faults=faults)
    record = _workbook(ctx, session, key)
    _schedule(ctx, record["upload"], session, {"enabled": True, "intervalDays": 1})
    return session, record, _ts(EPOCH) + DAY


def _schedule_before_due(case, ctx):
    session, record, due = _due_namespace(ctx)
    advanced = _clock(ctx, session, _show(due - timedelta(microseconds=1)))
    ctx.mark()
    problems = [f"{len(advanced.triggeredAudits)} audits were triggered before the due time"] if advanced.triggeredAudits else []
    return _verdict("Before due", problems, "Advancing to one microsecond before the due time triggered no audit.")


def _schedule_exact_due(case, ctx):
    session, record, due = _due_namespace(ctx)
    upload = record["upload"]
    advanced = _clock(ctx, session, _show(due))
    ctx.mark()
    if len(advanced.triggeredAudits) != 1:
        return CaseResult.failed(f"Advancing to the due time triggered {len(advanced.triggeredAudits)} audits, expected 1.")
    audit = _scheduled_audit(ctx, upload, upload["versionId"], advanced.triggeredAudits[0], session, "The scheduled audit")
    problems = [] if audit.rulesetVersion == ctx.manifest.ruleset_version else [f"ruleset {audit.rulesetVersion}"]
    if audit.status == "PROCESSING_FAILED":
        problems.append(f"the scheduled audit failed ({audit.error.code if audit.error else 'no error body'})")
    problems += _source_problems(ctx, upload, record["bytes"], session)
    return _verdict("Exact due", problems, "At the due time exactly one fresh audit ran on the existing version with "
                                           "the installed ruleset, and the source bytes were unchanged.")


def _schedule_coalesce(case, ctx):
    session, record, due = _due_namespace(ctx)
    advanced = _clock(ctx, session, _show(due + 3 * DAY + DAY / 2))
    after = _schedule(ctx, record["upload"], session)
    ctx.mark()
    problems = [] if len(advanced.triggeredAudits) == 1 else [f"a multi-interval jump triggered "
                                                              f"{len(advanced.triggeredAudits)} audits, expected 1"]
    problems += _expect_due(after, due + 4 * DAY, "after the jump (original grid)")
    return _verdict("Coalesced intervals", problems, "Several missed intervals produced one audit and the next due "
                                                     "time stayed on the original grid.")


def _schedule_same_time(case, ctx):
    session, record, due = _due_namespace(ctx)
    first = _clock(ctx, session, _show(due))
    count = _audit_count(ctx, record["upload"], session)
    replay = _clock(ctx, session, _show(due), "The replayed clock advance")
    ctx.mark()
    problems = [] if len(first.triggeredAudits) == 1 else [f"the due advance triggered {len(first.triggeredAudits)} audits"]
    if replay.triggeredAudits or _audit_count(ctx, record["upload"], session) != count:
        problems.append("replaying the committed timestamp dispatched a duplicate audit")
    return _verdict("Same-time replay", problems, "Replaying the clock timestamp returned no IDs and added no audit.")


def _new_version(ctx, upload, session, key="clean_all_six"):
    response = ctx.upload(f"{WORKBOOKS}/{upload['workbookId']}/versions", role="userA", fixture=key, session=session)
    if response.status != 202:
        raise Stop(CaseResult.failed(f"The new-version upload returned {response.status}, expected 202."))
    newer = UploadResponse.model_validate(response.json()).model_dump()
    _finished_audit(ctx, newer, "The new version's audit", session=session, mark=False)
    return newer


def _schedule_latest_upload(case, ctx):
    session, record, due = _due_namespace(ctx)
    upload = record["upload"]
    _clock(ctx, session, _show(due - DAY / 2))
    newer = _new_version(ctx, upload, session)
    before = _schedule(ctx, upload, session)
    advanced = _clock(ctx, session, _show(due))
    ctx.mark()
    problems = _expect_due(before, due, "after the new upload (not postponed)")
    if before.versionId != newer["versionId"]:
        problems.append(f"the schedule follows {before.versionId}, not the newest {newer['versionId']}")
    if len(advanced.triggeredAudits) != 1:
        problems.append(f"the due advance triggered {len(advanced.triggeredAudits)} audits")
    else:
        _scheduled_audit(ctx, upload, newer["versionId"], advanced.triggeredAudits[0], session,
                         "The scheduled audit of the newest version")
    return _verdict("Newest upload", problems, "The schedule followed the newest uploaded version without postponing "
                                               "the due time, and the scheduled audit ran on it.")


def _remediate(ctx, record, session):
    ##  (accepted remediation body, None) after submitting the fixture's corrections.
    decisions, problems = _decisions(record, _decision_spec(record["entry"], "corrections"))
    if problems or not decisions:
        raise Stop(CaseResult.error("tester", f"The {record['key']} corrections could not be built: {problems}."))
    response = _submit(ctx, record, decisions, session=session)
    if response.status != 202:
        raise Stop(CaseResult.failed(f"The remediation request returned {response.status}, expected 202."))
    return response.json()


def _schedule_latest_output(case, ctx):
    session, record, due = _due_namespace(ctx, key="seeded_all_six")
    upload = record["upload"]
    _clock(ctx, session, _show(due - DAY / 2))
    accepted = _remediate(ctx, record, session)
    response, finished = _poll_remediation(ctx, accepted["remediationId"], session)
    result = response.json() if response.status == 200 else {}
    if not finished or result.get("status") != "REMEDIATED":
        return CaseResult.failed(f"The remediation did not finish as REMEDIATED ({result.get('status')}).")
    output = result["outputVersionId"]
    before = _schedule(ctx, upload, session)
    advanced = _clock(ctx, session, _show(due))
    ctx.mark()
    problems = _expect_due(before, due, "after publishing the output (not postponed)")
    if before.versionId != output:
        problems.append(f"the schedule follows {before.versionId}, not the generated {output}")
    if len(advanced.triggeredAudits) != 1:
        problems.append(f"the due advance triggered {len(advanced.triggeredAudits)} audits")
    else:
        _scheduled_audit(ctx, upload, output, advanced.triggeredAudits[0], session, "The scheduled audit of the output")
    version = ctx.call("GET", f"{WORKBOOKS}/{upload['workbookId']}/versions/{output}", role="userA", session=session)
    if version.status != 200 or version.json().get("sourceVersionId") != upload["versionId"]:
        problems.append("the generated version no longer records its source version")
    return _verdict("Newest output", problems, "The schedule followed the generated version without postponing the "
                                               "due time and kept its provenance.")


def _schedule_old_reaudit(case, ctx):
    session, record, due = _due_namespace(ctx)
    upload = record["upload"]
    newer = _new_version(ctx, upload, session)
    response = ctx.call("POST", f"{_version_path(upload)}/audits", role="userA", session=session, json_body={})
    if response.status != 202:
        return CaseResult.failed(f"The manual re-audit of the older version returned {response.status}, expected 202.")
    _finished_audit(ctx, {**upload, "auditId": response.json()["auditId"]}, "The older version's re-audit",
                    session=session, mark=False)
    advanced = _clock(ctx, session, _show(due))
    ctx.mark()
    if len(advanced.triggeredAudits) != 1:
        return CaseResult.failed(f"The due advance triggered {len(advanced.triggeredAudits)} audits, expected 1.")
    _scheduled_audit(ctx, upload, newer["versionId"], advanced.triggeredAudits[0], session,
                     "The scheduled audit of the newest version")
    return CaseResult.passed("Re-auditing an older version did not change the schedule's newest-version selection.")


def _busy(ctx, session, upload, due, kind, read_state, finish):
    ##  Spec §9: a due version with active work refuses the whole advance (409, nothing changes);
    ##  after the work finishes the identical advance succeeds. Skips if the work finished too fast.
    if read_state() is False:
        return CaseResult("skip", f"Not executed: the {kind} finished before the clock request, so the busy "
                                  f"condition could not be produced.")
    response = _advance(ctx, session, _show(due))
    if response.status == 200:
        return CaseResult("skip", f"Not executed: the {kind} finished before the clock request arrived, so the "
                                  f"busy condition could not be produced.")
    ctx.mark()
    problems = _rejection(response, 409, "ACTIVE_OPERATION", f"the advance during an active {kind}")
    after = _schedule(ctx, upload, session)
    problems += _expect_due(after, due, "after the refused advance")
    problems += _clock_at(ctx, session, _ts(EPOCH), "after the refused advance")
    finish()
    retried = _clock(ctx, session, _show(due), "The retried clock advance")
    if len(retried.triggeredAudits) != 1:
        problems.append(f"the retried advance triggered {len(retried.triggeredAudits)} audits, expected 1")
    return _verdict(f"Busy {kind}", problems, f"A due version with an active {kind} refused the advance with 409 and "
                                              f"changed nothing; the identical retry succeeded after it finished.")


def _schedule_busy_audit(case, ctx):
    session, record, due = _due_namespace(ctx)
    upload = record["upload"]
    response = ctx.call("POST", f"{_version_path(upload)}/audits", role="userA", session=session, json_body={})
    if response.status != 202:
        return CaseResult.failed(f"The manual re-audit returned {response.status}, expected 202.")
    running = {**upload, "auditId": response.json()["auditId"]}

    def processing():
        state = ctx.call("GET", _audit_path(running), role="userA", session=session)
        return state.status == 200 and state.json().get("status") == "PROCESSING"
    return _busy(ctx, session, upload, due, "audit", processing,
                 lambda: _finished_audit(ctx, running, "The running audit", session=session, mark=False))


def _schedule_busy_remediation(case, ctx):
    session, record, due = _due_namespace(ctx, key="seeded_all_six")
    accepted = _remediate(ctx, record, session)

    def remediating():
        state = ctx.call("GET", f"/api/v1/remediations/{accepted['remediationId']}", role="userA", session=session)
        return state.status == 200 and state.json().get("status") == "REMEDIATING"
    return _busy(ctx, session, record["upload"], due, "remediation", remediating,
                 lambda: _poll_remediation(ctx, accepted["remediationId"], session))


def _schedule_two_workbooks(case, ctx):
    session = _namespace(ctx)
    mine = _workbook(ctx, session)["upload"]
    response = ctx.upload(WORKBOOKS, role="userB", fixture="clean_all_six", session=session)
    if response.status != 202:
        return CaseResult.failed(f"User B's upload returned {response.status}, expected 202.")
    theirs = UploadResponse.model_validate(response.json()).model_dump()
    ##  Finish user B's upload audit first (read as its owner), or the due advance is rightly refused as busy.
    ctx.poll(lambda: ctx.call("GET", _audit_path(theirs), role="userB", session=session),
             lambda r: not (r.status == 200 and r.json().get("status") == "PROCESSING"))
    _schedule(ctx, mine, session, {"enabled": True, "intervalDays": 1})
    put = _put(ctx, theirs, {"enabled": True, "intervalDays": 1}, session, role="userB")
    if put.status != 200:
        return CaseResult.failed(f"User B's schedule PUT returned {put.status}, expected 200.")
    advanced = _clock(ctx, session, _show(_ts(EPOCH) + DAY))
    ctx.mark()
    if len(advanced.triggeredAudits) != 2:
        return CaseResult.failed(f"One advance triggered {len(advanced.triggeredAudits)} audits, expected 2.")
    ##  Equal due times dispatch in workbookId order (spec §9); each audit belongs to its own workbook.
    order = sorted([mine, theirs], key=lambda u: u["workbookId"])
    problems = []
    for upload, audit_id in zip(order, advanced.triggeredAudits):
        role = "userA" if upload is mine else "userB"
        read = ctx.call("GET", _audit_path({**upload, "auditId": audit_id}), role=role, session=session)
        if read.status != 200:
            problems.append(f"triggered audit {audit_id} is not {role}'s workbook {upload['workbookId']} "
                            f"(read returned {read.status})")
    leak = ctx.call("GET", _audit_path({**theirs, "auditId": advanced.triggeredAudits[order.index(theirs)]}),
                    role="userA", session=session)
    if leak.status not in (403, 404):
        problems.append(f"user A could read user B's scheduled audit ({leak.status})")
    return _verdict("Two workbooks", problems, "One advance dispatched both owners' workbooks in workbookId order "
                                               "without cross-owner access.")


def _schedule_failed_next(case, ctx):
    session, record, due = _due_namespace(ctx, faults={"scheduled_audit_failures": 1})
    upload = record["upload"]
    first = _clock(ctx, session, _show(due))
    ctx.mark()
    if len(first.triggeredAudits) != 1:
        return CaseResult.failed(f"The due advance triggered {len(first.triggeredAudits)} audits, expected 1.")
    failed = _scheduled_audit(ctx, upload, upload["versionId"], first.triggeredAudits[0], session,
                              "The injected scheduled audit")
    problems = []
    if failed.status != "PROCESSING_FAILED" or not failed.error or failed.error.code != "TEST_SCHEDULED_AUDIT_FAILURE":
        problems.append(f"the injected scheduled audit ended {failed.status} "
                        f"({failed.error.code if failed.error else 'no error'})")
    problems += _source_problems(ctx, upload, record["bytes"], session)
    second = _clock(ctx, session, _show(due + DAY), "The next interval's advance")
    if len(second.triggeredAudits) != 1:
        problems.append(f"the next interval triggered {len(second.triggeredAudits)} audits, expected 1")
    else:
        later = _scheduled_audit(ctx, upload, upload["versionId"], second.triggeredAudits[0], session,
                                 "The next scheduled audit")
        if later.status == "PROCESSING_FAILED":
            problems.append("the next interval's audit also failed")
    return _verdict("Scheduled failure then recovery", problems, "The injected scheduled failure kept the source; "
                                                                 "the next interval ran normally as a new audit.")


INVALID_SCHEDULES = {
    "REJECT-ZERO": b'{"enabled": true, "intervalDays": 0}',
    "REJECT-OVER": b'{"enabled": true, "intervalDays": 91}',
    "REJECT-BOOL": b'{"enabled": true, "intervalDays": true}',
    "REJECT-STRING": b'{"enabled": true, "intervalDays": "7"}',
    "REJECT-DECIMAL": b'{"enabled": true, "intervalDays": 7.0}',
    "REJECT-NULL": b'{"enabled": true, "intervalDays": null}',
    "REJECT-MISSING": b'{"enabled": true}',
    "REJECT-INVALID-DAY": b'{"enabled": false, "complianceDeadline": "2027-02-30"}',
    "REJECT-BAD-FORM": b'{"enabled": false, "complianceDeadline": "2027/04/26"}',
    "UNKNOWN-FIELD": b'{"enabled": false, "complianceDeadline": null, "remindEvery": 7}',
}


def _schedule_rejected(case, ctx):
    ##  Spec §6: invalid content is 400 INVALID_REQUEST and leaves the previous configuration unchanged.
    upload = _workbook(ctx, True)["upload"]
    before = _schedule(ctx, upload, True, {"enabled": True, "intervalDays": 7, "complianceDeadline": "2027-04-26"},
                       "The valid starting schedule")
    raw = INVALID_SCHEDULES[case.parameters["case"]]
    response = _put(ctx, upload, None, True, raw=raw)
    if response.status >= 500:
        return _system_failure("The invalid schedule request", response)
    ctx.mark()
    problems = _rejection(response, 400, "INVALID_REQUEST", f"the schedule {raw.decode()}")
    if response.status == 200:
        problems.append("the invalid schedule was accepted")
    after = _schedule(ctx, upload, True, what="The schedule after the refused request")
    if after != before:
        problems.append(f"the configuration changed to {after.model_dump()}")
    return _verdict("Invalid schedule", problems, f"{raw.decode()} was refused with 400 INVALID_REQUEST and the "
                                                  f"previous configuration was unchanged.")


SCHEDULE_CASES = {"DEFAULT": _schedule_default, "MIN": _schedule_min, "MAX": _schedule_max,
                  "PUT-REPLAY": _schedule_put_replay, "DEADLINE-ONLY": _schedule_deadline_only,
                  "INTERVAL-CHANGE": _schedule_interval_change, "DISABLE": _schedule_disable,
                  "REENABLE": _schedule_reenable, "BEFORE-DUE": _schedule_before_due, "EXACT-DUE": _schedule_exact_due,
                  "COALESCE": _schedule_coalesce, "SAME-TIME": _schedule_same_time,
                  "LATEST-UPLOAD": _schedule_latest_upload, "LATEST-OUTPUT": _schedule_latest_output,
                  "OLD-REAUDIT": _schedule_old_reaudit, "BUSY-AUDIT": _schedule_busy_audit,
                  "BUSY-REMEDIATION": _schedule_busy_remediation, "TWO-WORKBOOKS": _schedule_two_workbooks,
                  "FAILED-NEXT": _schedule_failed_next, **{name: _schedule_rejected for name in INVALID_SCHEDULES}}


def phase5_schedule(case, ctx):
    return _run(case, ctx, SCHEDULE_CASES)


##  ---- P5-REMINDER-* (spec §8) ----

DEADLINE = "2027-04-26"      # policy vector: thresholds 2027-01-26, 2027-03-27 and 2027-04-19
REMINDER_DAYS = (90, 30, 7)
REMINDER_TYPE = "COMPLIANCE_DEADLINE_REMINDER"
LEAP_VECTORS = {"2028-04-26": {90: "2028-01-27T00:00:00Z", 30: "2028-03-27T00:00:00Z", 7: "2028-04-19T00:00:00Z"}}


def _threshold(deadline, offset):
    ##  00:00:00Z on the deadline date minus `offset` UTC calendar days.
    day = date.fromisoformat(deadline)
    return datetime(day.year, day.month, day.day, tzinfo=timezone.utc) - offset * DAY


def _notifications_path(upload):
    return f"{WORKBOOKS}/{upload['workbookId']}/notifications"


def _notifications(ctx, upload, session, role="userA", what="The notification list"):
    ##  The workbook's notification records (dicts, in returned order) from a read the case relies on.
    response = ctx.call("GET", _notifications_path(upload), role=role, session=session)
    if response.status >= 500:
        raise Stop(_system_failure(what, response))
    if response.status != 200:
        raise Stop(CaseResult.failed(f"{what} returned {response.status}, expected 200."))
    try:
        notes = NotificationResponse.model_validate(response.json()).model_dump()["notifications"]
    except ValidationError as problem:
        raise Stop(CaseResult.failed(f"{what} does not match NotificationResponse "
                                     f"({_schema_problem(problem)}).")) from None
    for note in notes:
        if note["workbookId"] != upload["workbookId"] or note["type"] != REMINDER_TYPE:
            raise Stop(CaseResult.failed(f"{what} has record {note['notificationId']} of type {note['type']} for "
                                         f"workbook {note['workbookId']}; expected only {REMINDER_TYPE} records "
                                         f"for {upload['workbookId']}."))
    return notes


def _deadline_namespace(ctx, key="seeded_all_six", deadline=DEADLINE, clock=None, faults=None, body=None):
    ##  A fresh namespace with one audited workbook whose deadline is set (periodic auditing off).
    session = _namespace(ctx, clock=clock, faults=faults)
    record = _workbook(ctx, session, key)
    _schedule(ctx, record["upload"], session, body or {"enabled": False, "complianceDeadline": deadline})
    return session, record


def _new_notes(advanced, notes, expected, label):
    ##  Problems unless this advance recorded exactly `expected` [(threshold, versionId, status)],
    ##  in that order, each visible in the list with the triggered ID.
    problems = []
    if len(advanced.triggeredNotifications) != len(expected):
        return [f"{label}: the advance recorded {len(advanced.triggeredNotifications)} notifications, "
                f"expected {len(expected)}"]
    by_id = {n["notificationId"]: n for n in notes}
    for note_id, (moment, version_id, status) in zip(advanced.triggeredNotifications, expected):
        note = by_id.get(note_id)
        if note is None:
            problems.append(f"{label}: triggered notification {note_id} is not in the list")
            continue
        if not _same(note["scheduledFor"], moment):
            problems.append(f"{label}: scheduledFor is {note['scheduledFor']}, expected the threshold {_show(moment)}")
        if note["versionId"] != version_id:
            problems.append(f"{label}: the reminder names version {note['versionId']}, expected {version_id}")
        if note["status"] != status:
            problems.append(f"{label}: status {note['status']}, expected {status}")
    return problems


def _reminder_threshold(case, ctx):
    offset = int(case.parameters["case"])
    session, record = _deadline_namespace(ctx)
    upload = record["upload"]
    earlier = [o for o in REMINDER_DAYS if o > offset]
    for passed in earlier:
        _clock(ctx, session, _show(_threshold(DEADLINE, passed)), f"The advance to the {passed}-day threshold")
    moment = _threshold(DEADLINE, offset)
    advanced = _clock(ctx, session, _show(moment), f"The advance to the {offset}-day threshold")
    ctx.mark()
    notes = _notifications(ctx, upload, session)
    problems = _new_notes(advanced, notes, [(moment, upload["versionId"], "DELIVERED")], f"{offset} days")
    if len(notes) != len(earlier) + 1:
        problems.append(f"the list holds {len(notes)} records, expected {len(earlier) + 1}")
    return _verdict(f"{offset}-day reminder", problems, f"An eligible workbook got one DELIVERED reminder scheduled "
                                                        f"for exactly {_show(moment)}.")


def _reminder_before(case, ctx):
    session, record = _deadline_namespace(ctx)
    advanced = _clock(ctx, session, _show(_threshold(DEADLINE, 90) - timedelta(microseconds=1)))
    ctx.mark()
    notes = _notifications(ctx, record["upload"], session)
    problems = [] if not advanced.triggeredNotifications and not notes else ["a reminder was recorded before its threshold"]
    return _verdict("Before the threshold", problems, "One microsecond before the 90-day threshold no reminder exists.")


def _reminder_clean(case, ctx):
    session, record = _deadline_namespace(ctx, key="clean_all_six")
    advanced = _clock(ctx, session, _show(_threshold(DEADLINE, 90)))
    ctx.mark()
    notes = _notifications(ctx, record["upload"], session)
    problems = [] if not advanced.triggeredNotifications and not notes else \
        ["a workbook whose latest audit is clean still got a reminder"]
    return _verdict("Clean workbook", problems, "A latest successful audit with no findings suppressed the reminder.")


def _reminder_unfinished(case, ctx, read_while_processing):
    ##  NO-AUDIT and PROCESSING: the threshold passes while the upload's audit has not completed.
    ##  The clean fixture makes eligibility come only from that. Audit timestamps use effective
    ##  time (spec §9), so a completedAt before the threshold proves the audit finished first.
    session = _namespace(ctx)
    response = ctx.upload(WORKBOOKS, role="userA", fixture="clean_all_six", session=session)
    if response.status != 202:
        return CaseResult.failed(f"The upload returned {response.status}, expected 202.")
    upload = UploadResponse.model_validate(response.json()).model_dump()
    _schedule(ctx, upload, session, {"enabled": False, "complianceDeadline": DEADLINE})
    moment = _threshold(DEADLINE, 90)
    advanced = _clock(ctx, session, _show(moment))
    problems = []
    if read_while_processing:
        state = ctx.call("GET", _audit_path(upload), role="userA", session=session)
        body = state.json() if state.status == 200 else {}
        if isinstance(body, dict) and body.get("status") == "PROCESSING" and body.get("findings"):
            problems.append(f"the PROCESSING audit exposed {len(body['findings'])} partial findings")
    audit = _scheduled_audit(ctx, upload, upload["versionId"], upload["auditId"], session, "The upload audit")
    if not advanced.triggeredNotifications and audit.completedAt and _ts(audit.completedAt) < moment:
        return CaseResult("skip", "Not executed: the upload audit completed before the clock call, so no version "
                                  "without a completed audit existed at the threshold.")
    ctx.mark()
    notes = _notifications(ctx, upload, session)
    problems += _new_notes(advanced, notes, [(moment, upload["versionId"], "DELIVERED")], "the unfinished audit")
    what = "processing" if read_while_processing else "not yet completed"
    return _verdict(f"Audit {what}", problems, f"A latest version whose audit was {what} at the threshold was "
                                               f"eligible{', and no partial findings were exposed' if read_while_processing else ''}.")


def _reminder_failed_audit(case, ctx):
    session = _namespace(ctx, faults={"audit_failures": 1})
    response = ctx.upload(WORKBOOKS, role="userA", fixture="clean_all_six", session=session)
    if response.status != 202:
        return CaseResult.failed(f"The upload returned {response.status}, expected 202.")
    upload = UploadResponse.model_validate(response.json()).model_dump()
    audit = _scheduled_audit(ctx, upload, upload["versionId"], upload["auditId"], session, "The armed upload audit")
    if audit.status != "PROCESSING_FAILED":
        return CaseResult.failed(f"The armed audit failure did not occur (the audit ended {audit.status}), so a "
                                 f"failed latest audit could not be produced.")
    _schedule(ctx, upload, session, {"enabled": False, "complianceDeadline": DEADLINE})
    moment = _threshold(DEADLINE, 90)
    advanced = _clock(ctx, session, _show(moment))
    ctx.mark()
    notes = _notifications(ctx, upload, session)
    return _verdict("Failed latest audit", _new_notes(advanced, notes, [(moment, upload["versionId"], "DELIVERED")],
                                                      "the failed audit"),
                    "A latest PROCESSING_FAILED audit (of a clean workbook) was eligible for the reminder.")


def _reminder_declined(case, ctx):
    session = _namespace(ctx)
    record = _workbook(ctx, session, "seeded_all_six")
    upload = record["upload"]
    decisions = [{"findingId": f["findingId"], "action": "DECLINE" if f["classification"] == "REQUIRES_USER_INPUT"
                  else "MANUAL_REVIEW"} for f in record["audit"]["findings"]]
    response = _submit(ctx, record, decisions, session=session)
    if response.status != 202:
        return CaseResult.failed(f"The decline/manual-review remediation returned {response.status}, expected 202.")
    finished, done = _poll_remediation(ctx, response.json()["remediationId"], session)
    if not done or finished.status != 200 or finished.json().get("status") != "REMEDIATED":
        return CaseResult.failed(f"The decline/manual-review remediation did not finish REMEDIATED "
                                 f"({finished.json().get('status') if finished.status == 200 else finished.status}).")
    newest = _schedule(ctx, upload, session, {"enabled": False, "complianceDeadline": DEADLINE}).versionId
    output = finished.json()["outputVersionId"]
    _scheduled_audit(ctx, upload, output, finished.json()["auditId"], session, "The output audit")
    moment = _threshold(DEADLINE, 90)
    advanced = _clock(ctx, session, _show(moment))
    ctx.mark()
    notes = _notifications(ctx, upload, session)
    problems = [] if newest == output else [f"the schedule follows {newest}, not the newest output {output}"]
    problems += _new_notes(advanced, notes, [(moment, output, "DELIVERED")], "declined findings")
    return _verdict("Declined and manual findings", problems, "After every finding was declined or sent to manual "
                                                              "review, the newest version was still eligible.")


def _reminder_periodic_off(case, ctx):
    session, record = _deadline_namespace(ctx, body={"enabled": True, "intervalDays": 1})
    upload = record["upload"]
    _schedule(ctx, upload, session, {"enabled": False, "complianceDeadline": DEADLINE})
    moment = _threshold(DEADLINE, 90)
    advanced = _clock(ctx, session, _show(moment))
    ctx.mark()
    notes = _notifications(ctx, upload, session)
    problems = [f"{len(advanced.triggeredAudits)} periodic audits ran while disabled"] if advanced.triggeredAudits else []
    problems += _new_notes(advanced, notes, [(moment, upload["versionId"], "DELIVERED")], "periodic off")
    return _verdict("Periodic auditing off", problems, "With periodic auditing disabled the deadline reminder was "
                                                       "still recorded, and no periodic audit ran.")


def _reminder_clear_deadline(case, ctx):
    session, record = _deadline_namespace(ctx)
    upload = record["upload"]
    _clock(ctx, session, _show(_threshold(DEADLINE, 90)))
    first = _notifications(ctx, upload, session)
    _schedule(ctx, upload, session, {"enabled": False, "complianceDeadline": None})
    advanced = _clock(ctx, session, _show(_threshold(DEADLINE, 7)))
    ctx.mark()
    after = _notifications(ctx, upload, session)
    problems = [] if len(first) == 1 else [f"the 90-day threshold recorded {len(first)} reminders, expected 1"]
    if advanced.triggeredNotifications:
        problems.append("a null deadline still produced reminders")
    if after != first:
        problems.append("clearing the deadline changed or removed the earlier record")
    return _verdict("Cleared deadline", problems, "A null deadline produced no further reminders and kept the "
                                                  "earlier record unchanged.")


def _reminder_no_backfill(case, ctx):
    session, record = _deadline_namespace(ctx, clock=_show(_threshold(DEADLINE, 90) + DAY))
    upload = record["upload"]
    moment = _threshold(DEADLINE, 30)
    advanced = _clock(ctx, session, _show(moment))
    ctx.mark()
    notes = _notifications(ctx, upload, session)
    problems = _new_notes(advanced, notes, [(moment, upload["versionId"], "DELIVERED")], "after a late deadline")
    if len(notes) != 1:
        problems.append(f"the list holds {len(notes)} records; the passed 90-day threshold must not be backfilled")
    return _verdict("No backfill", problems, "A deadline set after its 90-day threshold produced only the 30-day "
                                             "reminder.")


def _reminder_config_exact(case, ctx):
    moment = _threshold(DEADLINE, 90)
    session, record = _deadline_namespace(ctx, clock=_show(moment))
    upload = record["upload"]
    advanced = _clock(ctx, session, _show(moment), "The equal-time advance")
    replay = _clock(ctx, session, _show(moment), "The repeated equal-time advance")
    ctx.mark()
    notes = _notifications(ctx, upload, session)
    problems = _new_notes(advanced, notes, [(moment, upload["versionId"], "DELIVERED")], "configured at the threshold")
    if replay.triggeredNotifications:
        problems.append("a second equal-time pass issued the reminder again")
    return _verdict("Configured at a threshold", problems, "A deadline configured exactly at its threshold was "
                                                           "issued by one equal-time pass, once.")


def _reminder_jump(case, ctx):
    session, record = _deadline_namespace(ctx)
    upload = record["upload"]
    advanced = _clock(ctx, session, _show(_threshold(DEADLINE, 7)), "The jump past all three thresholds")
    ctx.mark()
    notes = _notifications(ctx, upload, session)
    expected = [(_threshold(DEADLINE, o), upload["versionId"], "DELIVERED") for o in REMINDER_DAYS]
    return _verdict("Jump across thresholds", _new_notes(advanced, notes, expected, "the jump"),
                    "One forward jump recorded the 90-, 30- and 7-day reminders in that order.")


def _reminder_dedup(case, ctx):
    session, record = _deadline_namespace(ctx)
    upload = record["upload"]
    moment = _threshold(DEADLINE, 90)
    _clock(ctx, session, _show(moment))
    again = [_clock(ctx, session, _show(moment), "The repeated advance")]
    _schedule(ctx, upload, session, {"enabled": False, "complianceDeadline": DEADLINE}, "The repeated deadline")
    again.append(_clock(ctx, session, _show(moment), "The advance after the repeated PUT"))
    again.append(_clock(ctx, session, _show(moment + timedelta(hours=1)), "The later advance"))
    ctx.mark()
    notes = _notifications(ctx, upload, session)
    problems = [] if len(notes) == 1 else [f"the list holds {len(notes)} records, expected 1"]
    if any(a.triggeredNotifications for a in again):
        problems.append("a repeated timestamp, repeated PUT or later tick issued the occurrence again")
    return _verdict("Deduplicated reminder", problems, "Repeated clock calls and an identical PUT did not "
                                                       "duplicate the occurrence.")


def _reminder_clean_then_dirty(case, ctx):
    session, record = _deadline_namespace(ctx, key="clean_all_six")
    upload = record["upload"]
    first = _clock(ctx, session, _show(_threshold(DEADLINE, 90)))
    newer = _new_version(ctx, upload, session, key="seeded_all_six")
    later = _clock(ctx, session, _show(_threshold(DEADLINE, 90) + DAY))
    moment = _threshold(DEADLINE, 30)
    advanced = _clock(ctx, session, _show(moment))
    ctx.mark()
    notes = _notifications(ctx, upload, session)
    problems = ["the clean 90-day evaluation issued a reminder"] if first.triggeredNotifications else []
    if later.triggeredNotifications:
        problems.append("the 90-day occurrence was issued retroactively once the workbook became dirty")
    problems += _new_notes(advanced, notes, [(moment, newer["versionId"], "DELIVERED")], "the 30-day threshold")
    if len(notes) != 1:
        problems.append(f"the list holds {len(notes)} records, expected only the 30-day one")
    return _verdict("Clean then dirty", problems, "An occurrence considered clean was not emitted later; the next "
                                                  "threshold reminded about the newer dirty version.")


def _reminder_return_deadline(case, ctx):
    session, record = _deadline_namespace(ctx)
    upload = record["upload"]
    moment = _threshold(DEADLINE, 90)
    _clock(ctx, session, _show(moment))
    _schedule(ctx, upload, session, {"enabled": False, "complianceDeadline": "2027-12-31"}, "The changed deadline")
    _schedule(ctx, upload, session, {"enabled": False, "complianceDeadline": DEADLINE}, "The restored deadline")
    again = [_clock(ctx, session, _show(moment)), _clock(ctx, session, _show(moment + timedelta(hours=1)))]
    ctx.mark()
    notes = _notifications(ctx, upload, session)
    problems = [] if len(notes) == 1 else [f"the list holds {len(notes)} records, expected 1"]
    if any(a.triggeredNotifications for a in again):
        problems.append("returning to the earlier deadline reissued its considered 90-day key")
    return _verdict("Returned deadline", problems, "Returning to an earlier deadline did not reissue its "
                                                   "considered occurrence.")


def _reminder_deadline_edit(case, ctx):
    session, record = _deadline_namespace(ctx)
    upload = record["upload"]
    _clock(ctx, session, _show(_threshold(DEADLINE, 90)))
    first = _notifications(ctx, upload, session)
    changed = "2027-05-26"
    _schedule(ctx, upload, session, {"enabled": False, "complianceDeadline": changed}, "The edited deadline")
    moment = _threshold(changed, 90)
    advanced = _clock(ctx, session, _show(moment))
    ctx.mark()
    notes = _notifications(ctx, upload, session)
    problems = _new_notes(advanced, notes, [(moment, upload["versionId"], "DELIVERED")], "the new deadline")
    if len(first) != 1 or first[0] not in notes:
        problems.append("the earlier deadline's record changed or disappeared")
    return _verdict("Edited deadline", problems, "The new deadline produced its own future reminder and the "
                                                 "earlier record was retained unchanged.")


def _reminder_latest_version(case, ctx):
    session, record = _deadline_namespace(ctx, key="clean_all_six")
    upload = record["upload"]
    newer = _new_version(ctx, upload, session, key="seeded_all_six")
    moment = _threshold(DEADLINE, 90)
    advanced = _clock(ctx, session, _show(moment))
    ctx.mark()
    notes = _notifications(ctx, upload, session)
    return _verdict("Newest version", _new_notes(advanced, notes, [(moment, newer["versionId"], "DELIVERED")],
                                                 "newest version"),
                    "The reminder named the newest (dirty) version, not the earlier clean one.")


def _reminder_audit_same_tick(case, ctx):
    moment = _threshold(DEADLINE, 90)
    interval = (moment - _ts(EPOCH)).days
    session, record = _deadline_namespace(ctx, key="clean_all_six", body={
        "enabled": True, "intervalDays": interval, "complianceDeadline": DEADLINE})
    upload = record["upload"]
    advanced = _clock(ctx, session, _show(moment))
    ctx.mark()
    problems = [] if len(advanced.triggeredAudits) == 1 else [f"the tick dispatched {len(advanced.triggeredAudits)} "
                                                              f"scheduled audits, expected 1"]
    if advanced.triggeredNotifications:
        problems.append("the audit dispatched in the same tick made the clean workbook look unresolved")
    for audit_id in advanced.triggeredAudits:
        _scheduled_audit(ctx, upload, upload["versionId"], audit_id, session, "The same-tick scheduled audit")
    if _notifications(ctx, upload, session):
        problems.append("a reminder was recorded for the clean workbook")
    return _verdict("Same-tick audit", problems, "Eligibility used the pre-dispatch snapshot: the clean workbook got "
                                                 "its scheduled audit and no reminder.")


def _reminder_leap(case, ctx):
    deadline, vectors = next(iter(LEAP_VECTORS.items()))
    session, record = _deadline_namespace(ctx, deadline=deadline, clock="2028-01-01T00:00:00Z")
    upload = record["upload"]
    advanced = _clock(ctx, session, vectors[7])
    ctx.mark()
    notes = _notifications(ctx, upload, session)
    expected = [(_ts(vectors[o]), upload["versionId"], "DELIVERED") for o in REMINDER_DAYS]
    return _verdict("Leap-year thresholds", _new_notes(advanced, notes, expected, f"deadline {deadline}"),
                    f"Thresholds for {deadline} equal the frozen UTC vectors {', '.join(vectors.values())}.")


def _notification_failure(ctx, label):
    ##  REMINDER-FAILED-RECORD and FAULT-NOTIFICATION: the injected failure records FAILED, leaves
    ##  audit state alone, is not retried, and is one-shot (the next eligible reminder is DELIVERED).
    session, record = _deadline_namespace(ctx, faults={"notification_failures": 1})
    upload = record["upload"]
    before, problem = _history(ctx, upload["workbookId"], session)
    if problem:
        return CaseResult.failed(f"The history before the threshold failed: {problem}.")
    moment = _threshold(DEADLINE, 90)
    advanced = _clock(ctx, session, _show(moment))
    ctx.mark()
    notes = _notifications(ctx, upload, session)
    problems = _new_notes(advanced, notes, [(moment, upload["versionId"], "FAILED")], "the injected failure")
    after, problem = _history(ctx, upload["workbookId"], session)
    if problem or after["audits"] != before["audits"] or after["versions"] != before["versions"]:
        problems.append("the notification failure changed audit or version state")
    retry = _clock(ctx, session, _show(moment + DAY), "The later advance")
    if retry.triggeredNotifications:
        problems.append("the failed reminder was retried automatically")
    nxt = _threshold(DEADLINE, 30)
    following = _clock(ctx, session, _show(nxt), "The advance to the 30-day threshold")
    problems += _new_notes(following, _notifications(ctx, upload, session),
                           [(nxt, upload["versionId"], "DELIVERED")], "the next reminder")
    return _verdict(label, problems, "The injected failure recorded one FAILED reminder, left audit state unchanged, "
                                     "was not retried, and the next reminder was DELIVERED.")


def _reminder_failed_record(case, ctx):
    return _notification_failure(ctx, "Failed reminder record")


def _reminder_empty(case, ctx):
    record, result = _audited(ctx, "seeded_all_six", ctx.case.test_id, True)
    if result:
        return result
    response = ctx.call("GET", _notifications_path(record["upload"]), role="userA")
    if response.status >= 500:
        return _system_failure("The notification list", response)
    ctx.mark()
    if response.status != 200:
        return CaseResult.failed(f"The notification list returned {response.status}, expected 200.")
    return _verdict("No reminders", [] if response.json() == {"notifications": []} else
                    [f"the body is {response.body[:200]!r}, expected exactly {{\"notifications\": []}}"],
                    "A workbook with no reminders returned exactly {\"notifications\": []}.")


def _reminder_order(case, ctx):
    session, record = _deadline_namespace(ctx)
    upload = record["upload"]
    _clock(ctx, session, _show(_threshold(DEADLINE, 30)))
    _clock(ctx, session, _show(_threshold(DEADLINE, 7)))
    ctx.mark()
    first, second = _notifications(ctx, upload, session), _notifications(ctx, upload, session)
    times = [_ts(n["scheduledFor"]) for n in first]
    problems = [] if len(first) == 3 else [f"the list holds {len(first)} records, expected 3"]
    if times != sorted(times):
        problems.append(f"records are not in scheduledFor order: {[n['scheduledFor'] for n in first]}")
    if first != second:
        problems.append("two consecutive reads returned different lists")
    return _verdict("Notification order", problems, "Records came back oldest scheduledFor first, identically on "
                                                    "repeated reads.")


REMINDER_CASES = {"90": _reminder_threshold, "30": _reminder_threshold, "7": _reminder_threshold,
                  "BEFORE": _reminder_before, "CLEAN": _reminder_clean,
                  "NO-AUDIT": lambda case, ctx: _reminder_unfinished(case, ctx, False),
                  "PROCESSING": lambda case, ctx: _reminder_unfinished(case, ctx, True),
                  "FAILED-AUDIT": _reminder_failed_audit, "DECLINED": _reminder_declined,
                  "PERIODIC-OFF": _reminder_periodic_off, "CLEAR-DEADLINE": _reminder_clear_deadline,
                  "NO-BACKFILL": _reminder_no_backfill, "CONFIG-EXACT": _reminder_config_exact,
                  "JUMP": _reminder_jump, "DEDUP": _reminder_dedup, "CLEAN-THEN-DIRTY": _reminder_clean_then_dirty,
                  "RETURN-DEADLINE": _reminder_return_deadline, "DEADLINE-EDIT": _reminder_deadline_edit,
                  "LATEST-VERSION": _reminder_latest_version, "AUDIT-SAME-TICK": _reminder_audit_same_tick,
                  "LEAP-UTC": _reminder_leap, "FAILED-RECORD": _reminder_failed_record, "EMPTY": _reminder_empty,
                  "ORDER": _reminder_order}


def phase5_reminder(case, ctx):
    return _run(case, ctx, REMINDER_CASES)


##  ---- P5-DELETE-* (spec §10) ----

def _workbook_path(upload):
    return f"{WORKBOOKS}/{upload['workbookId']}"


def _delete(ctx, upload, session, role="userA", **kwargs):
    return ctx.call("DELETE", _workbook_path(upload), role=role, session=session, **kwargs)


def _deleted(ctx, upload, session, what="The owner deletion"):
    ##  Problems with a DELETE the case expects to complete (204 and no body).
    response = _delete(ctx, upload, session)
    if response.status >= 500:
        raise Stop(_system_failure(what, response))
    if response.status != 204:
        return [f"{what} returned {response.status}, expected 204"]
    return [] if response.body == b"" else [f"{what} returned a {len(response.body)}-byte body; 204 has none"]


def _gone(ctx, urls, session):
    ##  Problems for every URL that does not now answer 404.
    problems = []
    for label, path in urls:
        response = ctx.call("GET", path, role="userA", session=session)
        if response.status != 404:
            problems.append(f"{label} returned {response.status}, expected 404")
    return problems


def _rich(ctx, session):
    ##  A workbook with every kind of derived content: source, a remediation output with its audit,
    ##  report and review, history, a schedule and a reminder record. (record, [(label, URL)]).
    record = _workbook(ctx, session, "seeded_all_six")
    upload = record["upload"]
    accepted = _remediate(ctx, record, session)
    finished, done = _poll_remediation(ctx, accepted["remediationId"], session)
    result = finished.json() if finished.status == 200 else {}
    if not done or result.get("status") != "REMEDIATED":
        raise Stop(CaseResult.failed(f"The remediation did not finish REMEDIATED ({result.get('status')})."))
    output = {**upload, "versionId": result["outputVersionId"], "auditId": result["auditId"]}
    _scheduled_audit(ctx, upload, output["versionId"], output["auditId"], session, "The output audit")
    _schedule(ctx, upload, session, {"enabled": True, "intervalDays": 30, "complianceDeadline": DEADLINE})
    _clock(ctx, session, _show(_threshold(DEADLINE, 90)))
    if not _notifications(ctx, upload, session):
        raise Stop(CaseResult.failed("The rich workbook got no reminder record to delete."))
    urls = [("history", f"{_workbook_path(upload)}/history"), ("schedule", _schedule_path(upload)),
            ("notifications", _notifications_path(upload))]
    for label, item in (("source", upload), ("output", output)):
        urls += [(f"{label} version", _version_path(item)), (f"{label} source download", f"{_version_path(item)}/source"),
                 (f"{label} audit", _audit_path(item)), (f"{label} report", f"{_audit_path(item)}/report"),
                 (f"{label} review", f"{_audit_path(item)}/review")]
    urls += [("output download", f"/api/v1/outputs/{result['outputId']}/workbook"),
             ("remediation", f"/api/v1/remediations/{accepted['remediationId']}")]
    return record, urls


def _delete_complete(case, ctx):
    session = _namespace(ctx)
    record, urls = _rich(ctx, session)
    problems = _deleted(ctx, record["upload"], session)
    ctx.mark()
    problems += _gone(ctx, [u for u in urls if u[0] in ("history", "schedule", "notifications", "source source download",
                                                       "output download", "source report")], session)
    return _verdict("Complete deletion", problems, "The owner's DELETE returned 204 with no body and the source, "
                                                   "output, report, history, schedule and notifications are gone.")


def _delete_old_urls(case, ctx):
    session = _namespace(ctx)
    record, urls = _rich(ctx, session)
    problems = _deleted(ctx, record["upload"], session)
    ctx.mark()
    problems += _gone(ctx, urls, session)
    return _verdict("Old URLs", problems, f"All {len(urls)} known workbook, version, audit, output, review, report, "
                                          f"history, schedule, notification and remediation URLs return 404.")


def _delete_repeat(case, ctx):
    session = _namespace(ctx)
    upload = _workbook(ctx, session)["upload"]
    problems = _deleted(ctx, upload, session)
    again = _delete(ctx, upload, session)
    ctx.mark()
    problems += _rejection(again, 404, None, "the repeated DELETE")
    return _verdict("Repeated deletion", problems, "A second DELETE of the deleted workbook returned 404.")


def _delete_cancel_future(case, ctx):
    session = _namespace(ctx)
    upload = _workbook(ctx, session, "seeded_all_six")["upload"]
    _schedule(ctx, upload, session, {"enabled": True, "intervalDays": 1, "complianceDeadline": DEADLINE})
    problems = _deleted(ctx, upload, session)
    advanced = _clock(ctx, session, _show(_threshold(DEADLINE, 7)))
    ctx.mark()
    if advanced.triggeredAudits or advanced.triggeredNotifications:
        problems.append(f"after deletion the advance created {len(advanced.triggeredAudits)} audits and "
                        f"{len(advanced.triggeredNotifications)} reminders")
    return _verdict("Future work cancelled", problems, "Advancing past due times and thresholds after deletion "
                                                       "created no audit or reminder.")


def _snapshot(ctx, record, session):
    ##  What deletion of another workbook must leave unchanged: source bytes, history and schedule.
    upload = record["upload"]
    source = ctx.download(f"{_version_path(upload)}/source", role="userA", session=session)
    history, _problem = _history(ctx, upload["workbookId"], session)
    schedule = ctx.call("GET", _schedule_path(upload), role="userA", session=session)
    return source.status, source.body, history, schedule.status, schedule.body


def _delete_other_data(case, ctx):
    session, other = _namespace(ctx), _namespace(ctx)
    doomed = _workbook(ctx, session, "preservation_rich")["upload"]
    kept = _workbook(ctx, session, "seeded_all_six")
    _schedule(ctx, kept["upload"], session, {"enabled": False, "complianceDeadline": DEADLINE})
    elsewhere = _workbook(ctx, other, "clean_all_six")
    before = [_snapshot(ctx, kept, session), _snapshot(ctx, elsewhere, other)]
    problems = _deleted(ctx, doomed, session)
    ctx.mark()
    after = [_snapshot(ctx, kept, session), _snapshot(ctx, elsewhere, other)]
    for label, old, new in zip(("the other workbook in the namespace", "the workbook in another namespace"), before, after):
        if new != old or old[0] != 200:
            problems.append(f"{label} changed (source, history or schedule differ after the deletion)")
    return _verdict("Other data preserved", problems, "Deleting one workbook left another workbook in its namespace "
                                                      "and a workbook in another namespace byte-identical.")


def _delete_retain_tester(case, ctx):
    return CaseResult("skip", "Not executed: finalized tester reports live in this tester's own store, which no "
                              "target request can reach, so a hosted check has nothing on the target to observe. "
                              "Asked Team 9 how this case is meant to run.")


def _delete_active(ctx, kind, start, still_running, finish, key):
    session = _namespace(ctx)
    record = _workbook(ctx, session, key)
    upload = record["upload"]
    baseline = _schedule(ctx, upload, session, {"enabled": False, "complianceDeadline": DEADLINE})
    before, _problem = _history(ctx, upload["workbookId"], session)
    running = start(record, session)
    if not still_running(running, session):
        finish(running, session)
        return CaseResult("skip", f"Not executed: the {kind} finished before the DELETE could be sent, so the "
                                  f"active condition could not be produced.")
    response = _delete(ctx, upload, session)
    if response.status == 204:
        return CaseResult("skip", f"Not executed: the DELETE returned 204, so the {kind} had finished first (or the "
                                  f"target ignored it); the two cannot be told apart over HTTP.")
    ctx.mark()
    problems = _rejection(response, 409, "ACTIVE_OPERATION", f"the DELETE during an active {kind}")
    problems += _source_problems(ctx, upload, record["bytes"], session)
    if _schedule(ctx, upload, session, what="The schedule after the refused DELETE") != baseline:
        problems.append("the refused DELETE changed the schedule")
    finish(running, session)
    after, _problem = _history(ctx, upload["workbookId"], session)
    if before and after and [v["versionId"] for v in before["versions"]] != \
            [v["versionId"] for v in after["versions"]][:len(before["versions"])]:
        problems.append("the refused DELETE removed versions (partial deletion)")
    problems += _deleted(ctx, upload, session, "The DELETE after the work finished")
    return _verdict(f"DELETE during an active {kind}", problems, f"The DELETE was refused 409 ACTIVE_OPERATION while "
                                                                 f"the {kind} ran and nothing was removed; it "
                                                                 f"completed afterwards.")


def _start_audit(record, session, ctx):
    response = ctx.call("POST", f"{_version_path(record['upload'])}/audits", role="userA", session=session,
                        json_body={})
    if response.status != 202:
        raise Stop(CaseResult.failed(f"The manual re-audit returned {response.status}, expected 202."))
    return {**record["upload"], "auditId": response.json()["auditId"]}


def _delete_active_audit(case, ctx):
    def running(audit, session):
        state = ctx.call("GET", _audit_path(audit), role="userA", session=session)
        return state.status == 200 and state.json().get("status") == "PROCESSING"
    return _delete_active(ctx, "audit", lambda r, s: _start_audit(r, s, ctx), running,
                          lambda a, s: _finished_audit(ctx, a, "The running audit", session=s, mark=False),
                          "clean_all_six")


def _delete_active_remediation(case, ctx):
    def running(accepted, session):
        state = ctx.call("GET", f"/api/v1/remediations/{accepted['remediationId']}", role="userA", session=session)
        return state.status == 200 and state.json().get("status") == "REMEDIATING"
    return _delete_active(ctx, "remediation", lambda r, s: _remediate(ctx, r, s), running,
                          lambda a, s: _poll_remediation(ctx, a["remediationId"], s), "seeded_all_six")


def _deletion_failure(ctx, label):
    ##  DELETE-FAIL-ONCE and FAULT-DELETION: the injected pre-delete failure is a controlled 500
    ##  TEST_DELETION_FAILURE that leaves the workbook readable; the owner's retry completes.
    session = _namespace(ctx, faults={"deletion_failures": 1})
    record = _workbook(ctx, session)
    upload = record["upload"]
    response = _delete(ctx, upload, session)
    ctx.mark()
    problems = _rejection(response, 500, "TEST_DELETION_FAILURE", "the armed DELETE")
    problems += _source_problems(ctx, upload, record["bytes"], session)
    problems += _deleted(ctx, upload, session, "The owner's retry")
    problems += _gone(ctx, [("history", f"{_workbook_path(upload)}/history")], session)
    return _verdict(label, problems, "The injected deletion failure returned 500 TEST_DELETION_FAILURE and left the "
                                     "source readable; the owner's retry returned 204 and removed the workbook.")


def _delete_fail_once(case, ctx):
    return _deletion_failure(ctx, "Deletion failure then retry")


DELETE_CASES = {"COMPLETE": _delete_complete, "OLD-URLS": _delete_old_urls, "REPEAT": _delete_repeat,
                "CANCEL-FUTURE": _delete_cancel_future, "OTHER-DATA": _delete_other_data,
                "RETAIN-TESTER": _delete_retain_tester, "ACTIVE-AUDIT": _delete_active_audit,
                "ACTIVE-REMEDIATION": _delete_active_remediation, "FAIL-ONCE": _delete_fail_once}


def phase5_delete(case, ctx):
    return _run(case, ctx, DELETE_CASES)


##  ---- P5-FAULT-* (spec §11) ----

SIX = ["ALT_TEXT", "WORKSHEET_NAME", "TABLE_HEADER", "MERGED_CELLS", "LINK_TEXT", "COLOR_CONTRAST"]
INJECTED = {"audit": ("TEST_AUDIT_FAILURE", "Audit failure requested by the isolated test session."),
            "remediation": ("TEST_REMEDIATION_FAILURE", "Remediation failure requested by the isolated test session."),
            "report": ("TEST_REPORT_FAILURE", "Report failure requested by the isolated test session."),
            "scheduled_audit": ("TEST_SCHEDULED_AUDIT_FAILURE",
                                "Scheduled audit failure requested by the isolated test session.")}


def _envelope_problems(error, stage, label):
    ##  The exact injected asynchronous error: code, fixed message, details and a requestId.
    code, message = INJECTED[stage]
    if error is None:
        return [f"{label}: no error body"]
    error = error if isinstance(error, dict) else error.model_dump()
    problems = []
    if error.get("code") != code:
        problems.append(f"{label}: code {error.get('code')}, expected {code}")
    if error.get("message") != message:
        problems.append(f"{label}: message {error.get('message')!r}, expected {message!r}")
    if error.get("details") != {"stage": stage, "testOnly": True}:
        problems.append(f"{label}: details {error.get('details')}, expected {{'stage': '{stage}', 'testOnly': True}}")
    if not error.get("requestId"):
        problems.append(f"{label}: no requestId")
    return problems


def _report_problems(ctx, audit_ref, session, checks, label):
    ##  The failed audit's report snapshot: PROCESSING_FAILED, the completed checks only, no findings.
    response = ctx.download(f"{_audit_path(audit_ref)}/report", role="userA", session=session)
    if response.status != 200:
        return [f"{label}: the report download returned {response.status}, expected 200"]
    report = response.json() or {}
    problems = []
    if report.get("status") != "PROCESSING_FAILED":
        problems.append(f"{label}: the report status is {report.get('status')}")
    if report.get("checksPerformed") != checks:
        problems.append(f"{label}: checksPerformed is {report.get('checksPerformed')}, expected {checks}")
    if report.get("findings"):
        problems.append(f"{label}: the failed report carries {len(report['findings'])} partial findings")
    return problems


def _armed_upload(ctx, session, key="clean_all_six"):
    ##  (upload, bytes) for a fixture uploaded in a namespace whose audit is expected to fail.
    response = ctx.upload(WORKBOOKS, role="userA", fixture=key, session=session)
    if response.status != 202:
        raise Stop(CaseResult.failed(f"The upload in the fault namespace returned {response.status}, expected 202."))
    return UploadResponse.model_validate(response.json()).model_dump(), ctx.fixture(key)[0]


def _reaudit_normal(ctx, upload, session, label):
    ##  Problems unless a manual re-audit now runs normally (the control was one-shot).
    response = ctx.call("POST", f"{_version_path(upload)}/audits", role="userA", session=session, json_body={})
    if response.status != 202:
        return [f"{label}: the manual re-audit returned {response.status}, expected 202"]
    audit = _scheduled_audit(ctx, upload, upload["versionId"], response.json()["auditId"], session, label)
    return [f"{label}: the re-audit also failed (the control was not one-shot)"] if audit.status == "PROCESSING_FAILED" else []


def _fault_audit_like(ctx, fault, stage, checks):
    session = _namespace(ctx, faults={fault: 1})
    upload, data = _armed_upload(ctx, session)
    audit = _scheduled_audit(ctx, upload, upload["versionId"], upload["auditId"], session, "The armed audit")
    ctx.mark()
    if audit.status != "PROCESSING_FAILED":
        return CaseResult.failed(f"The armed {fault} control did not fail the first audit (it ended {audit.status}).")
    problems = _envelope_problems(audit.error, stage, "the failed audit")
    if audit.findings:
        problems.append(f"the failed audit exposes {len(audit.findings)} partial findings")
    problems += _report_problems(ctx, upload, session, checks, "the failed report")
    problems += _source_problems(ctx, upload, data, session)
    problems += _reaudit_normal(ctx, upload, session, "The next audit")
    return _verdict(f"{fault} control", problems, f"The first accepted audit failed exactly as specified "
                                                  f"({INJECTED[stage][0]}), the source was kept, and the next audit "
                                                  f"ran normally.")


def _fault_audit(case, ctx):
    return _fault_audit_like(ctx, "audit_failures", "audit", [])


def _fault_report(case, ctx):
    return _fault_audit_like(ctx, "report_failures", "report", SIX)


def _fault_storage(case, ctx):
    session = _namespace(ctx, faults={"storage_failures": 1})
    response = ctx.upload(WORKBOOKS, role="userA", fixture="clean_all_six", session=session)
    ctx.mark()
    problems = _rejection(response, 500, "TEST_STORAGE_FAILURE", "the armed upload")
    body = response.json()
    if isinstance(body, dict) and ({"workbookId", "versionId", "auditId"} & set(body)):
        problems.append("the failed upload response names a workbook, version or audit")
    again = ctx.upload(WORKBOOKS, role="userA", fixture="clean_all_six", session=session)
    if again.status != 202:
        problems.append(f"the next upload returned {again.status}, expected 202 (the control was not one-shot)")
    else:
        later = UploadResponse.model_validate(again.json()).model_dump()
        audit = _scheduled_audit(ctx, later, later["versionId"], later["auditId"], session, "The next upload's audit")
        if audit.status == "PROCESSING_FAILED":
            problems.append("the next upload's audit failed")
    return _verdict("storage_failures control", problems, "The next upload failed before acceptance with 500 "
                                                          "TEST_STORAGE_FAILURE; the following upload was normal.")


def _fault_scheduled_audit(case, ctx):
    session, record, due = _due_namespace(ctx, faults={"scheduled_audit_failures": 1})
    upload = record["upload"]
    advanced = _clock(ctx, session, _show(due))
    ctx.mark()
    if len(advanced.triggeredAudits) != 1:
        return CaseResult.failed(f"The due advance triggered {len(advanced.triggeredAudits)} audits, expected 1.")
    failed = {**upload, "auditId": advanced.triggeredAudits[0]}
    audit = _scheduled_audit(ctx, upload, upload["versionId"], failed["auditId"], session, "The scheduled audit")
    problems = [] if audit.status == "PROCESSING_FAILED" else [f"the armed scheduled audit ended {audit.status}"]
    problems += _envelope_problems(audit.error, "scheduled_audit", "the scheduled audit")
    problems += _report_problems(ctx, failed, session, [], "the failed report")
    problems += _source_problems(ctx, upload, record["bytes"], session)
    nxt = _clock(ctx, session, _show(due + DAY), "The next interval's advance")
    if len(nxt.triggeredAudits) != 1:
        problems.append(f"the next interval triggered {len(nxt.triggeredAudits)} audits, expected 1")
    elif _scheduled_audit(ctx, upload, upload["versionId"], nxt.triggeredAudits[0], session,
                          "The next scheduled audit").status == "PROCESSING_FAILED":
        problems.append("the next scheduled audit also failed")
    return _verdict("scheduled_audit_failures control", problems, "The upload's ordinary audit was unaffected; the "
                                                                  "first scheduled audit failed exactly as specified "
                                                                  "and the next interval ran normally.")


def _fault_remediation(case, ctx):
    session = _namespace(ctx, faults={"remediation_failures": 1})
    record = _workbook(ctx, session, "seeded_all_six")
    upload = record["upload"]
    before, _problem = _history(ctx, upload["workbookId"], session)
    accepted = _remediate(ctx, record, session)
    finished, done = _poll_remediation(ctx, accepted["remediationId"], session)
    ctx.mark()
    body = finished.json() if finished.status == 200 else {}
    problems = [] if done and body.get("status") == "PROCESSING_FAILED" else \
        [f"the armed remediation ended {body.get('status') or finished.status}, expected PROCESSING_FAILED"]
    problems += _envelope_problems(body.get("error"), "remediation", "the failed remediation")
    if any(body.get(k) for k in ("outputVersionId", "outputId", "auditId")):
        problems.append("the failed remediation names an output, output version or audit")
    after, _problem = _history(ctx, upload["workbookId"], session)
    if before and after and len(after["versions"]) != len(before["versions"]):
        problems.append("the failed remediation published a version")
    problems += _source_problems(ctx, upload, record["bytes"], session)
    retry = _remediate(ctx, record, session)
    again, done = _poll_remediation(ctx, retry["remediationId"], session)
    if not done or again.status != 200 or again.json().get("status") != "REMEDIATED":
        problems.append("the next remediation did not finish REMEDIATED (the control was not one-shot)")
    return _verdict("remediation_failures control", problems, "The first remediation failed exactly as specified, "
                                                              "published nothing and kept the source; the next one "
                                                              "succeeded.")


def _fault_notification(case, ctx):
    return _notification_failure(ctx, "notification_failures control")


def _fault_deletion(case, ctx):
    return _deletion_failure(ctx, "deletion_failures control")


def _refused_fault_setup(ctx, faults, status, label):
    session_id, response = _fault_setup_call(ctx, {"faults": faults})
    if response.status >= 500:
        return _system_failure(f"The {label} fault setup", response)
    ctx.mark()
    return _verdict(label, _refused_setup_problems(ctx, session_id, response, status, label,
                                                   source="system" if status == 400 else None),
                    f"Fault setup {faults} was refused with {status} and left no runnable session.")


def _armed(ctx):
    ##  A fresh namespace armed with one audit failure.
    return _namespace(ctx, faults={"audit_failures": 1})


def _audit_result(ctx, session, label):
    ##  The finished audit of a fresh clean upload in `session`.
    upload, _data = _armed_upload(ctx, session)
    return _scheduled_audit(ctx, upload, upload["versionId"], upload["auditId"], session, label)


def _fault_isolated(ctx, other, label, where):
    armed = _armed(ctx)
    elsewhere = _audit_result(ctx, other, f"The audit in {where}")
    still = _audit_result(ctx, armed, "The first audit in the armed namespace")
    ctx.mark()
    problems = [] if elsewhere.status != "PROCESSING_FAILED" else [f"the armed fault failed an audit in {where}"]
    if still.status != "PROCESSING_FAILED":
        problems.append("the armed namespace's first audit did not fail, so the fault was consumed elsewhere")
    return _verdict(label, problems, f"An armed audit failure did not affect {where}; it still failed the armed "
                                     f"namespace's first audit.")


def _fault_reused_id(case, ctx):
    armed = _armed(ctx)
    first = _audit_result(ctx, armed, "The armed audit")
    response = ctx.target.system_setup(armed, {"faults": {"audit_failures": 1}}, ctx.deadline)
    ctx.mark()
    problems = [] if first.status == "PROCESSING_FAILED" else ["the armed audit did not fail"]
    if response.status != 409:
        problems.append(f"repeating setup with the same session ID returned {response.status}, expected 409")
    if _audit_result(ctx, armed, "The audit after the repeated setup").status == "PROCESSING_FAILED":
        problems.append("the repeated setup rearmed the control")
    return _verdict("Reused session ID", problems, "Repeating setup with the same session ID returned 409 and did "
                                                   "not rearm the consumed control.")


def _fault_no_consume(case, ctx):
    armed = _armed(ctx)
    attempts = [("an unsupported .txt upload", ctx.call("POST", WORKBOOKS, role="userA", session=armed,
                                                         files={"file": ("notes.txt", b"not a workbook", "text/plain")})),
                ("an upload without a token", ctx.upload(WORKBOOKS, role=None, fixture="clean_all_six", session=armed)),
                ("an upload with the test-admin token", ctx.upload(WORKBOOKS, role="test-admin", fixture="clean_all_six",
                                                                   session=armed))]
    problems = [f"{label} was accepted ({r.status})" for label, r in attempts if r.status < 400]
    audit = _audit_result(ctx, armed, "The first valid audit")
    ctx.mark()
    if audit.status != "PROCESSING_FAILED":
        problems.append("the first valid audit did not fail, so a rejected request consumed the control")
    return _verdict("Rejected requests keep the control", problems, "Invalid and unauthorized uploads were refused "
                                                                    "and did not consume the armed fault.")


def _fault_disabled(case, ctx):
    session_id, response = _fault_setup_call(ctx, {"faults": {"audit_failures": 1}})
    if response.status == 201:
        return CaseResult("skip", "Not executed: the fault capability is enabled on this deployment (as the other "
                                  "fault cases need), so the disabled 403 cannot be produced here.")
    if response.status >= 500:
        return _system_failure("The fault setup", response)
    ctx.mark()
    return _verdict("Disabled capability", _refused_setup_problems(ctx, session_id, response, 403, "the fault setup"),
                    "A well-formed fault setup with the capability disabled was refused 403 with no runnable session.")


FAULT_CASES = {"AUDIT": _fault_audit, "REMEDIATION": _fault_remediation, "REPORT": _fault_report,
               "STORAGE": _fault_storage, "SCHEDULED_AUDIT": _fault_scheduled_audit,
               "NOTIFICATION": _fault_notification, "DELETION": _fault_deletion,
               "REJECT-UNKNOWN": lambda c, x: _refused_fault_setup(x, {"unknown_failures": 1}, 400, "Unknown control"),
               "REJECT-BOOLEAN": lambda c, x: _refused_fault_setup(x, {"audit_failures": True}, 400, "Boolean counter"),
               "REJECT-EMPTY": lambda c, x: _refused_fault_setup(x, {}, 400, "Empty faults"),
               "REJECT-AUDIT-REPORT-COMBINATION": lambda c, x: _refused_fault_setup(
                   x, {"audit_failures": 1, "report_failures": 1}, 400, "Audit and report combination"),
               "REJECT-DISABLED": _fault_disabled,
               "REJECT-ORDINARY": lambda c, x: _fault_isolated(x, True, "Ordinary data unaffected",
                                                               "the run's own unfaulted namespace"),
               "REJECT-OTHER-SESSION": lambda c, x: _fault_isolated(x, _namespace(x), "Other namespace unaffected",
                                                                    "another fresh namespace"),
               "REJECT-REUSED-ID": _fault_reused_id, "REJECT-REJECT-NO-CONSUME": _fault_no_consume}


def phase5_fault(case, ctx):
    return _run(case, ctx, FAULT_CASES)


##  ---- P5-ACCESS-* (spec §4, §9; expected status from the plan's inputs) ----

IDENTITIES = {"NO-TOKEN": {"role": None}, "INVALID-TOKEN": {"role": None, "bearer": "invalid"},
              "FOREIGN-OWNER": {"role": "userB"}, "WRONG-NAMESPACE": {"role": "userA"},
              "TEST-ADMIN": {"role": "test-admin"}, "UNKNOWN-RESOURCE": {"role": "userA"}, "OWNER": {"role": "userA"},
              "GRANTED-REVIEWER": {"role": "reviewer"}, "UNGRANTED-REVIEWER": {"role": "reviewer-ungranted"}}
CLOCK_IDENTITIES = {"NO-TOKEN": {"role": None}, "INVALID-TOKEN": {"role": None, "bearer": "invalid"},
                    "OWNER-USER": {"role": "userA"}, "REVIEWER": {"role": "reviewer"},
                    "FOREIGN-ADMIN": {"role": "test-admin-2"}, "CREATING-ADMIN": {"role": "test-admin"}}
ACCESS_BASELINE = {"enabled": False, "complianceDeadline": DEADLINE}


def _identity(ctx, spec):
    ##  ctx.call keyword arguments for an identity, or a skip when its optional token is absent.
    role = spec["role"]
    if role is not None and not ctx.target.has_role(role):
        raise Stop(CaseResult("skip", f"Not executed: no {role} token is configured for this target "
                                      f"(TARGET_AUTH_MAP_JSON), so this identity cannot be presented."))
    kwargs = {"role": role}
    if spec.get("bearer"):
        kwargs["bearer"] = f"tester-invalid-{ctx.new_idempotency_key()[7:]}"
    return kwargs


def _access_fixture(ctx):
    ##  The shared access workbook in the run's namespace, with a fixed baseline schedule.
    shared = ctx.state.get("p5_access")
    if shared is None:
        record, result = _audited(ctx, "clean_all_six", "p5-access", True)
        if result:
            raise Stop(result)
        baseline = _schedule(ctx, record["upload"], True, ACCESS_BASELINE, "The access baseline schedule")
        shared = ctx.state["p5_access"] = {"upload": record["upload"], "baseline": baseline}
    return shared


def _access_request(ctx, operation, upload, session, kwargs):
    path = {"SCHEDULE-WRITE": _schedule_path, "SCHEDULE-READ": _schedule_path, "NOTIFICATIONS": _notifications_path,
            "DELETE": _workbook_path}[operation](upload)
    if operation == "SCHEDULE-WRITE":
        return ctx.call("PUT", path, session=session, json_body=ACCESS_BASELINE, **kwargs)
    return ctx.call("DELETE" if operation == "DELETE" else "GET", path, session=session, **kwargs)


def _access_workbook(case, ctx, operation, identity, expected):
    kwargs = _identity(ctx, IDENTITIES[identity])
    shared = _access_fixture(ctx)
    upload, session = shared["upload"], True
    if identity == "WRONG-NAMESPACE":
        session = ctx.state.get("p5_access_other") or ctx.state.setdefault("p5_access_other", _namespace(ctx))
    if identity == "UNKNOWN-RESOURCE":
        upload = {**upload, "workbookId": f"unknown-{ctx.new_idempotency_key()[7:23]}"}
    if operation == "DELETE" and identity == "OWNER":
        record, result = _audited(ctx, "clean_all_six", ctx.case.test_id, True)
        if result:
            return result
        upload = record["upload"]
    response = _access_request(ctx, operation, upload, session, kwargs)
    if response.status >= 500:
        return _system_failure(f"The {operation.lower()} request", response)
    ctx.mark()
    label = f"{operation.lower()} as {identity.lower()}"
    if response.status != expected:
        problems = [f"{label} returned {response.status}, expected {expected}"]
    elif expected >= 400:
        problems = _rejection(response, expected, None, label)
    else:
        problems = _access_success(ctx, operation, response, shared, upload)
    if expected >= 400 or operation != "DELETE":
        ##  No state change: the owner still reads the unchanged baseline configuration.
        after = _schedule(ctx, shared["upload"], True, what="The owner's schedule read afterwards")
        if after != shared["baseline"]:
            problems.append(f"the shared workbook's schedule changed to {after.model_dump()}")
    return _verdict(f"Access: {label}", problems, f"{label.capitalize()} returned {expected} with no content "
                                                  f"disclosure or state change.")


def _access_success(ctx, operation, response, shared, upload):
    if operation == "DELETE":
        problems = [] if response.body == b"" else ["the 204 carried a body"]
        return problems + _gone(ctx, [("history", f"{_workbook_path(upload)}/history")], True)
    model = NotificationResponse if operation == "NOTIFICATIONS" else ScheduleResponse
    try:
        body = model.model_validate(response.json())
    except ValidationError as problem:
        return [f"the 200 body does not match {model.__name__} ({_schema_problem(problem)})"]
    if model is ScheduleResponse and body != shared["baseline"]:
        return [f"the schedule read {body.model_dump()} differs from the owner's"]
    return []


def _access_clock(case, ctx, identity, expected):
    kwargs = _identity(ctx, CLOCK_IDENTITIES[identity])
    session = ctx.state.get("p5_access_clock") or ctx.state.setdefault("p5_access_clock", _namespace(ctx))
    ##  The creating admin's call is an equal-time advance, so every case can confirm the clock
    ##  still reads EPOCH (a refused identity's advance would have moved it a day).
    when = EPOCH if identity == "CREATING-ADMIN" else _show(_ts(EPOCH) + DAY)
    response = _advance(ctx, session, when, **kwargs)
    if response.status >= 500:
        return _system_failure("The clock request", response)
    ctx.mark()
    label = f"the clock as {identity.lower()}"
    if expected >= 400:
        problems = _rejection(response, expected, None, label)
    elif response.status != expected:
        problems = [f"{label} returned {response.status}, expected {expected}"]
    else:
        problems = []
    problems += _clock_at(ctx, session, _ts(EPOCH), "afterwards")
    return _verdict(f"Access: {label}", problems, f"{label.capitalize()} returned {expected} and the namespace "
                                                  f"clock was unchanged.")


def phase5_access(case, ctx):
    name, expected = case.parameters["case"], case.parameters["expected_status"]
    try:
        if name.startswith("CLOCK-"):
            return _access_clock(case, ctx, name.removeprefix("CLOCK-"), expected)
        for operation in ("SCHEDULE-WRITE", "SCHEDULE-READ", "NOTIFICATIONS", "DELETE"):
            if name.startswith(operation + "-"):
                return _access_workbook(case, ctx, operation, name.removeprefix(operation + "-"), expected)
    except Stop as stop:
        return stop.result
    return CaseResult.error("tester", f"No access check is defined for {name}.")


##  ---- P5-PERFORMANCE-* (test plan; spec §12 bounds) ----

PERFORMANCE = "performance_250000_cells"


def _performance_run(case, ctx, number):
    entry = ctx.fixture_entry(PERFORMANCE)
    if entry is None:
        return CaseResult("skip", f"Not executed: the frozen fixture pack has no {PERFORMANCE} entry.")
    runs = ctx.state.setdefault("p5_performance", {})
    record = runs[number] = {"run": number, "outcome": "not finished", "findings": None}
    ctx.provide()                   # COMPARE discloses every run's outcome, including failed ones
    started = time.monotonic()
    response = ctx.upload(WORKBOOKS, role="userA", fixture=PERFORMANCE)
    record["upload_seconds"] = round(time.monotonic() - started, 3)
    if response.status != 202:
        record["outcome"] = f"upload returned {response.status}"
        return _system_failure("The performance upload", response) if response.status >= 500 else \
            CaseResult.failed(f"The 250,000-cell upload returned {response.status}, expected 202.")
    upload = UploadResponse.model_validate(response.json()).model_dump()
    audit, result = _finished_audit(ctx, upload, f"Performance run {number}'s audit")
    record["end_to_end_seconds"] = round(time.monotonic() - started, 3)
    if result:
        record["outcome"] = result.message
        return result
    if audit.status == "PROCESSING_FAILED":
        record["outcome"] = f"PROCESSING_FAILED ({audit.error.code if audit.error else 'no error body'})"
        return _processing_failure(ctx, f"Performance run {number}'s audit", audit)
    record.update(outcome=audit.status, findings=sorted((f.ruleId, f.worksheet, f.target) for f in audit.findings))
    problems = _audit_problems(audit, upload, entry, ctx.manifest.ruleset_version)
    timing = (f"upload accepted after {record['upload_seconds']:.1f} s (validation), audit observed finished "
              f"{record['end_to_end_seconds']:.1f} s after the upload began (end to end, to the poll interval); queue "
              f"and engine time are not observable over HTTP")
    if problems:
        return CaseResult.failed(f"Performance run {number}: {'; '.join(problems[:4])}. Timing: {timing}.")
    return CaseResult.passed(f"Performance run {number} reached {audit.status} with exactly the expected findings; "
                             f"{timing}.")


def _performance_compare(case, ctx):
    runs = [ctx.state.get("p5_performance", {}).get(n) for n in range(1, 6)]
    if any(r is None for r in runs):
        return CaseResult("skip", "Not executed: not every performance run was attempted.")
    ctx.mark()
    successful = [r for r in runs if r["findings"] is not None]
    outcomes = "; ".join(f"run {r['run']}: {r['outcome']}"
                         + (f" ({r.get('end_to_end_seconds', 0):.1f} s end to end)" if "end_to_end_seconds" in r else "")
                         for r in runs)
    environment = (f"target {ctx.target_url}, target revision {ctx.provenance.get('target_revision') or 'not supplied'}, "
                   f"tester revision {ctx.provenance.get('tester_revision') or 'not supplied'}")
    if not successful:
        return CaseResult.failed(f"No performance run succeeded, so there is nothing to compare. {outcomes}. "
                                 f"Environment: {environment}.")
    if any(r["findings"] != successful[0]["findings"] for r in successful):
        return CaseResult.failed(f"Successful runs reported different issue types or locations. {outcomes}. "
                                 f"Environment: {environment}.")
    return CaseResult.passed(f"All {len(successful)} successful runs reported identical issue types and locations. "
                             f"{outcomes}. Environment: {environment}.")


def phase5_performance(case, ctx):
    name = case.parameters["case"]
    if name == "COMPARE":
        return _performance_compare(case, ctx)
    return _performance_run(case, ctx, int(name.removeprefix("RUN-")))


PHASE5_CHECKS = {"phase5_pending": phase5_pending, "phase5_clock": phase5_clock, "phase5_schedule": phase5_schedule,
                 "phase5_reminder": phase5_reminder, "phase5_delete": phase5_delete, "phase5_fault": phase5_fault,
                 "phase5_access": phase5_access, "phase5_performance": phase5_performance}
