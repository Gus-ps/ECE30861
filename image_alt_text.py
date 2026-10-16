"""WCAG 2.1 1.1.1 Non-text Content: missing descriptions on inserted pictures.

Prototype presence check only; does not assess the full criterion or alt quality.
"""

import posixpath
from os import PathLike
from xml.etree import ElementTree as ET
from zipfile import ZipFile

_DECORATIVE = "{http://schemas.microsoft.com/office/drawing/2017/decorative}decorative"


def _relationship_id(element: ET.Element) -> str:
    return next(value for key, value in element.attrib.items() if key.endswith("}id"))


def _relationships(workbook: ZipFile, part: str) -> dict[str, ET.Element]:
    directory, filename = posixpath.split(part)
    root = ET.fromstring(workbook.read(f"{directory}/_rels/{filename}.rels"))
    return {rel.attrib["Id"]: rel for rel in root}


def _target(part: str, relationship: ET.Element) -> str:
    return posixpath.normpath(
        posixpath.join(posixpath.dirname(part), relationship.attrib["Target"])
    ).lstrip("/")


def check_image_alt_text(path: str | PathLike[str]) -> list[dict[str, str]]:
    """Return missing descriptions with worksheet, drawing, image ID/name, reason.

    Assume a valid, readable .xlsx. Read only directly anchored DrawingML pictures
    on visible worksheets. Explicit decorative=true pictures are exempt; titles
    and names do not replace descriptions. Image bytes are not decoded, so this
    check does not depend on the embedded image's encoding.

    Grouped/compatibility-wrapped pictures and other representations are not
    assessed. Empty results do not mean unsupported content or a workbook passed.
    """
    results = []
    with ZipFile(path, "r") as workbook:
        workbook_part = "xl/workbook.xml"
        root = ET.fromstring(workbook.read(workbook_part))
        sheet_relationships = _relationships(workbook, workbook_part)
        for sheet in root.findall("{*}sheets/{*}sheet"):
            if sheet.get("state", "visible") != "visible":
                continue
            relationship = sheet_relationships[_relationship_id(sheet)]
            if not relationship.attrib["Type"].endswith("/worksheet"):
                continue
            sheet_part = _target(workbook_part, relationship)
            sheet_root = ET.fromstring(workbook.read(sheet_part))
            drawings = sheet_root.findall("{*}drawing")
            if not drawings:
                continue
            drawing_relationships = _relationships(workbook, sheet_part)
            for drawing in drawings:
                relationship = drawing_relationships[_relationship_id(drawing)]
                drawing_part = _target(sheet_part, relationship)
                drawing_root = ET.fromstring(workbook.read(drawing_part))
                for anchor in drawing_root:
                    if anchor.tag.rsplit("}", 1)[-1] not in (
                        "oneCellAnchor",
                        "twoCellAnchor",
                        "absoluteAnchor",
                    ):
                        continue
                    for picture in anchor.findall("{*}pic"):
                        properties = picture.find("{*}nvPicPr/{*}cNvPr")
                        decorative = properties.find(
                            f"{{*}}extLst/{{*}}ext/{_DECORATIVE}"
                        )
                        if decorative is not None and decorative.get("val") in (
                            "1",
                            "true",
                        ):
                            continue
                        description = properties.get("descr")
                        if description is None:
                            reason = "MISSING_DESCRIPTION"
                        elif description == "":
                            reason = "EMPTY_DESCRIPTION"
                        elif not description.strip():
                            reason = "WHITESPACE_DESCRIPTION"
                        else:
                            continue
                        results.append(
                            {
                                "worksheet": sheet.attrib["name"],
                                "drawing": drawing_part,
                                "image_id": properties.attrib["id"],
                                "image_name": properties.attrib["name"],
                                "reason": reason,
                            }
                        )
    return results
