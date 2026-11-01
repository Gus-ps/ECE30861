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


def worksheet(cells, *, widths=(), merges=(), links=(), drawing=None, tables=(), conditional=(), validations=()):
    ##  cells: {ref: (value, style)} or {ref: ("=formula", cached value, style)}. Strings are
    ##  inline strings unless given as Shared(index). links: [(ref, rId)] for external links or
    ##  [(ref, None, location, display)] for internal ones; conditional: [(sqref, formula, dxfId)];
    ##  validations: [(sqref, list formula)]; drawing / tables: relationship IDs. Elements follow
    ##  the CT_Worksheet order.
    def cell(ref, spec):
        value, style = spec[0], spec[-1]
        if isinstance(value, Shared):
            return f'<c r="{ref}" s="{style}" t="s"><v>{value.index}</v></c>'
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
    data = "".join(f'<row r="{r}">{"".join(row)}</row>' for r, row in sorted(rows.items()))
    cols = "".join(f'<col min="{i}" max="{i}" width="{w}" customWidth="1"/>' for i, w in enumerate(widths, start=1))
    xml = f'{HEAD}<worksheet xmlns="{MAIN}" xmlns:r="{REL}">' + (f"<cols>{cols}</cols>" if cols else "")
    xml += f"<sheetData>{data}</sheetData>"
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
    if drawing:
        xml += f'<drawing r:id="{drawing}"/>'
    if tables:
        xml += f'<tableParts count="{len(tables)}">' + "".join(f'<tablePart r:id="{t}"/>' for t in tables) + "</tableParts>"
    return xml + "</worksheet>"


def table(table_id, name, ref, columns, header_row_count=None):
    ##  A minimal formal table: no filter, no style overlay, no totals row.
    header = "" if header_row_count is None else f' headerRowCount="{header_row_count}"'
    cols = "".join(f'<tableColumn id="{i}" name={quoteattr(c)}/>' for i, c in enumerate(columns, start=1))
    return (f'{HEAD}<table xmlns="{MAIN}" id="{table_id}" name="{name}" displayName="{name}" ref="{ref}"{header}>'
            f'<tableColumns count="{len(columns)}">{cols}</tableColumns></table>')


##  ---- Package ----

def package(title, sheets, tables, drawings, charts, media, defined_names=(), shared_strings=None, styles=STYLES):
    ##  sheets: [(name, sheetId, part number, worksheet xml, [(rId, type, target, external?)])]
    ##  tables: {number: xml}; drawings: {number: (xml, Drawing)}; charts: {number: xml};
    ##  defined_names: [(name, formula, local sheet index or None)]; shared_strings: [text]
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
        workbook_rels.append((f"rId{len(sheets) + 2}", f"{REL}/sharedStrings", "sharedStrings.xml"))
    types = ('<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
             '<Default Extension="xml" ContentType="application/xml"/><Default Extension="png" ContentType="image/png"/>'
             '<Default Extension="jpeg" ContentType="image/jpeg"/>'
             + "".join(f'<Override PartName="{p}" ContentType="{t}"/>' for p, t in overrides))
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
                                f'<sheet name={quoteattr(name)} sheetId="{sid}" r:id="rId{i + 1}"/>'
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
    return parts


ITEMS = [("Rent", 1200, 1250), ("Travel", 300, 280), ("Supplies", 200, 240)]


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


def seeded_all_six():
    ##  Every rule triggered at least once, user-input and manual items, one limitation, and a
    ##  target for each supported correction. See tester/fixtures/phase4/README.md.
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
    return package("Seeded all-six fixture", [
        ("Sheet1", 1, 1, worksheet(sheet1, widths=(22, 12, 12, 4, 14, 14), merges=("E1:F1",),
                                   links=(("A7", "rId2"),), drawing="rId1"),
         [("rId1", f"{REL}/drawing", "../drawings/drawing1.xml", False),
          ("rId2", HYPERLINK, "https://example.edu/team12/budget-guidance", True)]),
        ("Summary", 2, 2, worksheet(summary, widths=(22, 12), tables=("rId1",)),
         [("rId1", f"{REL}/table", "../tables/table1.xml", False)]),
    ], {1: table(1, "QuarterTotals", "A1:B3", ["Item", "Total"], header_row_count=0)},
        {1: (seeded_xml, seeded)}, {1: chart("Sheet1", "Costs by quarter")}, media)


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


FIXTURES = {"clean_all_six": clean_all_six, "seeded_all_six": seeded_all_six, "alt_supported": alt_supported,
            "rename_references": rename_references, "link_supported": link_supported, "header_range": header_range,
            "header_disabled_table": header_disabled_table}


def build():
    return {f"{key}.xlsx": zipped(make()) for key, make in FIXTURES.items()}


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
