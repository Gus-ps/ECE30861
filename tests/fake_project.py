"""Test-only stand-in for the project API, shared by the pytest FakeSystem and the rehearsal
stand-in system. It is not a reference implementation.

- Ruleset 1.0.0 (default): audits with tester/suite/pod_rules.py, Team 12's independent
  oracle, never the fixture expectations, so Phase 3 comparisons are real checks.
- Ruleset 2.0.0 (Phase 4): there is no six-rule oracle, so audits of known fixtures answer
  from the Phase 4 pack's answer key, and outputs from that answer minus the corrected
  findings. Phase 4 self-tests therefore prove the tester's plumbing, not rule agreement.
- A session armed with one audit failure (system setup `faults`) fails the first accepted
  audit in it (shared specification §14.1). Resources are scoped to their session.
"""

import hashlib
import io
import json
import re
import uuid
import zipfile
from datetime import datetime, timezone
from urllib.parse import quote

from tester.config import FIXTURES
from tester.models import PodProfile
from tester.suite.identity import finding_id
from tester.suite.pod_rules import evaluate

from .fake_phase4 import Phase4Routes

USERS = {"tok-a": "userA", "tok-b": "userB", "tok-r": "reviewer"}
ADMIN = "tok-admin"
MAX_BYTES, MAX_WORKSHEETS, MAX_CELLS = 25_000_000, 50, 250_000
WORKSHEET_REL = "/relationships/worksheet"
NONEMPTY_CELL = re.compile(rb"<c\b[^>]*>\s*<(?:f|v|is)\b")
SHEET_LOCK = re.compile(rb'<sheetProtection\b[^>]*\bsheet="(?:1|true)"')
VERSION = r"^/api/v1/workbooks/([^/]+)/versions/([^/]+)"
ROUTES = [
    ("GET", re.compile(VERSION + r"/audits/([^/]+)/report$"), "report"),
    ("GET", re.compile(VERSION + r"/audits/([^/]+)/review$"), "review"),
    ("GET", re.compile(VERSION + r"/audits/([^/]+)$"), "audit"),
    ("POST", re.compile(VERSION + r"/audits$"), "reaudit"),
    ("POST", re.compile(VERSION + r"/remediations$"), "remediate"),
    ("GET", re.compile(VERSION + r"/source$"), "source"),
    ("GET", re.compile(VERSION + r"$"), "version"),
    ("POST", re.compile(r"^/api/v1/workbooks/([^/]+)/versions$"), "new_version"),
    ("GET", re.compile(r"^/api/v1/workbooks/([^/]+)/history$"), "history"),
    ("GET", re.compile(r"^/api/v1/remediations/([^/]+)$"), "remediation_status"),
    ("GET", re.compile(r"^/api/v1/outputs/([^/]+)/workbook$"), "output"),
]
REVIEWER_GRANTS = {"reviewer": {"userA"}}      # explicit read grants; the reviewer role alone reads nothing
RULESET = "1.0.0"
PROFILE = PodProfile.model_validate(json.loads((FIXTURES / "pod_profile.json").read_text(encoding="utf-8")))
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
SIX_CHECKS = ["ALT_TEXT", "WORKSHEET_NAME", "TABLE_HEADER", "MERGED_CELLS", "LINK_TEXT", "COLOR_CONTRAST"]
INJECTED = {"code": "TEST_AUDIT_FAILURE", "message": "Audit failure requested by the isolated test session.",
            "details": {"stage": "audit", "testOnly": True}}


def phase4_answer_key():
    ##  {sha256: expectations entry} for every accepted fixture in the Phase 4 pack.
    pack = json.loads((FIXTURES / "phase4" / "expectations.json").read_text(encoding="utf-8"))
    return {e["sha256"]: e for e in pack["fixtures"].values() if e["kind"] == "accepted"}


