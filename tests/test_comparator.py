"""The independent Phase 4 workbook comparator (tester/suite/comparator.py).

Outputs are made from the source by plain string edits, the way a correct or a careless
editor might write them, so the expected results do not depend on the comparator's own
tree transforms.
"""

import hashlib
import io
import zipfile

import pytest

from tester.config import FIXTURES
from tester.suite.comparator import (AltText, ChangeError, EnableHeader, HeaderRow, LinkLabel, Rename,
                                     change_from_decision, compare, rewrite_sheet_references)

HEAD = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG = "http://schemas.openxmlformats.org/package/2006/relationships"
CT = "application/vnd.openxmlformats-officedocument"
MC = "http://schemas.openxmlformats.org/markup-compatibility/2006"
X14AC = "http://schemas.microsoft.com/office/spreadsheetml/2009/9/ac"
TABLE_TYPE = f"{CT}.spreadsheetml.table+xml"

SOURCE = {
    "[Content_Types].xml": (
        f'{HEAD}<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/><Default Extension="png" ContentType="image/png"/>'
        f'<Override PartName="/xl/workbook.xml" ContentType="{CT}.spreadsheetml.sheet.main+xml"/>'
        f'<Override PartName="/xl/worksheets/sheet1.xml" ContentType="{CT}.spreadsheetml.worksheet+xml"/>'
        f'<Override PartName="/xl/worksheets/sheet2.xml" ContentType="{CT}.spreadsheetml.worksheet+xml"/>'
        f'<Override PartName="/xl/worksheets/sheet3.xml" ContentType="{CT}.spreadsheetml.worksheet+xml"/>'
        f'<Override PartName="/xl/drawings/drawing1.xml" ContentType="{CT}.drawing+xml"/>'
        f'<Override PartName="/xl/charts/chart1.xml" ContentType="{CT}.drawingml.chart+xml"/>'
        f'<Override PartName="/xl/sharedStrings.xml" ContentType="{CT}.spreadsheetml.sharedStrings+xml"/>'
        f'<Override PartName="/xl/styles.xml" ContentType="{CT}.spreadsheetml.styles+xml"/>'
        f'<Override PartName="/docProps/app.xml" ContentType="{CT}.extended-properties+xml"/></Types>'),
    "_rels/.rels": (f'{HEAD}<Relationships xmlns="{PKG}">'
                    f'<Relationship Id="rId1" Type="{REL}/officeDocument" Target="xl/workbook.xml"/>'
                    f'<Relationship Id="rId2" Type="{REL}/extended-properties" Target="docProps/app.xml"/>'
                    '</Relationships>'),
    "docProps/app.xml": (
        f'{HEAD}<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" '
        'xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes"><TitlesOfParts>'
        '<vt:vector size="3" baseType="lpstr"><vt:lpstr>Summary</vt:lpstr><vt:lpstr>Sheet1</vt:lpstr>'
        '<vt:lpstr>Sheet10</vt:lpstr></vt:vector></TitlesOfParts></Properties>'),
    "xl/workbook.xml": (
        f'{HEAD}<workbook xmlns="{MAIN}" xmlns:r="{REL}" xmlns:mc="{MC}" xmlns:x14ac="{X14AC}" '
        'mc:Ignorable="x14ac"><sheets><sheet name="Summary" sheetId="1" r:id="rId1"/>'
        '<sheet name="Sheet1" sheetId="2" r:id="rId2"/><sheet name="Sheet10" sheetId="3" r:id="rId3"/></sheets>'
        '<definedNames><definedName name="Totals">Sheet1!$B$2:$B$3</definedName></definedNames></workbook>'),
    "xl/_rels/workbook.xml.rels": (
        f'{HEAD}<Relationships xmlns="{PKG}">'
        f'<Relationship Id="rId1" Type="{REL}/worksheet" Target="worksheets/sheet1.xml"/>'
        f'<Relationship Id="rId2" Type="{REL}/worksheet" Target="worksheets/sheet2.xml"/>'
        f'<Relationship Id="rId3" Type="{REL}/worksheet" Target="worksheets/sheet3.xml"/>'
        f'<Relationship Id="rId4" Type="{REL}/sharedStrings" Target="sharedStrings.xml"/>'
        f'<Relationship Id="rId5" Type="{REL}/styles" Target="styles.xml"/></Relationships>'),
    "xl/worksheets/sheet1.xml": (
        f'{HEAD}<worksheet xmlns="{MAIN}" xmlns:r="{REL}"><!-- summary formulas --><sheetData>'
        '<row r="1"><c r="A1"><f>SUM(Sheet1!B2:B3)+\'Sheet1\'!B2+Sheet10!A1+[1]Sheet1!A1</f><v>10</v></c>'
        '<c r="B1" t="str"><f>IF(A1&gt;0,"Sheet1!A1","")</f><v>Sheet1!A1</v></c></row>'
        '<row r="5"><c r="A5" t="s"><v>0</v></c><c r="B5" t="s"><v>0</v></c></row></sheetData>'
        '<conditionalFormatting sqref="A1"><cfRule type="expression" priority="1"><formula>Sheet1!$B$2&gt;0'
        '</formula></cfRule></conditionalFormatting>'
        '<dataValidations count="1"><dataValidation type="list" sqref="C1"><formula1>Sheet1!$A$2:$A$3</formula1>'
        '</dataValidation></dataValidations>'
        '<hyperlinks><hyperlink ref="A5" location="Sheet1!A1" display="click here"/></hyperlinks></worksheet>'),
    "xl/worksheets/sheet2.xml": (
        f'{HEAD}<worksheet xmlns="{MAIN}" xmlns:r="{REL}"><sheetData>'
        '<row r="1"><c r="A1" t="inlineStr"><is><t>Item</t></is></c><c r="B1" t="inlineStr"><is><t>Amount</t></is></c></row>'
        '<row r="2"><c r="A2" t="inlineStr"><is><t>Rent</t></is></c><c r="B2"><v>1200</v></c></row>'
        '<row r="3"><c r="A3" t="inlineStr"><is><t>Travel</t></is></c><c r="B3"><v>300</v></c></row>'
        '</sheetData><drawing r:id="rId1"/></worksheet>'),
    "xl/worksheets/_rels/sheet2.xml.rels": (
        f'{HEAD}<Relationships xmlns="{PKG}">'
        f'<Relationship Id="rId1" Type="{REL}/drawing" Target="../drawings/drawing1.xml"/></Relationships>'),
    "xl/worksheets/sheet3.xml": f'{HEAD}<worksheet xmlns="{MAIN}"><sheetData/></worksheet>',
    "xl/drawings/drawing1.xml": (
        f'{HEAD}<xdr:wsDr xmlns:xdr="http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing" '
        'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
        '<xdr:twoCellAnchor><xdr:pic><xdr:nvPicPr><xdr:cNvPr id="2" name="Picture 1" title="Logo"/></xdr:nvPicPr>'
        '</xdr:pic></xdr:twoCellAnchor><xdr:twoCellAnchor><xdr:sp><xdr:nvSpPr><xdr:cNvPr id="3" name="Box 2"/>'
        '</xdr:nvSpPr></xdr:sp></xdr:twoCellAnchor></xdr:wsDr>'),
    "xl/drawings/_rels/drawing1.xml.rels": (
        f'{HEAD}<Relationships xmlns="{PKG}">'
        f'<Relationship Id="rId1" Type="{REL}/chart" Target="../charts/chart1.xml"/></Relationships>'),
    "xl/charts/chart1.xml": (
        f'{HEAD}<c:chartSpace xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart"><c:chart>'
        '<c:ser><c:val><c:numRef><c:f>Sheet1!$B$2:$B$3</c:f></c:numRef></c:val></c:ser></c:chart></c:chartSpace>'),
    "xl/sharedStrings.xml": f'{HEAD}<sst xmlns="{MAIN}" count="2" uniqueCount="1"><si><t>click here</t></si></sst>',
    "xl/styles.xml": f'{HEAD}<styleSheet xmlns="{MAIN}"><fonts count="1"><font><sz val="11"/></font></fonts></styleSheet>',
    "xl/media/image1.png": b"\x89PNG\r\n\x1a\nnot really an image",
}


