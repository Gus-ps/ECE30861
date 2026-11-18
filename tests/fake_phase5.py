"""Phase 5 routes of the test fake (shared specification 3.0.0): schedules (operations 11 and G),
notifications (12), the isolated test clock (13), owner deletion (14), and the seven one-shot
setup faults. Test-only; not a reference implementation.

Phase 5 behaviour is opt-in (FakeProject.phase5 = True): only then do new sessions get a clock,
so Phase 3 and 4 runs keep real timestamps. Session preparation (validate_setup / prepare) is
shared by the pytest FakeSystem and the rehearsal stand-in so the two cannot drift.
"""

import json
import re
import uuid
from datetime import date, datetime, timedelta, timezone

DEFAULT_CLOCK = datetime(2027, 1, 1, tzinfo=timezone.utc)
FAULT_KEYS = ("audit_failures", "remediation_failures", "report_failures", "storage_failures",
              "scheduled_audit_failures", "notification_failures", "deletion_failures")
REMINDER_DAYS = [90, 30, 7]
TIMESTAMP = re.compile(r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(\.\d{1,6})?Z$")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
INJECTED = {   # spec 3.0.0 §11: code, fixed message and details stage per injected failure
    "remediation": ("TEST_REMEDIATION_FAILURE", "Remediation failure requested by the isolated test session."),
    "report": ("TEST_REPORT_FAILURE", "Report failure requested by the isolated test session."),
    "scheduled_audit": ("TEST_SCHEDULED_AUDIT_FAILURE", "Scheduled audit failure requested by the isolated test session."),
}
REMINDER_MESSAGE = ("This stored workbook version has unresolved accessibility findings or no completed successful "
                    "audit. External workbook changes require a new upload.")
FAILED_MESSAGE = "Reminder recording failed in the isolated test session."
MAX_CLOCK_AUDITS, MAX_CLOCK_REMINDERS = 1000, 3000


def _error(status, code, message):
    return status, {"code": code, "message": message, "requestId": f"req-{uuid.uuid4().hex[:12]}", "details": {}}


def injected(stage, request_id=None):
    code, message = INJECTED[stage]
    return {"code": code, "message": message, "requestId": request_id or f"job-{uuid.uuid4().hex[:12]}",
            "details": {"stage": stage, "testOnly": True}}


def parse_timestamp(text):
    ##  UTC RFC 3339 ending in Z with at most six fractional digits, else None (spec 3.0.0 §4).
    if not isinstance(text, str):
        return None
    match = TIMESTAMP.match(text)
    if not match:
        return None
    try:
        return datetime.fromisoformat(text[:-1]).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def show(moment):
    text = moment.strftime("%Y-%m-%dT%H:%M:%S")
    return text + (f".{moment.microsecond:06d}".rstrip("0") if moment.microsecond else "") + "Z"


def parse_date(text):
    if not isinstance(text, str) or not DATE.match(text):
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def strict_json(body):
    ##  A JSON object with no duplicate keys, non-finite numbers or decimal-written numbers
    ##  (1.0 is not an integer here), or None (spec 3.0.0 §4).
    class Decimal(float):
        pass

    def pairs(items):
        keys = [k for k, _ in items]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate key")
        return dict(items)
    try:
        value = json.loads(body or b"", object_pairs_hook=pairs, parse_float=Decimal,
                           parse_constant=lambda name: (_ for _ in ()).throw(ValueError(name)))
    except (ValueError, UnicodeDecodeError):
        return None
    return value if isinstance(value, dict) else None


def is_interval(value):
    return type(value) is int and 1 <= value <= 90


def validate_setup(setup, fault_switch=True, clock_switch=True):
    ##  (status, message) for a refused system setup body, or None (spec 3.0.0 §9, §11, §13).
    if not isinstance(setup, dict) or set(setup) - {"cleanup_session_ids", "faults", "clock"}:
        return 400, "Unknown setup keys."
    if "faults" in setup:
        faults = setup["faults"]
        if not isinstance(faults, dict) or not faults or set(faults) - set(FAULT_KEYS) \
                or any(type(v) is not int or v != 1 for v in faults.values()):
            return 400, "faults must name one or more known controls, each exactly 1."
        if {"audit_failures", "report_failures"} <= set(faults):
            return 400, "audit_failures and report_failures cannot be combined."
        if not fault_switch:
            return 403, "The test fault switch is disabled on this deployment."
    if "clock" in setup:
        clock = setup["clock"]
        if not isinstance(clock, dict) or set(clock) != {"currentTime"} or parse_timestamp(clock["currentTime"]) is None:
            return 400, "clock must be exactly {\"currentTime\": <UTC timestamp>}."
        if not clock_switch:
            return 403, "The test clock capability is disabled on this deployment."
    return None


class Phase5Routes:
    ##  Mixed into FakeProject; relies on its versions/audits stores, _version, _audit_status,
    ##  _new_audit, outputs, remediations and sessions.

    def _phase5_state(self):
        self.phase5 = False
        self.clocks = {}             # session -> effective time (Phase 5 sessions only)
        self.session_admins = {}     # session -> creating test-admin
        self.faults = {}             # session -> armed one-shot fault keys (other than audit_failures)
        self.schedules = {}          # workbookId -> schedule state
        self.notifications = []      # notification records in durable creation order
        self.considered = set()      # (workbookId, deadline, offset) reminder keys already considered
        self.sequence = 0            # durable creation sequence for versions and notifications
        self.remediation_polls = 0   # remediation reads answered REMEDIATING before the result

    def prepare(self, session_id, setup, admin):
        ##  Applies a validated setup to a fresh session.
        self.cleanup(setup.get("cleanup_session_ids", []))
        self.sessions.add(session_id)
        self.session_admins[session_id] = admin
        faults = set(setup.get("faults") or {})
        if "audit_failures" in faults:
            self.armed.add(session_id)
        self.faults[session_id] = faults - {"audit_failures"}
        if self.phase5:
            clock = setup.get("clock")
            self.clocks[session_id] = parse_timestamp(clock["currentTime"]) if clock else DEFAULT_CLOCK

    def _cleanup_phase5(self, session_id):
        self.clocks.pop(session_id, None)
        self.faults.pop(session_id, None)
        self.session_admins.pop(session_id, None)
        for workbook_id in [w for w, s in self.schedules.items() if s["session"] == session_id]:
            self._forget_workbook(workbook_id)

    def effective_now(self, session):
        return self.clocks.get(session) or datetime.now(timezone.utc)

    def _take_fault(self, session, key):
        armed = self.faults.get(session, set())
        if key in armed:
            armed.discard(key)
            return True
        return False

    ##  ---- Workbook lookup ----

    def _workbook(self, subject, workbook_id, session, write=False):
        ##  (versions in creation order, None) or (None, error reply). Spec 3.0.0 §4 order:
        ##  resolve in the namespace (404), then authorize (403).
        versions = sorted((v for v in self.versions.values()
                           if v["workbookId"] == workbook_id and v["session"] == session), key=lambda v: v["sequence"])
        if not versions:
            return None, _error(404, "NOT_FOUND", "No such workbook.")
        owner = versions[0]["owner"]
        allowed = subject == owner if write else self._readable(subject, owner)
        if not allowed:
            return None, _error(403, "FORBIDDEN", "You cannot access this workbook.")
        return versions, None

    def _schedule(self, workbook_id, session):
        return self.schedules.setdefault(workbook_id, {
            "session": session, "configured": False, "enabled": False, "intervalDays": None,
            "complianceDeadline": None, "nextAuditAt": None, "deadlineSetAt": None})

    def _schedule_response(self, workbook_id, versions):
        state = self.schedules.get(workbook_id) or {"enabled": False, "intervalDays": None,
                                                   "complianceDeadline": None, "nextAuditAt": None}
        newest = self._newest(workbook_id, versions[0]["session"])     # committed versions only
        return {"workbookId": workbook_id, "enabled": state["enabled"], "intervalDays": state["intervalDays"],
                "complianceDeadline": state["complianceDeadline"], "versionId": newest["versionId"],
                "nextAuditAt": show(state["nextAuditAt"]) if state["nextAuditAt"] else None,
                "reminderDays": list(REMINDER_DAYS)}

    ##  ---- Operation G and 11: schedules (spec 3.0.0 §6) ----

    def schedule_get(self, subject, workbook_id, session=None, **_):
        versions, problem = self._workbook(subject, workbook_id, session)
        return problem or (200, self._schedule_response(workbook_id, versions))

    def schedule_put(self, subject, workbook_id, body=b"", session=None, **_):
        versions, problem = self._workbook(subject, workbook_id, session, write=True)
        if problem:
            return problem
        request = strict_json(body)
        if request is None or set(request) - {"enabled", "intervalDays", "complianceDeadline"} \
                or type(request.get("enabled")) is not bool:
            return _error(400, "INVALID_REQUEST", "A schedule needs boolean enabled and only known fields.")
        enabled, interval = request["enabled"], request.get("intervalDays")
        if enabled and not is_interval(interval):
            return _error(400, "INVALID_REQUEST", "An enabled schedule needs an integer intervalDays from 1 to 90.")
        if not enabled and interval is not None and not is_interval(interval):
            return _error(400, "INVALID_REQUEST", "intervalDays must be null or an integer from 1 to 90.")
        deadline = request.get("complianceDeadline")
        if deadline is not None and parse_date(deadline) is None:
            return _error(400, "INVALID_REQUEST", "complianceDeadline must be a real YYYY-MM-DD date or null.")
        now, state = self.effective_now(session), self._schedule(workbook_id, session)
        if enabled:
            try:
                due = now + timedelta(days=interval)
            except OverflowError:
                due = None
            if due is None or due.year > 9999:
                return _error(400, "TIME_RANGE_EXCEEDED", "The next due time is outside years 0001 to 9999.")
        changed = not state["configured"] or (enabled, interval) != (state["enabled"], state["intervalDays"])
        if changed:
            state["nextAuditAt"] = now + timedelta(days=interval) if enabled else None
        if deadline != state["complianceDeadline"]:
            state["deadlineSetAt"] = now if deadline else None
        ##  Full replacement: an absent interval or deadline normalizes to null.
        state.update(configured=True, enabled=enabled, intervalDays=interval, complianceDeadline=deadline)
        return 200, self._schedule_response(workbook_id, versions)

    ##  ---- Operation 12: notifications (spec 3.0.0 §8) ----

    def notifications_get(self, subject, workbook_id, session=None, **_):
        _versions, problem = self._workbook(subject, workbook_id, session)
        if problem:
            return problem
        records = sorted((n for n in self.notifications if n["workbookId"] == workbook_id),
                         key=lambda n: (n["scheduledFor"], n["sequence"]))
        return 200, {"notifications": [{k: n[k] for k in ("notificationId", "type", "workbookId", "versionId",
                                                          "scheduledFor", "status", "message")} for n in records]}

    ##  ---- Operation 13: isolated clock (spec 3.0.0 §9) ----

    def clock(self, token, headers, body):
        from .fake_project import ADMINS, USERS
        session = headers.get("x-test-session")
        if not self.phase5 or not session:
            return _error(404, "TEST_CLOCK_DISABLED", "The test clock is not available here.")
        if token not in ADMINS and token not in USERS:
            return _error(401, "UNAUTHORIZED", "A test-admin bearer token is required.")
        if token in USERS:
            return _error(403, "FORBIDDEN", "Only the creating test-admin may advance this clock.")
        if session not in self.sessions:
            return _error(400, "INVALID_TEST_SESSION", "Unknown or cleaned test session.")
        if self.session_admins.get(session) != ADMINS[token]:
            return _error(403, "FORBIDDEN", "Only the creating test-admin may advance this clock.")
        if session not in self.clocks:
            return _error(409, "LEGACY_SESSION_CLOCK", "This session has no Phase 5 clock; prepare a fresh one.")
        request = strict_json(body)
        target = parse_timestamp((request or {}).get("currentTime"))
        if request is None or set(request) != {"currentTime"} or target is None:
            return _error(400, "INVALID_REQUEST", "Send exactly {\"currentTime\": <UTC timestamp>}.")
        if target < self.clocks[session]:
            return _error(400, "CLOCK_REWIND", "The clock cannot move backward.")
        return self._advance(session, target)

    def _running_remediations(self):
        return [r for r in self.remediations.values() if r.get("polls_left", 0) > 0]

    def _newest(self, workbook_id, session):
        ##  The newest committed version; a still-running remediation's output is not published yet.
        unpublished = {r["response"]["outputVersionId"] for r in self._running_remediations()}
        versions = [v for v in self.versions.values() if v["workbookId"] == workbook_id and v["session"] == session
                    and v["versionId"] not in unpublished]
        return max(versions, key=lambda v: v["sequence"]) if versions else None

    def _busy(self, version):
        if version["audits"] and self._audit_status(self.audits[version["audits"][-1]]) == "PROCESSING":
            return True
        return any(r["response"]["sourceVersionId"] == version["versionId"] for r in self._running_remediations())

    def _eligible(self, version):
        ##  Spec 3.0.0 §8: no audit, PROCESSING, PROCESSING_FAILED or any finding is eligible;
        ##  only a successful terminal audit with no findings suppresses the reminder.
        if version is None or not version["audits"]:
            return True
        latest = self.audits[version["audits"][-1]]
        status = self._audit_status(latest)
        return status in ("PROCESSING", "PROCESSING_FAILED") or bool(latest["result"]["findings"])

    def _advance(self, session, target):
        schedules = {w: s for w, s in self.schedules.items() if s["session"] == session}
        due = sorted(((s["nextAuditAt"], w) for w, s in schedules.items()
                      if s["enabled"] and s["nextAuditAt"] and s["nextAuditAt"] <= target))
        reminders = []
        for workbook_id, state in schedules.items():
            deadline = parse_date(state["complianceDeadline"]) if state["complianceDeadline"] else None
            if deadline is None:
                continue
            midnight = datetime(deadline.year, deadline.month, deadline.day, tzinfo=timezone.utc)
            for offset in REMINDER_DAYS:
                instant = midnight - timedelta(days=offset)
                key = (workbook_id, state["complianceDeadline"], offset)
                if key not in self.considered and state["deadlineSetAt"] <= instant <= target:
                    reminders.append((instant, workbook_id, -offset, key))
        reminders.sort()
        if len(due) > MAX_CLOCK_AUDITS or len(reminders) > MAX_CLOCK_REMINDERS:
            return _error(409, "CLOCK_WORK_LIMIT", "Too much due work for one advance; use smaller steps.")
        ##  Busy check first, so a refusal changes no time, events or cadence.
        for _due, workbook_id in due:
            if self._busy(self._newest(workbook_id, session)):
                return _error(409, "ACTIVE_OPERATION", "A due version has active work; retry after it finishes.")
        ##  Reminder eligibility comes from the snapshot before this tick's audits are dispatched.
        snapshot = {w: self._eligible(self._newest(w, session)) for _i, w, _o, _k in reminders}
        newest = {w: self._newest(w, session)["versionId"] for _i, w, _o, _k in reminders}
        self.clocks[session] = target
        audits = []
        for old_due, workbook_id in due:
            state, interval = schedules[workbook_id], timedelta(days=schedules[workbook_id]["intervalDays"])
            audits.append(self._new_audit(self._newest(workbook_id, session), session, kind="scheduled"))
            state["nextAuditAt"] = old_due + ((target - old_due) // interval + 1) * interval
        notes = []
        for instant, workbook_id, _offset, key in reminders:
            self.considered.add(key)
            if not snapshot[workbook_id]:
                continue          # considered clean: never emitted later for this key
            failed = self._take_fault(session, "notification_failures")
            self.sequence += 1
            note = {"notificationId": f"note-{uuid.uuid4().hex[:10]}", "type": "COMPLIANCE_DEADLINE_REMINDER",
                    "workbookId": workbook_id, "versionId": newest[workbook_id], "scheduledFor": show(instant),
                    "status": "FAILED" if failed else "DELIVERED", "message": FAILED_MESSAGE if failed else REMINDER_MESSAGE,
                    "sequence": self.sequence, "session": session}
            self.notifications.append(note)
            notes.append(note["notificationId"])
        return 200, {"currentTime": show(target), "triggeredAudits": audits, "triggeredNotifications": notes}

    ##  ---- Operation 14: owner deletion (spec 3.0.0 §10) ----

    def delete_workbook(self, subject, workbook_id, session=None, **_):
        versions, problem = self._workbook(subject, workbook_id, session, write=True)
        if problem:
            return problem
        if any(self._busy(v) for v in versions):
            return _error(409, "ACTIVE_OPERATION", "An audit or remediation is still running for this workbook.")
        if self._take_fault(session, "deletion_failures"):
            reply = _error(500, "TEST_DELETION_FAILURE", "Deletion failure requested by the isolated test session.")
            reply[1]["details"] = {"stage": "deletion", "testOnly": True}
            return reply
        self._forget_workbook(workbook_id)
        return 204, b""

    def _forget_workbook(self, workbook_id):
        for version_id in [v for v, record in self.versions.items() if record["workbookId"] == workbook_id]:
            for audit_id in self.versions.pop(version_id)["audits"]:
                self.audits.pop(audit_id, None)
            for output_id in [o for o, record in self.outputs.items() if record["versionId"] == version_id]:
                self.outputs.pop(output_id)
        ##  A remediation whose source version is gone belonged to this workbook.
        for remediation_id in [r for r, record in self.remediations.items()
                               if record["response"]["sourceVersionId"] not in self.versions]:
            self.remediations.pop(remediation_id)
        self.schedules.pop(workbook_id, None)
        self.notifications = [n for n in self.notifications if n["workbookId"] != workbook_id]
        self.considered = {key for key in self.considered if key[0] != workbook_id}
