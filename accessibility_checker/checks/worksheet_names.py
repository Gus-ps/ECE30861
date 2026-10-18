"""WCAG 2.1 2.4.2 Page Titled: Section 5 Phase 3 worksheet-name rule only.

Related: 2.4.6 Headings and Labels. This does not assess full criterion coverage.
"""

import posixpath
import re
from os import PathLike
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from accessibility_checker.finding_ids import get_source_sha256, make_phase3_finding_id
from accessibility_checker.phase3_policy import UNICODE_WHITE_SPACE

_RULE_ID = "WORKSHEET_NAME"


def check_worksheet_names(
    path: str | PathLike[str], *, source_sha256: str | None = None
) -> list[dict[str, str]]:
    """Inspect all worksheets, including hidden/veryHidden, but not chartsheets.

    The optional digest is supplied by the runner to avoid repeated hashing.
    Direct callers may omit it. Never normalize or change the original name.
    """
    if source_sha256 is None:
        source_sha256 = get_source_sha256(path)
    with ZipFile(path, "r") as workbook:
        root = ET.fromstring(workbook.read("xl/workbook.xml"))
        relationships = ET.fromstring(workbook.read("xl/_rels/workbook.xml.rels"))
        worksheets = {
            rel.attrib["Id"]: rel
            for rel in relationships
            if rel.attrib["Type"].endswith("/worksheet")
        }
        results = []
        for sheet in root.findall("{*}sheets/{*}sheet"):
            relationship_id = next(
                value for key, value in sheet.attrib.items() if key.endswith("}id")
            )
            relationship = worksheets.get(relationship_id)
            if relationship is None:
                continue
            name = sheet.attrib["name"]
            match = re.fullmatch(
                r"sheet([0-9]+)",
                name.strip(UNICODE_WHITE_SPACE),
                flags=re.IGNORECASE | re.ASCII,
            )
            if match is None or not match.group(1).lstrip("0"):
                continue
            if relationship.get("TargetMode") == "External":
                raise NotImplementedError(
                    "External worksheet relationship needs contract confirmation."
                )
            part = posixpath.normpath(
                posixpath.join("xl", relationship.attrib["Target"])
            ).lstrip("/")
            target = f"{part}#sheetId={sheet.attrib['sheetId']}"
            results.append(
                {
                    "findingId": make_phase3_finding_id(
                        source_sha256, _RULE_ID, name, target
                    ),
                    "ruleId": _RULE_ID,
                    "category": "WORKSHEET_NAME",
                    "worksheet": name,
                    "target": target,
                    "classification": "REQUIRES_USER_INPUT",
                    "message": "Worksheet name is a default Sheet name with a positive numeric suffix.",
                    "recommendation": "Provide a descriptive worksheet name based on its purpose.",
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
