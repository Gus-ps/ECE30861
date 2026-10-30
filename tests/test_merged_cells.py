"""1.3.1 partial merge screening; REQ-03/04/05/06, AC-03/04/05/06."""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

from openpyxl import Workbook

from accessibility_checker.checks.merged_cells import check_merged_cells

MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"


class MergedCellsTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "merges.xlsx"
        book = Workbook()
        book.active.title = "Data"
        book.create_sheet("Hidden").sheet_state = "veryHidden"
        book.save(self.path)
        book.close()

    def write_sheet(self, cells, merges, part="xl/worksheets/sheet1.xml"):
        with ZipFile(self.path) as archive:
            parts = {name: archive.read(name) for name in archive.namelist()}
        parts[part] = (
            f'<worksheet xmlns="{MAIN}"><dimension ref="A1:XFD1048576"/>'
            f"<sheetData>{cells}</sheetData><mergeCells>"
            + "".join(f'<mergeCell ref="{ref}"/>' for ref in merges)
            + "</mergeCells></worksheet>"
        ).encode()
        with ZipFile(self.path, "w") as archive:
            for name, data in parts.items():
                archive.writestr(name, data)

    def test_populated_boundary_and_independent_identity(self):
        for content, expected in [
            ("", False),
            ('<c r="A1" s="0"/>', False),
            ('<c r="A1" t="inlineStr"><is><t> \u00a0\t</t></is></c>', False),
            ('<c r="A1"><v>0</v></c>', True),
            ('<c r="A1" t="b"><v>0</v></c>', True),
            ('<c r="A1"><f>SUM(B1)</f></c>', True),
            ('<c r="A1" t="inlineStr"><is><t>Title</t></is></c>', True),
            ('<c r="A1" t="inlineStr"><is><t>\u200b</t></is></c>', True),
        ]:
            with self.subTest(content=content):
                self.write_sheet(f'<row r="1">{content}</row>', ["A1:D1", "A1:D1"])
                before = self.path.read_bytes()
                result = check_merged_cells(self.path)
                self.assertEqual(len(result), int(expected))
                if expected:
                    item = result[0]
                    self.assertEqual(item["target"], "xl/worksheets/sheet1.xml#merge=A1:D1")
                    self.assertEqual(
                        (item["ruleId"], item["category"], item["classification"]),
                        ("MERGED_CELLS", "MERGED_CELLS", "MANUAL_REVIEW"),
                    )
                    identity = [
                        hashlib.sha256(before).hexdigest(),
                        "2.0.0",
                        "MERGED_CELLS",
                        "Data",
                        item["target"],
                    ]
                    self.assertEqual(
                        item["findingId"],
                        hashlib.sha256(
                            json.dumps(identity, ensure_ascii=False, separators=(",", ":")).encode()
                        ).hexdigest(),
                    )
                self.assertEqual(result, check_merged_cells(self.path))
                self.assertEqual(self.path.read_bytes(), before)

    def test_overlaps_even_empty_and_duplicate_canonicalization(self):
        self.write_sheet("", ["a01:b02", "A1:B2", "B2:C3"])
        result = check_merged_cells(self.path)
        self.assertEqual(
            [f["target"].split("#")[1] for f in result], ["merge=A1:B2", "merge=B2:C3"]
        )
        self.assertEqual(len(result.limitations), 2)

    def test_hidden_huge_rectangle_stays_sparse(self):
        self.write_sheet(
            '<row r="1048576"><c r="XFD1048576"><v>0</v></c></row>',
            ["A1:XFD1048576"],
            "xl/worksheets/sheet2.xml",
        )
        result = check_merged_cells(self.path)
        self.assertEqual(
            [(f["worksheet"], f["target"]) for f in result],
            [("Hidden", "xl/worksheets/sheet2.xml#merge=A1:XFD1048576")],
        )

    def test_single_cell_and_invalid_range(self):
        self.write_sheet("<row><c><v>1</v></c></row>", ["A1"])
        self.assertEqual(check_merged_cells(self.path), [])
        self.write_sheet("", ["B2:A1"])
        with self.assertRaises(ValueError):
            check_merged_cells(self.path)
