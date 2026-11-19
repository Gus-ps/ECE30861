import json
import io
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from accessibility_checker.audit_cache import audit_cache, cache_for
from accessibility_checker.cell_reader import WorkbookReader
from accessibility_checker.runner import check_workbook
from phase4_jobs import child
from test_phase4_service import workbook


class PerformanceTests(unittest.TestCase):
    def test_cell_cache_is_shared_only_inside_one_immutable_audit(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'source.xlsx'; path.write_bytes(workbook('Records'))
            with audit_cache(path):
                with WorkbookReader(path) as reader:
                    first=reader.read_cells(reader.sheets[0])
                with WorkbookReader(path) as reader:
                    self.assertIs(first,reader.read_cells(reader.sheets[0]))
                    self.assertIn(('cells',reader.sheets[0]),cache_for(path))
            self.assertIsNone(cache_for(path))
            path.write_bytes(workbook('New Records'))
            with WorkbookReader(path) as reader:
                self.assertEqual(reader.sheets[0].name,'New Records')
            with self.assertRaisesRegex(RuntimeError,'abort'):
                with audit_cache(path): raise RuntimeError('abort')
            self.assertIsNone(cache_for(path))

    def test_six_rule_regression_tuples_match_independent_retained_expectations(self):
        root=Path(__file__).parent/'fixtures/deployment'
        entries=json.loads((root/'expectations.json').read_text(encoding='utf-8'))
        # Retained fixture oracle, never regenerated from the optimized checker.
        for key,entry in entries.items():
            if not isinstance(entry,dict) or 'findings' not in entry: continue
            path=root/entry.get('file',key+'.xlsx')
            if not path.exists(): continue
            with self.subTest(fixture=key):
                actual=check_workbook(path)
                fields=('ruleId','worksheet','target','classification')
                self.assertEqual(sorted(tuple(f[k] for k in fields) for f in actual),
                                 sorted(tuple(f[k] for k in fields) for f in entry['findings']))

    def test_child_timeout_and_response_limit_do_not_return_partial_results(self):
        with tempfile.TemporaryDirectory() as d:
            source=Path(d)/'source.xlsx'; source.write_bytes(b'not read by mocked worker')
            with patch('phase4_jobs.subprocess.run',side_effect=subprocess.TimeoutExpired('worker',60)):
                with self.assertRaises(subprocess.TimeoutExpired): child('audit',source)
            class OversizedResponse(io.BytesIO):
                def tell(self):
                    return 64*1024**2+1
            # Simulate the boundary without allocating a 64 MiB disk file;
            # otherwise a full laptop disk can mask the intended exception.
            with patch('phase4_jobs.tempfile.TemporaryFile',side_effect=[OversizedResponse(),io.BytesIO()]), \
                 patch('phase4_jobs.subprocess.run',return_value=subprocess.CompletedProcess([],0)):
                with self.assertRaisesRegex(RuntimeError,'RESULT_TOO_LARGE'): child('audit',source)
