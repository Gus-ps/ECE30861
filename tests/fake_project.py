"""Test-only stand-in for the project API: health, upload intake, version and audit reads,
and the Phase 4 routes the fault cases use (manual re-audit, source, report, history).

Shared by the pytest FakeSystem and the rehearsal stand-in system. It applies the
Phase 3 intake rules just far enough to answer the tester's workbooks, and audits
with tester/suite/pod_rules.py, Team 12's oracle (never the fixture expectations),
so comparing its audits with the pack is a real check. A session armed with one
audit failure (system setup `faults`) fails the first accepted audit in it, as
shared specification §14.1 describes. It is not a reference implementation.
"""

import hashlib
import io
import json
import re
import uuid
import zipfile
from datetime import datetime, timezone

from tester.config import FIXTURES
from tester.models import PodProfile
from tester.suite.identity import finding_id
from tester.suite.pod_rules import evaluate

USERS = {"tok-a": "userA", "tok-b": "userB", "tok-r": "reviewer"}
ADMIN = "tok-admin"
MAX_BYTES, MAX_WORKSHEETS, MAX_CELLS = 25_000_000, 50, 250_000
WORKSHEET_REL = "/relationships/worksheet"
NONEMPTY_CELL = re.compile(rb"<c\b[^>]*>\s*<(?:f|v|is)\b")
SHEET_LOCK = re.compile(rb'<sheetProtection\b[^>]*\bsheet="(?:1|true)"')
VERSION = r"^/api/v1/workbooks/([^/]+)/versions/([^/]+)"
ROUTES = [
    ("GET", re.compile(VERSION + r"/audits/([^/]+)/report$"), "report"),
    ("GET", re.compile(VERSION + r"/audits/([^/]+)$"), "audit"),
    ("POST", re.compile(VERSION + r"/audits$"), "reaudit"),
    ("GET", re.compile(VERSION + r"/source$"), "source"),
    ("GET", re.compile(VERSION + r"$"), "version"),
    ("GET", re.compile(r"^/api/v1/workbooks/([^/]+)/history$"), "history"),
]
REVIEWER_GRANTS = {"reviewer": {"userA"}}      # explicit read grants; the reviewer role alone reads nothing
RULESET = "1.0.0"
PROFILE = PodProfile.model_validate(json.loads((FIXTURES / "pod_profile.json").read_text(encoding="utf-8")))
SIX_CHECKS = ["ALT_TEXT", "WORKSHEET_NAME", "TABLE_HEADER", "MERGED_CELLS", "LINK_TEXT", "COLOR_CONTRAST"]
INJECTED = {"code": "TEST_AUDIT_FAILURE", "message": "Audit failure requested by the isolated test session.",
            "details": {"stage": "audit", "testOnly": True}}


def can_read(subject, owner):
    return subject == owner or owner in REVIEWER_GRANTS.get(subject, set())


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def unsafe(name):
    ##  An entry name that is absolute, uses backslashes, or climbs out of the package root.
    return name.startswith("/") or "\\" in name or ".." in name.split("/")


def error(status, code, message):
    return status, {"code": code, "message": message, "requestId": f"req-{uuid.uuid4().hex[:12]}", "details": {}}


