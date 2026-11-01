"""Phase 4 check functions (shared specification 2.1.0), keyed by the manifest's `check` name.

They share a cached resource layer: each fixture is uploaded and audited once per purpose
(`_audited`), each decision set is remediated once (`_remediated`). A resource that failed
to build is cached as failed, so later cases that need it skip with the case that failed,
instead of repeating the upload. Expected results come only from the frozen fixture pack;
output packages are judged by the independent comparator (comparator.py).
"""

import hashlib
import json
import uuid

from pydantic import ValidationError

from ..models import (AuditReport, HistoryResponse, ProjectError, ReauditResponse, RemediationAccepted,
                      RemediationResponse, ReviewResponse, SystemReport, TestResult, UploadResponse, VersionResponse)
from .checks import (FAULT_SETUP, FINDING_KEY, WORKBOOKS, _accepted, _audit_fixture, _audit_path, _fault_setup_call,
                     _finished_audit, _fixture, _read_version, _schema_problem, _system_failure, _upload_fixture,
                     _verdict, _version_path)
from .comparator import change_from_decision, compare
from .identity import finding_id
from .runner import CaseResult
from .transfer import download_problems, generated_name, upload_files

REMEDIATIONS = "/api/v1/remediations"
OUTPUTS = "/api/v1/outputs"
OWNER_ACTIONS = {"REQUIRES_USER_INPUT": ["APPLY", "DECLINE", "MANUAL_REVIEW"], "MANUAL_REVIEW": ["DECLINE", "MANUAL_REVIEW"]}


def _skip_failed(what, test_id):
    return CaseResult("skip", f"Not executed: {what} this case needs could not be prepared (see {test_id}).")


def _error_problems(response, status, code, what):
    ##  Problems with an expected ProjectError rejection (empty when it conforms).
    if response.status != status:
        accepted = ", accepting it" if response.status in (200, 201, 202) else ""
        return [f"{what}: expected {status}, received {response.status}{accepted}"]
    try:
        error = ProjectError.model_validate(response.json())
    except ValidationError as problem:
        return [f"{what}: {status} body does not match ProjectError ({_schema_problem(problem)})"]
    return [] if code is None or error.code == code else [f"{what}: code {error.code}, expected {code}"]


##  ---- Shared resources ----

def _audited(ctx, key, tag="shared", session=True):
    ##  (record, None) for an uploaded, successfully audited fixture, or (None, result to report).
    bucket = ctx.state.setdefault("audited", {})
    slot = f"{key}|{tag}|{session}"
    if slot in bucket:
        record = bucket[slot]
        return (None, _skip_failed(f"the {key} upload and audit", record["failed"])) if "failed" in record else (record, None)
    entry, problem = _fixture(ctx, key, "accepted")
    if problem:
        return None, problem
    response = ctx.upload(WORKBOOKS, role="userA", fixture=key, session=session)
    accepted = _accepted(ctx, response, f"The {key} upload", mark=False)
    if accepted.outcome != "pass":
        bucket[slot] = {"failed": ctx.case.test_id}
        return None, accepted
    upload = UploadResponse.model_validate(response.json()).model_dump()
    audit, result = _finished_audit(ctx, upload, f"The {key} audit", session=session, mark=False)
    if result is None and audit.status == "PROCESSING_FAILED":
        result = CaseResult.failed(f"The {key} audit failed ({audit.error.code if audit.error else 'no error body'}).")
    if result:
        bucket[slot] = {"failed": ctx.case.test_id}
        return None, result
    record = {"key": key, "entry": entry, "upload": upload, "audit": audit.model_dump(), "session": session,
              "bytes": ctx.fixture(key)[0]}
    bucket[slot] = record
    return record, None


def _ids_by_target(audit):
    return {f["target"]: f["findingId"] for f in audit["findings"]}


def _decision_spec(entry, set_name, targets=None):
    if set_name == "corrections":
        spec = [{"target": c["target"], "action": "APPLY", "value": c["value"]} for c in entry["corrections"]]
    else:
        spec = entry["decision_sets"][set_name]
    return [d for d in spec if not targets or d["target"] in targets]


def _decisions(record, spec):
    ##  (wire decisions, problems): finding IDs come from the target's own audit.
    ids, out, problems = _ids_by_target(record["audit"]), [], []
    for d in spec:
        if d["target"] not in ids:
            problems.append(f"the audit reported no finding at {d['target']}, so it cannot be decided")
            continue
        item = {"findingId": ids[d["target"]], "action": d["action"]}
        if "value" in d:
            item["value"] = d["value"]
        out.append(item)
    return out, problems


def _submit(ctx, record, decisions, key=None, session=None, body=None, **kwargs):
    body = {"auditId": record["audit"]["auditId"], "decisions": decisions} if body is None else body
    return ctx.call("POST", f"{_version_path(record['upload'])}/remediations", role=kwargs.pop("role", "userA"),
                    session=record["session"] if session is None else session, json_body=body,
                    idempotency_key=ctx.new_idempotency_key() if key is None else key, **kwargs)


def _poll_remediation(ctx, remediation_id, session=True):
    timing = ctx.profile.timing
    response, finished = ctx.poll(
        lambda: ctx.call("GET", f"{REMEDIATIONS}/{remediation_id}", role="userA", session=session),
        lambda r: not (r.status == 200 and isinstance(r.json(), dict) and r.json().get("status") == "REMEDIATING"),
        budget=timing.remediation_poll_seconds or timing.audit_poll_seconds)
    return response, finished


def _history(ctx, workbook_id, session=True):
    response = ctx.call("GET", f"{WORKBOOKS}/{workbook_id}/history", role="userA", session=session)
    if response.status != 200:
        return None, f"the history read returned {response.status}"
    try:
        return HistoryResponse.model_validate(response.json()).model_dump(), None
    except ValidationError as problem:
        return None, f"history does not match HistoryResponse ({_schema_problem(problem)})"


def _renames(spec, entry):
    ##  {old worksheet name: new name} for APPLY renames in a decision spec.
    worksheet_of = {f["target"]: f["worksheet"] for f in entry["findings"]}
    return {worksheet_of[d["target"]]: d["value"]["name"] for d in spec
            if d["action"] == "APPLY" and "#sheetId=" in d["target"]}


def _output_audit_problems(record, spec, output_audit):
    ##  Corrected targets are absent; every other source finding is retained (worksheet names
    ##  follow approved renames). Finding IDs change with the bytes, so they are not compared.
    applied = {d["target"] for d in spec if d["action"] == "APPLY"}
    renames = _renames(spec, record["entry"])
    present = {(f["ruleId"], f["worksheet"], f["target"]) for f in output_audit["findings"]}
    problems = []
    for f in record["audit"]["findings"]:
        moved = (f["ruleId"], renames.get(f["worksheet"], f["worksheet"]), f["target"])
        if f["target"] in applied and any(p[0] == f["ruleId"] and p[2] == f["target"] for p in present):
            problems.append(f"the output audit still reports the corrected {f['ruleId']} at {f['target']}")
        elif f["target"] not in applied and moved not in present:
            problems.append(f"the output audit lost the unselected {f['ruleId']} at {f['target']}")
    return problems


