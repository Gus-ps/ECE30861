"""WCAG 2.1 1.1.1 Non-text Content: determined Section 5 Phase 3 subset.

Checks accessibility title/description, not visible captions or semantic quality.
Unsupported or ambiguous representations produce manual-review findings.
"""

import posixpath
import re
from collections import Counter
from os import PathLike
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from accessibility_checker.finding_ids import get_source_sha256, make_phase3_finding_id
from accessibility_checker.phase3_policy import UNICODE_WHITE_SPACE
from accessibility_checker.results import Findings

_RULE_ID = "ALT_TEXT"
_DECORATIVE = "{http://schemas.microsoft.com/office/drawing/2017/decorative}decorative"
_DRAWING_NAMESPACES = {
    "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing",
    "http://purl.oclc.org/ooxml/drawingml/spreadsheetDrawing",
}
_CHART_TAGS = {
    "{http://schemas.openxmlformats.org/drawingml/2006/chart}chart",
    "{http://purl.oclc.org/ooxml/drawingml/chart}chart",
}
_PROPERTIES = {
    "pic": "nvPicPr",
    "sp": "nvSpPr",
    "cxnSp": "nvCxnSpPr",
    "graphicFrame": "nvGraphicFramePr",
    "grpSp": "nvGrpSpPr",
}


def _relationship_id(element: ET.Element) -> str:
    return next(value for key, value in element.attrib.items() if key.endswith("}id"))


def _relationships(workbook: ZipFile, part: str) -> dict[str, ET.Element]:
    directory, filename = posixpath.split(part)
    root = ET.fromstring(workbook.read(f"{directory}/_rels/{filename}.rels"))
    return {rel.attrib["Id"]: rel for rel in root}


def _target(part: str, relationship: ET.Element) -> str:
    if relationship.get("TargetMode") == "External":
        raise NotImplementedError(
            "External object content is not fetched; manual review is required."
        )
    return posixpath.normpath(
        posixpath.join(posixpath.dirname(part), relationship.attrib["Target"])
    ).lstrip("/")


def _properties(element: ET.Element, namespace: str) -> ET.Element:
    kind = element.tag.rsplit("}", 1)[-1]
    properties = element.findall(
        f"{{{namespace}}}{_PROPERTIES[kind]}/{{{namespace}}}cNvPr"
    )
    if len(properties) != 1:
        raise NotImplementedError(
            "Missing or ambiguous nonvisual properties require manual review."
        )
    return properties[0]


def _is_decorative(properties: ET.Element) -> bool:
    markers = [
        item
        for item in properties.iter()
        if item.tag.rsplit("}", 1)[-1] == "decorative"
    ]
    if not markers:
        return False
    if len(markers) != 1 or markers[0].tag != _DECORATIVE:
        raise NotImplementedError(
            "Ambiguous decorative metadata requires manual review."
        )
    value = markers[0].get("val")
    if value not in ("0", "1", "false", "true"):
        raise NotImplementedError(
            "Unspecified decorative flag value requires manual review."
        )
    return value in ("1", "true")


def _check_chart_reference(workbook: ZipFile, part: str, element: ET.Element):
    data = element.findall("{*}graphic/{*}graphicData")
    if len(data) != 1 or len(data[0]) != 1 or data[0][0].tag not in _CHART_TAGS:
        raise NotImplementedError(
            "Nonstandard graphicFrame requires manual review."
        )
    relationship = _relationships(workbook, part)[_relationship_id(data[0][0])]
    if not relationship.attrib["Type"].endswith("/chart"):
        raise NotImplementedError(
            "Ambiguous chart relationship requires manual review."
        )
    workbook.getinfo(_target(part, relationship))


def _xml_locations(root):
    """Stable, one-based, namespace-independent paths within an XML part."""
    locations = {}

    def visit(element, location):
        locations[element] = location
        counts = Counter()
        for child in element:
            local = child.tag.rsplit("}", 1)[-1]
            counts[local] += 1
            visit(child, f"{location}/{local}[{counts[local]}]")

    visit(root, f"/{root.tag.rsplit('}', 1)[-1]}[1]")
    return locations



