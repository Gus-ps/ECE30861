"""Check functions, keyed by the manifest's `check` name.

Each takes (case, ctx) and returns a CaseResult. Call ctx.mark() once the
case's qualifying assertion is actually evaluated, pass or fail.

The intake checks send workbooks the tester generates (suite/workbooks.py),
not reviewed fixtures, so they need no fixture pack. The fixture checks upload
files from the session's frozen pack and skip without one; audits are compared
with the pack's hand-authored expectations, never with another implementation.
"""

import hashlib
import uuid
from collections import Counter
from datetime import datetime

from pydantic import ValidationError

from ..models import (AuditReport, AuditResponse, HealthResponse, HistoryResponse, ProjectError, ReauditResponse,
                      SetupResponse, SystemReport, TestEndpointError, UploadResponse, VersionResponse)
from .identity import finding_id
from .runner import CaseResult
from .transfer import XLSX
from .workbooks import CSV, LEGACY_XLS, workbook

HEALTH = "/api/v1/health"
WORKBOOKS = "/api/v1/workbooks"
TOO_LARGE = 413
INVALID_WORKBOOK = 422


def _schema_problem(error: ValidationError):
    first = error.errors()[0]
    where = ".".join(str(p) for p in first["loc"]) or "body"
    return f"{where}: {first['msg']}"


def _system_failure(name, response):
    return CaseResult.error("system", f"{name} returned an unexpected {response.status} internal failure.")


def _rejected(ctx, response, what, expected, code=None):
    ##  An expected project-API rejection: the status, a strict ProjectError body (so no
    ##  accepted identifiers), and the exact code only where the contract fixes one.
    if response.status >= 500:
        return _system_failure(what, response)
    ctx.mark()
    if response.status != expected:
        accepted = ", accepting the upload" if response.status == 202 else ""
        return CaseResult.failed(f"Expected {expected} for {what}; received {response.status}{accepted}.")
    try:
        error = ProjectError.model_validate(response.json())
    except ValidationError as problem:
        return CaseResult.failed(f"{expected} body does not match ProjectError ({_schema_problem(problem)}).")
    if code is not None and error.code != code:
        return CaseResult.failed(f"{what} returned {expected} with code {error.code}, expected {code}.")
    named = f" code {code}" if code is not None else ""
    return CaseResult.passed(f"{what} returned {expected} with a valid project error{named}.")


def _accepted(ctx, response, what, mark=True):
    ##  An expected 202: a strict UploadResponse with three distinct PROCESSING identifiers.
    ##  mark=False when the upload only prepares a resource for another assertion.
    if response.status >= 500:
        return _system_failure(what, response)
    if mark:
        ctx.mark()
    if response.status != 202:
        return CaseResult.failed(f"Expected 202 for {what}; received {response.status}.")
    try:
        upload = UploadResponse.model_validate(response.json())
    except ValidationError as problem:
        return CaseResult.failed(f"202 body does not match UploadResponse ({_schema_problem(problem)}).")
    if len({upload.workbookId, upload.versionId, upload.auditId}) != 3:
        return CaseResult.failed(f"{what} was accepted, but its workbook, version and audit IDs are not distinct.")
    return CaseResult.passed(f"{what} was accepted (202) with three distinct PROCESSING identifiers.")


def _upload(ctx, name, content, role="userA", **kwargs):
    return ctx.upload(WORKBOOKS, role=role, name=name, content=content, **kwargs)


##  ---- Health and authentication ----

def health(case, ctx):
    ##  P3-HEALTH: public health returns HealthResponse with the manifest's ruleset.
    response = ctx.call("GET", HEALTH, role=None)
    if response.status >= 500:
        return _system_failure("Health", response)
    ctx.mark()
    if response.status != 200:
        return CaseResult.failed(f"Expected 200 from health; received {response.status}.")
    try:
        body = HealthResponse.model_validate(response.json())
    except ValidationError as problem:
        return CaseResult.failed(f"Health body does not match HealthResponse ({_schema_problem(problem)}).")
    expected = ctx.manifest.ruleset_version
    if body.rulesetVersion != expected:
        return CaseResult.failed(f"Health reports ruleset {body.rulesetVersion}, expected {expected}.")
    return CaseResult.passed(f"Health returned AVAILABLE, API 1.0, ruleset {expected}.")


def upload_without_token(case, ctx):
    ##  P3-AUTH-UPLOAD: a valid workbook with no bearer token is 401 with no accepted IDs.
    response = _upload(ctx, "intake.xlsx", workbook(), role=None)
    return _rejected(ctx, response, "An upload without a bearer token", 401)


def upload_invalid_token(case, ctx):
    ##  P3-AUTH-UPLOAD-INVALID: an unknown bearer token is 401.
    response = _upload(ctx, "intake.xlsx", workbook(), role=None, bearer=f"tester-invalid-{uuid.uuid4().hex}")
    return _rejected(ctx, response, "An upload with an unknown bearer token", 401)


##  ---- Upload intake ----

def upload_missing_file(case, ctx):
    ##  P3-INPUT-MISSING-FILE: a multipart body whose only part is not named `file` is 400.
    response = ctx.call("POST", WORKBOOKS, role="userA",
                        files={"attachment": ("intake.xlsx", workbook(), XLSX)})
    return _rejected(ctx, response, "A multipart upload without the file field", 400)


def _unsupported(ctx, name, content, what):
    return _rejected(ctx, _upload(ctx, name, content), what, ctx.profile.unsupported_types.status)


def upload_csv(case, ctx):
    ##  P3-INPUT-CSV
    return _unsupported(ctx, "totals.csv", CSV, "A CSV upload")


def upload_no_extension(case, ctx):
    ##  P3-INPUT-MISSING-EXTENSION: a valid workbook named without an extension.
    return _unsupported(ctx, "intake", workbook(), "A valid workbook named without an extension")