def _remediated(ctx, key, set_name, tag="shared", targets=None):
    ##  (record, None) for a completed remediation of a fixture with a decision set; the record
    ##  carries every problem observed while building it. (None, result) if it cannot be built.
    bucket = ctx.state.setdefault("remediated", {})
    slot = f"{key}|{set_name}|{tag}|{targets}"
    if slot in bucket:
        record = bucket[slot]
        return (None, _skip_failed(f"the {key} remediation ({set_name})", record["failed"])) if "failed" in record \
            else (record, None)

    def failed(result):
        bucket[slot] = {"failed": ctx.case.test_id}
        return None, result

    source, result = _audited(ctx, key, tag)
    if result:
        return failed(result)
    entry, upload = source["entry"], source["upload"]
    spec = _decision_spec(entry, set_name, targets)
    decisions, problems = _decisions(source, spec)
    if problems:
        return failed(CaseResult.failed("; ".join(problems) + "."))
    report_before = ctx.download(f"{_audit_path(upload)}/report", role="userA", session=source["session"])
    key_used = ctx.new_idempotency_key()
    response = _submit(ctx, source, decisions, key=key_used)
    if response.status >= 500:
        return failed(_system_failure("The decision request", response))
    if response.status != 202:
        return failed(CaseResult.failed(f"Expected 202 for the decision request; received {response.status}."))
    try:
        accepted = RemediationAccepted.model_validate(response.json())
    except ValidationError as problem:
        return failed(CaseResult.failed(f"202 body does not match RemediationAccepted ({_schema_problem(problem)})."))
    if accepted.sourceVersionId != upload["versionId"]:
        problems.append(f"sourceVersionId {accepted.sourceVersionId} is not the source version {upload['versionId']}")
    polled, finished = _poll_remediation(ctx, accepted.remediationId, source["session"])
    if polled.status >= 500:
        return failed(_system_failure("The remediation status read", polled))
    if not finished:
        return failed(CaseResult.failed("The remediation was still REMEDIATING at the poll budget."))
    try:
        remediation = RemediationResponse.model_validate(polled.json())
    except ValidationError as problem:
        return failed(CaseResult.failed(f"Remediation status does not match RemediationResponse "
                                        f"({_schema_problem(problem)})."))
    if remediation.status != "REMEDIATED":
        return failed(CaseResult.failed(f"The remediation ended {remediation.status} "
                                        f"({remediation.error.code if remediation.error else 'no error'})."))
    output_response = ctx.download(f"{OUTPUTS}/{remediation.outputId}/workbook", role="userA", session=source["session"])
    if output_response.status != 200:
        return failed(CaseResult.failed(f"The output download returned {output_response.status}."))
    output = output_response.body
    problems += [f"output download: {p}" for p in
                 download_problems(output_response, "workbook", generated_name(entry["upload_name"]))]
    output_upload = {"workbookId": upload["workbookId"], "versionId": remediation.outputVersionId,
                     "auditId": remediation.auditId}
    version_response = ctx.call("GET", _version_path(output_upload), role="userA", session=source["session"])
    version = None
    try:
        version = VersionResponse.model_validate(version_response.json()) if version_response.status == 200 else None
    except ValidationError as problem:
        problems.append(f"output version does not match VersionResponse ({_schema_problem(problem)})")
    if version is None:
        problems.append(f"the output version read returned {version_response.status}")
    else:
        if version.sourceVersionId != upload["versionId"]:
            problems.append(f"output sourceVersionId {version.sourceVersionId} is not the source version")
        if version.sha256 != hashlib.sha256(output).hexdigest():
            problems.append("the output version's sha256 does not match the downloaded output bytes")
        if version.status != "REMEDIATED":
            problems.append(f"the output version status is {version.status}, expected REMEDIATED")
    changes = [change_from_decision(d["target"], d["value"]) for d in spec if d["action"] == "APPLY"]
    if changes:
        problems += [f"preservation: {p}" for p in compare(source["bytes"], output, changes,
                                                            version.sha256 if version else None)]
    elif output != source["bytes"]:
        problems.append("a batch with no APPLY must produce byte-identical output, but the bytes differ")
    output_audit, result = _finished_audit(ctx, output_upload, "The output audit", session=source["session"], mark=False)
    if result:
        problems.append(result.message.rstrip("."))
        output_audit_dump = None
    else:
        output_audit_dump = output_audit.model_dump()
        problems += _output_audit_problems(source, spec, output_audit_dump)
    record = {"source": source, "spec": spec, "decisions": decisions, "remediation": remediation.model_dump(),
              "output": output, "output_upload": output_upload, "output_version": version.model_dump() if version else None,
              "output_audit": output_audit_dump, "problems": problems, "key": key_used,
              "accepted": response.json(), "report_before": report_before.body if report_before.status == 200 else None}
    bucket[slot] = record
    return record, None


##  ---- Uploads, audits and rule vectors ----

def upload_and_audit(case, ctx):
    ##  P4-CLEAN-ALL-SIX, P4-MANUAL-ONLY-STATUS: a fresh upload audited against the pack. With
    ##  no_apply, the review context must advertise no APPLY action.
    key = case.parameters["fixture"]
    upload = _upload_fixture(ctx, key)
    if upload.outcome != "pass":
        return upload
    result = _audit_fixture(ctx, key)
    if result.outcome != "pass" or not case.parameters.get("no_apply"):
        return result
    record = {"upload": ctx.state["uploads"][key], "audit": ctx.state["audits"][key]}
    response = ctx.call("GET", f"{_audit_path(record['upload'])}/review", role="userA")
    try:
        review = ReviewResponse.model_validate(response.json()) if response.status == 200 else None
    except ValidationError as problem:
        return CaseResult.failed(f"Review context does not match ReviewResponse ({_schema_problem(problem)}).")
    if review is None:
        return CaseResult.failed(f"{result.message} The review context read returned {response.status}.")
    offered = [item.findingId for item in review.items if "APPLY" in item.allowedActions]
    if offered:
        return CaseResult.failed(f"The all-manual audit advertises APPLY for {len(offered)} finding(s).")
    return CaseResult.passed(f"{result.message} No APPLY correction is advertised.")


def _in_scope(finding, rule, scope):
    if finding["ruleId"] != rule:
        return False
    if "worksheets" in scope and finding["worksheet"] in scope["worksheets"]:
        return True
    if "targets" in scope and finding["target"] in scope["targets"]:
        return True
    return any(finding["target"].startswith(p) for p in scope.get("target_prefixes", []))


def rule_vector(case, ctx):
    ##  P4-RULE-*: one fixture audited once, each case comparing the findings inside its own
    ##  scope with its vector (exact tuples, recomputed IDs, required limitation facts).
    key = case.parameters["fixture"]
    record, result = _audited(ctx, key, "rules")
    if result:
        return result
    entry = record["entry"]
    vector = entry.get("vectors", {}).get(case.parameters.get("vector", case.test_id)) if "rule" not in case.parameters \
        else {"rule": case.parameters["rule"], "scope": {"target_prefixes": [""]},
              "findings": [f for f in entry["findings"] if f["ruleId"] == case.parameters["rule"]],
              "limitation_facts": []}
    if vector is None:
        return CaseResult.error("tester", f"Fixture {key} has no vector for {case.test_id}.")
    ctx.mark()
    actual = [f for f in record["audit"]["findings"] if _in_scope(f, vector["rule"], vector["scope"])]
    got = sorted(tuple(f[k] for k in FINDING_KEY) for f in actual)
    want = sorted(tuple(f[k] for k in FINDING_KEY) for f in vector["findings"])
    problems = [f"missing {w[0]} {w[4]} at {w[3]}" for w in want if w not in got]
    problems += [f"unexpected {g[0]} {g[4]} at {g[3]}" for g in got if g not in want]
    for f in actual:
        expected_id = finding_id(entry["sha256"], ctx.manifest.ruleset_version, f["ruleId"], f["worksheet"], f["target"])
        if f["findingId"] != expected_id:
            problems.append(f"findingId at {f['target']} is {f['findingId']}, expected {expected_id}")
    if vector["limitation_facts"] and not record["audit"]["limitations"]:
        problems.append(f"limitations is empty; this vector requires: {' '.join(vector['limitation_facts'])}")
    return _verdict(f"{case.test_id} on {key}", problems,
                    f"{len(want)} expected {vector['rule']} finding(s) and no others in scope on {key}.")


