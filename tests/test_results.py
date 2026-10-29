"""Result-container tests for partial WCAG 1.1.1 Non-text Content findings.

REQ-05/AC-05: preserve findings and separate unassessed-content disclosures.
"""

import json
import unittest

from accessibility_checker.results import Findings, finalize_findings


class FindingsTests(unittest.TestCase):
    def test_unicode_codepoint_sort_keeps_duplicate_finding_records(self):
        records = [
            {"ruleId": rule, "worksheet": sheet, "target": target}
            for rule, sheet, target in (
                ("WORKSHEET_NAME", "A", "A"),
                ("ALT_TEXT", "é", "a"),
                ("ALT_TEXT", "e\u0301", "x2"),
                ("ALT_TEXT", "e\u0301", "x10"),
                ("ALT_TEXT", "e\u0301", "x10"),
            )
        ]
        results = Findings(records, ["é", "e\u0301", "é"])
        self.assertIs(finalize_findings(results), results)
        self.assertEqual(results, [records[i] for i in (3, 4, 2, 1, 0)])
        self.assertEqual(results.limitations, ["e\u0301", "é"])

    def test_list_behavior_and_separate_disclosures(self):
        item = {"target": "drawing.xml#xml=/wsDr[1]"}
        results = Findings([item], ["Unsupported representation."])
        self.assertIsInstance(results, list)
        self.assertEqual(results, [item])
        self.assertEqual(results.limitations, ["Unsupported representation."])
        # List serialization does not carry attributes: consumers must copy them.
        self.assertEqual(json.loads(json.dumps(results)), [item])

    def test_disclosures_are_not_shared_between_instances_or_input_lists(self):
        source = ["Original limitation."]
        first = Findings(limitations=source)
        second = Findings()
        first.limitations.append("Additional limitation.")
        self.assertEqual(source, ["Original limitation."])
        self.assertEqual(second.limitations, [])


if __name__ == "__main__":
    unittest.main()
