"""Prototype tests related to REQ-03/04 and AC-03/04, not full acceptance tests."""

import tempfile
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from worksheet_names import check_worksheet_names


class WorksheetNameTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "workbook.xlsx"

    def write_metadata(self, sheets):
        """Create only the OOXML metadata parts read by this check."""
        main = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
        doc = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
        pkg = "http://schemas.openxmlformats.org/package/2006/relationships"
        workbook = ET.Element(f"{{{main}}}workbook")
        sheet_list = ET.SubElement(workbook, f"{{{main}}}sheets")
        relationships = ET.Element(f"{{{pkg}}}Relationships")
        for index, (name, state, kind) in enumerate(sheets, 1):
            attributes = {
                "name": name,
                "sheetId": str(index),
                f"{{{doc}}}id": f"rId{index}",
            }
            if state is not None:
                attributes["state"] = state
            ET.SubElement(sheet_list, f"{{{main}}}sheet", attributes)
            ET.SubElement(
                relationships,
                f"{{{pkg}}}Relationship",
                {
                    "Id": f"rId{index}",
                    "Type": f"{doc}/{kind}",
                    "Target": f"{kind}s/sheet{index}.xml",
                },
            )
        with ZipFile(self.path, "w") as archive:
            archive.writestr("xl/workbook.xml", ET.tostring(workbook))
            archive.writestr("xl/_rels/workbook.xml.rels", ET.tostring(relationships))

    def test_req04_ac04_matching_names_in_mixed_workbook(self):
        names = [
            "Sheet123",
            "Budget",
            "2025",
            "Sheet",
            "Sheet1 Budget",
            "sheet2",
            "Sheet1",
        ]
        self.write_metadata([(name, "visible", "worksheet") for name in names])
        self.assertEqual(
            check_worksheet_names(self.path),
            [
                {"name": "Sheet123", "reason": "DEFAULT_LIKE"},
                {"name": "2025", "reason": "NUMERIC_REQUIRES_REVIEW"},
                {"name": "Sheet", "reason": "DEFAULT_LIKE"},
                {"name": "sheet2", "reason": "DEFAULT_LIKE"},
                {"name": "Sheet1", "reason": "DEFAULT_LIKE"},
            ],
        )

    def test_req04_ac04_default_name_variants_preserve_original_names(self):
        for name in (
            "Sheet",
            "Sheet1",
            "sheet1",
            "SHEET1",
            "Sheet 1",
            " Sheet1 ",
            "S h e e t 001",
            "She\tet\n1",
            "Sheet\u00a01",
            "Sheet\u30001",
        ):
            with self.subTest(name=name):
                self.write_metadata([(name, "visible", "worksheet")])
                self.assertEqual(
                    check_worksheet_names(self.path),
                    [{"name": name, "reason": "DEFAULT_LIKE"}],
                )

    def test_req04_req06_ac04_ac06_numeric_names_require_review(self):
        names = ["1", "123", "2025", " 2 0\t2\n6 "]
        self.write_metadata([(name, "visible", "worksheet") for name in names])
        self.assertEqual(
            check_worksheet_names(self.path),
            [{"name": name, "reason": "NUMERIC_REQUIRES_REVIEW"} for name in names],
        )

    def test_req04_ac04_nonmatching_names_return_empty_list(self):
        names = [
            "Budget",
            "Sheet1 Budget",
            "Worksheet1",
            "Sheet１２",
            "Sheet١",
            "１２３",
            "١٢٣",
            "2025 Budget",
            "1.23",
            "-123",
            "Sheet1x",
            "Sheet_1",
        ]
        self.write_metadata([(name, "visible", "worksheet") for name in names])
        self.assertEqual(check_worksheet_names(self.path), [])

    def test_req04_ac04_hidden_sheets_and_chartsheets_excluded(self):
        self.write_metadata(
            [
                ("Sheet", None, "worksheet"),
                ("Sheet1", "hidden", "worksheet"),
                ("Sheet123", "veryHidden", "worksheet"),
                ("2025", "hidden", "worksheet"),
                ("123", "veryHidden", "worksheet"),
                ("Sheet2", "visible", "chartsheet"),
                ("Sheet001", "visible", "worksheet"),
            ]
        )
        self.assertEqual(
            check_worksheet_names(str(self.path)),
            [
                {"name": "Sheet", "reason": "DEFAULT_LIKE"},
                {"name": "Sheet001", "reason": "DEFAULT_LIKE"},
            ],
        )

    def test_req03_ac03_original_bytes_unchanged(self):
        self.write_metadata(
            [
                (" Sheet 1 ", "visible", "worksheet"),
                ("2025", "visible", "worksheet"),
            ]
        )
        before = self.path.read_bytes()
        check_worksheet_names(self.path)
        self.assertEqual(self.path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
