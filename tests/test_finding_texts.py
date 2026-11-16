"""REQ: shared finding-text contract (§3/§7); AC-05 prose bounds, stability and limitations; partial WCAG checks.

1.1.1 Non-text Content; 1.3.1 Info and Relationships; 1.4.1 Use of Color;
1.4.3 Contrast (Minimum); 2.4.2 Page Titled (related 2.4.6 Headings and Labels);
2.4.4 Link Purpose (In Context). Human accuracy review remains outstanding.
"""

import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

from accessibility_checker.runner import check_workbook
from scripts.export_finding_texts import export, fixture_paths


class FindingTextTests(unittest.TestCase):
    def assert_text_contract(self, findings):
        for finding in findings:
            for key in ("message", "recommendation"):
                text = finding[key]
                self.assertIsInstance(text, str)
                self.assertTrue(text.strip(), (finding, key))
                self.assertLessEqual(len(text), 500, (finding, key))
                self.assertGreaterEqual(len(text), 1)
        self.assertEqual(findings.limitations, sorted(set(findings.limitations)))

    def test_fixture_bounds_stability_and_limitations(self):
        for path in fixture_paths():
            with self.subTest(path=path.name):
                first = check_workbook(path)
                second = check_workbook(path)
                self.assert_text_contract(first)
                self.assert_text_contract(second)
                self.assertEqual(
                    [(f["ruleId"], f["worksheet"], f["target"],
                      f["message"], f["recommendation"]) for f in first],
                    [(f["ruleId"], f["worksheet"], f["target"],
                      f["message"], f["recommendation"]) for f in second],
                )
                self.assertEqual(first.limitations, second.limitations)

    def test_export_is_deterministic_and_deduplicated(self):
        first = export()
        self.assertEqual(first, export())
        keys = [(r["ruleId"], r["classification"], r["messageTemplate"],
                 r["recommendation"]) for r in first["findings"]]
        self.assertEqual(keys, sorted(set(keys)))

    def test_unbounded_cell_text_and_maximum_sheet_name_do_not_enter_prose(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "long.xlsx"
            book = Workbook()
            sheet = book.active
            sheet.title = "S" * 31
            sheet["A1"] = "LONG_TEXT_SENTINEL"
            sheet["A1"].font = Font(color="FFFFFF", size=11)
            sheet["A1"].fill = PatternFill("solid", fgColor="FFFFFF")
            sheet["B1"] = "click here"
            sheet["B1"].hyperlink = "https://example.com/" + "z" * 1000
            book.save(path)
            book.close()
            # Raw OOXML avoids openpyxl's cell-text truncation.
            with ZipFile(path) as archive:
                parts = {name: archive.read(name) for name in archive.namelist()}
            parts["xl/worksheets/sheet1.xml"] = parts["xl/worksheets/sheet1.xml"].replace(
                b"LONG_TEXT_SENTINEL", ("長" * 100000).encode()
            )
            with ZipFile(path, "w") as archive:
                for name, content in parts.items():
                    archive.writestr(name, content)
            findings = check_workbook(path)
            self.assert_text_contract(findings)
            self.assertIn("COLOR_CONTRAST", {f["ruleId"] for f in findings})
            self.assertIn("LINK_TEXT", {f["ruleId"] for f in findings})
            for finding in findings:
                for key in ("message", "recommendation"):
                    self.assertNotIn("長", finding[key])