def _sheet_objects(stream):
    """Stream cells without retaining the grid or a path string for every cell."""
    selected = {"legacyDrawing", "legacyDrawingHF", "picture", "control", "oleObject", "drawing"}
    stack = []
    objects = []
    cell_depth = None
    for event, element in ET.iterparse(stream, events=("start", "end")):
        local = element.tag.rsplit("}", 1)[-1]
        if event == "start":
            if stack:
                counts = stack[-1][2]
                counts[local] += 1
                location = f"{stack[-1][1]}/{local}[{counts[local]}]"
            else:
                location = f"/{local}[1]"
            stack.append((element, location, Counter()))
            if local == "c":
                cell_depth = len(stack)
            continue
        location = stack[-1][1]
        keep = local in selected
        if local == "c":
            keep = element.get("vm") is not None or any(
                re.search(r"(?:^|[^A-Za-z0-9_])(?:_xlfn\.)?IMAGE\s*\(",
                          formula.text or "", re.IGNORECASE | re.ASCII)
                for formula in element.findall("{*}f"))
            cell_depth = None
        inside_cell = cell_depth is not None
        stack.pop()
        if keep:
            objects.append((element, location))
        if not inside_cell:
            if stack:
                stack[-1][0].remove(element)
            if not keep:
                element.clear()
    return objects


