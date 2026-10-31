"""
Review accessibility findings and write a remediated copy of an .xlsx workbook.

Uses the checker in accessibility_checker (Haruki's branch) and the Phase 4
correction profile (Phase4_Shared_Specification.md, Sections 8 and 11):
    - Only REQUIRES_USER_INPUT findings for ALT_TEXT, WORKSHEET_NAME, LINK_TEXT
      and TABLE_HEADER can be applied, and only with a value the user supplied.
    - Edits are targeted changes to the affected XML parts; every other package
      entry is copied byte for byte. The source workbook is never modified.
    - A batch is all-or-nothing: if any decision or check fails, no output is written.

Usage:
    python remediation.py <workbook.xlsx> [output.xlsx]
"""

import hashlib
import html
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

from accessibility_checker.cell_reader import WorkbookReader
from accessibility_checker.checks.link_text import ambiguous_label
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
GENERIC_NAME = re.compile(r"\s*sheet0*[1-9][0-9]*\s*", re.IGNORECASE | re.ASCII)
# Elements whose text is a formula that may contain sheet references.
FORMULA = re.compile(
    r"(<((?:\w+:)?(?:f|formula|formula1|formula2|definedName|calculatedColumnFormula"
    r"|totalsRowFormula))\b[^>]*>)([^<]*)(</\2>)"
)
LOCATION = re.compile(r'(<(?:\w+:)?hyperlink\b[^>]*?\slocation=")([^"]*)')
# A string literal (skipped) or a sheet qualifier such as Sheet2! or 'My Sheet'!
SHEET_REF = re.compile(r"\"(?:[^\"]|\"\")*\"|(?<![\w.'\]#])('(?:[^']|'')+'|[^\W\d][\w.]*)!")


class RemediationError(ValueError):
    """A rejected decision batch or failed remediation; code follows spec Section 8.2."""

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


def remediate(src, dst, decisions):
    """Apply approved decisions to a copy of src written to dst and return a report.

    decisions: [{"findingId", "action": APPLY|DECLINE|MANUAL_REVIEW, "value"}].
    Raises RemediationError and writes nothing if any decision or check fails.
    """
    if os.path.exists(dst) and os.path.samefile(src, dst):
        raise RemediationError("INVALID_REQUEST", "The output must not overwrite the source workbook.")
    source = check_workbook(src)
    order = {f["findingId"]: i for i, f in enumerate(source)}
    records = sorted(_validate(decisions, source), key=lambda r: order[r["findingId"]])
    approved = [r for r in records if r["action"] == "APPLY"]
    with zipfile.ZipFile(src) as archive:
        infos = archive.infolist()
        parts = {info.filename: archive.read(info) for info in infos}
    editors = {
        "ALT_TEXT": _alt_text,
        "LINK_TEXT": _link_text,
        "TABLE_HEADER": _table_header,
        "WORKSHEET_NAME": _rename,
    }
    try:
        for record in sorted(approved, key=lambda r: APPLY_ORDER.index(r["ruleId"])):
            editors[record["ruleId"]](parts, record, src)
    except UnicodeDecodeError:
        raise RemediationError("UNSUPPORTED_CORRECTION", "A target part is not UTF-8 XML.") from None

    fd, temp = tempfile.mkstemp(suffix=".xlsx", dir=os.path.dirname(os.path.abspath(dst)))
    os.close(fd)
    try:
        with zipfile.ZipFile(temp, "w") as out:
            for info in infos:
                out.writestr(info, parts[info.filename])
            for name in sorted(parts.keys() - {info.filename for info in infos}):
                out.writestr(name, parts[name], zipfile.ZIP_DEFLATED)
        output = _verify(temp, parts, approved)
        os.replace(temp, dst)
    finally:
        if os.path.exists(temp):
            os.remove(temp)

    return {
        "sourceSha256": _sha256(src),
        "outputSha256": _sha256(dst),
        "checksPerformed": list(RULE_ORDER),
        "decisions": records,
        "approvedChanges": approved,
        "unresolvedFindings": list(output),
        "manualReviewItems": [f for f in output if f["classification"] == "MANUAL_REVIEW"],
        "limitations": output.limitations,
    }


def _validate(decisions, source):
    by_id = {f["findingId"]: f for f in source}
    if (
        not isinstance(decisions, list)
        or not 1 <= len(decisions) <= 1000
        or not all(isinstance(d, dict) and isinstance(d.get("findingId"), str) for d in decisions)
    ):
        raise RemediationError("INVALID_REQUEST", "Provide 1 to 1,000 decisions, each with a findingId.")
    ids = [d["findingId"] for d in decisions]
    if len(set(ids)) != len(ids):
        raise RemediationError("DUPLICATE_DECISION", "Each finding may have only one decision.")
    records = []
    for decision in decisions:
        finding = by_id.get(decision["findingId"])
        action = decision.get("action")
        if finding is None:
            raise RemediationError("FINDING_NOT_FOUND", f"Unknown finding {decision['findingId']}.")
        if action not in ("APPLY", "DECLINE", "MANUAL_REVIEW"):
            raise RemediationError("INVALID_REQUEST", f"Unknown action {action!r}.")
        if action != "APPLY" and "value" in decision:
            raise RemediationError("INVALID_REQUEST", f"{action} does not take a value.")
        if action == "APPLY":
            value = decision.get("value")
            if value is None:
                raise RemediationError("MISSING_VALUE", "A value is required to apply a fix.")
            if finding["classification"] != "REQUIRES_USER_INPUT" or finding["ruleId"] not in FIELDS:
                raise RemediationError("UNSUPPORTED_CORRECTION", "This finding needs manual review.")
            if not isinstance(value, dict) or set(value) != set(FIELDS[finding["ruleId"]]):
                fields = ", ".join(FIELDS[finding["ruleId"]])
                raise RemediationError("INVALID_CORRECTION", f"The value must contain: {fields}.")
        records.append(
            {key: finding[key] for key in ("findingId", "ruleId", "worksheet", "target")}
            | {"action": action, "value": decision.get("value")}
        )
    return records


