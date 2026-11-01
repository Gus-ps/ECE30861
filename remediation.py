"""
Review accessibility findings and write a remediated copy of an .xlsx workbook.

Uses the checker in accessibility_checker (Haruki's branch) and the Phase 4
correction profile (Phase4_Shared_Specification.md, Sections 8 and 11):
    - Only REQUIRES_USER_INPUT findings for ALT_TEXT, WORKSHEET_NAME, LINK_TEXT
      and TABLE_HEADER can be applied, and only with a value the user supplied.
    - Edits are targeted changes to the affected XML parts; every other package
      entry is copied byte for byte. The source workbook is never modified.
    - A batch is all-or-nothing: if any decision or check fails, no output is written.
    - validate_decisions() runs every check that can be made before a job is
      accepted, so a service can reject a bad batch before replying 202.
    - The output is compared with the source by an independent parser; only the
      differences the approved corrections allow may appear.

Usage:
    python remediation.py <workbook.xlsx> [output.xlsx]
"""

import hashlib
import html
import io
import itertools
import json
import os
import posixpath
import re
import sys
import tempfile
import zipfile
from xml.sax.saxutils import escape

from openpyxl.utils.cell import range_boundaries

from accessibility_checker import safe_xml
from accessibility_checker.cell_reader import WorkbookReader
from accessibility_checker.checks.link_text import ambiguous_label
from accessibility_checker.phase3_policy import UNICODE_WHITE_SPACE
from accessibility_checker.runner import RULE_ORDER, check_workbook
from validity_check import validate_file

# Value fields the user must supply to APPLY a correction (spec Section 8).
FIELDS = {
    "ALT_TEXT": ("title", "description"),
    "WORKSHEET_NAME": ("name",),
    "LINK_TEXT": ("text",),
    "TABLE_HEADER": ("headerRow",),
}
APPLY_ORDER = ("ALT_TEXT", "LINK_TEXT", "TABLE_HEADER", "WORKSHEET_NAME")
MAX_DECISIONS = 1000
MAX_VALUE_BYTES = 8192
LOCATIONS = {
    "cell": "cell {}",
    "range": "cells {}",
    "merge": "merged cells {}",
    "conditional": "conditional formatting on {}",
    "sheetId": "worksheet tab",
    "id": "drawing object id {}",
    "tableId": "table id {}",
    "xml": "element {}",
}
MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
TABLE_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.table+xml"
ATTR_ESCAPES = {'"': "&quot;", "\n": "&#10;", "\r": "&#13;", "\t": "&#9;"}
BAD_XML = re.compile("[^\t\n\r\x20-퟿-�\U00010000-\U0010ffff]")
# Parts whose formulas or hyperlink locations may refer to a worksheet by name.
REFERENCE_PARTS = re.compile(r"xl/(?:workbook|(?:worksheets|charts|tables)/[^/]+)\.xml")
FORMULA_TAGS = {
    "f", "formula", "formula1", "formula2", "definedName", "calculatedColumnFormula",
    "totalsRowFormula",
}
# Elements whose text is a formula that may contain sheet references.
FORMULA = re.compile(r"(<((?:\w+:)?(?:%s))\b[^>]*>)([^<]*)(</\2>)" % "|".join(sorted(FORMULA_TAGS)))
LOCATION = re.compile(r'(<(?:\w+:)?hyperlink\b[^>]*?\slocation=")([^"]*)')
# A string literal (skipped) or a sheet qualifier such as Sheet2! or 'My Sheet'!
SHEET_REF = re.compile(r"\"(?:[^\"]|\"\")*\"|(?<![\w.'\]#])('(?:[^']|'')+'|[^\W\d][\w.]*)!")
UNQUOTED_SHEET = re.compile(r"[^\W\d][\w.]*(?=!)")


