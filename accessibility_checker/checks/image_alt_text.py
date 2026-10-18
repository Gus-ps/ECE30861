"""WCAG 2.1 1.1.1 Non-text Content: determined Section 5 Phase 3 subset.

Checks accessibility title/description, not visible captions or semantic quality.
Pending unsupported-object/#xml=/limitations rules stop processing explicitly.
"""

import posixpath
import re
from collections import Counter
from os import PathLike
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from accessibility_checker.finding_ids import get_source_sha256, make_phase3_finding_id
from accessibility_checker.phase3_policy import UNICODE_WHITE_SPACE

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
            "External object relationships require the pending review/limitations contract."
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
            "Missing/ambiguous nonvisual properties require the pending #xml= contract."
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
            "Ambiguous decorative metadata requires the pending review/limitations contract."
        )
    value = markers[0].get("val")
    if value not in ("0", "1", "false", "true"):
        raise NotImplementedError(
            "Unspecified decorative flag value requires contract confirmation."
        )
    return value in ("1", "true")


def _objects(parent: ET.Element, namespace: str):
    """Visit known anchor/group children without silently dropping other objects."""
    parent_kind = parent.tag.rsplit("}", 1)[-1]
    metadata = (
        {"nvGrpSpPr", "grpSpPr"}
        if parent_kind == "grpSp"
        else {
            "from",
            "to",
            "pos",
            "ext",
            "clientData",
        }
    )
    for child in parent:
        kind = child.tag.rsplit("}", 1)[-1]
        if child.tag != f"{{{namespace}}}{kind}":
            raise NotImplementedError(
                "Unsupported drawing namespace requires the pending review/limitations contract."
            )
        if kind in metadata:
            continue
        if kind == "grpSp":
            # TODO: Obtain the contract's group-level decorative inheritance rule.
            if _is_decorative(_properties(child, namespace)):
                raise NotImplementedError(
                    "Decorative group inheritance is not yet defined by an available contract."
                )
            yield from _objects(child, namespace)
        elif kind in ("pic", "sp", "cxnSp", "graphicFrame"):
            yield child
        else:
            raise NotImplementedError(
                f"Unsupported drawing object {kind}; review/limitations contract pending."
            )


def _check_chart_reference(workbook: ZipFile, part: str, element: ET.Element):
    data = element.findall("{*}graphic/{*}graphicData")
    if len(data) != 1 or len(data[0]) != 1 or data[0][0].tag not in _CHART_TAGS:
        raise NotImplementedError(
            "Nonstandard graphicFrame requires the pending review/limitations contract."
        )
    relationship = _relationships(workbook, part)[_relationship_id(data[0][0])]
    if not relationship.attrib["Type"].endswith("/chart"):
        raise NotImplementedError(
            "Ambiguous chart relationship requires contract confirmation."
        )
    workbook.getinfo(_target(part, relationship))


def _reject_unresolved_sheet_content(sheet: ET.Element):
    # TODO: Replace conservative failures with the contract's required review
    # findings and limitations once their exact representations are available.
    if any(
        sheet.find(f"{{*}}{kind}") is not None
        for kind in (
            "legacyDrawing",
            "legacyDrawingHF",
            "picture",
            "controls",
            "oleObjects",
        )
    ):
        raise NotImplementedError(
            "Legacy/background/control objects require the pending review/limitations contract."
        )
    if sheet.find(".//{*}c[@vm]") is not None:
        raise NotImplementedError(
            "Value-metadata/cell-image representation needs contract confirmation."
        )
    for formula in sheet.findall(".//{*}f"):
        if re.search(
            r"(?:^|[^A-Za-z0-9_])(?:_xlfn\.)?IMAGE\s*\(",
            formula.text or "",
            re.IGNORECASE | re.ASCII,
        ):
            raise NotImplementedError(
                "Potential IMAGE formula representation needs contract confirmation."
            )