def package(parts, compression=zipfile.ZIP_STORED, reverse=False, stamp=(1980, 1, 1, 0, 0, 0)):
    buffer = io.BytesIO()
    items = list(parts.items())
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in reversed(items) if reverse else items:
            info = zipfile.ZipInfo(name, stamp)
            info.compress_type = compression
            archive.writestr(info, content.encode() if isinstance(content, str) else content)
    return buffer.getvalue()


def edited(**edits):
    ##  edits: part key (path with / and . replaced by _) -> [(old, new), ...] string replacements.
    parts = dict(SOURCE)
    for key, replacements in edits.items():
        name = next(n for n in parts if n.replace("/", "_").replace(".", "_").replace("[", "").replace("]", "") == key)
        for old, new in replacements:
            assert old in parts[name], (name, old)
            parts[name] = parts[name].replace(old, new)
    return parts


SRC = package(SOURCE)


##  ---- Package level ----

def test_identical_contents_in_a_different_zip_serialization_match():
    output = package(SOURCE, zipfile.ZIP_DEFLATED, reverse=True, stamp=(2026, 11, 1, 12, 0, 0))
    assert output != SRC
    assert compare(SRC, output, declared_sha256=hashlib.sha256(output).hexdigest()) == []


def test_declared_hash_must_match_the_downloaded_bytes():
    problems = compare(SRC, SRC, declared_sha256="0" * 64)
    assert len(problems) == 1 and "declared sha256" in problems[0]


