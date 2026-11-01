"""Builds Team 12's Phase 4 fixtures (shared specification 2.1.0, ruleset 2.0.0) into
tester/fixtures/phase4/: clean_all_six, seeded_all_six, and the correction fixtures
alt_supported, rename_references, link_supported, header_range and header_disabled_table.

Every part is written by hand so each cell, style, table, merge, link and object is
deliberate; expected findings are listed per item in tester/fixtures/phase4/README.md
and were written from these definitions, not by running an engine. Drawing, chart and
ZIP helpers are shared with scripts/build_shared_fixtures.py, so entries are stored
uncompressed with fixed timestamps and the bytes are reproducible.

Colour policy (spec §7.7): every style names an explicit black or grey font colour and a
solid white fill, so no populated cell relies on the "missing fill is white / missing font
is black" display assumption, and only the cells seeded on purpose are nonneutral.

    uv run python scripts/build_phase4_fixtures.py          # write the files
    uv run python scripts/build_phase4_fixtures.py --check  # verify committed bytes
"""

import re
import sys
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_shared_fixtures import (  # noqa: E402
    CT, HEAD, MAIN, REL, Drawing, Media, chart, chart_frame, drawing_xml, group, picture, props, rels, shape, zipped)

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "tester" / "fixtures" / "phase4"
PKG = "http://schemas.openxmlformats.org/package/2006/relationships"
HYPERLINK = f"{REL}/hyperlink"

##  Cell styles (cellXfs indices). Font colours: 0 black, 1 black bold, 2 red, 3 grey 999999.
TEXT, HEADER, MONEY, RED, GREY = 0, 1, 2, 3, 4
STYLES = (
    f'{HEAD}<styleSheet xmlns="{MAIN}">'
    '<numFmts count="1"><numFmt numFmtId="164" formatCode="&quot;$&quot;#,##0"/></numFmts>'
    '<fonts count="4">'
    '<font><sz val="11"/><color rgb="FF000000"/><name val="Calibri"/><family val="2"/></font>'
    '<font><b/><sz val="11"/><color rgb="FF000000"/><name val="Calibri"/><family val="2"/></font>'
    '<font><sz val="11"/><color rgb="FFFF0000"/><name val="Calibri"/><family val="2"/></font>'
    '<font><sz val="11"/><color rgb="FF999999"/><name val="Calibri"/><family val="2"/></font></fonts>'
    '<fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill>'
    '<fill><patternFill patternType="solid"><fgColor rgb="FFFFFFFF"/><bgColor indexed="64"/></patternFill></fill>'
    '</fills><borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
    '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="2" borderId="0" applyFont="1" applyFill="1"/>'
    '</cellStyleXfs><cellXfs count="5">'
    '<xf numFmtId="0" fontId="0" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/>'
    '<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/>'
    '<xf numFmtId="164" fontId="0" fillId="2" borderId="0" xfId="0" applyNumberFormat="1" applyFont="1" applyFill="1"/>'
    '<xf numFmtId="0" fontId="2" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/>'
    '<xf numFmtId="0" fontId="3" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/></cellXfs>'
    '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>')


##  ---- Worksheets ----

def _split(ref):
    letters, digits = re.fullmatch(r"([A-Z]+)([0-9]+)", ref).groups()
    number = 0
    for letter in letters:
        number = number * 26 + ord(letter) - 64
    return int(digits), number


class Shared:
    ##  A cell value stored as an index into the workbook's shared-string table.
    def __init__(self, index):
        self.index = index


class Rich:
    ##  An inline string made of rich-text runs: [(text, run properties xml)].
    def __init__(self, *runs):
        self.runs = runs


def worksheet(cells, *, widths=(), merges=(), links=(), drawing=None, tables=(), conditional=(), validations=(),
              protection=None, page_setup=None, legacy_drawing=None, hidden_rows=(), hidden_cols=()):
    ##  cells: {ref: (value, style)} or {ref: ("=formula", cached value, style)}. Strings are
    ##  inline strings unless given as Shared(index). links: [(ref, rId)] for external links or
    ##  [(ref, None, location, display)] for internal ones; conditional: [(sqref, formula, dxfId)];
    ##  validations: [(sqref, list formula)]; drawing / tables: relationship IDs. Elements follow
    ##  the CT_Worksheet order.
    def cell(ref, spec):
        value, style = spec[0], spec[-1]
        if isinstance(value, Shared):
            return f'<c r="{ref}" s="{style}" t="s"><v>{value.index}</v></c>'
        if isinstance(value, Rich):
            runs = "".join(f"<r><rPr>{props_xml}</rPr><t xml:space=\"preserve\">{escape(text)}</t></r>"
                           for text, props_xml in value.runs)
            return f'<c r="{ref}" s="{style}" t="inlineStr"><is>{runs}</is></c>'
        if isinstance(value, str) and value.startswith("="):
            kind = ' t="str"' if isinstance(spec[1], str) else ""
            return f'<c r="{ref}" s="{style}"{kind}><f>{escape(value[1:])}</f><v>{escape(str(spec[1]))}</v></c>'
        if isinstance(value, str):
            return f'<c r="{ref}" s="{style}" t="inlineStr"><is><t>{escape(value)}</t></is></c>'
        return f'<c r="{ref}" s="{style}"><v>{value}</v></c>'

    def hyperlink(ref, rid, location=None, display=None):
        attrs = f'ref="{ref}"' + (f' r:id="{rid}"' if rid else "")
        attrs += (f" location={quoteattr(location)}" if location else "") + (f" display={quoteattr(display)}" if display else "")
        return f"<hyperlink {attrs}/>"

    rows = {}
    for ref in sorted(cells, key=_split):
        rows.setdefault(_split(ref)[0], []).append(cell(ref, cells[ref]))
    data = "".join(f'<row r="{r}"' + (' hidden="1"' if r in hidden_rows else "") + f'>{"".join(row)}</row>'
                   for r, row in sorted(rows.items()))
    cols = "".join(f'<col min="{i}" max="{i}" width="{w}" customWidth="1"' + (' hidden="1"' if i in hidden_cols else "")
                   + "/>" for i, w in enumerate(widths, start=1))
    xml = f'{HEAD}<worksheet xmlns="{MAIN}" xmlns:r="{REL}">' + (f"<cols>{cols}</cols>" if cols else "")
    xml += f"<sheetData>{data}</sheetData>"
    if protection:
        xml += f"<sheetProtection {protection}/>"
    if merges:
        xml += f'<mergeCells count="{len(merges)}">' + "".join(f'<mergeCell ref="{m}"/>' for m in merges) + "</mergeCells>"
    for priority, (sqref, formula, dxf) in enumerate(conditional, start=1):
        xml += (f'<conditionalFormatting sqref="{sqref}"><cfRule type="expression" dxfId="{dxf}" priority="{priority}">'
                f"<formula>{escape(formula)}</formula></cfRule></conditionalFormatting>")
    if validations:
        xml += f'<dataValidations count="{len(validations)}">' + "".join(
            f'<dataValidation type="list" allowBlank="1" showInputMessage="1" showErrorMessage="1" sqref="{sqref}">'
            f"<formula1>{escape(formula)}</formula1></dataValidation>" for sqref, formula in validations) + "</dataValidations>"
    if links:
        xml += "<hyperlinks>" + "".join(hyperlink(*link) for link in links) + "</hyperlinks>"
    xml += '<pageMargins left="0.7" right="0.7" top="0.75" bottom="0.75" header="0.3" footer="0.3"/>'
    if page_setup:
        xml += f'<pageSetup orientation="landscape" r:id="{page_setup}"/>'
    if drawing:
        xml += f'<drawing r:id="{drawing}"/>'
    if legacy_drawing:
        xml += f'<legacyDrawing r:id="{legacy_drawing}"/>'
    if tables:
        xml += f'<tableParts count="{len(tables)}">' + "".join(f'<tablePart r:id="{t}"/>' for t in tables) + "</tableParts>"
    return xml + "</worksheet>"


