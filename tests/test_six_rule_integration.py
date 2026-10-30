"""Six-rule partial WCAG integration; adds 1.4.1/1.4.3 to five-rule coverage.
REQ-03/04/05/06/15, AC-03/04/05/06/18; not Excel UI/remediation evidence.
"""

import tempfile
from pathlib import Path
from xml.etree.ElementTree import ParseError
from zipfile import ZipFile

from test_five_rule_integration import FIXTURES, SEEDED
from test_five_rule_integration import FiveRuleIntegrationTests as _Base

from accessibility_checker.runner import check_workbook


class SixRuleIntegrationTests(_Base):
    clean_name = "six_rule_clean.xlsx"
    seeded_name = "six_rule_seeded.xlsx"
    expected_seeded = sorted(
        SEEDED
        + [
            (
                "COLOR_CONTRAST",
                "COLOR_OR_CONTRAST",
                "Data",
                "xl/worksheets/sheet1.xml#cell=B2",
                "MANUAL_REVIEW",
            )
        ]
    )

    def test_sparse_dimension_and_processing_failure(self):
        with ZipFile(FIXTURES / self.seeded_name) as z:
            parts = {p: z.read(p) for p in z.namelist()}
        sheet = "xl/worksheets/sheet1.xml"
        parts[sheet] = parts[sheet].replace(b'ref="A1:B2"', b'ref="A1:XFD1048576"', 1)
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "large-dimension.xlsx"
            with ZipFile(path, "w") as z:
                for p, b in parts.items():
                    z.writestr(p, b)
            before = path.read_bytes()
            result = check_workbook(path)
            self.assertEqual(
                [
                    tuple(
                        f[k]
                        for k in ("ruleId", "category", "worksheet", "target", "classification")
                    )
                    for f in result
                ],
                self.expected_seeded,
            )
            self.assertEqual(path.read_bytes(), before)
            parts[sheet] = b"<not-closed"
            with ZipFile(path, "w") as z:
                for p, b in parts.items():
                    z.writestr(p, b)
            with self.assertRaises(ParseError):
                check_workbook(path)


# Avoid rediscovering the imported historical test class in this module.
del _Base