def test_untouched_parts_must_be_byte_identical():
    output = package(edited(xl_styles_xml=[('<sz val="11"/>', '<sz val="12"/>')]))
    assert compare(SRC, output) == ["xl/styles.xml changed, but no approved change touches it"]
    ##  Even a semantically equal re-serialization of an untouched part is a difference.
    reserialized = package(edited(xl_styles_xml=[('<sz val="11"/>', '<sz val="11" />')]))
    assert compare(SRC, reserialized) == ["xl/styles.xml changed, but no approved change touches it"]


def test_binary_parts_entry_sets_and_removed_entries():
    parts = dict(SOURCE)
    parts["xl/media/image1.png"] = b"\x89PNG\r\n\x1a\nreplaced"
    del parts["xl/worksheets/sheet3.xml"]
    parts["xl/extra.xml"] = f"{HEAD}<extra/>"
    assert compare(SRC, package(parts)) == ["xl/worksheets/sheet3.xml is missing from the output",
                                            "xl/extra.xml was added, but no approved change adds it",
                                            "xl/media/image1.png changed, but no approved change touches it"]


@pytest.mark.parametrize("output, text", [
    (b"PK\x03\x04 not a zip", "output is not a readable ZIP package"),
    (package({**SOURCE, "../escape.xml": "x"}), "unsafe name"),
])
def test_unreadable_or_unsafe_outputs(output, text):
    problems = compare(SRC, output)
    assert any(text in p for p in problems), problems


def test_duplicate_entries_are_reported():
    buffer = io.BytesIO()
    with pytest.warns(UserWarning), zipfile.ZipFile(buffer, "w") as archive:
        for name, content in SOURCE.items():
            archive.writestr(name, content)
        archive.writestr("xl/styles.xml", SOURCE["xl/styles.xml"])
    assert compare(SRC, buffer.getvalue()) == ["the output repeats an entry name"]


##  ---- Alternative text (§8.3) ----

ALT = AltText("xl/drawings/drawing1.xml", "2", "Team logo", "Team 12 logo placeholder.")
ALT_DONE = [('id="2" name="Picture 1" title="Logo"/>',
             'id="2" name="Picture 1" title="Team logo" descr="Team 12 logo placeholder."/>')]


def test_alt_text_applied_exactly():
    assert compare(SRC, package(edited(xl_drawings_drawing1_xml=ALT_DONE)), [ALT]) == []