def table(table_id, name, ref, columns, header_row_count=None, style=None):
    ##  A minimal formal table: no filter, no totals row, and no style overlay unless named.
    header = "" if header_row_count is None else f' headerRowCount="{header_row_count}"'
    cols = "".join(f'<tableColumn id="{i}" name={quoteattr(c)}/>' for i, c in enumerate(columns, start=1))
    overlay = (f'<tableStyleInfo name="{style}" showFirstColumn="0" showLastColumn="0" showRowStripes="1" '
               f'showColumnStripes="0"/>') if style else ""
    return (f'{HEAD}<table xmlns="{MAIN}" id="{table_id}" name="{name}" displayName="{name}" ref="{ref}"{header}>'
            f'<tableColumns count="{len(columns)}">{cols}</tableColumns>{overlay}</table>')


##  ---- Package ----

def package(title, sheets, tables, drawings, charts, media, defined_names=(), shared_strings=None, styles=STYLES,
            extra_parts=None, extra_types=(), states=None, theme=None):
    ##  sheets: [(name, sheetId, part number, worksheet xml, [(rId, type, target, external?)])]
    ##  tables: {number: xml}; drawings: {number: (xml, Drawing)}; charts: {number: xml};
    ##  defined_names: [(name, formula, local sheet index or None)]; shared_strings: [text];
    ##  extra_parts: {path: content} with extra_types [("Default"|"Override", extension or part, type)];
    ##  states: {sheet name: "hidden" | "veryHidden"}
    overrides = [("/xl/workbook.xml", f"{CT}.spreadsheetml.sheet.main+xml"),
                 ("/xl/styles.xml", f"{CT}.spreadsheetml.styles+xml"),
                 ("/docProps/core.xml", "application/vnd.openxmlformats-package.core-properties+xml"),
                 ("/docProps/app.xml", f"{CT}.extended-properties+xml")]
    overrides += [(f"/xl/worksheets/sheet{s[2]}.xml", f"{CT}.spreadsheetml.worksheet+xml") for s in sheets]
    overrides += [(f"/xl/tables/table{n}.xml", f"{CT}.spreadsheetml.table+xml") for n in tables]
    overrides += [(f"/xl/drawings/drawing{n}.xml", f"{CT}.drawing+xml") for n in drawings]
    overrides += [(f"/xl/charts/chart{n}.xml", f"{CT}.drawingml.chart+xml") for n in charts]
    if shared_strings is not None:
        overrides.append(("/xl/sharedStrings.xml", f"{CT}.spreadsheetml.sharedStrings+xml"))
    names = "".join(f"<definedName name={quoteattr(name)}" + (f' localSheetId="{local}"' if local is not None else "")
                    + f">{escape(formula)}</definedName>" for name, formula, local in defined_names)
    workbook_rels = [(f"rId{i + 1}", f"{REL}/worksheet", f"worksheets/sheet{s[2]}.xml") for i, s in enumerate(sheets)]
    workbook_rels.append((f"rId{len(sheets) + 1}", f"{REL}/styles", "styles.xml"))
    if shared_strings is not None:
        workbook_rels.append((f"rId{len(workbook_rels) + 1}", f"{REL}/sharedStrings", "sharedStrings.xml"))
    if theme is not None:
        workbook_rels.append((f"rId{len(workbook_rels) + 1}", f"{REL}/theme", "theme/theme1.xml"))
        overrides.append(("/xl/theme/theme1.xml", f"{CT}.theme+xml"))
        extra_parts = {**(extra_parts or {}), "xl/theme/theme1.xml": theme}
    types = ('<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
             '<Default Extension="xml" ContentType="application/xml"/><Default Extension="png" ContentType="image/png"/>'
             '<Default Extension="jpeg" ContentType="image/jpeg"/>'
             + "".join(f'<Default Extension="{k}" ContentType="{t}"/>' for kind, k, t in extra_types if kind == "Default")
             + "".join(f'<Override PartName="{p}" ContentType="{t}"/>' for p, t in overrides)
             + "".join(f'<Override PartName="{k}" ContentType="{t}"/>' for kind, k, t in extra_types if kind == "Override"))
    states = states or {}
    parts = {
        "[Content_Types].xml": f'{HEAD}<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">{types}</Types>',
        "_rels/.rels": rels(("rId1", f"{REL}/officeDocument", "xl/workbook.xml"),
                            ("rId2", "http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties",
                             "docProps/core.xml"),
                            ("rId3", f"{REL}/extended-properties", "docProps/app.xml")),
        "docProps/core.xml": (f'{HEAD}<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/'
                              f'metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>'
                              f'{escape(title)}</dc:title><dc:creator>Team 12</dc:creator><dc:language>en-US'
                              f'</dc:language></cp:coreProperties>'),
        "docProps/app.xml": (f'{HEAD}<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/'
                             f'extended-properties"><Application>Microsoft Excel</Application></Properties>'),
        "xl/workbook.xml": (f'{HEAD}<workbook xmlns="{MAIN}" xmlns:r="{REL}"><bookViews><workbookView activeTab="0"/>'
                            f'</bookViews><sheets>' + "".join(
                                f'<sheet name={quoteattr(name)} sheetId="{sid}"'
                                + (f' state="{states[name]}"' if name in states else "") + f' r:id="rId{i + 1}"/>'
                                for i, (name, sid, *_rest) in enumerate(sheets)) + "</sheets>"
                            + (f"<definedNames>{names}</definedNames>" if names else "") + "</workbook>"),
        "xl/_rels/workbook.xml.rels": rels(*workbook_rels),
        "xl/styles.xml": styles,
    }
    if shared_strings is not None:
        parts["xl/sharedStrings.xml"] = (
            f'{HEAD}<sst xmlns="{MAIN}" count="{len(shared_strings)}" uniqueCount="{len(shared_strings)}">'
            + "".join(f"<si><t>{escape(s)}</t></si>" for s in shared_strings) + "</sst>")
    for _name, _sid, number, xml, sheet_rels in sheets:
        parts[f"xl/worksheets/sheet{number}.xml"] = xml
        if sheet_rels:
            body = "".join(f'<Relationship Id="{rid}" Type="{kind}" Target={quoteattr(target)}'
                           + (' TargetMode="External"' if external else "") + "/>"
                           for rid, kind, target, external in sheet_rels)
            parts[f"xl/worksheets/_rels/sheet{number}.xml.rels"] = f'{HEAD}<Relationships xmlns="{PKG}">{body}</Relationships>'
    for number, xml in tables.items():
        parts[f"xl/tables/table{number}.xml"] = xml
    for number, (xml, drawing) in drawings.items():
        parts[f"xl/drawings/drawing{number}.xml"] = xml
        parts[f"xl/drawings/_rels/drawing{number}.xml.rels"] = rels(*drawing.rels)
    for number, xml in charts.items():
        parts[f"xl/charts/chart{number}.xml"] = xml
    for name, data in media.files.items():
        parts[f"xl/media/{name}"] = data
    parts.update(extra_parts or {})
    return parts


ITEMS =[("Rent", 1200, 1250), ("Travel", 300, 280), ("Supplies", 200, 240)]


def clean_all_six():
    ##  No finding under any of the six rules and no limitation: every populated cell is inside
    ##  a formal table with a proper header, every colour is black or white, no merges, a
    ##  descriptive link, and every object has both alt-text fields.
    media = Media()
    budget = Drawing(media)
    budget_xml = drawing_xml(
        (picture(props(2, "Picture 1", "Team logo", "Team 12 logo placeholder."), budget.image("logo")), 2, 6),
        (shape(props(3, "Rectangle 2", "Budget note", "Callout noting that rent is the largest cost."),
               "Rent is the largest cost", fill="FFFFFF", line="000000"), 3, 4),
        (chart_frame(props(4, "Chart 3", "Costs by item", "Column chart: rent $1,200, travel $300, supplies $200."),
                     budget.chart(1)), 6, 14))
    budget_cells = {"A1": ("Item", HEADER), "B1": ("Amount", HEADER)}
    for row, (item, amount, _q2) in enumerate(ITEMS, start=2):
        budget_cells[f"A{row}"], budget_cells[f"B{row}"] = (item, TEXT), (amount, MONEY)
    sources_cells = {"A1": ("Source", HEADER), "B1": ("Notes", HEADER),
                     "A2": ("Team 12 budget guidance", TEXT), "B2": ("Figures are illustrative test data.", TEXT)}
    return package("Clean all-six fixture", [
        ("Budget", 1, 1, worksheet(budget_cells, widths=(22, 12), drawing="rId1", tables=("rId2",)),
         [("rId1", f"{REL}/drawing", "../drawings/drawing1.xml", False),
          ("rId2", f"{REL}/table", "../tables/table1.xml", False)]),
        ("Sources", 2, 2, worksheet(sources_cells, widths=(30, 40), links=(("A2", "rId1"),), tables=("rId2",)),
         [("rId1", HYPERLINK, "https://example.edu/team12/budget-guidance", True),
          ("rId2", f"{REL}/table", "../tables/table2.xml", False)]),
    ], {1: table(1, "BudgetItems", f"A1:B{len(ITEMS) + 1}", ["Item", "Amount"]),
        2: table(2, "Sources", "A1:B2", ["Source", "Notes"])},
        {1: (budget_xml, budget)}, {1: chart("Budget", "Costs by item")}, media)


