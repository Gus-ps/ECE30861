"""Team 12's Phase 4 fixtures (tester/fixtures/phase4/) and their hand-authored expectations.

ALT_TEXT and WORKSHEET_NAME rows are cross-checked against tester/suite/pod_rules.py. The
other four rules have no oracle in the tester, so these tests re-derive each expected row
from the package XML with small, separately written checks (W3C contrast, four-neighbour
components, populated merges, the spec 7.6 link vocabulary). They were written after the
expectations; a disagreement means one of the two is wrong and needs a person to decide.
"""

import hashlib
import io
import json
import re
import subprocess
import sys
import warnings
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import pytest

from tester.config import FIXTURES
from tester.models import FixturePack, PodProfile
from tester.suite.comparator import change_from_decision, compare
from tester.suite.identity import finding_id, sort_key, trim
from tester.suite.pod_rules import evaluate

ROOT = Path(__file__).resolve().parent.parent
PACK = FIXTURES / "phase4"
EXPECTATIONS = json.loads((PACK / "expectations.json").read_text(encoding="utf-8"))
PHASE3_PROFILE = PodProfile.model_validate(json.loads((FIXTURES / "pod_profile.json").read_text(encoding="utf-8")))
CORRECTION_KEYS = ["alt_supported", "rename_references", "link_supported", "header_range", "header_disabled_table"]
KEYS = ["clean_all_six", "seeded_all_six", *CORRECTION_KEYS, "mixed_decisions", "review_only", "unsupported_edits",
        "preservation_rich", "large_preservation", "inactive_protection", "unicode", "repeated_ids", "multiple_drawings"]
##  Where ruleset 2.0.0 departs from the Phase 3 oracle (VML, duplicate IDs, unsafe rename);
##  these are checked against the XML directly below.
ORACLE_KEYS = [k for k in KEYS if k not in ("unsupported_edits", "preservation_rich", "repeated_ids")]
VECTOR_KEYS = ["table_header_vectors", "merge_vectors", "link_vectors", "contrast_vectors"]
KEYS += VECTOR_KEYS
ORACLE_KEYS += VECTOR_KEYS
##  The simple re-derivations below skip only their own rule's vector fixture, whose forms
##  (theme/indexed colours, overlays, formula and range links, header defects) they do not model.
COLOR_KEYS = [k for k in KEYS if k != "contrast_vectors"]
LINK_KEYS = [k for k in KEYS if k != "link_vectors"]
TABLE_KEYS = [k for k in KEYS if k != "table_header_vectors"]
REJECTED = ["corrupt", "zip_traversal", "zip_duplicate", "xml_dtd", "macro_parts", "encrypted_zip", "protected_sheet",
            "protected_structure"]
M = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
XDR = "{http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
P = "{http://schemas.openxmlformats.org/package/2006/relationships}"


def entry(key):
    return EXPECTATIONS["fixtures"][key]


def expected(key, *rules):
    return [f for f in entry(key)["findings"] if not rules or f["ruleId"] in rules]


##  ---- Files, hashes, pack ----

