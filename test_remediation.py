"""Tests for remediation.py. Run with: python -m unittest test_remediation"""

import hashlib
import os
import tempfile
import unittest
import zipfile

from openpyxl import Workbook, load_workbook
from openpyxl.chart import BarChart, Reference
from openpyxl.workbook.defined_name import DefinedName
from openpyxl.worksheet.hyperlink import Hyperlink
from openpyxl.worksheet.table import Table, TableColumn

from remediation import RemediationError, remediate, review


def build(path):
    """A workbook with one fixable finding per supported rule, based on Haruki's fixtures."""
    book = Workbook()
    data = book.active
    data.title = "Data"
    data.append(["Name", "Score"])
    data.append(["Ada", 9])
    data.add_table(Table(displayName="Scores", ref="A1:B2", headerRowCount=0,
                         tableColumns=[TableColumn(id=1, name="Name"), TableColumn(id=2, name="Score")]))
    data["D1"] = "=Sheet2!A1&\"Sheet2!A1\""
    data["D2"] = "Go"
    data["D2"].hyperlink = Hyperlink(ref="D2", location="Sheet2!A1", display="Go")
    data["F1"] = "Title"
    data.merge_cells("F1:G1")
    for row, values in enumerate((["Month", "Visits"], ["May", 4], ["June", 5]), 1):
        data.cell(row, 9, values[0]), data.cell(row, 10, values[1])
    objects = book.create_sheet("Sheet2")
    objects["A1"] = "Totals"
    chart = BarChart()
    chart.add_data(Reference(data, min_col=2, min_row=2, max_row=2))
    objects.add_chart(chart, "G1")
    objects["E5"] = "click here"
    objects["E5"].hyperlink = "https://example.invalid/report"
    budget = book.create_sheet("Budget")
    for row in (["Item", "Cost"], ["Paper", 3], ["Ink", 4]):
        budget.append(row)
    book.defined_names["Total"] = DefinedName("Total", attr_text="Sheet2!$A$1")
    book.save(path)


def sha256(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


class RemediationTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.src = os.path.join(self.dir.name, "seeded.xlsx")
        self.dst = os.path.join(self.dir.name, "out.xlsx")
        build(self.src)

    def fixable(self):
        return [f for f in review(self.src)["findings"] if f["input"] is not None]

    def test_review_lists_locations_and_inputs(self):
        rules = sorted(f["ruleId"] for f in self.fixable())
        self.assertEqual(rules, ["ALT_TEXT", "LINK_TEXT"] + ["TABLE_HEADER"] * 3 + ["WORKSHEET_NAME"])
        self.assertTrue(all(f["location"].startswith("sheet '") for f in review(self.src)["findings"]))

    def test_apply_all_supported_corrections(self):
        values = {"ALT_TEXT": {"title": "Scores", "description": "Bar chart of Ada's score."},
                  "LINK_TEXT": {"text": "Annual report & summary"},
                  "WORKSHEET_NAME": {"name": "Ada's Totals"}}
        decisions = [{"findingId": f["findingId"], "action": "APPLY",
                      "value": values.get(f["ruleId"], f["input"])} for f in self.fixable()]
        before = sha256(self.src)
        report = remediate(self.src, self.dst, decisions)

        self.assertEqual(before, sha256(self.src))
        self.assertEqual(report["outputSha256"], sha256(self.dst))
        self.assertEqual(len(report["approvedChanges"]), 6)
        self.assertFalse([f for f in report["unresolvedFindings"] if f["classification"] != "MANUAL_REVIEW"])
        book = load_workbook(self.dst)
        self.assertEqual(book.sheetnames, ["Data", "Ada's Totals", "Budget"])
        self.assertEqual(book["Data"]["D1"].value, "='Ada''s Totals'!A1&\"Sheet2!A1\"")
        self.assertEqual(book["Data"]["D2"].hyperlink.location, "'Ada''s Totals'!A1")
        self.assertEqual(book.defined_names["Total"].attr_text, "'Ada''s Totals'!$A$1")
        self.assertEqual(book["Ada's Totals"]["E5"].value, "Annual report & summary")
        self.assertEqual(book["Budget"].tables["A11yTable2"].ref, "A1:B3")
        self.assertEqual(sorted(book["Data"].tables), ["A11yTable3", "Scores"])
        with zipfile.ZipFile(self.src) as a, zipfile.ZipFile(self.dst) as b:
            changed = {n for n in a.namelist() if a.read(n) != b.read(n)}
            added = set(b.namelist()) - set(a.namelist())
        self.assertEqual(changed, {"[Content_Types].xml", "xl/workbook.xml", "xl/drawings/drawing1.xml",
                                   "xl/tables/table1.xml", "xl/worksheets/sheet1.xml",
                                   "xl/worksheets/sheet2.xml", "xl/worksheets/sheet3.xml",
                                   "xl/worksheets/_rels/sheet1.xml.rels"})
        self.assertEqual(added, {"xl/tables/table2.xml", "xl/tables/table3.xml",
                                 "xl/worksheets/_rels/sheet3.xml.rels"})

    def test_rejected_batches_write_nothing(self):
        fixable = {f["ruleId"]: f for f in self.fixable()}
        manual = next(f for f in review(self.src)["findings"] if f["input"] is None)
        link = fixable["LINK_TEXT"]["findingId"]
        cases = {
            "MISSING_VALUE": [{"findingId": link, "action": "APPLY"}],
            "UNSUPPORTED_CORRECTION": [{"findingId": manual["findingId"], "action": "APPLY", "value": {}}],
            "DUPLICATE_DECISION": [{"findingId": link, "action": "DECLINE"}] * 2,
            "FINDING_NOT_FOUND": [{"findingId": "x", "action": "DECLINE"}],
            "INVALID_CORRECTION": [{"findingId": link, "action": "APPLY", "value": {"text": "click here"}}],
        }
        cases["INVALID_REQUEST"] = [{"findingId": link, "action": "DECLINE", "value": {"text": "x"}}]
        sheet = fixable["WORKSHEET_NAME"]["findingId"]
        cases["INVALID_CORRECTION "] = [{"findingId": sheet, "action": "APPLY", "value": {"name": "Budget"}}]
        for code, decisions in cases.items():
            with self.subTest(code), self.assertRaises(RemediationError) as error:
                remediate(self.src, self.dst, decisions)
            self.assertEqual(error.exception.code, code.strip())
            self.assertFalse(os.path.exists(self.dst))
        self.assertEqual(os.listdir(self.dir.name), ["seeded.xlsx"])


if __name__ == "__main__":
    unittest.main()
