"""WCAG 2.1 1.3.1 Info and Relationships: missing table-header row tests.

REQ-03/04/05/06 and AC-03/04/05/06: prototype scope, not full criterion coverage.
"""

import tempfile
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from accessibility_checker.checks.legacy_table_headers import check_table_headers
from accessibility_checker.finding_ids import make_finding_id

MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
DOC = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG = "http://schemas.openxmlformats.org/package/2006/relationships"


def relationships(items):
    root = ET.Element(f"{{{PKG}}}Relationships")
    for identifier, kind, target in items:
        ET.SubElement(
            root,
            f"{{{PKG}}}Relationship",
            {
                "Id": identifier,
                "Type": f"{DOC}/{kind}",
                "Target": target,
            },
        )
    return root


class TableHeaderTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "tables.xlsx"

    def write_metadata(self, sheets):
        """Write synthetic metadata; sheets contain name, state, tables, kind.

        Tables are (ref, headerRowCount or None). Part names deliberately do not
        share workbook-order numbers. No complete Excel workbook is generated.
        """
        root = ET.Element(f"{{{MAIN}}}workbook")
        sheet_list = ET.SubElement(root, f"{{{MAIN}}}sheets")
        workbook_relationships = []
        table_number = 80
        with ZipFile(self.path, "w") as archive:
            for index, (name, state, tables, kind) in enumerate(sheets):
                sheet_file = f"sheet{17 - index}.xml"
                attributes = {
                    "name": name,
                    "sheetId": str(index + 1),
                    f"{{{DOC}}}id": f"rId{index}",
                }
                if state is not None:
                    attributes["state"] = state
                ET.SubElement(sheet_list, f"{{{MAIN}}}sheet", attributes)
                workbook_relationships.append(
                    (f"rId{index}", kind, f"worksheets/{sheet_file}")
                )
                sheet = ET.Element(f"{{{MAIN}}}worksheet")
                ET.SubElement(sheet, f"{{{MAIN}}}sheetData")
                table_parts = ET.SubElement(sheet, f"{{{MAIN}}}tableParts")
                sheet_relationships = []
                for table_index, (ref, header_count) in enumerate(tables):
                    table_number += 1
                    filename = f"table{table_number}.xml"
                    identifier = f"rId{table_index + 42}"
                    ET.SubElement(
                        table_parts,
                        f"{{{MAIN}}}tablePart",
                        {f"{{{DOC}}}id": identifier},
                    )
                    target = (
                        f"../tables/{filename}"
                        if index == 0
                        else f"/xl/tables/{filename}"
                    )
                    sheet_relationships.append((identifier, "table", target))
                    attributes = {
                        "id": str(table_number),
                        "displayName": f"Table{table_number}",
                        "ref": ref,
                    }
                    if header_count is not None:
                        attributes["headerRowCount"] = header_count
                    archive.writestr(
                        f"xl/tables/{filename}",
                        ET.tostring(ET.Element(f"{{{MAIN}}}table", attributes)),
                    )
                archive.writestr(f"xl/worksheets/{sheet_file}", ET.tostring(sheet))
                if tables:
                    archive.writestr(
                        f"xl/worksheets/_rels/{sheet_file}.rels",
                        ET.tostring(relationships(sheet_relationships)),
                    )
            archive.writestr("xl/workbook.xml", ET.tostring(root))
            archive.writestr(
                "xl/_rels/workbook.xml.rels",
                ET.tostring(relationships(workbook_relationships)),
            )

    def test_req04_ac04_explicit_missing_header_row(self):
        self.write_metadata([("Budget", None, [("B3:D12", "0")], "worksheet")])
        findings = check_table_headers(self.path)
        self.assertEqual(
            [(item["worksheet"], item["target"]) for item in findings],
            [("Budget", "B3:D12")],
        )

    def test_req04_ac04_nonzero_or_omitted_count_not_flagged(self):
        self.write_metadata(
            [("Budget", "visible", [("A1:C5", "1"), ("E1:G5", None)], "worksheet")]
        )
        self.assertEqual(check_table_headers(self.path), [])

    def test_req04_ac04_multiple_tables_sheets_relationships_and_sorting(self):
        self.write_metadata(
            [
                (
                    "Second",
                    "visible",
                    [("E2:G9", "0"), ("A1:C5", "0"), ("I1:K5", "1")],
                    "worksheet",
                ),
                ("First", None, [("B3:D6", "0")], "worksheet"),
            ]
        )
        self.assertEqual(
            [
                (item["worksheet"], item["target"])
                for item in check_table_headers(str(self.path))
            ],
            [
                ("First", "B3:D6"),
                ("Second", "A1:C5"),
                ("Second", "E2:G9"),
            ],
        )

    def test_req04_ac04_hidden_veryhidden_and_chartsheets_excluded(self):
        self.write_metadata(
            [
                ("Hidden", "hidden", [("A1:C5", "0")], "worksheet"),
                ("VeryHidden", "veryHidden", [("A1:C5", "0")], "worksheet"),
                ("Chart", "visible", [("A1:C5", "0")], "chartsheet"),
                ("Budget", "visible", [("D2:F9", "0")], "worksheet"),
            ]
        )
        self.assertEqual(
            [item["worksheet"] for item in check_table_headers(self.path)], ["Budget"]
        )

    def test_req04_ac04_no_table_parts_does_not_require_sheet_relationships(self):
        self.write_metadata([("Budget", None, [], "worksheet")])
        self.assertEqual(check_table_headers(self.path), [])

    def test_req04_ac04_unreferenced_table_part_not_examined(self):
        self.write_metadata([("Budget", None, [], "worksheet")])
        with ZipFile(self.path, "a") as archive:
            archive.writestr(
                "xl/tables/table17.xml",
                f'<table xmlns="{MAIN}" ref="A1:C5" headerRowCount="0"/>',
            )
        self.assertEqual(check_table_headers(self.path), [])

    def test_req05_ac05_finding_fields_id_and_repeatability(self):
        self.write_metadata(
            [("Budget", None, [("A1:C5", "0"), ("E1:G5", "0")], "worksheet")]
        )
        findings = check_table_headers(self.path)
        self.assertEqual(findings, check_table_headers(self.path))
        self.assertEqual(len({item["findingId"] for item in findings}), 2)
        for item in findings:
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
            self.assertTrue(all(isinstance(value, str) for value in item.values()))
            self.assertEqual(item["ruleId"], "1.3.1-TABLE-NO-HEADER")
            self.assertEqual(item["category"], "TABLE_STRUCTURE")
            self.assertEqual(item["classification"], "REQUIRES_USER_INPUT")
            self.assertEqual(
                item["findingId"],
                make_finding_id(item["ruleId"], "Budget", item["target"]),
            )
            self.assertRegex(item["findingId"], r"\A[A-Za-z0-9_-]{1,64}\Z")
            for field in ("message", "recommendation"):
                self.assertTrue(1 <= len(item[field]) <= 500)

    def test_req03_ac03_source_bytes_unchanged(self):
        self.write_metadata(
            [("Budget", None, [("A1:C5", "0"), ("E1:G5", "1")], "worksheet")]
        )
        before = self.path.read_bytes()
        check_table_headers(self.path)
        self.assertEqual(self.path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
