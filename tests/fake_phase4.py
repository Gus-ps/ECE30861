"""Phase 4 routes of the test fake (new versions, review context, remediations, outputs).

Validation follows shared specification §8-9 closely enough for the tester's negative cases
to have a conforming counterpart. Outputs are produced by applying the comparator's own
change model (tester/suite/comparator.py Plan), so the fake cannot catch a comparator
modelling error; the comparator has its own independent tests for that.
"""

import copy
import hashlib
import io
import json
import re
import uuid
import xml.etree.ElementTree as ET
import zipfile

from tester.suite.comparator import ChangeError, Plan, _canon, _namespaces, _parse, change_from_decision, read_package
from tester.suite.identity import trim

IDENTIFIER = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
SHA = re.compile(r"^[0-9a-f]{64}$")
AMBIGUOUS = {"click here", "here", "link", "more", "read more", "learn more", "website", "url"}
FORBIDDEN = set(':\\/?*[]')


def _error(status, code, message):
    return status, {"code": code, "message": message, "requestId": f"req-{uuid.uuid4().hex[:12]}", "details": {}}


def _ambiguous(text):
    label = re.sub(r"\s+", " ", trim(text)).casefold()
    label = label[:-1] if label[-1:] in ".!?" else label
    return not label or label in AMBIGUOUS or label.startswith(("http://", "https://", "www.", "mailto:"))


def edit_package(source, changes):
    ##  Output bytes: the source with exactly the approved changes, untouched parts byte-identical.
    entries, _ = read_package(source, "source")
    plan = Plan(entries, changes)
    out = dict(entries)
    for name, transforms in plan.transforms.items():
        original = _parse(entries[name], name)
        variants = [original]
        for transform in transforms:
            variants = [r for v in variants for r in transform(copy.deepcopy(v))]
        if _canon(variants[0]) == _canon(original):
            continue
        declared = _namespaces(entries[name])
        for prefix, uri in declared:
            ET.register_namespace(prefix, uri)
        xml = ET.tostring(variants[0], encoding="UTF-8", xml_declaration=True)
        ##  ElementTree drops declarations nothing uses (spec 11 forbids that); put them back on the root.
        missing = declared - _namespaces(xml)
        if missing:
            extra = "".join(f' xmlns:{p}="{u}"' if p else f' xmlns="{u}"' for p, u in sorted(missing))
            xml = re.sub(rb"(<(?!\?)[^\s>/]+)", lambda m: m[1] + extra.encode(), xml, count=1)
        out[name] = xml
    rel_ns = plan.rel_ns
    for sheet, rids in plan.table_parts.items():
        parts = "".join(f'<tablePart xmlns:r="{rel_ns}" r:id="{rid}"/>' for rid in rids)
        out[sheet] = out[sheet].replace(b"</worksheet>", f'<tableParts count="{len(rids)}">{parts}</tableParts>'
                                        f"</worksheet>".encode(), 1)
    for path, rels in plan.rels_additions.items():
        body = "".join(f'<Relationship Id="{rid}" Type="{kind}" Target="/{target}"/>' for rid, (kind, target, _m) in rels.items())
        existing = out.get(path, b'<?xml version="1.0" encoding="UTF-8"?>\n<Relationships '
                                 b'xmlns="http://schemas.openxmlformats.org/package/2006/relationships"></Relationships>')
        out[path] = existing.replace(b"</Relationships>", body.encode() + b"</Relationships>")
    for part, kind in plan.content_type_additions.items():
        out["[Content_Types].xml"] = out["[Content_Types].xml"].replace(
            b"</Types>", f'<Override PartName="{part}" ContentType="{kind}"/></Types>'.encode())
    for part, (table_id, name, ref, labels) in plan.new_tables.items():
        cols = "".join(f'<tableColumn id="{i}" name="{label}"/>' for i, label in enumerate(labels, start=1))
        out[part] = (f'<?xml version="1.0" encoding="UTF-8"?>\n<table xmlns="{plan.main}" id="{table_id}" name="{name}" '
                     f'displayName="{name}" ref="{ref}"><tableColumns count="{len(labels)}">{cols}</tableColumns>'
                     f"</table>").encode()
    ##  Keep each entry's compression type, as spec 11 asks where possible.
    with zipfile.ZipFile(io.BytesIO(source)) as original:
        compression = {info.filename: info.compress_type for info in original.infolist()}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in out.items():
            archive.writestr(name, data, compress_type=compression.get(name, zipfile.ZIP_DEFLATED))
    return buffer.getvalue(), plan