def test_builder_reproduces_committed_bytes():
    result = subprocess.run([sys.executable, str(ROOT / "scripts" / "build_phase4_fixtures.py"), "--check"],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("key", KEYS)
def test_recorded_sha256_and_section_15_2_fields(key):
    item = entry(key)
    assert hashlib.sha256((PACK / item["file"]).read_bytes()).hexdigest() == item["sha256"]
    for field in ("kind", "file", "origin", "upload_name", "http_status", "expected_status", "findings",
                  "limitation_facts", "review", "excel_open"):
        assert field in item, field
    assert item["review"] == {"reviewers": [], "date": None, "decisions": None}


##  Every accepted source fixture was opened in Excel on 2026-11-01; only these repaired, with the
##  parts Excel's repair log named. Rejected inputs are not opened (several are meant not to open).
EXCEL_REPAIRED = {"table_header_vectors": ["xl/tables/table3.xml", "xl/tables/table4.xml"]}


@pytest.mark.parametrize("key", [*KEYS, "clean", "seeded_issues"])
def test_excel_open_is_recorded_and_repairs_are_the_deliberately_invalid_tables(key):
    record = entry(key)["excel_open"]
    assert record["date"] == "2026-11-01" and record["expected"] is True
    if key not in EXCEL_REPAIRED:
        assert (record["result"], record["repaired_parts"]) == ("opened_clean", [])
        return
    assert record["result"] == "repair_prompt" and record["repaired_parts"] == EXCEL_REPAIRED[key]
    ##  Each repaired part is a table whose expected finding is MANUAL_REVIEW, so no correction
    ##  output ever has to edit it.
    manual = {f["target"].split("#")[0] for f in entry(key)["findings"] if f["classification"] == "MANUAL_REVIEW"}
    assert set(record["repaired_parts"]) <= manual


@pytest.mark.parametrize("key", REJECTED)
def test_rejected_inputs_have_no_excel_record(key):
    assert entry(key)["excel_open"] is None


def test_pack_validates_with_ruleset_2():
    pack = FixturePack.model_validate(EXPECTATIONS)
    assert pack.ruleset_version == "2.0.0" and set(pack.fixtures) == {*KEYS, *REJECTED, "clean", "seeded_issues"}


@pytest.mark.parametrize("key", REJECTED)
def test_rejected_inputs_are_the_phase3_bytes(key):
    assert (PACK / f"{key}.xlsx").read_bytes() == (FIXTURES / "shared" / f"{key}.xlsx").read_bytes()
    assert (entry(key)["kind"], entry(key)["http_status"], entry(key)["error_code"]) == ("rejected", 422, None)


@pytest.mark.parametrize("alias, source", [("clean", "clean_all_six"), ("seeded_issues", "seeded_all_six")])
def test_phase3_numbered_aliases_point_at_the_all_six_files(alias, source):
    assert entry(alias)["file"] == entry(source)["file"] and entry(alias)["findings"] == entry(source)["findings"]
    assert entry(alias)["expected_status"] == entry(source)["expected_status"]


def test_repeated_ids_targets_match_the_spec_vector():
    vectors = json.loads((ROOT / "ref" / "Phase4_Agent_Context_Pack" / "phase4-policy-vectors.json")
                         .read_text(encoding="utf-8"))["duplicate_id_targets"]
    manual = [f["target"] for f in entry("repeated_ids")["findings"] if f["classification"] == "MANUAL_REVIEW"]
    assert manual == vectors
    ids = [p.get("id") for p in Workbook("repeated_ids").xml("xl/drawings/drawing1.xml").iter(f"{XDR}cNvPr")]
    assert ids == ["2", "2", "3"]


def test_unsupported_edits_xml_facts():
    book = Workbook("unsupported_edits")
    drawing = book.xml("xl/drawings/drawing1.xml")
    assert [p.get("id") for p in drawing.iter(f"{XDR}cNvPr")] == ["2", "3", "3"]
    assert any(e.tag.endswith("decorative") for e in drawing.iter())
    assert b"INDIRECT(" in book.zip.read("xl/worksheets/sheet2.xml")
    assert b"<f>HYPERLINK(&quot;" in book.zip.read("xl/worksheets/sheet1.xml") or \
        b'<f>HYPERLINK("' in book.zip.read("xl/worksheets/sheet1.xml")
    assert all(f["classification"] == "MANUAL_REVIEW" for f in entry("unsupported_edits")["findings"])
    assert entry("unsupported_edits")["expected_status"] == "REVIEW_REQUIRED"


def test_preservation_rich_contains_every_section_11_feature():
    book = Workbook("preservation_rich")
    names = set(book.zip.namelist())
    assert {"xl/comments1.xml", "xl/drawings/vmlDrawing1.vml", "xl/printerSettings/printerSettings1.bin",
            "xl/charts/chart1.xml", "xl/tables/table2.xml"} <= names
    sheet = book.zip.read("xl/worksheets/sheet1.xml")
    for marker in (b"<conditionalFormatting", b"<dataValidations", b"<legacyDrawing", b"<pageSetup", b"<f>SUM(B2:B4)</f>"):
        assert marker in sheet, marker
    assert b'state="hidden"' in book.zip.read("xl/workbook.xml") and b"<definedName" in book.zip.read("xl/workbook.xml")
    assert b'id="_x0000_s1025"' in book.zip.read("xl/drawings/vmlDrawing1.vml")


def test_large_preservation_exceeds_two_mib():
    assert (PACK / "large_preservation.xlsx").stat().st_size > 2 * 2 ** 20


@pytest.mark.parametrize("key", KEYS)
def test_findings_are_sorted_and_status_follows_section_9(key):
    findings = entry(key)["findings"]
    assert findings == sorted(findings, key=sort_key)
    classes = {f["classification"] for f in findings}
    status = ("AUDIT_COMPLETE" if not findings else "REMEDIATION_AVAILABLE" if "REQUIRES_USER_INPUT" in classes
              else "REVIEW_REQUIRED")
    assert entry(key)["expected_status"] == status


@pytest.mark.parametrize("key", KEYS)
def test_files_load_in_openpyxl(key):
    import openpyxl
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        openpyxl.load_workbook(PACK / f"{key}.xlsx")


##  ---- ALT_TEXT and WORKSHEET_NAME: the independent oracle ----

@pytest.mark.parametrize("key", ORACLE_KEYS)
def test_oracle_agrees_on_alt_text_and_worksheet_names(key):
    findings, limitations = evaluate((PACK / f"{key}.xlsx").read_bytes(), PHASE3_PROFILE)
    assert findings == expected(key, "ALT_TEXT", "WORKSHEET_NAME")
    assert limitations == []


##  ---- The other four rules, re-derived from the package XML ----

class Workbook:
    def __init__(self, key):
        self.zip = zipfile.ZipFile(PACK / f"{key}.xlsx")
        styles = self.xml("xl/styles.xml")
        fonts = [(f.find(f"{M}color").get("rgb") or "  ")[2:] if f.find(f"{M}color") is not None else None
                 for f in styles.find(f"{M}fonts")]
        fills = [f.find(f"{M}patternFill") for f in styles.find(f"{M}fills")]
        self.xfs = []
        for xf in styles.find(f"{M}cellXfs"):
            fill = fills[int(xf.get("fillId"))]
            solid = fill is not None and fill.get("patternType") == "solid"
            self.xfs.append((fonts[int(xf.get("fontId"))], fill.find(f"{M}fgColor").get("rgb")[2:] if solid else None))
        rels = {r.get("Id"): r.get("Target") for r in self.xml("xl/_rels/workbook.xml.rels")}
        self.sheets = [(s.get("name"), "xl/" + rels[s.get(f"{R}id")]) for s in self.xml("xl/workbook.xml").iter(f"{M}sheet")]
        self.strings = ["".join(t.text or "" for t in si.iter(f"{M}t")) for si in self.xml("xl/sharedStrings.xml")] \
            if "xl/sharedStrings.xml" in self.zip.namelist() else []

    def xml(self, part):
        return ET.fromstring(self.zip.read(part))

    def sheet_rels(self, part):
        path = part.replace("worksheets/", "worksheets/_rels/") + ".rels"
        if path not in self.zip.namelist():
            return {}
        return {r.get("Id"): r for r in self.xml(path).iter(f"{P}Relationship")}

    def cells(self, part):
        ##  {ref: (text, style index, is formula)} for populated cells.
        out = {}
        for c in self.xml(part).iter(f"{M}c"):
            formula = c.find(f"{M}f") is not None
            if c.get("t") == "inlineStr":
                text = "".join(t.text or "" for t in c.iter(f"{M}t"))
            elif c.get("t") == "s":
                text = self.strings[int(c.findtext(f"{M}v"))]
            else:
                text = c.findtext(f"{M}v")
            if formula or trim(text or ""):
                out[c.get("r")] = (text or "", int(c.get("s", "0")), formula)
        return out

    def tables(self, part):
        ##  [(table part, root)] reachable from the sheet's table relationships.
        return [("xl/tables/" + r.get("Target").rsplit("/", 1)[-1], self.xml("xl/tables/" + r.get("Target").rsplit("/", 1)[-1]))
                for r in self.sheet_rels(part).values() if r.get("Type").endswith("/table")]


def coords(ref):
    letters, digits = re.fullmatch(r"([A-Z]+)([0-9]+)", ref).groups()
    col = 0
    for letter in letters:
        col = col * 26 + ord(letter) - 64
    return int(digits), col


def in_range(ref, rng):
    (r1, c1), (r2, c2) = (coords(x) for x in rng.split(":"))
    r, c = coords(ref)
    return r1 <= r <= r2 and c1 <= c <= c2


def contrast(font, fill):
    def luminance(hex_rgb):
        def channel(value):
            value /= 255
            return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
        r, g, b = (int(hex_rgb[i:i + 2], 16) for i in (0, 2, 4))
        return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)
    high, low = sorted((luminance(font), luminance(fill)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def test_contrast_matches_the_policy_vectors():
    vectors = json.loads((ROOT / "ref" / "Phase4_Agent_Context_Pack" / "phase4-policy-vectors.json")
                         .read_text(encoding="utf-8"))["contrast"]
    for vector in vectors:
        assert contrast(vector["font_rgb"], vector["fill_rgb"]) == pytest.approx(vector["ratio"], abs=1e-9)


def neutral(rgb):
    return rgb[0:2] == rgb[2:4] == rgb[4:6]


@pytest.mark.parametrize("key", COLOR_KEYS)
def test_color_contrast_rows(key):
    book, found = Workbook(key), []
    for name, part in book.sheets:
        for ref, (_text, style, _formula) in book.cells(part).items():
            font, fill = book.xfs[style]
            assert fill is not None, f"{ref} relies on the missing-fill display assumption"
            if not (neutral(font) and neutral(fill)) or contrast(font, fill) < 4.5:
                found.append({"ruleId": "COLOR_CONTRAST", "category": "COLOR_OR_CONTRAST", "worksheet": name,
                              "target": f"{part}#cell={ref}", "classification": "MANUAL_REVIEW"})
    assert sorted(found, key=sort_key) == expected(key, "COLOR_CONTRAST")


@pytest.mark.parametrize("key", KEYS)
def test_merged_cells_rows(key):
    book, found = Workbook(key), []
    for name, part in book.sheets:
        populated = book.cells(part)
        for merge in book.xml(part).iter(f"{M}mergeCell"):
            if any(in_range(ref, merge.get("ref")) for ref in populated):
                found.append({"ruleId": "MERGED_CELLS", "category": "MERGED_CELLS", "worksheet": name,
                              "target": f"{part}#merge={merge.get('ref')}", "classification": "MANUAL_REVIEW"})
    assert found == expected(key, "MERGED_CELLS")


AMBIGUOUS = {"click here", "here", "link", "more", "read more", "learn more", "website", "url"}


def ambiguous(label, destination):
    text = re.sub(r"\s+", " ", trim(label)).casefold()
    text = text[:-1] if text[-1:] in (".", "!", "?") else text
    raw = text.startswith(("http://", "https://", "www.", "mailto:")) or text == trim(destination).casefold()
    return not text or text in AMBIGUOUS or raw


def test_link_predicate_matches_the_policy_vectors():
    vectors = json.loads((ROOT / "ref" / "Phase4_Agent_Context_Pack" / "phase4-policy-vectors.json")
                         .read_text(encoding="utf-8"))["ambiguous_labels"]
    for vector in vectors:
        assert ambiguous(vector["label"], vector["destination"]) is vector["triggers"], vector


@pytest.mark.parametrize("key", LINK_KEYS)
def test_link_text_rows(key):
    book, found = Workbook(key), []
    for name, part in book.sheets:
        cells, rels = book.cells(part), book.sheet_rels(part)
        for link in book.xml(part).iter(f"{M}hyperlink"):
            label = cells.get(link.get("ref"), ("",))[0]
            rid = link.get(f"{R}id")
            destination = rels[rid].get("Target") if rid else link.get("location")
            if ambiguous(label, destination):
                ##  Single cell, inline string, no formula, no merge: the safe simple profile.
                found.append({"ruleId": "LINK_TEXT", "category": "LINK_TEXT", "worksheet": name,
                              "target": f"{part}#cell={link.get('ref')}", "classification": "REQUIRES_USER_INPUT"})
        root = book.xml(part)
        locations = {}
        def index(element, path):
            locations[element] = path
            counts = {}
            for child in element:
                tag = child.tag.rsplit('}', 1)[-1]
                counts[tag] = counts.get(tag, 0) + 1
                index(child, path + '/' + tag + '[' + str(counts[tag]) + ']')
        index(root, '/worksheet[1]')
        for c in root.iter(f"{M}c"):
            ##  A HYPERLINK formula with literal arguments is screened on its label; never editable.
            match = re.fullmatch(r'(?:_xlfn\.)?HYPERLINK\("([^"]*)"(?:,"([^"]*)")?\)', c.findtext(f"{M}f") or "", re.I)
            if match and ambiguous(match[2] if match[2] is not None else match[1], match[1]):
                found.append({"ruleId": "LINK_TEXT", "category": "LINK_TEXT", "worksheet": name,
                              "target": f"{part}#xml={locations[c]}", "classification": "MANUAL_REVIEW"})
    assert sorted(found, key=sort_key) == expected(key, "LINK_TEXT")


def components(refs):
    ##  Four-neighbour connected components of cell references.
    remaining, groups = set(refs), []
    while remaining:
        stack, group = [remaining.pop()], set()
        while stack:
            ref = stack.pop()
            group.add(ref)
            r, c = coords(ref)
            for other in list(remaining):
                if abs(coords(other)[0] - r) + abs(coords(other)[1] - c) == 1:
                    remaining.discard(other)
                    stack.append(other)
        groups.append(group)
    return groups


@pytest.mark.parametrize("key", TABLE_KEYS)
def test_table_header_rows_and_the_limitation_fact(key):
    book, found, small = Workbook(key), [], False
    for name, part in book.sheets:
        cells = book.cells(part)
        covered = set()
        for table_part, root in book.tables(part):
            covered |= {ref for ref in cells if in_range(ref, root.get("ref"))}
            first = coords(root.get("ref").split(":")[0])
            labels = [text for ref, (text, _s, _f) in sorted(cells.items(), key=lambda kv: coords(kv[0]))
                      if coords(ref)[0] == first[0] and in_range(ref, root.get("ref"))]
            columns = [c.get("name") for c in root.find(f"{M}tableColumns")]
            if root.get("headerRowCount", "1") == "0":
                assert labels == columns      # the safe EnableHeader profile
                found.append({"ruleId": "TABLE_HEADER", "category": "TABLE_STRUCTURE", "worksheet": name,
                              "target": f"{table_part}#tableId={root.get('id')}", "classification": "REQUIRES_USER_INPUT"})
            else:
                assert labels == columns and len(set(columns)) == len(columns)
        for group in components(set(cells) - covered):
            rows = {coords(ref)[0] for ref in group}
            cols = {coords(ref)[1] for ref in group}
            if len(rows) < 2 or len(cols) < 2:
                small = True
                continue
            dense = len(group) == len(rows) * len(cols)
            top = [cells[ref] for ref in group if coords(ref)[0] == min(rows)]
            safe = dense and all(not formula and text.strip() for text, _s, formula in top) \
                and len({t.casefold() for t, _s, _f in top}) == len(top)
            ref = (f"{_letters(min(cols))}{min(rows)}:{_letters(max(cols))}{max(rows)}")
            found.append({"ruleId": "TABLE_HEADER", "category": "TABLE_STRUCTURE", "worksheet": name,
                          "target": f"{part}#range={ref}",
                          "classification": "REQUIRES_USER_INPUT" if safe else "MANUAL_REVIEW"})
    assert sorted(found, key=sort_key) == expected(key, "TABLE_HEADER")
    assert small is any("single-cell" in fact for fact in entry(key)["limitation_facts"])


def _letters(column):
    out = ""
    while column:
        column, remainder = divmod(column - 1, 26)
        out = chr(65 + remainder) + out
    return out


##  ---- Vector fixtures ----

@pytest.mark.parametrize("key", VECTOR_KEYS)
def test_vectors_partition_the_fixture_findings(key):
    vectors = entry(key)["vectors"]
    union = sorted({json.dumps(f, sort_keys=True) for v in vectors.values() for f in v["findings"]})
    assert union == sorted(json.dumps(f, sort_keys=True) for f in entry(key)["findings"])
    for test_id, vector in vectors.items():
        assert vector["scope"], test_id
        assert all(f["ruleId"] == vector["rule"] for f in vector["findings"]), test_id
        assert set(vector["limitation_facts"]) <= set(entry(key)["limitation_facts"]), test_id


def tint(hex_rgb, t):
    ##  Spec 7.7: apply tint to HSL lightness, convert back, clamp, round half up.
    import colorsys
    from decimal import ROUND_HALF_UP, Decimal
    r, g, b = (int(hex_rgb[i:i + 2], 16) / 255 for i in (0, 2, 4))
    h, lightness, s = colorsys.rgb_to_hls(r, g, b)
    lightness = lightness * (1 + t) if t < 0 else lightness * (1 - t) + t
    out = colorsys.hls_to_rgb(h, lightness, s)
    return "".join(f"{int(Decimal(min(max(c, 0), 1) * 255).quantize(0, ROUND_HALF_UP)):02X}" for c in out)


def test_tint_matches_the_policy_vectors_and_the_theme_rows():
    vectors = json.loads((ROOT / "ref" / "Phase4_Agent_Context_Pack" / "phase4-policy-vectors.json")
                         .read_text(encoding="utf-8"))["tint"]
    for vector in vectors:
        assert tint(vector["base_rgb"], vector["tint"]) == vector["expected_rgb"], vector
    rows = {"A1": tint("336699", -1), "A3": tint("336699", 0.5), "A5": tint("000000", 0.5), "A7": tint("000000", 0.25)}
    assert rows == {"A1": "000000", "A3": "8CB2D9", "A5": "808080", "A7": "404040"}
    flagged = {ref for ref, rgb in rows.items() if not neutral(rgb) or contrast(rgb, "FFFFFF") < 4.5}
    expected_refs = {f["target"].rsplit("=", 1)[1] for f in entry("contrast_vectors")["vectors"]["P4-RULE-COLOR-THEME-TINT"]["findings"]}
    assert flagged == expected_refs == {"A3", "A5"}


def test_contrast_vectors_large_text_and_palette():
    large = {"A1": (18, False, "959595"), "A3": (18, False, "949494"), "A5": (14, True, "949494"), "A7": (14, False, "949494")}
    flagged = {ref for ref, (size, bold, rgb) in large.items()
               if contrast(rgb, "FFFFFF") < (3.0 if size >= 18 or (size >= 14 and bold) else 4.5)}
    expected_refs = {f["target"].rsplit("=", 1)[1] for f in entry("contrast_vectors")["vectors"]["P4-RULE-COLOR-LARGE-TEXT"]["findings"]}
    assert flagged == expected_refs == {"A1", "A7"}
    palette = [c.get("rgb") for c in Workbook("contrast_vectors").xml("xl/styles.xml").iter(f"{M}rgbColor")]
    assert len(palette) == 64 and palette[10] == "FF000000" and palette[12] == "FF0000FF"


def test_every_seeded_rule_is_covered_and_clean_has_none():
    rules = {f["ruleId"] for f in entry("seeded_all_six")["findings"]}
    assert rules == {"ALT_TEXT", "WORKSHEET_NAME", "TABLE_HEADER", "MERGED_CELLS", "LINK_TEXT", "COLOR_CONTRAST"}
    assert {f["classification"] for f in entry("seeded_all_six")["findings"]} == {"REQUIRES_USER_INPUT",
                                                                                   "MANUAL_REVIEW"}
    assert entry("clean_all_six")["findings"] == [] and entry("clean_all_six")["limitation_facts"] == []


@pytest.mark.parametrize("key", ["seeded_all_six", *CORRECTION_KEYS])
def test_corrections_cover_exactly_the_user_input_findings(key):
    targets = [f["target"] for f in entry(key)["findings"] if f["classification"] == "REQUIRES_USER_INPUT"]
    assert [c["target"] for c in entry(key)["corrections"]] == targets
    for correction in entry(key)["corrections"]:
        change_from_decision(correction["target"], correction["value"])       # a supported APPLY value


@pytest.mark.parametrize("key", ["mixed_decisions", "preservation_rich", "large_preservation"])
def test_decision_set_targets_are_findings(key):
    targets = {f["target"] for f in entry(key)["findings"]}
    for name, decisions in entry(key)["decision_sets"].items():
        assert {d["target"] for d in decisions} <= targets, name


@pytest.mark.parametrize("key", CORRECTION_KEYS)
def test_correction_fixtures_have_only_their_targets(key):
    assert all(f["classification"] == "REQUIRES_USER_INPUT" for f in entry(key)["findings"])
    assert entry(key)["limitation_facts"] == [] and entry(key)["expected_status"] == "REMEDIATION_AVAILABLE"


##  ---- Correction effects: a hand-made output must pass the comparator ----
##  Each expected output is the source with the entry's described effect applied as plain
##  string edits, so it does not depend on the comparator's own model of the changes.

TABLE_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.table+xml"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
HEAD = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'


def new_table(table_id, name, ref, columns):
    cols = "".join(f'<tableColumn id="{i}" name="{c}"/>' for i, c in enumerate(columns, start=1))
    return (f'{HEAD}<table xmlns="{M[1:-1]}" id="{table_id}" name="{name}" displayName="{name}" ref="{ref}" '
            f'headerRowCount="1"><tableColumns count="{len(columns)}">{cols}</tableColumns></table>')


def add_table(parts, sheet_part, rels_part, rid, table_number, table_xml, existing_rels=True):
    parts[f"xl/tables/table{table_number}.xml"] = table_xml.encode()
    rel = f'<Relationship Id="{rid}" Type="{REL_NS}/table" Target="../tables/table{table_number}.xml"/>'
    if existing_rels:
        parts[rels_part] = parts[rels_part].replace(b"</Relationships>", rel.encode() + b"</Relationships>")
    else:
        parts[rels_part] = (f'{HEAD}<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                            f"{rel}</Relationships>").encode()
    parts[sheet_part] = parts[sheet_part].replace(
        b"</worksheet>", f'<tableParts count="1"><tablePart r:id="{rid}"/></tableParts></worksheet>'.encode())
    parts["[Content_Types].xml"] = parts["[Content_Types].xml"].replace(
        b"</Types>", f'<Override PartName="/xl/tables/table{table_number}.xml" ContentType="{TABLE_TYPE}"/></Types>'.encode())


def edit(parts, part, *pairs):
    for old, new in pairs:
        assert parts[part].count(old.encode()) == 1, (part, old)
        parts[part] = parts[part].replace(old.encode(), new.encode())


def apply_alt_supported(parts):
    edit(parts, "xl/drawings/drawing1.xml",
         ('id="2" name="Picture 1" title="Logo"/>', 'id="2" name="Picture 1" title="Team logo" descr="Team 12 logo placeholder."/>'),
         ('id="3" name="Chart 2"/>', 'id="3" name="Chart 2" title="Costs by item" '
                                     'descr="Column chart: rent $1,200, travel $300, supplies $200."/>'),
         ('id="4" name="Rectangle 3" title=""', 'id="4" name="Rectangle 3" title="Budget note"'),
         ('id="5" name="Straight Arrow Connector 4"/>', 'id="5" name="Straight Arrow Connector 4" title="Arrow to rent" '
                                                        'descr="Arrow pointing from the note to the rent row."/>'),
         ('id="6" name="TextBox 5" title="Instructions"/>', 'id="6" name="TextBox 5" title="Instructions" '
                                                            'descr="Text box explaining that amounts are in US dollars. "/>'))


def apply_rename_references(parts):
    q = "'Q1 Bob''s Costs'"
    edit(parts, "xl/workbook.xml", ('<sheet name="Sheet1" sheetId="1"', '<sheet name="Q1 Bob\'s Costs" sheetId="1"'),
         (">Sheet1!$B$2:$B$4<", f">{q}!$B$2:$B$4<"), (">Sheet1!$B$2<", f">{q}!$B$2<"))
    edit(parts, "xl/worksheets/sheet2.xml", ("SUM(Sheet1!B2:B4)", f"SUM({q}!B2:B4)"),
         ("<f>'Sheet1'!B2+", f"<f>{q}!B2+"), ("+Sheet1!$B$3<", f"+{q}!$B$3<"),
         ("<formula>Sheet1!$B$2", f"<formula>{q}!$B$2"), ("<formula1>Sheet1!$A$2", f"<formula1>{q}!$A$2"),
         ('location="Sheet1!A1"', f'location="{q}!A1"'))
    parts["xl/charts/chart1.xml"] = parts["xl/charts/chart1.xml"].replace(b"'Sheet1'!", f"{q}!".encode())


def apply_link_supported(parts):
    edit(parts, "xl/worksheets/sheet1.xml",
         ('<c r="A2" s="0" t="s"><v>0</v></c>', '<c r="A2" s="0" t="inlineStr"><is><t>Team 12 budget guidance</t></is></c>'),
         ('display="click here"', 'display="Team 12 budget guidance"'),
         ("<t>here</t>", "<t>=Board minutes 2026</t>"))


def apply_header_range(parts):
    add_table(parts, "xl/worksheets/sheet1.xml", "xl/worksheets/_rels/sheet1.xml.rels", "rId1", 2,
              new_table(2, "A11yTable2_1", "A1:D4", ["Item", "Q1", "Q2", "Total"]), existing_rels=False)


def apply_header_disabled_table(parts):
    edit(parts, "xl/tables/table1.xml", ('headerRowCount="0"', 'headerRowCount="1"'))


def apply_seeded_all_six(parts):
    edit(parts, "xl/drawings/drawing1.xml",
         ('id="2" name="Picture 1" title="Logo"/>', 'id="2" name="Picture 1" title="Team logo" descr="Team 12 logo placeholder."/>'))
    edit(parts, "xl/workbook.xml", ('<sheet name="Sheet1"', '<sheet name="Quarterly costs"'))
    edit(parts, "xl/worksheets/sheet2.xml", ("Sheet1!B2+Sheet1!C2", "'Quarterly costs'!B2+'Quarterly costs'!C2"),
         ("Sheet1!B3+Sheet1!C3", "'Quarterly costs'!B3+'Quarterly costs'!C3"))
    parts["xl/charts/chart1.xml"] = parts["xl/charts/chart1.xml"].replace(b"'Sheet1'!", b"'Quarterly costs'!")
    edit(parts, "xl/worksheets/sheet1.xml", ("<t>click here</t>", "<t>Team 12 budget guidance</t>"))
    add_table(parts, "xl/worksheets/sheet1.xml", "xl/worksheets/_rels/sheet1.xml.rels", "rId3", 2,
              new_table(2, "A11yTable2", "A1:C4", ["Item", "Q1", "Q2"]))
    edit(parts, "xl/tables/table1.xml", ('headerRowCount="0"', 'headerRowCount="1"'))


def apply_mixed_decisions(parts):
    ##  The "combined" decision set: every family, including the rename of the sheet holding the
    ##  other targets. Tables 1 and 2 exist, so the new table is table 3.
    edit(parts, "xl/drawings/drawing1.xml",
         ('id="2" name="Picture 1" title="Logo"/>', 'id="2" name="Picture 1" title="Team logo" descr="Team 12 logo placeholder."/>'))
    edit(parts, "xl/workbook.xml", ('<sheet name="Sheet1"', '<sheet name="Quarterly costs"'))
    edit(parts, "xl/worksheets/sheet2.xml", ("Sheet1!B2+Sheet1!C2", "'Quarterly costs'!B2+'Quarterly costs'!C2"),
         ("Sheet1!B3+Sheet1!C3", "'Quarterly costs'!B3+'Quarterly costs'!C3"))
    parts["xl/charts/chart1.xml"] = parts["xl/charts/chart1.xml"].replace(b"'Sheet1'!", b"'Quarterly costs'!")
    edit(parts, "xl/worksheets/sheet1.xml", ("<t>click here</t>", "<t>Team 12 budget guidance</t>"))
    add_table(parts, "xl/worksheets/sheet1.xml", "xl/worksheets/_rels/sheet1.xml.rels", "rId3", 3,
              new_table(3, "A11yTable3", "A1:C4", ["Item", "Q1", "Q2"]))
    edit(parts, "xl/tables/table1.xml", ('headerRowCount="0"', 'headerRowCount="1"'))


def apply_preservation_rich(parts):
    edit(parts, "xl/drawings/drawing1.xml",
         ('id="2" name="Picture 1" title="Logo"/>', 'id="2" name="Picture 1" title="Team logo" descr="Team 12 logo placeholder."/>'))


def apply_large_preservation(parts):
    edit(parts, "xl/drawings/drawing1.xml",
         ('id="2" name="Picture 1" title="Site photo"/>',
          'id="2" name="Picture 1" title="Site photo" descr="Large site photo placeholder used to test downloads over 2 MiB."/>'))


DECISION_SETS = {"mixed_decisions": "combined", "preservation_rich": "preserve", "large_preservation": "large"}


@pytest.mark.parametrize("key", ["seeded_all_six", *CORRECTION_KEYS, *DECISION_SETS])
def test_the_described_correction_effects_pass_the_comparator(key):
    source = (PACK / f"{key}.xlsx").read_bytes()
    with zipfile.ZipFile(io.BytesIO(source)) as archive:
        parts = {name: archive.read(name) for name in archive.namelist()}
    globals()[f"apply_{key}"](parts)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in parts.items():
            archive.writestr(name, data)
    output = buffer.getvalue()
    applied = entry(key)["decision_sets"][DECISION_SETS[key]] if key in DECISION_SETS else entry(key)["corrections"]
    changes = [change_from_decision(c["target"], c["value"]) for c in applied if c.get("action", "APPLY") == "APPLY"]
    assert compare(source, output, changes, hashlib.sha256(output).hexdigest()) == []
    assert compare(source, source, changes) != []          # not applying them is caught


def test_readme_lists_hashes_and_finding_ids():
    readme = (PACK / "README.md").read_text(encoding="utf-8")
    for key in KEYS:
        assert entry(key)["sha256"] in readme
        for f in entry(key)["findings"]:
            assert finding_id(entry(key)["sha256"], "2.0.0", f["ruleId"], f["worksheet"], f["target"]) in readme
