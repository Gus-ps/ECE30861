"""Checker-only regressions adopted from the deployed engine (Gustavo branch).

Partial coverage of 1.1.1 Non-text Content, 1.3.1 Info and Relationships,
1.4.1 Use of Color, 1.4.3 Contrast (Minimum), 2.4.2 Page Titled and
2.4.4 Link Purpose (In Context); related: 2.4.6 Headings and Labels.
REQ-03/04/05/06, AC-03/04/05/06. Fixtures and expected tuples come from the
deployed branch's November 1 cross-team corrections. Service/API checks from
that branch are excluded because this branch contains only the checker.
"""

import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from accessibility_checker.runner import check_workbook

FIXTURES = Path(__file__).parent / "fixtures" / "deployment"
EXPECTED = json.loads((FIXTURES / "expectations.json").read_text(encoding="utf-8"))
SEEDED = FIXTURES / "seeded_all_six.xlsx"
HEADER_TARGET = "xl/worksheets/sheet1.xml#range=A1:C4"


def rewrite(data, name, change):
    out = io.BytesIO()
    with ZipFile(io.BytesIO(data)) as source, ZipFile(out, "w") as target:
        for item in source.infolist():
            contents = source.read(item)
            if item.filename == name:
                contents = change(contents)
            target.writestr(item, contents)
    return out.getvalue()


class DeploymentRegressionTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.temp = Path(temp.name)

    def write(self, data, name):
        path = self.temp / name
        path.write_bytes(data)
        return path

    def test_fixture_tuples_and_independent_ids(self):
        keys = ("ruleId", "category", "worksheet", "target", "classification")
        for key, expected in EXPECTED.items():
            with self.subTest(fixture=key):
                path = FIXTURES / expected["file"]
                before = path.read_bytes()
                digest = hashlib.sha256(before).hexdigest()
                self.assertEqual(digest, expected["sha256"])
                actual = check_workbook(path)
                self.assertEqual([{k: f[k] for k in keys} for f in actual], expected["findings"])
                for finding in actual:
                    identity = [
                        digest,
                        "2.0.0",
                        finding["ruleId"],
                        finding["worksheet"],
                        finding["target"],
                    ]
                    encoded = json.dumps(identity, ensure_ascii=False, separators=(",", ":"))
                    self.assertEqual(
                        finding["findingId"], hashlib.sha256(encoded.encode()).hexdigest()
                    )
                if key == "unicode":
                    self.assertEqual(actual.limitations, [])
                self.assertEqual(path.read_bytes(), before)

    def test_formula_links_never_use_cell_targets(self):
        for key, expected in EXPECTED.items():
            path = FIXTURES / expected["file"]
            with ZipFile(path) as archive:
                sheets = {
                    name: archive.read(name)
                    for name in archive.namelist()
                    if name.startswith("xl/worksheets/") and name.endswith(".xml")
                }
            for finding in check_workbook(path):
                if finding["ruleId"] != "LINK_TEXT" or "#cell=" not in finding["target"]:
                    continue
                part, address = finding["target"].split("#cell=")
                root = ET.fromstring(sheets[part])
                cell = next(c for c in root.iter() if c.tag.endswith("}c") and c.get("r") == address)
                with self.subTest(fixture=key, target=finding["target"]):
                    self.assertIsNone(cell.find("{*}f"))

    def test_disjoint_drawing_keeps_header_user_input(self):
        header = next(f for f in check_workbook(SEEDED) if f["target"] == HEADER_TARGET)
        self.assertEqual(header["classification"], "REQUIRES_USER_INPUT")

    def test_overlapping_drawing_and_unknown_extension_stay_manual(self):
        original = SEEDED.read_bytes()

        def move_anchor(data):
            root = ET.fromstring(data)
            root.find("{*}twoCellAnchor/{*}from/{*}col").text = "0"
            return ET.tostring(root)

        path = self.write(rewrite(original, "xl/drawings/drawing1.xml", move_anchor), "overlap.xlsx")
        headers = [f for f in check_workbook(path) if f["target"] == HEADER_TARGET]
        self.assertEqual(headers[0]["classification"], "MANUAL_REVIEW")

        changed = rewrite(
            original,
            "xl/drawings/drawing1.xml",
            lambda data: data.replace(
                b"{C183D7F6-B498-43B3-948B-1728B52AA6E4}", b"{UNKNOWN-EXTENSION}"
            ),
        )
        path = self.write(changed, "extension.xlsx")
        self.assertTrue(
            any(
                f["ruleId"] == "WORKSHEET_NAME" and f["classification"] == "MANUAL_REVIEW"
                for f in check_workbook(path)
            )
        )

    def test_in_cell_metadata_inside_candidate_stays_manual(self):
        def attach(data):
            root = ET.fromstring(data)
            cell = next(c for c in root.iter() if c.tag.endswith("}c") and c.get("r") == "B2")
            cell.set("vm", "1")
            return ET.tostring(root)

        path = self.write(
            rewrite(SEEDED.read_bytes(), "xl/worksheets/sheet1.xml", attach), "cell-image.xlsx"
        )
        findings = check_workbook(path)
        header = next(
            f for f in findings if f["ruleId"] == "TABLE_HEADER" and f["target"] == HEADER_TARGET
        )
        self.assertEqual(header["classification"], "MANUAL_REVIEW")
        self.assertTrue(any("In-cell image" in line for line in findings.limitations))


if __name__ == "__main__":
    unittest.main()