class RemediationError(ValueError):
    """A rejected decision batch or failed remediation; code follows spec Sections 8.2 and 10."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def review(path):
    """Audit a workbook and describe each finding for the user.

    Each finding gains "location" (readable position) and "input" (the value to
    fill in to apply a correction, or None when only manual review is possible).
    """
    findings = check_workbook(path)
    with zipfile.ZipFile(path) as archive:
        items = [dict(f, location=_location(f), input=_template(archive, f)) for f in findings]
    return {"findings": items, "limitations": findings.limitations}


def validate_decisions(path, decisions, findings=None):
    """Check a decision batch against the workbook without writing anything.

    Runs every check that can be made before a remediation is accepted (spec 8.2),
    including resolving and applying the edits in memory. Returns the canonical
    decision records in source finding order; raises RemediationError on the
    first problem found. findings: the stored source audit's findings, if known;
    passing them skips re-auditing the source.
    """
    return _plan(path, decisions, findings)["records"]


def remediate(src, dst, decisions, findings=None):
    """Apply approved decisions to a copy of src written to dst and return a report.

    decisions: [{"findingId", "action": APPLY|DECLINE|MANUAL_REVIEW, "value"}].
    findings: as for validate_decisions. Raises RemediationError and writes
    nothing if any decision or check fails.
    """
    if os.path.exists(dst) and os.path.samefile(src, dst):
        raise RemediationError("INVALID_REQUEST", "The output must not overwrite the source workbook.")
    plan = _plan(src, decisions, findings)
    fd, temp = tempfile.mkstemp(suffix=".xlsx", dir=os.path.dirname(os.path.abspath(dst)))
    os.close(fd)
    try:
        parts = plan["parts"]
        with zipfile.ZipFile(temp, "w") as out:
            for info in plan["infos"]:
                out.writestr(info, parts[info.filename])
            for name in sorted(parts.keys() - plan["original"].keys()):
                out.writestr(name, parts[name], zipfile.ZIP_DEFLATED)
        output = _verify(temp, plan)
        os.replace(temp, dst)
    finally:
        if os.path.exists(temp):
            os.remove(temp)

    return {
        "sourceSha256": _sha256(src),
        "outputSha256": _sha256(dst),
        "checksPerformed": list(RULE_ORDER),
        "decisions": plan["records"],
        "approvedChanges": plan["approved"],
        "unresolvedFindings": list(output),
        "manualReviewItems": [f for f in output if f["classification"] == "MANUAL_REVIEW"],
        "limitations": output.limitations,
    }


def _plan(src, decisions, findings=None):
    """Validate a batch and apply its edits to an in-memory copy of the package."""
    source = check_workbook(src) if findings is None else findings
    with zipfile.ZipFile(src) as archive:
        infos = archive.infolist()
        original = {info.filename: archive.read(info) for info in infos}
    order = {f["findingId"]: i for i, f in enumerate(source)}
    parts = dict(original)
    try:
        records = sorted(_validate(decisions, source, original), key=lambda r: order[r["findingId"]])
        approved = [r for r in records if r["action"] == "APPLY"]
        for record in sorted(approved, key=lambda r: APPLY_ORDER.index(r["ruleId"])):
            before = dict(parts)
            EDITORS[record["ruleId"]](parts, record, src)
            if parts == before:
                raise RemediationError(
                    "INVALID_CORRECTION", f"The {record['ruleId']} correction would not change the workbook."
                )
    except UnicodeDecodeError:
        raise RemediationError("UNSUPPORTED_CORRECTION", "A target part is not UTF-8 XML.") from None
    return {"records": records, "approved": approved, "infos": infos, "original": original, "parts": parts}


def _validate(decisions, source, parts):
    """Check each decision in input order, then the batch's interactions (spec 8.2, 10)."""
    if not isinstance(decisions, list) or not 1 <= len(decisions) <= MAX_DECISIONS:
        raise RemediationError("INVALID_REQUEST", "Provide 1 to 1,000 decisions.")
    by_id = {f["findingId"]: f for f in source}
    records, seen = [], set()
    for decision in decisions:
        if (
            not isinstance(decision, dict)
            or not isinstance(decision.get("findingId"), str)
            or not decision.keys() <= {"findingId", "action", "value"}
        ):
            raise RemediationError(
                "INVALID_REQUEST", "Each decision has only findingId, action and, for APPLY, value."
            )
        if decision["findingId"] in seen:
            raise RemediationError("DUPLICATE_DECISION", "Each finding may have only one decision.")
        seen.add(decision["findingId"])
        finding = by_id.get(decision["findingId"])
        action = decision.get("action")
        if finding is None:
            raise RemediationError("FINDING_NOT_FOUND", f"Unknown finding {decision['findingId']}.")
        if action not in ("APPLY", "DECLINE", "MANUAL_REVIEW"):
            raise RemediationError("INVALID_REQUEST", f"Unknown action {action!r}.")
        if action != "APPLY" and "value" in decision:
            raise RemediationError("INVALID_REQUEST", f"{action} does not take a value.")
        if action == "APPLY":
            if "value" not in decision:
                raise RemediationError("MISSING_VALUE", "A value is required to apply a fix.")
            value = decision["value"]
            if finding["classification"] != "REQUIRES_USER_INPUT" or finding["ruleId"] not in FIELDS:
                raise RemediationError("UNSUPPORTED_CORRECTION", "This finding needs manual review.")
            if not isinstance(value, dict) or set(value) != set(FIELDS[finding["ruleId"]]):
                fields = ", ".join(FIELDS[finding["ruleId"]])
                raise RemediationError("INVALID_CORRECTION", f"The value must contain: {fields}.")
            encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=repr)
            if len(encoded.encode("utf-8", "surrogatepass")) > MAX_VALUE_BYTES:
                raise RemediationError("INVALID_CORRECTION", "The value must be at most 8,192 bytes of JSON.")
            _check_value(finding, value, parts)
        records.append(
            {key: finding[key] for key in ("findingId", "ruleId", "worksheet", "target")}
            | {"action": action, "value": decision.get("value")}
        )
    _check_renames(records, parts)
    return records


