"""Synthetic performance tooling for REQ-15 / AC-18 preparation (not acceptance evidence).

No WCAG criterion is checked here; the tools time all six rules together
(1.1.1, 1.3.1, 1.4.1/1.4.3, 2.4.2 related 2.4.6, 2.4.4). Tests use small cell
counts only. The 250,000-cell measurement runs only through the script, or via
CHECKER_PERF_FULL=1 for the opt-in test below.
"""

import os
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

from accessibility_checker.cell_reader import WorkbookReader
from accessibility_checker.runner import check_workbook
from scripts.perf_harness import compare_runs, fingerprint, measure_workbook
from scripts.perf_workbooks import PROFILES, LimitExceeded, build_workbook, check_limits

SMALL = {"a": 1_000, "b": 5_000, "c": 2_500, "d": 1_000}


class GeneratorTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)

    def tearDown(self):
        self.directory.cleanup()

    def test_same_arguments_produce_identical_bytes(self):
        for profile, cells in SMALL.items():
            with self.subTest(profile=profile):
                first = build_workbook(profile, self.root / "one" / "x.xlsx", cells=cells)
                second = build_workbook(profile, self.root / "two" / "x.xlsx", cells=cells)
                self.assertEqual(first["sha256"], second["sha256"])
                self.assertEqual(
                    Path(first["path"]).read_bytes(), Path(second["path"]).read_bytes()
                )
                with ZipFile(first["path"]) as archive:
                    self.assertEqual(
                        {info.date_time for info in archive.infolist()}, {(1980, 1, 1, 0, 0, 0)}
                    )

    def test_reported_cells_match_intake_nonempty_and_sheet_counts(self):
        expected_sheets = {"a": 1, "b": 50, "c": 10, "d": 1}
        for profile, cells in SMALL.items():
            with self.subTest(profile=profile):
                manifest = build_workbook(profile, self.root / f"{profile}.xlsx", cells=cells)
                with WorkbookReader(manifest["path"]) as reader:
                    counted = sum(
                        cell.intake_nonempty
                        for sheet in reader.sheets
                        for cell in reader.read_cells(sheet)
                    )
                    self.assertEqual(len(reader.sheets), expected_sheets[profile])
                self.assertEqual(counted, cells)
                self.assertEqual(manifest["nonempty_cells"], cells)
                self.assertTrue(manifest["synthetic"])

    def test_profile_c_contains_the_documented_feature_mix(self):
        manifest = build_workbook("c", self.root / "c.xlsx", cells=2_500)
        self.assertEqual(manifest["formal_tables"], 2)
        self.assertEqual(manifest["merges"], 10 * 30)
        self.assertEqual(manifest["conditional_formatting_blocks"], 20)
        self.assertGreater(manifest["hyperlinks"], 0)
        result = check_workbook(manifest["path"])
        rules = {finding["ruleId"] for finding in result}
        self.assertTrue(
            {"COLOR_CONTRAST", "MERGED_CELLS", "LINK_TEXT", "TABLE_HEADER", "WORKSHEET_NAME"}
            <= rules
        )

    def test_limits_are_inclusive_and_violations_rejected(self):
        check_limits(size=25_000_000, sheets=50, cells=250_000)
        for kwargs in (
            {"size": 25_000_001, "sheets": 1, "cells": 1},
            {"size": 1, "sheets": 51, "cells": 1},
            {"size": 1, "sheets": 1, "cells": 250_001},
        ):
            with self.subTest(**kwargs), self.assertRaises(LimitExceeded):
                check_limits(**kwargs)

    def test_generation_refuses_and_removes_oversized_output(self):
        path = self.root / "big.xlsx"
        with self.assertRaises(LimitExceeded):
            build_workbook("a", path, cells=1_000, max_bytes=1_000)
        self.assertFalse(path.exists())
        with self.assertRaises(LimitExceeded):
            build_workbook("a", path, cells=1_000, max_cells=999)
        self.assertFalse(path.exists())
        with self.assertRaises(LimitExceeded):
            build_workbook("b", path, cells=5_000, max_sheets=49)


