"""Synthetic boundary workbooks for checker-only performance measurement.

Primary criterion: none (not a WCAG check). This supports the performance
requirement REQ-15 / AC-18 (five runs of supported boundary work, each within
60 seconds or a controlled failure, with identical successful findings).
The measurement exercises all six implemented rules together: 1.1.1 Non-text
Content, 1.3.1 Info and Relationships, 1.4.1 Use of Color / 1.4.3 Contrast
(Minimum), 2.4.2 Page Titled (related 2.4.6) and 2.4.4 Link Purpose (In Context).

These are SYNTHETIC measurement inputs, not the human-reviewed boundary
fixtures owned by the tester team, and not acceptance evidence. The profile
compositions are prototype choices recorded in AE-022; the specification does
not define them. Only the bounds (25,000,000 bytes, 50 worksheets, 250,000
nonempty cells) come from the Phase 5 specification.

Determinism: packages are written directly as OOXML with fixed ZIP timestamps,
attributes and member order, so identical arguments give identical bytes on the
same Python/zlib build (deflate output may differ between zlib versions).

Usage:
    .venv/bin/python -m scripts.perf_workbooks --out .perf/workbooks [--profile a ...]
"""

import argparse
import hashlib
import json
import sys
import zipfile
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

from openpyxl.utils.cell import get_column_letter
from openpyxl.writer.theme import theme_xml

MAX_BYTES = 25_000_000
MAX_SHEETS = 50
MAX_CELLS = 250_000
DEFAULT_CELLS = 250_000

ZIP_DATE = (1980, 1, 1, 0, 0, 0)
MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
CT_MAIN = "application/vnd.openxmlformats-officedocument.spreadsheetml"

HEADERS = (
    "Item ID",
    "Category",
    "Quantity",
    "Unit Price",
    "Amount",
    "Score",
    "Date",
    "Status",
    "Link",
    "Note",
)
CATEGORIES = tuple(f"Category {n:02d}" for n in range(1, 21))
NOTES = (
    "Verified",
    "Awaiting review",
    "Backordered",
    "Discontinued",
    "Seasonal",
    "Promotional",
    "Bulk order",
    "Standard",
)

# cellXfs indices used below (see STYLES_XML).
S_DEFAULT, S_HEADER, S_MONEY, S_RED, S_LINK, S_YELLOW, S_DATE, S_TITLE = range(8)