class Phase4Routes:
    ##  Mixed into FakeProject; relies on its _version, _audit, _intake, _store_version,
    ##  _new_audit, _audit_status and audits/versions stores.

    def new_version(self, subject, workbook_id, body=b"", session=None, headers=None, **_):
        existing = [v for v in self.versions.values() if v["workbookId"] == workbook_id and v["session"] == session]
        if not existing:
            return _error(404, "NOT_FOUND", "No such workbook.")
        if subject != existing[0]["owner"]:
            return _error(403, "FORBIDDEN", "Only the owner may add versions.")
        intake = self._intake(headers.get("content-type", ""), body)
        if isinstance(intake[0], int):
            return intake
        version = self._store_version(workbook_id, subject, session, *intake)
        audit_id = self._new_audit(version, session)
        return 202, {"workbookId": workbook_id, "versionId": version["versionId"], "auditId": audit_id,
                     "status": "PROCESSING"}

    def _latest(self, version):
        return self.audits[version["audits"][-1]]

    def review(self, subject, workbook_id, version_id, audit_id, session=None, **_):
        record, problem = self._audit(subject, workbook_id, version_id, audit_id, session)
        if problem:
            return problem
        version = self.versions[version_id]
        if self._audit_status(record) in ("PROCESSING", "PROCESSING_FAILED"):
            return _error(409, "AUDIT_NOT_READY", "The audit is not complete.")
        if self._latest(version)["auditId"] != audit_id:
            return _error(409, "STALE_AUDIT", "A newer audit exists.")
        owner = subject == version["owner"]
        entries, _ = read_package(version["content"], "source")
        plan = Plan(entries, [])
        items = []
        for f in record["result"]["findings"]:
            actions = (["APPLY", "DECLINE", "MANUAL_REVIEW"] if f["classification"] == "REQUIRES_USER_INPUT"
                       else ["DECLINE", "MANUAL_REVIEW"]) if owner else []
            items.append({"findingId": f["findingId"], "allowedActions": actions,
                          "currentValue": self._current(plan, entries, f), "reason": "Decide this finding."})
        return 200, {"workbookId": workbook_id, "versionId": version_id, "auditId": audit_id, "items": items}

    def _current(self, plan, entries, finding):
        part, _, locator = finding["target"].partition("#")
        kind, _, key = locator.partition("=")
        if finding["ruleId"] == "ALT_TEXT" and kind == "id":
            props = next(p for p in _parse(entries[part], part).iter() if p.tag.endswith("}cNvPr") and p.get("id") == key)
            return {"title": props.get("title"), "description": props.get("descr")}
        if finding["ruleId"] == "WORKSHEET_NAME":
            return {"name": finding["worksheet"]}
        if finding["ruleId"] == "LINK_TEXT" and kind == "cell" and finding["classification"] == "REQUIRES_USER_INPUT":
            return {"text": plan._cell_text(part, key) or ""}
        if finding["ruleId"] == "TABLE_HEADER" and finding["classification"] == "REQUIRES_USER_INPUT":
            return {"headerRow": int(re.match(r"[A-Z]+([0-9]+)", key)[1]) if kind == "range" else 1}
        return None

    def remediation_status(self, subject, remediation_id, session=None, **_):
        record = self.remediations.get(remediation_id)
        if record is None or record["session"] != session:
            return _error(404, "NOT_FOUND", "No such remediation.")
        if not self._readable(subject, record["owner"]):
            return _error(403, "FORBIDDEN", "This remediation belongs to another user.")
        return 200, record["response"]

    def output(self, subject, output_id, session=None, **_):
        record = self.outputs.get(output_id)
        if record is None or record["session"] != session:
            return _error(404, "NOT_FOUND", "No such output.")
        if not self._readable(subject, record["owner"]):
            return _error(403, "FORBIDDEN", "This output belongs to another user.")
        version = self.versions[record["versionId"]]
        from .fake_project import XLSX, download
        return download(version["content"], XLSX, version["fileName"])

    def _readable(self, subject, owner):
        from .fake_project import can_read
        return can_read(subject, owner)

    ##  ---- Operation 7 ----

    def remediate(self, subject, workbook_id, version_id, body=b"", session=None, headers=None, **_):
        version, problem = self._version(subject, workbook_id, version_id, session, write=True)
        if problem:
            return problem
        key = (headers or {}).get("idempotency-key")
        if not key or not IDENTIFIER.match(key):
            return _error(400, "IDEMPOTENCY_KEY_REQUIRED", "A valid Idempotency-Key header is required.")
        try:
            request = json.loads(body)
        except ValueError:
            return _error(400, "INVALID_REQUEST", "The body is not JSON.")
        problem = self._shape(request)
        if problem:
            return problem
        canonical = json.dumps({"auditId": request["auditId"],
                                "decisions": sorted(request["decisions"], key=lambda d: d["findingId"])},
                               sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        scope = (subject, session, version_id, key)
        if scope in self.idempotency:
            digest, response = self.idempotency[scope]
            return (202, response) if digest == canonical else \
                _error(409, "IDEMPOTENCY_CONFLICT", "This key was used with a different request.")
        problem = self._semantics(version, request)
        if problem:
            return problem
        response = self._accept(subject, version, request, session)
        self.idempotency[scope] = (canonical, response)
        return 202, response

    def _shape(self, request):
        if not isinstance(request, dict) or set(request) != {"auditId", "decisions"}:
            return _error(400, "INVALID_REQUEST", "The body must have exactly auditId and decisions.")
        decisions = request["decisions"]
        if not isinstance(decisions, list) or not 1 <= len(decisions) <= 1000:
            return _error(400, "INVALID_REQUEST", "decisions must hold 1 to 1,000 items.")
        seen = set()
        for d in decisions:
            if not isinstance(d, dict) or set(d) - {"findingId", "action", "value"} or \
                    d.get("action") not in ("APPLY", "DECLINE", "MANUAL_REVIEW") or not SHA.match(str(d.get("findingId"))):
                return _error(400, "INVALID_REQUEST", "Each decision has findingId, action and, for APPLY, value.")
            if d["findingId"] in seen:
                return _error(400, "DUPLICATE_DECISION", "A finding is decided twice.")
            seen.add(d["findingId"])
            if d["action"] == "APPLY" and "value" not in d:
                return _error(400, "MISSING_VALUE", "APPLY needs a value.")
            if d["action"] != "APPLY" and "value" in d:
                return _error(400, "INVALID_REQUEST", "Only APPLY takes a value.")
        return None

    def _semantics(self, version, request):
        audit = self.audits.get(request["auditId"])
        if audit is None or request["auditId"] not in version["audits"]:
            return _error(404, "NOT_FOUND", "No such audit for this version.")
        latest = self._latest(version)
        if self._audit_status(latest) == "PROCESSING":
            return _error(409, "ACTIVE_OPERATION", "An audit is running on this version.")
        if latest["result"]["status"] == "PROCESSING_FAILED":
            return _error(409, "AUDIT_NOT_READY", "The latest audit failed.")
        if latest["auditId"] != request["auditId"]:
            return _error(409, "STALE_AUDIT", "A newer audit exists.")
        findings = {f["findingId"]: f for f in audit["result"]["findings"]}
        for d in request["decisions"]:
            if d["findingId"] not in findings:
                return _error(404, "FINDING_NOT_FOUND", "The finding is not in this audit.")
        renames = {}
        for d in request["decisions"]:
            if d["action"] != "APPLY":
                continue
            finding = findings[d["findingId"]]
            if finding["classification"] != "REQUIRES_USER_INPUT":
                return _error(422, "UNSUPPORTED_CORRECTION", "This finding has no supported correction.")
            problem = self._value(version, finding, d["value"])
            if problem:
                return problem
            if finding["ruleId"] == "WORKSHEET_NAME":
                renames[finding["worksheet"]] = d["value"]["name"]
        finals = [n.casefold() for n in renames.values()]
        if len(set(finals)) != len(finals) or set(finals) & {old.casefold() for old in renames}:
            return _error(422, "CONFLICTING_CORRECTIONS", "Requested names conflict.")
        return None

    def _value(self, version, finding, value):
        def invalid(why):
            return _error(422, "INVALID_CORRECTION", why)
        rule = finding["ruleId"]
        shapes = {"ALT_TEXT": {"title", "description"}, "WORKSHEET_NAME": {"name"}, "LINK_TEXT": {"text"},
                  "TABLE_HEADER": {"headerRow"}}
        if not isinstance(value, dict) or set(value) != shapes[rule]:
            return invalid("The value has the wrong shape for this rule.")
        if rule == "ALT_TEXT":
            title, description = value["title"], value["description"]
            if not all(isinstance(v, str) and trim(v) for v in (title, description)) or len(title) > 200 \
                    or len(description) > 800:
                return invalid("Alt text needs a nonblank title (200) and description (800).")
        if rule == "LINK_TEXT":
            if not isinstance(value["text"], str) or not trim(value["text"]) or len(value["text"]) > 1000 \
                    or _ambiguous(value["text"]):
                return invalid("The label is blank, too long or still ambiguous.")
        if rule == "TABLE_HEADER":
            row = value["headerRow"]
            locator = finding["target"].partition("#")[2]
            expected = int(re.match(r"range=[A-Z]+([0-9]+)", locator)[1]) if locator.startswith("range=") else 1
            if type(row) is not int or row != expected:
                return invalid("headerRow must be the candidate's first row.")
        if rule == "WORKSHEET_NAME":
            name, old = value["name"], finding["worksheet"]
            others = {n.casefold() for n in self._sheet_names(version) if n != old}
            if not isinstance(name, str) or not 1 <= len(name) <= 31 or name != trim(name) or FORBIDDEN & set(name) \
                    or name[:1] == "'" or name[-1:] == "'" or name.casefold() == "history" \
                    or re.fullmatch(r"(?i)sheet0*[1-9][0-9]*", name, re.ASCII) or name.casefold() == old.casefold() \
                    or name.casefold() in others:
                return invalid("The worksheet name is not valid.")
        return None

    def _sheet_names(self, version):
        entries, _ = read_package(version["content"], "source")
        return [name for name, _part in Plan(entries, []).sheets.values()]

    def _accept(self, subject, version, request, session):
        from .fake_project import now
        audit = self.audits[request["auditId"]]
        findings = {f["findingId"]: f for f in audit["result"]["findings"]}
        decisions = request["decisions"]
        changes = [change_from_decision(findings[d["findingId"]]["target"], d["value"])
                   for d in decisions if d["action"] == "APPLY"]
        try:
            output, _plan = edit_package(version["content"], changes) if changes else (version["content"], None)
        except ChangeError as problem:
            return _error(422, "UNSUPPORTED_CORRECTION", str(problem))
        applied = {findings[d["findingId"]]["target"] for d in decisions if d["action"] == "APPLY"}
        renames = {findings[d["findingId"]]["worksheet"]: d["value"]["name"] for d in decisions
                   if d["action"] == "APPLY" and findings[d["findingId"]]["ruleId"] == "WORKSHEET_NAME"}
        remaining = [{k: f[k] for k in ("ruleId", "category", "worksheet", "target", "classification")}
                     | {"worksheet": renames.get(f["worksheet"], f["worksheet"])}
                     for f in audit["result"]["findings"] if f["target"] not in applied]
        self.derived[hashlib.sha256(output).hexdigest()] = (remaining, audit["result"]["limitations"])
        name = version["fileName"][:-5] + "-remediated.xlsx"
        out_version = self._store_version(version["workbookId"], version["owner"], session, name, output,
                                          source_version=version["versionId"])
        out_audit = self._new_audit(out_version, None)
        self.audits[out_audit]["polls_left"] = 0     # spec 9: the output audit completes before the commit
        remediation_id, output_id = f"rem-{uuid.uuid4().hex[:10]}", f"out-{uuid.uuid4().hex[:10]}"
        out_version["remediationId"] = remediation_id
        self.outputs[output_id] = {"versionId": out_version["versionId"], "owner": version["owner"], "session": session}
        report_decisions = [{"sourceAuditId": audit["auditId"], "findingId": d["findingId"],
                             "ruleId": findings[d["findingId"]]["ruleId"], "worksheet": findings[d["findingId"]]["worksheet"],
                             "target": findings[d["findingId"]]["target"], "action": d["action"],
                             "value": d.get("value")} for d in decisions]
        self.remediations[remediation_id] = {
            "remediationId": remediation_id, "owner": version["owner"], "session": session, "outputId": output_id,
            "auditId": out_audit, "report_decisions": report_decisions, "created": now(),
            "response": {"remediationId": remediation_id, "status": "REMEDIATED", "sourceVersionId": version["versionId"],
                         "outputVersionId": out_version["versionId"], "outputId": output_id, "auditId": out_audit,
                         "error": None}}
        return {"remediationId": remediation_id, "sourceVersionId": version["versionId"], "status": "REMEDIATING"}
