"""Builds Team 12's shared Phase 3 fixtures: clean.xlsx, seeded_issues.xlsx, corrupt.xlsx.

Every part is written by hand so each object and attribute is deliberate.
Entries are stored uncompressed with fixed timestamps, so the bytes (and the
SHA256 values in tester/fixtures/shared/expectations.json) are reproducible.

Pictures use generated placeholders unless a replacement image exists in
scripts/fixture_images/ named after the picture key (logo, chart_icon,
divider, totals_icon, receipt, archive) with a .png, .jpg or .jpeg
extension. Replacing an image keeps every object ID, anchor and alt-text
field, so the expected findings stay the same; only the file hashes change.
After replacing images, rebuild and update the SHA256 values in
tester/fixtures/shared/expectations.json and README.md.

    uv run python scripts/build_shared_fixtures.py          # write the files
    uv run python scripts/build_shared_fixtures.py --check  # verify committed bytes
"""

import io
import struct
import sys
import zipfile
import zlib
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "tester" / "fixtures" / "shared"
IMAGES = Path(__file__).resolve().parent / "fixture_images"
STAMP = (1980, 1, 1, 0, 0, 0)
EMU_PER_COL, EMU_PER_ROW = 609600, 190500     # default column width and row height in EMUs

MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG = "http://schemas.openxmlformats.org/package/2006/relationships"
XDR = "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
C = "http://schemas.openxmlformats.org/drawingml/2006/chart"
ADEC = "http://schemas.microsoft.com/office/drawing/2017/decorative"
CT = "application/vnd.openxmlformats-officedocument"
HEAD = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'

##  Placeholder colours per picture key: (background, foreground).
PLACEHOLDERS = {
    "logo": ((221, 235, 247), (31, 78, 120)),
    "chart_icon": ((226, 239, 218), (56, 87, 35)),
    "divider": ((237, 231, 246), (94, 53, 177)),
    "totals_icon": ((252, 228, 214), (197, 90, 17)),
    "receipt": ((255, 242, 204), (127, 96, 0)),
    "archive": ((237, 237, 237), (64, 64, 64)),
}


##  ---- Images ----

def png(width, height, pixel):
    ##  RGB PNG using stored (uncompressed) deflate blocks, so no zlib version can change the bytes.
    raw = b"".join(b"\x00" + b"".join(bytes(pixel(x, y)) for x in range(width)) for y in range(height))
    blocks = [raw[i:i + 65535] for i in range(0, len(raw), 65535)] or [b""]
    stream = b"\x78\x01" + b"".join(
        bytes([1 if i == len(blocks) - 1 else 0]) + struct.pack("<HH", len(b), len(b) ^ 0xFFFF) + b
        for i, b in enumerate(blocks)) + struct.pack(">I", zlib.adler32(raw))

    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", stream) + chunk(b"IEND", b""))


def placeholder(key):
    ##  A framed image-placeholder (border plus diagonal cross) in the key's colours.
    background, foreground = PLACEHOLDERS[key]
    size, edge = 120, 6

    def pixel(x, y):
        on_frame = x < edge or y < edge or x >= size - edge or y >= size - edge
        on_cross = abs(x - y) < 3 or abs(x + y - (size - 1)) < 3
        return foreground if on_frame or on_cross else background

    return png(size, size, pixel)


def image(key):
    ##  (bytes, extension): a replacement from scripts/fixture_images/ if present, else the placeholder.
    for extension in ("png", "jpg", "jpeg"):
        path = IMAGES / f"{key}.{extension}"
        if path.exists():
            return path.read_bytes(), "jpeg" if extension == "jpg" else extension
    return placeholder(key), "png"


class Media:
    ##  Workbook-wide xl/media/ parts, one per picture key.
    def __init__(self):
        self.files = {}
        self.names = {}

    def add(self, key):
        if key not in self.names:
            data, extension = image(key)
            self.names[key] = f"image{len(self.names) + 1}.{extension}"
            self.files[self.names[key]] = data
        return self.names[key]


