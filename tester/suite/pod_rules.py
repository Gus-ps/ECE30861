"""Independent oracle for the two Phase 3 pod rules, ALT_TEXT and WORKSHEET_NAME
(ref/phase3.md, "Audit policy and deterministic identity").

Used to cross-check hand-authored fixture expectations, never to derive them
from a system under test. Policy choices that await pod confirmation come
from the pod profile.
"""

import io
import posixpath
import re
import xml.etree.ElementTree as ET
import zipfile

from .identity import sort_key, trim

REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
OBJECTS = {"pic", "sp", "graphicFrame", "grpSp", "cxnSp"}
DECORATIVE = "{http://schemas.microsoft.com/office/drawing/2017/decorative}decorative"


def _local(tag):
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _rels(package, part):
    path = posixpath.join(posixpath.dirname(part), "_rels", posixpath.basename(part) + ".rels")
    if path not in package.namelist():
        return {}
    out = {}
    for rel in ET.fromstring(package.read(path)).iter(f"{{{PKG_REL}}}Relationship"):
        if rel.get("TargetMode") == "External":
            continue
        target = rel.get("Target", "")
        target = target[1:] if target.startswith("/") else posixpath.normpath(
            posixpath.join(posixpath.dirname(part), target))
        out[rel.get("Id")] = (rel.get("Type", "").rsplit("/", 1)[-1], target)
    return out


def _xml_path(root, element):
    ##  /local[1]/local[n]/... with 1-based indices among same-named siblings.
    parents = {child: parent for parent in root.iter() for child in parent}
    steps = []
    node = element
    while node is not None:
        parent = parents.get(node)
        siblings = [s for s in parent if _local(s.tag) == _local(node.tag)] if parent is not None else [node]
        steps.append(f"{_local(node.tag)}[{siblings.index(node) + 1}]")
        node = parent
    return "/" + "/".join(reversed(steps))


def worksheet_name_finding(name, part, sheet_id, profile):
    policy = profile.worksheet_name
    trimmed = trim(name)
    if not re.fullmatch(policy.pattern, trimmed):
        return None
    suffix = re.search(r"[0-9]+$", trimmed)
    if policy.suffix_must_exceed_zero and (suffix is None or int(suffix.group()) == 0):
        return None
    return {"ruleId": "WORKSHEET_NAME", "category": "WORKSHEET_NAME", "worksheet": name,
            "target": f"{part}#sheetId={sheet_id}", "classification": "REQUIRES_USER_INPUT"}


def _alt_text_findings(package, drawing_part, worksheet, profile, limitations):
    root = ET.fromstring(package.read(drawing_part))
    if any(_local(el.tag) == "AlternateContent" for el in root.iter()):
        limitations.append(f"{drawing_part}: mc:AlternateContent objects are not interpreted.")
    objects = []
    for element in root.iter():
        if _local(element.tag) not in OBJECTS:
            continue
        props = next((p for nv in element if _local(nv.tag).startswith("nv")
                      for p in nv if _local(p.tag) == "cNvPr"), None)
        if props is not None:
            objects.append(props)
    ids = [p.get("id") for p in objects]
    findings = []
    for props in objects:
        object_id = props.get("id")
        if not object_id or ids.count(object_id) > 1:
            target = f"{drawing_part}#xml={_xml_path(root, props)}"
            limitations.append(f"{target}: object id is missing or duplicated; an XML path identifies it.")
        else:
            target = f"{drawing_part}#id={object_id}"
        decorative = [el.get("val") for el in props.iter(DECORATIVE)]
        if decorative:
            if any(v not in ("1", "true", "0", "false") for v in decorative):
                limitations.append(f"{target}: decorative flag has an invalid value.")
                classification = "MANUAL_REVIEW"
            elif any(v in ("1", "true") for v in decorative):
                classification = profile.alt_text.decorative_classification
            else:
                classification = None
            if classification:
                findings.append(_alt_finding(worksheet, target, classification))
                continue
        missing_title = profile.alt_text.require_title and not trim(props.get("title"))
        missing_descr = profile.alt_text.require_description and not trim(props.get("descr"))
        if missing_title or missing_descr:
            findings.append(_alt_finding(worksheet, target, "REQUIRES_USER_INPUT"))
    return findings


def _alt_finding(worksheet, target, classification):
    return {"ruleId": "ALT_TEXT", "category": "NON_TEXT_CONTENT", "worksheet": worksheet,
            "target": target, "classification": classification}


def evaluate(data, profile):
    ##  Returns (findings sorted in contract order, limitations).
    package = zipfile.ZipFile(io.BytesIO(data))
    workbook_part = next(t for kind, t in _rels(package, "").values() if kind == "officeDocument")
    workbook_rels = _rels(package, workbook_part)
    findings, limitations = [], []
    for sheet in ET.fromstring(package.read(workbook_part)).iter():
        if _local(sheet.tag) != "sheet":
            continue
        name, sheet_id = sheet.get("name"), sheet.get("sheetId")
        part = workbook_rels[sheet.get(f"{{{REL}}}id")][1]
        finding = worksheet_name_finding(name, part, sheet_id, profile)
        if finding:
            findings.append(finding)
        for kind, target in _rels(package, part).values():
            if kind == "drawing":
                findings += _alt_text_findings(package, target, name, profile, limitations)
            elif kind == "vmlDrawing":
                limitations.append(f"{target}: legacy VML objects are not interpreted.")
    return sorted(findings, key=sort_key), limitations