def upload_xls(case, ctx):
    ##  P3-INPUT-XLS: a legacy compound-document file named .xls.
    return _unsupported(ctx, "legacy.xls", LEGACY_XLS, "A legacy .xls upload")


def upload_xlsm(case, ctx):
    ##  P3-INPUT-XLSM: a named .xlsm is 422 with the one exactly compared rejection code.
    policy = ctx.profile.xlsm
    response = _upload(ctx, "macros.xlsm", workbook())
    return _rejected(ctx, response, "A named .xlsm upload", policy.status, code=policy.code)


def upload_protected(case, ctx):
    ##  P3-INPUT-PROTECTED: a workbook with password-protected structure.
    response = _upload(ctx, "protected.xlsx", workbook(protect_structure=True))
    return _rejected(ctx, response, "A workbook with password-protected structure",
                     ctx.profile.protected_workbook_status)


##  ---- Intake limits (exactly at a limit is valid; one over is rejected) ----

def upload_over_limit(case, ctx):
    ##  P3-INPUT-BYTES-OVER
    size = ctx.profile.limits.max_file_bytes + 1
    response = _upload(ctx, "over-limit.xlsx", workbook(size=size))
    return _rejected(ctx, response, f"A {size:,}-byte workbook", TOO_LARGE)


def upload_at_limit(case, ctx):
    ##  P3-INPUT-BYTES-AT
    size = ctx.profile.limits.max_file_bytes
    return _accepted(ctx, _upload(ctx, "at-limit.xlsx", workbook(size=size)), f"A {size:,}-byte workbook")


def upload_worksheets_over(case, ctx):
    ##  P3-INPUT-SHEETS-OVER
    count = ctx.profile.limits.max_worksheets + 1
    response = _upload(ctx, "worksheets-over.xlsx", workbook(worksheets=count))
    return _rejected(ctx, response, f"A workbook with {count} worksheets", INVALID_WORKBOOK)


def upload_worksheets_at(case, ctx):
    ##  P3-INPUT-SHEETS-AT
    count = ctx.profile.limits.max_worksheets
    response = _upload(ctx, "worksheets-at.xlsx", workbook(worksheets=count))
    return _accepted(ctx, response, f"A workbook with {count} worksheets")


def upload_worksheets_chartsheet(case, ctx):
    ##  P3-INPUT-SHEETS-CHARTSHEET (Phase 4 plan): chartsheets do not count toward the limit.
    count = ctx.profile.limits.max_worksheets
    response = _upload(ctx, "worksheets-chartsheet.xlsx", workbook(worksheets=count, cells=3, chartsheet=True))
    return _accepted(ctx, response, f"A workbook with {count} worksheets and one chartsheet")


def upload_cells_over(case, ctx):
    ##  P3-INPUT-CELLS-OVER
    count = ctx.profile.limits.max_nonempty_cells + 1
    response = _upload(ctx, "cells-over.xlsx", workbook(cells=count))
    return _rejected(ctx, response, f"A workbook with {count:,} nonempty cells", INVALID_WORKBOOK)


def upload_cells_at(case, ctx):
    ##  P3-INPUT-CELLS-AT
    count = ctx.profile.limits.max_nonempty_cells
    response = _upload(ctx, "cells-at.xlsx", workbook(cells=count))
    return _accepted(ctx, response, f"A workbook with {count:,} nonempty cells")


##  ---- Fixtures from the session's frozen pack ----

def _fixture(ctx, key, kind):
    ##  (entry, None), or (None, the skip or tester error to report instead).
    entry = ctx.fixture_entry(key)
    if entry is None:
        return None, CaseResult("skip", f"Not executed: no fixture pack with a {key} entry was frozen at setup.")
    if entry["kind"] != kind:
        return None, CaseResult.error("tester", f"Fixture {key} is a {entry['kind']} entry; this case needs a "
                                                f"{kind} one.")
    return entry, None


##  ---- Accepted fixtures: upload, then compare the audit with the hand-authored expectations ----

FINDING_KEY = ("ruleId", "category", "worksheet", "target", "classification")


def _upload_fixture(ctx, key):
    entry, problem = _fixture(ctx, key, "accepted")
    if problem:
        return problem
    response = ctx.upload(WORKBOOKS, role="userA", fixture=key)
    result = _accepted(ctx, response, f"The {key} fixture ({entry['upload_name']})")
    if result.outcome == "pass":
        ctx.state.setdefault("uploads", {})[key] = UploadResponse.model_validate(response.json()).model_dump()
    return result


def _audit_path(upload):
    return f"{WORKBOOKS}/{upload['workbookId']}/versions/{upload['versionId']}/audits/{upload['auditId']}"


def _processing(response):
    body = response.json() if response.status == 200 else None
    return isinstance(body, dict) and body.get("status") == "PROCESSING"


def _describe(finding):
    rule, _category, worksheet, target, classification = finding
    return f"{rule} {classification} on {worksheet!r} at {target}"


def _finding_problems(findings, entry, ruleset):
    got = [tuple(getattr(f, field) for field in FINDING_KEY) for f in findings]
    expected = [tuple(f[field] for field in FINDING_KEY) for f in entry["findings"]]
    missing, extra = Counter(expected) - Counter(got), Counter(got) - Counter(expected)
    problems = [f"missing {_describe(f)}" for f in missing.elements()]
    problems += [f"unexpected {_describe(f)}" for f in extra.elements()]
    if not problems and got != expected:
        problems.append("findings are not in contract order (ruleId, worksheet, target by code point)")
    for f in findings:
        expected_id = finding_id(entry["sha256"], ruleset, f.ruleId, f.worksheet, f.target)
        if f.findingId != expected_id:
            problems.append(f"findingId at {f.target} is {f.findingId}, expected {expected_id}")
    return problems


