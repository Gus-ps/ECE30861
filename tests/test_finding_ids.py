"""Temporary finding-ID tests for 1.1.1 Non-text Content and 2.4.2 Page Titled.

REQ-05/15 and AC-05/18: identifier format and local repeatability only.
"""

import unittest

from finding_ids import make_finding_id


class FindingIdTests(unittest.TestCase):
    def test_identifier_format_and_repeatability(self):
        identifier = make_finding_id("ALT_TEXT", "予算", "drawing.xml#id=2")
        self.assertRegex(identifier, r"\A[A-Za-z0-9_-]{1,64}\Z")
        self.assertEqual(identifier, make_finding_id("ALT_TEXT", "予算", "drawing.xml#id=2"))

    def test_rule_sheet_target_and_component_boundaries_distinguish_ids(self):
        inputs = [
            ("ALT_TEXT", "Budget", "drawing.xml#id=1"),
            ("OTHER", "Budget", "drawing.xml#id=1"),
            ("ALT_TEXT", "Forecast", "drawing.xml#id=1"),
            ("ALT_TEXT", "Budget", "drawing.xml#id=2"),
            ("ALT_TEXT", "Budget", "other-drawing.xml#id=1"),
            ("A", "B-C", "D"), ("A-B", "C", "D"),
        ]
        self.assertEqual(len({make_finding_id(*item) for item in inputs}), len(inputs))


if __name__ == "__main__":
    unittest.main()
