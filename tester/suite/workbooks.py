"""Workbooks the tester generates itself for intake checks.

These are not reviewed fixtures and carry no findings oracle: each has only the
property its check needs (an exact byte size, a worksheet or nonempty-cell
count, a chartsheet, structure protection). Output is deterministic, so the
same build sends the same bytes in every run.
"""

import base64
import hashlib
import io
import zipfile

MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
CONTENT_TYPES = "http://schemas.openxmlformats.org/package/2006/content-types"
DRAWING = "http://schemas.openxmlformats.org/drawingml/2006/main"
SPREADSHEET_DRAWING = "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"
CHART = "http://schemas.openxmlformats.org/drawingml/2006/chart"
TYPE = "application/vnd.openxmlformats-officedocument."
FIXED_TIME = (1980, 1, 1, 0, 0, 0)
CELLS_PER_ROW = 100
PADDING_PART = "tester-padding.bin"

##  Legacy binary (.xls) files are OLE compound documents; this is their signature.
LEGACY_XLS = bytes.fromhex("d0cf11e0a1b11ae1") + bytes(504)
CSV = b"Region,Total\r\nNorth,10\r\nSouth,12\r\n"


def workbook(worksheets=1, cells=0, chartsheet=False, protect_structure=False, size=None):
    ##  A valid .xlsx. cells nonempty numeric cells go on the first worksheet; size pads the
    ##  package with an unreferenced stored part to exactly that many bytes.
    if worksheets < 1:
        raise ValueError("a workbook needs at least one worksheet")
    parts = _parts(worksheets, cells, chartsheet, protect_structure)
    if size is None:
        return _package(parts, None)
    unpadded = len(_package(parts, b""))
    if size < unpadded:
        raise ValueError(f"cannot build a {size}-byte workbook; the smallest is {unpadded} bytes")
    content = _package(parts, bytes(size - unpadded))
    if len(content) != size:
        raise AssertionError(f"padded workbook is {len(content)} bytes, not {size}")
    return content


def structure_password_hash(password, salt, spin_count=100_000):
    ##  ECMA-376 agile password hash (SHA-512) as stored in workbookProtection.
    digest = hashlib.sha512(salt + password.encode("utf-16-le")).digest()
    for iteration in range(spin_count):
        digest = hashlib.sha512(digest + iteration.to_bytes(4, "little")).digest()
    return digest


