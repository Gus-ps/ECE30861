"""Checker-only timing/memory harness for REQ-15 / AC-18 preparation.

Primary criterion: none (not a WCAG check). Measures the whole six-rule
runner (1.1.1, 1.3.1, 1.4.1/1.4.3, 2.4.2 related 2.4.6, 2.4.4) as one unit.

Each run of accessibility_checker.runner.check_workbook(path) executes in a
fresh child Python process. Recorded per run: engine time (perf_counter around
check_workbook), child wall time (time.monotonic in the parent, including
interpreter start-up and result fingerprinting), peak RSS (getrusage for the
child, reported by os.wait4 so crashed children are measured too), status and
a findings fingerprint. Optional modes:

* --rlimit-as: the child sets RLIMIT_AS to 384 MiB after its imports, mirroring
  the deployed worker (Linux only). MemoryError / signals are failures.
* --per-rule: each checker function is also run once in its own child.
* --cprofile: one extra child runs check_workbook under cProfile.

This is LOCAL, SYNTHETIC measurement; it is not the hosted five-run AC-18
evidence (no intake, queue, HTTP, storage or service_worker review-item step).
Queue time is therefore reported as null. The public runner is not modified.

Usage:
    .venv/bin/python -m scripts.perf_harness --workbook X.xlsx [--runs 5] [--rlimit-as]
    .venv/bin/python -m scripts.perf_harness --generate [--profile c] [--output out.json]
"""

import argparse
import hashlib
import json
import os
import platform
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RLIMIT_AS_BYTES = 384 * 1024**2
ENGINE_BOUND_SECONDS = 60
TUPLE_KEYS = ("ruleId", "category", "worksheet", "target", "classification")


# ---------------------------------------------------------------- fingerprints


def _digest(items):
    hasher = hashlib.sha256()
    for item in items:
        hasher.update(json.dumps(item, ensure_ascii=False, sort_keys=True).encode("utf-8"))
        hasher.update(b"\n")
    return hasher.hexdigest()


def fingerprint(findings, limitations):
    """Order-sensitive digests of everything AC-18 requires to repeat exactly."""
    counts = {}
    for finding in findings:
        key = f"{finding['ruleId']}/{finding['classification']}"
        counts[key] = counts.get(key, 0) + 1
    return {
        "finding_count": len(findings),
        "limitation_count": len(limitations),
        "counts_by_rule_classification": dict(sorted(counts.items())),
        "tuples_sha256": _digest([finding[k] for k in TUPLE_KEYS] for finding in findings),
        "finding_ids_sha256": _digest(finding["findingId"] for finding in findings),
        "limitations_sha256": _digest(limitations),
        "full_sha256": _digest(list(findings) + ["--limitations--"] + list(limitations)),
    }


FINGERPRINT_FIELDS = ("tuples_sha256", "finding_ids_sha256", "limitations_sha256", "full_sha256")


def compare_runs(runs):
    """Compare fingerprints of successful runs only.

    Returns identical=None when no run succeeded; failed runs are listed
    separately and never treated as matching or as passing.
    """
    ok = [run for run in runs if run.get("status") == "ok"]
    failed = [run["run"] for run in runs if run.get("status") != "ok"]
    if not ok:
        return {"identical": None, "compared_runs": 0, "failed_runs": failed, "differing": []}
    reference = ok[0]["fingerprint"]
    differing = sorted(
        {
            field
            for run in ok[1:]
            for field in FINGERPRINT_FIELDS
            if run["fingerprint"][field] != reference[field]
        }
    )
    return {
        "identical": not differing,
        "compared_runs": len(ok),
        "failed_runs": failed,
        "differing": differing,
    }


# ---------------------------------------------------------------------- child


def _peak_rss_kib():
    import resource

    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss  # KiB on Linux


