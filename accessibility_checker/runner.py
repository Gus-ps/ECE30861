"""Run the Section 5 Phase 3 subset, without an overall compliance verdict.

1.1.1 Non-text Content and 2.4.2 Page Titled;
related: 2.4.6 Headings and Labels (worksheet-name results).
"""

from os import PathLike

from accessibility_checker.checks.image_alt_text import check_image_alt_text
from accessibility_checker.checks.worksheet_names import check_worksheet_names
from accessibility_checker.finding_ids import get_source_sha256


def check_workbook(path: str | PathLike[str]) -> list[dict[str, str]]:
    """Aggregate WORKSHEET_NAME and ALT_TEXT for a valid local .xlsx.

    Compute the raw-file digest once. Exceptions propagate; no partial result
    is returned on failure. Title/Table checks are retained but not called.
    TODO: Confirm the contract's limitations transport before changing this
    list return type. Unsupported cases currently stop with NotImplementedError.
    """
    source_sha256 = get_source_sha256(path)
    findings = []
    for checker in (
        check_worksheet_names,
        check_image_alt_text,
    ):
        findings.extend(checker(path, source_sha256=source_sha256))
    return sorted(
        findings,
        key=lambda finding: (finding["ruleId"], finding["worksheet"], finding["target"]),
    )