def blocked_fixture(case, ctx):
    ##  A planned case whose fixture cannot be authored yet; reported as a skip with the reason.
    return CaseResult("skip", f"Not executed: fixture {case.parameters['blocked']} is not built yet "
                              f"({case.parameters['reason']}).")


##  ---- Review context ----

def review_context(case, ctx):
    ##  P4-REVIEW-CONTEXT: items follow the audit order with owner actions by classification and
    ##  the source's current values for supported findings.
    record, result = _audited(ctx, case.parameters["fixture"])
    if result:
        return result
    response = ctx.call("GET", f"{_audit_path(record['upload'])}/review", role="userA")
    if response.status >= 500:
        return _system_failure("The review context read", response)
    ctx.mark()
    if response.status != 200:
        return CaseResult.failed(f"Expected 200 for the review context; received {response.status}.")
    try:
        review = ReviewResponse.model_validate(response.json())
    except ValidationError as problem:
        return CaseResult.failed(f"Review context does not match ReviewResponse ({_schema_problem(problem)}).")
    audit, entry = record["audit"], record["entry"]
    problems = [f"{field} {getattr(review, field)} is not the audit's" for field in ("workbookId", "versionId", "auditId")
                if getattr(review, field) != audit[field]]
    if [i.findingId for i in review.items] != [f["findingId"] for f in audit["findings"]]:
        problems.append("items are not the audit's findings in audit order")
    by_id = {f["findingId"]: f for f in audit["findings"]}
    current = entry.get("review_current", {})
    for item in review.items:
        finding = by_id.get(item.findingId)
        if finding is None:
            continue
        if item.allowedActions != OWNER_ACTIONS[finding["classification"]]:
            problems.append(f"{finding['target']}: owner actions {item.allowedActions}, expected "
                            f"{OWNER_ACTIONS[finding['classification']]}")
        if finding["target"] in current and item.currentValue != current[finding["target"]]:
            problems.append(f"{finding['target']}: currentValue {item.currentValue}, expected {current[finding['target']]}")
    return _verdict("The review context", problems,
                    f"The review context lists the {len(review.items)} findings in order with owner actions and "
                    f"current values.")


def review_reviewer(case, ctx):
    ##  P4-REVIEW-REVIEWER: the granted reviewer sees the same items and values with no actions,
    ##  and cannot submit decisions.
    record, result = _audited(ctx, case.parameters["fixture"])
    if result:
        return result
    path = f"{_audit_path(record['upload'])}/review"
    owner, reviewer = (ctx.call("GET", path, role=role) for role in ("userA", "reviewer"))
    if reviewer.status >= 500:
        return _system_failure("The reviewer's review context read", reviewer)
    ctx.mark()
    if reviewer.status != 200:
        return CaseResult.failed(f"Expected 200 for the reviewer's review context; received {reviewer.status}.")
    try:
        mine, theirs = ReviewResponse.model_validate(owner.json()), ReviewResponse.model_validate(reviewer.json())
    except ValidationError as problem:
        return CaseResult.failed(f"Review context does not match ReviewResponse ({_schema_problem(problem)}).")
    problems = []
    if [(i.findingId, i.currentValue) for i in theirs.items] != [(i.findingId, i.currentValue) for i in mine.items]:
        problems.append("the reviewer's items or current values differ from the owner's")
    if any(i.allowedActions for i in theirs.items):
        problems.append("the reviewer is offered actions")
    spec = _decision_spec(record["entry"], "mixed") if "decision_sets" in record["entry"] else []
    decisions, _ = _decisions(record, spec[:1])
    submitted = _submit(ctx, record, decisions, role="reviewer")
    problems += _error_problems(submitted, 403, None, "the reviewer's decision request")
    return _verdict("The reviewer's review", problems,
                    "The reviewer sees the owner's items and values with no actions, and a decision request is 403.")


##  ---- New versions, history and re-audits ----

def _fresh_upload(ctx, key, name=None):
    response = ctx.upload(WORKBOOKS, role="userA", fixture=key, name=name)
    accepted = _accepted(ctx, response, f"The {key} upload", mark=False)
    return (UploadResponse.model_validate(response.json()).model_dump(), None) if accepted.outcome == "pass" \
        else (None, accepted)


def _new_version(ctx, workbook_id, key, name):
    data = ctx.fixture(key)[0]
    return ctx.call("POST", f"{WORKBOOKS}/{workbook_id}/versions", role="userA", files=upload_files(name, data))


def version_new(case, ctx):
    ##  P4-VERSION-NEW: operation 3 with changed bytes under the same filename keeps the workbook
    ##  ID, makes fresh version and audit IDs with a null parent, and leaves the first version.
    key, other = case.parameters["fixture"], case.parameters["new_bytes"]
    first, result = _fresh_upload(ctx, key)
    if result:
        return result
    name = ctx.fixture_entry(key)["upload_name"]
    return _version_case(ctx, first, key, other, name, "changed bytes")


def version_same_bytes(case, ctx):
    ##  P4-VERSION-SAME-BYTES: identical bytes still make a fresh version with the same hash.
    key = case.parameters["fixture"]
    first, result = _fresh_upload(ctx, key)
    if result:
        return result
    return _version_case(ctx, first, key, key, ctx.fixture_entry(key)["upload_name"], "the same bytes")


def _version_case(ctx, first, key, new_key, name, what):
    before = ctx.call("GET", _version_path(first), role="userA").json()
    response = _new_version(ctx, first["workbookId"], new_key, name)
    if response.status >= 500:
        return _system_failure("The new-version upload", response)
    ctx.mark()
    if response.status != 202:
        return CaseResult.failed(f"Expected 202 for a new version with {what}; received {response.status}.")
    try:
        second = UploadResponse.model_validate(response.json()).model_dump()
    except ValidationError as problem:
        return CaseResult.failed(f"202 body does not match UploadResponse ({_schema_problem(problem)}).")
    problems = []
    if second["workbookId"] != first["workbookId"]:
        problems.append("the new version has a different workbookId")
    if second["versionId"] == first["versionId"] or second["auditId"] == first["auditId"]:
        problems.append("the new version reused the first version's or audit's ID")
    version, result = _read_version(ctx, ctx.call("GET", _version_path(second), role="userA"), "The new version read")
    if result:
        problems.append(result.message.rstrip("."))
    else:
        if version.sourceVersionId is not None:
            problems.append("an uploaded version has a non-null sourceVersionId")
        if version.sha256 != hashlib.sha256(ctx.fixture(new_key)[0]).hexdigest():
            problems.append("the new version's sha256 is not the hash of the uploaded bytes")
        if version.fileName != name:
            problems.append(f"fileName {version.fileName!r}, expected {name!r}")
    after = ctx.call("GET", _version_path(first), role="userA").json()
    if isinstance(before, dict) and isinstance(after, dict):
        stable = {k: before.get(k) for k in ("sha256", "fileName", "createdAt", "sourceVersionId")}
        if stable != {k: after.get(k) for k in stable}:
            problems.append("the first version's metadata changed")
    history, problem = _history(ctx, first["workbookId"])
    if problem:
        problems.append(problem)
    elif [v["versionId"] for v in history["versions"]] != [first["versionId"], second["versionId"]]:
        problems.append("history does not list the two versions in upload order")
    return _verdict(f"The new version with {what}", problems,
                    f"A new version with {what} kept the workbook ID, got fresh IDs and a null parent, and history "
                    f"lists both versions in order.")


def _reaudit(ctx, upload, body="absent", session=True):
    kwargs = {} if body == "absent" else {"json_body": body}
    return ctx.call("POST", f"{_version_path(upload)}/audits", role="userA", session=session, **kwargs)