def _child(mode, path, rule, rlimit_as):
    """Executed inside the child process; prints exactly one JSON object."""
    from accessibility_checker import runner
    from accessibility_checker.finding_ids import get_source_sha256
    from accessibility_checker.results import Findings, finalize_findings

    if rlimit_as:
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (RLIMIT_AS_BYTES, RLIMIT_AS_BYTES))
    output = {"mode": mode, "rule": rule}
    try:
        if mode == "run":
            start = time.perf_counter()
            findings = runner.check_workbook(path)
            output["engine_seconds"] = time.perf_counter() - start
            output["peak_rss_kib_after_engine"] = _peak_rss_kib()
            output["fingerprint"] = fingerprint(findings, findings.limitations)
        elif mode == "rule":
            checkers = _rule_checkers(runner)
            start = time.perf_counter()
            source = get_source_sha256(path)
            output["sha256_seconds"] = time.perf_counter() - start
            start = time.perf_counter()
            result = checkers[rule](path, source_sha256=source)
            output["engine_seconds"] = time.perf_counter() - start
            output["peak_rss_kib_after_engine"] = _peak_rss_kib()
            combined = finalize_findings(Findings(result, getattr(result, "limitations", [])))
            output["fingerprint"] = fingerprint(combined, combined.limitations)
        elif mode == "cprofile":
            import cProfile
            import io
            import pstats

            profiler = cProfile.Profile()
            start = time.perf_counter()
            profiler.enable()
            findings = runner.check_workbook(path)
            profiler.disable()
            output["engine_seconds"] = time.perf_counter() - start
            output["fingerprint"] = fingerprint(findings, findings.limitations)
            for order in ("cumulative", "tottime"):
                stream = io.StringIO()
                pstats.Stats(profiler, stream=stream).sort_stats(order).print_stats(30)
                output[f"top_{order}"] = stream.getvalue()
        else:
            raise ValueError(f"unknown child mode {mode!r}")
        output["status"] = "ok"
        code = 0
    except MemoryError:
        output = {"mode": mode, "rule": rule, "status": "memory_error"}
        code = 3
    except Exception as error:  # recorded as a failed run, never as success
        output["status"] = "exception"
        output["error"] = f"{type(error).__name__}: {error}"[:2000]
        code = 2
    output["peak_rss_kib"] = _peak_rss_kib()
    print(json.dumps(output))
    return code


def _rule_checkers(runner):
    # Mirror runner.check_workbook's registry without changing the runner.
    from accessibility_checker.checks.color_contrast import check_color_contrast
    from accessibility_checker.checks.image_alt_text import check_image_alt_text
    from accessibility_checker.checks.link_text import check_link_text
    from accessibility_checker.checks.merged_cells import check_merged_cells
    from accessibility_checker.checks.table_headers import check_table_headers
    from accessibility_checker.checks.worksheet_names import check_worksheet_names

    checkers = {
        "ALT_TEXT": check_image_alt_text,
        "WORKSHEET_NAME": check_worksheet_names,
        "TABLE_HEADER": check_table_headers,
        "MERGED_CELLS": check_merged_cells,
        "LINK_TEXT": check_link_text,
        "COLOR_CONTRAST": check_color_contrast,
    }
    assert tuple(checkers) == tuple(runner.RULE_ORDER), "runner registry changed"
    return checkers


# --------------------------------------------------------------------- parent


def spawn(mode, path, *, rule=None, rlimit_as=False, timeout=120.0):
    """Run one child and return its measured record (never raises on child failure)."""
    command = [sys.executable, "-m", "scripts.perf_harness", "--child", mode, str(path)]
    if rule:
        command += ["--rule", rule]
    if rlimit_as:
        command.append("--child-rlimit-as")
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        start = time.monotonic()
        process = subprocess.Popen(command, cwd=ROOT, stdout=stdout, stderr=stderr)
        timed_out = threading.Event()

        def kill():
            timed_out.set()
            process.kill()

        timer = threading.Timer(timeout, kill)
        timer.start()
        try:
            # wait4 reaps the child itself, so peak RSS is available even after a crash.
            _, status, usage = os.wait4(process.pid, 0)
        finally:
            timer.cancel()
        wall = time.monotonic() - start
        process.returncode = os.waitstatus_to_exitcode(status)
        stdout.seek(0)
        stderr.seek(0)
        out = stdout.read().decode("utf-8", "replace").strip()
        err = stderr.read().decode("utf-8", "replace").strip()
    record = {
        "child_wall_seconds": wall,
        "returncode": process.returncode,
        "peak_rss_kib_wait4": usage.ru_maxrss,
    }
    try:
        record.update(json.loads(out.splitlines()[-1]))
    except (IndexError, ValueError):
        record["status"] = "no_result"
    if timed_out.is_set():
        record["status"] = "timeout"
    elif process.returncode < 0:
        record["status"] = f"signal_{signal.Signals(-process.returncode).name}"
    elif process.returncode != 0 and record.get("status") == "ok":
        record["status"] = "nonzero_exit"
    if record["status"] != "ok" and err:
        record["stderr_tail"] = err[-2000:]
    record["peak_rss_mib"] = round(record["peak_rss_kib_wait4"] / 1024, 1)
    engine = record.get("engine_seconds")
    record["within_60s"] = (
        engine is not None and record["status"] == "ok" and engine <= ENGINE_BOUND_SECONDS
    )
    return record


