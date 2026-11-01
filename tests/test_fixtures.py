"""Team 12 shared fixtures and their independent oracle."""

import hashlib
import io
import json
import subprocess
import sys
import unicodedata
import warnings
import zipfile
from pathlib import Path

import pytest

from tester.config import FIXTURES
from tester.models import PodProfile
from tester.suite.identity import finding_id, sort_key, trim
from tester.suite.pod_rules import evaluate, worksheet_name_finding

ROOT = Path(__file__).resolve().parent.parent
SHARED = FIXTURES / "shared"
EXPECTATIONS = json.loads((SHARED / "expectations.json").read_text(encoding="utf-8"))
PROFILE = PodProfile.model_validate(json.loads((FIXTURES / "pod_profile.json").read_text(encoding="utf-8")))


##  ---- Identity (ref/phase3.md, "Fixed identifier example") ----

def test_golden_finding_id():
    assert finding_id("0" * 64, "1.0.0", "ALT_TEXT", "Expenses", "xl/drawings/drawing1.xml#id=7") == \
        "502d6624551c9da5c9a80d7efcc04be1119dad4a16f55171487949600a177714"


def test_finding_id_keeps_unicode_unescaped_and_unnormalized():
    composed, decomposed = "Café", "Café"
    assert finding_id("0" * 64, "1.0.0", "WORKSHEET_NAME", composed, "t") != \
        finding_id("0" * 64, "1.0.0", "WORKSHEET_NAME", decomposed, "t")
    payload = json.dumps(["0" * 64, "1.0.0", "WORKSHEET_NAME", composed, "t"], ensure_ascii=False,
                         separators=(",", ":")).encode("utf-8")
    assert finding_id("0" * 64, "1.0.0", "WORKSHEET_NAME", composed, "t") == hashlib.sha256(payload).hexdigest()


def test_trim_uses_the_explicit_white_space_set():
    assert trim(" 　 x  ") == "x"
    assert trim("​") == "​"          # zero-width space is not White_Space


@pytest.mark.parametrize("name,flagged", [
    ("Sheet1", True), ("sheet2", True), ("Sheet01", True), (" Sheet3 ", True),
    ("Sheet0", False), ("Sheet", False), ("Expenses", False), ("Q1 Budget", False), ("Sheet1a", False),
    ("　Sheet2　", True), ("ſheet4", False), ("Sheet３", False), ("Sheet​1", False),
])
def test_worksheet_name_examples_from_contract(name, flagged):
    assert (worksheet_name_finding(name, "xl/worksheets/sheet1.xml", "1", PROFILE) is not None) == flagged


##  ---- Fixture files ----