def can_read(subject, owner):
    return subject == owner or owner in REVIEWER_GRANTS.get(subject, set())


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def unsafe(name):
    ##  An entry name that is absolute, uses backslashes, or climbs out of the package root.
    return name.startswith("/") or "\\" in name or ".." in name.split("/")


def error(status, code, message):
    return status, {"code": code, "message": message, "requestId": f"req-{uuid.uuid4().hex[:12]}", "details": {}}


def download(body, media, name):
    ##  (200, bytes, headers) for a download with the §5.4 headers.
    fallback = "".join(c if c.isascii() and c.isprintable() and c not in '"\\/' else "_" for c in name)
    return 200, body, {"content-type": media, "cache-control": "no-store",
                       "content-disposition": f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(name)}"}


def status_of(findings, ruleset):
    if not findings:
        return "AUDIT_COMPLETE"
    if ruleset == "1.0.0":
        return "REVIEW_REQUIRED"
    return "REMEDIATION_AVAILABLE" if any(f["classification"] == "REQUIRES_USER_INPUT" for f in findings) \
        else "REVIEW_REQUIRED"


class FakeProject(Phase4Routes):
    def __init__(self, sessions):
        self.sessions = sessions          # live set of prepared session IDs
        self.armed = set()                # sessions whose next accepted audit fails (one-shot)
        self.versions = {}                # versionId -> stored version, with its audit IDs in order
        self.audits = {}                  # auditId -> stored audit record
        self.processing_polls = 0         # audit reads answered PROCESSING before the result
        self.ruleset = RULESET
        self.answer_key = phase4_answer_key()
        self.derived = {}                 # output sha256 -> (findings, limitations) for generated versions
        self.remediations, self.outputs, self.idempotency = {}, {}, {}

    def handle(self, method, path, headers, body):
        ##  (status, JSON body or raw bytes[, headers]) for a project call; headers lowercase-keyed.
        if path == "/api/v1/health" and method == "GET":
            return 200, {"status": "AVAILABLE", "apiVersion": "1.0", "rulesetVersion": self.ruleset}
        token = headers.get("authorization", "").removeprefix("Bearer ")
        if token == ADMIN:
            return error(403, "FORBIDDEN", "A test-admin token cannot call business routes.")
        if token not in USERS:
            return error(401, "UNAUTHENTICATED", "A valid bearer token is required.")
        session = headers.get("x-test-session")
        if session not in self.sessions:
            return error(400, "UNKNOWN_TEST_SESSION", "Unknown test session.")
        subject = USERS[token]
        if path == "/api/v1/workbooks" and method == "POST":
            return self.upload(headers.get("content-type", ""), body, subject, session)
        for verb, pattern, name in ROUTES:
            match = pattern.match(path)
            if match and method == verb:
                return getattr(self, name)(subject, *match.groups(), body=body, session=session, headers=headers)
        return error(404, "NOT_FOUND", "No route.")

    def cleanup(self, session_ids):
        ##  Caller-owned cleanup of inactive sessions: their sessions and resources disappear.
        for session_id in session_ids:
            self.sessions.discard(session_id)
            for version_id in [v for v, record in self.versions.items() if record["session"] == session_id]:
                for audit_id in self.versions.pop(version_id)["audits"]:
                    self.audits.pop(audit_id, None)

    ##  ---- Reads ----

    def _version(self, subject, workbook_id, version_id, session=None, write=False):
        ##  (version, None) or (None, error reply). Another session's resources do not exist here.
        version = self.versions.get(version_id)
        if version is None or version["workbookId"] != workbook_id or (session and version["session"] != session):
            return None, error(404, "NOT_FOUND", "No such version.")
        allowed = subject == version["owner"] if write else can_read(subject, version["owner"])
        if not allowed:
            return None, error(403, "FORBIDDEN", "This version belongs to another user.")
        return version, None

    def _audit(self, subject, workbook_id, version_id, audit_id, session=None):
        version, problem = self._version(subject, workbook_id, version_id, session)
        if problem:
            return None, problem
        record = self.audits.get(audit_id)
        if record is None or audit_id not in version["audits"]:
            return None, error(404, "NOT_FOUND", "No such audit.")
        return record, None

    def _audit_status(self, record):
        return "PROCESSING" if record["polls_left"] > 0 else record["result"]["status"]

    def _version_status(self, version):
        latest = self.audits[version["audits"][-1]]
        status = self._audit_status(latest)
        if version["sourceVersionId"] and status not in ("PROCESSING", "PROCESSING_FAILED"):
            return "REMEDIATED"
        return status

    def version(self, subject, workbook_id, version_id, session=None, **_):
        version, problem = self._version(subject, workbook_id, version_id, session)
        if problem:
            return problem
        return 200, {"workbookId": workbook_id, "versionId": version_id, "fileName": version["fileName"],
                     "sha256": version["sha256"], "createdAt": version["createdAt"],
                     "status": self._version_status(version), "latestAuditId": version["audits"][-1],
                     "sourceVersionId": version["sourceVersionId"]}

    def audit(self, subject, workbook_id, version_id, audit_id, session=None, **_):
        record, problem = self._audit(subject, workbook_id, version_id, audit_id, session)
        if problem:
            return problem
        reply = {key: record[key] for key in ("auditId", "workbookId", "versionId", "startedAt")}
        reply["rulesetVersion"] = self.ruleset
        if record["polls_left"] > 0:
            record["polls_left"] -= 1
            return 200, {**reply, "status": "PROCESSING", "completedAt": None, "findings": [], "limitations": [],
                         "error": None}
        return 200, {**reply, **record["result"]}

    def report(self, subject, workbook_id, version_id, audit_id, session=None, **_):
        record, problem = self._audit(subject, workbook_id, version_id, audit_id, session)
        if problem:
            return problem
        if self._audit_status(record) == "PROCESSING":
            return error(409, "AUDIT_NOT_READY", "The audit has not finished.")
        version, result = self.versions[version_id], record["result"]
        failed = result["status"] == "PROCESSING_FAILED"
        remediation = self.remediations.get(version.get("remediationId")) if version["sourceVersionId"] else None
        decisions = remediation["report_decisions"] if remediation and audit_id == remediation["auditId"] else []
        body = {"reportVersion": "2.0.0", "specificationVersion": "2.1.0", "workbookId": workbook_id,
                "versionId": version_id, "auditId": audit_id, "fileName": version["fileName"],
                "sha256": version["sha256"], "sourceVersionId": version["sourceVersionId"],
                "auditDate": record["startedAt"], "rulesetVersion": self.ruleset, "status": result["status"],
                "checksPerformed": [] if failed else SIX_CHECKS, "findings": result["findings"],
                "decisions": decisions, "approvedChanges": [d for d in decisions if d["action"] == "APPLY"],
                "unresolvedFindings": [f for f in result["findings"] if f["classification"] != "MANUAL_REVIEW"],
                "manualReviewItems": [f for f in result["findings"] if f["classification"] == "MANUAL_REVIEW"],
                "limitations": result["limitations"],
                "remediationId": remediation["remediationId"] if decisions else None,
                "outputVersionId": version_id if decisions else None,
                "outputId": remediation["outputId"] if decisions else None, "error": result["error"]}
        return download(json.dumps(body, ensure_ascii=False).encode("utf-8"), "application/json", f"audit-{audit_id}.json")

    def source(self, subject, workbook_id, version_id, session=None, **_):
        version, problem = self._version(subject, workbook_id, version_id, session)
        return problem or download(version["content"], XLSX, version["fileName"])

    def history(self, subject, workbook_id, session=None, **_):
        versions = [v for v in self.versions.values() if v["workbookId"] == workbook_id and v["session"] == session]
        if not versions:
            return error(404, "NOT_FOUND", "No such workbook.")
        if not can_read(subject, versions[0]["owner"]):
            return error(403, "FORBIDDEN", "This workbook belongs to another user.")
        audits = sorted((self.audits[a] for v in versions for a in v["audits"]), key=lambda a: a["sequence"])
        return 200, {"workbookId": workbook_id,
                     "versions": [{"versionId": v["versionId"], "sourceVersionId": v["sourceVersionId"],
                                   "createdAt": v["createdAt"], "status": self._version_status(v)} for v in versions],
                     "audits": [{"auditId": a["auditId"], "versionId": a["versionId"], "rulesetVersion": self.ruleset,
                                 "status": self._audit_status(a)} for a in audits]}

    ##  ---- Writes ----

    def reaudit(self, subject, workbook_id, version_id, body=b"", session=None, **_):
        version, problem = self._version(subject, workbook_id, version_id, session, write=True)
        if problem:
            return problem
        try:
            request = json.loads(body) if body else {}
        except ValueError:
            request = None
        if not isinstance(request, dict) or set(request) - {"reason"} or request.get("reason", "MANUAL_REAUDIT") \
                != "MANUAL_REAUDIT":
            return error(400, "INVALID_REQUEST", "Only an empty body or reason MANUAL_REAUDIT is accepted.")
        audit_id = self._new_audit(version, session)
        return 202, {"auditId": audit_id, "versionId": version_id, "rulesetVersion": self.ruleset,
                     "status": "PROCESSING"}

    def _new_audit(self, version, session):
        ##  The first accepted audit in an armed session consumes the fault and fails as injected.
        audit_id = f"audit-{uuid.uuid4().hex[:10]}"
        if session in self.armed:
            self.armed.discard(session)
            result = {"status": "PROCESSING_FAILED", "completedAt": now(), "findings": [], "limitations": [],
                      "error": {**INJECTED, "requestId": f"job-{uuid.uuid4().hex[:12]}"}}
        else:
            result = self._audit_result(version["content"])
        self.audits[audit_id] = {"auditId": audit_id, "workbookId": version["workbookId"],
                                 "versionId": version["versionId"], "startedAt": now(), "sequence": len(self.audits),
                                 "polls_left": self.processing_polls, "result": result}
        version["audits"].append(audit_id)
        return audit_id

    def _audit_result(self, content):
        source = hashlib.sha256(content).hexdigest()
        if self.ruleset != RULESET and (source in self.answer_key or source in self.derived):
            if source in self.answer_key:
                entry = self.answer_key[source]
                raw, limitations = entry["findings"], sorted(set(entry["limitation_facts"]))
            else:
                raw, limitations = self.derived[source]
        else:
            try:
                raw, limitations = evaluate(content, PROFILE)
            except Exception:
                return {"status": "PROCESSING_FAILED", "completedAt": now(), "findings": [], "limitations": [],
                        "error": error(500, "AUDIT_FAILED", "The workbook could not be audited.")[1]}
        findings = [{"findingId": finding_id(source, self.ruleset, f["ruleId"], f["worksheet"], f["target"]), **f,
                     "message": f"{f['ruleId']} finding at {f['target']}.",
                     "recommendation": "Review the flagged item and supply the missing information."}
                    for f in raw]
        return {"status": status_of(findings, self.ruleset), "completedAt": now(), "findings": findings,
                "limitations": limitations, "error": None}

    def _intake(self, content_type, body):
        ##  (name, content) for an acceptable one-file upload, or an error reply.
        parts = multipart(content_type, body)
        if parts is None or "file" not in parts:
            return error(400, "INVALID_REQUEST", "The multipart field 'file' is required.")
        name, content = parts["file"]
        if name.lower().endswith(".xlsm"):
            return error(422, "MACRO_ENABLED_WORKBOOK_UNSUPPORTED", "Macro-enabled workbooks are not supported.")
        if not name.lower().endswith(".xlsx"):
            return error(415, "UNSUPPORTED_FILE_TYPE", "Only .xlsx workbooks are supported.")
        if len(content) > MAX_BYTES:
            return error(413, "FILE_TOO_LARGE", "The workbook exceeds 25,000,000 bytes.")
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as package:
                names = package.namelist()
                if any(info.flag_bits & 1 for info in package.infolist()):
                    return error(422, "INVALID_WORKBOOK", "Encrypted packages are not supported.")
                if len(set(names)) != len(names) or any(unsafe(n) for n in names):
                    return error(422, "INVALID_WORKBOOK", "The package has duplicate or unsafe entry names.")
                if any(n.lower().endswith("vbaproject.bin") for n in names):
                    return error(422, "INVALID_WORKBOOK", "The package carries a VBA project.")
                markup = {n: package.read(n) for n in names if n.endswith((".xml", ".rels"))}
                workbook = markup["xl/workbook.xml"]
                rels = markup["xl/_rels/workbook.xml.rels"]
                sheets = [n for n in markup if n.startswith("xl/worksheets/") and n.endswith(".xml")]
                cells = sum(len(NONEMPTY_CELL.findall(markup[n])) for n in sheets)
        except (zipfile.BadZipFile, KeyError):
            return error(422, "INVALID_WORKBOOK", "The workbook cannot be read.")
        if any(b"<!DOCTYPE" in part for part in markup.values()):
            return error(422, "INVALID_WORKBOOK", "DTDs are not allowed.")
        if b"<workbookProtection" in workbook and b'lockStructure="1"' in workbook:
            return error(422, "PROTECTED_WORKBOOK", "Protected workbooks are not supported.")
        if any(SHEET_LOCK.search(markup[n]) for n in sheets):
            return error(422, "PROTECTED_WORKBOOK", "Protected worksheets are not supported.")
        if rels.count(WORKSHEET_REL.encode() + b'"') > MAX_WORKSHEETS:
            return error(422, "TOO_MANY_WORKSHEETS", "The workbook has more than 50 worksheets.")
        if cells > MAX_CELLS:
            return error(422, "TOO_MANY_CELLS", "The workbook has more than 250,000 nonempty cells.")
        return name, content

    def _store_version(self, workbook_id, owner, session, name, content, source_version=None):
        version = {"workbookId": workbook_id, "versionId": f"ver-{uuid.uuid4().hex[:10]}", "owner": owner,
                   "session": session, "fileName": name, "sha256": hashlib.sha256(content).hexdigest(),
                   "content": content, "createdAt": now(), "audits": [], "sourceVersionId": source_version}
        self.versions[version["versionId"]] = version
        return version

    def upload(self, content_type, body, owner="userA", session=None):
        intake = self._intake(content_type, body)
        if isinstance(intake[0], int):
            return intake
        name, content = intake
        version = self._store_version(f"wb-{uuid.uuid4().hex[:10]}", owner, session, name, content)
        audit_id = self._new_audit(version, session)
        return 202, {"workbookId": version["workbookId"], "versionId": version["versionId"], "auditId": audit_id,
                     "status": "PROCESSING"}


def multipart(content_type, body):
    ##  {field name: (filename, bytes)}, or None when the body is not multipart.
    match = re.search(r'boundary="?([^";]+)"?', content_type)
    if not content_type.startswith("multipart/form-data") or not match:
        return None
    fields = {}
    for chunk in body.split(b"--" + match.group(1).encode())[1:]:
        if chunk.startswith(b"--"):
            break
        head, _, content = chunk.partition(b"\r\n\r\n")
        name = re.search(rb'\bname="([^"]*)"', head)
        filename = re.search(rb'filename="([^"]*)"', head)
        if name:
            fields[name.group(1).decode()] = (filename.group(1).decode() if filename else "",
                                              content.removesuffix(b"\r\n"))
    return fields
