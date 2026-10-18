"""Team 12 shared fixtures and their independent oracle."""

import hashlib
import io
import json
import subprocess
import sys
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
])
def test_worksheet_name_examples_from_contract(name, flagged):
    assert (worksheet_name_finding(name, "xl/worksheets/sheet1.xml", "1", PROFILE) is not None) == flagged


##  ---- Fixture files ----

def test_builder_reproduces_committed_bytes():
    result = subprocess.run([sys.executable, str(ROOT / "scripts" / "build_shared_fixtures.py"), "--check"],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("key", ["clean", "seeded_issues", "corrupt"])
def test_recorded_sha256_matches_file(key):
    entry = EXPECTATIONS["fixtures"][key]
    data = (FIXTURES / entry["file"]).read_bytes()
    assert hashlib.sha256(data).hexdigest() == entry["sha256"]
    assert entry["origin"] == "team12"


@pytest.mark.parametrize("key", ["clean", "seeded_issues"])
def test_oracle_agrees_with_hand_authored_expectations(key):
    entry = EXPECTATIONS["fixtures"][key]
    findings, limitations = evaluate((FIXTURES / entry["file"]).read_bytes(), PROFILE)
    assert findings == entry["findings"]
    assert entry["findings"] == sorted(entry["findings"], key=sort_key)
    assert limitations == []
    assert entry["expected_status"] == ("REVIEW_REQUIRED" if findings else "AUDIT_COMPLETE")


def test_corrupt_fixture_is_unreadable():
    data = (SHARED / "corrupt.xlsx").read_bytes()
    assert data.startswith(b"PK\x03\x04")
    with pytest.raises(zipfile.BadZipFile):
        zipfile.ZipFile(io.BytesIO(data))


@pytest.mark.parametrize("name,sheets", [
    ("clean.xlsx", [("Budget", "visible"), ("Notes", "visible")]),
    ("seeded_issues.xlsx", [("Expenses", "visible"), ("Sheet1", "visible"), (" Sheet03 ", "hidden"),
                            ("Sheet0", "visible")]),
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


@pytest.mark.parametrize("name", ["clean.xlsx", "seeded_issues.xlsx"])
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
    for name in ("clean.xlsx", "seeded_issues.xlsx"):
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
    for name in ("clean.xlsx", "seeded_issues.xlsx"):
        package = zipfile.ZipFile(SHARED / name)
        content_types = ET.fromstring(package.read("[Content_Types].xml"))
        overrides = {o.get("PartName") for o in content_types if o.tag.endswith("Override")}
        defaults = {d.get("Extension") for d in content_types if d.tag.endswith("Default")}
        for part in package.namelist():
            if part != "[Content_Types].xml":
                assert "/" + part in overrides or part.rsplit(".", 1)[-1] in defaults, part
            if part.endswith((".xml", ".rels")):
                ET.fromstring(package.read(part))