def measure_workbook(path, *, runs=5, rlimit_as=False, per_rule=False, cprofile=False,
                     timeout=120.0, log=None):
    path = Path(path)
    data = path.read_bytes()
    result = {
        "workbook": str(path),
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
        "rlimit_as_bytes": RLIMIT_AS_BYTES if rlimit_as else None,
        "queue_seconds": None,
        "queue_note": "No queue exists in this local checker-only measurement.",
        "runs": [],
    }
    for number in range(1, runs + 1):
        record = spawn("run", path, rlimit_as=rlimit_as, timeout=timeout)
        record["run"] = number
        result["runs"].append(record)
        if log:
            log(
                f"{path.name} run {number}: {record['status']} "
                f"engine={record.get('engine_seconds', float('nan')):.2f}s "
                f"rss={record['peak_rss_mib']}MiB"
            )
    result["comparison"] = compare_runs(result["runs"])
    engines = [r["engine_seconds"] for r in result["runs"] if r["status"] == "ok"]
    result["summary"] = {
        "ok_runs": len(engines),
        "engine_seconds_min": min(engines) if engines else None,
        "engine_seconds_max": max(engines) if engines else None,
        "peak_rss_mib_max": max(r["peak_rss_mib"] for r in result["runs"]) if runs else None,
        "all_within_60s_or_controlled": all(
            r["within_60s"] or r["status"] != "ok" for r in result["runs"]
        ),
    }
    if per_rule:
        from accessibility_checker.runner import RULE_ORDER

        result["per_rule"] = {}
        for rule in RULE_ORDER:
            record = spawn("rule", path, rule=rule, rlimit_as=rlimit_as, timeout=timeout)
            result["per_rule"][rule] = record
            if log:
                log(
                    f"{path.name} {rule}: {record['status']} "
                    f"{record.get('engine_seconds', float('nan')):.2f}s "
                    f"rss={record['peak_rss_mib']}MiB"
                )
    if cprofile:
        result["cprofile"] = spawn("cprofile", path, timeout=timeout * 4)
    return result


def environment():
    info = {
        "python": sys.version,
        "implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "cpu_count": os.cpu_count(),
        "cpu_model": None,
        "memory_total_kib": None,
    }
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("model name"):
                info["cpu_model"] = line.split(":", 1)[1].strip()
                break
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemTotal"):
                info["memory_total_kib"] = int(line.split()[1])
                break
    except OSError:
        pass
    try:
        import defusedxml
        import openpyxl

        info["openpyxl"] = openpyxl.__version__
        info["defusedxml"] = defusedxml.__version__
    except ImportError:
        pass
    return info


def main(argv=None):
    parser = argparse.ArgumentParser(description="Checker-only AC-18 preparation harness")
    parser.add_argument("--child", nargs=2, metavar=("MODE", "PATH"), help=argparse.SUPPRESS)
    parser.add_argument("--rule", help=argparse.SUPPRESS)
    parser.add_argument("--child-rlimit-as", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--workbook", action="append", default=[], help="existing .xlsx")
    parser.add_argument("--generate", action="store_true", help="generate synthetic profiles")
    parser.add_argument("--profile", action="append", help="profile(s) for --generate")
    parser.add_argument("--cells", type=int, default=250_000)
    parser.add_argument("--workbook-dir", default=".perf/workbooks")
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--rlimit-as", action="store_true", help="384 MiB RLIMIT_AS (Linux)")
    parser.add_argument("--per-rule", action="store_true")
    parser.add_argument("--cprofile", action="store_true")
    parser.add_argument("--timeout", type=float, default=120.0, help="kill a child after N s")
    parser.add_argument("--output", help="write JSON here (default: stdout)")
    args = parser.parse_args(argv)
    if args.child:
        return _child(args.child[0], args.child[1], args.rule, args.child_rlimit_as)
    if not hasattr(os, "wait4"):
        parser.error("this harness requires a POSIX system (os.wait4)")
    if args.rlimit_as and not sys.platform.startswith("linux"):
        parser.error("--rlimit-as reproduces the Linux deployment and is Linux-only")
    workbooks = []
    if args.generate:
        from scripts.perf_workbooks import PROFILES, build_workbook

        for profile in args.profile or sorted(PROFILES):
            name = f"perf_{profile}_{PROFILES[profile][0]}_{args.cells}.xlsx"
            workbooks.append(
                build_workbook(profile, Path(args.workbook_dir) / name, cells=args.cells)
            )
    workbooks += [{"path": path} for path in args.workbook]
    if not workbooks:
        parser.error("supply --workbook or --generate")

    def log(message):
        print(message, file=sys.stderr, flush=True)

    report = {
        "synthetic_local_measurement": True,
        "note": "Checker-only; excludes intake, queue, HTTP, storage and review-item building.",
        "environment": environment(),
        "settings": {
            "runs": args.runs,
            "rlimit_as": args.rlimit_as,
            "timeout_seconds": args.timeout,
            "engine_bound_seconds": ENGINE_BOUND_SECONDS,
        },
        "results": [],
    }
    for manifest in workbooks:
        measured = measure_workbook(
            manifest["path"],
            runs=args.runs,
            rlimit_as=args.rlimit_as,
            per_rule=args.per_rule,
            cprofile=args.cprofile,
            timeout=args.timeout,
            log=log,
        )
        if len(manifest) > 1:
            measured["generator_manifest"] = manifest
        report["results"].append(measured)
    text = json.dumps(report, indent=2)
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