def _check_value(finding, value, parts):
    """Rule-specific value checks (spec Sections 8.3 to 8.6)."""
    part, key, ref = _target(finding["target"])
    if finding["ruleId"] == "ALT_TEXT":
        _string(value["title"], 200)
        _string(value["description"], 800)
    elif finding["ruleId"] == "LINK_TEXT":
        if ambiguous_label(_string(value["text"], 1000), _destination(parts, part, ref)):
            raise RemediationError("INVALID_CORRECTION", "The new link text is still not descriptive.")
    elif finding["ruleId"] == "TABLE_HEADER":
        row = value["headerRow"]
        if type(row) is not int or row != range_boundaries(_rectangle(parts[part], key, ref))[1]:
            raise RemediationError("INVALID_CORRECTION", "Only the first row of the range can be the header.")
    else:
        new, old = _string(value["name"], 31), finding["worksheet"]
        if new == old:
            raise RemediationError("INVALID_CORRECTION", "The new name is the same as the current name.")
        if new.casefold() == old.casefold():
            raise RemediationError("UNSUPPORTED_CORRECTION", "Changing only the letter case of a name is not supported.")
        if (
            new != new.strip(UNICODE_WHITE_SPACE)
            or re.search(r"[:\\/?*\[\]\x00-\x1f]", new)
            or new[0] == "'"
            or new[-1] == "'"
            or new.casefold() == "history"
            or _generic(new)
        ):
            raise RemediationError("INVALID_CORRECTION", f"{new!r} is not a valid descriptive sheet name.")


def _check_renames(records, parts):
    """New sheet names must be unique among the source sheets and across the batch."""
    workbook = safe_xml.fromstring(parts["xl/workbook.xml"])
    taken = {sheet.get("name").casefold() for sheet in workbook.findall("{*}sheets/{*}sheet")}
    chosen = set()
    for record in records:
        if record["ruleId"] == "WORKSHEET_NAME" and record["action"] == "APPLY":
            name = record["value"]["name"]
            if name.casefold() in taken:
                raise RemediationError("CONFLICTING_CORRECTIONS", f"A sheet named {name!r} already exists.")
            if name.casefold() in chosen:
                raise RemediationError("CONFLICTING_CORRECTIONS", f"{name!r} is used by another rename.")
            chosen.add(name.casefold())


def _destination(parts, part, cell):
    """The hyperlink destination of cell, built the way the LINK_TEXT rule builds it."""
    links = [h for h in safe_xml.fromstring(parts[part]).iter(f"{{{MAIN_NS}}}hyperlink") if h.get("ref") == cell]
    if len(links) != 1:
        return ""
    location, rel_id = links[0].get("location", ""), links[0].get(f"{{{REL_NS}}}id")
    if rel_id is None:
        return location
    rels = safe_xml.fromstring(parts[_rels_path(part)])
    target = next((r.get("Target", "") for r in rels if r.get("Id") == rel_id), "")
    return target + ("#" + location if location else "")


def _verify(path, plan):
    """Check the candidate package, its preservation and the effect of every approved fix."""
    parts = plan["parts"]
    with zipfile.ZipFile(path) as out:
        if (
            out.testzip() is not None
            or sorted(out.namelist()) != sorted(parts)
            or any(out.read(n) != parts[n] for n in parts)
        ):
            raise RemediationError("PRESERVATION_FAILED", "Output entries differ from the plan.")
    errors = validate_file(path)
    if errors:
        raise RemediationError("OUTPUT_VALIDATION_FAILED", " ".join(errors))
    try:
        _check_preservation(path, plan)
    except RemediationError:
        raise
    except Exception as error:
        raise RemediationError("PRESERVATION_FAILED", f"The output could not be compared: {error}") from error
    try:
        output = check_workbook(path)
    except Exception as error:
        raise RemediationError("OUTPUT_AUDIT_FAILED", f"The output audit failed: {error}") from error
    remaining = {(f["ruleId"], f["target"]) for f in output}
    for record in plan["approved"]:
        if (record["ruleId"], record["target"]) in remaining:
            raise RemediationError(
                "INVALID_CORRECTION", f"{record['ruleId']} at {record['target']} is still reported."
            )
    return output


def _location(finding):
    part, key, ref = _target(finding["target"])
    return f"sheet '{finding['worksheet']}', {LOCATIONS.get(key, '{}').format(ref)} ({part})"


def _template(archive, finding):
    if finding["classification"] != "REQUIRES_USER_INPUT" or finding["ruleId"] not in FIELDS:
        return None
    part, key, ref = _target(finding["target"])
    if finding["ruleId"] == "ALT_TEXT":
        tag = _find(_cnvpr(ref), archive.read(part).decode("utf-8")).group(0)
        return {"title": _attr(tag, "title") or "", "description": _attr(tag, "descr") or ""}
    if finding["ruleId"] == "TABLE_HEADER":
        return {"headerRow": range_boundaries(_rectangle(archive.read(part), key, ref))[1]}
    return {FIELDS[finding["ruleId"]][0]: ""}


def _rectangle(data, key, ref):
    """The candidate range of a TABLE_HEADER finding; an existing table's comes from its part."""
    if key == "tableId":
        return _attr(_find(r"<(?:\w+:)?table\b[^>]*>", data.decode("utf-8")).group(0), "ref")
    return ref


