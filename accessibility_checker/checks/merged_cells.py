"""1.3.1 Info and Relationships: populated declared merges, partial screening."""

from accessibility_checker.cell_reader import WorkbookReader
from accessibility_checker.coordinates import range_sort_key
from accessibility_checker.finding_ids import get_source_sha256, make_phase4_finding_id
from accessibility_checker.results import Findings, finalize_findings
from accessibility_checker.worksheet_features import contains, merge_ranges, overlaps


def check_merged_cells(path, *, source_sha256=None):
    """Inspect stored cells/merges without expanding rectangles or saving input."""
    source = source_sha256 if source_sha256 is not None else get_source_sha256(path)
    result = Findings()
    with WorkbookReader(path) as reader:
        for sheet in reader.sheets:
            if sheet.kind != "worksheet":
                continue
            if sheet.external:
                target = reader.workbook_part + "#xml=/"
                reason = "External worksheet merge content is not fetched."
                _review(result, source, sheet.name, target, reason, True)
                continue
            ranges = merge_ranges(reader, sheet)
            if not ranges:
                continue
            cells = [cell for cell in reader.read_cells(sheet) if cell.populated]
            for rectangle in ranges:
                top, left, bottom, right = range_sort_key(rectangle)
                conflict = any(
                    other != rectangle and overlaps(rectangle, other) for other in ranges
                )
                if conflict or (
                    (top, left) != (bottom, right)
                    and any(contains(rectangle, cell.row, cell.column) for cell in cells)
                ):
                    reason = (
                        "Overlapping merge declarations require manual review."
                        if conflict
                        else "Populated merged cells may impede navigation, including title merges."
                    )
                    _review(
                        result,
                        source,
                        sheet.name,
                        sheet.part + "#merge=" + rectangle,
                        reason,
                        conflict,
                    )
    return finalize_findings(result)


def _review(result, source, worksheet, target, reason, limitation):
    result.append(
        {
            "findingId": make_phase4_finding_id(source, "MERGED_CELLS", worksheet, target),
            "ruleId": "MERGED_CELLS",
            "category": "MERGED_CELLS",
            "worksheet": worksheet,
            "target": target,
            "classification": "MANUAL_REVIEW",
            "message": reason,
            "recommendation": "Review the merged range and its effect on navigation; no cells were changed.",
        }
    )
    if limitation:
        result.limitations.append(f"{worksheet}: {target}: {reason}")