class Drawing:
    ##  One xl/drawings/drawingN.xml and its relationships.
    def __init__(self, media):
        self.media = media
        self.rels = []

    def _rel(self, kind, target):
        rid = f"rId{len(self.rels) + 1}"
        self.rels.append((rid, f"{REL}/{kind}", target))
        return rid

    def image(self, key):
        return self._rel("image", f"../media/{self.media.add(key)}")

    def chart(self, number):
        return self._rel("chart", f"../charts/chart{number}.xml")


##  ---- Drawing objects ----

def props(object_id, name, title=None, descr=None, decorative=False):
    attrs = f'id="{object_id}" name={quoteattr(name)}'
    if title is not None:
        attrs += f" title={quoteattr(title)}"
    if descr is not None:
        attrs += f" descr={quoteattr(descr)}"
    if not decorative:
        return f"<xdr:cNvPr {attrs}/>"
    return (f'<xdr:cNvPr {attrs}><a:extLst><a:ext uri="{{C183D7F6-B498-43B3-948B-1728B52AA6E4}}">'
            f'<adec:decorative xmlns:adec="{ADEC}" val="1"/></a:ext></a:extLst></xdr:cNvPr>')


def xfrm(x, y, cx, cy, tag="a:xfrm"):
    return f'<{tag}><a:off x="{x}" y="{y}"/><a:ext cx="{cx}" cy="{cy}"/></{tag}>'


def solid(color):
    return f'<a:solidFill><a:srgbClr val="{color}"/></a:solidFill>'


def picture(cnvpr, rid, x=0, y=0, cx=914400, cy=914400):
    return (f'<xdr:pic><xdr:nvPicPr>{cnvpr}<xdr:cNvPicPr><a:picLocks noChangeAspect="1"/></xdr:cNvPicPr>'
            f'</xdr:nvPicPr><xdr:blipFill><a:blip r:embed="{rid}"/><a:stretch><a:fillRect/></a:stretch>'
            f'</xdr:blipFill><xdr:spPr>{xfrm(x, y, cx, cy)}<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>'
            f'</xdr:spPr></xdr:pic>')


def shape(cnvpr, label, geometry="rect", fill="DDEBF7", line="1F4E78", x=0, y=0, cx=1828800, cy=762000):
    ##  A filled, outlined shape with a visible text label (the label is not alt text).
    text = (f'<xdr:txBody><a:bodyPr vertOverflow="clip" horzOverflow="clip" rtlCol="0" anchor="ctr"/><a:lstStyle/>'
            f'<a:p><a:pPr algn="ctr"/><a:r><a:rPr lang="en-US" sz="1100">{solid("1F1F1F")}</a:rPr>'
            f'<a:t>{escape(label)}</a:t></a:r></a:p></xdr:txBody>')
    return (f'<xdr:sp macro="" textlink=""><xdr:nvSpPr>{cnvpr}<xdr:cNvSpPr/></xdr:nvSpPr>'
            f'<xdr:spPr>{xfrm(x, y, cx, cy)}<a:prstGeom prst="{geometry}"><a:avLst/></a:prstGeom>{solid(fill)}'
            f'<a:ln w="19050">{solid(line)}</a:ln></xdr:spPr>{text}</xdr:sp>')


def chart_frame(cnvpr, rid):
    return (f'<xdr:graphicFrame macro=""><xdr:nvGraphicFramePr>{cnvpr}<xdr:cNvGraphicFramePr/>'
            f'</xdr:nvGraphicFramePr>{xfrm(0, 0, 0, 0, "xdr:xfrm")}<a:graphic>'
            f'<a:graphicData uri="{C}"><c:chart xmlns:c="{C}" r:id="{rid}"/></a:graphicData>'
            f'</a:graphic></xdr:graphicFrame>')


