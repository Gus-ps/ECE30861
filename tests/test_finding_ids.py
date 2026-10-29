"""Current/historical ID tests for 1.1.1 Non-text Content and 2.4.2 Page Titled.

REQ-05/15 and AC-05/18: identifier format and local repeatability only.
"""

import hashlib
import tempfile
import unittest
from pathlib import Path

from accessibility_checker.finding_ids import (
    get_source_sha256,
    make_finding_id,
    make_phase3_finding_id,
    make_phase4_finding_id,
    RULESET_VERSION,
)


class FindingIdTests(unittest.TestCase):
    def test_phase4_independent_fixed_vectors_without_unicode_normalization(self):
        self.assertEqual(RULESET_VERSION, "2.0.0")
        vectors = (
            ("Expenses", "cb2c9e338057c073a33cf03ec43085470810c3cfa4d62f5a5afd9df388f37b3e"),
            ("Dépenses 📊", "0e649325952b60274320b6b2bef5778d13b2677330caea10f20cc9f9dce2c304"),
            ("De\u0301penses 📊", "3fd4f9b41173d0702c18b219f6a87b98d3fa53431001eca7c1cc063a5896788d"),
        )
        for worksheet, expected in vectors:
            with self.subTest(worksheet=worksheet):
                arguments = ("0" * 64, "ALT_TEXT", worksheet, "xl/drawings/drawing1.xml#id=7")
                self.assertEqual(make_phase4_finding_id(*arguments), expected)
                self.assertNotEqual(make_phase3_finding_id(*arguments), expected)

    def test_identifier_format_and_repeatability(self):
        identifier = make_finding_id("ALT_TEXT", "予算", "drawing.xml#id=2")
        self.assertRegex(identifier, r"\A[A-Za-z0-9_-]{1,64}\Z")
        self.assertEqual(
            identifier, make_finding_id("ALT_TEXT", "予算", "drawing.xml#id=2")
        )

    def test_rule_sheet_target_and_component_boundaries_distinguish_ids(self):
        inputs = [
            ("ALT_TEXT", "Budget", "drawing.xml#id=1"),
            ("OTHER", "Budget", "drawing.xml#id=1"),
            ("ALT_TEXT", "Forecast", "drawing.xml#id=1"),
            ("ALT_TEXT", "Budget", "drawing.xml#id=2"),
            ("ALT_TEXT", "Budget", "other-drawing.xml#id=1"),
            ("A", "B-C", "D"),
            ("A-B", "C", "D"),
        ]
        self.assertEqual(len({make_finding_id(*item) for item in inputs}), len(inputs))

    def test_phase3_exact_utf8_compact_json_recipe(self):
        source = "a" * 64
        # Literal oracle avoids reusing production JSON serialization.
        payload = (
            '["'
            + source
            + '","1.0.0","ALT_TEXT","予算","xl/drawings/drawing1.xml#id=2"]'
        ).encode("utf-8")
        identifier = make_phase3_finding_id(
            source, "ALT_TEXT", "予算", "xl/drawings/drawing1.xml#id=2"
        )
        self.assertEqual(identifier, hashlib.sha256(payload).hexdigest())
        self.assertRegex(identifier, r"\A[0-9a-f]{64}\Z")
        self.assertNotEqual(
            identifier,
            make_phase3_finding_id(
                "b" * 64, "ALT_TEXT", "予算", "xl/drawings/drawing1.xml#id=2"
            ),
        )
        self.assertNotEqual(
            make_phase3_finding_id(source, "ALT_TEXT", "é", "x"),
            make_phase3_finding_id(source, "ALT_TEXT", "e\u0301", "x"),
        )

    def test_source_hash_uses_original_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "source.xlsx"
            original = b"\x00raw\r\nbytes\xff"
            path.write_bytes(original)
            self.assertEqual(
                get_source_sha256(path), hashlib.sha256(original).hexdigest()
            )
            self.assertEqual(path.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
