"""Runner tests for partial WCAG 1.1.1, 1.3.1, 2.4.2 (related: 2.4.6) checks.

REQ-03/04/05/13 and AC-03/04/05/13: aggregation, locations, and failure behavior.
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from zipfile import ZipFile

from accessibility_checker.runner import check_workbook


class RunnerTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "workbook.xlsx"

    def write_metadata(self, *, issues):
        """Build metadata consumed by all four checkers, not a full Excel file."""
        main = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
        doc = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
        pkg = "http://schemas.openxmlformats.org/package/2006/relationships"
        xdr = "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"
        name = "Sheet1" if issues else "Budget"
        title = "" if issues else "<dc:title>Budget</dc:title>"
        description = "" if issues else 'descr="Company logo"'
        count = "0" if issues else "1"
        parts = {
            "_rels/.rels": f'''<Relationships xmlns="{pkg}">
                <Relationship Id="core" Type="{pkg}/metadata/core-properties" Target="docProps/core.xml"/>
            </Relationships>''',
            "docProps/core.xml": f'''<cp:coreProperties
                xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
                xmlns:dc="http://purl.org/dc/elements/1.1/">{title}</cp:coreProperties>''',
            "xl/workbook.xml": f'''<workbook xmlns="{main}" xmlns:r="{doc}">
                <sheets><sheet name="{name}" sheetId="1" r:id="sheet"/></sheets>
            </workbook>''',
            "xl/_rels/workbook.xml.rels": f'''<Relationships xmlns="{pkg}">
                <Relationship Id="sheet" Type="{doc}/worksheet" Target="worksheets/sheet17.xml"/>
            </Relationships>''',
            "xl/worksheets/sheet17.xml": f'''<worksheet xmlns="{main}" xmlns:r="{doc}">
                <sheetData/><drawing r:id="drawing"/>
                <tableParts count="1"><tablePart r:id="table"/></tableParts>
            </worksheet>''',
            "xl/worksheets/_rels/sheet17.xml.rels": f'''<Relationships xmlns="{pkg}">
                <Relationship Id="drawing" Type="{doc}/drawing" Target="../drawings/drawing90.xml"/>
                <Relationship Id="table" Type="{doc}/table" Target="../tables/table81.xml"/>
            </Relationships>''',
            "xl/drawings/drawing90.xml": f'''<xdr:wsDr xmlns:xdr="{xdr}">
                <xdr:twoCellAnchor><xdr:pic><xdr:nvPicPr>
                <xdr:cNvPr id="1" name="Picture 1" {description}/>
                </xdr:nvPicPr></xdr:pic></xdr:twoCellAnchor>
            </xdr:wsDr>''',
            "xl/tables/table81.xml": f'''<table xmlns="{main}" id="81"
                displayName="Table81" ref="B3:D12" headerRowCount="{count}"/>''',
        }
        with ZipFile(self.path, "w") as archive:
            for part, xml in parts.items():
                archive.writestr(part, xml)

    def test_real_checkers_aggregate_four_findings(self):
        self.write_metadata(issues=True)
        findings = check_workbook(self.path)
        self.assertEqual([
            (item["ruleId"], item["worksheet"], item["target"]) for item in findings
        ], [
            ("1.3.1-TABLE-NO-HEADER", "Sheet1", "B3:D12"),
            ("ALT_TEXT", "Sheet1", "xl/drawings/drawing90.xml#id=1"),
            ("WORKBOOK_TITLE", "__WORKBOOK__", "__WORKBOOK__"),
            ("WORKSHEET_NAME", "Sheet1", "Sheet1"),
        ])

    def test_all_checkers_without_findings_return_empty(self):
        self.write_metadata(issues=False)
        self.assertEqual(check_workbook(str(self.path)), [])

    def test_req03_ac03_source_bytes_unchanged(self):
        for issues in (True, False):
            with self.subTest(issues=issues):
                self.write_metadata(issues=issues)
                before = self.path.read_bytes()
                check_workbook(self.path)
                self.assertEqual(self.path.read_bytes(), before)

    def test_explicit_call_order_global_sort_and_unchanged_findings(self):
        def finding(identifier, rule, sheet, target):
            return {
                "findingId": identifier, "ruleId": rule, "category": "WORKSHEET_NAME",
                "worksheet": sheet, "target": target, "classification": "REQUIRES_USER_INPUT",
                "message": "Test finding.", "recommendation": "Review this test finding.",
            }

        # Rule, worksheet, and target ties each exercise a different sort key.
        a = finding("a", "Z", "A", "A")
        b = finding("b", "A", "B", "A")
        c = finding("c", "A", "A", "Z")
        d = finding("d", "A", "A", "A")
        e = finding("e", "A", "A", "B")
        calls = []

        def checker(name, results):
            def run(path):
                calls.append((name, path))
                return results
            return Mock(side_effect=run)

        checkers = {
            "check_worksheet_names": checker("worksheet", [a]),
            "check_image_alt_text": checker("image", [b, c]),
            "check_workbook_title": checker("title", [d]),
            "check_table_headers": checker("table", [e]),
        }
        with patch.multiple("accessibility_checker.runner", **checkers):
            findings = check_workbook(self.path)
        self.assertEqual(calls, [(name, self.path) for name in ("worksheet", "image", "title", "table")])
        self.assertEqual(findings, [d, e, c, b, a])

    def test_exception_from_any_checker_propagates_without_partial_result(self):
        names = (
            "check_worksheet_names", "check_image_alt_text",
            "check_workbook_title", "check_table_headers",
        )
        for failed_index, name in enumerate(names):
            with self.subTest(checker=name):
                error = RuntimeError("Checker failed")
                checkers = {key: Mock(return_value=[{"partial": "must not be returned"}]) for key in names}
                checkers[name].side_effect = error
                with patch.multiple("accessibility_checker.runner", **checkers):
                    with self.assertRaises(RuntimeError) as raised:
                        check_workbook(self.path)
                self.assertIs(raised.exception, error)
                for index, key in enumerate(names):
                    if index <= failed_index:
                        checkers[key].assert_called_once_with(self.path)
                    else:
                        checkers[key].assert_not_called()


if __name__ == "__main__":
    unittest.main()