def _accepted_reaudit(ctx, upload, response):
    ##  (ReauditResponse dict, problems)
    if response.status != 202:
        return None, [f"expected 202 for a manual re-audit; received {response.status}"]
    try:
        reaudit = ReauditResponse.model_validate(response.json()).model_dump()
    except ValidationError as problem:
        return None, [f"202 body does not match ReauditResponse ({_schema_problem(problem)})"]
    return reaudit, ([] if reaudit["versionId"] == upload["versionId"] else ["the re-audit names another version"])


def reaudit(case, ctx):
    ##  P4-REAUDIT: absent body, {} and {"reason": "MANUAL_REAUDIT"} each start a fresh audit on
    ##  the same version; earlier audit and report bytes stay unchanged.
    record, result = _audited(ctx, case.parameters["fixture"], "reaudit")
    if result:
        return result
    upload, first = record["upload"], record["audit"]
    report = ctx.download(f"{_audit_path(upload)}/report", role="userA")
    problems, ids = [], [first["auditId"]]
    for body in ("absent", {}, {"reason": "MANUAL_REAUDIT"}):
        response = _reaudit(ctx, upload, body)
        if response.status >= 500:
            return _system_failure("The manual re-audit", response)
        ctx.mark()
        accepted, trouble = _accepted_reaudit(ctx, upload, response)
        problems += [f"{json.dumps(body) if body != 'absent' else 'absent body'}: {t}" for t in trouble]
        if accepted is None:
            continue
        ids.append(accepted["auditId"])
        audit, result = _finished_audit(ctx, {**upload, "auditId": accepted["auditId"]}, "The re-audit", mark=False)
        if result:
            problems.append(result.message.rstrip("."))
    if len(set(ids)) != len(ids):
        problems.append("a re-audit reused an earlier audit ID")
    if ctx.call("GET", _audit_path(upload), role="userA").json() != first:
        problems.append("the first audit changed after the re-audits")
    if report.status == 200 and ctx.download(f"{_audit_path(upload)}/report", role="userA").body != report.body:
        problems.append("the first audit's report bytes changed after the re-audits")
    history, problem = _history(ctx, upload["workbookId"])
    if problem:
        problems.append(problem)
    elif [a["auditId"] for a in history["audits"]] != ids:
        problems.append("history does not list the audits in acceptance order")
    return _verdict("The manual re-audits", problems,
                    "Three manual re-audit forms each started a fresh audit on the same version; the first audit and "
                    "its report are unchanged.")


def reaudit_invalid(case, ctx):
    ##  P4-REAUDIT-INVALID: a wrong reason or an unknown field is 400 INVALID_REQUEST, with no audit.
    record, result = _audited(ctx, case.parameters["fixture"], "reaudit-invalid")
    if result:
        return result
    upload, problems = record["upload"], []
    for body in ({"reason": "SCHEDULED"}, {"reason": "MANUAL_REAUDIT", "ruleset": "1.0.0"}):
        response = _reaudit(ctx, upload, body)
        if response.status >= 500:
            return _system_failure("The invalid re-audit", response)
        ctx.mark()
        problems += _error_problems(response, 400, "INVALID_REQUEST", json.dumps(body))
    history, problem = _history(ctx, upload["workbookId"])
    if problem:
        problems.append(problem)
    elif len(history["audits"]) != 1:
        problems.append(f"history lists {len(history['audits'])} audits after rejected re-audits, expected 1")
    return _verdict("Invalid re-audit requests", problems,
                    "A wrong reason and an unknown field were each 400 INVALID_REQUEST, and no audit was added.")


def reaudit_determinism(case, ctx):
    ##  P4-REAUDIT-DETERMINISM: five manual re-audits match the first audit exactly (status,
    ##  findings with IDs and prose, limitations) under fresh audit IDs.
    record, result = _audited(ctx, case.parameters["fixture"], "reaudit-determinism")
    if result:
        return result
    upload, first, problems, ids = record["upload"], record["audit"], [], {record["audit"]["auditId"]}
    for run in range(1, case.parameters.get("runs", 5) + 1):
        response = _reaudit(ctx, upload, {})
        if response.status >= 500:
            return _system_failure(f"Re-audit {run}", response)
        accepted, trouble = _accepted_reaudit(ctx, upload, response)
        problems += [f"re-audit {run}: {t}" for t in trouble]
        if accepted is None:
            continue
        audit, result = _finished_audit(ctx, {**upload, "auditId": accepted["auditId"]}, f"Re-audit {run}")
        if result:
            problems.append(result.message.rstrip("."))
            continue
        current = audit.model_dump()
        problems += [f"re-audit {run}: {field} differs" for field in ("status", "rulesetVersion", "findings", "limitations")
                     if current[field] != first[field]]
        if current["auditId"] in ids:
            problems.append(f"re-audit {run} reused an audit ID")
        ids.add(current["auditId"])
    return _verdict("Five manual re-audits", problems,
                    "Five manual re-audits matched the first audit exactly under fresh audit IDs.")


##  ---- Source and output downloads ----

def source_before(case, ctx):
    ##  P4-SOURCE-BEFORE: the source download is the uploaded bytes with correct headers.
    record, result = _audited(ctx, case.parameters["fixture"])
    if result:
        return result
    response = ctx.download(f"{_version_path(record['upload'])}/source", role="userA")
    if response.status >= 500:
        return _system_failure("The source download", response)
    ctx.mark()
    if response.status != 200:
        return CaseResult.failed(f"Expected 200 for the source download; received {response.status}.")
    problems = download_problems(response, "workbook", record["entry"]["upload_name"])
    if response.body != record["bytes"]:
        problems.append("the downloaded bytes are not the uploaded bytes")
    return _verdict("The source download", problems, "The source download is the uploaded bytes with correct headers.")


def download_large(case, ctx):
    ##  P4-DOWNLOAD-LARGE: a source over 2 MiB, and its remediated output, download whole. The
    ##  output's size depends on the system's compression, so it is reported, not required.
    record, result = _remediated(ctx, case.parameters["fixture"], case.parameters["set"])
    if result:
        return result
    ctx.mark()
    source = ctx.download(f"{_version_path(record['source']['upload'])}/source", role="userA")
    problems = list(record["problems"])
    if len(record["source"]["bytes"]) <= 2 * 2 ** 20:
        return CaseResult.error("tester", f"Fixture {record['source']['key']} is not over 2 MiB.")
    if source.status != 200 or source.body != record["source"]["bytes"]:
        problems.append(f"the large source download returned {source.status} or different bytes")
    return _verdict("Large downloads", problems,
                    f"A {len(record['source']['bytes']):,}-byte source and its {len(record['output']):,}-byte output "
                    f"downloaded whole.")


##  ---- Decisions, corrections and their follow-ups ----

def remediation(case, ctx):
    ##  P4-DECISIONS-MIXED, P4-APPLY-*: submit a decision set, wait for REMEDIATED, then judge the
    ##  output with the comparator, its provenance, and its six-rule audit.
    record, result = _remediated(ctx, case.parameters["fixture"], case.parameters["set"],
                                 targets=tuple(case.parameters["targets"]) if "targets" in case.parameters else None)
    if result:
        return result
    ctx.mark()
    applied = sum(1 for d in record["spec"] if d["action"] == "APPLY")
    return _verdict(f"The {case.parameters['set']} remediation of {case.parameters['fixture']}", record["problems"],
                    f"REMEDIATED with {applied} approved change(s): the output differs from the source by exactly those "
                    f"changes, its provenance is coherent, and its audit dropped only the corrected findings.")


def remediation_followup(case, ctx):
    ##  P4-OUTPUT-HASH, -SOURCE-AFTER, -PRESERVATION, -OUTPUT-AUDIT, -REPORT-COMPLETE, -REPORT-STABLE,
    ##  -HISTORY, -REMEDIATED-STATUS on an already built remediation.
    record, result = _remediated(ctx, case.parameters["fixture"], case.parameters["set"])
    if result:
        return result
    aspect = case.parameters["aspect"]
    ctx.mark()
    problems = globals()[f"_aspect_{aspect}"](ctx, record)
    return _verdict(f"{case.test_id} ({aspect})", problems, f"{aspect.replace('_', ' ')} verified on the remediation.")


