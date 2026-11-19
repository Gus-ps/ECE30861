"""PERF-1: fingerprint, summary and verdict rules on made-up runs (no real measurement)."""
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('perf_service', Path(__file__).resolve().parents[1] / 'scripts' / 'perf_service.py')
perf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(perf)

FINDINGS = [
    {'ruleId': 'ALT_TEXT', 'worksheet': 'Sheet1', 'target': 'xl/drawings/drawing1.xml#id=2',
     'category': 'NON_TEXT_CONTENT', 'findingId': 'f1', 'message': 'm'},
    {'ruleId': 'LINK_TEXT', 'worksheet': 'Sheet1', 'target': 'A1', 'category': 'LINK_TEXT',
     'findingId': 'f2', 'message': 'm'},
]


def run(seconds, outcome='SUCCESS', fingerprint='a', **extra):
    return dict(dict(workbook='w.xlsx', outcome=outcome, error_code=None, end_to_end_seconds=seconds + 1,
                     execution_seconds=seconds, queue_seconds=1.0, findings_count=2,
                     fingerprint=fingerprint if outcome == 'SUCCESS' else None,
                     findings_bytes=100, report_bytes=200), **extra)


class PerfScriptTests(unittest.TestCase):
    def test_fingerprint_ignores_order_and_other_fields(self):
        moved = [dict(FINDINGS[1], message='other'), FINDINGS[0]]
        self.assertEqual(perf.fingerprint(FINDINGS), perf.fingerprint(moved))
        for key in ('ruleId', 'worksheet', 'target', 'category', 'findingId'):
            with self.subTest(key=key):
                changed = [dict(FINDINGS[0], **{key: 'x'}), FINDINGS[1]]
                self.assertNotEqual(perf.fingerprint(FINDINGS), perf.fingerprint(changed))

    def test_verdict_rules(self):
        cases = [
            ('headroom at 75%', [run(44), run(44), run(45)], 'PASS WITH HEADROOM'),
            ('marginal', [run(50), run(52), run(55)], 'MARGINAL'),
            ('at the budget', [run(58), run(59), run(60)], 'MARGINAL'),
            ('over the budget', [run(30), run(30), run(60.5)], 'FAIL'),
            ('differing findings', [run(30), run(30, fingerprint='b')], 'FAIL'),
            ('uncontrolled outcome', [run(30), run(30, outcome='TIMEOUT')], 'FAIL'),
            ('success without a measurement', [run(30), run(30, execution_seconds=None)], 'FAIL'),
            ('controlled failures', [run(20, outcome='PROCESSING_FAILED', execution_seconds=None)] * 2,
             'CONTROLLED FAILURE (2/2 runs)'),
            ('mixed', [run(20), run(21, outcome='PROCESSING_FAILED')], 'CONTROLLED FAILURE (1/2 runs)'),
            ('slow controlled failure', [run(20), run(61, outcome='PROCESSING_FAILED')], 'FAIL'),
            ('noisy spread', [run(10), run(10), run(13)], 'PASS WITH HEADROOM; noisy, repeat'),
        ]
        for name, runs, expected in cases:
            with self.subTest(name):
                self.assertEqual(perf.verdict(runs, 'execution_seconds', 60), expected)

    def test_summary_reports_stats_outcomes_and_sizes(self):
        runs = [run(10), run(20), run(30, findings_bytes=5000),
                run(12, outcome='PROCESSING_FAILED', error_code='PROCESSING_TIMEOUT')]
        lines = perf.summary(runs).splitlines()
        self.assertEqual(lines[1].split()[:4], ['execution', '10.00', '16.00', '30.00'])
        self.assertIn('CONTROLLED FAILURE (1/4 runs)', lines[1])
        self.assertTrue(lines[2].startswith('queue (approx)'))
        self.assertIn('end_to_end', lines[3])
        self.assertIn('budget 80 s', lines[3])
        self.assertEqual(lines[4], 'outcomes: PROCESSING_FAILED/PROCESSING_TIMEOUT, SUCCESS, SUCCESS, SUCCESS')
        self.assertEqual(lines[5], 'findings counts: [2], distinct fingerprints: 1')
        self.assertEqual(lines[6], f'largest response: 5000 bytes (limit {64 * 1024**2})')


if __name__ == '__main__':
    unittest.main()
