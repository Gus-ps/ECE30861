"""Runs the frozen plan in manifest order and builds the suite report.

Each case gets exactly one result. A prerequisite is met when that earlier
case passed or declared its resource usable with ctx.provide(): a seeded
audit with wrong findings is still a valid determinism baseline. An exhausted
suite budget aborts the run: the interrupted case is an error with source
"tester" and every later case is skipped.
"""

import json
import time
import uuid
from dataclasses import dataclass

from ..models import CoverageMeasure, SuiteReport
from ..target import CommunicationError, Deadline, DeadlineExceeded, ResponseTooLarge
from .plan import PlanError, fixture_bytes, manifest_of, profile_of
from .transfer import upload_files

NOT_RETRIEVED = {"covered": None, "total": None,
                 "basis": "Not measured: the target's code-coverage report was not retrieved in this run."}


@dataclass(frozen=True)
class CaseResult:
    outcome: str
    message: str
    source: str | None = None

    @classmethod
    def passed(cls, message):
        return cls("pass", message)

    @classmethod
    def failed(cls, message):
        return cls("fail", message)

    @classmethod
    def error(cls, source, message):
        return cls("error", message, source)


class CaseContext:
    ##  What a check function may use.
    def __init__(self, case, run):
        self.case = case
        self._run = run
        self.session_id = run.session_id
        self.target = run.target
        self.deadline = run.deadline
        self.manifest = run.manifest
        self.profile = run.profile
        self.state = run.state
        self.provided = False

    def mark(self, components=None, acceptance=None):
        ##  Records that a qualifying assertion executed, pass or fail. With no
        ##  arguments the case earns everything it declares; a check that only
        ##  reached some assertions names just those (a subset of its declaration).
        components = self.case.components if components is None else components
        acceptance = self.case.acceptance if acceptance is None else acceptance
        undeclared = (set(components) - set(self.case.components)) | (set(acceptance) - set(self.case.acceptance))
        if undeclared:
            raise ValueError(f"{self.case.test_id} does not declare {', '.join(sorted(undeclared))}")
        self._run.components.update(components)
        self._run.acceptance.update(acceptance)
        for catalog, ids in (("components", components), ("acceptance", acceptance)):
            for item in ids:
                cases = self._run.evidence[catalog].setdefault(item, [])
                if self.case.test_id not in cases:
                    cases.append(self.case.test_id)

    def fixture(self, key):
        ##  (bytes, expectations entry) for a fixture in the session's frozen pack.
        return fixture_bytes(self._run.plan, key), self._run.plan["fixtures"]["entries"][key]

    def fixture_entry(self, key):
        ##  The frozen expectations entry, or None when no pack (or no such entry) was frozen at setup.
        return (self._run.plan.get("fixtures") or {}).get("entries", {}).get(key)

    def provide(self):
        ##  This case produced a usable resource for later cases, even if it failed.
        self.provided = True

    def record_fault_session(self, session_id):
        ##  A separate system session this case created (or may have created); it goes into the
        ##  run record and is queued for cleanup once the run is stored. Its coverage is never
        ##  added to the main session's.
        if session_id not in self._run.fault_sessions:
            self._run.fault_sessions.append(session_id)

    def record_code_coverage(self, measure):
        self._run.code = CoverageMeasure.model_validate(measure).model_dump()

    def call(self, method, path, *, role, budget=None, session=True, **kwargs):
        ##  A project API call: user role token plus the session header (per pod profile).
        ##  session=False omits the header; a string sends that session ID instead of this one.
        timing = self.profile.timing
        if budget is None:
            budget = timing.upload_seconds if method == "POST" else timing.get_seconds
        send_session = session and (path != "/api/v1/health" or self.profile.session_transport.send_on_health)
        session_id = (session if isinstance(session, str) else self.session_id) if send_session else None
        return self.target.request(method, path, budget=budget, deadline=self.deadline, role=role,
                                   session_id=session_id, **kwargs)

    def upload(self, path, *, role, fixture=None, name=None, content=None, **kwargs):
        ##  POST a one-part multipart upload: a frozen fixture (sent under its upload_name)
        ##  or explicit name and bytes. Uploads are never retried.
        if fixture is not None:
            content, entry = self.fixture(fixture)
            name = entry["upload_name"] if name is None else name
        return self.call("POST", path, role=role, files=upload_files(name, content), **kwargs)

    def download(self, path, *, role, **kwargs):
        ##  GET a workbook or report download under the binary size cap and download budget.
        budget = self.profile.timing.download_seconds or self.profile.timing.get_seconds
        return self.call("GET", path, role=role, budget=budget, binary=True, **kwargs)

    def new_idempotency_key(self):
        ##  A fresh key for one remediation request; a replay case reuses it on purpose.
        return f"tester-{uuid.uuid4().hex}"

    def poll(self, fetch, finished, budget=None):
        ##  Calls fetch() until finished(value) or the poll budget runs out.
        ##  Returns (last value, finished?). Running out of the *suite* budget
        ##  raises DeadlineExceeded and aborts the run instead.
        timing = self.profile.timing
        limit = Deadline(timing.audit_poll_seconds if budget is None else budget)
        while True:
            value = fetch()
            if finished(value):
                return value, True
            pause = min(timing.poll_interval_seconds, limit.remaining())
            if pause <= 0:
                return value, False
            if pause > self.deadline.remaining():
                raise DeadlineExceeded("The suite time budget ran out while polling.")
            time.sleep(pause)