def _aspect_output_hash(ctx, record):
    out = record["output_upload"]
    again = ctx.download(f"{OUTPUTS}/{record['remediation']['outputId']}/workbook", role="userA")
    as_source = ctx.download(f"{_version_path(out)}/source", role="userA")
    problems = []
    if again.body != record["output"]:
        problems.append("repeated output downloads differ")
    if as_source.status != 200 or as_source.body != record["output"]:
        problems.append("the output version's source download differs from the output download")
    if record["output_version"] and record["output_version"]["sha256"] != hashlib.sha256(record["output"]).hexdigest():
        problems.append("the output version's sha256 does not match the output bytes")
    return problems


def _aspect_source_after(ctx, record):
    source = record["source"]
    problems = []
    if ctx.download(f"{_version_path(source['upload'])}/source", role="userA").body != source["bytes"]:
        problems.append("the source download changed after remediation")
    if ctx.call("GET", _audit_path(source["upload"]), role="userA").json() != source["audit"]:
        problems.append("the source audit changed after remediation")
    after = ctx.download(f"{_audit_path(source['upload'])}/report", role="userA")
    if record["report_before"] is None or after.body != record["report_before"]:
        problems.append("the source audit's report bytes changed after remediation (or could not be read)")
    return problems


def _aspect_preservation(ctx, record):
    return [p for p in record["problems"] if p.startswith("preservation:")]


def _aspect_output_audit(ctx, record):
    audit = record["output_audit"]
    if audit is None:
        return ["the output audit did not finish"]
    problems = [] if audit["rulesetVersion"] == ctx.manifest.ruleset_version else ["the output audit uses another ruleset"]
    return problems + [p for p in record["problems"] if "output audit" in p]


def _aspect_report_complete(ctx, record):
    out = record["output_upload"]
    response = ctx.download(f"{_audit_path(out)}/report", role="userA")
    if response.status != 200:
        return [f"the output audit report download returned {response.status}"]
    try:
        report = AuditReport.model_validate(response.json())
    except ValidationError as problem:
        return [f"the output report does not match AuditReport ({_schema_problem(problem)})"]
    problems = [f"{p}" for p in download_problems(response, "report", f"audit-{out['auditId']}.json")]
    audit, source = record["output_audit"] or {}, record["source"]
    if report.findings and [f.model_dump() for f in report.findings] != audit.get("findings"):
        problems.append("report findings differ from the output audit")
    if len(report.checksPerformed) != 6:
        problems.append(f"checksPerformed lists {len(report.checksPerformed)} checks, expected all six")
    submitted = {(d["findingId"], d["action"], json.dumps(d.get("value"), sort_keys=True)) for d in record["decisions"]}
    reported = {(d.findingId, d.action, json.dumps(d.value, sort_keys=True)) for d in report.decisions}
    if submitted != reported:
        problems.append("report decisions differ from the submitted decisions")
    if any(d.sourceAuditId != source["audit"]["auditId"] for d in report.decisions):
        problems.append("a report decision names another source audit")
    if {c.findingId for c in report.approvedChanges} != {d["findingId"] for d in record["decisions"] if d["action"] == "APPLY"}:
        problems.append("approvedChanges are not exactly the APPLY decisions")
    if (report.remediationId, report.outputVersionId, report.outputId) != (
            record["remediation"]["remediationId"], out["versionId"], record["remediation"]["outputId"]):
        problems.append("report provenance IDs do not match the remediation")
    if report.sourceVersionId != source["upload"]["versionId"] or report.sha256 != hashlib.sha256(record["output"]).hexdigest():
        problems.append("report sourceVersionId or sha256 does not describe the output")
    return problems


def _aspect_report_stable(ctx, record):
    out, source = record["output_upload"], record["source"]
    first = ctx.download(f"{_audit_path(out)}/report", role="userA")
    second = ctx.download(f"{_audit_path(out)}/report", role="userA")
    problems = [] if first.status == 200 and first.body == second.body else ["repeated report downloads differ"]
    response = _reaudit(ctx, out, {})
    accepted, trouble = _accepted_reaudit(ctx, out, response)
    problems += trouble
    if accepted:
        _finished_audit(ctx, {**out, "auditId": accepted["auditId"]}, "The output re-audit", mark=False)
    if ctx.download(f"{_audit_path(out)}/report", role="userA").body != first.body:
        problems.append("a later re-audit rewrote the earlier output report")
    if record["report_before"] is not None and \
            ctx.download(f"{_audit_path(source['upload'])}/report", role="userA").body != record["report_before"]:
        problems.append("the source report changed after decisions and re-audits")
    return problems


def _aspect_history(ctx, record):
    source, out = record["source"]["upload"], record["output_upload"]
    history, problem = _history(ctx, source["workbookId"])
    if problem:
        return [problem]
    versions = [(v["versionId"], v["sourceVersionId"]) for v in history["versions"]]
    problems = []
    if versions[:1] != [(source["versionId"], None)] or (out["versionId"], source["versionId"]) not in versions:
        problems.append(f"history versions {versions} do not show the output derived from the source")
    audits = [a["auditId"] for a in history["audits"]]
    for audit_id in (source["auditId"], out["auditId"]):
        if audit_id not in audits:
            problems.append(f"history omits audit {audit_id}")
    if audits.index(source["auditId"]) > audits.index(out["auditId"]) if out["auditId"] in audits else False:
        problems.append("history lists the output audit before the source audit")
    return problems


def _aspect_remediated_status(ctx, record):
    version = ctx.call("GET", _version_path(record["output_upload"]), role="userA").json()
    problems = [] if isinstance(version, dict) and version.get("status") == "REMEDIATED" else \
        [f"the output version status is {version.get('status') if isinstance(version, dict) else version}"]
    audit = record["output_audit"] or {}
    if audit.get("status") not in ("REVIEW_REQUIRED", "REMEDIATION_AVAILABLE", "AUDIT_COMPLETE"):
        problems.append(f"the output audit status is {audit.get('status')}")
    return problems


##  ---- Rejected decision requests ----

