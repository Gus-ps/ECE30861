"""Prototype name-matching rule, not a team/pod-approved common specification."""

import re
from os import PathLike
from xml.etree import ElementTree as ET
from zipfile import ZipFile


def check_worksheet_names(path: str | PathLike[str]) -> list[dict[str, str]]:
    """Return original visible worksheet names and reasons in workbook order.

    Reasons are DEFAULT_LIKE or NUMERIC_REQUIRES_REVIEW. Numeric names may be
    meaningful; review their meaning rather than treating them as inappropriate.
    Assume a valid, readable .xlsx. Never save it or assess content accessibility.
    """
    with ZipFile(path, "r") as workbook:
        root = ET.fromstring(workbook.read("xl/workbook.xml"))
        relationships = ET.fromstring(workbook.read("xl/_rels/workbook.xml.rels"))

    worksheet_ids = {
        rel.attrib["Id"]
        for rel in relationships
        if rel.attrib["Type"].endswith("/worksheet")
    }
    results = []
    for sheet in root.findall("{*}sheets/{*}sheet"):
        if sheet.get("state", "visible") != "visible":
            continue
        relationship_id = next(
            value for key, value in sheet.attrib.items() if key.endswith("}id")
        )
        if relationship_id not in worksheet_ids:
            continue
        name = sheet.attrib["name"]
        normalized = "".join(name.split()).lower()
        if re.fullmatch(r"sheet[0-9]*", normalized):
            results.append({"name": name, "reason": "DEFAULT_LIKE"})
        elif re.fullmatch(r"[0-9]+", normalized):
            results.append({"name": name, "reason": "NUMERIC_REQUIRES_REVIEW"})
    return results
