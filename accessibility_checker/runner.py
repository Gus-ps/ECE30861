"""Run existing partial WCAG 2.1 checks, without an overall compliance verdict.

1.1.1 Non-text Content, 1.3.1 Info and Relationships, 2.4.2 Page Titled;
related: 2.4.6 Headings and Labels (worksheet-name results).
"""

from os import PathLike

from accessibility_checker.checks.image_alt_text import check_image_alt_text
from accessibility_checker.checks.table_headers import check_table_headers
from accessibility_checker.checks.workbook_title import check_workbook_title
from accessibility_checker.checks.worksheet_names import check_worksheet_names


def check_workbook(path: str | PathLike[str]) -> list[dict[str, str]]:
    """Aggregate existing findings for a valid, readable local .xlsx.

    Each checker reads the file independently. Exceptions propagate; no partial
    result is returned on failure. Preserve existing findings and temporary IDs.
    """
    findings = []
    for checker in (
        check_worksheet_names,
        check_image_alt_text,
        check_workbook_title,
        check_table_headers,
    ):
        findings.extend(checker(path))
    return sorted(
        findings,
        key=lambda finding: (finding["ruleId"], finding["worksheet"], finding["target"]),
    )