def _audit_problems(audit, upload, entry, ruleset):
    problems = [f"{field} {getattr(audit, field)} is not the upload's {upload[field]}"
                for field in ("auditId", "workbookId", "versionId") if getattr(audit, field) != upload[field]]
    if audit.rulesetVersion != ruleset:
        problems.append(f"rulesetVersion {audit.rulesetVersion}, expected {ruleset}")
    if audit.status == "PROCESSING_FAILED":
        code = audit.error.code if audit.error else "with no error body"
        return problems + [f"processing failed ({code}), expected {entry['expected_status']}"]
    if audit.completedAt is None:
        problems.append("completedAt is null on a finished audit")
    elif datetime.fromisoformat(audit.completedAt) < datetime.fromisoformat(audit.startedAt):
        problems.append("completedAt is earlier than startedAt")
    if audit.error is not None:
        problems.append(f"error {audit.error.code} is set on a successful audit")
    if audit.status != entry["expected_status"]:
        problems.append(f"status {audit.status}, expected {entry['expected_status']}")
    problems += _finding_problems(audit.findings, entry, ruleset)
    ##  Limitation wording is not agreed, so only presence is compared. A Phase 4 entry lists the
    ##  facts that must be disclosed (limitation_facts); Phase 4 also requires sorted, unique strings.
    required = entry.get("limitations_required", False) or bool(entry.get("limitation_facts"))
    if required and not audit.limitations:
        problems.append("limitations is empty, but this fixture's unusual metadata must be disclosed")
    elif not required and audit.limitations:
        problems.append(f"expected no limitations; received {len(audit.limitations)}")
    if "limitation_facts" in entry and audit.limitations != sorted(set(audit.limitations)):
        problems.append("limitations are not sorted by code point without duplicates")
    return problems


def _finished_audit(ctx, upload, what, session=True, mark=True):
    ##  (AuditResponse, None) once the owner's audit read leaves PROCESSING, or (None, the result
    ##  to report). Marks the case once a finished response is evaluated (unless mark=False, for
    ##  an audit that only prepares a resource). Every PROCESSING_FAILED audit is kept for
    ##  P3-AUDIT-FAILURE-ENVELOPE. session names a fault session instead.
    response, finished = ctx.poll(lambda: ctx.call("GET", _audit_path(upload), role="userA", session=session),
                                  lambda r: not _processing(r))
    if response.status >= 500:
        return None, _system_failure(what, response)
    if not finished:
        return None, CaseResult.failed(f"{what} was still PROCESSING after "
                                       f"{ctx.profile.timing.audit_poll_seconds:g} s.")
    if mark:
        ctx.mark()
    if response.status != 200:
        return None, CaseResult.failed(f"Expected 200 for {what}; received {response.status}.")
    try:
        audit = AuditResponse.model_validate(response.json())
    except ValidationError as problem:
        return None, CaseResult.failed(f"{what} body does not match AuditResponse ({_schema_problem(problem)}).")
    if audit.status == "PROCESSING_FAILED":
        ctx.state.setdefault("controlled_failures", []).append({"test_id": ctx.case.test_id, "audit": audit.model_dump()})
    return audit, None


def _audit_fixture(ctx, key):
    entry, problem = _fixture(ctx, key, "accepted")
    if problem:
        return problem
    upload, what = ctx.state["uploads"][key], f"The {key} audit"
    audit, result = _finished_audit(ctx, upload, what)
    if result:
        return result
    ##  A finished audit is usable by later cases (source hash, determinism) even when its
    ##  findings are wrong; a processing failure is not.
    ctx.state.setdefault("audits", {})[key] = audit.model_dump()
    if audit.status != "PROCESSING_FAILED":
        ctx.provide()
    problems = _audit_problems(audit, upload, entry, ctx.manifest.ruleset_version)
    if problems:
        more = f"; and {len(problems) - 4} more" if len(problems) > 4 else ""
        return CaseResult.failed(f"{what}: " + "; ".join(problems[:4]) + more + ".")
    count = len(audit.findings)
    return CaseResult.passed(f"{what} reached {audit.status} with exactly the {count} expected "
                             f"finding{'' if count == 1 else 's'} in contract order.")


def upload_clean(case, ctx):
    ##  P3-UPLOAD-CLEAN
    return _upload_fixture(ctx, "clean")


def upload_seeded(case, ctx):
    ##  P3-UPLOAD-SEEDED
    return _upload_fixture(ctx, "seeded_issues")


def audit_clean(case, ctx):
    ##  P3-AUDIT-CLEAN: AUDIT_COMPLETE with no findings.
    return _audit_fixture(ctx, "clean")


def audit_seeded(case, ctx):
    ##  P3-AUDIT-SEEDED: exactly the expected findings in contract order.
    return _audit_fixture(ctx, "seeded_issues")


def edge_upload(case, ctx):
    ##  P3-UPLOAD-UNICODE, -REPEATED-IDS, -MULTIPLE-DRAWINGS
    return _upload_fixture(ctx, case.parameters["fixture"])


def edge_audit(case, ctx):
    ##  P3-AUDIT-UNICODE, -REPEATED-IDS, -MULTIPLE-DRAWINGS: findings and limitations.
    return _audit_fixture(ctx, case.parameters["fixture"])


##  ---- Versions, source hash and access (reuse the clean and seeded uploads) ----

def _version_path(upload):
    return f"{WORKBOOKS}/{upload['workbookId']}/versions/{upload['versionId']}"


def _verdict(what, problems, passed):
    if not problems:
        return CaseResult.passed(passed)
    more = f"; and {len(problems) - 4} more" if len(problems) > 4 else ""
    return CaseResult.failed(f"{what}: " + "; ".join(problems[:4]) + more + ".")