def test_builder_reproduces_committed_bytes():
    result = subprocess.run([sys.executable, str(ROOT / "scripts" / "build_shared_fixtures.py"), "--check"],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


EDGES = ["unicode", "repeated_ids", "multiple_drawings"]
REJECTED = ["zip_traversal", "zip_duplicate", "xml_dtd", "macro_parts", "encrypted_zip", "protected_sheet",
            "protected_structure"]


@pytest.mark.parametrize("key", ["clean", "seeded_issues", "corrupt", *EDGES, *REJECTED])
def test_recorded_sha256_matches_file(key):
    entry = EXPECTATIONS["fixtures"][key]
    data = (SHARED / entry["file"]).read_bytes()
    assert hashlib.sha256(data).hexdigest() == entry["sha256"]
    assert entry["origin"] == "team12"


def test_pack_loads_as_the_configured_fixture_pack():
    from tester.suite.plan import load_plan
    plan = load_plan(FIXTURES / "manifest.json", FIXTURES / "pod_profile.json", SHARED / "expectations.json")
    assert set(plan["fixtures"]["entries"]) == set(EXPECTATIONS["fixtures"])


@pytest.mark.parametrize("key", ["clean", "seeded_issues", *EDGES])
def test_oracle_agrees_with_hand_authored_expectations(key):
    entry = EXPECTATIONS["fixtures"][key]
    findings, limitations = evaluate((SHARED / entry["file"]).read_bytes(), PROFILE)
    assert findings == entry["findings"]
    assert entry["findings"] == sorted(entry["findings"], key=sort_key)
    assert bool(limitations) is entry.get("limitations_required", False)
    assert entry["expected_status"] == ("REVIEW_REQUIRED" if findings else "AUDIT_COMPLETE")


##  ---- Accepted edge fixtures ----

def edge(key):
    return zipfile.ZipFile(SHARED / f"{key}.xlsx")


MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"


def sheet_names(package):
    import xml.etree.ElementTree as ET
    return [s.get("name") for s in ET.fromstring(package.read("xl/workbook.xml")).iter(f"{{{MAIN}}}sheet")]


def test_unicode_names_are_stored_raw():
    names = sheet_names(edge("unicode"))
    assert names[0] == "Café costs" and names[0] != unicodedata.normalize("NFC", names[0])
    assert "\U0001f4ca Summary" in names and "ｾｰﾙｽ" in names
    ##  Code-point order and UTF-16 order disagree for these two names; the contract uses code points.
    assert "ｾ" < "\U0001f4ca" and "ｾ".encode("utf-16-be") > "\U0001f4ca".encode("utf-16-be")


def test_unicode_near_whitespace_survives_attribute_parsing():
    import xml.etree.ElementTree as ET
    props = {p.get("id"): p for p in ET.fromstring(edge("unicode").read("xl/drawings/drawing1.xml")).iter(f"{XDR}cNvPr")}
    assert props["2"].get("descr") == "​" and trim(props["2"].get("descr"))
    assert props["6"].get("title") == "﻿" and trim(props["6"].get("title"))
    assert props["7"].get("descr") == "\t\n\r " and not trim(props["7"].get("descr"))


def test_repeated_ids_repeat_only_within_one_part():
    import xml.etree.ElementTree as ET
    package = edge("repeated_ids")
    ids = [p.get("id") for p in ET.fromstring(package.read("xl/drawings/drawing1.xml")).iter(f"{XDR}cNvPr")]
    assert ids == ["2", "2", "3", "4", "4", "5"]
    assert [p.get("id") for p in ET.fromstring(package.read("xl/drawings/drawing2.xml")).iter(f"{XDR}cNvPr")] == ["2"]


def test_multiple_drawings_resolve_through_relationships():
    package = edge("multiple_drawings")
    assert sorted(p for p in package.namelist() if p.startswith("xl/drawings/drawing")) == \
        [f"xl/drawings/drawing{n}.xml" for n in range(1, 5)]
    assert b'Target="/xl/drawings/drawing4.xml"' in package.read("xl/worksheets/_rels/sheet5.xml.rels")
    assert b'Target="../drawings/drawing3.xml"' in package.read("xl/worksheets/_rels/sheet1.xml.rels")
    workbook = package.read("xl/workbook.xml")
    assert b'state="hidden"' in workbook and b'state="veryHidden"' in workbook


def test_corrupt_fixture_is_unreadable():
    data = (SHARED / "corrupt.xlsx").read_bytes()
    assert data.startswith(b"PK\x03\x04")
    with pytest.raises(zipfile.BadZipFile):
        zipfile.ZipFile(io.BytesIO(data))


##  ---- Rejected fixtures: exactly one defect each ----

SHEET = "xl/worksheets/sheet1.xml"
BASE_PARTS = ["[Content_Types].xml", "_rels/.rels", "docProps/core.xml", "docProps/app.xml", "xl/workbook.xml",
              "xl/_rels/workbook.xml.rels", "xl/styles.xml", SHEET]


def rejected(key):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        return zipfile.ZipFile(SHARED / f"{key}.xlsx")


def test_rejected_entries_name_the_manifest_cases():
    manifest = json.loads((FIXTURES / "manifest.json").read_text(encoding="utf-8"))
    named = {c["parameters"]["fixture"] for c in manifest["tests"] if c["check"] == "rejected_fixture"}
    assert named == set(REJECTED)
    for key in REJECTED:
        entry = EXPECTATIONS["fixtures"][key]
        assert (entry["kind"], entry["http_status"], entry["error_code"]) == ("rejected", 422, None)
        assert entry["upload_name"] == entry["file"] == f"{key}.xlsx"


def test_zip_traversal_adds_only_an_escaping_entry():
    assert rejected("zip_traversal").namelist() == BASE_PARTS + ["../outside.xml"]


def test_zip_duplicate_repeats_one_path_with_different_contents():
    package = rejected("zip_duplicate")
    assert package.namelist() == BASE_PARTS + [SHEET]
    first, second = [package.open(info).read() for info in package.infolist() if info.filename == SHEET]
    assert first != second


def test_xml_dtd_declares_only_an_internal_entity():
    package = rejected("xml_dtd")
    sheet = package.read(SHEET)
    assert b'<!DOCTYPE worksheet [<!ENTITY team "Team 12">]>' in sheet and b"&team;" in sheet
    assert b"SYSTEM" not in sheet and b"PUBLIC" not in sheet
    assert all(b"<!DOCTYPE" not in package.read(p) for p in BASE_PARTS if p != SHEET)


def test_macro_parts_is_an_xlsx_with_an_inert_vba_part():
    package = rejected("macro_parts")
    assert package.namelist() == BASE_PARTS + ["xl/vbaProject.bin"]
    types = package.read("[Content_Types].xml")
    assert b"spreadsheetml.sheet.main+xml" in types and b"macroEnabled" not in types
    assert b'ContentType="application/vnd.ms-office.vbaProject"' in types
    assert b"relationships/vbaProject" in package.read("xl/_rels/workbook.xml.rels")
    assert package.read("xl/vbaProject.bin").startswith(bytes.fromhex("d0cf11e0a1b11ae1"))


def test_encrypted_zip_encrypts_every_entry():
    package = rejected("encrypted_zip")
    assert package.namelist() == BASE_PARTS
    assert all(info.flag_bits & 1 for info in package.infolist())
    with pytest.raises(RuntimeError, match="password required"):
        package.read("xl/workbook.xml")
    import xml.etree.ElementTree as ET
    for part in BASE_PARTS:
        ET.fromstring(package.read(part, pwd=b"team12-fixture"))


@pytest.mark.parametrize("key, sheet_locked, structure_locked", [
    ("protected_sheet", True, False), ("protected_structure", False, True)])
def test_protection_fixtures_isolate_one_lock(key, sheet_locked, structure_locked):
    import openpyxl
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        book = openpyxl.load_workbook(SHARED / f"{key}.xlsx")
    assert book.worksheets[0].protection.sheet is sheet_locked
    assert bool(book.security and book.security.lockStructure) is structure_locked
    assert rejected(key).namelist() == BASE_PARTS


@pytest.mark.parametrize("name,sheets", [
    ("clean.xlsx", [("Budget", "visible"), ("Notes", "visible")]),
    ("seeded_issues.xlsx", [("Expenses", "visible"), ("Sheet1", "visible"), (" Sheet03 ", "hidden"),
                            ("Sheet0", "visible")]),
    ("unicode.xlsx", [("Café costs", "visible"), ("　Sheet2　", "visible"), ("Sheet３", "visible"),
                      ("ſheet4", "visible"), ("\U0001f4ca Summary", "visible"),
                      ("ｾｰﾙｽ", "visible")]),
    ("repeated_ids.xlsx", [("Expenses", "visible"), ("Receipts", "visible")]),
    ("multiple_drawings.xlsx", [("Summary", "visible"), ("Expenses", "visible"), ("Hidden costs", "hidden"),
                                ("Notes", "visible"), ("Archive", "veryHidden")]),
])
def test_valid_fixtures_load_in_openpyxl(name, sheets):
    import openpyxl
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        workbook = openpyxl.load_workbook(SHARED / name)
    assert [(ws.title, ws.sheet_state) for ws in workbook.worksheets] == sheets
    assert workbook.properties.title and workbook.properties.language == "en-US"


XDR = "{http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing}"
DRAW = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
RID = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"


def drawing_parts(name):
    import xml.etree.ElementTree as ET
    package = zipfile.ZipFile(SHARED / name)
    for part in package.namelist():
        if part.startswith("xl/drawings/drawing") and part.endswith(".xml"):
            rels_part = part.replace("drawings/", "drawings/_rels/") + ".rels"
            rels = {r.get("Id"): r.get("Target") for r in ET.fromstring(package.read(rels_part))}
            yield package, part, ET.fromstring(package.read(part)), rels


VALID = ["clean.xlsx", "seeded_issues.xlsx", *(f"{key}.xlsx" for key in EDGES)]


@pytest.mark.parametrize("name", VALID)
def test_objects_are_visible(name):
    ##  Regression: anchors once started and ended in the same column, so every object had zero width.
    for package, part, root, rels in drawing_parts(name):
        for anchor in root.findall(f"{XDR}twoCellAnchor"):
            start, end = anchor.find(f"{XDR}from"), anchor.find(f"{XDR}to")
            for axis in ("col", "row"):
                assert int(end.find(f"{XDR}{axis}").text) > int(start.find(f"{XDR}{axis}").text), part
        for shape in root.iter(f"{XDR}sp"):
            properties = shape.find(f"{XDR}spPr")
            assert properties.find(f"{DRAW}solidFill") is not None and properties.find(f"{DRAW}ln") is not None
            assert "".join(t.text for t in shape.iter(f"{DRAW}t")).strip(), "shape has no visible label"
        for blip in root.iter(f"{DRAW}blip"):
            media = "xl/" + rels[blip.get(f"{RID}embed")].removeprefix("../")
            assert package.read(media)[:8] in (b"\x89PNG\r\n\x1a\n",) or package.read(media)[:3] == b"\xff\xd8\xff"


def test_charts_have_visible_titles():
    for name in VALID:
        package = zipfile.ZipFile(SHARED / name)
        for part in (p for p in package.namelist() if p.startswith("xl/charts/")):
            assert b"<c:title>" in package.read(part) and b'<c:autoTitleDeleted val="0"/>' in package.read(part)


def test_readme_matches_recorded_hashes_and_finding_ids():
    readme = (SHARED / "README.md").read_text(encoding="utf-8")
    seeded = EXPECTATIONS["fixtures"]["seeded_issues"]
    for entry in EXPECTATIONS["fixtures"].values():
        assert entry["sha256"] in readme
    for finding in seeded["findings"]:
        assert finding_id(seeded["sha256"], EXPECTATIONS["ruleset_version"], finding["ruleId"],
                          finding["worksheet"], finding["target"]) in readme


def test_every_package_part_is_declared_and_well_formed():
    import xml.etree.ElementTree as ET
    for name in VALID:
        package = zipfile.ZipFile(SHARED / name)
        content_types = ET.fromstring(package.read("[Content_Types].xml"))
        overrides = {o.get("PartName") for o in content_types if o.tag.endswith("Override")}
        defaults = {d.get("Extension") for d in content_types if d.tag.endswith("Default")}
        for part in package.namelist():
            if part != "[Content_Types].xml":
                assert "/" + part in overrides or part.rsplit(".", 1)[-1] in defaults, part
            if part.endswith((".xml", ".rels")):
                ET.fromstring(package.read(part))
