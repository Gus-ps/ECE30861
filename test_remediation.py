"""Tests for remediation.py. Run with: python -m unittest test_remediation"""

import hashlib
import os
import tempfile
import unittest
import zipfile
from unittest import mock

from openpyxl import Workbook, load_workbook
from openpyxl.chart import BarChart, Reference
from openpyxl.workbook.defined_name import DefinedName
from openpyxl.worksheet.hyperlink import Hyperlink
from openpyxl.worksheet.table import Table, TableColumn

import remediation
from accessibility_checker.runner import check_workbook
from remediation import RemediationError, remediate, review, validate_decisions


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
        sheet = fixable["WORKSHEET_NAME"]["findingId"]
        cases = [
            ("MISSING_VALUE", [{"findingId": link, "action": "APPLY"}]),
            ("UNSUPPORTED_CORRECTION", [{"findingId": manual["findingId"], "action": "APPLY", "value": {}}]),
            ("DUPLICATE_DECISION", [{"findingId": link, "action": "DECLINE"}] * 2),
            ("FINDING_NOT_FOUND", [{"findingId": "x", "action": "DECLINE"}]),
            ("INVALID_CORRECTION", [{"findingId": link, "action": "APPLY", "value": {"text": "click here"}}]),
            ("INVALID_REQUEST", [{"findingId": link, "action": "DECLINE", "value": {"text": "x"}}]),
            ("INVALID_REQUEST", [{"findingId": link, "action": "DECLINE", "note": "x"}]),
            ("INVALID_REQUEST", []),
            ("CONFLICTING_CORRECTIONS", [{"findingId": sheet, "action": "APPLY", "value": {"name": "Budget"}}]),
            ("INVALID_CORRECTION", [{"findingId": sheet, "action": "APPLY", "value": {"name": "Sheet2"}}]),
            ("UNSUPPORTED_CORRECTION", [{"findingId": sheet, "action": "APPLY", "value": {"name": "SHEET2"}}]),
            ("INVALID_CORRECTION", [{"findingId": sheet, "action": "APPLY", "value": {"name": "Sheet7"}}]),
        ]
        for code, decisions in cases:
            for function in (validate_decisions, lambda s, d: remediate(s, self.dst, d)):
                with self.subTest(code=code, decisions=decisions), self.assertRaises(RemediationError) as error:
                    function(self.src, decisions)
                self.assertEqual(error.exception.code, code)
                self.assertFalse(os.path.exists(self.dst))
        self.assertEqual(os.listdir(self.dir.name), ["seeded.xlsx"])

    def test_validate_decisions_writes_nothing(self):
        decisions = [{"findingId": f["findingId"], "action": "DECLINE"} for f in self.fixable()]
        records = validate_decisions(self.src, list(reversed(decisions)))
        order = [f["findingId"] for f in review(self.src)["findings"]]
        self.assertEqual([r["findingId"] for r in records], [i for i in order if i in {d["findingId"] for d in decisions}])
        self.assertTrue(all(r["value"] is None for r in records))
        self.assertEqual(os.listdir(self.dir.name), ["seeded.xlsx"])

    def test_stored_findings_skip_the_source_audit(self):
        findings = check_workbook(self.src)
        decision = {"findingId": findings[0]["findingId"], "action": "DECLINE"}
        with mock.patch("remediation.check_workbook", side_effect=AssertionError("re-audited")):
            self.assertEqual(len(validate_decisions(self.src, [decision], findings=findings)), 1)

    def test_first_error_in_input_order_is_reported(self):
        link = next(f for f in self.fixable() if f["ruleId"] == "LINK_TEXT")["findingId"]
        bad_value = {"findingId": link, "action": "APPLY", "value": {"text": "here"}}
        unknown = {"findingId": "x", "action": "DECLINE"}
        for decisions, code in (([bad_value, unknown], "INVALID_CORRECTION"),
                                ([unknown, bad_value], "FINDING_NOT_FOUND")):
            with self.subTest(code), self.assertRaises(RemediationError) as error:
                validate_decisions(self.src, decisions)
            self.assertEqual(error.exception.code, code)

    def test_value_size_limit(self):
        sheet = next(f for f in self.fixable() if f["ruleId"] == "WORKSHEET_NAME")["findingId"]
        with self.assertRaises(RemediationError) as error:
            validate_decisions(self.src, [{"findingId": sheet, "action": "APPLY", "value": {"name": "x" * 9000}}])
        self.assertEqual(error.exception.code, "INVALID_CORRECTION")
        self.assertIn("8,192", str(error.exception))

    def test_renames_must_not_collide(self):
        path = os.path.join(self.dir.name, "two.xlsx")
        book = Workbook()
        book.active.title = "Sheet2"
        book.create_sheet("Sheet3")
        book.save(path)
        ids = [f["findingId"] for f in review(path)["findings"] if f["ruleId"] == "WORKSHEET_NAME"]
        decisions = [{"findingId": i, "action": "APPLY", "value": {"name": "Summary"}} for i in ids]
        with self.assertRaises(RemediationError) as error:
            validate_decisions(path, decisions)
        self.assertEqual(error.exception.code, "CONFLICTING_CORRECTIONS")

    def test_decline_only_batch_copies_the_workbook(self):
        finding = review(self.src)["findings"][0]
        report = remediate(self.src, self.dst, [{"findingId": finding["findingId"], "action": "DECLINE"}])
        self.assertEqual(sha256(self.src), sha256(self.dst))
        self.assertEqual(report["approvedChanges"], [])
        self.assertEqual(len(report["unresolvedFindings"]), len(review(self.src)["findings"]))

    def test_link_text_keeps_carriage_return(self):
        link = next(f for f in self.fixable() if f["ruleId"] == "LINK_TEXT")
        text = "Annual\r\nreport"
        remediate(self.src, self.dst, [{"findingId": link["findingId"], "action": "APPLY", "value": {"text": text}}])
        self.assertEqual(load_workbook(self.dst)["Sheet2"]["E5"].value, text)

    def test_unexplained_changes_fail_preservation(self):
        fixable = {f["ruleId"]: f for f in self.fixable()}
        alt = {"findingId": fixable["ALT_TEXT"]["findingId"], "action": "APPLY",
               "value": {"title": "Scores", "description": "Bar chart of scores."}}
        rename = {"findingId": fixable["WORKSHEET_NAME"]["findingId"], "action": "APPLY",
                  "value": {"name": "Totals"}}

        def tamper(rule, part, old, new):
            editor = remediation.EDITORS[rule]

            def edit(parts, record, src):
                editor(parts, record, src)
                self.assertIn(old, parts[part])
                parts[part] = parts[part].replace(old, new, 1)
            return {rule: edit}

        cases = {
            "renamed drawing object": (alt, tamper("ALT_TEXT", "xl/drawings/drawing1.xml", b' name="', b' name="X')),
            "rewritten string literal": (rename, tamper("WORKSHEET_NAME", "xl/worksheets/sheet1.xml",
                                                        b'"Sheet2!A1"', b"\"'Totals'!A1\"")),
            "stale defined name": (rename, tamper("WORKSHEET_NAME", "xl/workbook.xml",
                                                  b"'Totals'!$A$1", b"Sheet2!$A$1")),
        }
        for label, (decision, editors) in cases.items():
            with self.subTest(label), mock.patch.dict(remediation.EDITORS, editors):
                with self.assertRaises(RemediationError) as error:
                    remediate(self.src, self.dst, [decision])
                self.assertEqual(error.exception.code, "PRESERVATION_FAILED")
                self.assertEqual(os.listdir(self.dir.name), ["seeded.xlsx"])

    def test_output_audit_failure_writes_nothing(self):
        link = next(f for f in self.fixable() if f["ruleId"] == "LINK_TEXT")
        decision = {"findingId": link["findingId"], "action": "APPLY", "value": {"text": "Annual report"}}
        with mock.patch("remediation.check_workbook", side_effect=[check_workbook(self.src), RuntimeError("boom")]):
            with self.assertRaises(RemediationError) as error:
                remediate(self.src, self.dst, [decision])
        self.assertEqual(error.exception.code, "OUTPUT_AUDIT_FAILED")
        self.assertEqual(os.listdir(self.dir.name), ["seeded.xlsx"])


if __name__ == "__main__":
    unittest.main()