STYLES_XML = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="{MAIN}">
<numFmts count="1"><numFmt numFmtId="164" formatCode="#,##0.00"/></numFmts>
<fonts count="5">
<font><sz val="11"/><color theme="1"/><name val="Calibri"/><family val="2"/><scheme val="minor"/></font>
<font><b/><sz val="11"/><color theme="1"/><name val="Calibri"/><family val="2"/><scheme val="minor"/></font>
<font><sz val="11"/><color rgb="FFC00000"/><name val="Calibri"/><family val="2"/><scheme val="minor"/></font>
<font><u/><sz val="11"/><color theme="10"/><name val="Calibri"/><family val="2"/><scheme val="minor"/></font>
<font><b/><sz val="14"/><color theme="1"/><name val="Calibri"/><family val="2"/><scheme val="minor"/></font>
</fonts>
<fills count="4">
<fill><patternFill patternType="none"/></fill>
<fill><patternFill patternType="gray125"/></fill>
<fill><patternFill patternType="solid"><fgColor rgb="FFD9D9D9"/><bgColor indexed="64"/></patternFill></fill>
<fill><patternFill patternType="solid"><fgColor rgb="FFFFFF00"/><bgColor indexed="64"/></patternFill></fill>
</fills>
<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>
<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
<cellXfs count="8">
<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/>
<xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>
<xf numFmtId="0" fontId="2" fillId="0" borderId="0" xfId="0" applyFont="1"/>
<xf numFmtId="0" fontId="3" fillId="0" borderId="0" xfId="0" applyFont="1"/>
<xf numFmtId="0" fontId="0" fillId="3" borderId="0" xfId="0" applyFill="1"/>
<xf numFmtId="14" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>
<xf numFmtId="0" fontId="4" fillId="0" borderId="0" xfId="0" applyFont="1"/>
</cellXfs>
<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
<dxfs count="1"><dxf><font><color rgb="FF9C0006"/></font><fill><patternFill><bgColor rgb="FFFFC7CE"/></patternFill></fill></dxf></dxfs>
<tableStyles count="0" defaultTableStyle="TableStyleMedium2" defaultPivotStyle="PivotStyleLight16"/>
</styleSheet>
"""


class LimitExceeded(ValueError):
    """A generated workbook would exceed a Phase 5 intake bound."""


def check_limits(*, size, sheets, cells, max_bytes=MAX_BYTES, max_sheets=MAX_SHEETS,
                 max_cells=MAX_CELLS):
    """Raise LimitExceeded unless every bound is respected (inclusive)."""
    problems = []
    if size is not None and size > max_bytes:
        problems.append(f"{size} bytes > {max_bytes}")
    if sheets > max_sheets:
        problems.append(f"{sheets} worksheets > {max_sheets}")
    if cells > max_cells:
        problems.append(f"{cells} nonempty cells > {max_cells}")
    if problems:
        raise LimitExceeded("; ".join(problems))


@dataclass
class Sheet:
    name: str
    rows: list = field(default_factory=list)  # [(row_number, [cell_xml, ...])]
    max_column: int = 1
    merges: list = field(default_factory=list)
    conditional: list = field(default_factory=list)  # raw XML fragments
    hyperlinks: list = field(default_factory=list)  # [(ref, url)]
    table: tuple | None = None  # (ref, header names)
    cells: int = 0


class _Strings:
    def __init__(self):
        self.index = {}
        self.uses = 0

    def __call__(self, text):
        self.uses += 1
        return self.index.setdefault(text, len(self.index))

    def xml(self):
        items = "".join(
            f'<si><t xml:space="preserve">{escape(text)}</t></si>' for text in self.index
        )
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            f'<sst xmlns="{MAIN}" count="{self.uses}" uniqueCount="{len(self.index)}">'
            f"{items}</sst>"
        )


def _ref(row, column):
    return f"{get_column_letter(column)}{row}"


def _style(style):
    return f' s="{style}"' if style else ""


class _Builder:
    """Accumulates cells for one sheet and counts every nonempty cell written."""

    def __init__(self, sheet, strings):
        self.sheet = sheet
        self.strings = strings
        self.row_number = None
        self.row = None

    def start_row(self, number):
        self.row_number = number
        self.row = []
        self.sheet.rows.append((number, self.row))

    def _add(self, column, xml):
        self.row.append(xml)
        self.sheet.cells += 1
        self.sheet.max_column = max(self.sheet.max_column, column)

    def number(self, column, value, style=0):
        ref = _ref(self.row_number, column)
        self._add(column, f'<c r="{ref}"{_style(style)}><v>{value}</v></c>')

    def text(self, column, value, style=0):
        ref = _ref(self.row_number, column)
        index = self.strings(value)
        self._add(column, f'<c r="{ref}"{_style(style)} t="s"><v>{index}</v></c>')

    def formula(self, column, formula, cached, style=0, string=False):
        ref = _ref(self.row_number, column)
        kind = ' t="str"' if string else ""
        self._add(
            column,
            f'<c r="{ref}"{_style(style)}{kind}><f>{escape(formula)}</f>'
            f"<v>{escape(str(cached))}</v></c>",
        )


def _numeric_sheet(name, strings, rows, columns=10, offset=0):
    sheet = Sheet(name)
    builder = _Builder(sheet, strings)
    for row in range(1, rows + 1):
        builder.start_row(row)
        for column in range(1, columns + 1):
            seed = (row * 31 + column * 17 + offset * 7) % 100_000
            value = seed if column % 2 else f"{seed // 100}.{seed % 100:02d}"
            builder.number(column, value)
    return sheet


def _data_row(builder, sheet_index, i, *, links, formula_links):
    """One deterministic 10-column record (A..J) for data index i (1-based)."""
    r = builder.row_number
    quantity = (i * 37 + sheet_index * 11) % 500 + 1
    cents = (i * 53 + sheet_index * 7) % 10_000
    builder.text(1, f"S{sheet_index:02d}-ITEM-{i:05d}")
    builder.text(2, CATEGORIES[(i * 7 + sheet_index) % len(CATEGORIES)])
    builder.number(3, quantity)
    builder.number(4, f"{cents // 100}.{cents % 100:02d}", S_MONEY)
    builder.formula(5, f"C{r}*D{r}", Decimal(quantity) * Decimal(cents) / 100, S_MONEY)
    builder.number(6, (i * 13 + sheet_index) % 101)
    builder.number(7, 45_000 + i % 730, S_DATE)
    if i % 20 == 7:
        builder.text(8, "Late", S_RED)
    else:
        builder.text(8, ("Open", "Closed", "Pending")[i % 3])
    url = None
    if links and i == 5:
        builder.text(9, "click here", S_LINK)
        url = "https://example.invalid/help"
    elif links and i % 10 == 0:
        builder.text(9, f"Details for item {i:05d}", S_LINK)
        url = f"https://example.invalid/items/{sheet_index}/{i}"
    elif formula_links and i in (7, 13):
        builder.formula(
            9, 'HYPERLINK("https://example.invalid/help","here")', "here", S_LINK, string=True
        )
    else:
        builder.text(9, "No link")
    if url:
        builder.sheet.hyperlinks.append((_ref(r, 9), url))
    builder.text(10, NOTES[(i * 5) % len(NOTES)], S_YELLOW if i % 25 == 0 else 0)


def _conditional(first, last):
    return [
        f'<conditionalFormatting sqref="E{first}:E{last}"><cfRule type="cellIs" dxfId="0" '
        'priority="1" operator="greaterThan"><formula>2500</formula></cfRule>'
        "</conditionalFormatting>",
        f'<conditionalFormatting sqref="F{first}:F{last}"><cfRule type="colorScale" '
        'priority="2"><colorScale><cfvo type="min"/><cfvo type="max"/>'
        '<color rgb="FFF8696B"/><color rgb="FF63BE7B"/></colorScale></cfRule>'
        "</conditionalFormatting>",
    ]


def _mixed_sheet(name, strings, sheet_index, per_sheet, *, table):
    """Title merge, blank row, header row, dense 10-column data, blank row, merged notes.

    per_sheet = 1 (title) + 10 (header) + 10 * data_rows + notes, with
    20 <= notes <= 29 chosen so that the data block is a whole number of rows.
    """
    remaining = per_sheet - 11
    notes = 20 + (remaining - 20) % 10
    data_rows = (remaining - notes) // 10
    if data_rows < 20:
        raise ValueError("Profile c needs at least 241 cells per worksheet")
    sheet = Sheet(name)
    builder = _Builder(sheet, strings)
    builder.start_row(1)
    builder.text(1, f"{name} quarterly sales report", S_TITLE)
    sheet.merges.append("A1:J1")
    builder.start_row(3)
    for column, header in enumerate(HEADERS, 1):
        builder.text(column, header, S_HEADER)
    first, last = 4, 3 + data_rows
    for i in range(1, data_rows + 1):
        builder.start_row(3 + i)
        _data_row(builder, sheet_index, i, links=True, formula_links=True)
    for n in range(notes):
        row = last + 2 + n
        builder.start_row(row)
        builder.text(1, f"Note {n + 1}: synthetic measurement row for {name}")
        sheet.merges.append(f"A{row}:J{row}")
    sheet.conditional = _conditional(first, last)
    if table:
        sheet.table = (f"A3:J{last}", HEADERS)
    return sheet


def _table_sheet(name, strings, cells):
    if cells % 10 or cells < 30:
        raise ValueError("Profile d needs a multiple of 10 cells (at least 30)")
    sheet = Sheet(name)
    builder = _Builder(sheet, strings)
    builder.start_row(1)
    for column, header in enumerate(HEADERS, 1):
        builder.text(column, header, S_HEADER)
    rows = cells // 10 - 1
    for i in range(1, rows + 1):
        builder.start_row(1 + i)
        _data_row(builder, 1, i, links=False, formula_links=False)
    sheet.table = (f"A1:J{rows + 1}", HEADERS)
    return sheet


def _profile_a(cells, strings):
    if cells % 10:
        raise ValueError("Profile a needs a multiple of 10 cells")
    return [_numeric_sheet("Numbers", strings, cells // 10)]


def _profile_b(cells, strings):
    if cells % 500:
        raise ValueError("Profile b needs a multiple of 500 cells (50 sheets x 10 columns)")
    return [
        _numeric_sheet(f"Part{n:02d}", strings, cells // 500, offset=n) for n in range(1, 51)
    ]


def _profile_c(cells, strings):
    if cells % 10:
        raise ValueError("Profile c needs a multiple of 10 cells (10 sheets)")
    sheets = []
    for n in range(1, 11):
        # The last tab keeps a default name so WORKSHEET_NAME's whole-workbook
        # rename preflight is exercised; sheets 1 and 6 hold styled formal tables.
        name = "Sheet10" if n == 10 else f"Region{n:02d}"
        sheets.append(_mixed_sheet(name, strings, n, cells // 10, table=n in (1, 6)))
    return sheets


def _profile_d(cells, strings):
    return [_table_sheet("Ledger", strings, cells)]


PROFILES = {
    "a": ("numeric_single_sheet", _profile_a),
    "b": ("numeric_50_sheets", _profile_b),
    "c": ("mixed_realistic_10_sheets", _profile_c),
    "d": ("styled_table_single_sheet", _profile_d),
}


def _sheet_xml(sheet, rels):
    last_row = sheet.rows[-1][0] if sheet.rows else 1
    parts = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n',
        f'<worksheet xmlns="{MAIN}" xmlns:r="{REL}">',
        f'<dimension ref="A1:{_ref(last_row, sheet.max_column)}"/>',
        '<sheetViews><sheetView workbookViewId="0"/></sheetViews>',
        '<sheetFormatPr defaultRowHeight="15"/>',
        "<sheetData>",
    ]
    for number, cells in sheet.rows:
        parts.append(f'<row r="{number}">{"".join(cells)}</row>')
    parts.append("</sheetData>")
    if sheet.merges:
        parts.append(f'<mergeCells count="{len(sheet.merges)}">')
        parts.extend(f'<mergeCell ref="{ref}"/>' for ref in sheet.merges)
        parts.append("</mergeCells>")
    parts.extend(sheet.conditional)
    if sheet.hyperlinks:
        parts.append("<hyperlinks>")
        for ref, url in sheet.hyperlinks:
            rid = f"rId{len(rels) + 1}"
            rels.append((rid, "hyperlink", url, True))
            parts.append(f'<hyperlink ref="{ref}" r:id="{rid}"/>')
        parts.append("</hyperlinks>")
    parts.append(
        '<pageMargins left="0.7" right="0.7" top="0.75" bottom="0.75" header="0.3" footer="0.3"/>'
    )
    return parts


def _rels_xml(rels):
    items = "".join(
        f'<Relationship Id="{rid}" Type="{REL}/{kind}" Target={quoteattr(target)}'
        + (' TargetMode="External"' if external else "")
        + "/>"
        for rid, kind, target, external in rels
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f'<Relationships xmlns="{PKG_REL}">{items}</Relationships>'
    )


def _table_xml(table_id, ref, headers):
    columns = "".join(
        f'<tableColumn id="{n}" name={quoteattr(name)}/>' for n, name in enumerate(headers, 1)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f'<table xmlns="{MAIN}" id="{table_id}" name="Table{table_id}" '
        f'displayName="Table{table_id}" ref="{ref}" totalsRowShown="0">'
        f'<autoFilter ref="{ref}"/><tableColumns count="{len(headers)}">{columns}</tableColumns>'
        '<tableStyleInfo name="TableStyleMedium2" showFirstColumn="0" showLastColumn="0" '
        'showRowStripes="1" showColumnStripes="0"/></table>'
    )


def _write(archive, name, data):
    info = zipfile.ZipInfo(name, ZIP_DATE)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = 0o644 << 16
    if isinstance(data, str):
        data = data.encode("utf-8")
    archive.writestr(info, data, compresslevel=6)


def build_workbook(profile, path, *, cells=DEFAULT_CELLS, max_bytes=MAX_BYTES,
                   max_sheets=MAX_SHEETS, max_cells=MAX_CELLS):
    """Write one synthetic profile to path and return its manifest dictionary.

    Limits are checked before writing (sheets/cells) and after writing (bytes);
    an oversized package is deleted before LimitExceeded is raised.
    """
    if profile not in PROFILES:
        raise ValueError(f"Unknown profile {profile!r}; choose from {sorted(PROFILES)}")
    label, factory = PROFILES[profile]
    strings = _Strings()
    sheets = factory(cells, strings)
    nonempty = sum(sheet.cells for sheet in sheets)
    if nonempty != cells:
        raise AssertionError(f"Generator wrote {nonempty} cells, expected {cells}")
    check_limits(size=None, sheets=len(sheets), cells=nonempty, max_bytes=max_bytes,
                 max_sheets=max_sheets, max_cells=max_cells)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tables = 0
    overrides = [
        ("/xl/workbook.xml", f"{CT_MAIN}.sheet.main+xml"),
        ("/xl/styles.xml", f"{CT_MAIN}.styles+xml"),
        ("/xl/theme/theme1.xml", "application/vnd.openxmlformats-officedocument.theme+xml"),
        ("/xl/sharedStrings.xml", f"{CT_MAIN}.sharedStrings+xml"),
        ("/docProps/core.xml", "application/vnd.openxmlformats-package.core-properties+xml"),
        (
            "/docProps/app.xml",
            "application/vnd.openxmlformats-officedocument.extended-properties+xml",
        ),
    ]
    with zipfile.ZipFile(path, "w") as archive:
        for index, sheet in enumerate(sheets, 1):
            rels = []
            parts = _sheet_xml(sheet, rels)
            if sheet.table:
                tables += 1
                rid = f"rId{len(rels) + 1}"
                rels.append((rid, "table", f"../tables/table{tables}.xml", False))
                parts.append(f'<tableParts count="1"><tablePart r:id="{rid}"/></tableParts>')
                _write(archive, f"xl/tables/table{tables}.xml", _table_xml(tables, *sheet.table))
                overrides.append((f"/xl/tables/table{tables}.xml", f"{CT_MAIN}.table+xml"))
            parts.append("</worksheet>")
            _write(archive, f"xl/worksheets/sheet{index}.xml", "".join(parts))
            if rels:
                _write(archive, f"xl/worksheets/_rels/sheet{index}.xml.rels", _rels_xml(rels))
            overrides.append(
                (f"/xl/worksheets/sheet{index}.xml", f"{CT_MAIN}.worksheet+xml")
            )
            sheet.rows = None  # release cell XML once written
        workbook_sheets = "".join(
            f'<sheet name={quoteattr(sheet.name)} sheetId="{n}" r:id="rId{n}"/>'
            for n, sheet in enumerate(sheets, 1)
        )
        _write(
            archive,
            "xl/workbook.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            f'<workbook xmlns="{MAIN}" xmlns:r="{REL}"><bookViews><workbookView/></bookViews>'
            f"<sheets>{workbook_sheets}</sheets></workbook>",
        )
        count = len(sheets)
        workbook_rels = [
            (f"rId{n}", "worksheet", f"worksheets/sheet{n}.xml", False)
            for n in range(1, count + 1)
        ] + [
            (f"rId{count + 1}", "styles", "styles.xml", False),
            (f"rId{count + 2}", "theme", "theme/theme1.xml", False),
            (f"rId{count + 3}", "sharedStrings", "sharedStrings.xml", False),
        ]
        _write(archive, "xl/_rels/workbook.xml.rels", _rels_xml(workbook_rels))
        _write(archive, "xl/styles.xml", STYLES_XML)
        _write(archive, "xl/theme/theme1.xml", theme_xml)
        _write(archive, "xl/sharedStrings.xml", strings.xml())
        _write(
            archive,
            "docProps/core.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/'
            'metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" '
            'xmlns:dcterms="http://purl.org/dc/terms/" '
            'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
            f"<dc:title>Synthetic performance workbook ({label})</dc:title>"
            "<dc:creator>perf_workbooks.py</dc:creator>"
            '<dcterms:created xsi:type="dcterms:W3CDTF">2026-01-01T00:00:00Z</dcterms:created>'
            '<dcterms:modified xsi:type="dcterms:W3CDTF">2026-01-01T00:00:00Z</dcterms:modified>'
            "</cp:coreProperties>",
        )
        _write(
            archive,
            "docProps/app.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/'
            'extended-properties"><Application>Microsoft Excel</Application></Properties>',
        )
        content_types = "".join(
            f'<Override PartName="{name}" ContentType="{kind}"/>' for name, kind in overrides
        )
        _write(
            archive,
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.'
            'relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'
            f"{content_types}</Types>",
        )
        _write(
            archive,
            "_rels/.rels",
            _rels_xml(
                [
                    ("rId1", "officeDocument", "xl/workbook.xml", False),
                    (
                        "rId2",
                        "metadata/core-properties",
                        "docProps/core.xml",
                        False,
                    ),
                    ("rId3", "extended-properties", "docProps/app.xml", False),
                ]
            ).replace(
                f"{REL}/metadata/core-properties",
                "http://schemas.openxmlformats.org/package/2006/relationships/metadata/"
                "core-properties",
            ),
        )
    data = path.read_bytes()
    try:
        check_limits(size=len(data), sheets=len(sheets), cells=nonempty, max_bytes=max_bytes,
                     max_sheets=max_sheets, max_cells=max_cells)
    except LimitExceeded:
        path.unlink()
        raise
    return {
        "profile": profile,
        "label": label,
        "path": str(path),
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
        "worksheets": len(sheets),
        "nonempty_cells": nonempty,
        "unique_shared_strings": len(strings.index),
        "merges": sum(len(s.merges) for s in sheets),
        "hyperlinks": sum(len(s.hyperlinks) for s in sheets),
        "formal_tables": tables,
        "conditional_formatting_blocks": sum(len(s.conditional) for s in sheets),
        "synthetic": True,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--out", default=".perf/workbooks", help="output directory")
    parser.add_argument("--profile", action="append", choices=sorted(PROFILES))
    parser.add_argument("--cells", type=int, default=DEFAULT_CELLS)
    args = parser.parse_args(argv)
    manifests = []
    for profile in args.profile or sorted(PROFILES):
        name = f"perf_{profile}_{PROFILES[profile][0]}_{args.cells}.xlsx"
        manifests.append(build_workbook(profile, Path(args.out) / name, cells=args.cells))
    json.dump(manifests, sys.stdout, indent=2)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
