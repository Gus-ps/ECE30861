"""WCAG 2.1 2.4.2 Page Titled: missing workbook Title only, not full coverage."""

import posixpath
from os import PathLike
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from finding_ids import make_finding_id

# TODO: Replace these developer-authorized placeholders after team confirmation.
# WORKBOOK_TITLE is not a confirmed category in the current HTTP contract.
_RULE_ID = "WORKBOOK_TITLE"
_CATEGORY = "WORKBOOK_TITLE"
# A real worksheet can have this name; these sentinels are not collision-proof.
_WORKBOOK_WORKSHEET = "__WORKBOOK__"
_WORKBOOK_TARGET = "__WORKBOOK__"


def check_workbook_title(path: str | PathLike[str]) -> list[dict[str, str]]:
    """Return one finding if core properties/title are absent, empty, or blank.

    Assume a valid, readable .xlsx; never save or evaluate title quality.
    Uses the existing temporary ID policy without workbook/ruleset identity.
    """
    with ZipFile(path, "r") as workbook:
        relationships = ET.fromstring(workbook.read("_rels/.rels"))
        core = next(
            (
                rel
                for rel in relationships
                if rel.attrib["Type"].endswith("/metadata/core-properties")
            ),
            None,
        )
        if core is not None:
            part = posixpath.normpath(core.attrib["Target"]).lstrip("/")
            properties = ET.fromstring(workbook.read(part))
            title = properties.find("{http://purl.org/dc/elements/1.1/}title")
            if title is not None and (title.text or "").strip():
                return []

    return [
        {
            "findingId": make_finding_id(
                _RULE_ID, _WORKBOOK_WORKSHEET, _WORKBOOK_TARGET
            ),
            "ruleId": _RULE_ID,
            "category": _CATEGORY,
            "worksheet": _WORKBOOK_WORKSHEET,
            "target": _WORKBOOK_TARGET,
            "classification": "REQUIRES_USER_INPUT",
            "message": "Workbook Title is missing, empty, or contains only whitespace.",
            "recommendation": "Provide a title that describes the workbook's topic or purpose.",
        }
    ]
