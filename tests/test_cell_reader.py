"""Common input for future partial 1.3.1 Info and Relationships, 2.4.4 Link
Purpose (In Context), 1.4.1 Use of Color and 1.4.3 Contrast (Minimum) checks.

REQ-03/04/15 and AC-03/04/18: sparse interpretation and source preservation,
not individual rule acceptance or six-rule coverage.
"""

import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from zipfile import ZipFile

from defusedxml.common import DefusedXmlException

from accessibility_checker.cell_reader import WorkbookReader, WorkbookReadError
from accessibility_checker.coordinates import (
    CoordinateError, canonical_range, cell_position, cell_reference, range_sort_key,
)
from accessibility_checker.phase3_policy import UNICODE_WHITE_SPACE


MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
DOC = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG = "http://schemas.openxmlformats.org/package/2006/relationships"


class CoordinateTests(unittest.TestCase):
    def test_canonical_cells_ranges_and_numeric_order(self):
        self.assertEqual(cell_reference(*cell_position("xfd1048576")), "XFD1048576")
        self.assertEqual(cell_reference(*cell_position("a01")), "A1")
        self.assertEqual(canonical_range("b2"), "B2:B2")
        self.assertEqual(canonical_range("a1:d9"), "A1:D9")
        self.assertEqual(sorted(["A10", "A2", "B2"], key=cell_position), ["A2", "B2", "A10"])
        self.assertEqual(sorted(["A10:B11", "B2:C2", "A2:A9"], key=range_sort_key),
                         ["A2:A9", "B2:C2", "A10:B11"])

    def test_invalid_and_reversed_coordinates(self):
        for reference in ("A0", "XFE1", "A1048577", "$A$1", "Sheet1!A1", "A-1", "A", " A1", "Ａ1"):
            with self.subTest(reference=reference), self.assertRaises(CoordinateError):
                cell_position(reference)
        for reference in ("D9:A1", "B1:A2", "A1:B0", "A1:B2:C3"):
            with self.subTest(reference=reference), self.assertRaises(CoordinateError):
                canonical_range(reference)

    def test_extremely_long_coordinate_digits_have_explicit_coordinate_errors(self):
        with self.assertRaises(CoordinateError):
            cell_position("A" + "9" * 5000)
        self.assertEqual(cell_position("A" + "0" * 5000 + "1"), (1, 1))


class CellReaderTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "source.xlsx"

    def write(self, rows, strings=None, *, namespace=MAIN, extra_sheets=False,
              sheet_target="../grid/data.xml", external_strings=False):
        """Nonstandard part names exercise relationships rather than filenames."""
        shared = (
            f'<Relationship Id="strings" Type="{DOC}/sharedStrings" '
            'Target="../text/strings.xml"'
            + (' TargetMode="External"' if external_strings else '') + '/>'
        ) if strings is not None else ""
        sheets = '<sheet name=" Dépenses 📊 " sheetId="007" state="hidden" r:id="grid"/>'
        extras = ""
        if extra_sheets:
            sheets += '<sheet name="Private" sheetId="8" state="veryHidden" r:id="private"/>'
            sheets += '<sheet name="Chart" sheetId="9" state="hidden" r:id="chart"/>'
            sheets += '<sheet name="External" sheetId="10" r:id="external"/>'
            extras = (
                f'<Relationship Id="private" Type="{DOC}/worksheet" Target="/grid/private.xml"/>'
                f'<Relationship Id="chart" Type="{DOC}/chartsheet" Target="/charts/actual.xml"/>'
                f'<Relationship Id="external" Type="{DOC}/worksheet" Target="https://example.invalid/sheet" TargetMode="External"/>'
            )
        parts = {
            "_rels/.rels": f'<Relationships xmlns="{PKG}"><Relationship Id="book" Type="{DOC}/officeDocument" Target="meta/book.xml"/></Relationships>',
            "meta/book.xml": f'<workbook xmlns="{namespace}" xmlns:r="{DOC}"><sheets>{sheets}</sheets></workbook>',
            "meta/_rels/book.xml.rels": f'<Relationships xmlns="{PKG}"><Relationship Id="grid" Type="{DOC}/worksheet" Target="{sheet_target}"/>{shared}{extras}</Relationships>',
            "grid/data.xml": f'<worksheet xmlns="{namespace}"><dimension ref="A1:XFD1048576"/><sheetData>{rows}</sheetData></worksheet>',
            "grid/private.xml": f'<worksheet xmlns="{namespace}"><sheetData><row><c t="b"><v>0</v></c></row></sheetData></worksheet>',
            "charts/actual.xml": f'<chartsheet xmlns="{namespace}"/>',
        }
        if strings is not None:
            parts["text/strings.xml"] = f'<sst xmlns="{namespace}">{strings}</sst>'
        with ZipFile(self.path, "w") as archive:
            for part, data in parts.items():
                archive.writestr(part, data)

    def read(self):
        with WorkbookReader(self.path) as reader:
            return reader.read_cells(reader.sheets[0])

    def test_omitted_coordinates_follow_previous_stored_row_and_column(self):
        self.write('<row><c><v>0</v></c><c r="C1"><v>3</v></c><c/></row>'
                   '<row r="10"><c r="b10"/><c/></row><row><c/></row>')
        before = self.path.read_bytes()
        cells = self.read()
        self.assertEqual([c.reference for c in cells], ["A1", "C1", "D1", "B10", "C10", "A11"])
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(cells, self.read())

    def test_numeric_order_does_not_expand_declared_used_range(self):
        self.write('<row r="10"><c r="XFD10"/><c r="A10"/></row>'
                   '<row r="2"><c r="B2"/><c r="A2"/></row>')
        self.assertEqual([c.reference for c in self.read()], ["A2", "B2", "A10", "XFD10"])

    def test_coordinate_errors_are_not_corrected_or_overwritten(self):
        cases = (
            '<row r="0"><c/></row>', '<row r="1048577"/>', '<row r="-1"/>',
            '<row r="1"><c r="A2"/></row>', '<row><c r="XFE1"/></row>',
            '<row><c r="$A$1"/></row>', '<row><c r="A1"/><c r="a01"/></row>',
            '<row r="2"/><row r="2"/>',
            '<row r="1048576"/><row/>', '<row><c r="XFD1"/><c/></row>',
            '<c r="A1"/>', '<row><row><c/></row></row>',
            '<row r="' + '9' * 5000 + '"/>',
        )
        for rows in cases:
            with self.subTest(rows=rows):
                self.write(rows)
                with self.assertRaises(CoordinateError):
                    self.read()

    def test_shared_inline_rich_text_document_order_and_phonetic_exclusion(self):
        self.write(
            '<row><c t="s"><v>0</v></c><c t="inlineStr"><is>'
            '<r><t xml:space="preserve"> é </t></r><t>tail</t>'
            '<rPh sb="0" eb="1"><t>PHONETIC</t></rPh><r><t>📊</t></r></is></c></row>',
            '<si><r><t>First</t></r><t xml:space="preserve"> second </t>'
            '<rPh sb="0" eb="1"><t>ふりがな</t></rPh><r><t>last</t></r></si>',
        )
        first, second = self.read()
        self.assertEqual(first.value, "First second last")
        self.assertEqual(first.raw_value, "0")
        self.assertEqual(first.data_type, "s")
        self.assertEqual(second.value, " é tail📊")
        self.assertNotEqual(second.value, " é tail📊")

    def test_formula_presence_metadata_and_saved_cache_are_separate(self):
        self.write('<row>'
                   '<c><f>1+1</f><v>2</v></c>'
                   '<c><f t="shared" si="3"/></c>'
                   '<c t="str"><f>" text "</f><v xml:space="preserve"> text </v></c>'
                   '<c><f>1/0</f><v/></c>'
                   '<c t="e"><f>1/0</f><v>#DIV/0!</v></c>'
                   '<c t="s"><f t="shared" si="3"/></c>'
                   '</row>')
        numeric, shared, string, empty, error, no_index = self.read()
        self.assertEqual(numeric.formula.text, "1+1")
        self.assertEqual(numeric.cached_value, Decimal(2))
        self.assertTrue(numeric.has_cached_value)
        self.assertTrue(shared.has_formula)
        self.assertFalse(shared.has_cached_value)
        self.assertIsNone(shared.formula.text)
        self.assertEqual(shared.formula.attributes, {"t": "shared", "si": "3"})
        self.assertEqual(string.cached_value, " text ")
        self.assertEqual(empty.raw_value, "")
        self.assertTrue(empty.has_cached_value)
        self.assertIsNone(empty.cached_value)
        self.assertEqual(error.data_type, "e")
        self.assertEqual(error.cached_value, "#DIV/0!")
        self.assertTrue(no_index.has_formula)
        self.assertFalse(no_index.has_cached_value)
        self.assertIsNone(no_index.cached_value)
        self.assertTrue(all(cell.populated and cell.intake_nonempty for cell in self.read()))

    def test_zero_false_precision_and_formatting_only_cells(self):
        self.write('<row><c><v>0</v></c><c t="b"><v>0</v></c>'
                   '<c><v>12345678901234567890.0123456789</v></c><c s="7"/>'
                   '<c t="e"><v>#N/A</v></c></row>')
        zero, false, exact, style, error = self.read()
        self.assertEqual(zero.value, Decimal(0))
        self.assertIs(false.value, False)
        self.assertEqual(exact.value, Decimal("12345678901234567890.0123456789"))
        self.assertEqual(exact.raw_value, "12345678901234567890.0123456789")
        self.assertEqual(style.style_id, "7")
        self.assertFalse(style.intake_nonempty)
        self.assertFalse(style.populated)
        self.assertTrue(all(c.intake_nonempty and c.populated for c in (zero, false, exact, error)))

    def test_intake_vs_populated_strings_and_exact_whitespace_set(self):
        # XML 1.0 excludes some policy controls. Exercise those through CellData
        # below instead of creating invalid XML or changing the parser.
        self.write('<row><c t="s"><v>0</v></c><c t="s"><v>1</v></c>'
                   '<c t="inlineStr"><is><t> &#9;&#10;&#13; 　</t></is></c>'
                   '<c t="inlineStr"><is><t>​</t></is></c>'
                   '<c t="inlineStr"><is><t/></is></c></row>',
                   '<si><t/></si><si><t> </t></si>')
        empty_shared, space_shared, space_inline, zwsp, empty_inline = self.read()
        for c in (empty_shared, space_shared, space_inline):
            self.assertTrue(c.intake_nonempty)
            self.assertFalse(c.populated)
        self.assertTrue(zwsp.populated)
        self.assertFalse(empty_inline.intake_nonempty)
        self.assertFalse(empty_inline.populated)
        from dataclasses import replace
        for whitespace in UNICODE_WHITE_SPACE:
            self.assertFalse(replace(space_inline, value=whitespace).populated)
        for excluded in "\u200b\u001c\u001d\u001e\u001f":
            self.assertTrue(replace(space_inline, value=excluded).populated)

    def test_actual_relationship_parts_hidden_tabs_and_chart_distinction(self):
        self.write('<row><c><v>1</v></c></row>', extra_sheets=True)
        with WorkbookReader(self.path) as reader:
            self.assertEqual(reader.workbook_part, "meta/book.xml")
            grid, private, chart, external = reader.sheets
            self.assertEqual(grid.name, " Dépenses 📊 ")
            self.assertEqual(grid.sheet_id, "007")
            self.assertEqual(grid.part, "grid/data.xml")
            self.assertEqual(grid.state, "hidden")
            self.assertEqual(private.state, "veryHidden")
            self.assertEqual(chart.kind, "chartsheet")
            self.assertEqual(chart.part, "charts/actual.xml")
            self.assertEqual(len(reader.read_cells(grid)), 1)
            self.assertIs(reader.read_cells(private)[0].value, False)
            self.assertTrue(external.external)
            self.assertIsNone(external.part)
            for sheet in (chart, external):
                with self.assertRaises(WorkbookReadError):
                    reader.read_cells(sheet)

    def test_strict_namespace_cells_and_relationship_targets(self):
        self.write('<row><c t="s"><v>0</v></c></row>', '<si><r><t>Strict</t></r></si>',
                   namespace="http://purl.oclc.org/ooxml/spreadsheetml/main")
        self.assertEqual(self.read()[0].value, "Strict")

    def test_bad_values_or_shared_string_references_raise(self):
        for cell, strings in (
            ('<c t="s"><v>0</v></c>', None),
            ('<c t="s"><v>9</v></c>', '<si><t>x</t></si>'),
            ('<c t="s"><v>-1</v></c>', '<si><t>x</t></si>'),
            ('<c t="b"><v>unknown</v></c>', None),
            ('<c><v>NaN</v></c>', None), ('<c><v>abc</v></c>', None),
            ('<c t="unsupported"><v>1</v></c>', None),
            ('<c><v>1</v><v>2</v></c>', None),
        ):
            with self.subTest(cell=cell):
                self.write(f'<row>{cell}</row>', strings)
                with self.assertRaises(WorkbookReadError):
                    self.read()

    def test_external_shared_strings_or_escaping_paths_are_never_fetched(self):
        self.write('<row><c t="s"><v>0</v></c></row>', '<si><t>x</t></si>', external_strings=True)
        with self.assertRaises(WorkbookReadError):
            self.read()
        for target in ("../../outside.xml", "https://example.invalid/x", "../%2e%2e/outside.xml"):
            with self.subTest(target=target):
                self.write('', sheet_target=target)
                with self.assertRaises(WorkbookReadError):
                    self.read()

    def test_unsupported_string_wrapper_is_not_an_empty_populated_result(self):
        self.write('<row><c t="inlineStr"><is><wrapper><t>text</t></wrapper></is></c></row>')
        with self.assertRaisesRegex(WorkbookReadError, "Unsupported string"):
            self.read()

    def test_reader_on_complete_package_and_original_bytes(self):
        path = Path(__file__).parent / 'fixtures' / 'migration_complete.xlsx'
        before = path.read_bytes()
        with WorkbookReader(path) as reader:
            cells = reader.read_cells(reader.sheets[0])
            self.assertEqual(next(c.value for c in cells if c.reference == "A2"), "予算")
            formula = next(c for c in cells if c.reference == "D2")
            self.assertTrue(formula.has_formula)
            self.assertTrue(formula.populated)
            self.assertEqual(reader.sheets[2].state, "hidden")
        self.assertEqual(path.read_bytes(), before)
        with self.assertRaises(WorkbookReadError):
            reader.read_cells(reader.sheets[0])

    def test_shared_string_unsafe_xml_failure_is_not_cached_as_success(self):
        self.write('<row><c t="s"><v>0</v></c></row>', '<si><t>x</t></si>')
        with ZipFile(self.path) as archive:
            parts = {p: archive.read(p) for p in archive.namelist()}
        parts['text/strings.xml'] = b'<!DOCTYPE sst>' + parts['text/strings.xml']
        with ZipFile(self.path, "w") as archive:
            for part, data in parts.items():
                archive.writestr(part, data)
        with WorkbookReader(self.path) as reader:
            for _ in range(2):
                with self.assertRaises(DefusedXmlException):
                    reader.read_cells(reader.sheets[0])


if __name__ == '__main__':
    unittest.main()