def group(cnvpr, cx, cy, *children):
    box = (f'<a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/><a:chOff x="0" y="0"/>'
           f'<a:chExt cx="{cx}" cy="{cy}"/></a:xfrm>')
    return (f'<xdr:grpSp><xdr:nvGrpSpPr>{cnvpr}<xdr:cNvGrpSpPr/></xdr:nvGrpSpPr>'
            f'<xdr:grpSpPr>{box}</xdr:grpSpPr>{"".join(children)}</xdr:grpSp>')


def drawing_xml(*items):
    ##  items: (object xml, width in columns, height in rows), stacked down from column E.
    def cell(col, row):
        return f"<xdr:col>{col}</xdr:col><xdr:colOff>0</xdr:colOff><xdr:row>{row}</xdr:row><xdr:rowOff>0</xdr:rowOff>"

    anchors, top = [], 1
    for body, cols, rows in items:
        anchors.append(f'<xdr:twoCellAnchor editAs="oneCell"><xdr:from>{cell(4, top)}</xdr:from>'
                       f'<xdr:to>{cell(4 + cols, top + rows)}</xdr:to>{body}<xdr:clientData/></xdr:twoCellAnchor>')
        top += rows + 1
    return f'{HEAD}<xdr:wsDr xmlns:xdr="{XDR}" xmlns:a="{A}" xmlns:r="{REL}">{"".join(anchors)}</xdr:wsDr>'


def chart(sheet, title):
    ##  Clustered column chart over the sheet's item rows, with a visible title and series colour.
    ref = f"'{sheet}'"
    items, amounts = [row[0] for row in ITEMS], [row[1] for row in ITEMS]
    end = len(ITEMS) + 1

    def cache(kind, values):
        return (f'<c:{kind}><c:ptCount val="{len(values)}"/>' + "".join(
            f'<c:pt idx="{i}"><c:v>{v}</c:v></c:pt>' for i, v in enumerate(values)) + f"</c:{kind}>")

    title_xml = (f'<c:title><c:tx><c:rich><a:bodyPr/><a:lstStyle/><a:p><a:r><a:rPr lang="en-US" sz="1200" b="1"/>'
                 f'<a:t>{escape(title)}</a:t></a:r></a:p></c:rich></c:tx><c:overlay val="0"/></c:title>')
    return (f'{HEAD}<c:chartSpace xmlns:c="{C}" xmlns:a="{A}" xmlns:r="{REL}"><c:chart>{title_xml}'
            f'<c:autoTitleDeleted val="0"/><c:plotArea><c:layout/><c:barChart><c:barDir val="col"/>'
            f'<c:grouping val="clustered"/><c:varyColors val="0"/><c:ser><c:idx val="0"/><c:order val="0"/>'
            f'<c:tx><c:strRef><c:f>{ref}!$B$1</c:f>{cache("strCache", ["Amount"])}</c:strRef></c:tx>'
            f'<c:spPr>{solid("2E75B6")}</c:spPr><c:invertIfNegative val="0"/>'
            f'<c:cat><c:strRef><c:f>{ref}!$A$2:$A${end}</c:f>{cache("strCache", items)}</c:strRef></c:cat>'
            f'<c:val><c:numRef><c:f>{ref}!$B$2:$B${end}</c:f>{cache("numCache", amounts)}</c:numRef></c:val>'
            f'</c:ser><c:gapWidth val="80"/><c:axId val="10"/><c:axId val="20"/></c:barChart>'
            f'<c:catAx><c:axId val="10"/><c:scaling><c:orientation val="minMax"/></c:scaling><c:delete val="0"/>'
            f'<c:axPos val="b"/><c:numFmt formatCode="General" sourceLinked="0"/><c:tickLblPos val="nextTo"/>'
            f'<c:crossAx val="20"/><c:crosses val="autoZero"/><c:auto val="1"/><c:lblAlgn val="ctr"/>'
            f'<c:lblOffset val="100"/></c:catAx>'
            f'<c:valAx><c:axId val="20"/><c:scaling><c:orientation val="minMax"/></c:scaling><c:delete val="0"/>'
            f'<c:axPos val="l"/><c:majorGridlines/><c:numFmt formatCode="&quot;$&quot;#,##0" sourceLinked="0"/>'
            f'<c:tickLblPos val="nextTo"/><c:crossAx val="10"/><c:crosses val="autoZero"/>'
            f'<c:crossBetween val="between"/></c:valAx></c:plotArea><c:plotVisOnly val="1"/>'
            f'</c:chart></c:chartSpace>')