def _invalid_bodies(ctx, record, condition):
    ##  [(label, body, status, code, kwargs)] for one P4-REJECT-* condition.
    audit_id, ids = record["audit"]["auditId"], _ids_by_target(record["audit"])
    by_rule = {}
    for f in record["audit"]["findings"]:
        by_rule.setdefault((f["ruleId"], f["classification"]), f["findingId"])
    alt, name = by_rule.get(("ALT_TEXT", "REQUIRES_USER_INPUT")), by_rule.get(("WORKSHEET_NAME", "REQUIRES_USER_INPUT"))
    link, header = by_rule.get(("LINK_TEXT", "REQUIRES_USER_INPUT")), by_rule.get(("TABLE_HEADER", "REQUIRES_USER_INPUT"))
    good_alt = {"findingId": alt, "action": "APPLY", "value": {"title": "Team logo", "description": "Team 12 logo."}}

    def body(*decisions):
        return {"auditId": audit_id, "decisions": list(decisions)}

    def apply(finding, value):
        return body({"findingId": finding, "action": "APPLY", "value": value})
    table = {
        "EMPTY": [("empty decisions", body(), 400, "INVALID_REQUEST")],
        "UNKNOWN-FIELD": [("extra envelope field", {**body(good_alt), "note": "x"}, 400, "INVALID_REQUEST"),
                          ("extra decision field", body({**good_alt, "note": "x"}), 400, "INVALID_REQUEST")],
        "DUPLICATE": [("same finding twice", body(good_alt, {"findingId": alt, "action": "DECLINE"}), 400,
                       "DUPLICATE_DECISION")],
        "UNKNOWN-FINDING": [("unknown finding", body({"findingId": "f" * 64, "action": "DECLINE"}), 404,
                             "FINDING_NOT_FOUND")],
        "VALUE-MISSING": [("APPLY without value", body({"findingId": alt, "action": "APPLY"}), 400, "MISSING_VALUE")],
        "VALUE-WRONG-SHAPE": [("string value", apply(alt, "Team logo"), 422, "INVALID_CORRECTION"),
                              ("name value on alt text", apply(alt, {"name": "Logo"}), 422, "INVALID_CORRECTION"),
                              ("unknown value field", apply(alt, {"title": "T", "description": "D", "x": 1}), 422,
                               "INVALID_CORRECTION"),
                              ("null value", apply(alt, None), 422, "INVALID_CORRECTION")],
        "VALUE-ON-DECLINE": [("DECLINE with value", body({"findingId": alt, "action": "DECLINE", "value": {"title": "T",
                              "description": "D"}}), 400, "INVALID_REQUEST"),
                             ("MANUAL_REVIEW with value", body({"findingId": alt, "action": "MANUAL_REVIEW",
                              "value": {"title": "T", "description": "D"}}), 400, "INVALID_REQUEST")],
        "ALT-BLANK": [("blank title", apply(alt, {"title": "   ", "description": "D"}), 422, "INVALID_CORRECTION"),
                      ("blank description", apply(alt, {"title": "T", "description": "　"}), 422, "INVALID_CORRECTION")],
        "ALT-TOO-LONG": [("201-code-point title", apply(alt, {"title": "t" * 201, "description": "D"}), 422,
                          "INVALID_CORRECTION"),
                         ("801-code-point description", apply(alt, {"title": "T", "description": "d" * 801}), 422,
                          "INVALID_CORRECTION")],
        "NAME-INVALID": [(f"name {n!r}", apply(name, {"name": n}), 422,
                          "UNSUPPORTED_CORRECTION" if n == "sheet1" else
                          "CONFLICTING_CORRECTIONS" if n == "Summary" else "INVALID_CORRECTION")
                         for n in ("n" * 32, " Costs", "Costs:2026", "Sheet9", "History", "sheet1", "Sheet1", "Summary")],
        "LINK-AMBIGUOUS": [("ambiguous label", apply(link, {"text": "Click here."}), 422, "INVALID_CORRECTION")],
        "HEADER-ROW": [("wrong row", apply(header, {"headerRow": 2}), 422, "INVALID_CORRECTION"),
                       ("boolean row", apply(header, {"headerRow": True}), 422, "INVALID_CORRECTION"),
                       ("replacement labels", apply(header, {"headerRow": 1, "labels": ["A", "B", "C"]}), 422,
                        "INVALID_CORRECTION")],
        "DECISIONS-OVER": [("1001 decisions", body(*({"findingId": f"{i:064x}", "action": "DECLINE"} for i in range(1001))),
                            400, "INVALID_REQUEST")],
        "MISSING-KEY": [("no Idempotency-Key", body(good_alt), 400, "IDEMPOTENCY_KEY_REQUIRED", {"idempotency_key": ""}),
                        ("malformed Idempotency-Key", body(good_alt), 400, "IDEMPOTENCY_KEY_REQUIRED",
                         {"idempotency_key": "not a valid key!"})],
    }
    if condition == "NAME-SWAP":
        decisions, _ = _decisions(record, record["entry"]["decision_sets"]["conflicting_names"])
        return [("two sheets renamed to one name", body(*decisions), 422, "CONFLICTING_CORRECTIONS")]
    if condition == "MANUAL-APPLY":
        return [(attempt["why"], apply(ids.get(attempt["target"]), attempt["value"]), 422, "UNSUPPORTED_CORRECTION")
                for attempt in record["entry"]["apply_attempts"]]
    return table[condition]


def reject_decisions(case, ctx):
    ##  P4-REJECT-*: each variant is rejected with its exact status and code, and no remediation,
    ##  output or history entry appears.
    condition = case.parameters["condition"]
    if condition in ("CROSS-AUDIT-FINDING", "STALE-AUDIT", "AUDIT-PROCESSING", "AUDIT-FAILED"):
        return globals()[f"_reject_{condition.lower().replace('-', '_')}"](case, ctx)
    record, result = _audited(ctx, case.parameters["fixture"])
    if result:
        return result
    before, problem = _history(ctx, record["upload"]["workbookId"])
    problems = [problem] if problem else []
    for label, body, status, code, *extra in _invalid_bodies(ctx, record, condition):
        kwargs = extra[0] if extra else {}
        key = kwargs.get("idempotency_key")
        response = ctx.call("POST", f"{_version_path(record['upload'])}/remediations", role="userA", json_body=body,
                            idempotency_key=(key or None) if key is not None else ctx.new_idempotency_key())
        if response.status >= 500:
            return _system_failure(f"The {label} request", response)
        ctx.mark()
        problems += _error_problems(response, status, code, label)
    after, problem = _history(ctx, record["upload"]["workbookId"])
    if problem or after != before:
        problems.append("history changed after rejected decision requests")
    return _verdict(f"{condition} decision requests", problems,
                    f"Every {condition} variant was rejected with its exact status and code, leaving history unchanged.")


def _single_reject(ctx, record, body, status, code, what, session=None):
    response = ctx.call("POST", f"{_version_path(record['upload'])}/remediations", role="userA",
                        session=record["session"] if session is None else session, json_body=body,
                        idempotency_key=ctx.new_idempotency_key())
    if response.status >= 500:
        return None, _system_failure(what, response)
    ctx.mark()
    return response, None


def _reject_cross_audit_finding(case, ctx):
    record, result = _audited(ctx, case.parameters["fixture"])
    other, other_result = _audited(ctx, "seeded_all_six", "cross-audit")
    if result or other_result:
        return result or other_result
    foreign = other["audit"]["findings"][0]["findingId"]
    body = {"auditId": record["audit"]["auditId"], "decisions": [{"findingId": foreign, "action": "DECLINE"}]}
    response, result = _single_reject(ctx, record, body, 404, "FINDING_NOT_FOUND", "The cross-audit decision")
    return result or _verdict("A finding from another version", _error_problems(response, 404, "FINDING_NOT_FOUND",
                              "cross-audit finding"), "A finding from another version's audit was 404 FINDING_NOT_FOUND.")


def _reject_stale_audit(case, ctx):
    record, result = _audited(ctx, case.parameters["fixture"], "stale")
    if result:
        return result
    response = _reaudit(ctx, record["upload"], {})
    accepted, trouble = _accepted_reaudit(ctx, record["upload"], response)
    if accepted is None:
        return CaseResult.failed(f"The re-audit needed for a stale audit was not accepted ({'; '.join(trouble)}).")
    _finished_audit(ctx, {**record["upload"], "auditId": accepted["auditId"]}, "The newer audit", mark=False)
    decisions, _ = _decisions(record, _decision_spec(record["entry"], "mixed")[:1])
    body = {"auditId": record["audit"]["auditId"], "decisions": decisions}
    response, result = _single_reject(ctx, record, body, 409, "STALE_AUDIT", "The stale-audit decision")
    return result or _verdict("Decisions on a superseded audit", _error_problems(response, 409, "STALE_AUDIT", "stale audit"),
                              "Decisions referencing a superseded audit were 409 STALE_AUDIT.")


def _expected_ids(entry, ruleset):
    return {f["target"]: finding_id(entry["sha256"], ruleset, f["ruleId"], f["worksheet"], f["target"])
            for f in entry["findings"]}


