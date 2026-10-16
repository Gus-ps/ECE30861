"""WCAG 2.1 2.4.2 Page Titled: prototype worksheet-name heuristics only.

Related: 2.4.6 Headings and Labels reuses sheet-name results in the mapping guide.
Does not assess either full criterion; not a team/pod-approved common rule.
"""

import re
from os import PathLike
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from finding_ids import make_finding_id

# TODO: Replace this temporary rule ID with the approved shared catalog ID.
_RULE_ID = "WORKSHEET_NAME"


def check_worksheet_names(path: str | PathLike[str]) -> list[dict[str, str]]:
    """Return findings for visible worksheet names, sorted by rule/sheet/target.

    Numeric names may be meaningful; request review rather than declaring them
    inappropriate. Rule and finding IDs are temporary (see finding_ids.py).
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
            message = "Worksheet name resembles a default name."
        elif re.fullmatch(r"[0-9]+", normalized):
            message = "Worksheet name contains only digits; confirm whether it is descriptive."
        else:
            continue
        results.append(
            {
                "findingId": make_finding_id(_RULE_ID, name, name),
                "ruleId": _RULE_ID,
                "category": "WORKSHEET_NAME",
                "worksheet": name,
                "target": name,
                "classification": "REQUIRES_USER_INPUT",
                "message": message,
                "recommendation": "Confirm the worksheet's meaning and provide a descriptive name if needed.",
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