def seeded_all_six(second_generic_sheet=False):
    ##  Every rule triggered at least once, user-input and manual items, one limitation, and a
    ##  target for each supported correction. See tester/fixtures/phase4/README.md.
    ##  second_generic_sheet adds Sheet2 (mixed_decisions), so two renames can conflict.
    media = Media()
    seeded = Drawing(media)
    seeded_xml = drawing_xml(
        (picture(props(2, "Picture 1", title="Logo"), seeded.image("logo")), 2, 6),                       # descr absent
        (picture(props(3, "Picture 2", decorative=True), seeded.image("divider")), 2, 6),                  # decorative
        (chart_frame(props(4, "Chart 3", "Costs by quarter", "Column chart of Q1 costs: rent $1,200, travel $300, "
                           "supplies $200."), seeded.chart(1)), 6, 14))                                     # complete
    sheet1 = {"A1": ("Item", HEADER), "B1": ("Q1", HEADER), "C1": ("Q2", HEADER)}
    for row, (item, q1, q2) in enumerate(ITEMS, start=2):
        sheet1[f"A{row}"], sheet1[f"B{row}"], sheet1[f"C{row}"] = (item, TEXT), (q1, MONEY), (q2, MONEY)
    sheet1.update({
        "E1": ("Notes", HEADER),                      # merged with F1
        "A7": ("click here", TEXT),                   # ambiguous link label
        "A9": ("Overdue", RED),                       # nonneutral colour, 3.9985:1
        "A11": ("Draft", GREY),                       # grey 999999 on white, 2.849:1
    })
    summary = {"A1": ("Item", TEXT), "B1": ("Total", TEXT),
               "A2": ("Rent", TEXT), "B2": ("=Sheet1!B2+Sheet1!C2", ITEMS[0][1] + ITEMS[0][2], MONEY),
               "A3": ("Travel", TEXT), "B3": ("=Sheet1!B3+Sheet1!C3", ITEMS[1][1] + ITEMS[1][2], MONEY)}
    sheets = [
        ("Sheet1", 1, 1, worksheet(sheet1, widths=(22, 12, 12, 4, 14, 14), merges=("E1:F1",),
                                   links=(("A7", "rId2"),), drawing="rId1"),
         [("rId1", f"{REL}/drawing", "../drawings/drawing1.xml", False),
          ("rId2", HYPERLINK, "https://example.edu/team12/budget-guidance", True)]),
        ("Summary", 2, 2, worksheet(summary, widths=(22, 12), tables=("rId1",)),
         [("rId1", f"{REL}/table", "../tables/table1.xml", False)]),
    ]
    tables = {1: table(1, "QuarterTotals", "A1:B3", ["Item", "Total"], header_row_count=0)}
    if second_generic_sheet:
        archive = {"A1": ("Year", HEADER), "B1": ("Total", HEADER), "A2": ("2025", TEXT), "B2": (1650, MONEY)}
        sheets.append(("Sheet2", 3, 3, worksheet(archive, widths=(12, 12), tables=("rId1",)),
                       [("rId1", f"{REL}/table", "../tables/table2.xml", False)]))
        tables[2] = table(2, "ArchiveTotals", "A1:B2", ["Year", "Total"])
    title = "Mixed decisions fixture" if second_generic_sheet else "Seeded all-six fixture"
    return package(title, sheets, tables, {1: (seeded_xml, seeded)}, {1: chart("Sheet1", "Costs by quarter")}, media)


def mixed_decisions():
    return seeded_all_six(second_generic_sheet=True)


def review_only():
    ##  Only manual findings: a decorative picture, a populated merge and a nonneutral colour.
    ##  No supported correction is advertised, so the audit is REVIEW_REQUIRED.
    media = Media()
    gallery = Drawing(media)
    gallery_xml = drawing_xml((picture(props(2, "Picture 1", decorative=True), gallery.image("divider")), 2, 6))
    cells = {"A1": ("Quarterly gallery", HEADER), "A3": ("Overdue", RED)}
    return package("Review only fixture", [
        ("Gallery", 1, 1, worksheet(cells, widths=(18, 12, 12), merges=("A1:C1",), drawing="rId1"),
         [("rId1", f"{REL}/drawing", "../drawings/drawing1.xml", False)]),
    ], {}, {1: (gallery_xml, gallery)}, {}, media)


def unsupported_edits():
    ##  An APPLY target for every manual kind: decorative object, duplicate-ID pair, colour cell,
    ##  populated merge, HYPERLINK formula, and a generic sheet whose rename is unsafe because
    ##  the workbook builds a reference with INDIRECT.
    media = Media()
    objects = Drawing(media)
    objects_xml = drawing_xml(
        (picture(props(2, "Picture 1", decorative=True), objects.image("divider")), 2, 6),
        (picture(props(3, "Picture 2", title="Receipt"), objects.image("receipt")), 2, 6),
        (picture(props(3, "Picture 3", title="Archive"), objects.image("archive")), 2, 6))
    sheet1 = {"A1": ("Item", HEADER), "B1": ("Note", HEADER),
              "A2": ("Rent", TEXT), "B2": ("Overdue", RED),
              "A3": ("Guidance", TEXT), "B3": ('=HYPERLINK("https://example.edu/team12","click here")', "click here", TEXT),
              "D1": ("Notes", HEADER)}
    summary = {"A1": ("Label", HEADER), "B1": ("Value", HEADER),
               "A2": ("Rent item", TEXT), "B2": ('=INDIRECT("Sheet1!A2")', "Rent", TEXT)}
    return package("Unsupported edits fixture", [
        ("Sheet1", 1, 1, worksheet(sheet1, widths=(18, 30, 4, 12, 12), merges=("D1:E1",), drawing="rId1",
                                   tables=("rId2",)),
         [("rId1", f"{REL}/drawing", "../drawings/drawing1.xml", False),
          ("rId2", f"{REL}/table", "../tables/table1.xml", False)]),
        ("Summary", 2, 2, worksheet(summary, widths=(18, 12), tables=("rId1",)),
         [("rId1", f"{REL}/table", "../tables/table2.xml", False)]),
    ], {1: table(1, "Items", "A1:B3", ["Item", "Note"]), 2: table(2, "Lookup", "A1:B2", ["Label", "Value"])},
        {1: (objects_xml, objects)}, {}, media)


VML = "urn:schemas-microsoft-com:vml"
PRINTER_SETTINGS = b"Team 12 opaque printer settings placeholder; must stay byte-identical.\x00\x01\x02" * 8


