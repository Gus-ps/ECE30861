"""WCAG 2.1 2.4.2 Page Titled: Section 5 Phase 3 worksheet-name rule only.

Related: 2.4.6 Headings and Labels. This does not assess full criterion coverage.
Detection is retained from Phase 3; new finding identity uses ruleset 2.0.0.
Whole-workbook reference preflight classifies rename support; no editing occurs.
"""

import posixpath
import re
from os import PathLike
from zipfile import ZipFile

from accessibility_checker import safe_xml as ET
from accessibility_checker.excel_metadata import sheet_attributes
from accessibility_checker.finding_ids import get_source_sha256, make_phase4_finding_id
from accessibility_checker.phase3_policy import UNICODE_WHITE_SPACE
from accessibility_checker.rename_safety import rename_limitations
from accessibility_checker.results import Findings, finalize_findings

_RULE_ID = "WORKSHEET_NAME"


def check_worksheet_names(
    path: str | PathLike[str], *, source_sha256: str | None = None
) -> Findings:
    """Inspect all worksheet and chartsheet tabs, including hidden/veryHidden.

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
            if rel.attrib["Type"].endswith(("/worksheet", "/chartsheet"))
        }
        results = Findings()
        for sheet in root.findall("{*}sheets/{*}sheet"):
            attributes = sheet_attributes(sheet)
            relationship_id = next(
                value for key, value in attributes.items() if key.endswith("}id")
            )
            relationship = worksheets.get(relationship_id)
            if relationship is None:
                continue
            name = attributes["name"]
            match = re.fullmatch(
                r"sheet([0-9]+)",
                name.strip(UNICODE_WHITE_SPACE),
                flags=re.IGNORECASE | re.ASCII,
            )
            if match is None or not match.group(1).lstrip("0"):
                continue
            part = posixpath.normpath(
                posixpath.join("xl", relationship.attrib["Target"])
            ).lstrip("/")
            target = f"{part}#sheetId={attributes['sheetId']}"
            results.append(
                {
                    "findingId": make_phase4_finding_id(
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
        if results:
            # Preflight the whole workbook once, including other/hidden sheets.
            limitations = rename_limitations(
                workbook, root, {r.attrib["Id"]: r for r in relationships}
            )
            if limitations:
                for finding in results:
                    finding["classification"] = "MANUAL_REVIEW"
                    finding["recommendation"] = (
                        "Review workbook reference safety before renaming this worksheet."
                    )
                    results.limitations.extend(
                        f"{finding['worksheet']}: {finding['target']}: {reason}"
                        for reason in limitations
                    )
    return finalize_findings(results)