def _alt_text(parts, record, src):
    title, description = record["value"]["title"], record["value"]["description"]
    part, _, object_id = _target(record["target"])
    xml = parts[part].decode("utf-8")
    match = _find(_cnvpr(object_id), xml)
    attrs = re.sub(r"\s(?:title|descr)=(?:\"[^\"]*\"|'[^']*')", "", match.group(2))
    tag = f'<{match.group(1)}{attrs} title="{_esc(title)}" descr="{_esc(description)}"{match.group(3)}>'
    parts[part] = (xml[: match.start()] + tag + xml[match.end() :]).encode("utf-8")


def _link_text(parts, record, src):
    text = record["value"]["text"]
    part, _, cell = _target(record["target"])
    xml = parts[part].decode("utf-8")
    pattern = r'<((?:\w+:)?)c\b((?=[^>]*\sr="%s")[^>]*?)(?:/>|>.*?</\1c>)' % cell
    match = _find(re.compile(pattern, re.S), xml)
    p, attrs = match.group(1), re.sub(r'\st="[^"]*"', "", match.group(2))
    # An explicit inline string is always text, so "=" or "+" is never a formula.
    # A literal carriage return would be read back as a line feed, so it is escaped.
    body = escape(text, {"\r": "&#13;"})
    new = f'<{p}c{attrs} t="inlineStr"><{p}is><{p}t xml:space="preserve">{body}</{p}t></{p}is></{p}c>'
    xml = xml[: match.start()] + new + xml[match.end() :]
    display = r'(<(?:\w+:)?hyperlink\b(?=[^>]*\sref="%s")[^>]*?\sdisplay=")[^"]*' % cell
    xml = re.sub(display, lambda m: m.group(1) + _esc(text), xml)
    parts[part] = xml.encode("utf-8")


def _table_header(parts, record, src):
    part, key, ref = _target(record["target"])
    if key == "tableId":
        # Existing table with its header disabled: only headerRowCount changes.
        xml = parts[part].decode("utf-8")
        match = _find(r"<(?:\w+:)?table\b[^>]*>", xml)
        tag = re.sub(r'\sheaderRowCount="0"', ' headerRowCount="1"', match.group(0))
        parts[part] = (xml[: match.start()] + tag + xml[match.end() :]).encode("utf-8")
    else:
        _add_table(parts, part, ref, src)