def preservation_rich():
    ##  One supported correction (alt text on Picture 1) amid everything spec 11 lists for the
    ##  semantic comparison: formulas and caches, styles and number formats, defined names, a
    ##  chart, media, a cell comment (comments part plus legacy VML), relationships, data
    ##  validation, bold-only conditional formatting, a hidden sheet, and an opaque untouched
    ##  printer-settings part.
    media = Media()
    budget = Drawing(media)
    budget_xml = drawing_xml(
        (picture(props(2, "Picture 1", title="Logo"), budget.image("logo")), 2, 6),
        (chart_frame(props(3, "Chart 2", "Costs by item", "Column chart: rent $1,200, travel $300, supplies $200."),
                     budget.chart(1)), 6, 14))
    cells = budget_table({"A5": ("Total", HEADER), "B5": ("=SUM(B2:B4)", 1700, MONEY)})
    comments = (f'{HEAD}<comments xmlns="{MAIN}"><authors><author>Team 12</author></authors><commentList>'
                '<comment ref="A2" authorId="0"><text><t>Rent includes utilities.</t></text></comment>'
                "</commentList></comments>")
    vml = ('<xml xmlns:v="urn:schemas-microsoft-com:vml" xmlns:o="urn:schemas-microsoft-com:office:office" '
           'xmlns:x="urn:schemas-microsoft-com:office:excel"><o:shapelayout v:ext="edit"><o:idmap v:ext="edit" data="1"/>'
           '</o:shapelayout><v:shapetype id="_x0000_t202" coordsize="21600,21600" o:spt="202" path="m,l,21600r21600,l21600,xe">'
           '<v:stroke joinstyle="miter"/><v:path gradientshapeok="t" o:connecttype="rect"/></v:shapetype>'
           '<v:shape id="_x0000_s1025" type="#_x0000_t202" style="position:absolute;margin-left:80pt;margin-top:2pt;'
           'width:108pt;height:59pt;z-index:1;visibility:hidden" fillcolor="#ffffe1" o:insetmode="auto">'
           '<v:fill color2="#ffffe1"/><v:shadow on="t" color="black" obscured="t"/><v:path o:connecttype="none"/>'
           '<v:textbox style="mso-direction-alt:auto"><div style="text-align:left"></div></v:textbox>'
           '<x:ClientData ObjectType="Note"><x:MoveWithCells/><x:SizeWithCells/><x:Anchor>1, 15, 0, 2, 3, 15, 3, 16'
           '</x:Anchor><x:AutoFill>False</x:AutoFill><x:Row>1</x:Row><x:Column>0</x:Column></x:ClientData></v:shape></xml>')
    hidden = {"A1": ("Code", HEADER), "B1": ("Rate", HEADER), "A2": ("MILE", TEXT), "B2": (0.67, TEXT)}
    return package("Preservation rich fixture", [
        ("Budget", 1, 1, worksheet(cells, widths=(22, 12, 4, 14), drawing="rId1", tables=("rId2",),
                                   conditional=(("B2:B4", "B2>1000", 0),), validations=(("D2", "$A$2:$A$4"),),
                                   page_setup="rId3", legacy_drawing="rId4"),
         [("rId1", f"{REL}/drawing", "../drawings/drawing1.xml", False),
          ("rId2", f"{REL}/table", "../tables/table1.xml", False),
          ("rId3", f"{REL}/printerSettings", "../printerSettings/printerSettings1.bin", False),
          ("rId4", f"{REL}/vmlDrawing", "../drawings/vmlDrawing1.vml", False),
          ("rId5", f"{REL}/comments", "../comments1.xml", False)]),
        ("Rates", 2, 2, worksheet(hidden, widths=(12, 12), tables=("rId1",)),
         [("rId1", f"{REL}/table", "../tables/table2.xml", False)]),
    ], {1: table(1, "BudgetItems", "A1:B5", ["Item", "Amount"]), 2: table(2, "Rates", "A1:B2", ["Code", "Rate"])},
        {1: (budget_xml, budget)}, {1: chart("Budget", "Costs by item")}, media,
        defined_names=(("BudgetTotal", "Budget!$B$5", None),), styles=STYLES_DXF, states={"Rates": "hidden"},
        extra_parts={"xl/comments1.xml": comments, "xl/drawings/vmlDrawing1.vml": vml,
                     "xl/printerSettings/printerSettings1.bin": PRINTER_SETTINGS},
        extra_types=(("Default", "vml", f"{CT}.vmlDrawing"), ("Default", "bin", f"{CT}.spreadsheetml.printerSettings"),
                     ("Override", "/xl/comments1.xml", f"{CT}.spreadsheetml.comments+xml")))


def large_image():
    ##  A deterministic 900 x 900 RGB PNG with stored (uncompressed) blocks: about 2.4 MB.
    from build_shared_fixtures import png
    return png(900, 900, lambda x, y: ((x * 7) % 256, (y * 5) % 256, ((x + y) * 3) % 256))


def large_preservation():
    ##  Over 2 MiB, so source and output downloads exceed the Phase 3 binary cap; one supported
    ##  alt-text correction produces an equally large output.
    media = Media()
    media.files["image1.png"] = large_image()
    photos = Drawing(media)
    rid = photos._rel("image", "../media/image1.png")
    photos_xml = drawing_xml((picture(props(2, "Picture 1", title="Site photo"), rid, cx=3657600, cy=3657600), 6, 20))
    return package("Large preservation fixture", [
        ("Photos", 1, 1, worksheet(budget_table(), widths=(22, 12), drawing="rId1", tables=("rId2",)),
         [("rId1", f"{REL}/drawing", "../drawings/drawing1.xml", False),
          ("rId2", f"{REL}/table", "../tables/table1.xml", False)]),
    ], {1: table(1, "BudgetItems", "A1:B4", ["Item", "Amount"])}, {1: (photos_xml, photos)}, {}, media)


def inactive_protection():
    ##  A stored sheet password with protection explicitly off (sheet="0"): not active
    ##  protection (spec 6), so it is accepted and audits clean.
    from build_shared_fixtures import protection_attrs
    lock =protection_attrs("", "inactive_protection") + ' sheet="0"'
    return package("Inactive protection fixture", [
        ("Budget", 1, 1, worksheet(budget_table(), widths=(22, 12), tables=("rId1",), protection=lock),
         [("rId1", f"{REL}/table", "../tables/table1.xml", False)]),
    ], {1: table(1, "BudgetItems", "A1:B4", ["Item", "Amount"])}, {}, {}, Media())


def two_by_two(first, second, value):
    return {"A1": (first, HEADER), "B1": (second, HEADER), "A2": ("Item", TEXT), "B2": (value, TEXT)}


def unicode_edges():
    ##  The Phase 3 unicode cases on a ruleset 2.0.0 clean background: each sheet's cells form a
    ##  formal table, all black on white. Same names, objects and expected ALT/name findings.
    media = Media()
    costs, summary, sales = Drawing(media), Drawing(media), Drawing(media)
    costs_xml = drawing_xml(
        (picture(props(2, "Picture 1", "Team logo", "​"), costs.image("logo")), 2, 6),
        (picture(props(3, "Picture 2", "  ", "Scanned receipt placeholder."), costs.image("receipt")), 2, 6),
        (shape(props(4, "Rectangle 3", "Totals", "\u0085  "), "Totals", fill="FFFFFF", line="000000"), 3, 4),
        (shape(props(5, "Rectangle 4", "東京オフィス", "Büro München: Übersicht der Kosten."), "東京",
               fill="FFFFFF", line="000000"), 3, 4),
        (picture(props(6, "Picture 5", "﻿", "Divider line placeholder."), costs.image("divider")), 2, 6),
        (picture(props(7, "Picture 6", "Chart icon", "\t\n\r "), costs.image("chart_icon")), 2, 6))
    summary_xml = drawing_xml((picture(props(2, "Picture 1", title="Chart icon"), summary.image("chart_icon")), 2, 6))
    sales_xml = drawing_xml((shape(props(2, "Rectangle 1", "Sales", ""), "Sales", fill="FFFFFF", line="000000"), 3, 4))
    names = ["Café costs", "　Sheet2　", "Sheet３", "ſheet4", "\U0001f4ca Summary",
             "ｾｰﾙｽ"]
    drawings_of = {0: 1, 4: 2, 5: 3}
    sheets, tables = [], {}
    for index, name in enumerate(names):
        number = index + 1
        rels_list = [("rId1", f"{REL}/table", f"../tables/table{number}.xml", False)]
        drawing = None
        if index in drawings_of:
            rels_list.append(("rId2", f"{REL}/drawing", f"../drawings/drawing{drawings_of[index]}.xml", False))
            drawing = "rId2"
        sheets.append((name, number, number, worksheet(two_by_two("Label", "Value", f"Row {number}"), widths=(18, 18),
                                                       drawing=drawing, tables=("rId1",)), rels_list))
        tables[number] = table(number, f"Table{number}", "A1:B2", ["Label", "Value"])
    return package("Unicode fixture (ruleset 2.0.0)", sheets, tables,
                   {1: (costs_xml, costs), 2: (summary_xml, summary), 3: (sales_xml, sales)}, {}, media)