def _read_version(ctx, response, what):
    ##  (VersionResponse, None) or (None, the result to report). Marks the case on any non-5xx reply.
    if response.status >= 500:
        return None, _system_failure(what, response)
    ctx.mark()
    if response.status != 200:
        return None, CaseResult.failed(f"Expected 200 for {what}; received {response.status}.")
    try:
        return VersionResponse.model_validate(response.json()), None
    except ValidationError as problem:
        return None, CaseResult.failed(f"{what} body does not match VersionResponse ({_schema_problem(problem)}).")


def _version_problems(ctx, version, upload, key):
    ##  Identity, file name and hash; the hash is the tester's own SHA256 of the bytes it sent.
    data, entry = ctx.fixture(key)
    own = hashlib.sha256(data).hexdigest()
    problems = [f"{field} {getattr(version, field)} is not the upload's {upload[field]}"
                for field in ("workbookId", "versionId") if getattr(version, field) != upload[field]]
    if version.fileName != entry["upload_name"]:
        problems.append(f"fileName {version.fileName!r}, expected {entry['upload_name']!r}")
    if version.sha256 != own:
        problems.append(f"sha256 {version.sha256} is not the tester's SHA256 {own} of the uploaded bytes")
    if version.latestAuditId != upload["auditId"]:
        problems.append(f"latestAuditId {version.latestAuditId}, expected the upload's {upload['auditId']}")
    if version.sourceVersionId is not None:
        problems.append(f"sourceVersionId {version.sourceVersionId} is set on an initial upload")
    return problems


def version_clean(case, ctx):
    ##  P3-VERSION-VALID: runs before the clean audit is read, so PROCESSING is also acceptable.
    upload, expected = ctx.state["uploads"]["clean"], ctx.fixture_entry("clean")["expected_status"]
    what = "The clean version read"
    version, result = _read_version(ctx, ctx.call("GET", _version_path(upload), role="userA"), what)
    if result:
        return result
    problems = _version_problems(ctx, version, upload, "clean")
    if version.status not in ("PROCESSING", expected):
        problems.append(f"status {version.status}, expected PROCESSING or {expected}")
    return _verdict(what, problems, f"{what} matches the upload, its file name and the tester's own SHA256.")


def hash_after_audit(case, ctx):
    ##  P3-SOURCE-HASH: after the seeded audit finished, the version still reports the hash of
    ##  the bytes the tester sent. Over HTTP this is the strongest check available.
    upload, audit = ctx.state["uploads"]["seeded_issues"], ctx.state["audits"]["seeded_issues"]
    what = "The seeded version read after its audit"
    version, result = _read_version(ctx, ctx.call("GET", _version_path(upload), role="userA"), what)
    if result:
        return result
    problems = _version_problems(ctx, version, upload, "seeded_issues")
    if version.status != audit["status"]:
        problems.append(f"status {version.status}, but the finished audit is {audit['status']}")
    return _verdict(what, problems, f"{what} still reports the tester's own SHA256 of the uploaded bytes.")


def version_unauthenticated(case, ctx):
    ##  P3-VERSION-UNAUTHENTICATED
    response = ctx.call("GET", _version_path(ctx.state["uploads"]["clean"]), role=None)
    return _rejected(ctx, response, "A version read without a bearer token", 401)


def audit_unauthenticated(case, ctx):
    ##  P3-AUDIT-UNAUTHENTICATED
    response = ctx.call("GET", _audit_path(ctx.state["uploads"]["clean"]), role=None)
    return _rejected(ctx, response, "An audit read without a bearer token", 401)


def foreign_owner_forbidden(case, ctx):
    ##  P3-VERSION-FOREIGN
    response = ctx.call("GET", _version_path(ctx.state["uploads"]["seeded_issues"]), role="userB")
    return _rejected(ctx, response, "User B reading user A's version", 403)


def audit_foreign_owner(case, ctx):
    ##  P3-AUDIT-FOREIGN
    response = ctx.call("GET", _audit_path(ctx.state["uploads"]["seeded_issues"]), role="userB")
    return _rejected(ctx, response, "User B reading user A's audit", 403)


def reviewer_version(case, ctx):
    ##  P3-VERSION-REVIEWER: the explicitly granted reviewer sees user A's version.
    upload, what = ctx.state["uploads"]["seeded_issues"], "The reviewer's read of user A's version"
    version, result = _read_version(ctx, ctx.call("GET", _version_path(upload), role="reviewer"), what)
    if result:
        return result
    return _verdict(what, _version_problems(ctx, version, upload, "seeded_issues"),
                    f"{what} returned 200 with user A's version metadata.")


def reviewer_audit(case, ctx):
    ##  P3-AUDIT-REVIEWER: the reviewer sees the same audit the owner saw.
    upload, what = ctx.state["uploads"]["seeded_issues"], "The reviewer's read of user A's audit"
    response = ctx.call("GET", _audit_path(upload), role="reviewer")
    if response.status >= 500:
        return _system_failure(what, response)
    ctx.mark()
    if response.status != 200:
        return CaseResult.failed(f"Expected 200 for {what}; received {response.status}.")
    try:
        audit = AuditResponse.model_validate(response.json())
    except ValidationError as problem:
        return CaseResult.failed(f"{what} body does not match AuditResponse ({_schema_problem(problem)}).")
    problems = [f"{field} {getattr(audit, field)} is not the upload's {upload[field]}"
                for field in ("auditId", "workbookId", "versionId") if getattr(audit, field) != upload[field]]
    owner_view = ctx.state.get("audits", {}).get("seeded_issues")
    if owner_view is not None:
        problems += [f"{field} differs from the owner's read" for field in ("status", "findings", "limitations")
                     if audit.model_dump()[field] != owner_view[field]]
    return _verdict(what, problems, f"{what} returned 200 with the audit user A saw.")


