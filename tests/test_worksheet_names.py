"""WCAG 2.1 2.4.2 Page Titled: prototype worksheet-name tests.

Related: 2.4.6 Headings and Labels (sheet-name result reuse).
REQ-03/04 and AC-03/04 references remain; these are not full acceptance tests.
"""

import tempfile
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from accessibility_checker.checks.worksheet_names import check_worksheet_names


class WorksheetNameTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "workbook.xlsx"

    def write_metadata(self, sheets):
        """Minimal metadata plus real empty parts required by rename preflight."""
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
            for index, (_, _, kind) in enumerate(sheets, 1):
                part = ET.Element(f"{{{main}}}{kind}")
                if kind == "worksheet":
                    ET.SubElement(part, f"{{{main}}}sheetData")
                archive.writestr(f"xl/{kind}s/sheet{index}.xml", ET.tostring(part))

    def test_req04_ac04_matching_and_nonmatching_names(self):
        matches = ["Sheet1", "sheet2", "SHEET3", "Sheet01", " \u3000Sheet3\u0085"]
        excluded = [
            "Sheet0",
            "Sheet000",
            "Sheet",
            "Sheet 1",
            "123",
            "2025",
            "Sheet1 Budget",
            "Worksheet1",
            "Sheet１２",
            "ſheet1",
            "\u200bSheet1",
            "Sheet1\u200b",
        ]
        self.write_metadata([(name, None, "worksheet") for name in matches + excluded])
        findings = check_worksheet_names(self.path)
        self.assertEqual([f["worksheet"] for f in findings], sorted(matches))
        for item in findings:
            index = matches.index(item["worksheet"]) + 1
            self.assertEqual(
                item["target"], f"xl/worksheets/sheet{index}.xml#sheetId={index}"
            )

    def test_exact_unicode_whitespace_boundaries(self):
        # Independent transcription of the Section 5 code-point set.
        points = [
            *range(9, 14),
            32,
            133,
            160,
            5760,
            *range(8192, 8203),
            8232,
            8233,
            8239,
            8287,
            12288,
        ]
        from accessibility_checker.phase3_policy import UNICODE_WHITE_SPACE

        self.assertEqual(set(map(ord, UNICODE_WHITE_SPACE)), set(points))
        self.assertTrue(
            all(chr(p) not in UNICODE_WHITE_SPACE for p in (*range(28, 32), 8203))
        )
        # XML 1.0 cannot store U+000B/U+000C; check those in the policy above.
        for point in (p for p in points if p not in (11, 12)):
            with self.subTest(point=point):
                name = chr(point) + "Sheet01" + chr(point)
                self.write_metadata([(name, None, "worksheet")])
                self.assertEqual(
                    [f["worksheet"] for f in check_worksheet_names(self.path)], [name]
                )

    def test_hidden_worksheets_and_chartsheets_included(self):
        self.write_metadata(
            [
                ("Sheet1", "hidden", "worksheet"),
                ("Sheet2", "veryHidden", "worksheet"),
                ("Sheet3", None, "chartsheet"),
            ]
        )
        self.assertEqual(
            [f["worksheet"] for f in check_worksheet_names(self.path)],
            ["Sheet1", "Sheet2", "Sheet3"],
        )

    def test_req05_ac05_schema_repeatability_and_source_preservation(self):
        self.write_metadata([("Sheet1", None, "worksheet")])
        before = self.path.read_bytes()
        findings = check_worksheet_names(self.path)
        self.assertEqual(findings, check_worksheet_names(self.path))
        self.assertEqual(self.path.read_bytes(), before)
        item = findings[0]
        self.assertEqual(
            set(item),
            {
                "findingId",
                "ruleId",
                "category",
                "worksheet",
                "target",
                "classification",
                "message",
                "recommendation",
            },
        )
        self.assertTrue(
            all(isinstance(value, str) and value for value in item.values())
        )
        self.assertRegex(item["findingId"], r"\A[0-9a-f]{64}\Z")
        self.assertEqual(item["ruleId"], "WORKSHEET_NAME")
        self.assertEqual(item["category"], "WORKSHEET_NAME")
        self.assertEqual(item["classification"], "REQUIRES_USER_INPUT")


if __name__ == "__main__":
    unittest.main()