def repeated_ids():
    ##  Spec 7.1's exact layout: two sibling twoCellAnchor elements whose pictures share cNvPr id 2
    ##  (both MANUAL_REVIEW at their pic paths), a unique shape missing its description, and the
    ##  same id 2 in another drawing part, which is not a repeat.
    media = Media()
    expenses, receipts = Drawing(media), Drawing(media)
    expenses_xml = drawing_xml(
        (picture(props(2, "Picture 1", title="Receipt"), expenses.image("receipt")), 2, 6),
        (picture(props(2, "Picture 2", "Team logo", "Team 12 logo placeholder."), expenses.image("logo")), 2, 6),
        (shape(props(3, "Rectangle 3", title="Totals"), "Totals", fill="FFFFFF", line="000000"), 3, 4))
    receipts_xml = drawing_xml((picture(props(2, "Picture 1", title="Archive"), receipts.image("archive")), 2, 6))
    return package("Repeated IDs fixture (ruleset 2.0.0)", [
        ("Expenses", 1, 1, worksheet(budget_table(), widths=(22, 12), drawing="rId1", tables=("rId2",)),
         [("rId1", f"{REL}/drawing", "../drawings/drawing1.xml", False),
          ("rId2", f"{REL}/table", "../tables/table1.xml", False)]),
        ("Receipts", 2, 2, worksheet(two_by_two("Receipt", "Amount", "Taxi"), widths=(18, 12), drawing="rId1",
                                     tables=("rId2",)),
         [("rId1", f"{REL}/drawing", "../drawings/drawing2.xml", False),
          ("rId2", f"{REL}/table", "../tables/table2.xml", False)]),
    ], {1: table(1, "ExpenseItems", "A1:B4", ["Item", "Amount"]), 2: table(2, "Receipts", "A1:B2", ["Receipt", "Amount"])},
        {1: (expenses_xml, expenses), 2: (receipts_xml, receipts)}, {}, media)


def multiple_drawings():
    ##  Four drawings on four sheets (hidden and veryHidden included), numbered out of sheet
    ##  order, IDs restarting in each part, one absolute relationship target; data in tables.
    media = Media()
    expenses, hidden, summary, archive = Drawing(media), Drawing(media), Drawing(media), Drawing(media)
    expenses_xml = drawing_xml(
        (picture(props(2, "Picture 1", "Receipt", "Scanned travel receipt placeholder."), expenses.image("receipt")), 2, 6),
        (shape(props(3, "Rectangle 2", descr="Callout noting that rent is the largest cost."), "Rent is the largest cost",
               fill="FFFFFF", line="000000"), 3, 4))
    hidden_xml = drawing_xml((picture(props(2, "Picture 1"), hidden.image("archive")), 2, 6))
    summary_xml = drawing_xml(
        (chart_frame(props(2, "Chart 1", "Costs by item", "Column chart: rent $1,200, travel $300, supplies $200."),
                     summary.chart(1)), 6, 14),
        (picture(props(3, "Picture 2", title="Team logo", descr=" "), summary.image("logo")), 2, 6))
    archive_xml = drawing_xml((picture(props(2, "Picture 1", title="Divider"), archive.image("divider")), 2, 6))

    def sheet(number, drawing_number, cells=None):
        rels_list = [("rId1", f"{REL}/table", f"../tables/table{number}.xml", False)]
        if drawing_number:
            rels_list.append(("rId2", f"{REL}/drawing", f"../drawings/drawing{drawing_number}.xml", False))
        xml = worksheet(cells or two_by_two("Label", "Value", f"Row {number}"), widths=(18, 18),
                        drawing="rId2" if drawing_number else None, tables=("rId1",))
        return xml, rels_list

    layout = [("Summary", 1, 3, budget_table()), ("Expenses", 2, 1, None), ("Hidden costs", 3, 2, None),
              ("Notes", 4, None, None), ("Archive", 5, 4, None)]
    sheets, tables = [], {}
    for name, number, drawing_number, cells in layout:
        xml, rels_list = sheet(number, drawing_number, cells)
        sheets.append((name, number, number, xml, rels_list))
        ref = "A1:B4" if cells else "A1:B2"
        tables[number] = table(number, f"Table{number}", ref, ["Item", "Amount"] if cells else ["Label", "Value"])
    parts = package("Multiple drawings fixture (ruleset 2.0.0)", sheets, tables,
                    {1: (expenses_xml, expenses), 2: (hidden_xml, hidden), 3: (summary_xml, summary),
                     4: (archive_xml, archive)}, {1: chart("Summary", "Costs by item")}, media,
                    states={"Hidden costs": "hidden", "Archive": "veryHidden"})
    archive_rels = "xl/worksheets/_rels/sheet5.xml.rels"
    parts[archive_rels] = parts[archive_rels].replace('"../drawings/drawing4.xml"', '"/xl/drawings/drawing4.xml"')
    return parts


##  ---- Correction fixtures: each is clean under all six rules except its correction targets ----

##  A bold-only differential format: conditional formatting with no colour change (spec §7.7).
STYLES_DXF = STYLES.replace("</styleSheet>", '<dxfs count="1"><dxf><font><b/></font></dxf></dxfs></styleSheet>')


def connector(cnvpr, x=0, y=0, cx=1828800, cy=0):
    return (f'<xdr:cxnSp macro=""><xdr:nvCxnSpPr>{cnvpr}<xdr:cNvCxnSpPr/></xdr:nvCxnSpPr><xdr:spPr>'
            f'<a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'
            f'<a:prstGeom prst="straightConnector1"><a:avLst/></a:prstGeom><a:ln w="19050"><a:solidFill>'
            f'<a:srgbClr val="000000"/></a:solidFill><a:tailEnd type="triangle"/></a:ln></xdr:spPr></xdr:cxnSp>')


def text_box(cnvpr, label):
    return shape(cnvpr, label, fill="FFFFFF", line="000000").replace("<xdr:cNvSpPr/>", '<xdr:cNvSpPr txBox="1"/>', 1)


def budget_table(sheet_cells=None):
    ##  Item / Amount over A1:B4, the rows the shared chart helper plots.
    cells = {"A1": ("Item", HEADER), "B1": ("Amount", HEADER)}
    for row, (item, amount, _q2) in enumerate(ITEMS, start=2):
        cells[f"A{row}"], cells[f"B{row}"] = (item, TEXT), (amount, MONEY)
    return {**cells, **(sheet_cells or {})}


def alt_supported():
    ##  One of each eligible object type missing alt text (§8.3), plus a complete group whose
    ##  structure a correction must preserve.
    media = Media()
    budget = Drawing(media)
    budget_xml = drawing_xml(
        (picture(props(2, "Picture 1", title="Logo"), budget.image("logo")), 2, 6),                       # descr absent
        (chart_frame(props(3, "Chart 2"), budget.chart(1)), 6, 14),                                         # both absent
        (shape(props(4, "Rectangle 3", title="", descr="Callout noting that rent is the largest cost."),
               "Rent is the largest cost", fill="FFFFFF", line="000000"), 3, 4),                            # title empty
        (connector(props(5, "Straight Arrow Connector 4")), 3, 1),                                          # both absent
        (text_box(props(6, "TextBox 5", title="Instructions"), "Amounts are in US dollars."), 3, 3),       # descr absent
        (group(props(7, "Group 6", "Receipt and total", "Receipt image beside the total label."), 2743200, 914400,
               picture(props(8, "Picture 7", "Receipt", "Scanned travel receipt placeholder."),
                       budget.image("receipt"), 0, 0, 914400, 914400),
               shape(props(9, "Rectangle 8", "Total label", "Label reading Total $1,700."), "Total $1,700",
                     "rect", "FFFFFF", "000000", 1097280, 76200, 1645920, 762000)), 5, 5))
    return package("Alt text correction fixture", [
        ("Budget", 1, 1, worksheet(budget_table(), widths=(22, 12), drawing="rId1", tables=("rId2",)),
         [("rId1", f"{REL}/drawing", "../drawings/drawing1.xml", False),
          ("rId2", f"{REL}/table", "../tables/table1.xml", False)]),
    ], {1: table(1, "BudgetItems", "A1:B4", ["Item", "Amount"])}, {1: (budget_xml, budget)},
        {1: chart("Budget", "Costs by item")}, media)