def _reject_audit_processing(case, ctx):
    key = case.parameters["fixture"]
    entry, problem = _fixture(ctx, key, "accepted")
    if problem:
        return problem
    upload, result = _fresh_upload(ctx, key)
    if result:
        return result
    ids = _expected_ids(entry, ctx.manifest.ruleset_version)
    target = _decision_spec(entry, "mixed")[0]["target"]
    body = {"auditId": upload["auditId"], "decisions": [{"findingId": ids[target], "action": "DECLINE"}]}
    record = {"upload": upload, "session": True}
    response, result = _single_reject(ctx, record, body, 409, "ACTIVE_OPERATION", "The decision on a running audit")
    if result:
        return result
    if response.status == 202:
        state = ctx.call("GET", _audit_path(upload), role="userA").json()
        if isinstance(state, dict) and state.get("status") != "PROCESSING":
            return CaseResult("skip", "Not executed: the audit finished before the decision request arrived, so the "
                                      "running-audit condition could not be produced.")
    return _verdict("Decisions on a running audit", _error_problems(response, 409, "ACTIVE_OPERATION", "running audit"),
                    "Decisions on a still-running audit were 409 ACTIVE_OPERATION.")


def _reject_audit_failed(case, ctx):
    ##  A separate fault session makes the latest audit fail; its ID joins the run record.
    key = case.parameters["fixture"]
    entry, problem = _fixture(ctx, key, "accepted")
    if problem:
        return problem
    session_id, response = _fault_setup_call(ctx, FAULT_SETUP)
    if response.status != 201:
        return CaseResult.failed(f"A fault session for this case could not be created ({response.status}).")
    upload_response = ctx.upload(WORKBOOKS, role="userA", fixture=key, session=session_id)
    accepted = _accepted(ctx, upload_response, f"The {key} upload in a fault session", mark=False)
    if accepted.outcome != "pass":
        return accepted
    upload = UploadResponse.model_validate(upload_response.json()).model_dump()
    audit, result = _finished_audit(ctx, upload, "The fault-session audit", session=session_id, mark=False)
    if result or audit.status != "PROCESSING_FAILED":
        return result or CaseResult.failed(f"The fault-session audit ended {audit.status}, not PROCESSING_FAILED.")
    ids = _expected_ids(entry, ctx.manifest.ruleset_version)
    body = {"auditId": upload["auditId"],
            "decisions": [{"findingId": ids[_decision_spec(entry, "mixed")[0]["target"]], "action": "DECLINE"}]}
    record = {"upload": upload, "session": session_id}
    response, result = _single_reject(ctx, record, body, 409, "AUDIT_NOT_READY", "The decision on a failed audit")
    return result or _verdict("Decisions on a failed audit", _error_problems(response, 409, "AUDIT_NOT_READY", "failed audit"),
                              "Decisions on a failed latest audit were 409 AUDIT_NOT_READY.")


def batch_atomic(case, ctx):
    ##  P4-BATCH-ATOMIC-REJECTION: one valid APPLY plus one invalid decision rejects the batch.
    record, result = _audited(ctx, case.parameters["fixture"])
    if result:
        return result
    before, _ = _history(ctx, record["upload"]["workbookId"])
    spec = _decision_spec(record["entry"], "combined")
    decisions, _ = _decisions(record, spec[:2])
    decisions[1] = {**decisions[1], "value": {"text": "click here"}} if decisions[1].get("value", {}).get("text") \
        else {**decisions[1], "value": {"title": "  ", "description": "D"}}
    response = _submit(ctx, record, decisions)
    if response.status >= 500:
        return _system_failure("The mixed valid and invalid batch", response)
    ctx.mark()
    problems = _error_problems(response, 422, "INVALID_CORRECTION", "a batch with one invalid decision")
    after, _ = _history(ctx, record["upload"]["workbookId"])
    if after != before:
        problems.append("history changed, so part of the rejected batch was applied")
    return _verdict("The partly invalid batch", problems,
                    "A batch with one valid and one invalid decision was rejected whole; nothing was applied.")


def idempotency(case, ctx):
    ##  P4-IDEMPOTENCY-REPLAY, -CONFLICT, -INVALID-FIRST, each on its own upload.
    mode = case.parameters["mode"]
    record, result = _audited(ctx, case.parameters["fixture"], f"idempotency-{mode}")
    if result:
        return result
    decisions, _ = _decisions(record, _decision_spec(record["entry"], "mixed"))
    key, problems = ctx.new_idempotency_key(), []
    if mode == "INVALID-FIRST":
        bad = _submit(ctx, record, [{**decisions[0], "value": {"title": " ", "description": "D"}}], key=key)
        ctx.mark()
        if bad.status not in (400, 422):
            problems.append(f"the invalid first request returned {bad.status}, expected a 400 or 422 rejection")
        good = _submit(ctx, record, decisions, key=key)
        problems += [] if good.status == 202 else [f"the corrected request with the same key returned {good.status}"]
        return _verdict("Key reuse after an invalid request", problems,
                        "A rejected request did not consume its key; the corrected body was accepted with it.")
    first = _submit(ctx, record, decisions, key=key)
    if first.status != 202:
        return CaseResult.failed(f"Expected 202 for the first keyed request; received {first.status}.")
    ctx.mark()
    accepted = first.json()
    if mode == "REPLAY":
        pending = _submit(ctx, record, decisions, key=key)
        problems += [] if (pending.status, pending.json()) == (202, accepted) else ["a replay while pending differed"]
        _poll_remediation(ctx, accepted["remediationId"])
        reordered = [json.loads(json.dumps(d, sort_keys=True)) for d in reversed(decisions)]
        body = {"decisions": reordered, "auditId": record["audit"]["auditId"]}
        after = _submit(ctx, record, None, key=key, body=body)
        problems += [] if (after.status, after.json()) == (202, accepted) else \
            ["a replay after completion with reordered decisions and keys differed"]
        history, problem = _history(ctx, record["upload"]["workbookId"])
        outputs = [v for v in (history or {}).get("versions", []) if v["sourceVersionId"] == record["upload"]["versionId"]]
        problems += [problem] if problem else ([] if len(outputs) == 1 else [f"{len(outputs)} outputs exist, expected 1"])
        return _verdict("Idempotent replays", problems,
                        "Replays while pending and after completion returned the original 202; exactly one output exists.")
    changed = _submit(ctx, record, decisions[:-1], key=key)
    problems += _error_problems(changed, 409, "IDEMPOTENCY_CONFLICT", "a changed body under the same key")
    status = ctx.call("GET", f"{REMEDIATIONS}/{accepted['remediationId']}", role="userA").json()
    if not isinstance(status, dict) or status.get("remediationId") != accepted["remediationId"]:
        problems.append("the first remediation is no longer readable")
    return _verdict("A changed body under a used key", problems,
                    "A changed body under the same key was 409 IDEMPOTENCY_CONFLICT; the first remediation is intact.")


##  ---- The access matrix ----

READS = {"REMEDIATION", "OUTPUT", "HISTORY", "SOURCE", "REPORT", "REVIEW"}
CONDITIONS = {"UNAUTHENTICATED": (401, None), "INVALID-TOKEN": (401, None), "FOREIGN": (403, None),
              "UNKNOWN": (404, None), "WRONG-NAMESPACE": (404, None), "REVIEWER-WRITE-REFUSED": (403, None),
              "REVIEWER-READ": (200, None), "TEST-ADMIN": (403, "FORBIDDEN")}


def _other_namespace(ctx):
    ##  A second prepared session: resources of the main session must not resolve under it.
    if "other_namespace" not in ctx.state:
        session_id, response = _fault_setup_call(ctx, {})
        ctx.state["other_namespace"] = session_id if response.status == 201 else None
    return ctx.state["other_namespace"]