def check_image_alt_text(
    path: str | PathLike[str], *, source_sha256: str | None = None
) -> list[dict[str, str]]:
    """Check supported objects on all worksheets, including hidden worksheets.

    Native decorative objects get MANUAL_REVIEW; others require title and descr.
    Group containers are traversal containers; children are assessed individually.
    Unsupported/ambiguous cases stop without returning a successful partial list.
    No review/limitations schema or #xml= path is invented.
    """
    if source_sha256 is None:
        source_sha256 = get_source_sha256(path)
    results = []
    with ZipFile(path, "r") as workbook:
        if any(
            name.startswith("xl/richData/") or name == "xl/cellimages.xml"
            for name in workbook.namelist()
        ):
            raise NotImplementedError(
                "Rich-data/cell-image metadata requires the pending review/limitations contract."
            )
        workbook_part = "xl/workbook.xml"
        root = ET.fromstring(workbook.read(workbook_part))
        sheet_relationships = _relationships(workbook, workbook_part)
        for sheet in root.findall("{*}sheets/{*}sheet"):
            relationship = sheet_relationships[_relationship_id(sheet)]
            if not relationship.attrib["Type"].endswith("/worksheet"):
                continue
            sheet_part = _target(workbook_part, relationship)
            sheet_root = ET.fromstring(workbook.read(sheet_part))
            _reject_unresolved_sheet_content(sheet_root)
            drawings = sheet_root.findall("{*}drawing")
            if not drawings:
                continue
            drawing_relationships = _relationships(workbook, sheet_part)
            for drawing in drawings:
                relationship = drawing_relationships[_relationship_id(drawing)]
                if not relationship.attrib["Type"].endswith("/drawing"):
                    raise NotImplementedError(
                        "Ambiguous drawing relationship needs contract confirmation."
                    )
                part = _target(sheet_part, relationship)
                drawing_root = ET.fromstring(workbook.read(part))
                namespace = drawing_root.tag.removesuffix("}wsDr").removeprefix("{")
                if (
                    namespace not in _DRAWING_NAMESPACES
                    or drawing_root.tag != f"{{{namespace}}}wsDr"
                ):
                    raise NotImplementedError(
                        "Unsupported drawing representation requires contract confirmation."
                    )
                if any(
                    item.tag.rsplit("}", 1)[-1] == "AlternateContent"
                    for item in drawing_root.iter()
                ):
                    raise NotImplementedError(
                        "AlternateContent selection requires the pending review/limitations contract."
                    )
                identifiers = Counter(
                    item.get("id")
                    for item in drawing_root.iter(f"{{{namespace}}}cNvPr")
                    if item.get("id") is not None
                )
                for anchor in drawing_root:
                    if anchor.tag not in {
                        f"{{{namespace}}}{kind}"
                        for kind in (
                            "oneCellAnchor",
                            "twoCellAnchor",
                            "absoluteAnchor",
                        )
                    }:
                        raise NotImplementedError(
                            "Unsupported drawing anchor requires the pending review/limitations contract."
                        )
                    for element in _objects(anchor, namespace):
                        properties = _properties(element, namespace)
                        identifier = properties.get("id")
                        if not identifier or identifiers[identifier] != 1:
                            # TODO: Use the exact indexed #xml= path from the missing contract.
                            raise NotImplementedError(
                                f"Missing/duplicate object ID in {part}; #xml= and limitations contract pending."
                            )
                        if element.tag == f"{{{namespace}}}graphicFrame":
                            _check_chart_reference(workbook, part, element)
                        if _is_decorative(properties):
                            classification = "MANUAL_REVIEW"
                            message = "Object is marked decorative; confirm that it conveys no information."
                            recommendation = "Confirm the decorative designation or provide alternative text title and description."
                        else:
                            missing = [
                                label
                                for attribute, label in (
                                    ("title", "title"),
                                    ("descr", "description (descr)"),
                                )
                                if not properties.get(attribute, "").strip(
                                    UNICODE_WHITE_SPACE
                                )
                            ]
                            if not missing:
                                continue
                            classification = "REQUIRES_USER_INPUT"
                            message = (
                                "Object is missing alternative text "
                                + " and ".join(missing)
                                + "."
                            )
                            recommendation = "Provide the missing accessibility title and/or description."
                        worksheet = sheet.attrib["name"]
                        target = f"{part}#id={identifier}"
                        results.append(
                            {
                                "findingId": make_phase3_finding_id(
                                    source_sha256, _RULE_ID, worksheet, target
                                ),
                                "ruleId": _RULE_ID,
                                "category": "NON_TEXT_CONTENT",
                                "worksheet": worksheet,
                                "target": target,
                                "classification": classification,
                                "message": message,
                                "recommendation": recommendation,
                            }
                        )
    return sorted(
        results,
        key=lambda finding: (
            finding["ruleId"],
            finding["worksheet"],
            finding["target"],
        ),
    )
