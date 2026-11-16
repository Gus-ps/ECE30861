"""1.3.1 Info and Relationships, partial; REQ-15 / AC-18 output preservation."""

import unittest
from unittest.mock import patch

from accessibility_checker.coordinates import CoordinateError, range_sort_key
from accessibility_checker.worksheet_features import contains
from tests import test_merged_cells


class RangeCacheTests(unittest.TestCase):
    def test_repeated_immutable_results_and_bounded_cache(self):
        range_sort_key.cache_clear()
        for reference in ("a01:b02", "A1", "A1:XFD1048576"):
            first = range_sort_key(reference)
            self.assertIs(first, range_sort_key(reference))
            self.assertIsInstance(first, tuple)
        self.assertEqual(range_sort_key.cache_info().hits, 3)
        self.assertEqual(range_sort_key.cache_info().maxsize, 4096)

    def test_invalid_inputs_are_not_cached(self):
        range_sort_key.cache_clear()
        for reference in ("", "A0", "XFE1", "B2:A1", "A1:B2:C3", "$A$1"):
            for _ in range(2):
                with self.assertRaises(CoordinateError):
                    range_sort_key(reference)
        self.assertEqual(range_sort_key.cache_info().currsize, 0)


class IndexedMergeTests(unittest.TestCase):
    setUp = test_merged_cells.MergedCellsTests.setUp
    write_sheet = test_merged_cells.MergedCellsTests.write_sheet

    def test_legacy_scan_equivalence_across_sheets(self):
        from accessibility_checker.checks.merged_cells import check_merged_cells
        from accessibility_checker.coordinates import cell_reference

        def legacy_scan(columns_by_row, rows, top, left, bottom, right):
            rectangle = f"{cell_reference(top, left)}:{cell_reference(bottom, right)}"
            return any(
                contains(rectangle, row, column)
                for row in rows for column in columns_by_row[row]
            )

        merges = ["B2:D4", "F2:H4", "J2:L4", "N2:P4", "R2:T4",
                  "B8:D9", "F8", "H8:J9", "J9:L10"]
        # Interior, top-left, bottom-right, adjacent outside, same rows outside,
        # empty, single-cell and overlapping declarations.
        self.write_sheet(
            '<row r="2"><c r="F2"><v>1</v></c><c r="Q2"><v>1</v></c></row>'
            '<row r="3"><c r="C3"><v>1</v></c><c r="U3"><v>1</v></c></row>'
            '<row r="4"><c r="L4"><v>1</v></c></row>'
            '<row r="8"><c r="F8"><v>1</v></c><c r="I8"><v>1</v></c></row>',
            merges,
        )
        self.write_sheet(
            '<row r="1048576"><c r="XFD1048576"><v>1</v></c></row>',
            ["A1:XFD1048576"], "xl/worksheets/sheet2.xml",
        )
        with patch("accessibility_checker.checks.merged_cells._has_populated_cell",
                   side_effect=legacy_scan):
            expected = check_merged_cells(self.path)
        actual = check_merged_cells(self.path)
        self.assertEqual(actual, expected)
        self.assertEqual(actual.limitations, expected.limitations)
        self.assertEqual(len(actual), 6)