class SuiteRun:
    def __init__(self, session_id, target_url, plan, target, checks, deadline, on_progress):
        self.session_id = session_id
        self.target_url = target_url
        self.plan = plan
        self.manifest = manifest_of(plan)
        self.profile = profile_of(plan)
        self.target = target
        self.checks = checks
        self.deadline = deadline
        self.on_progress = on_progress
        self.state = {}
        self.results = []
        self.components = set()
        self.acceptance = set()
        ##  catalog item -> test IDs whose qualifying assertion earned it, in run order
        self.evidence = {"components": {}, "acceptance": {}}
        self.code = None
        self.fault_sessions = []
        self.abort_reason = None

    def progress(self):
        return {"results": self.results, "components": sorted(self.components),
                "acceptance": sorted(self.acceptance), "evidence": self.evidence, "code": self.code,
                "fault_sessions": self.fault_sessions}

    def execute(self):
        provided = set()
        for case in self.manifest.tests:
            if self.abort_reason is not None:
                result = CaseResult("skip", "Not executed: the suite aborted before this test.")
            else:
                result, usable = self._run_case(case, provided)
                if usable:
                    provided.add(case.test_id)
            self.results.append(_result_dict(case.test_id, result))
            self.on_progress(self.progress())
        return self.abort_reason is not None

    def _run_case(self, case, provided):
        ##  Returns (result, whether later cases may use this case's resource).
        unmet = [p for p in case.prerequisites if p not in provided]
        if unmet:
            return CaseResult("skip", f"Not executed: prerequisite {', '.join(unmet)} "
                                      f"did not produce a usable resource."), False
        check = self.checks.get(case.check)
        if check is None:
            return CaseResult("skip", f"Not executed: check '{case.check}' is not implemented "
                                      f"in this tester build."), False
        ctx = CaseContext(case, self)
        result = self._guarded(case, check, ctx)
        return result, result.outcome == "pass" or (ctx.provided and result.outcome == "fail")

    def _guarded(self, case, check, ctx):
        try:
            self.deadline.check()
            return check(case, ctx)
        except DeadlineExceeded:
            self.abort_reason = f"the suite time budget ran out during {case.test_id}"
            return CaseResult.error("tester", "The tester aborted: the suite time budget ran out during this test.")
        except CommunicationError as error:
            return CaseResult.error("communication", f"{error} No response was available to evaluate.")
        except ResponseTooLarge as error:
            return CaseResult.error("tester", f"{error} The tester's response-size limit prevented evaluation.")
        except PlanError as error:
            return CaseResult.error("tester", f"The tester could not use its frozen plan: {error}.")
        except Exception as error:
            return CaseResult.error("tester", f"The tester failed while running this test ({type(error).__name__}).")


def _result_dict(test_id, result):
    entry = {"test_id": test_id, "outcome": result.outcome, "message": result.message}
    if result.outcome == "error":
        entry["source"] = result.source
    return entry


def build_report(session_id, target_url, plan, progress, interrupted_reason=None):
    ##  Report from recorded progress. With interrupted_reason, the first case
    ##  without a result becomes a tester error and the rest are skipped.
    manifest = manifest_of(plan)
    results = list((progress or {}).get("results", []))
    if interrupted_reason is not None:
        for offset, case in enumerate(manifest.tests[len(results):]):
            if offset == 0:
                results.append({"test_id": case.test_id, "outcome": "error", "source": "tester",
                                "message": f"The tester aborted during this test: {interrupted_reason}."})
            else:
                results.append({"test_id": case.test_id, "outcome": "skip",
                                "message": "Not executed: the suite aborted before this test."})
    components = set((progress or {}).get("components", []))
    acceptance = set((progress or {}).get("acceptance", []))
    code = (progress or {}).get("code") or NOT_RETRIEVED
    catalogs = profile_of(plan).coverage
    report = {
        "session_id": session_id,
        "target_url": target_url,
        "results": results,
        "coverage": {
            "code": code,
            "component": {"covered": len(components), "total": len(manifest.components),
                          "basis": catalogs.component_basis},
            "system": {"covered": len(acceptance), "total": len(manifest.acceptance),
                       "basis": catalogs.system_basis},
        },
    }
    SuiteReport.model_validate(report)
    if [r["test_id"] for r in results] != [case.test_id for case in manifest.tests]:
        raise ValueError("report results do not cover every planned test exactly once, in order")
    return json.dumps(report, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