def rename_references():
    ##  Sheet1 is renamed; every supported reference kind points at it, alongside references to
    ##  similar names and an apostrophe name, a string literal and plain text that must not change.
    media = Media()
    costs = Drawing(media)
    costs_xml = drawing_xml(
        (chart_frame(props(2, "Chart 1", "Costs by item", "Column chart: rent $1,200, travel $300, supplies $200."),
                     costs.chart(1)), 6, 14))
    summary = {
        "A1": ("Label", HEADER), "B1": ("Value", HEADER),
        "A2": ("Total", TEXT), "B2": ("=SUM(Sheet1!B2:B4)", 1700, MONEY),
        "A3": ("Rent plus note", TEXT), "B3": ("='Sheet1'!B2+'Bob''s Notes'!B2", 1250, MONEY),
        "A4": ("Old rent plus travel", TEXT), "B4": ("='Sheet1 (old)'!B2+Sheet1!$B$3", 1400, MONEY),
        "A5": ("Literal", TEXT), "B5": ('="Sheet1!B2 is rent"', "Sheet1!B2 is rent", TEXT),
        "A6": ("Sheet1", TEXT), "B6": ("Plain text, not a reference", TEXT),
        "A7": ("Go to quarterly costs", TEXT),
    }
    return package("Rename references fixture", [
        ("Sheet1", 1, 1, worksheet(budget_table(), widths=(22, 12), drawing="rId1", tables=("rId2",)),
         [("rId1", f"{REL}/drawing", "../drawings/drawing1.xml", False),
          ("rId2", f"{REL}/table", "../tables/table1.xml", False)]),
        ("Summary", 2, 2, worksheet(summary, widths=(24, 30, 4, 14), tables=("rId1",),
                                    conditional=(("B2:B4", "Sheet1!$B$2>1000", 0),),
                                    validations=(("D2", "Sheet1!$A$2:$A$4"),),
                                    links=(("A7", None, "Sheet1!A1", None),)),
         [("rId1", f"{REL}/table", "../tables/table2.xml", False)]),
        ("Bob's Notes", 3, 3, worksheet({"A1": ("Note", HEADER), "B1": ("Value", HEADER), "A2": ("Deposit", TEXT),
                                          "B2": (50, MONEY)}, widths=(18, 12), tables=("rId1",)),
         [("rId1", f"{REL}/table", "../tables/table3.xml", False)]),
        ("Sheet1 (old)", 4, 4, worksheet({"A1": ("Item", HEADER), "B1": ("Amount", HEADER), "A2": ("Rent", TEXT),
                                           "B2": (1100, MONEY)}, widths=(18, 12), tables=("rId1",)),
         [("rId1", f"{REL}/table", "../tables/table4.xml", False)]),
    ], {1: table(1, "CostItems", "A1:B4", ["Item", "Amount"]), 2: table(2, "SummaryRows", "A1:B7", ["Label", "Value"]),
        3: table(3, "BobNotes", "A1:B2", ["Note", "Value"]), 4: table(4, "OldCosts", "A1:B2", ["Item", "Amount"])},
        {1: (costs_xml, costs)}, {1: chart("Sheet1", "Costs by item")}, media,
        defined_names=(("LocalRent", "Sheet1!$B$2", 1), ("Totals", "Sheet1!$B$2:$B$4", None)), styles=STYLES_DXF)


def link_supported():
    ##  Two ambiguous simple links: one shared string reused by a plain cell, one inline string
    ##  whose approved label starts with "=". A descriptive link must stay unflagged.
    cells = {"A1": ("Resource", HEADER), "B1": ("Notes", HEADER),
             "A2": (Shared(0), TEXT), "B2": (Shared(0), TEXT),
             "A3": ("here", TEXT), "B3": ("Board minutes", TEXT),
             "A4": ("Annual accessibility report", TEXT), "B4": ("Published each June.", TEXT)}
    return package("Link label correction fixture", [
        ("Resources", 1, 1, worksheet(cells, widths=(30, 24), tables=("rId4",),
                                      links=(("A2", "rId1", None, "click here"), ("A3", "rId2"), ("A4", "rId3"))),
         [("rId1", HYPERLINK, "https://example.edu/team12/budget-guidance", True),
          ("rId2", HYPERLINK, "https://example.edu/team12/board-minutes", True),
          ("rId3", HYPERLINK, "https://example.edu/team12/accessibility-report", True),
          ("rId4", f"{REL}/table", "../tables/table1.xml", False)]),
    ], {1: table(1, "Resources", "A1:B4", ["Resource", "Notes"])}, {}, {}, Media(), shared_strings=["click here"])


def header_range():
    ##  A dense unstructured block on a sheet with no relationships yet, a formal table 1
    ##  elsewhere, and a defined name that takes the first candidate table name.
    costs = {"A1": ("Item", HEADER), "B1": ("Q1", HEADER), "C1": ("Q2", HEADER), "D1": ("Total", HEADER)}
    for row, (item, q1, q2) in enumerate(ITEMS, start=2):
        costs.update({f"A{row}": (item, TEXT), f"B{row}": (q1, MONEY), f"C{row}": (q2, MONEY),
                      f"D{row}": (f"=B{row}+C{row}", q1 + q2, MONEY)})
    rates = {"A1": ("Rate", HEADER), "B1": ("Value", HEADER), "A2": ("Mileage", TEXT), "B2": (0.67, TEXT)}
    return package("Header range correction fixture", [
        ("Costs", 1, 1, worksheet(costs, widths=(18, 12, 12, 12)), []),
        ("Reference", 2, 2, worksheet(rates, widths=(18, 12), tables=("rId1",)),
         [("rId1", f"{REL}/table", "../tables/table1.xml", False)]),
    ], {1: table(1, "Rates", "A1:B2", ["Rate", "Value"])}, {}, {}, Media(),
        defined_names=(("A11yTable2", "Reference!$B$2", None),))


def header_disabled_table():
    ##  An existing table with its header row switched off, whose first row already matches its
    ##  column names; a second, ordinary table must be left alone.
    ledger = {"A1": ("Item", TEXT), "B1": ("Amount", TEXT), "C1": ("Running total", TEXT),
              "A2": ("Rent", TEXT), "B2": (1200, MONEY), "C2": ("=B2", 1200, MONEY),
              "A3": ("Travel", TEXT), "B3": (300, MONEY), "C3": ("=C2+B3", 1500, MONEY),
              "A4": ("Supplies", TEXT), "B4": (200, MONEY), "C4": ("=C3+B4", 1700, MONEY)}
    archive = {"A1": ("Year", HEADER), "B1": ("Total", HEADER), "A2": ("2025", TEXT), "B2": (1650, MONEY)}
    return package("Disabled header correction fixture", [
        ("Ledger", 1, 1, worksheet(ledger, widths=(18, 12, 16), tables=("rId1",)),
         [("rId1", f"{REL}/table", "../tables/table1.xml", False)]),
        ("Archive", 2, 2, worksheet(archive, widths=(12, 12), tables=("rId1",)),
         [("rId1", f"{REL}/table", "../tables/table2.xml", False)]),
    ], {1: table(1, "Ledger", "A1:C4", ["Item", "Amount", "Running total"], header_row_count=0),
        2: table(2, "Archive", "A1:B2", ["Year", "Total"])}, {}, {}, Media())


##  ---- Vector fixtures: each P4-RULE-* case owns its own sheets or targets ----

def _sheets(spec):
    ##  spec: [(name, cells, worksheet kwargs, tables [(number, xml)])] -> (sheets, tables)
    sheets, tables = [], {}
    for number, (name, cells, kwargs, sheet_tables) in enumerate(spec, start=1):
        rels_list = [(f"rId{i}", f"{REL}/table", f"../tables/table{n}.xml", False)
                     for i, (n, _xml) in enumerate(sheet_tables, start=1)]
        rels_list += kwargs.pop("extra_rels", [])
        tables.update(dict(sheet_tables))
        sheets.append((name, number, number, worksheet(cells, tables=tuple(r[0] for r in rels_list[:len(sheet_tables)]),
                                                       **kwargs), rels_list))
    return sheets, tables