class ComparisonTests(unittest.TestCase):
    finding = {
        "findingId": "a" * 64,
        "ruleId": "LINK_TEXT",
        "category": "LINK_TEXT",
        "worksheet": "S",
        "target": "xl/worksheets/sheet1.xml#cell=A1",
        "classification": "REQUIRES_USER_INPUT",
        "message": "m",
        "recommendation": "r",
    }

    def run_record(self, number, findings, limitations, status="ok"):
        return {"run": number, "status": status, "fingerprint": fingerprint(findings, limitations)}

    def test_identical_runs_match(self):
        runs = [self.run_record(n, [self.finding], ["x"]) for n in (1, 2, 3)]
        self.assertEqual(
            compare_runs(runs),
            {"identical": True, "compared_runs": 3, "failed_runs": [], "differing": []},
        )

    def test_id_target_and_limitation_changes_are_detected(self):
        base = self.run_record(1, [self.finding], ["x"])
        changed_id = self.run_record(2, [dict(self.finding, findingId="b" * 64)], ["x"])
        self.assertEqual(
            compare_runs([base, changed_id])["differing"], ["finding_ids_sha256", "full_sha256"]
        )
        moved = dict(self.finding, target="xl/worksheets/sheet1.xml#cell=A2")
        self.assertIn("tuples_sha256", compare_runs([base, self.run_record(2, [moved], ["x"])])[
            "differing"
        ])
        limitation = self.run_record(2, [self.finding], ["y"])
        self.assertEqual(
            compare_runs([base, limitation])["differing"], ["full_sha256", "limitations_sha256"]
        )
        reordered = self.run_record(2, [self.finding, moved], ["x"])
        swapped = self.run_record(3, [moved, self.finding], ["x"])
        self.assertFalse(compare_runs([reordered, swapped])["identical"])

    def test_failed_runs_are_excluded_and_reported(self):
        ok = self.run_record(1, [self.finding], [])
        failed = {"run": 2, "status": "timeout"}
        self.assertEqual(
            compare_runs([ok, failed]),
            {"identical": True, "compared_runs": 1, "failed_runs": [2], "differing": []},
        )
        self.assertIsNone(compare_runs([failed])["identical"])


class HarnessTests(unittest.TestCase):
    def test_child_runs_record_time_memory_and_identical_findings(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = build_workbook("c", Path(directory) / "c.xlsx", cells=2_500)
            before = Path(manifest["path"]).read_bytes()
            result = measure_workbook(manifest["path"], runs=2, timeout=60)
            self.assertEqual(Path(manifest["path"]).read_bytes(), before)
        self.assertEqual(result["sha256"], manifest["sha256"])
        self.assertTrue(result["comparison"]["identical"])
        for run in result["runs"]:
            self.assertEqual(run["status"], "ok")
            self.assertGreater(run["engine_seconds"], 0)
            self.assertGreater(run["peak_rss_kib_wait4"], 0)
        self.assertIsNone(result["queue_seconds"])

    def test_child_findings_equal_in_process_runner(self):
        from accessibility_checker.runner import check_workbook as run

        with tempfile.TemporaryDirectory() as directory:
            manifest = build_workbook("d", Path(directory) / "d.xlsx", cells=300)
            local = run(manifest["path"])
            result = measure_workbook(manifest["path"], runs=1, timeout=60)
        self.assertEqual(
            result["runs"][0]["fingerprint"], fingerprint(local, local.limitations)
        )


@unittest.skipUnless(os.environ.get("CHECKER_PERF_FULL") == "1", "set CHECKER_PERF_FULL=1")
class FullBoundaryMeasurement(unittest.TestCase):
    """Opt-in: five runs per 250,000-cell profile under the 384 MiB limit."""

    def test_full_profiles(self):
        with tempfile.TemporaryDirectory() as directory:
            for profile in sorted(PROFILES):
                with self.subTest(profile=profile):
                    manifest = build_workbook(profile, Path(directory) / f"{profile}.xlsx")
                    result = measure_workbook(
                        manifest["path"], runs=5, rlimit_as=True, timeout=90
                    )
                    self.assertTrue(result["summary"]["all_within_60s_or_controlled"])
                    self.assertTrue(result["comparison"]["identical"])
