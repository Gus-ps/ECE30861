"""WCAG 2.1 2.4.2 Page Titled: missing-title prototype tests.

Related: REQ-03/05/06/15 and AC-03/05/06/18; not full criterion coverage.
"""

import tempfile
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from accessibility_checker.finding_ids import make_finding_id
from accessibility_checker.checks.workbook_title import check_workbook_title


class WorkbookTitleTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "workbook.xlsx"

    def write_metadata(self, title=None, *, core=True, part="docProps/core.xml"):
        """Write only package relationships and core metadata used by the check."""
        pkg = "http://schemas.openxmlformats.org/package/2006/relationships"
        properties = ET.Element(
            "{http://schemas.openxmlformats.org/package/2006/metadata/core-properties}coreProperties"
        )
        if title is not None:
            ET.SubElement(properties, "{http://purl.org/dc/elements/1.1/}title").text = title
        relationships = ET.Element(f"{{{pkg}}}Relationships")
        if core:
            ET.SubElement(relationships, f"{{{pkg}}}Relationship", {
                "Id": "rId2", "Type": f"{pkg}/metadata/core-properties", "Target": part,
            })
        with ZipFile(self.path, "w") as archive:
            archive.writestr("_rels/.rels", ET.tostring(relationships))
            if core:
                archive.writestr(part.lstrip("/"), ET.tostring(properties))

    def test_missing_title_element(self):
        self.write_metadata()
        self.assertEqual(len(check_workbook_title(self.path)), 1)

    def test_empty_title(self):
        self.write_metadata("")
        self.assertEqual(len(check_workbook_title(self.path)), 1)

    def test_whitespace_only_title(self):
        self.write_metadata(" \t\n\u00a0\u3000")
        self.assertEqual(len(check_workbook_title(self.path)), 1)

    def test_nonblank_titles_are_not_evaluated_for_quality(self):
        for title in ("Budget", "  予算  ", "Book1", "workbook.xlsx", "0"):
            with self.subTest(title=title):
                self.write_metadata(title)
                self.assertEqual(check_workbook_title(str(self.path)), [])

    def test_core_properties_absent(self):
        self.write_metadata(core=False)
        self.assertEqual(len(check_workbook_title(self.path)), 1)

    def test_core_properties_relationship_determines_part_location(self):
        for part in ("metadata/title.xml", "/metadata/title.xml"):
            with self.subTest(part=part):
                self.write_metadata("Budget", part=part)
                self.assertEqual(check_workbook_title(self.path), [])

    def test_req05_ac05_finding_shape_and_temporary_values(self):
        self.write_metadata()
        finding, = check_workbook_title(self.path)
        self.assertEqual(set(finding), {
            "findingId", "ruleId", "category", "worksheet", "target",
            "classification", "message", "recommendation",
        })
        self.assertTrue(all(isinstance(value, str) for value in finding.values()))
        self.assertEqual(finding["ruleId"], "WORKBOOK_TITLE")
        self.assertEqual(finding["category"], "WORKBOOK_TITLE")
        self.assertEqual(finding["worksheet"], "__WORKBOOK__")
        self.assertEqual(finding["target"], "__WORKBOOK__")
        self.assertEqual(finding["classification"], "REQUIRES_USER_INPUT")
        self.assertEqual(finding["findingId"], make_finding_id(
            "WORKBOOK_TITLE", "__WORKBOOK__", "__WORKBOOK__",
        ))
        self.assertRegex(finding["findingId"], r"\A[A-Za-z0-9_-]{1,64}\Z")
        for field in ("message", "recommendation"):
            self.assertTrue(1 <= len(finding[field]) <= 500)
        self.assertEqual([finding], check_workbook_title(self.path))

    def test_req03_ac03_source_bytes_unchanged(self):
        for title, core in ((None, True), ("Budget", True), (None, False)):
            with self.subTest(title=title, core=core):
                self.write_metadata(title, core=core)
                before = self.path.read_bytes()
                check_workbook_title(self.path)
                self.assertEqual(self.path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