@pytest.mark.parametrize("replacements, text", [
    ([(ALT_DONE[0][0], 'id="2" name="Picture 1" title="Team logo" descr="Generated text."/>')],
     "attribute descr is 'Generated text.', expected 'Team 12 logo placeholder.'"),
    ([(ALT_DONE[0][0], 'id="2" name="Team logo" title="Team logo" descr="Team 12 logo placeholder."/>')],
     "attribute name is 'Team logo', expected 'Picture 1'"),
    (ALT_DONE + [('id="3" name="Box 2"/>', 'id="3" name="Box 2" descr="Also edited."/>')],
     "attribute descr is 'Also edited.', expected None"),
])
def test_alt_text_wrong_edits(replacements, text):
    problems = compare(SRC, package(edited(xl_drawings_drawing1_xml=replacements)), [ALT])
    assert len(problems) == 1 and text in problems[0], problems


def test_an_approved_change_that_was_not_applied():
    problems = compare(SRC, SRC, [ALT])
    assert problems == ["xl/drawings/drawing1.xml is unchanged, but an approved change requires an edit there "
                        "(alt text of object 2)"]


def test_a_change_that_cannot_be_located():
    problems = compare(SRC, SRC, [AltText("xl/drawings/drawing1.xml", "9", "t", "d")])
    assert problems == ["approved change not locatable in the source: xl/drawings/drawing1.xml#id=9 does not "
                        "identify exactly one object"]


##  ---- Worksheet rename (§8.4) ----

RENAME = Rename("2", "Q1 Costs")
RENAMED = dict(
    xl_workbook_xml=[('name="Sheet1" sheetId="2"', 'name="Q1 Costs" sheetId="2"'),
                     (">Sheet1!$B$2:$B$3<", ">'Q1 Costs'!$B$2:$B$3<")],
    xl_worksheets_sheet1_xml=[("SUM(Sheet1!B2:B3)+'Sheet1'!B2+Sheet10!A1+[1]Sheet1!A1",
                               "SUM('Q1 Costs'!B2:B3)+'Q1 Costs'!B2+Sheet10!A1+[1]Sheet1!A1"),
                              ("<formula>Sheet1!$B$2", "<formula>'Q1 Costs'!$B$2"),
                              ("<formula1>Sheet1!$A$2", "<formula1>'Q1 Costs'!$A$2"),
                              ('location="Sheet1!A1"', "location=\"'Q1 Costs'!A1\"")],
    xl_charts_chart1_xml=[("<c:f>Sheet1!", "<c:f>'Q1 Costs'!")],
)


def test_rename_with_every_reference_rewritten():
    assert compare(SRC, package(edited(**RENAMED)), [RENAME]) == []


def test_rename_may_also_update_the_app_titles():
    both = edited(**RENAMED, docProps_app_xml=[("<vt:lpstr>Sheet1</vt:lpstr>", "<vt:lpstr>Q1 Costs</vt:lpstr>")])
    assert compare(SRC, package(both), [RENAME]) == []


def test_rename_missing_a_chart_reference():
    partial = {key: value for key, value in RENAMED.items() if key != "xl_charts_chart1_xml"}
    problems = compare(SRC, package(edited(**partial)), [RENAME])
    assert problems == ["xl/charts/chart1.xml is unchanged, but an approved change requires an edit there (sheet "
                        "references rewritten for the rename of 'Sheet1' to 'Q1 Costs')"]


def test_rename_by_global_text_replacement_is_caught():
    ##  Replacing every "Sheet1" also hits Sheet10, the external [1]Sheet1 reference and a string literal.
    parts = {name: content.replace("Sheet1", "Q1Costs") if isinstance(content, str) else content
             for name, content in SOURCE.items()}
    problems = compare(SRC, package(parts), [Rename("2", "Q1Costs")])
    by_part = {p.split(":", 1)[0]: p for p in problems}
    assert set(by_part) == {"docProps/app.xml", "xl/charts/chart1.xml", "xl/workbook.xml", "xl/worksheets/sheet1.xml"}
    assert "/workbook/sheets[1]/sheet[3]: attribute name is 'Q1Costs0', expected 'Sheet10'" in by_part["xl/workbook.xml"]
    assert ("text is \"SUM(Q1Costs!B2:B3)+'Q1Costs'!B2+Q1Costs0!A1+[1]Q1Costs!A1\", expected "
            "\"SUM('Q1Costs'!B2:B3)+'Q1Costs'!B2+Sheet10!A1+[1]Sheet1!A1\"") in by_part["xl/worksheets/sheet1.xml"]
    assert "text is 'Q1Costs!$B$2:$B$3', expected \"'Q1Costs'!$B$2:$B$3\"" in by_part["xl/charts/chart1.xml"]