##  ---- Determinism, session header and controlled failures ----

DETERMINISM_FIELDS = ("rulesetVersion", "status", "findings", "limitations")


def determinism(case, ctx):
    ##  P3-DETERMINISM(-3/-4/-5): a fresh upload of the same seeded bytes must audit to the same
    ##  status, findings (IDs and text included) and limitations as the first seeded audit.
    run, first = case.parameters.get("run"), ctx.state["audits"]["seeded_issues"]
    response = ctx.upload(WORKBOOKS, role="userA", fixture="seeded_issues")
    if response.status >= 500:
        return _system_failure(f"Upload {run} of the seeded fixture", response)
    try:
        upload = UploadResponse.model_validate(response.json()).model_dump() if response.status == 202 else None
    except ValidationError:
        upload = None
    if upload is None:
        return CaseResult.failed(f"Upload {run} of the seeded fixture was not accepted with a valid "
                                 f"UploadResponse (status {response.status}), so no audit could be compared.")
    what = f"Seeded audit {run}"
    audit, result = _finished_audit(ctx, upload, what)
    if result:
        return result
    current = audit.model_dump()
    problems = [f"{field} differs from the first audit" for field in DETERMINISM_FIELDS if current[field] != first[field]]
    if upload["auditId"] == first["auditId"]:
        problems.append(f"upload {run} reused the first audit's ID {first['auditId']}")
    return _verdict(what, problems, f"{what} matches the first audit: {audit.status}, the same "
                                    f"{len(audit.findings)} findings with identical IDs and text, and the same "
                                    f"limitations.")


def unknown_session_header(case, ctx):
    ##  P3-SESSION-UNKNOWN: a project call naming a session the system never prepared.
    transport = ctx.profile.session_transport
    response = ctx.call("GET", _version_path(ctx.state["uploads"]["seeded_issues"]), role="userA",
                        session=f"unknown-{uuid.uuid4().hex}")
    return _rejected(ctx, response, f"A version read naming an unknown {transport.header}",
                     transport.unknown_session_status)


def controlled_failure(case, ctx):
    ##  P3-AUDIT-FAILURE-ENVELOPE: every PROCESSING_FAILED audit seen in this run must carry a
    ##  completion time and a ProjectError and expose no partial findings.
    failures = ctx.state.get("controlled_failures", [])
    if not failures:
        return CaseResult("skip", "Not executed: no controlled audit failure (PROCESSING_FAILED) was observed "
                                  "in this run.")
    ctx.mark()
    problems = []
    for item in failures:
        audit, where = item["audit"], item["test_id"]
        if audit["completedAt"] is None:
            problems.append(f"{where}: completedAt is null")
        elif datetime.fromisoformat(audit["completedAt"]) < datetime.fromisoformat(audit["startedAt"]):
            problems.append(f"{where}: completedAt is earlier than startedAt")
        if audit["error"] is None:
            problems.append(f"{where}: error is null")
        if audit["findings"]:
            problems.append(f"{where}: exposes {len(audit['findings'])} partial findings")
    return _verdict("The controlled audit failure envelope", problems,
                    f"{len(failures)} controlled audit failure{'' if len(failures) == 1 else 's'} carried a "
                    f"completion time and a ProjectError and exposed no partial findings.")


##  ---- Phase 4 controlled audit failure (shared specification §14.1) ----
##  A separate fresh system session armed with one audit failure. Its ID goes into the run
##  record and is queued for cleanup after the run; its coverage is never requested.

FAULT_SETUP = {"faults": {"audit_failures": 1}}
FAULT_ERROR = {"code": "TEST_AUDIT_FAILURE", "message": "Audit failure requested by the isolated test session.",
               "details": {"stage": "audit", "testOnly": True}}
FAULT_CREDENTIALS = {"user": ("userA", 403), "reviewer": ("reviewer", 403), "none": (None, 401), "invalid": (None, 401)}
INVALID_FAULTS = {
    "empty": {}, "zero": {"audit_failures": 0}, "two": {"audit_failures": 2}, "true": {"audit_failures": True},
    "string": {"audit_failures": "1"}, "unknown-key": {"audit_failures": 1, "repeat": True},
}


def _fault_setup_call(ctx, setup, role="test-admin", bearer=None):
    ##  (fresh session ID, response). A 201 or 5xx may have left state on the target.
    session_id = str(uuid.uuid4())
    response = ctx.target.system_setup(session_id, setup, ctx.deadline, role=role, bearer=bearer)
    if response.status == 201 or response.status >= 500:
        ctx.record_fault_session(session_id)
    return session_id, response


def _not_runnable(ctx, session_id, label):
    ##  A refused setup must leave no runnable namespace: the session header is still unknown.
    transport = ctx.profile.session_transport
    probe = ctx.call("GET", f"{WORKBOOKS}/unknown-{uuid.uuid4().hex[:16]}/versions/unknown-{uuid.uuid4().hex[:16]}",
                     role="userA", session=session_id)
    if probe.status != transport.unknown_session_status:
        return [f"{label}: a project call naming the refused session returned {probe.status}, expected "
                f"{transport.unknown_session_status} for an unknown {transport.header}"]
    return []


def _refused_setup_problems(ctx, session_id, response, expected, label, source=None):
    problems = []
    if response.status != expected:
        accepted = ", creating the session" if response.status == 201 else ""
        return [f"{label}: expected {expected}, received {response.status}{accepted}"]
    try:
        error = TestEndpointError.model_validate(response.json())
    except ValidationError as problem:
        return [f"{label}: {expected} body does not match TestEndpointError ({_schema_problem(problem)})"]
    if source is not None and error.source != source:
        problems.append(f"{label}: source is {error.source}, expected {source}")
    return problems + _not_runnable(ctx, session_id, label)


