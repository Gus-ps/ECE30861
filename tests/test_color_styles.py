"""1.4.1/1.4.3 style foundation; independent examples, NOT frozen vectors.
REQ-03/04/05/06 and AC-03/04/05/06: original bytes and bounded static reading.
"""

import tempfile
import unittest
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.worksheet.table import Table, TableStyleInfo

from accessibility_checker.cell_reader import WorkbookReader
from accessibility_checker.color_styles import (
    StyleResolver,
    UnsupportedRendering,
    contrast_ratio,
    relative_luminance,
    resolve_color,
    rgb,
    tinted,
)

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


class ColorMathTests(unittest.TestCase):
    def test_rgb_argb_tint_and_half_up_examples(self):
        self.assertEqual(rgb("1234AB"), (18, 52, 171))
        self.assertEqual(rgb("001234AB"), (18, 52, 171))
        self.assertEqual(tinted((0, 0, 0), ".5"), (128, 128, 128))
        self.assertEqual(tinted((255, 255, 255), "-.5"), (128, 128, 128))
        self.assertEqual(tinted((255, 0, 0), ".5"), (255, 128, 128))
        self.assertEqual(tinted((255, 0, 0), "-.5"), (128, 0, 0))
        for t in ["-1", "0", "1"]:
            self.assertTrue(all(0 <= v <= 255 for v in tinted((13, 97, 211), t)))
        for t in ["NaN", "1.1", "-1.1"]:
            with self.assertRaises(UnsupportedRendering):
                tinted((0, 0, 0), t)

    def test_concrete_palette_theme_and_ambiguous_sources(self):
        def color(**attrs):
            return ET.Element(NS + "color", attrs)

        self.assertEqual(
            resolve_color(color(theme="0"), theme=((255, 255, 255), (0, 0, 0))), (255, 255, 255)
        )
        self.assertEqual(
            resolve_color(color(indexed="1"), palette=((0, 0, 0), (255, 0, 0))), (255, 0, 0)
        )
        for item in [
            color(auto="1"),
            color(rgb="FF0000", theme="0"),
            color(indexed="64"),
            color(theme="99"),
        ]:
            with self.assertRaises(UnsupportedRendering):
                resolve_color(item)
        self.assertEqual(resolve_color(color(indexed="0")), (0, 0, 0))

    def test_luminance_formula_endpoints_and_grayscale(self):
        self.assertEqual(relative_luminance((0, 0, 0)), 0)
        self.assertEqual(relative_luminance((255, 255, 255)), 1)
        self.assertEqual(contrast_ratio((0, 0, 0), (255, 255, 255)), 21)
        self.assertEqual(contrast_ratio((77, 77, 77), (77, 77, 77)), 1)
        self.assertLess(contrast_ratio((128, 128, 128), (255, 255, 255)), 4.5)
        self.assertGreater(contrast_ratio((118, 118, 118), (255, 255, 255)), 4.5)


class StyleResolverTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "styles.xlsx"
        book = Workbook()
        sheet = book.active
        sheet.title = "Data"
        sheet["A1"] = "Header"
        sheet["B1"] = "Value"
        sheet["A2"] = 0
        sheet["B2"] = False
        sheet["A1"].font = Font(name="Arial", sz=18, b=True, color="FFFF0000")
        sheet["B1"].fill = PatternFill("solid", fgColor="FF808080")
        book.save(self.path)
        book.close()

    def edit(self, part, action):
        with ZipFile(self.path) as archive:
            parts = {name: archive.read(name) for name in archive.namelist()}
        root = ET.fromstring(parts[part])
        action(root)
        parts[part] = ET.tostring(root)
        with ZipFile(self.path, "w") as archive:
            for name, data in parts.items():
                archive.writestr(name, data)

    def test_explicit_style_theme_default_and_source_unchanged(self):
        before = self.path.read_bytes()
        with WorkbookReader(self.path) as reader:
            resolver = StyleResolver(reader)
            sheet = reader.sheets[0]
            cells = reader.read_cells(sheet)
            first = resolver.resolve(sheet, cells[0])
            self.assertEqual(
                (first.font_rgb, first.fill_rgb, first.size, first.bold),
                ((255, 0, 0), (255, 255, 255), Decimal(18), True),
            )
            second = resolver.resolve(sheet, cells[1])
            self.assertEqual(second.fill_rgb, (128, 128, 128))
            last = resolver.resolve(sheet, cells[-1])
            self.assertEqual(last.font_rgb, (0, 0, 0))
            self.assertTrue(last.assumptions)
            self.assertEqual(resolver.theme[0], (255, 255, 255))
            self.assertEqual(resolver.theme[1], (0, 0, 0))
        self.assertEqual(before, self.path.read_bytes())

    def test_cell_then_custom_row_then_column_then_zero(self):
        def change(root):
            data = root.find(NS + "sheetData")
            row = data[0]
            row.set("s", "1")
            row.set("customFormat", "1")
            row[1].attrib.pop("s", None)
            cols = ET.Element(NS + "cols")
            ET.SubElement(cols, NS + "col", min="1", max="2", style="2")
            root.insert(0, cols)

        self.edit("xl/worksheets/sheet1.xml", change)
        with WorkbookReader(self.path) as reader:
            sheet = reader.sheets[0]
            cells = reader.read_cells(sheet)
            resolver = StyleResolver(reader)
            self.assertEqual(
                resolver.resolve(sheet, cells[1]).font_rgb, (255, 0, 0)
            )  # custom row wins column
            self.assertEqual(
                resolver.resolve(sheet, cells[2]).fill_rgb, (128, 128, 128)
            )  # column wins 0
            self.assertEqual(
                resolver.resolve(sheet, replace(cells[0], style_id="0")).font_rgb, (0, 0, 0)
            )  # explicit 0 wins row

    def test_apply_flags_reference_base_and_missing_base_is_unsupported(self):
        def change(root):
            root.find(NS + "cellXfs")[1].set("applyFont", "0")

        self.edit("xl/styles.xml", change)
        with WorkbookReader(self.path) as reader:
            sheet = reader.sheets[0]
            cell = reader.read_cells(sheet)[0]
            self.assertEqual(StyleResolver(reader).resolve(sheet, cell).font_rgb, (0, 0, 0))
        self.edit("xl/styles.xml", lambda r: r.find(NS + "cellXfs")[1].attrib.pop("xfId"))
        with WorkbookReader(self.path) as reader:
            with self.assertRaisesRegex(UnsupportedRendering, "base"):
                StyleResolver(reader).resolve(
                    reader.sheets[0], reader.read_cells(reader.sheets[0])[0]
                )

    def test_gradient_and_mixed_rich_text_are_unsupported(self):
        def pattern(root):
            root.find(NS + "fills")[2][0].set("patternType", "darkGrid")

        self.edit("xl/styles.xml", pattern)
        with WorkbookReader(self.path) as reader:
            sheet = reader.sheets[0]
            resolver = StyleResolver(reader)
            cells = reader.read_cells(sheet)
            with self.assertRaisesRegex(UnsupportedRendering, "Patterned"):
                resolver.resolve(sheet, cells[1])
            mixed = replace(cells[0], rich_text=True, rich_runs=(("A", ()), ("B", (("b", ()),))))
            with self.assertRaisesRegex(UnsupportedRendering, "Mixed"):
                resolver.resolve(sheet, mixed)

    def test_workbook_palette_is_read_instead_of_fallback(self):
        def palette(root):
            existing = root.find(NS + "colors")
            if existing is not None:
                root.remove(existing)
            colors = ET.SubElement(root, NS + "colors")
            indexed = ET.SubElement(colors, NS + "indexedColors")
            ET.SubElement(indexed, NS + "rgbColor", rgb="FF123456")
            font = root.find(NS + "fonts")[1]
            font.find(NS + "color").clear()
            font.find(NS + "color").set("indexed", "0")

        self.edit("xl/styles.xml", palette)
        with WorkbookReader(self.path) as reader:
            sheet = reader.sheets[0]
            self.assertEqual(
                StyleResolver(reader).resolve(sheet, reader.read_cells(sheet)[0]).font_rgb,
                (18, 52, 86),
            )

    def test_table_style_overlay_is_explicitly_unsupported(self):
        from openpyxl import load_workbook

        book = load_workbook(self.path)
        table = Table(displayName="Styled", ref="A1:B2")
        table.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showRowStripes=True)
        book.active.add_table(table)
        book.save(self.path)
        book.close()
        with WorkbookReader(self.path) as reader:
            sheet = reader.sheets[0]
            with self.assertRaisesRegex(UnsupportedRendering, "Table-style"):
                StyleResolver(reader).resolve(sheet, reader.read_cells(sheet)[0])


class CorrectedPackTests(unittest.TestCase):
    def test_frozen_palette_tint_and_contrast(self):
        import json

        from accessibility_checker.color_palette import INDEXED_RGB

        pack = json.loads(
            (
                Path(__file__).parents[1]
                / ".docs/phase4_agent_context_pack/phase4-policy-vectors.json"
            ).read_text()
        )
        self.assertEqual(list(INDEXED_RGB), pack["default_indexed_rgb"])
        for case in pack["tint"]:
            with self.subTest(case=case):
                self.assertEqual(
                    tinted(rgb(case["base_rgb"]), case["tint"]), rgb(case["expected_rgb"])
                )
        for case in pack["contrast"]:
            self.assertAlmostEqual(
                contrast_ratio(rgb(case["font_rgb"]), rgb(case["fill_rgb"])),
                case["ratio"],
                places=12,
            )

    def test_exact_half_and_neighbors(self):
        self.assertEqual(tinted((1, 1, 1), "-0.5"), (1, 1, 1))
        self.assertEqual(tinted((5, 5, 5), "-0.5"), (3, 3, 3))
        self.assertEqual(tinted((1, 1, 1), "-0.500000000000000000000000000001"), (0, 0, 0))
        self.assertEqual(tinted((1, 1, 1), "-0.499999999999999999999999999999"), (1, 1, 1))