##  ---- Cells and styles ----

ITEMS = [("Rent", 1200), ("Travel", 300), ("Supplies", 200)]
HEADER, CURRENCY, TOTAL_LABEL, TOTAL_AMOUNT = 1, 2, 3, 4

STYLES = (
    f'{HEAD}<styleSheet xmlns="{MAIN}">'
    '<numFmts count="1"><numFmt numFmtId="164" formatCode="&quot;$&quot;#,##0"/></numFmts>'
    '<fonts count="3">'
    '<font><sz val="11"/><color rgb="FF000000"/><name val="Calibri"/><family val="2"/></font>'
    '<font><b/><sz val="11"/><color rgb="FFFFFFFF"/><name val="Calibri"/><family val="2"/></font>'
    '<font><b/><sz val="11"/><color rgb="FF000000"/><name val="Calibri"/><family val="2"/></font></fonts>'
    '<fills count="4"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill>'
    '<fill><patternFill patternType="solid"><fgColor rgb="FF1F4E78"/><bgColor indexed="64"/></patternFill></fill>'
    '<fill><patternFill patternType="solid"><fgColor rgb="FFDDEBF7"/><bgColor indexed="64"/></patternFill></fill>'
    '</fills><borders count="2"><border><left/><right/><top/><bottom/><diagonal/></border>'
    '<border><left/><right/><top style="thin"><color rgb="FF1F4E78"/></top><bottom/><diagonal/></border></borders>'
    '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
    '<cellXfs count="5"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
    '<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/>'
    '<xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
    '<xf numFmtId="0" fontId="2" fillId="3" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1"/>'
    '<xf numFmtId="164" fontId="2" fillId="3" borderId="1" xfId="0" applyNumberFormat="1" applyFont="1" '
    'applyFill="1" applyBorder="1"/></cellXfs>'
    '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>')


def budget_rows():
    ##  Header, item rows, and a SUM total; cells are (value, style) or ("=formula", cached value, style).
    total = sum(amount for _, amount in ITEMS)
    return ([[("Item", HEADER), ("Amount", HEADER)]]
            + [[(item, 0), (amount, CURRENCY)] for item, amount in ITEMS]
            + [[("Total", TOTAL_LABEL), (f"=SUM(B2:B{len(ITEMS) + 1})", total, TOTAL_AMOUNT)]])


def note_rows(heading, text):
    return [[(heading, HEADER)], [(text, 0)]]


def worksheet(rows, has_drawing, widths=(22, 12)):
    def cell(ref, spec):
        value, style = spec[0], spec[-1]
        s = f' s="{style}"' if style else ""
        if isinstance(value, str) and value.startswith("="):
            return f'<c r="{ref}"{s}><f>{value[1:]}</f><v>{spec[1]}</v></c>'
        if isinstance(value, str):
            return f'<c r="{ref}"{s} t="inlineStr"><is><t>{escape(value)}</t></is></c>'
        return f'<c r="{ref}"{s}><v>{value}</v></c>'

    cols = "".join(f'<col min="{i}" max="{i}" width="{w}" customWidth="1"/>' for i, w in enumerate(widths, start=1))
    data = "".join(f'<row r="{r}">' + "".join(cell(f"{col}{r}", spec) for col, spec in zip("AB", values)) + "</row>"
                   for r, values in enumerate(rows, start=1))
    margins = '<pageMargins left="0.7" right="0.7" top="0.75" bottom="0.75" header="0.3" footer="0.3"/>'
    ##  Landscape so the data and the drawing column fit one printed page.
    page = '<pageSetup orientation="landscape"/><drawing r:id="rId1"/>' if has_drawing else ""
    return (f'{HEAD}<worksheet xmlns="{MAIN}" xmlns:r="{REL}"><cols>{cols}</cols><sheetData>{data}</sheetData>'
            f'{margins}{page}</worksheet>')