def fault_setup(case, ctx):
    ##  P4-FAULT-SETUP: test-admin creates a fresh session with exactly one armed audit failure.
    ##  A refused capability (403 when the trusted switch is off) is a failure, not a skip.
    session_id, response = _fault_setup_call(ctx, FAULT_SETUP)
    if response.status >= 500:
        return _system_failure("Fault-session setup", response)
    ctx.mark()
    if response.status != 201:
        refused = " (the fault capability was refused)" if response.status == 403 else ""
        return CaseResult.failed(f"Expected 201 for fault-session setup; received {response.status}{refused}.")
    try:
        echoed = SetupResponse.model_validate(response.json()).session_id
    except ValidationError as problem:
        return CaseResult.failed(f"201 body does not match SetupResponse ({_schema_problem(problem)}).")
    if echoed != session_id:
        return CaseResult.failed(f"Fault-session setup echoed {echoed}, not {session_id}.")
    ctx.state["fault_session"] = session_id
    return CaseResult.passed(f"Fault session {session_id} was created with one armed audit failure.")


def _injected_failure_problems(audit, upload, ruleset):
    problems = [f"{field} {getattr(audit, field)} is not the upload's {upload[field]}"
                for field in ("auditId", "workbookId", "versionId") if getattr(audit, field) != upload[field]]
    if audit.rulesetVersion != ruleset:
        problems.append(f"rulesetVersion {audit.rulesetVersion}, expected {ruleset}")
    if audit.status != "PROCESSING_FAILED":
        return problems + [f"status {audit.status}: the armed audit failure was not applied"]
    if audit.completedAt is None:
        problems.append("completedAt is null")
    elif datetime.fromisoformat(audit.completedAt) < datetime.fromisoformat(audit.startedAt):
        problems.append("completedAt is earlier than startedAt")
    if audit.findings:
        problems.append(f"exposes {len(audit.findings)} partial findings")
    if audit.error is None:
        return problems + ["error is null"]
    actual = {"code": audit.error.code, "message": audit.error.message, "details": audit.error.details}
    problems += [f"error {field} is {actual[field]!r}, expected {expected!r}"
                 for field, expected in FAULT_ERROR.items() if actual[field] != expected]
    return problems


def _report(ctx, upload, session):
    ##  (AuditReport or None, raw bytes or None, problems) for the audit's downloadable report.
    response = ctx.download(f"{_audit_path(upload)}/report", role="userA", session=session)
    if response.status != 200:
        return None, None, [f"the audit report download returned {response.status}"]
    try:
        return AuditReport.model_validate(response.json()), response.body, []
    except ValidationError as problem:
        return None, response.body, [f"the audit report does not match AuditReport ({_schema_problem(problem)})"]


def _failed_report_problems(report, upload, audit):
    problems = [f"report {field} {getattr(report, field)} is not the upload's {upload[field]}"
                for field in ("auditId", "workbookId", "versionId") if getattr(report, field) != upload[field]]
    if report.status != "PROCESSING_FAILED":
        problems.append(f"report status is {report.status}, expected PROCESSING_FAILED")
    if report.checksPerformed:
        problems.append(f"report checksPerformed is {report.checksPerformed}, expected []")
    for field in ("findings", "unresolvedFindings", "manualReviewItems", "decisions", "approvedChanges"):
        if getattr(report, field):
            problems.append(f"report {field} is not empty")
    if report.error != audit.error:
        problems.append("report error differs from the audit's error")
    return problems


def _source_problems(ctx, upload, data, session):
    response = ctx.download(f"{_version_path(upload)}/source", role="userA", session=session)
    if response.status != 200:
        return [f"the source download returned {response.status}"]
    if response.body != data:
        return [f"the downloaded source (SHA256 {hashlib.sha256(response.body).hexdigest()}) is not the uploaded "
                f"bytes (SHA256 {hashlib.sha256(data).hexdigest()})"]
    return []


def fault_failure_envelope(case, ctx):
    ##  P3-AUDIT-FAILURE-ENVELOPE as the Phase 4 plan defines it: in the fault session, a valid
    ##  clean upload is accepted normally, then its audit fails exactly as specified, its failed
    ##  report has no checks, and the source stays downloadable and unchanged.
    key = case.parameters.get("fixture", "clean_all_six")
    entry, problem = _fixture(ctx, key, "accepted")
    if problem:
        return problem
    session = ctx.state["fault_session"]
    response = ctx.upload(WORKBOOKS, role="userA", fixture=key, session=session)
    accepted = _accepted(ctx, response, f"The {key} upload in the fault session")
    if accepted.outcome != "pass":
        return accepted
    upload = UploadResponse.model_validate(response.json()).model_dump()
    what = "The fault-session audit"
    audit, result = _finished_audit(ctx, upload, what, session=session)
    if result:
        return result
    problems = _injected_failure_problems(audit, upload, ctx.manifest.ruleset_version)
    version, result = _read_version(ctx, ctx.call("GET", _version_path(upload), role="userA", session=session),
                                    "The fault-session version read")
    if result:
        problems.append(result.message.rstrip("."))
    else:
        problems += _version_problems(ctx, version, upload, key)
        if version.status != "PROCESSING_FAILED":
            problems.append(f"version status is {version.status}, expected PROCESSING_FAILED")
    report, report_bytes, report_problems = _report(ctx, upload, session)
    problems += report_problems + (_failed_report_problems(report, upload, audit) if report else [])
    problems += _source_problems(ctx, upload, ctx.fixture(key)[0], session)
    if audit.status == "PROCESSING_FAILED" and audit.error and audit.error.code == FAULT_ERROR["code"]:
        ctx.state["fault"] = {"upload": upload, "audit": audit.model_dump(), "report": report_bytes, "fixture": key}
        ctx.provide()
    return _verdict(what, problems, f"{what} failed exactly as injected (TEST_AUDIT_FAILURE, no findings), its "
                                    f"report lists no checks, and the source downloads unchanged.")


