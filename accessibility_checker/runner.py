"""Run only implemented checks using Phase 4 common aggregation.

1.1.1 Non-text Content and 2.4.2 Page Titled;
related: 2.4.6 Headings and Labels (worksheet-name results).
"""

from os import PathLike

from accessibility_checker.checks.image_alt_text import check_image_alt_text
from accessibility_checker.checks.merged_cells import check_merged_cells
from accessibility_checker.checks.table_headers import check_table_headers
from accessibility_checker.checks.worksheet_names import check_worksheet_names
from accessibility_checker.finding_ids import get_source_sha256
from accessibility_checker.results import Findings, finalize_findings

# Ordering contract, not a claim that all six checks are implemented.
RULE_ORDER = (
    "ALT_TEXT",
    "WORKSHEET_NAME",
    "TABLE_HEADER",
    "MERGED_CELLS",
    "LINK_TEXT",
    "COLOR_CONTRAST",
)


def check_workbook(path: str | PathLike[str]) -> Findings:
    """Aggregate ALT_TEXT and WORKSHEET_NAME for a valid local .xlsx.

    Compute the digest once. Unsupported objects produce manual-review findings;
    genuine execution failures propagate without a successful partial result.
    Title/Table checks are retained but not called.
    """
    source_sha256 = get_source_sha256(path)
    findings = Findings()
    implemented = {
        "ALT_TEXT": check_image_alt_text,
        "WORKSHEET_NAME": check_worksheet_names,
        "TABLE_HEADER": check_table_headers,
        "MERGED_CELLS": check_merged_cells,
    }
    for rule_id in RULE_ORDER:
        if rule_id not in implemented:
            continue
        checker = implemented[rule_id]
        result = checker(path, source_sha256=source_sha256)
        findings.extend(result)
        findings.limitations.extend(getattr(result, "limitations", []))
    return finalize_findings(findings)