def test_rename_must_quote_the_new_name():
    unquoted = {key: [(old, new.replace("'Q1 Costs'", "Costs")) for old, new in pairs] for key, pairs in RENAMED.items()}
    unquoted["xl_workbook_xml"][0] = ('name="Sheet1" sheetId="2"', 'name="Costs" sheetId="2"')
    problems = compare(SRC, package(edited(**unquoted)), [Rename("2", "Costs")])
    assert any("expected \"SUM('Costs'!B2:B3)" in p for p in problems), problems


@pytest.mark.parametrize("formula, expected", [
    ("Sheet1!A1", "'New'!A1"),
    ("sheet1!A1", "'New'!A1"),                                  # sheet names compare case-insensitively
    ("'Sheet1'!A1:B2", "'New'!A1:B2"),
    ("SUM(Sheet1!A1,Sheet1!B1)", "SUM('New'!A1,'New'!B1)"),
    ("Sheet10!A1+Sheet1x!A1", "Sheet10!A1+Sheet1x!A1"),          # similar names untouched
    ('"Sheet1!A1"&Sheet1!A1', "\"Sheet1!A1\"&'New'!A1"),         # string literal untouched
    ('"say ""Sheet1!A1"""&Sheet1!A1', "\"say \"\"Sheet1!A1\"\"\"&'New'!A1"),
    ("[1]Sheet1!A1+'[Book.xlsx]Sheet1'!A1", "[1]Sheet1!A1+'[Book.xlsx]Sheet1'!A1"),   # external untouched
    ("#REF!+Sheet1!$A$1", "#REF!+'New'!$A$1"),
    ("Totals", "Totals"),
])
def test_sheet_reference_rewriting(formula, expected):
    assert rewrite_sheet_references(formula, "Sheet1", "New") == expected


def test_quoted_names_with_apostrophes_round_trip():
    assert rewrite_sheet_references("'Bob''s'!A1+Bob!A1", "Bob's", "It's") == "'It''s'!A1+Bob!A1"


##  ---- Hyperlink label (§8.5) ----

LINK = LinkLabel("xl/worksheets/sheet1.xml", "A5", "Annual accessibility report")
LINKED = [('<c r="A5" t="s"><v>0</v></c>',
           '<c r="A5" t="inlineStr"><is><t>Annual accessibility report</t></is></c>'),
          ('display="click here"', 'display="Annual accessibility report"')]


def test_link_label_applied_exactly():
    assert compare(SRC, package(edited(xl_worksheets_sheet1_xml=LINKED)), [LINK]) == []


def test_link_label_must_not_edit_the_shared_string():
    ##  The shared string is used by B5 too; editing it changes another cell.
    problems = compare(SRC, package(edited(
        xl_worksheets_sheet1_xml=[('display="click here"', 'display="Annual accessibility report"')],
        xl_sharedStrings_xml=[("<t>click here</t>", "<t>Annual accessibility report</t>")])), [LINK])
    assert "xl/sharedStrings.xml changed, but no approved change touches it" in problems
    assert any(p.startswith("xl/worksheets/sheet1.xml: ") for p in problems)


##  ---- Header row (§8.6) ----

HEADER = HeaderRow("xl/worksheets/sheet2.xml", "A1:B3")
TABLE = (f'{HEAD}<table xmlns="{MAIN}" id="1" name="A11yTable1" displayName="A11yTable1" ref="A1:B3" '
         'headerRowCount="1"><tableColumns count="2"><tableColumn id="1" name="Item"/>'
         '<tableColumn id="2" name="Amount"/></tableColumns></table>')


