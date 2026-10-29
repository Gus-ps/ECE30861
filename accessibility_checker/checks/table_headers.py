"""WCAG 2.1 1.3.1 Info and Relationships: Excel Tables without header rows only."""

import posixpath
from os import PathLike
from zipfile import ZipFile

from accessibility_checker import safe_xml as ET
from accessibility_checker.excel_metadata import sheet_attributes, table_header
from accessibility_checker.finding_ids import make_finding_id

# TODO: Replace this provisional rule ID after agreement with the other team.
_RULE_ID = "1.3.1-TABLE-NO-HEADER"
_CATEGORY = "TABLE_STRUCTURE"


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


def check_table_headers(path: str | PathLike[str]) -> list[dict[str, str]]:
    """Return one finding per visible-sheet Excel Table with headerRowCount=0.

    Assume a valid, readable .xlsx; never save it. Header names, ordinary cell
    ranges, and other structure checks are unexamined, not passed. Rule and
    finding IDs remain provisional; see accessibility_checker/finding_ids.py.
    """
    results = []
    with ZipFile(path, "r") as workbook:
        workbook_part = "xl/workbook.xml"
        root = ET.fromstring(workbook.read(workbook_part))
        sheet_relationships = _relationships(workbook, workbook_part)
        for sheet in root.findall("{*}sheets/{*}sheet"):
            attributes = sheet_attributes(sheet)
            if attributes.get("state", "visible") != "visible":
                continue
            relationship = sheet_relationships[_relationship_id(sheet)]
            if not relationship.attrib["Type"].endswith("/worksheet"):
                continue
            sheet_part = _target(workbook_part, relationship)
            sheet_root = ET.fromstring(workbook.read(sheet_part))
            table_parts = sheet_root.findall("{*}tableParts/{*}tablePart")
            if not table_parts:
                continue
            table_relationships = _relationships(workbook, sheet_part)
            for table_part in table_parts:
                relationship = table_relationships[_relationship_id(table_part)]
                table = ET.fromstring(workbook.read(_target(sheet_part, relationship)))
                header_count, target = table_header(table)
                if header_count != "0":
                    continue
                worksheet = attributes["name"]
                if target is None:
                    target = table.attrib["ref"]  # Preserve the existing KeyError.
                results.append(
                    {
                        "findingId": make_finding_id(_RULE_ID, worksheet, target),
                        "ruleId": _RULE_ID,
                        "category": _CATEGORY,
                        "worksheet": worksheet,
                        "target": target,
                        "classification": "REQUIRES_USER_INPUT",
                        "message": "Excel Table has no header row (headerRowCount=0).",
                        "recommendation": "Enable the table header row and provide meaningful column names.",
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