def fault_recovery(case, ctx):
    ##  P4-FAULT-RECOVERY: a manual re-audit of the same version then runs normally, while the
    ##  failed audit and its report stay unchanged.
    fault, session = ctx.state["fault"], ctx.state["fault_session"]
    upload, failed, key = fault["upload"], fault["audit"], fault["fixture"]
    entry = ctx.fixture_entry(key)
    response = ctx.call("POST", f"{_version_path(upload)}/audits", role="userA", session=session,
                        json_body={"reason": "MANUAL_REAUDIT"})
    if response.status >= 500:
        return _system_failure("The manual re-audit", response)
    ctx.mark()
    if response.status != 202:
        return CaseResult.failed(f"Expected 202 for the manual re-audit; received {response.status}.")
    try:
        reaudit = ReauditResponse.model_validate(response.json())
    except ValidationError as problem:
        return CaseResult.failed(f"202 body does not match ReauditResponse ({_schema_problem(problem)}).")
    problems = []
    if reaudit.versionId != upload["versionId"]:
        problems.append(f"the re-audit names version {reaudit.versionId}, not {upload['versionId']}")
    if reaudit.auditId == failed["auditId"]:
        problems.append("the re-audit reused the failed audit's ID")
    current = {**upload, "auditId": reaudit.auditId}
    what = "The re-audit after the injected failure"
    audit, result = _finished_audit(ctx, current, what, session=session)
    if result:
        return result
    problems += _audit_problems(audit, current, entry, ctx.manifest.ruleset_version)
    earlier = ctx.call("GET", _audit_path(upload), role="userA", session=session)
    if earlier.status != 200 or earlier.json() != failed:
        problems.append("the failed audit changed or could not be read after the re-audit")
    _, report_bytes, report_problems = _report(ctx, upload, session)
    if report_problems or report_bytes != fault["report"]:
        problems.append("the failed audit's report changed or could not be downloaded after the re-audit")
    version, result = _read_version(ctx, ctx.call("GET", _version_path(upload), role="userA", session=session),
                                    "The version read after the re-audit")
    if result:
        problems.append(result.message.rstrip("."))
    elif version.latestAuditId != reaudit.auditId:
        problems.append(f"latestAuditId is {version.latestAuditId}, expected the re-audit {reaudit.auditId}")
    history = ctx.call("GET", f"{WORKBOOKS}/{upload['workbookId']}/history", role="userA", session=session)
    try:
        audits = [a.auditId for a in HistoryResponse.model_validate(history.json()).audits] \
            if history.status == 200 else None
    except ValidationError as problem:
        audits, problems = None, problems + [f"history does not match HistoryResponse ({_schema_problem(problem)})"]
    if history.status != 200:
        problems.append(f"the history read returned {history.status}")
    elif audits is not None and audits != [failed["auditId"], reaudit.auditId]:
        problems.append(f"history lists audits {audits}, expected the failed audit then the re-audit")
    return _verdict(what, problems, f"{what} reached {audit.status} as expected; the failed audit, its report and "
                                    f"the history order are intact.")


def fault_auth(case, ctx):
    ##  P4-FAULT-AUTH: only test-admin may arm a fault. A credential parameter selects one
    ##  vector; without one, every vector runs.
    names = [case.parameters["credential"]] if "credential" in case.parameters else list(FAULT_CREDENTIALS)
    problems = []
    for name in names:
        role, expected = FAULT_CREDENTIALS[name]
        bearer = f"tester-invalid-{uuid.uuid4().hex}" if name == "invalid" else None
        session_id, response = _fault_setup_call(ctx, FAULT_SETUP, role=role, bearer=bearer)
        if response.status >= 500:
            return _system_failure(f"Fault setup with the {name} credential", response)
        ctx.mark()
        problems += _refused_setup_problems(ctx, session_id, response, expected, f"{name} credential")
    return _verdict("Fault setup without test-admin", problems,
                    f"Fault setup was refused for {', '.join(names)} credentials, leaving no runnable session.")


def fault_invalid(case, ctx):
    ##  P4-FAULT-INVALID: malformed faults are 400 with source system. A vector parameter selects
    ##  one; without one, every vector runs.
    names = [case.parameters["vector"]] if "vector" in case.parameters else list(INVALID_FAULTS)
    problems = []
    for name in names:
        session_id, response = _fault_setup_call(ctx, {"faults": INVALID_FAULTS[name]})
        if response.status >= 500:
            return _system_failure(f"Fault setup with the {name} vector", response)
        ctx.mark()
        problems += _refused_setup_problems(ctx, session_id, response, 400, f"{name} faults", source="system")
    return _verdict("Malformed fault setup", problems,
                    f"Fault setup was refused with 400 (source system) for {', '.join(names)}, leaving no runnable "
                    f"session.")


##  ---- Rejected fixtures ----

def _rejected_fixture(ctx, key):
    ##  The expected status and code come from the fixture's entry; a null code is not compared.
    entry, problem = _fixture(ctx, key, "rejected")
    if problem:
        return problem
    status = entry.get("http_status")
    if not isinstance(status, int):
        return CaseResult.error("tester", f"Fixture {key} has no integer http_status, so the expected rejection "
                                          f"is unknown.")
    response = ctx.upload(WORKBOOKS, role="userA", fixture=key)
    return _rejected(ctx, response, f"The {key} fixture ({entry['upload_name']})", status,
                     code=entry.get("error_code"))


def upload_corrupt(case, ctx):
    ##  P3-INPUT-CORRUPT: corrupt.xlsx is not a readable package.
    return _rejected_fixture(ctx, "corrupt")