def _add_table(parts, sheet_part, ref, src):
    """Create a minimal table over ref with its first row as the header (spec 8.6)."""
    root = _find(r"<((?:\w+:)?)worksheet\b[^>]*>", parts[sheet_part].decode("utf-8"))
    if f'"{MAIN_NS}"' not in root.group(0):
        raise RemediationError("UNSUPPORTED_CORRECTION", "Only Transitional workbooks are supported.")
    min_col, min_row, max_col, _ = range_boundaries(ref)
    with WorkbookReader(src) as reader:
        sheet = next(s for s in reader.sheets if s.part == sheet_part)
        labels = {c.column: c.value for c in reader.read_cells(sheet) if c.row == min_row}
    names = [labels[col] for col in range(min_col, max_col + 1)]

    tables = [
        _find(r"<(?:\w+:)?table\b[^>]*>", parts[n].decode("utf-8")).group(0)
        for n in parts
        if re.fullmatch(r"xl/tables/[^/]+\.xml", n)
    ]
    table_id = _lowest({int(_attr(t, "id")) for t in tables})
    workbook = parts["xl/workbook.xml"].decode("utf-8")
    taken = {(_attr(t, a) or "").casefold() for t in tables for a in ("name", "displayName")}
    taken |= {html.unescape(n).casefold() for n in re.findall(r'<(?:\w+:)?definedName\b[^>]*\sname="([^"]*)"', workbook)}
    name = next(
        n for n in itertools.chain([f"A11yTable{table_id}"], (f"A11yTable{table_id}_{k}" for k in itertools.count(1)))
        if n.casefold() not in taken
    )
    path = "xl/tables/table%d.xml" % _lowest(
        {int(n) for n in re.findall(r"xl/tables/table(\d+)\.xml", "\n".join(parts))}
    )
    columns = "".join(f'<tableColumn id="{i}" name="{_esc(n)}"/>' for i, n in enumerate(names, 1))
    parts[path] = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f'<table xmlns="{MAIN_NS}" id="{table_id}" name="{name}" displayName="{name}" ref="{ref}" '
        f'headerRowCount="1" totalsRowShown="0"><tableColumns count="{len(names)}">{columns}'
        "</tableColumns></table>"
    ).encode("utf-8")

    rels_path = _rels_path(sheet_part)
    rels = parts.get(rels_path, b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                     b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>')
    rels = re.sub(r"<Relationships\b([^>]*?)\s*/>", r"<Relationships\1></Relationships>", rels.decode("utf-8"))
    rel_id = "rId%d" % _lowest({int(n) for n in re.findall(r'\sId="rId(\d+)"', rels)})
    target = posixpath.relpath(path, posixpath.dirname(sheet_part))
    rel = f'<Relationship Id="{rel_id}" Type="{REL_NS}/table" Target="{target}"/>'
    parts[rels_path] = rels.replace("</Relationships>", rel + "</Relationships>").encode("utf-8")

    xml = parts[sheet_part].decode("utf-8")
    p, tag = root.group(1), root.group(0)
    prefix = re.search(r'\sxmlns:(\w+)="%s"' % re.escape(REL_NS), tag)
    if prefix is None:
        if " xmlns:r=" in tag:
            raise RemediationError("UNSUPPORTED_CORRECTION", "The worksheet namespaces are unsupported.")
        xml = xml.replace(tag, tag[:-1] + f' xmlns:r="{REL_NS}">', 1)
    part_tag = f'<{p}tablePart {prefix.group(1) if prefix else "r"}:id="{rel_id}"/>'
    if f"<{p}tableParts" in xml:
        count = rf'(<{p}tableParts\b[^>]*\scount=")(\d+)'
        xml = re.sub(count, lambda m: m.group(1) + str(int(m.group(2)) + 1), xml, count=1)
        xml = xml.replace(f"</{p}tableParts>", part_tag + f"</{p}tableParts>", 1)
    else:
        at = _child(xml, "extLst") or xml.rindex(f"</{p}worksheet>")
        xml = xml[:at] + f'<{p}tableParts count="1">{part_tag}</{p}tableParts>' + xml[at:]
    parts[sheet_part] = xml.encode("utf-8")
    types = parts["[Content_Types].xml"].decode("utf-8")
    override = f'<Override PartName="/{path}" ContentType="{TABLE_TYPE}"/>'
    parts["[Content_Types].xml"] = types.replace("</Types>", override + "</Types>").encode("utf-8")


def _rename(parts, record, src):
    """Rename a sheet and rewrite references to it in formulas, names, charts and links."""
    new, old = record["value"]["name"], record["worksheet"]
    workbook = parts["xl/workbook.xml"].decode("utf-8")
    sheet_id = _target(record["target"])[2]
    match = _find(r'<(?:\w+:)?sheet\b(?=[^>]*\ssheetId="%s")[^>]*>' % sheet_id, workbook)
    tag = re.sub(r'\sname="[^"]*"', f' name="{_esc(new)}"', match.group(0))
    parts["xl/workbook.xml"] = (workbook[: match.start()] + tag + workbook[match.end() :]).encode("utf-8")

    def formula(m):
        text = _rewrite(html.unescape(m.group(3)), old, new)
        return m.group(0) if text == html.unescape(m.group(3)) else m.group(1) + escape(text) + m.group(4)

    def location(m):
        text = _rewrite(html.unescape(m.group(2)), old, new)
        return m.group(0) if text == html.unescape(m.group(2)) else m.group(1) + _esc(text)

    for name in parts:
        if REFERENCE_PARTS.fullmatch(name):
            xml = parts[name].decode("utf-8")
            changed = LOCATION.sub(location, FORMULA.sub(formula, xml))
            if changed != xml:
                parts[name] = changed.encode("utf-8")


def _rewrite(text, old, new):
    """Point sheet qualifiers for old at new, leaving string literals untouched."""

    def replace(m):
        name = m.group(1)
        if name is None:
            return m.group(0)
        if name.startswith("'"):
            name = name[1:-1].replace("''", "'")
        return "'" + new.replace("'", "''") + "'!" if name.casefold() == old.casefold() else m.group(0)

    return SHEET_REF.sub(replace, text)


EDITORS = {
    "ALT_TEXT": _alt_text,
    "LINK_TEXT": _link_text,
    "TABLE_HEADER": _table_header,
    "WORKSHEET_NAME": _rename,
}


# Independent preservation check (spec Section 11). It re-reads both packages with
# the checker's safe parser and does not reuse the editors' regular expressions:
# each approved difference is checked for its exact expected value and then removed
# from both trees, and the remaining trees must be identical.


def _check_preservation(path, plan):
    original = plan["original"]
    with zipfile.ZipFile(path) as out:
        infos = {info.filename: info for info in out.infolist()}
        output = {name: out.read(info) for name, info in infos.items()}
    for info in plan["infos"]:
        if info.filename not in infos or infos[info.filename].compress_type != info.compress_type:
            _mismatch(info.filename, "the entry is missing or its compression changed")

    alt, links, headers, tables, renames = {}, {}, set(), {}, []
    for record in plan["approved"]:
        part, key, ref = _target(record["target"])
        value = record["value"]
        if record["ruleId"] == "ALT_TEXT":
            alt.setdefault(part, {})[ref] = (value["title"], value["description"])
        elif record["ruleId"] == "LINK_TEXT":
            links.setdefault(part, {})[ref] = value["text"]
        elif record["ruleId"] == "TABLE_HEADER" and key == "tableId":
            headers.add(part)
        elif record["ruleId"] == "TABLE_HEADER":
            tables.setdefault(part, []).append(ref)
        else:
            renames.append((record["worksheet"], value["name"], ref))

    rel_ids, table_paths, created = _check_new_tables(path, original, output, tables)
    if set(output) - set(original) != created:
        _mismatch(", ".join(sorted(set(output) - set(original) - created)), "unexpected new entry")
    sheet_rels = {_rels_path(sheet): sheet for sheet in tables}

    for name in sorted(original):
        if output[name] == original[name]:
            if renames and REFERENCE_PARTS.fullmatch(name):
                _check_stale(name, _parse(name, output[name])[0], renames)
            continue
        a, a_ns = _parse(name, original[name])
        b, b_ns = _parse(name, output[name])
        if not a_ns <= b_ns or b_ns - a_ns - {("r", REL_NS)}:
            _mismatch(name, "namespace declarations changed")
        for object_id, (title, description) in alt.get(name, {}).items():
            x = _one(name, a, lambda e: _local(e) == "cNvPr" and e.get("id") == object_id)
            y = _one(name, b, lambda e: _local(e) == "cNvPr" and e.get("id") == object_id)
            if y.get("title") != title or y.get("descr") != description:
                _mismatch(name, f"object {object_id} does not have the approved alternative text")
            for e in (x, y):
                e.attrib.pop("title", None)
                e.attrib.pop("descr", None)
        for cell, text in links.get(name, {}).items():
            _strip_link(name, a, b, cell, text)
        if name in headers:
            if a.get("headerRowCount") != "0" or b.get("headerRowCount") != "1":
                _mismatch(name, "headerRowCount is not changed from 0 to 1")
            del a.attrib["headerRowCount"], b.attrib["headerRowCount"]
        if name in tables:
            _strip_table_parts(name, a, b, rel_ids[name])
        if name in sheet_rels:
            for e in [e for e in b if e.get("Id") in rel_ids[sheet_rels[name]]]:
                b.remove(e)
        if name == "[Content_Types].xml":
            new = [e for e in b if _local(e) == "Override" and e.get("PartName", "")[1:] in table_paths]
            if sorted(e.get("PartName")[1:] for e in new) != sorted(table_paths) or any(
                e.get("ContentType") != TABLE_TYPE for e in new
            ):
                _mismatch(name, "the new tables are not declared exactly once")
            for e in new:
                b.remove(e)
        if name == "xl/workbook.xml":
            for old, new, sheet_id in renames:
                x = _one(name, a, lambda e: _local(e) == "sheet" and e.get("sheetId") == sheet_id)
                y = _one(name, b, lambda e: _local(e) == "sheet" and e.get("sheetId") == sheet_id)
                if x.get("name") != old or y.get("name") != new:
                    _mismatch(name, f"sheet {sheet_id} is not renamed from {old!r} to {new!r}")
                del x.attrib["name"], y.attrib["name"]
        _same(name, a, b, renames)
        if renames and REFERENCE_PARTS.fullmatch(name):
            _check_stale(name, b, renames)


def _check_new_tables(path, original, output, tables):
    """Check each table added for an unstructured header range and return what was added."""
    rel_ids, table_paths, created = {}, set(), set()
    for sheet, refs in tables.items():
        rels_path = _rels_path(sheet)
        before = {e.get("Id") for e in _parse(rels_path, original[rels_path])[0]} if rels_path in original else set()
        if rels_path not in output:
            _mismatch(rels_path, "the worksheet relationships are missing")
        rels = _parse(rels_path, output[rels_path])[0]
        new = [e for e in rels if e.get("Id") not in before]
        if rels_path not in original:
            created.add(rels_path)
            if _local(rels) != "Relationships" or len(rels) != len(new):
                _mismatch(rels_path, "the new relationships part has unexpected content")
        if len(new) != len(refs):
            _mismatch(rels_path, "the number of new relationships does not match the new tables")
        remaining = list(refs)
        for rel in new:
            table_path = posixpath.normpath(posixpath.join(posixpath.dirname(sheet), rel.get("Target", "")))
            if (
                rel.get("Type") != REL_NS + "/table"
                or rel.get("TargetMode") is not None
                or table_path in original
                or table_path in table_paths
                or table_path not in output
            ):
                _mismatch(rels_path, f"relationship {rel.get('Id')} is not a new table")
            table = _parse(table_path, output[table_path])[0]
            if table.get("ref") not in remaining:
                _mismatch(table_path, "the table range was not approved")
            remaining.remove(table.get("ref"))
            _check_table(path, output, sheet, table_path, table)
            table_paths.add(table_path)
        rel_ids[sheet] = {e.get("Id") for e in new}
    return rel_ids, table_paths, created | table_paths


def _check_table(path, output, sheet, table_path, table):
    """A new table must be minimal, uniquely identified and named after its header cells."""
    columns = table.findall(f"{{{MAIN_NS}}}tableColumns/{{{MAIN_NS}}}tableColumn")
    min_col, min_row, max_col, _ = range_boundaries(table.get("ref"))
    with WorkbookReader(path) as reader:
        info = next(s for s in reader.sheets if s.part == sheet)
        labels = {c.column: c.value for c in reader.read_cells(info) if c.row == min_row}
    if (
        table.tag != f"{{{MAIN_NS}}}table"
        or table.get("headerRowCount") != "1"
        or table.get("totalsRowCount", "0") != "0"
        or table.get("name") != table.get("displayName")
        or [_local(e) for e in table] != ["tableColumns"]
        or table[0].get("count") != str(len(columns))
        or [c.get("name") for c in columns] != [labels.get(col) for col in range(min_col, max_col + 1)]
    ):
        _mismatch(table_path, "the new table is not a minimal header table over its range")
    others = [
        _parse(n, output[n])[0] for n in output if re.fullmatch(r"xl/tables/[^/]+\.xml", n) and n != table_path
    ]
    workbook = _parse("xl/workbook.xml", output["xl/workbook.xml"])[0]
    names = {(t.get(a) or "").casefold() for t in others for a in ("name", "displayName")}
    names |= {(e.get("name") or "").casefold() for e in workbook.iter(f"{{{MAIN_NS}}}definedName")}
    if table.get("id") in {t.get("id") for t in others} or table.get("name").casefold() in names:
        _mismatch(table_path, "the new table's id or name is not unique")


def _strip_link(name, a, b, cell, text):
    x = _one(name, a, lambda e: _local(e) == "c" and e.get("r") == cell)
    y = _one(name, b, lambda e: _local(e) == "c" and e.get("r") == cell)
    if (
        y.get("t") != "inlineStr"
        or [_local(e) for e in y] != ["is"]
        or [_local(e) for e in y[0]] != ["t"]
        or y[0][0].text != text
    ):
        _mismatch(name, f"cell {cell} does not hold the approved link text as an inline string")
    for e in (x, y):
        e.attrib.pop("t", None)
        e[:] = []
        e.text = None
    old = [e for e in a.iter() if _local(e) == "hyperlink" and e.get("ref") == cell]
    new = [e for e in b.iter() if _local(e) == "hyperlink" and e.get("ref") == cell]
    for x, y in zip(old, new):
        if "display" in x.attrib:
            if y.get("display") != text:
                _mismatch(name, f"the hyperlink at {cell} does not display the approved text")
            del x.attrib["display"], y.attrib["display"]


def _strip_table_parts(name, a, b, rel_ids):
    rid = f"{{{REL_NS}}}id"
    holders = [e for e in b if _local(e) == "tableParts"]
    before = [e for e in a if _local(e) == "tableParts"]
    if len(holders) != 1:
        _mismatch(name, "the worksheet does not have exactly one tableParts element")
    holder = holders[0]
    added = [e for e in holder if e.get(rid) in rel_ids]
    if len(added) != len(rel_ids):
        _mismatch(name, "a new table is not referenced from tableParts")
    if any(_local(e) != "extLst" for e in list(b)[list(b).index(holder) + 1 :]):
        _mismatch(name, "tableParts is out of schema order")
    for e in added:
        holder.remove(e)
    count = int(before[0].get("count")) if before else 0
    if holder.get("count") != str(count + len(rel_ids)):
        _mismatch(name, "the tableParts count is wrong")
    if before:
        holder.set("count", before[0].get("count"))
    elif len(holder):
        _mismatch(name, "tableParts holds unexpected entries")
    else:
        b.remove(holder)


def _same(name, a, b, renames):
    """Require identical trees; a formula or link may differ only by an approved rename."""
    if a.tag != b.tag or len(a) != len(b) or a.attrib.keys() != b.attrib.keys():
        _mismatch(name, f"<{_local(a)}> changed")
    for key, value in a.attrib.items():
        if b.get(key) != value and not (
            renames and _local(a) == "hyperlink" and key == "location" and _explained(value, b.get(key), renames)
        ):
            _mismatch(name, f"attribute {key} of <{_local(a)}> changed")
    if (a.text or "") != (b.text or "") and not (
        renames and _local(a) in FORMULA_TAGS and _explained(a.text or "", b.text or "", renames)
    ):
        _mismatch(name, f"the text of <{_local(a)}> changed")
    if (a.tail or "") != (b.tail or ""):
        _mismatch(name, f"the text after <{_local(a)}> changed")
    for x, y in zip(a, b):
        _same(name, x, y, renames)


def _explained(before, after, renames):
    """True when after is before with some old-sheet qualifiers replaced by quoted new names."""
    pattern, i = [], 0
    while i < len(after):
        for old, new, _ in renames:
            qualifier = "'" + new.replace("'", "''") + "'!"
            if after.startswith(qualifier, i):
                quoted = re.escape("'" + old.replace("'", "''") + "'")
                pattern.append(f"(?i:{quoted}|{re.escape(old)})!")
                i += len(qualifier)
                break
        else:
            end = _token_end(after, i)
            pattern.append(re.escape(after[i:end]))
            i = end
    return re.fullmatch("".join(pattern), before) is not None


def _check_stale(name, root, renames):
    """No formula or internal link outside a string literal may still use an old sheet name."""
    olds = {old.casefold() for old, _, _ in renames}
    for e in root.iter():
        if _local(e) in FORMULA_TAGS:
            text = e.text or ""
        elif _local(e) == "hyperlink":
            text = e.get("location", "")
        else:
            continue
        i = 0
        while i < len(text):
            end = _token_end(text, i)
            if text[i] == "'":
                stale = text[end : end + 1] == "!" and text[i + 1 : end - 1].replace("''", "'").casefold() in olds
            else:
                match = text[i] != '"' and UNQUOTED_SHEET.match(text, i)
                stale = bool(match) and (i == 0 or not re.match(r"[\w.'\]#]", text[i - 1])) and (
                    match.group(0).casefold() in olds
                )
            if stale:
                _mismatch(name, f"<{_local(e)}> still refers to a renamed sheet")
            i = end


def _token_end(text, i):
    """End of the token at i: a whole quoted name or string literal, or one character."""
    quote = text[i]
    if quote not in "\"'":
        return i + 1
    j = i + 1
    while j < len(text):
        if text[j] == quote:
            if text[j + 1 : j + 2] != quote:
                return j + 1
            j += 1
        j += 1
    return len(text)


def _parse(name, data):
    """Parse a part with the checker's safe parser; return its root and namespace declarations."""
    root, declared = None, set()
    try:
        for event, item in safe_xml.iterparse(io.BytesIO(data), events=("start-ns", "end")):
            if event == "start-ns":
                declared.add(item)
            else:
                root = item
    except Exception as error:
        _mismatch(name, f"the part is not well-formed XML ({error})")
    return root, declared


def _one(name, root, predicate):
    matches = [e for e in root.iter() if predicate(e)]
    if len(matches) != 1:
        _mismatch(name, "a corrected element could not be located uniquely")
    return matches[0]


def _local(element):
    return element.tag.rpartition("}")[2]


def _mismatch(name, reason):
    raise RemediationError("PRESERVATION_FAILED", f"{name}: {reason}.")


def _child(xml, name):
    """Start index of the root element's direct child with this local name, if any."""
    depth = 0
    for m in re.finditer(r"<(/?)([\w.:-]+)[^>]*?(/?)>", xml):
        if m.group(1):
            depth -= 1
            continue
        if depth == 1 and m.group(2).split(":")[-1] == name:
            return m.start()
        depth += not m.group(3)
    return None


def _target(target):
    part, _, fragment = target.partition("#")
    key, _, ref = fragment.partition("=")
    return part, key, ref


def _rels_path(part):
    return posixpath.join(posixpath.dirname(part), "_rels", posixpath.basename(part) + ".rels")


def _cnvpr(object_id):
    return r'<((?:\w+:)?cNvPr)((?=[^>]*\sid="%s")[^>]*?)(/?)>' % re.escape(object_id)


def _find(pattern, xml):
    matches = list(re.finditer(pattern, xml))
    if len(matches) != 1:
        raise RemediationError("UNSUPPORTED_CORRECTION", "The target could not be located uniquely.")
    return matches[0]


def _attr(tag, name):
    match = re.search(rf'\s{name}="([^"]*)"', tag)
    return html.unescape(match.group(1)) if match else None


def _string(value, limit):
    if (
        not isinstance(value, str)
        or not value.strip(UNICODE_WHITE_SPACE)
        or len(value) > limit
        or BAD_XML.search(value)
    ):
        raise RemediationError("INVALID_CORRECTION", f"Enter nonblank text of at most {limit} characters.")
    return value


def _generic(name):
    """The WORKSHEET_NAME rule's default-name test (Sheet followed by a positive number)."""
    match = re.fullmatch(r"sheet([0-9]+)", name.strip(UNICODE_WHITE_SPACE), re.IGNORECASE | re.ASCII)
    return match is not None and match.group(1).lstrip("0") != ""


def _esc(value):
    return escape(value, ATTR_ESCAPES)


def _lowest(used):
    return next(i for i in itertools.count(1) if i not in used)


def _sha256(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def main():
    if len(sys.argv) not in (2, 3):
        print("Usage: python remediation.py <workbook.xlsx> [output.xlsx]")
        sys.exit(2)
    src = sys.argv[1]
    errors = validate_file(src)
    if errors:
        print(*errors, sep="\n")
        sys.exit(1)
    result = review(src)
    decisions = []
    for number, finding in enumerate(result["findings"], 1):
        print(f"\n{number}. {finding['ruleId']} ({finding['classification']}) at {finding['location']}")
        print(f"   {finding['message']}\n   Suggestion: {finding['recommendation']}")
        value = finding["input"]
        if value is None or input("   Apply a correction? [y/N] ").strip().lower() != "y":
            continue
        for key in value:
            if key != "headerRow":
                value[key] = input(f"   {key} [{value[key]}]: ") or value[key]
        decisions.append({"findingId": finding["findingId"], "action": "APPLY", "value": value})
    for limitation in result["limitations"]:
        print("Limitation:", limitation)
    if not result["findings"] or not decisions:
        print("\nNo corrections selected; no copy was written.")
        return
    dst = sys.argv[2] if len(sys.argv) == 3 else os.path.splitext(src)[0] + "-remediated.xlsx"
    try:
        report = remediate(src, dst, decisions)
    except RemediationError as error:
        print(f"\nNo copy was written ({error.code}): {error}")
        sys.exit(1)
    with open(os.path.splitext(dst)[0] + "-report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"\nWrote {dst}: {len(report['approvedChanges'])} change(s) applied, "
          f"{len(report['unresolvedFindings'])} finding(s) still open.")


if __name__ == "__main__":
    main()