##  ---- Workbook package ----

def rels(*entries):
    body = "".join(f'<Relationship Id="{rid}" Type="{kind}" Target="{target}"/>' for rid, kind, target in entries)
    return f'{HEAD}<Relationships xmlns="{PKG}">{body}</Relationships>'


def package(title, sheets, drawings, charts, media):
    ##  sheets: [(name, sheetId, state, part number, rows, drawing number or None)]
    ##  drawings: {number: (xml, Drawing)}; charts: {number: xml}
    overrides = [("/xl/workbook.xml", f"{CT}.spreadsheetml.sheet.main+xml"),
                 ("/xl/styles.xml", f"{CT}.spreadsheetml.styles+xml"),
                 ("/docProps/core.xml", "application/vnd.openxmlformats-package.core-properties+xml"),
                 ("/docProps/app.xml", f"{CT}.extended-properties+xml")]
    overrides += [(f"/xl/worksheets/sheet{s[3]}.xml", f"{CT}.spreadsheetml.worksheet+xml") for s in sheets]
    overrides += [(f"/xl/drawings/drawing{n}.xml", f"{CT}.drawing+xml") for n in drawings]
    overrides += [(f"/xl/charts/chart{n}.xml", f"{CT}.drawingml.chart+xml") for n in charts]
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
                              f'{title}</dc:title><dc:creator>Team 12</dc:creator><dc:language>en-US</dc:language>'
                              f'</cp:coreProperties>'),
        "docProps/app.xml": (f'{HEAD}<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/'
                             f'extended-properties"><Application>Microsoft Excel</Application></Properties>'),
        "xl/workbook.xml": (f'{HEAD}<workbook xmlns="{MAIN}" xmlns:r="{REL}"><bookViews><workbookView activeTab="0"/>'
                            f'</bookViews><sheets>' + "".join(
                                f'<sheet name={quoteattr(name)} sheetId="{sid}"'
                                + (f' state="{state}"' if state else "") + f' r:id="rId{i + 1}"/>'
                                for i, (name, sid, state, *_rest) in enumerate(sheets)) + "</sheets></workbook>"),
        "xl/_rels/workbook.xml.rels": rels(*[(f"rId{i + 1}", f"{REL}/worksheet", f"worksheets/sheet{s[3]}.xml")
                                             for i, s in enumerate(sheets)],
                                           (f"rId{len(sheets) + 1}", f"{REL}/styles", "styles.xml")),
        "xl/styles.xml": STYLES,
    }
    for name, sid, state, number, rows, drawing_number in sheets:
        parts[f"xl/worksheets/sheet{number}.xml"] = worksheet(rows, drawing_number is not None)
        if drawing_number is not None:
            parts[f"xl/worksheets/_rels/sheet{number}.xml.rels"] = rels(
                ("rId1", f"{REL}/drawing", f"../drawings/drawing{drawing_number}.xml"))
    for number, (xml, drawing) in drawings.items():
        parts[f"xl/drawings/drawing{number}.xml"] = xml
        parts[f"xl/drawings/_rels/drawing{number}.xml.rels"] = rels(*drawing.rels)
    for number, xml in charts.items():
        parts[f"xl/charts/chart{number}.xml"] = xml
    for name, data in media.files.items():
        parts[f"xl/media/{name}"] = data
    return parts