def rejected_fixture(case, ctx):
    ##  P3-INPUT-ZIP-TRAVERSAL through P3-INPUT-PROTECTED-STRUCTURE: one defect per workbook.
    return _rejected_fixture(ctx, case.parameters["fixture"])


##  ---- Resources ----

def unknown_resources(case, ctx):
    ##  P3-NOT-FOUND (version-unknown) needs no upload; the mismatch and audit-unknown variants
    ##  pair real IDs from the clean and seeded uploads so that only the pairing is wrong.
    variant = case.parameters.get("case")
    unknown = f"unknown-{uuid.uuid4().hex[:16]}"
    if variant == "version-unknown":
        path, what = f"{WORKBOOKS}/{unknown}/versions/unknown-{uuid.uuid4().hex[:16]}", "A version read with unknown IDs"
    else:
        uploads = ctx.state.get("uploads", {})
        clean, seeded = uploads.get("clean"), uploads.get("seeded_issues")
        if clean is None or seeded is None:
            return CaseResult.error("tester", f"The {variant} variant needs the clean and seeded uploads.")
        paths = {
            "version-mismatch": (f"{WORKBOOKS}/{clean['workbookId']}/versions/{seeded['versionId']}",
                                 "A version read pairing the clean workbook with the seeded version"),
            "audit-mismatch": (f"{_version_path(clean)}/audits/{seeded['auditId']}",
                               "An audit read pairing the clean version with the seeded audit"),
            "audit-unknown": (f"{_version_path(clean)}/audits/{unknown}", "An audit read with an unknown audit ID"),
        }
        if variant not in paths:
            return CaseResult.error("tester", f"Unknown unknown_resources variant {variant!r}.")
        path, what = paths[variant]
    return _rejected(ctx, ctx.call("GET", path, role="userA"), what, 404)


##  ---- System test endpoints ----

def system_report(case, ctx):
    ##  P3-CODE-REPORT: GET system /test/report returns this session's code coverage.
    response = ctx.target.system_report(ctx.session_id, ctx.deadline)
    if response.status >= 500:
        return _system_failure("System report", response)
    ctx.mark()
    if response.status != 200:
        return CaseResult.failed(f"Expected 200 from system report; received {response.status}.")
    try:
        report = SystemReport.model_validate(response.json())
    except ValidationError as error:
        return CaseResult.failed(f"System report body does not match SystemReport ({_schema_problem(error)}).")
    if report.session_id != ctx.session_id:
        return CaseResult.failed(f"System report echoed session {report.session_id}, not {ctx.session_id}.")
    measure = report.coverage["code"]
    ctx.record_code_coverage(measure.model_dump())
    if measure.covered is None:
        return CaseResult.passed(f"System report returned paired null code coverage ({measure.basis}).")
    return CaseResult.passed(f"System report returned code coverage {measure.covered}/{measure.total}.")


def system_setup_duplicate(case, ctx):
    ##  P3-SESSION-DUPLICATE: repeating system setup with this session's ID returns 409.
    response = ctx.target.system_setup(ctx.session_id, {}, ctx.deadline)
    if response.status >= 500:
        return _system_failure("Duplicate system setup", response)
    ctx.mark()
    if response.status != 409:
        return CaseResult.failed(f"Expected 409 for a duplicate system setup; received {response.status}.")
    try:
        TestEndpointError.model_validate(response.json())
    except ValidationError as error:
        return CaseResult.failed(f"409 body does not match TestEndpointError ({_schema_problem(error)}).")
    return CaseResult.passed("Duplicate system setup returned 409 with a valid {message, source} body.")


CHECKS = {
    "health": health,
    "upload_without_token": upload_without_token,
    "upload_invalid_token": upload_invalid_token,
    "upload_missing_file": upload_missing_file,
    "upload_csv": upload_csv,
    "upload_no_extension": upload_no_extension,
    "upload_xls": upload_xls,
    "upload_xlsm": upload_xlsm,
    "upload_protected": upload_protected,
    "upload_over_limit": upload_over_limit,
    "upload_at_limit": upload_at_limit,
    "upload_worksheets_over": upload_worksheets_over,
    "upload_worksheets_at": upload_worksheets_at,
    "upload_worksheets_chartsheet": upload_worksheets_chartsheet,
    "upload_cells_over": upload_cells_over,
    "upload_cells_at": upload_cells_at,
    "upload_corrupt": upload_corrupt,
    "upload_clean": upload_clean,
    "upload_seeded": upload_seeded,
    "audit_clean": audit_clean,
    "audit_seeded": audit_seeded,
    "edge_upload": edge_upload,
    "edge_audit": edge_audit,
    "version_clean": version_clean,
    "version_unauthenticated": version_unauthenticated,
    "hash_after_audit": hash_after_audit,
    "foreign_owner_forbidden": foreign_owner_forbidden,
    "audit_unauthenticated": audit_unauthenticated,
    "audit_foreign_owner": audit_foreign_owner,
    "reviewer_version": reviewer_version,
    "reviewer_audit": reviewer_audit,
    "determinism": determinism,
    "unknown_session_header": unknown_session_header,
    "controlled_failure": controlled_failure,
    "fault_setup": fault_setup,
    "fault_failure_envelope": fault_failure_envelope,
    "fault_recovery": fault_recovery,
    "fault_auth": fault_auth,
    "fault_invalid": fault_invalid,
    "rejected_fixture": rejected_fixture,
    "unknown_resources": unknown_resources,
    "system_report": system_report,
    "system_setup_duplicate": system_setup_duplicate,
}

##  Phase 4 checks live in checks_phase4.py, which builds on the helpers above.
from .checks_phase4 import PHASE4_CHECKS  # noqa: E402

CHECKS.update(PHASE4_CHECKS)
