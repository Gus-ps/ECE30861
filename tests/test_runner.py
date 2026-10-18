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
        """Build metadata consumed by both Phase 3 checkers, not a full Excel file."""
        main = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
        doc = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
        pkg = "http://schemas.openxmlformats.org/package/2006/relationships"
        xdr = "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"
        name = "Sheet1" if issues else "Budget"
        title = "" if issues else "<dc:title>Budget</dc:title>"
        description = "" if issues else 'title="Logo" descr="Company logo"'
        count = "0" if issues else "1"
        parts = {
            "_rels/.rels": f'''<Relationships xmlns="{pkg}">
                <Relationship Id="core" Type="{pkg}/metadata/core-properties" Target="docProps/core.xml"/>
            </Relationships>''',
            "docProps/core.xml": f"""<cp:coreProperties
                xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
                xmlns:dc="http://purl.org/dc/elements/1.1/">{title}</cp:coreProperties>""",
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

    def test_phase3_runs_only_two_rules_despite_legacy_issues(self):
        self.write_metadata(issues=True)
        findings = check_workbook(self.path)
        self.assertEqual(
            [(item["ruleId"], item["worksheet"], item["target"]) for item in findings],
            [
                ("ALT_TEXT", "Sheet1", "xl/drawings/drawing90.xml#id=1"),
                ("WORKSHEET_NAME", "Sheet1", "xl/worksheets/sheet17.xml#sheetId=1"),
            ],
        )

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
                "findingId": identifier,
                "ruleId": rule,
                "category": "WORKSHEET_NAME",
                "worksheet": sheet,
                "target": target,
                "classification": "REQUIRES_USER_INPUT",
                "message": "Test finding.",
                "recommendation": "Review this test finding.",
            }

        # Rule, worksheet, and target ties each exercise a different sort key.
        a = finding("a", "Z", "A", "A")
        b = finding("b", "A", "B", "A")
        c = finding("c", "A", "A", "Z")
        d = finding("d", "A", "A", "A")
        e = finding("e", "A", "A", "B")
        calls = []

        def checker(name, results):
            def run(path, *, source_sha256):
                calls.append((name, path, source_sha256))
                return results

            return Mock(side_effect=run)

        checkers = {
            "check_worksheet_names": checker("worksheet", [a]),
            "check_image_alt_text": checker("image", [b, c, d, e]),
        }
        with (
            patch.multiple("accessibility_checker.runner", **checkers),
            patch(
                "accessibility_checker.runner.get_source_sha256", return_value="a" * 64
            ) as source_hash,
        ):
            findings = check_workbook(self.path)
        self.assertEqual(
            calls, [(name, self.path, "a" * 64) for name in ("worksheet", "image")]
        )
        self.assertEqual(findings, [d, e, c, b, a])
        source_hash.assert_called_once_with(self.path)

    def test_exception_from_any_checker_propagates_without_partial_result(self):
        names = (
            "check_worksheet_names",
            "check_image_alt_text",
        )
        for failed_index, name in enumerate(names):
            with self.subTest(checker=name):
                error = RuntimeError("Checker failed")
                checkers = {
                    key: Mock(return_value=[{"partial": "must not be returned"}])
                    for key in names
                }
                checkers[name].side_effect = error
                with (
                    patch.multiple("accessibility_checker.runner", **checkers),
                    patch(
                        "accessibility_checker.runner.get_source_sha256",
                        return_value="a" * 64,
                    ) as source_hash,
                ):
                    with self.assertRaises(RuntimeError) as raised:
                        check_workbook(self.path)
                self.assertIs(raised.exception, error)
                for index, key in enumerate(names):
                    if index <= failed_index:
                        checkers[key].assert_called_once_with(
                            self.path, source_sha256="a" * 64
                        )
                    else:
                        checkers[key].assert_not_called()

    def test_runner_preserves_limitations_alongside_sorted_findings(self):
        from accessibility_checker.results import Findings

        self.write_metadata(issues=True)
        from xml.etree import ElementTree as ET

        with ZipFile(self.path) as archive:
            parts = {name: archive.read(name) for name in archive.namelist()}
        part = "xl/drawings/drawing90.xml"
        root = ET.fromstring(parts[part])
        props = root.find(".//{*}cNvPr")
        del props.attrib["id"]
        parts[part] = ET.tostring(root)
        with ZipFile(self.path, "w") as archive:
            for name, data in parts.items():
                archive.writestr(name, data)
        before = self.path.read_bytes()
        findings = check_workbook(self.path)
        self.assertIsInstance(findings, Findings)
        self.assertIsInstance(findings, list)
        self.assertEqual(
            [f["ruleId"] for f in findings], ["ALT_TEXT", "WORKSHEET_NAME"]
        )
        self.assertEqual(findings[0]["classification"], "MANUAL_REVIEW")
        self.assertEqual(len(findings.limitations), 1)
        self.assertIn(findings[0]["target"], findings.limitations[0])
        self.assertEqual(findings, check_workbook(self.path))
        self.assertEqual(findings.limitations, check_workbook(self.path).limitations)
        self.assertEqual(self.path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