def _access_request(ctx, operation, record, remediated, unknown):
    upload = dict(record["upload"])
    remediation = remediated["remediation"] if remediated else {}
    if unknown:
        upload = {k: f"unknown-{uuid.uuid4().hex[:12]}" for k in upload}
        remediation = {k: f"unknown-{uuid.uuid4().hex[:12]}" for k in ("remediationId", "outputId")}
    decisions, _ = _decisions(record, _decision_spec(record["entry"], "mixed"))
    return {
        "NEW-VERSION": ("POST", f"{WORKBOOKS}/{upload['workbookId']}/versions",
                        {"files": upload_files(record["entry"]["upload_name"], record["bytes"])}),
        "REAUDIT": ("POST", f"{_version_path(upload)}/audits", {"json_body": {}}),
        "DECISIONS": ("POST", f"{_version_path(upload)}/remediations",
                      {"json_body": {"auditId": upload["auditId"], "decisions": decisions},
                       "idempotency_key": ctx.new_idempotency_key()}),
        "REMEDIATION": ("GET", f"{REMEDIATIONS}/{remediation.get('remediationId')}", {}),
        "OUTPUT": ("GET", f"{OUTPUTS}/{remediation.get('outputId')}/workbook", {"binary": True}),
        "HISTORY": ("GET", f"{WORKBOOKS}/{upload['workbookId']}/history", {}),
        "SOURCE": ("GET", f"{_version_path(upload)}/source", {"binary": True}),
        "REPORT": ("GET", f"{_audit_path(upload)}/report", {"binary": True}),
        "REVIEW": ("GET", f"{_audit_path(upload)}/review", {}),
    }[operation]


def access(case, ctx):
    ##  P4-ACCESS-<OPERATION>-<CONDITION>: one cell of the access matrix on the mixed_decisions
    ##  resources. Writes must leave history unchanged; reads must not leak.
    operation, condition = case.parameters["operation"], case.parameters["condition"]
    record, result = _audited(ctx, case.parameters["fixture"])
    if result:
        return result
    remediated = None
    if operation in ("REMEDIATION", "OUTPUT"):
        remediated, result = _remediated(ctx, case.parameters["fixture"], "mixed")
        if result:
            return result
    session = True
    if condition == "WRONG-NAMESPACE":
        session = _other_namespace(ctx)
        if session is None:
            return CaseResult.error("system", "A second session for the wrong-namespace condition could not be created.")
    method, path, kwargs = _access_request(ctx, operation, record, remediated, condition == "UNKNOWN")
    role = {"UNAUTHENTICATED": None, "INVALID-TOKEN": None, "FOREIGN": "userB", "REVIEWER-WRITE-REFUSED": "reviewer",
            "REVIEWER-READ": "reviewer", "TEST-ADMIN": "test-admin"}.get(condition, "userA")
    if condition == "INVALID-TOKEN":
        kwargs["bearer"] = f"tester-invalid-{uuid.uuid4().hex}"
    before, _ = _history(ctx, record["upload"]["workbookId"]) if operation not in READS else (None, None)
    response = ctx.call(method, path, role=role, session=session, **kwargs)
    if response.status >= 500:
        return _system_failure(f"The {operation} request", response)
    ctx.mark()
    status, code = CONDITIONS[condition]
    what = f"{operation} with the {condition.lower().replace('-', ' ')} condition"
    if status == 200:
        problems = [] if response.status == 200 else [f"{what}: expected 200, received {response.status}"]
        if response.status == 200 and kwargs.get("binary"):
            owner = ctx.call(method, path, role="userA", **kwargs)
            if owner.body != response.body:
                problems.append(f"{what}: the reviewer received different bytes from the owner")
    else:
        problems = _error_problems(response, status, code, what)
    if before is not None:
        after, _ = _history(ctx, record["upload"]["workbookId"])
        if after != before:
            problems.append(f"{what}: history changed, so the refused write had an effect")
    return _verdict(f"P4 access: {what}", problems, f"{what} returned {status} as required, with no side effect.")


##  ---- Session-level cases ----

def session_coverage(case, ctx):
    ##  P4-SESSION-COVERAGE: the system report for this session is stable across retrievals.
    first, second = (ctx.target.system_report(ctx.session_id, ctx.deadline) for _ in range(2))
    if first.status >= 500:
        return _system_failure("The system report", first)
    ctx.mark()
    problems = []
    for label, response in (("first", first), ("second", second)):
        try:
            report = SystemReport.model_validate(response.json()) if response.status == 200 else None
        except ValidationError as problem:
            problems.append(f"{label} report does not match SystemReport ({_schema_problem(problem)})")
            continue
        if report is None or report.session_id != ctx.session_id:
            problems.append(f"{label} report returned {response.status} or another session")
    if first.body != second.body:
        problems.append("two retrievals returned different coverage, so retrieval executed or reset work")
    return _verdict("Session coverage", problems, "The session's coverage report is valid and stable across retrievals.")


def session_cleanup(case, ctx):
    ##  P4-SESSION-CLEANUP: a later setup that names an inactive caller-owned session removes its
    ##  resources, while this session's resources stay readable.
    key = case.parameters["fixture"]
    doomed, response = _fault_setup_call(ctx, {})
    if response.status != 201:
        return CaseResult.failed(f"A session to clean up could not be created ({response.status}).")
    uploaded = ctx.upload(WORKBOOKS, role="userA", fixture=key, session=doomed)
    if uploaded.status != 202:
        return CaseResult.failed(f"The upload into the session to clean up returned {uploaded.status}.")
    doomed_upload = UploadResponse.model_validate(uploaded.json()).model_dump()
    _finished_audit(ctx, doomed_upload, "The audit in the session to clean up", session=doomed, mark=False)
    _cleaner, cleaned = _fault_setup_call(ctx, {"cleanup_session_ids": [doomed]})
    if cleaned.status >= 500:
        return _system_failure("The cleanup setup", cleaned)
    ctx.mark()
    problems = [] if cleaned.status == 201 else [f"the setup naming the session to clean up returned {cleaned.status}"]
    gone = ctx.call("GET", _version_path(doomed_upload), role="userA", session=doomed)
    if gone.status not in (400, 404):
        problems.append(f"a read in the cleaned session returned {gone.status}, so its resources remain")
    main = ctx.state.get("uploads", {})
    if main:
        sample = next(iter(main.values()))
        if ctx.call("GET", _version_path(sample), role="userA").status != 200:
            problems.append("this session's resources became unreadable after another session's cleanup")
    return _verdict("Caller-owned session cleanup", problems,
                    "Cleanup removed the inactive session's resources and left this session's intact.")


def report_format(case, ctx):
    ##  P4-REPORT-FORMAT: every result so far is a valid TestResult, once each, in plan order,
    ##  with source exactly on errors.
    ctx.mark()
    results, order = ctx._run.results, [c.test_id for c in ctx.manifest.tests]
    problems = []
    ids = [r["test_id"] for r in results]
    if ids != order[:len(ids)]:
        problems.append("results so far are not the planned IDs in plan order")
    for r in results:
        try:
            TestResult.model_validate(r)
        except ValidationError as problem:
            problems.append(f"{r.get('test_id')}: {_schema_problem(problem)}")
    if len(set(order)) != len(order):
        problems.append("the plan repeats a test ID")
    return _verdict("The report format", problems,
                    f"{len(results)} results so far are valid, unique and in plan order; source appears only on errors.")


PHASE4_CHECKS = {
    "upload_and_audit": upload_and_audit, "rule_vector": rule_vector, "blocked_fixture": blocked_fixture,
    "review_context": review_context, "review_reviewer": review_reviewer, "version_new": version_new,
    "version_same_bytes": version_same_bytes, "reaudit": reaudit, "reaudit_invalid": reaudit_invalid,
    "reaudit_determinism": reaudit_determinism, "source_before": source_before, "download_large": download_large,
    "remediation": remediation, "remediation_followup": remediation_followup, "reject_decisions": reject_decisions,
    "batch_atomic": batch_atomic, "idempotency": idempotency, "access": access, "session_coverage": session_coverage,
    "session_cleanup": session_cleanup, "report_format": report_format,
}
