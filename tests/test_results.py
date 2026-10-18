"""Result-container tests for partial WCAG 1.1.1 Non-text Content findings.

REQ-05/AC-05: preserve findings and separate unassessed-content disclosures.
"""

import json
import unittest

from accessibility_checker.results import Findings


class FindingsTests(unittest.TestCase):
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