def _verify(path, parts, approved):
    """Check the candidate package, its bytes and the effect of every approved fix."""
    with zipfile.ZipFile(path) as out:
        if (
            out.testzip() is not None
            or sorted(out.namelist()) != sorted(parts)
            or any(out.read(n) != parts[n] for n in parts)
        ):
            raise RemediationError("PRESERVATION_FAILED", "Output entries differ from the plan.")
    output = check_workbook(path)
    remaining = {(f["ruleId"], f["target"]) for f in output}
    for record in approved:
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
        if key == "tableId":
            ref = _attr(_find(r"<(?:\w+:)?table\b[^>]*>", archive.read(part).decode()).group(0), "ref")
        return {"headerRow": range_boundaries(ref)[1]}
    return {FIELDS[finding["ruleId"]][0]: ""}


def _alt_text(parts, record, src):
    title = _string(record["value"]["title"], 200)
    description = _string(record["value"]["description"], 800)
    part, _, object_id = _target(record["target"])
    xml = parts[part].decode("utf-8")
    match = _find(_cnvpr(object_id), xml)
    attrs = re.sub(r"\s(?:title|descr)=(?:\"[^\"]*\"|'[^']*')", "", match.group(2))
    tag = f'<{match.group(1)}{attrs} title="{_esc(title)}" descr="{_esc(description)}"{match.group(3)}>'
    parts[part] = (xml[: match.start()] + tag + xml[match.end() :]).encode("utf-8")


def _link_text(parts, record, src):
    text = _string(record["value"]["text"], 1000)
    if ambiguous_label(text, ""):
        raise RemediationError("INVALID_CORRECTION", "The new link text is still not descriptive.")
    part, _, cell = _target(record["target"])
    xml = parts[part].decode("utf-8")
    pattern = r'<((?:\w+:)?)c\b((?=[^>]*\sr="%s")[^>]*?)(?:/>|>.*?</\1c>)' % cell
    match = _find(re.compile(pattern, re.S), xml)
    p, attrs = match.group(1), re.sub(r'\st="[^"]*"', "", match.group(2))
    # An explicit inline string is always text, so "=" or "+" is never a formula.
    new = f'<{p}c{attrs} t="inlineStr"><{p}is><{p}t xml:space="preserve">{escape(text)}</{p}t></{p}is></{p}c>'
    xml = xml[: match.start()] + new + xml[match.end() :]
    display = r'(<(?:\w+:)?hyperlink\b(?=[^>]*\sref="%s")[^>]*?\sdisplay=")[^"]*' % cell
    xml = re.sub(display, lambda m: m.group(1) + _esc(text), xml)
    parts[part] = xml.encode("utf-8")


def _table_header(parts, record, src):
    part, key, ref = _target(record["target"])
    row = record["value"]["headerRow"]
    xml = parts[part].decode("utf-8")
    if key == "tableId":
        # Existing table with its header disabled: only headerRowCount changes.
        match = _find(r"<(?:\w+:)?table\b[^>]*>", xml)
        ref = _attr(match.group(0), "ref")
        tag = re.sub(r'\sheaderRowCount="0"', ' headerRowCount="1"', match.group(0))
        xml = xml[: match.start()] + tag + xml[match.end() :]
    if type(row) is not int or row != range_boundaries(ref)[1]:
        raise RemediationError("INVALID_CORRECTION", "Only the first row of the range can be the header.")
    if key == "tableId":
        parts[part] = xml.encode("utf-8")
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

    rels_path = posixpath.join(posixpath.dirname(sheet_part), "_rels", posixpath.basename(sheet_part) + ".rels")
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
    new, old = _string(record["value"]["name"], 31), record["worksheet"]
    if (
        new != new.strip()
        or re.search(r"[:\\/?*\[\]\x00-\x1f]", new)
        or new[0] == "'"
        or new[-1] == "'"
        or new.casefold() == "history"
        or GENERIC_NAME.fullmatch(new)
    ):
        raise RemediationError("INVALID_CORRECTION", f"{new!r} is not a valid descriptive sheet name.")
    sheet_names = r'<(?:\w+:)?sheet\b[^>]*\sname="([^"]*)"'
    with zipfile.ZipFile(src) as archive:
        source_names = {html.unescape(n).casefold() for n in re.findall(sheet_names, archive.read("xl/workbook.xml").decode("utf-8"))}
    workbook = parts["xl/workbook.xml"].decode("utf-8")
    if new.casefold() in source_names:
        raise RemediationError("INVALID_CORRECTION", f"A sheet named {new!r} already exists.")
    if new.casefold() in {html.unescape(n).casefold() for n in re.findall(sheet_names, workbook)}:
        raise RemediationError("CONFLICTING_CORRECTIONS", f"{new!r} is used by another rename.")

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
        if re.fullmatch(r"xl/(?:workbook|(?:worksheets|charts|tables)/[^/]+)\.xml", name):
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
    if not isinstance(value, str) or not value.strip() or len(value) > limit or BAD_XML.search(value):
        raise RemediationError("INVALID_CORRECTION", f"Enter nonblank text of at most {limit} characters.")
    return value


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