def header_output(table=TABLE, sheet_tail='<tableParts count="1"><tablePart r:id="rId2"/></tableParts>',
                  rel=f'<Relationship Id="rId2" Type="{REL}/table" Target="../tables/table1.xml"/>',
                  override=f'<Override PartName="/xl/tables/table1.xml" ContentType="{TABLE_TYPE}"/>'):
    parts = edited(xl_worksheets_sheet2_xml=[('<drawing r:id="rId1"/>', f'<drawing r:id="rId1"/>{sheet_tail}')],
                   xl_worksheets__rels_sheet2_xml_rels=[("</Relationships>", f"{rel}</Relationships>")],
                   Content_Types_xml=[("</Types>", f"{override}</Types>")])
    if table is not None:
        parts["xl/tables/table1.xml"] = table
    return package(parts)


def test_header_row_adds_exactly_one_minimal_table():
    assert compare(SRC, header_output(), [HEADER]) == []


@pytest.mark.parametrize("kwargs, text", [
    ({"table": TABLE.replace('id="1" name', 'id="5" name')}, "xl/tables/table1.xml: id is '5', expected '1'"),
    ({"table": TABLE.replace('name="Amount"', 'name="Value"')}, "table columns are ['Item', 'Value']"),
    ({"table": TABLE.replace("</tableColumns>", '</tableColumns><tableStyleInfo name="TableStyleMedium2"/>')},
     "has <tableStyleInfo>"),
    ({"table": None}, "xl/tables/table1.xml, required by an approved header change, is missing"),
    ({"override": ""}, "[Content_Types].xml: missing declaration ('Override', '/xl/tables/table1.xml'"),
    ({"rel": f'<Relationship Id="rId7" Type="{REL}/table" Target="../tables/table1.xml"/>'},
     "missing relationship ('rId2'"),
    ({"sheet_tail": ""}, "xl/worksheets/sheet2.xml is unchanged, but an approved change requires an edit there "
                         "(tablePart rId2"),
    ({"sheet_tail": '<tableParts count="1"><tablePart r:id="rId3"/></tableParts>'},
     "tableParts references are ['rId3'], expected ['rId2']"),
])
def test_header_row_wrong_structure(kwargs, text):
    problems = compare(SRC, header_output(**kwargs), [HEADER])
    assert any(text in p for p in problems), problems


def test_header_row_on_a_sheet_without_relationships_creates_the_part():
    ##  Regression: a new relationships part used to crash the comparator (dict | set).
    ##  Source: sheet2 without its drawing reference or relationships part.
    parts = edited(xl_worksheets_sheet2_xml=[('<drawing r:id="rId1"/>',
                                              '<tableParts count="1"><tablePart r:id="rId1"/></tableParts>')],
                   Content_Types_xml=[("</Types>", f'<Override PartName="/xl/tables/table1.xml" '
                                                   f'ContentType="{TABLE_TYPE}"/></Types>')])
    del parts["xl/worksheets/_rels/sheet2.xml.rels"]
    parts["xl/worksheets/_rels/sheet2.xml.rels"] = (f'{HEAD}<Relationships xmlns="{PKG}"><Relationship Id="rId1" '
                                                    f'Type="{REL}/table" Target="../tables/table1.xml"/></Relationships>')
    parts["xl/tables/table1.xml"] = TABLE
    source_parts = {k: v for k, v in SOURCE.items() if k != "xl/worksheets/_rels/sheet2.xml.rels"}
    source_parts["xl/worksheets/sheet2.xml"] = SOURCE["xl/worksheets/sheet2.xml"].replace('<drawing r:id="rId1"/>', "")
    source = package(source_parts)
    assert compare(source, package(parts), [HEADER]) == []


def test_enable_header_on_an_existing_table():
    table = (f'{HEAD}<table xmlns="{MAIN}" id="1" name="Costs" displayName="Costs" ref="A1:B3" headerRowCount="0">'
             '<tableColumns count="2"><tableColumn id="1" name="Item"/><tableColumn id="2" name="Amount"/>'
             '</tableColumns></table>')
    source = package({**SOURCE, "xl/tables/table1.xml": table})
    change = EnableHeader("xl/tables/table1.xml")
    for enabled in ('headerRowCount="1"', ""):
        output = package({**SOURCE, "xl/tables/table1.xml": table.replace('headerRowCount="0"', enabled)})
        assert compare(source, output, [change]) == []
    assert compare(source, source, [change])[0].startswith("xl/tables/table1.xml is unchanged")


