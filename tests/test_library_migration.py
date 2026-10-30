"""Library compatibility for partial 1.1.1 Non-text Content, 2.4.2 Page Titled
and 1.3.1 Info and Relationships; related 2.4.6 Headings and Labels.

REQ-03/04/05/06/15, AC-03/04/05/06/18: legacy observations, deterministic
identity, source preservation and unassessed content. Not full acceptance tests.
"""

import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from defusedxml.common import DefusedXmlException
from openpyxl import load_workbook

from accessibility_checker import excel_metadata, safe_xml
from accessibility_checker.checks.image_alt_text import check_image_alt_text
from accessibility_checker.checks.legacy_table_headers import check_table_headers
from accessibility_checker.checks.workbook_title import check_workbook_title
from accessibility_checker.checks.worksheet_names import check_worksheet_names
from accessibility_checker.runner import check_workbook


FIXTURES = Path(__file__).parent / "fixtures"
MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
DOC = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
DC = "http://purl.org/dc/elements/1.1/"


def current_expected():
    """Keep the saved 1.0.0 observations; apply only authorized common changes.

    Identity is calculated independently of production ID helpers. All other
    finding fields and legacy checker expectations remain exact comparisons.
    """
    expected = json.loads((FIXTURES / "migration_complete.expected.json").read_text())
    for finding in expected["findings"]:
        identity = [expected["sha256"], "1.0.0", finding["ruleId"],
                    finding["worksheet"], finding["target"]]
        original_id = hashlib.sha256(json.dumps(
            identity, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")).hexdigest()
        if original_id != finding["findingId"]:
            raise AssertionError("Historical snapshot was changed")
        identity[1] = "2.0.0"
        finding["findingId"] = hashlib.sha256(json.dumps(
            identity, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")).hexdigest()
    expected["limitations"] = sorted(set(expected["limitations"]))
    return expected


class CompleteWorkbookTests(unittest.TestCase):
    def setUp(self):
        # Preserve this historical two-rule acceptance profile.
        for name in ("check_table_headers", "check_merged_cells"):
            mocked = patch("accessibility_checker.runner." + name, return_value=[])
            mocked.start()
            self.addCleanup(mocked.stop)

    def test_pre_migration_exact_outputs_repeatability_and_source_bytes(self):
        path = FIXTURES / "migration_complete.xlsx"
        before = path.read_bytes()
        expected = current_expected()
        self.assertEqual(hashlib.sha256(before).hexdigest(), expected["sha256"])
        for _ in range(2):
            findings = check_workbook(path)
            self.assertEqual(list(findings), expected["findings"])
            self.assertEqual(findings.limitations, expected["limitations"])
            self.assertEqual(check_workbook_title(path), expected["workbook_title"])
            self.assertEqual(check_table_headers(path), expected["table_headers"])
            self.assertEqual(path.read_bytes(), before)

    def test_complete_package_can_be_read_by_openpyxl(self):
        workbook = load_workbook(FIXTURES / "migration_complete.xlsx")
        self.addCleanup(workbook.close)
        self.assertEqual(workbook.sheetnames, ["Sheet01", "sheet2", "Sheet3"])
        self.assertEqual(workbook["sheet2"].sheet_state, "veryHidden")
        # load_workbook 3.1.5 drops chartsheet state. The checker reads the
        # original sheet definition instead of trusting that workbook object.
        with ZipFile(FIXTURES / "migration_complete.xlsx") as archive:
            root = safe_xml.fromstring(archive.read("xl/workbook.xml"))
        chart_sheet = root.find("{*}sheets")[-1]
        self.assertEqual(chart_sheet.get("state"), "hidden")
        self.assertEqual(excel_metadata.sheet_attributes(chart_sheet)["state"], "hidden")
        self.assertEqual(workbook["Sheet01"]["A2"].value, "予算")
        self.assertEqual(workbook["Sheet01"].tables["BudgetTable"].headerRowCount, 0)


class MetadataCompatibilityTests(unittest.TestCase):
    def setUp(self):
        # These assertions preserve the pre-migration two-rule profile.
        mocked = patch("accessibility_checker.runner.check_table_headers", return_value=[])
        mocked.start()
        self.addCleanup(mocked.stop)

    def test_sheet_model_keeps_original_name_ids_and_unknown_attributes(self):
        for extra in ({}, {"future": "unsupported"}):
            with self.subTest(extra=extra):
                attributes = {
                    "name": " Sheet01 ", "sheetId": "0007", "state": "veryHidden",
                    f"{{{DOC}}}id": "originalRelation", **extra,
                }
                element = ET.Element(f"{{{MAIN}}}sheet", attributes)
                self.assertEqual(excel_metadata.sheet_attributes(element), attributes)
                self.assertEqual(element.attrib, attributes)

    def test_table_lexical_counts_and_targets_are_not_normalized(self):
        for count in (None, "0", "00", "+0", " 0", "0.0", "1", "unknown"):
            with self.subTest(count=count):
                element = ET.Element(f"{{{MAIN}}}table", {
                    "id": "01", "displayName": "Table1", "ref": "a1:b2",
                })
                if count is not None:
                    element.set("headerRowCount", count)
                actual_count, target = excel_metadata.table_header(element)
                self.assertEqual(actual_count == "0", count == "0")
                self.assertEqual(target, "a1:b2")

    def test_title_first_element_and_raw_escape_semantics(self):
        for text in (None, "", "  予算  ", "_x0053_heet1", "\u200b"):
            for duplicate in (False, True):
                with self.subTest(text=text, duplicate=duplicate):
                    element = ET.Element("coreProperties")
                    ET.SubElement(element, f"{{{DC}}}title").text = text
                    if duplicate:
                        ET.SubElement(element, f"{{{DC}}}title").text = "Other"
                    self.assertEqual(excel_metadata.workbook_title(element), text)

    def test_foreign_title_namespace_cannot_supply_or_replace_core_title(self):
        for title in (None, "", "Original"):
            with self.subTest(title=title):
                element = ET.Element("coreProperties")
                if title is not None:
                    ET.SubElement(element, f"{{{DC}}}title").text = title
                ET.SubElement(element, "{urn:unsupported}title").text = "Foreign"
                self.assertEqual(excel_metadata.workbook_title(element), title)

    def test_model_rejection_uses_original_xml_not_a_clean_result(self):
        path = FIXTURES / "migration_complete.xlsx"
        expected = current_expected()
        for model in ("ChildSheet", "DocumentProperties", "Table"):
            for error in (TypeError, ValueError, OverflowError):
                with self.subTest(model=model, error=error), patch.object(
                    getattr(excel_metadata, model), "from_tree", side_effect=error
                ):
                    result = check_workbook(path)
                    self.assertEqual(list(result), expected["findings"])
                    self.assertEqual(result.limitations, expected["limitations"])
                    self.assertEqual(check_workbook_title(path), expected["workbook_title"])
                    self.assertEqual(check_table_headers(path), expected["table_headers"])

    def test_unexpected_model_failure_propagates(self):
        with patch.object(excel_metadata.ChildSheet, "from_tree", side_effect=RuntimeError):
            with self.assertRaises(RuntimeError):
                check_workbook(FIXTURES / "migration_complete.xlsx")

    def test_models_are_used_for_metadata(self):
        # An observation of real model calls, not an otherwise unused import.
        with patch.object(
            excel_metadata.ChildSheet, "from_tree",
            wraps=excel_metadata.ChildSheet.from_tree,
        ) as sheets, patch.object(
            excel_metadata.DocumentProperties, "from_tree",
            wraps=excel_metadata.DocumentProperties.from_tree,
        ) as properties, patch.object(
            excel_metadata.Table, "from_tree", wraps=excel_metadata.Table.from_tree,
        ) as tables:
            path = FIXTURES / "migration_complete.xlsx"
            check_workbook(path)
            check_workbook_title(path)
            check_table_headers(path)
            self.assertTrue(sheets.called)
            self.assertTrue(properties.called)
            self.assertTrue(tables.called)


class SafeXmlTests(unittest.TestCase):
    def test_dtd_entities_and_external_resources_are_rejected_tree_and_stream(self):
        documents = (
            '<!DOCTYPE root><root/>',
            '<!DOCTYPE root [<!ENTITY text "injected">]><root>&text;</root>',
            '<!DOCTYPE root SYSTEM "https://example.invalid/evil.dtd"><root/>',
            '<!DOCTYPE root [<!ENTITY text SYSTEM "file:///nonexistent">]><root>&text;</root>',
            '<!DOCTYPE root [<!ENTITY % e SYSTEM "https://example.invalid/e">%e;]><root/>',
        )
        for document in documents:
            for encoding in ("utf-8", "utf-16"):
                with self.subTest(document=document, encoding=encoding):
                    payload = ('<?xml version="1.0" encoding="' + encoding + '"?>'
                               + document).encode(encoding)
                    with self.assertRaises(DefusedXmlException):
                        safe_xml.fromstring(payload)
                    with self.assertRaises(DefusedXmlException):
                        list(safe_xml.iterparse(io.BytesIO(payload), ("start", "end")))

    def test_predefined_xml_escapes_are_still_allowed(self):
        payload = b'<root title="A &amp; B">&lt; &gt; &quot; &apos;</root>'
        root = safe_xml.fromstring(payload)
        self.assertEqual(root.get("title"), "A & B")
        self.assertEqual(root.text, '< > " \u0027')

    def test_each_checker_rejects_unsafe_parts_without_modifying_input(self):
        cases = (
            (check_worksheet_names, "xl/workbook.xml"),
            (check_worksheet_names, "xl/_rels/workbook.xml.rels"),
            (check_image_alt_text, "xl/worksheets/sheet1.xml"),
            (check_image_alt_text, "xl/drawings/drawing1.xml"),
            (check_workbook_title, "docProps/core.xml"),
            (check_table_headers, "xl/tables/table1.xml"),
            (check_workbook, "xl/drawings/drawing2.xml"),
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "unsafe.xlsx"
            for checker, part in cases:
                with self.subTest(checker=checker.__name__, part=part):
                    with ZipFile(FIXTURES / "migration_complete.xlsx") as source:
                        with ZipFile(path, "w") as target:
                            for entry in source.infolist():
                                data = source.read(entry)
                                if entry.filename == part:
                                    data = b'<!DOCTYPE unsafe>' + data
                                target.writestr(entry, data)
                    before = path.read_bytes()
                    with self.assertRaises(DefusedXmlException):
                        checker(path)
                    self.assertEqual(path.read_bytes(), before)

    def test_malformed_xml_and_missing_parts_still_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "broken.xlsx"
            for data, error in ((b'<workbook>', ET.ParseError), (None, KeyError)):
                with self.subTest(data=data):
                    with ZipFile(path, "w") as archive:
                        if data is not None:
                            archive.writestr("xl/workbook.xml", data)
                    with self.assertRaises(error):
                        check_workbook(path)


if __name__ == "__main__":
    unittest.main()