def table_header_vectors():
    ##  P4-RULE-HEADER-{DECLARED,BLANK,DUPLICATE,FORMULA,SPARSE,TITLE-LIST,HIDDEN}, one sheet each.
    ##  Excel repairs tables 3 (Blank) and 4 (Duplicate) on open: states it cannot store, kept on
    ##  purpose because spec 7.4 requires them to be flagged (see the pack README).
    def grid(first, second, rows=(("Ada", 9), ("Lin", 7))):
        cells = {"A1": first, "B1": second}
        for r, (a, b) in enumerate(rows, start=2):
            cells[f"A{r}"], cells[f"B{r}"] = (a, TEXT), (b, TEXT)
        return cells
    declared = grid(("Name", HEADER), ("Score", HEADER))
    declared.update({"D1": ("Item", HEADER), "E1": ("Qty", HEADER), "D2": ("Pens", TEXT), "E2": (4, TEXT),
                     "D3": ("Pads", TEXT), "E3": (2, TEXT)})
    sheets, tables = _sheets([
        ("Declared", declared, {"widths": (12, 10, 4, 12, 10)},
         [(1, table(1, "Scores", "A1:B3", ["Name", "Score"])), (2, table(2, "Stock", "D1:E3", ["Item", "Qty"], 1))]),
        ("Blank", {k: v for k, v in grid(("Name", HEADER), ("", HEADER)).items() if k != "B1"}, {"widths": (12, 10)},
         [(3, table(3, "BlankHeader", "A1:B3", ["Name", "Column2"]))]),
        ("Duplicate", grid(("Name", HEADER), ("name ", HEADER)), {"widths": (12, 10)},
         [(4, table(4, "DuplicateHeader", "A1:B3", ["Name", "name "]))]),
        ("Formula", grid(("Name", HEADER), ('="Score"', "Score", HEADER)), {"widths": (12, 10)},
         [(5, table(5, "FormulaHeader", "A1:B3", ["Name", "Score"]))]),
        ("Sparse", {"A1": ("Name", HEADER), "B1": ("Score", HEADER), "A2": ("Ada", TEXT),
                    "D4": ("Name", HEADER), "E5": (9, TEXT)}, {"widths": (12, 10, 4, 12, 10)}, []),
        ("Lists", {"A1": ("Q1", HEADER), "B1": ("Q2", HEADER), "C1": ("Q3", HEADER), "E1": ("Rent", TEXT),
                   "E2": ("Travel", TEXT), "E3": ("Supplies", TEXT), "G5": ("Quarterly notes", HEADER)},
         {"widths": (8, 8, 8, 4, 12, 4, 18)}, []),
        ("Hidden tables", grid(("Name", TEXT), ("Score", TEXT)), {"widths": (12, 10)},
         [(6, table(6, "HiddenScores", "A1:B3", ["Name", "Score"], 0))]),
    ])
    return package("Table header vectors", sheets, tables, {}, {}, Media(), states={"Hidden tables": "hidden"})


def merge_vectors():
    ##  P4-RULE-MERGE-POPULATED and -EMPTY: two populated merges (one a title) and two that are
    ##  empty or formatting-only.
    cells = {"A1": ("Quarterly summary", HEADER), "B3": (42, TEXT)}
    xml = worksheet(cells, widths=(12, 10, 10, 10, 4, 10, 10), merges=("A1:D1", "B3:C4", "F1:G1", "F3:G3"))
    ##  F3:G3 is formatting-only: styled cells with no value, appended to row 3.
    xml = re.sub(r'(<row r="3">)(.*?)(</row>)', lambda m: m[1] + m[2] + '<c r="F3" s="1"/><c r="G3" s="1"/>' + m[3], xml, 1)
    return package("Merge vectors", [("Merges", 1, 1, xml, [])], {}, {}, {}, Media())


def link_vectors():
    ##  P4-RULE-LINK-{GENERIC,RAW-ADDRESS,CELL-DISPLAY,FORMULA-LITERAL,FORMULA-DYNAMIC,RANGE-DUPLICATE}
    ##  in one formal table; spec 7.6 vocabulary and the policy label vectors.
    rows = [("A2", " click HERE! ", "https://example.edu/a", None), ("A3", "Read more.", "https://example.edu/b", None),
            ("A4", "Learn   more?", "https://example.edu/c", None),
            ("A5", "Annual accessibility report", "https://example.edu/report", None),
            ("A6", "https://example.edu/d", "https://other.example.edu/d", None),
            ("A7", "www.example.edu", "https://example.edu", None),
            ("A8", "mailto:staff@example.edu", "mailto:staff@example.edu", None),
            ("A9", "example.edu", "example.edu", None),
            ("A10", "click here", "https://example.edu/e", "Annual report")]
    cells = {"A1": ("Label", HEADER), "B1": ("Kind", HEADER)}
    links, rels_list = [], []
    for i, (ref, label, target, display) in enumerate(rows, start=1):
        cells[ref], cells["B" + ref[1:]] = (label, TEXT), ("simple link", TEXT)
        links.append((ref, f"rId{i + 1}", None, display))
        rels_list.append((f"rId{i + 1}", HYPERLINK, target, True))
    cells.update({
        "A11": ('=HYPERLINK("https://example.edu/f","here")', "here", TEXT), "B11": ("formula, two literals", TEXT),
        "A12": ('=HYPERLINK("https://example.edu/g")', "https://example.edu/g", TEXT), "B12": ("formula, one literal", TEXT),
        "A13": ('=HYPERLINK(B13,"link")', "link", TEXT), "B13": ("https://example.edu/h", TEXT),
        "A14": ("Board minutes", TEXT), "B14": ("range link", TEXT),
        "A15": ("Policy page", TEXT), "B15": ("duplicate links", TEXT)})
    n = len(rows) + 2
    links += [("A14:B14", f"rId{n}", None, None), ("A15", f"rId{n + 1}", None, None), ("A15", f"rId{n + 2}", None, None)]
    rels_list += [(f"rId{n}", HYPERLINK, "https://example.edu/minutes", True),
                  (f"rId{n + 1}", HYPERLINK, "https://example.edu/policy", True),
                  (f"rId{n + 2}", HYPERLINK, "https://example.edu/policy-archive", True)]
    xml = worksheet(cells, widths=(30, 24), links=links, tables=("rId1",))
    return package("Link vectors", [("Links", 1, 1, xml, [("rId1", f"{REL}/table", "../tables/table1.xml", False)] + rels_list)],
                   {1: table(1, "LinkVectors", "A1:B15", ["Label", "Kind"])}, {}, {}, Media())


THEME = (
    f'{HEAD}<a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" name="Team 12 vectors">'
    '<a:themeElements><a:clrScheme name="Team 12"><a:dk1><a:sysClr val="windowText" lastClr="000000"/></a:dk1>'
    '<a:lt1><a:sysClr val="window" lastClr="FFFFFF"/></a:lt1><a:dk2><a:srgbClr val="1F497D"/></a:dk2>'
    '<a:lt2><a:srgbClr val="EEECE1"/></a:lt2><a:accent1><a:srgbClr val="336699"/></a:accent1>'
    '<a:accent2><a:srgbClr val="C0504D"/></a:accent2><a:accent3><a:srgbClr val="9BBB59"/></a:accent3>'
    '<a:accent4><a:srgbClr val="8064A2"/></a:accent4><a:accent5><a:srgbClr val="4BACC6"/></a:accent5>'
    '<a:accent6><a:srgbClr val="F79646"/></a:accent6><a:hlink><a:srgbClr val="0000FF"/></a:hlink>'
    '<a:folHlink><a:srgbClr val="800080"/></a:folHlink></a:clrScheme>'
    '<a:fontScheme name="Office"><a:majorFont><a:latin typeface="Cambria"/><a:ea typeface=""/><a:cs typeface=""/>'
    '</a:majorFont><a:minorFont><a:latin typeface="Calibri"/><a:ea typeface=""/><a:cs typeface=""/></a:minorFont>'
    '</a:fontScheme><a:fmtScheme name="Office"><a:fillStyleLst>'
    + '<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>' * 3 + '</a:fillStyleLst><a:lnStyleLst>'
    + '<a:ln w="9525"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln>' * 3
    + '</a:lnStyleLst><a:effectStyleLst>' + '<a:effectStyle><a:effectLst/></a:effectStyle>' * 3
    + '</a:effectStyleLst><a:bgFillStyleLst>' + '<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>' * 3
    + '</a:bgFillStyleLst></a:fmtScheme></a:themeElements><a:objectDefaults/><a:extraClrSchemeLst/></a:theme>')