##  ---- Changed XML must keep markup it does not understand ----

def test_changed_part_keeps_comments_and_namespace_declarations():
    dropped_comment = edited(**{**RENAMED, "xl_worksheets_sheet1_xml":
                                RENAMED["xl_worksheets_sheet1_xml"] + [("<!-- summary formulas -->", "")]})
    problems = compare(SRC, package(dropped_comment), [RENAME])
    assert any("xl/worksheets/sheet1.xml: " in p for p in problems), problems
    renamed_prefix = edited(**{**RENAMED, "xl_workbook_xml": RENAMED["xl_workbook_xml"] + [
        ('xmlns:x14ac="', 'xmlns:ac="'), ('mc:Ignorable="x14ac"', 'mc:Ignorable="ac"')]})
    problems = compare(SRC, package(renamed_prefix), [RENAME])
    assert any("namespace declarations [('x14ac'" in p for p in problems), problems


def test_dtd_in_a_changed_output_part_is_refused():
    with_dtd = edited(xl_drawings_drawing1_xml=ALT_DONE + [(HEAD, HEAD + "<!DOCTYPE wsDr>")])
    assert compare(SRC, package(with_dtd), [ALT]) == ["output xl/drawings/drawing1.xml declares a DTD"]


@pytest.mark.parametrize("key", ["clean", "seeded_issues", "unicode", "repeated_ids", "multiple_drawings"])
def test_shared_fixtures_rezipped_have_no_differences(key):
    source = (FIXTURES / "shared" / f"{key}.xlsx").read_bytes()
    with zipfile.ZipFile(io.BytesIO(source)) as archive:
        parts = {name: archive.read(name) for name in archive.namelist()}
    assert compare(source, package(parts, zipfile.ZIP_DEFLATED, reverse=True)) == []


def test_alt_text_on_the_seeded_fixture():
    ##  The seeded Sheet1 picture (drawing2.xml id 2) lacks a description; supply both fields.
    source = (FIXTURES / "shared" / "seeded_issues.xlsx").read_bytes()
    with zipfile.ZipFile(io.BytesIO(source)) as archive:
        parts = {name: archive.read(name) for name in archive.namelist()}
    old = b'<xdr:cNvPr id="2" name="Picture 1" title="Logo"/>'
    assert parts["xl/drawings/drawing2.xml"].count(old) == 1
    parts["xl/drawings/drawing2.xml"] = parts["xl/drawings/drawing2.xml"].replace(
        old, b'<xdr:cNvPr id="2" name="Picture 1" title="Team logo" descr="Team 12 logo placeholder."/>')
    output = package(parts)
    change = change_from_decision("xl/drawings/drawing2.xml#id=2",
                                  {"title": "Team logo", "description": "Team 12 logo placeholder."})
    assert compare(source, output, [change], hashlib.sha256(output).hexdigest()) == []
    assert compare(source, source, [change]) != []


##  ---- Mapping decisions to changes ----

@pytest.mark.parametrize("target, value, expected", [
    ("xl/drawings/drawing1.xml#id=7", {"title": "T", "description": "D"}, AltText("xl/drawings/drawing1.xml", "7", "T", "D")),
    ("xl/worksheets/sheet2.xml#sheetId=2", {"name": "Costs"}, Rename("2", "Costs")),
    ("xl/worksheets/sheet1.xml#cell=A5", {"text": "Report"}, LinkLabel("xl/worksheets/sheet1.xml", "A5", "Report")),
    ("xl/worksheets/sheet1.xml#range=A1:D9", {"headerRow": 1}, HeaderRow("xl/worksheets/sheet1.xml", "A1:D9")),
    ("xl/tables/table1.xml#tableId=1", {"headerRow": 1}, EnableHeader("xl/tables/table1.xml")),
])
def test_change_from_decision(target, value, expected):
    assert change_from_decision(target, value) == expected


def test_change_from_decision_refuses_unsupported_targets():
    with pytest.raises(ChangeError):
        change_from_decision("xl/drawings/drawing1.xml#xml=/wsDr[1]/twoCellAnchor[1]/pic[1]", {"title": "T"})
