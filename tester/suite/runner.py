"""Runs the frozen plan in manifest order and builds the suite report.

Each case gets exactly one result. A prerequisite is met when that earlier
case passed or declared its resource usable with ctx.provide(): a seeded
audit with wrong findings is still a valid determinism baseline. An exhausted
suite budget aborts the run: the interrupted case is an error with source
"tester" and every later case is skipped.
"""

import json
import time
from dataclasses import dataclass

from ..models import CoverageMeasure, SuiteReport
from ..target import CommunicationError, Deadline, DeadlineExceeded, ResponseTooLarge
from .plan import manifest_of, profile_of

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

    def provide(self):
        ##  This case produced a usable resource for later cases, even if it failed.
        self.provided = True

    def record_code_coverage(self, measure):
        self._run.code = CoverageMeasure.model_validate(measure).model_dump()

    def call(self, method, path, *, role, budget=None, session=True, **kwargs):
        ##  A project API call: user role token plus the session header (per pod profile).
        timing = self.profile.timing
        if budget is None:
            budget = timing.upload_seconds if method == "POST" else timing.get_seconds
        send_session = session and (path != "/api/v1/health" or self.profile.session_transport.send_on_health)
        return self.target.request(method, path, budget=budget, deadline=self.deadline, role=role,
                                   session_id=self.session_id if send_session else None, **kwargs)

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
        self.code = None
        self.abort_reason = None

    def progress(self):
        return {"results": self.results, "components": sorted(self.components),
                "acceptance": sorted(self.acceptance), "code": self.code}

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
    report = {
        "session_id": session_id,
        "target_url": target_url,
        "results": results,
        "coverage": {
            "code": code,
            "component": {
                "covered": len(components), "total": len(manifest.components),
                "basis": f"Pod components {', '.join(manifest.components)} (Team 9 profile, pending pod "
                         f"confirmation); counted when a qualifying assertion executed, pass or fail.",
            },
            "system": {
                "covered": len(acceptance), "total": len(manifest.acceptance),
                "basis": f"Phase 3 portions of {', '.join(manifest.acceptance)} (Team 9 profile, pending pod "
                         f"confirmation); counted when a qualifying assertion executed, pass or fail.",
            },
        },
    }
    SuiteReport.model_validate(report)
    if [r["test_id"] for r in results] != [case.test_id for case in manifest.tests]:
        raise ValueError("report results do not cover every planned test exactly once, in order")
    return json.dumps(report, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