def contrast_styles():
    ##  Fonts and fills for the colour vectors; cellXf i uses FONTS[i] and its fill. xf 0 is
    ##  deliberately the default with no font colour and no fill (the display assumption).
    import json as _json
    palette = _json.loads((ROOT / "ref" / "Phase4_Agent_Context_Pack" / "phase4-policy-vectors.json")
                          .read_text(encoding="utf-8"))["default_indexed_rgb"]
    palette = list(palette)
    palette[10] = "000000"                    # the workbook palette overrides index 10 (red) with black
    fonts = ['<sz val="11"/><name val="Calibri"/>',
             '<sz val="11"/><color rgb="FF333333"/><name val="Calibri"/>',
             '<sz val="11"/><color rgb="FF777777"/><name val="Calibri"/>',
             '<sz val="11"/><color rgb="FF767676"/><name val="Calibri"/>',
             '<sz val="18"/><color rgb="FF959595"/><name val="Calibri"/>',
             '<sz val="18"/><color rgb="FF949494"/><name val="Calibri"/>',
             '<b/><sz val="14"/><color rgb="FF949494"/><name val="Calibri"/>',
             '<sz val="14"/><color rgb="FF949494"/><name val="Calibri"/>',
             '<sz val="11"/><color theme="4" tint="-1"/><name val="Calibri"/>',
             '<sz val="11"/><color theme="4" tint="0.5"/><name val="Calibri"/>',
             '<sz val="11"/><color theme="1" tint="0.5"/><name val="Calibri"/>',
             '<sz val="11"/><color theme="1" tint="0.25"/><name val="Calibri"/>',
             '<sz val="11"/><color indexed="10"/><name val="Calibri"/>',
             '<sz val="11"/><color indexed="12"/><name val="Calibri"/>',
             '<sz val="11"/><color rgb="FF0000FF"/><name val="Calibri"/>',
             '<sz val="11"/><color rgb="FF000000"/><name val="Calibri"/>']
    fills = ['<patternFill patternType="none"/>', '<patternFill patternType="gray125"/>',
             '<patternFill patternType="solid"><fgColor rgb="FFFFFFFF"/><bgColor indexed="64"/></patternFill>',
             '<patternFill patternType="solid"><fgColor rgb="FFFFFF00"/><bgColor indexed="64"/></patternFill>',
             '<gradientFill degree="90"><stop position="0"><color rgb="FFFFFFFF"/></stop>'
             '<stop position="1"><color rgb="FFC0C0C0"/></stop></gradientFill>',
             '<patternFill patternType="darkGray"><fgColor rgb="FF000000"/><bgColor rgb="FFFFFFFF"/></patternFill>']
    ##  (font, fill) per cellXf index
    xfs = [(0, 0)] + [(i, 2) for i in range(1, 15)] + [(15, 3), (15, 4), (15, 5), (15, 2)]
    return (f'{HEAD}<styleSheet xmlns="{MAIN}"><fonts count="{len(fonts)}">'
            + "".join(f"<font>{f}</font>" for f in fonts) + f'</fonts><fills count="{len(fills)}">'
            + "".join(f"<fill>{f}</fill>" for f in fills)
            + '</fills><borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
            '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
            f'<cellXfs count="{len(xfs)}">' + "".join(
                f'<xf numFmtId="0" fontId="{font}" fillId="{fill}" borderId="0" xfId="0"'
                + ("" if i == 0 else ' applyFont="1" applyFill="1"') + "/>" for i, (font, fill) in enumerate(xfs))
            + '</cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
            '<dxfs count="1"><dxf><fill><patternFill patternType="solid"><bgColor rgb="FFFFC7CE"/></patternFill></fill>'
            '</dxf></dxfs><colors><indexedColors>' + "".join(f'<rgbColor rgb="FF{c}"/>' for c in palette)
            + "</indexedColors></colors></styleSheet>")


##  cellXf indices in contrast_styles()
(DEFAULT, C333, C777, C767, L959, L949, B949, M949, T_NEG, T_POS, D_HALF, D_QUARTER, IDX10, IDX12, BLUE,
 YELLOW, GRADIENT, PATTERN, BLACK) = range(19)


def contrast_vectors():
    ##  P4-RULE-COLOR-{DEFAULT,LOW-CONTRAST,LARGE-TEXT,BOUNDARY,THEME-TINT,INDEXED,MEANING,
    ##  CONDITIONAL,UNSUPPORTED,HIDDEN}. Cells sit in column A on odd rows (or alone), so no two
    ##  cells touch and no table candidate forms.
    black = '<color rgb="FF000000"/><sz val="11"/><rFont val="Calibri"/>'
    red = '<color rgb="FFFF0000"/><sz val="11"/><rFont val="Calibri"/>'
    sheets, tables = _sheets([
        ("Default", {"A1": ("Default text", DEFAULT), "A3": ("Dark grey text", C333)}, {"widths": (24,)}, []),
        ("Contrast", {"A1": ("Grey 777777", C777), "A3": ("Grey 767676", C767)}, {"widths": (24,)}, []),
        ("Large", {"A1": ("18 pt 959595", L959), "A3": ("18 pt 949494", L949), "A5": ("14 pt bold 949494", B949),
                   "A7": ("14 pt 949494", M949)}, {"widths": (24,)}, []),
        ("Theme", {"A1": ("accent1 tint -1", T_NEG), "A3": ("accent1 tint 0.5", T_POS),
                   "A5": ("dk1 tint 0.5", D_HALF), "A7": ("dk1 tint 0.25", D_QUARTER)}, {"widths": (24,)}, []),
        ("Indexed", {"A1": ("indexed 10 (palette black)", IDX10), "A3": ("indexed 12 (blue)", IDX12)},
         {"widths": (28,)}, []),
        ("Meaning", {"A1": ("Blue text", BLUE), "A3": ("Yellow fill", YELLOW)}, {"widths": (24,)}, []),
        ("Conditional", {"A1": ("Inside one", BLACK), "A2": ("Inside grey", C777), "A3": ("Inside three", BLACK),
                         "A5": ("Outside grey", C777)}, {"widths": (24,), "conditional": (("A1:A3", "LEN(A1)>3", 0),)}, []),
        ("Unsupported", {"A1": ("Gradient fill", GRADIENT), "A3": ("Pattern fill", PATTERN),
                         "A5": (Rich(("Due ", black), ("today", red)), BLACK)}, {"widths": (24,)}, []),
        ("Overlay", {"A1": ("Name", BLACK), "B1": ("Score", BLACK), "A2": ("Ada", BLACK), "B2": (9, BLACK)},
         {"widths": (12, 10)}, [(1, table(1, "StyledScores", "A1:B2", ["Name", "Score"], style="TableStyleMedium2"))]),
        ("Hidden cells", {"A1": ("Visible black", BLACK), "A3": ("Hidden row grey", C777), "C1": ("Hidden column grey", C777)},
         {"widths": (24, 4, 24), "hidden_rows": (3,), "hidden_cols": (3,)}, []),
    ])
    return package("Contrast vectors", sheets, tables, {}, {}, Media(), styles=contrast_styles(), theme=THEME)


FIXTURES = {"clean_all_six": clean_all_six, "seeded_all_six": seeded_all_six, "alt_supported": alt_supported,
            "rename_references": rename_references, "link_supported": link_supported, "header_range": header_range,
            "header_disabled_table": header_disabled_table, "mixed_decisions": mixed_decisions,
            "review_only": review_only, "unsupported_edits": unsupported_edits,
            "preservation_rich": preservation_rich, "large_preservation": large_preservation,
            "inactive_protection": inactive_protection, "unicode": unicode_edges, "repeated_ids": repeated_ids,
            "multiple_drawings": multiple_drawings, "table_header_vectors": table_header_vectors,
            "merge_vectors": merge_vectors, "link_vectors": link_vectors, "contrast_vectors": contrast_vectors}
##  Rejected inputs are format-level and unchanged by ruleset 2.0.0: the Phase 3 files are copied.
COPIED = ["corrupt", "zip_traversal", "zip_duplicate", "xml_dtd", "macro_parts", "encrypted_zip", "protected_sheet",
          "protected_structure"]


def build():
    files = {f"{key}.xlsx": zipped(make()) for key, make in FIXTURES.items()}
    files.update({f"{key}.xlsx": (ROOT / "tester" / "fixtures" / "shared" / f"{key}.xlsx").read_bytes() for key in COPIED})
    return files


def main(argv):
    files = build()
    if "--check" in argv:
        stale = [name for name, data in files.items() if not (OUT / name).exists() or (OUT / name).read_bytes() != data]
        if stale:
            print("Committed fixtures differ from the builder: " + ", ".join(stale))
            return 1
        print("Committed fixtures match the builder.")
        return 0
    OUT.mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        (OUT / name).write_bytes(data)
        print(f"wrote {OUT / name} ({len(data)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