class FakeProject:
    def __init__(self, sessions):
        self.sessions = sessions          # live set of prepared session IDs
        self.armed = set()                # sessions whose next accepted audit fails (one-shot)
        self.versions = {}                # versionId -> stored version, with its audit IDs in order
        self.audits = {}                  # auditId -> stored audit record
        self.processing_polls = 0         # audit reads answered PROCESSING before the result
        self.ruleset = RULESET

    def handle(self, method, path, headers, body):
        ##  (status, JSON body or raw bytes) for a project call; headers are lowercase-keyed.
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
                return getattr(self, name)(subject, *match.groups(), body=body, session=session)
        return error(404, "NOT_FOUND", "No route.")

    ##  ---- Reads ----

    def _version(self, subject, workbook_id, version_id, write=False):
        ##  (version, None) or (None, error reply).
        version = self.versions.get(version_id)
        if version is None or version["workbookId"] != workbook_id:
            return None, error(404, "NOT_FOUND", "No such version.")
        allowed = subject == version["owner"] if write else can_read(subject, version["owner"])
        if not allowed:
            return None, error(403, "FORBIDDEN", "This version belongs to another user.")
        return version, None

    def _audit(self, subject, workbook_id, version_id, audit_id):
        version, problem = self._version(subject, workbook_id, version_id)
        if problem:
            return None, problem
        record = self.audits.get(audit_id)
        if record is None or audit_id not in version["audits"]:
            return None, error(404, "NOT_FOUND", "No such audit.")
        return record, None

    def _audit_status(self, record):
        return "PROCESSING" if record["polls_left"] > 0 else record["result"]["status"]

    def version(self, subject, workbook_id, version_id, **_):
        version, problem = self._version(subject, workbook_id, version_id)
        if problem:
            return problem
        latest = self.audits[version["audits"][-1]]
        return 200, {"workbookId": workbook_id, "versionId": version_id, "fileName": version["fileName"],
                     "sha256": version["sha256"], "createdAt": version["createdAt"],
                     "status": self._audit_status(latest), "latestAuditId": latest["auditId"], "sourceVersionId": None}

    def audit(self, subject, workbook_id, version_id, audit_id, **_):
        record, problem = self._audit(subject, workbook_id, version_id, audit_id)
        if problem:
            return problem
        reply = {key: record[key] for key in ("auditId", "workbookId", "versionId", "startedAt")}
        reply["rulesetVersion"] = self.ruleset
        if record["polls_left"] > 0:
            record["polls_left"] -= 1
            return 200, {**reply, "status": "PROCESSING", "completedAt": None, "findings": [], "limitations": [],
                         "error": None}
        return 200, {**reply, **record["result"]}

    def report(self, subject, workbook_id, version_id, audit_id, **_):
        record, problem = self._audit(subject, workbook_id, version_id, audit_id)
        if problem:
            return problem
        if self._audit_status(record) == "PROCESSING":
            return error(409, "AUDIT_NOT_READY", "The audit has not finished.")
        version, result = self.versions[version_id], record["result"]
        failed = result["status"] == "PROCESSING_FAILED"
        return 200, {"reportVersion": "2.0.0", "specificationVersion": "2.1.0", "workbookId": workbook_id,
                     "versionId": version_id, "auditId": audit_id, "fileName": version["fileName"],
                     "sha256": version["sha256"], "sourceVersionId": None, "auditDate": record["startedAt"],
                     "rulesetVersion": self.ruleset, "status": result["status"],
                     "checksPerformed": [] if failed else SIX_CHECKS, "findings": result["findings"],
                     "decisions": [], "approvedChanges": [], "unresolvedFindings": result["findings"],
                     "manualReviewItems": [], "limitations": result["limitations"], "remediationId": None,
                     "outputVersionId": None, "outputId": None, "error": result["error"]}

    def source(self, subject, workbook_id, version_id, **_):
        version, problem = self._version(subject, workbook_id, version_id)
        return problem or (200, version["content"])

    def history(self, subject, workbook_id, **_):
        versions = [v for v in self.versions.values() if v["workbookId"] == workbook_id]
        if not versions:
            return error(404, "NOT_FOUND", "No such workbook.")
        if not can_read(subject, versions[0]["owner"]):
            return error(403, "FORBIDDEN", "This workbook belongs to another user.")
        audits = [self.audits[a] for v in versions for a in v["audits"]]
        return 200, {"workbookId": workbook_id,
                     "versions": [{"versionId": v["versionId"], "sourceVersionId": None, "createdAt": v["createdAt"],
                                   "status": self._audit_status(self.audits[v["audits"][-1]])} for v in versions],
                     "audits": [{"auditId": a["auditId"], "versionId": a["versionId"], "rulesetVersion": self.ruleset,
                                 "status": self._audit_status(a)} for a in audits]}

    ##  ---- Writes ----

    def reaudit(self, subject, workbook_id, version_id, body=b"", session=None, **_):
        version, problem = self._version(subject, workbook_id, version_id, write=True)
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
                                 "versionId": version["versionId"], "startedAt": now(),
                                 "polls_left": self.processing_polls, "result": result}
        version["audits"].append(audit_id)
        return audit_id

    def _audit_result(self, content):
        source = hashlib.sha256(content).hexdigest()
        try:
            findings, limitations = evaluate(content, PROFILE)
        except Exception:
            return {"status": "PROCESSING_FAILED", "completedAt": now(), "findings": [], "limitations": [],
                    "error": error(500, "AUDIT_FAILED", "The workbook could not be audited.")[1]}
        findings = [{"findingId": finding_id(source, self.ruleset, f["ruleId"], f["worksheet"], f["target"]), **f,
                     "message": f"{f['ruleId']} finding at {f['target']}.",
                     "recommendation": "Review the flagged item and supply the missing information."}
                    for f in findings]
        return {"status": "REVIEW_REQUIRED" if findings else "AUDIT_COMPLETE", "completedAt": now(),
                "findings": findings, "limitations": limitations, "error": None}

    def upload(self, content_type, body, owner="userA", session=None):
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
        ids = uuid.uuid4().hex
        version = {"workbookId": f"wb-{ids[:10]}", "versionId": f"ver-{ids[10:20]}", "owner": owner,
                   "fileName": name, "sha256": hashlib.sha256(content).hexdigest(), "content": content,
                   "createdAt": now(), "audits": []}
        self.versions[version["versionId"]] = version
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