def column(index):
    ##  1 -> A, 26 -> Z, 27 -> AA.
    letters = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def _package(parts, padding):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as package:
        for name, data in parts:
            info = zipfile.ZipInfo(name, FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            package.writestr(info, data)
        if padding is not None:
            info = zipfile.ZipInfo(PADDING_PART, FIXED_TIME)
            info.compress_type = zipfile.ZIP_STORED      # each padding byte adds exactly one package byte
            package.writestr(info, padding)
    return buffer.getvalue()


def _parts(worksheets, cells, chartsheet, protect_structure):
    names = [f"Data {n}" for n in range(1, worksheets + 1)]
    overrides = [("/xl/workbook.xml", TYPE + "spreadsheetml.sheet.main+xml"),
                 ("/xl/styles.xml", TYPE + "spreadsheetml.styles+xml")]
    sheets, rels, parts = [], [], []
    for n, name in enumerate(names, 1):
        sheets.append(f'<sheet name="{name}" sheetId="{n}" r:id="rId{n}"/>')
        rels.append(_rel(f"rId{n}", "worksheet", f"worksheets/sheet{n}.xml"))
        overrides.append((f"/xl/worksheets/sheet{n}.xml", TYPE + "spreadsheetml.worksheet+xml"))
        parts.append((f"xl/worksheets/sheet{n}.xml", _worksheet(cells if n == 1 else 0)))
    if chartsheet:
        n = worksheets + 1
        sheets.append(f'<sheet name="Chart 1" sheetId="{n}" r:id="rId{n}"/>')
        rels.append(_rel(f"rId{n}", "chartsheet", "chartsheets/sheet1.xml"))
        overrides += [("/xl/chartsheets/sheet1.xml", TYPE + "spreadsheetml.chartsheet+xml"),
                      ("/xl/drawings/drawing1.xml", TYPE + "drawing+xml"),
                      ("/xl/charts/chart1.xml", TYPE + "drawingml.chart+xml")]
        parts += _chartsheet_parts(names[0])
    rels.append(_rel(f"rId{len(sheets) + 1}", "styles", "styles.xml"))
    protection = _protection() if protect_structure else ""
    parts += [
        ("[Content_Types].xml", _content_types(overrides)),
        ("_rels/.rels", _rels([_rel("rId1", "officeDocument", "xl/workbook.xml")])),
        ("xl/workbook.xml", f'<workbook xmlns="{MAIN}" xmlns:r="{REL}">{protection}'
                            f'<bookViews><workbookView/></bookViews><sheets>{"".join(sheets)}</sheets></workbook>'),
        ("xl/_rels/workbook.xml.rels", _rels(rels)),
        ("xl/styles.xml", STYLES),
    ]
    return [(name, data.encode("utf-8")) for name, data in parts]


def _worksheet(cells):
    rows = []
    for row in range(1, -(-cells // CELLS_PER_ROW) + 1):
        width = min(CELLS_PER_ROW, cells - (row - 1) * CELLS_PER_ROW)
        rows.append(f'<row r="{row}">'
                    + "".join(f'<c r="{column(c)}{row}"><v>{c}</v></c>' for c in range(1, width + 1))
                    + "</row>")
    return f'<worksheet xmlns="{MAIN}"><sheetData>{"".join(rows)}</sheetData></worksheet>'


def _chartsheet_parts(data_sheet):
    drawing = (
        f'<xdr:wsDr xmlns:xdr="{SPREADSHEET_DRAWING}" xmlns:a="{DRAWING}" xmlns:c="{CHART}" xmlns:r="{REL}">'
        '<xdr:absoluteAnchor><xdr:pos x="0" y="0"/><xdr:ext cx="8000000" cy="5000000"/>'
        '<xdr:graphicFrame macro=""><xdr:nvGraphicFramePr>'
        '<xdr:cNvPr id="2" name="Chart 1" title="Values by column" '
        f'descr="Column chart of the first row of {data_sheet}."/><xdr:cNvGraphicFramePr/></xdr:nvGraphicFramePr>'
        '<xdr:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/></xdr:xfrm>'
        f'<a:graphic><a:graphicData uri="{CHART}"><c:chart r:id="rId1"/></a:graphicData></a:graphic>'
        '</xdr:graphicFrame><xdr:clientData/></xdr:absoluteAnchor></xdr:wsDr>')
    axis = ('<c:axId val="{id}"/><c:scaling><c:orientation val="minMax"/></c:scaling><c:delete val="0"/>'
            '<c:axPos val="{pos}"/><c:crossAx val="{cross}"/>')
    chart = (
        f'<c:chartSpace xmlns:c="{CHART}" xmlns:a="{DRAWING}" xmlns:r="{REL}"><c:chart>'
        '<c:autoTitleDeleted val="1"/><c:plotArea><c:layout/><c:barChart><c:barDir val="col"/>'
        '<c:grouping val="clustered"/><c:varyColors val="0"/><c:ser><c:idx val="0"/><c:order val="0"/>'
        f"<c:val><c:numRef><c:f>'{data_sheet}'!$A$1:$C$1</c:f></c:numRef></c:val></c:ser>"
        '<c:axId val="10"/><c:axId val="20"/></c:barChart>'
        f'<c:catAx>{axis.format(id=10, pos="b", cross=20)}</c:catAx>'
        f'<c:valAx>{axis.format(id=20, pos="l", cross=10)}</c:valAx>'
        '</c:plotArea><c:plotVisOnly val="1"/></c:chart></c:chartSpace>')
    return [
        ("xl/chartsheets/sheet1.xml", f'<chartsheet xmlns="{MAIN}" xmlns:r="{REL}"><sheetViews>'
                                      '<sheetView workbookViewId="0"/></sheetViews><drawing r:id="rId1"/></chartsheet>'),
        ("xl/chartsheets/_rels/sheet1.xml.rels", _rels([_rel("rId1", "drawing", "../drawings/drawing1.xml")])),
        ("xl/drawings/drawing1.xml", drawing),
        ("xl/drawings/_rels/drawing1.xml.rels", _rels([_rel("rId1", "chart", "../charts/chart1.xml")])),
        ("xl/charts/chart1.xml", chart),
    ]


def _protection():
    salt = hashlib.sha256(b"team12 tester structure protection").digest()[:16]
    digest = structure_password_hash("tester-protected", salt)
    return ('<workbookProtection workbookAlgorithmName="SHA-512" '
            f'workbookHashValue="{base64.b64encode(digest).decode()}" '
            f'workbookSaltValue="{base64.b64encode(salt).decode()}" '
            'workbookSpinCount="100000" lockStructure="1"/>')


def _rel(rel_id, kind, target):
    return f'<Relationship Id="{rel_id}" Type="{REL}/{kind}" Target="{target}"/>'


def _rels(items):
    return f'<Relationships xmlns="{PACKAGE_REL}">{"".join(items)}</Relationships>'


def _content_types(overrides):
    return (f'<Types xmlns="{CONTENT_TYPES}">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Default Extension="bin" ContentType="application/octet-stream"/>'
            + "".join(f'<Override PartName="{name}" ContentType="{kind}"/>' for name, kind in overrides)
            + "</Types>")


STYLES = (
    f'<styleSheet xmlns="{MAIN}"><fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts>'
    '<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/>'
    '</fill></fills><borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
    '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
    '<cellXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/></cellXfs>'
    '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>')