def clean():
    ##  Descriptive names; every picture, shape and chart has a nonblank title and description.
    media = Media()
    budget = Drawing(media)
    budget_xml = drawing_xml(
        (picture(props(2, "Picture 1", "Team logo", "Team 12 logo placeholder."), budget.image("logo")), 2, 6),
        (shape(props(3, "Rectangle 2", "Budget note", "Callout noting that rent is the largest cost."),
               "Rent is the largest cost"), 3, 4),
        (chart_frame(props(4, "Chart 3", "Costs by item", "Column chart: rent $1,200, travel $300, supplies $200."),
                     budget.chart(1)), 6, 14))
    return package("Clean fixture", [
        ("Budget", 1, None, 1, budget_rows(), 1),
        ("Notes", 2, None, 2, note_rows("Note", "Figures are illustrative test data."), None),
    ], {1: (budget_xml, budget)}, {1: chart("Budget", "Costs by item")}, media)


def seeded_issues():
    ##  See tester/fixtures/shared/README.md for the intended finding of every object.
    media = Media()
    expenses, seeded, hidden = Drawing(media), Drawing(media), Drawing(media)
    expenses_xml = drawing_xml(
        (picture(props(2, "Picture 1", "Receipt", "Scanned travel receipt placeholder."), expenses.image("receipt")), 2, 6))
    seeded_xml = drawing_xml(
        (picture(props(2, "Picture 1", title="Logo"), seeded.image("logo")), 2, 6),                  # descr absent
        (shape(props(3, "Rectangle 2", title="", descr="Box around the totals."), "Totals"), 3, 4),   # title empty
        (chart_frame(props(4, "Chart 3", title=chr(0xA0), descr=chr(0x3000) + " "), seeded.chart(1)), 6, 14),  # whitespace only
        (picture(props(5, "Picture 4", decorative=True), seeded.image("divider")), 2, 6),             # native decorative
        (group(props(6, "Group 5", "Totals group", "Totals icon beside a status oval."), 2743200, 914400,
               picture(props(7, "Picture 6", "Totals icon", "Small totals icon placeholder."),     # child complete
                       seeded.image("totals_icon"), 0, 0, 914400, 914400),
               shape(props(8, "Oval 7"), "Status: OK", "ellipse", "E2EFDA", "385723",              # child: both absent
                     1097280, 76200, 1645920, 762000)), 5, 5))
    hidden_xml = drawing_xml(
        (picture(props(2, "Picture 1", title="Archive"), hidden.image("archive")), 2, 6))            # descr absent
    return package("Seeded issues fixture", [
        ("Expenses", 1, None, 1, budget_rows(), 1),
        ("Sheet1", 2, None, 2, budget_rows(), 2),
        (" Sheet03 ", 5, "hidden", 3, note_rows("Archived", "Old figures kept for reference."), 3),
        ("Sheet0", 4, None, 4, note_rows("Scratch", "Working notes."), None),
    ], {1: (expenses_xml, expenses), 2: (seeded_xml, seeded), 3: (hidden_xml, hidden)},
        {1: chart("Sheet1", "Costs by item")}, media)


def corrupt():
    ##  A ZIP local-file signature followed by bytes that are not a valid package.
    return b"PK\x03\x04" + b"Team 12 corrupt fixture: deliberately unreadable workbook bytes.\n" * 4


def zipped(parts):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED) as archive:
        for name, content in parts.items():
            info = zipfile.ZipInfo(name, STAMP)
            info.compress_type = zipfile.ZIP_STORED
            info.external_attr = 0o600 << 16
            archive.writestr(info, content.encode("utf-8") if isinstance(content, str) else content)
    return buffer.getvalue()


def build():
    return {"clean.xlsx": zipped(clean()), "seeded_issues.xlsx": zipped(seeded_issues()), "corrupt.xlsx": corrupt()}


def main(argv):
    files = build()
    if "--check" in argv:
        stale = [name for name, data in files.items() if (OUT / name).read_bytes() != data]
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
