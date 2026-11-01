"""Setup / run / report lifecycle for the instructor testing interface."""

import logging
import threading
import uuid

from pydantic import ValidationError

from .config import target_url_problem
from .errors import TesterError
from .models import SetupResponse, TestEndpointError
from .store import ENDED, Store, now
from .suite.checks import CHECKS
from .suite.plan import PlanError, load_plan, profile_of
from .suite.record import build_record
from .suite.runner import SuiteRun, build_report
from .target import CommunicationError, Deadline, DeadlineExceeded, ResponseTooLarge, TargetClient

log = logging.getLogger("tester")
RESTART_REASON = "the tester restarted while the suite was running"


class TesterService:
    def __init__(self, settings, store: Store, transport=None, checks=None):
        self.settings = settings
        self.store = store
        self.transport = transport
        self.checks = CHECKS if checks is None else checks
        ##  Validate the shipped plan and fixture pack at startup; each setup reloads and freezes them.
        self._load_plan()
        self.recover()

    def _load_plan(self):
        return load_plan(self.settings.manifest_path, self.settings.pod_profile_path, self.settings.expectations_path)

    def _client(self, target_url, plan):
        return TargetClient(target_url, self.settings.target_auth_map_json[target_url],
                            profile_of(plan), self.transport)

    def _owned(self, subject, session_id):
        row = self.store.get(session_id)
        if row is None:
            raise TesterError(404, f"Unknown session {session_id}.")
        if row.owner != subject:
            raise TesterError(403, "This session belongs to another operator.")
        return row

    ##  ---- Startup recovery ----

    def recover(self):
        ##  A previous process stopped mid-setup or mid-run. Setup is never
        ##  replayed; an interrupted run keeps its recorded results.
        for row in self.store.sessions_in("PREPARING"):
            self.store.mark_setup_failed(row.session_id, RESTART_REASON)
            self.store.queue_cleanup(row.target_url, row.session_id)
        for row in self.store.sessions_in("RUNNING"):
            report = build_report(row.session_id, row.target_url, row.plan, row.progress, RESTART_REASON)
            self._finish(row, "ABORTED", report, row.progress, RESTART_REASON)

    def _finish(self, row, state, report, progress, reason):
        ended_at = now()
        record = build_record(row.session_id, row.target_url, row.plan, report, progress, state=state,
                              started_at=row.started_at, ended_at=ended_at, abort_reason=reason)
        self.store.finish(row.session_id, state, report, reason, record, ended_at)
        ##  Fault sessions keep their evidence until the run is recorded, then the next setup cleans them.
        for fault_session in record["fault_session_ids"]:
            self.store.queue_cleanup(row.target_url, fault_session)

    ##  ---- POST /test/setup ----

    def setup(self, subject, target_url):
        problem = target_url_problem(target_url, self.settings.app_env)
        if problem:
            raise TesterError(400, f"Invalid target_url: {problem}.")
        if target_url not in self.settings.allowed_target_urls:
            raise TesterError(400, "target_url is not an approved target system for this tester.")
        try:
            plan = self._load_plan()
        except PlanError as error:
            raise TesterError(500, f"The tester's suite plan is unusable: {error}.")
        except (OSError, ValueError) as error:
            raise TesterError(500, f"The tester's suite plan could not be loaded ({type(error).__name__}).")
        plan["provenance"] = {"tester_revision": self.settings.tester_revision,
                              "target_revision": self.settings.target_revisions_json.get(target_url)}
        profile = profile_of(plan)
        session_id = str(uuid.uuid4())
        self.store.create(session_id, subject, target_url, plan)

        cleanup_ids = self.store.pending_cleanup(target_url) if profile.cleanup.send_failed_setup_ids else []
        setup_body = {"cleanup_session_ids": cleanup_ids} if cleanup_ids else {}
        client = self._client(target_url, plan)
        try:
            response = client.system_setup(session_id, setup_body, Deadline(profile.timing.tester_setup_seconds))
        except (CommunicationError, DeadlineExceeded) as error:
            self._setup_failed(session_id, target_url, 500, f"System setup failed: {error}", "communication")
        except ResponseTooLarge as error:
            self._setup_failed(session_id, target_url, 500, f"System setup failed: {error}", "tester")
        except Exception as error:
            log.exception("system setup call failed")
            self._setup_failed(session_id, target_url, 500,
                               f"System setup failed inside the tester ({type(error).__name__}).", "tester")
        finally:
            client.close()

        if response.status == 201:
            try:
                echoed = SetupResponse.model_validate(response.json()).session_id
            except ValidationError:
                echoed = None
            if echoed != session_id:
                self._setup_failed(session_id, target_url, 500,
                                   "System setup returned 201 without echoing the supplied session_id.", "system")
            self.store.mark_ready(session_id)
            self.store.clear_cleanup(target_url, cleanup_ids)
            return session_id

        ##  Forward a valid system error unchanged: same status, message and source.
        try:
            forwarded = TestEndpointError.model_validate(response.json())
        except ValidationError:
            forwarded = None
        if forwarded is not None and 400 <= response.status <= 599:
            self._setup_failed(session_id, target_url, response.status, forwarded.message, forwarded.source)
        status = response.status if 400 <= response.status <= 599 else 500
        self._setup_failed(session_id, target_url, status,
                           f"System setup returned {response.status} without a valid {{message, source}} body.",
                           "system")

    def _setup_failed(self, session_id, target_url, status, message, source):
        ##  The session never becomes runnable. Partial preparation on the target
        ##  is compensated by asking the next new setup to clean this ID.
        self.store.mark_setup_failed(session_id, message)
        if status >= 500:
            self.store.queue_cleanup(target_url, session_id)
        raise TesterError(status, message, source)

    ##  ---- POST /test/run ----

    def run(self, subject, session_id):
        row = self._owned(subject, session_id)
        if row.state != "READY" or not self.store.claim_run(session_id):
            raise TesterError(409, _not_runnable(row.state))
        outcome = {}
        done = threading.Event()
        worker = threading.Thread(target=self._execute, args=(self.store.get(session_id), outcome, done),
                                  name=f"suite-{session_id}", daemon=True)
        worker.start()
        ##  The suite enforces its own budget; this wait only guards the HTTP call.
        done.wait(profile_of(row.plan).timing.suite_seconds + 30)
        if not done.is_set():
            raise TesterError(500, "The suite did not finish in time; retrieve its report with GET /test/report.")
        if outcome.get("aborted"):
            raise TesterError(500, f"The tester aborted: {outcome['reason']}. "
                                   f"Available results are stored; retrieve them with GET /test/report.")
        return outcome["report"]

    def _execute(self, row, outcome, done):
        ##  Runs in its own thread, so a dropped client connection never cancels the suite.
        ##  If even the abort report cannot be stored, the session stays RUNNING and
        ##  startup recovery aborts it from its saved progress.
        try:
            self._run_and_store(row, outcome)
        except Exception as error:
            log.exception("could not finish the suite")
            outcome.update(aborted=True, reason=f"the report could not be stored ({type(error).__name__})")
        finally:
            done.set()

    def _run_and_store(self, row, outcome):
        profile = profile_of(row.plan)
        client = self._client(row.target_url, row.plan)
        suite = SuiteRun(row.session_id, row.target_url, row.plan, client, self.checks,
                         Deadline(profile.timing.suite_seconds),
                         lambda progress: self.store.save_progress(row.session_id, progress))
        try:
            aborted = suite.execute()
            reason = suite.abort_reason
        except Exception as error:
            log.exception("suite execution failed")
            aborted, reason = True, f"an internal tester failure ({type(error).__name__})"
        finally:
            client.close()
        progress = suite.progress()
        report = build_report(row.session_id, row.target_url, row.plan, progress, reason if aborted else None)
        self._finish(row, "ABORTED" if aborted else "COMPLETE", report, progress, reason if aborted else None)
        outcome.update(report=report, aborted=aborted, reason=reason)

    ##  ---- GET /test/report ----

    def report(self, subject, session_id):
        row = self._owned(subject, session_id)
        if row.state not in ENDED:
            raise TesterError(409, _no_report(row.state))
        self.store.record_retrieval(session_id)
        return row.report


def _not_runnable(state):
    return {
        "PREPARING": "Setup is still in progress for this session.",
        "SETUP_FAILED": "Setup failed for this session; create a new session.",
        "RUNNING": "This session's suite is already running; retrieve its report with GET /test/report.",
    }.get(state, "This session's suite has already run; create a new session to run it again.")


def _no_report(state):
    if state == "SETUP_FAILED":
        return "Setup failed for this session, so it has no suite report."
    return "The suite has not ended; retry the report later."