def check_image_alt_text(path: str | PathLike[str], *, source_sha256: str | None = None) -> Findings:
    """Return all supported-object issues and manual reviews for uncertain objects.

    Structural/read failures propagate. Unsupported representations do not discard
    other objects' findings. External relationship targets are never fetched.
    """
    source_sha256 = source_sha256 or get_source_sha256(path)
    results = Findings()
    seen = set()

    def emit(worksheet, target, classification, message, recommendation, limitation=None):
        key = (worksheet, target)
        if key in seen:
            return
        seen.add(key)
        results.append({
            "findingId": make_phase3_finding_id(source_sha256, _RULE_ID, worksheet, target),
            "ruleId": _RULE_ID, "category": "NON_TEXT_CONTENT",
            "worksheet": worksheet, "target": target,
            "classification": classification, "message": message[:500],
            "recommendation": recommendation[:500],
        })
        if limitation:
            results.limitations.append(f"{worksheet}: {target}: {limitation}")

    def review(worksheet, target, reason):
        emit(worksheet, target, "MANUAL_REVIEW",
             "Object requires manual accessibility review.",
             "Inspect the object and confirm its alternative text or decorative designation.", reason)

    with ZipFile(path, "r") as workbook:
        workbook_part = "xl/workbook.xml"
        root = ET.fromstring(workbook.read(workbook_part))
        sheet_relationships = _relationships(workbook, workbook_part)
        for name in workbook.namelist():
            if name.startswith("xl/richData/") or name == "xl/cellimages.xml":
                review("__WORKBOOK__", f"{name}#xml=/", "Cell-image/rich-data representation is not automatically assessed.")
        for sheet in root.findall("{*}sheets/{*}sheet"):
            relationship = sheet_relationships[_relationship_id(sheet)]
            if not relationship.attrib["Type"].endswith(("/worksheet", "/chartsheet")):
                continue
            worksheet = sheet.attrib["name"]
            if relationship.get("TargetMode") == "External":
                review(worksheet, f"{workbook_part}#sheetId={sheet.attrib['sheetId']}", "External sheet content is not fetched.")
                continue
            sheet_part = _target(workbook_part, relationship)
            with workbook.open(sheet_part) as stream:
                sheet_objects = _sheet_objects(stream)
            sheet_locations = dict(sheet_objects)
            sheet_rels = None

            def get_sheet_rels():
                nonlocal sheet_rels
                if sheet_rels is None:
                    sheet_rels = _relationships(workbook, sheet_part)
                return sheet_rels

            for element, _ in sheet_objects:
                kind = element.tag.rsplit("}", 1)[-1]
                if kind in ("legacyDrawing", "legacyDrawingHF", "picture", "control", "oleObject"):
                    fallback = f"{sheet_part}#xml={sheet_locations[element]}"
                    identifiers = [value for key, value in element.attrib.items() if key.endswith("}id")]
                    if kind == "picture":
                        review(worksheet, fallback, "Worksheet background picture requires manual accessibility review.")
                        continue
                    rel = get_sheet_rels().get(identifiers[0]) if identifiers else None
                    if rel is not None and rel.get("TargetMode") != "External":
                        part = _target(sheet_part, rel)
                        if part.lower().endswith(".vml"):
                            vml = ET.fromstring(workbook.read(part))
                            locations = _xml_locations(vml)
                            shapes = [item for item in vml.iter() if item.tag.rsplit("}", 1)[-1] == "shape"]
                            ids = Counter(item.get("id") for item in shapes)
                            for shape in shapes:
                                identifier = shape.get("id")
                                target = f"{part}#id={identifier}" if identifier and ids[identifier] == 1 else f"{part}#xml={locations[shape]}"
                                review(worksheet, target, "Legacy VML object requires manual review.")
                            if shapes:
                                continue
                    review(worksheet, fallback, "Legacy, background, control, embedded, or external object is not automatically assessed.")
                elif kind == "c":
                    has_image_formula = any(re.search(r"(?:^|[^A-Za-z0-9_])(?:_xlfn\.)?IMAGE\s*\(", formula.text or "", re.IGNORECASE | re.ASCII) for formula in element.findall("{*}f"))
                    if element.get("vm") is not None or has_image_formula:
                        review(worksheet, f"{sheet_part}#xml={sheet_locations[element]}", "Cell-image or IMAGE-formula representation requires manual review.")

            for drawing, _ in sheet_objects:
                if drawing.tag.rsplit("}", 1)[-1] != "drawing":
                    continue
                relationship = get_sheet_rels()[_relationship_id(drawing)]
                drawing_target = f"{sheet_part}#xml={sheet_locations[drawing]}"
                if relationship.get("TargetMode") == "External" or not relationship.attrib["Type"].endswith("/drawing"):
                    review(worksheet, drawing_target, "External or nonstandard drawing relationship is not automatically assessed.")
                    continue
                part = _target(sheet_part, relationship)
                drawing_root = ET.fromstring(workbook.read(part))
                locations = _xml_locations(drawing_root)
                namespace = drawing_root.tag.removesuffix("}wsDr").removeprefix("{")
                if namespace not in _DRAWING_NAMESPACES or drawing_root.tag != f"{{{namespace}}}wsDr":
                    review(worksheet, f"{part}#xml={locations[drawing_root]}", "Unsupported drawing namespace or representation.")
                    continue
                identifiers = Counter(item.get("id") for item in drawing_root.iter(f"{{{namespace}}}cNvPr") if item.get("id"))

                def inspect(element):
                    kind = element.tag.rsplit("}", 1)[-1]
                    fallback = f"{part}#xml={locations[element]}"
                    if element.tag != f"{{{namespace}}}{kind}" or kind not in _PROPERTIES:
                        review(worksheet, fallback, f"Unsupported drawing object: {kind}.")
                        return
                    target = fallback
                    try:
                        properties = _properties(element, namespace)
                        identifier = properties.get("id")
                        if not identifier or identifiers[identifier] != 1:
                            review(worksheet, f"{part}#xml={locations[properties]}", "Missing or duplicate drawing ID; indexed XML location used.")
                            if kind == "grpSp":
                                inspect_children(element, {"nvGrpSpPr", "grpSpPr"})
                            return
                        target = f"{part}#id={identifier}"
                        decorative = _is_decorative(properties)
                        if kind == "grpSp":
                            if decorative:
                                review(worksheet, target, "Decorative group inheritance requires manual review.")
                            inspect_children(element, {"nvGrpSpPr", "grpSpPr"})
                            return
                        if kind == "graphicFrame":
                            _check_chart_reference(workbook, part, element)
                        references = [value for item in element.iter() for key, value in item.attrib.items() if key.endswith("}link") or key.endswith("}embed")]
                        if references:
                            relationships_part = posixpath.join(posixpath.dirname(part), "_rels", posixpath.basename(part) + ".rels")
                            object_rels = _relationships(workbook, part) if relationships_part in workbook.namelist() else {}
                            if any(object_rels.get(ref) is not None and object_rels[ref].get("TargetMode") == "External" for ref in references):
                                review(worksheet, target, "External object content is not fetched.")
                                return
                    except NotImplementedError as error:
                        review(worksheet, target, str(error))
                        return
                    if decorative:
                        emit(worksheet, target, "MANUAL_REVIEW",
                             "Object is marked decorative; confirm that it conveys no information.",
                             "Confirm the decorative designation or provide alternative text title and description.")
                    else:
                        missing = [label for attribute, label in (("title", "title"), ("descr", "description (descr)")) if not properties.get(attribute, "").strip(UNICODE_WHITE_SPACE)]
                        if missing:
                            emit(worksheet, target, "REQUIRES_USER_INPUT",
                                 "Object is missing alternative text " + " and ".join(missing) + ".",
                                 "Provide the missing accessibility title and/or description.")

                def inspect_children(parent, metadata):
                    for child in parent:
                        if child.tag in {f"{{{namespace}}}{kind}" for kind in metadata}:
                            continue
                        inspect(child)

                for anchor in drawing_root:
                    if anchor.tag not in {f"{{{namespace}}}{kind}" for kind in ("oneCellAnchor", "twoCellAnchor", "absoluteAnchor")}:
                        review(worksheet, f"{part}#xml={locations[anchor]}", "Unsupported drawing anchor or alternate content requires review.")
                        continue
                    inspect_children(anchor, {"from", "to", "pos", "ext", "clientData"})
    results.sort(key=lambda finding: (finding["ruleId"], finding["worksheet"], finding["target"]))
    return results
