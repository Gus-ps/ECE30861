"""Smoke test a deployed Team 12 tester through the instructor interface.

Usage:
  TESTER_TOKEN=<operator token> uv run python scripts/smoke_test.py \
      --tester-url https://<host>/tester --target-url https://<host>/system
(PowerShell: $env:TESTER_TOKEN = '<operator token>' first.)

Runs one full suite: setup, report before run (409), run, stored report identical to the run
body, second run (409). It creates one real session on the target. Exits 0 when every check passes.
"""

import argparse
import json
import os
import sys
import time

import httpx

from tester.models import SuiteReport


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tester-url", required=True, help="tester base URL, without /test")
    parser.add_argument("--target-url", required=True, help="system base URL exactly as allowlisted")
    parser.add_argument("--setup-timeout", type=float, default=60)
    ##  Longer than the tester's own run ceiling (Phase 4 suite budget 1,800 s plus its 30 s guard).
    parser.add_argument("--run-timeout", type=float, default=1900)
    args = parser.parse_args()
    token = os.environ.get("TESTER_TOKEN")
    if not token:
        sys.exit("Set TESTER_TOKEN to the operator token.")

    failures = []

    def check(name, ok, detail=""):
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" -- {detail}" if detail else ""), flush=True)
        if not ok:
            failures.append(name)
        return ok

    client = httpx.Client(base_url=args.tester_url.rstrip("/"), headers={"Authorization": f"Bearer {token}"},
                          follow_redirects=False)
    started = time.monotonic()
    r = client.post("/test/setup", json={"target_url": args.target_url}, timeout=args.setup_timeout)
    if not check("setup -> 201", r.status_code == 201, f"{r.status_code} {r.text[:300]}"):
        sys.exit(1)
    session = r.json()["session_id"]
    print(f"session_id {session} (setup {time.monotonic() - started:.1f}s)")

    r = client.get("/test/report", params={"session_id": session}, timeout=30)
    check("report before run -> 409", r.status_code == 409, str(r.status_code))

    started = time.monotonic()
    r = client.post("/test/run", json={"session_id": session}, timeout=args.run_timeout)
    elapsed = time.monotonic() - started
    check("run -> 200", r.status_code == 200, f"{r.status_code} in {elapsed:.1f}s")
    run_body = r.content
    if r.status_code != 200:
        r = client.get("/test/report", params={"session_id": session}, timeout=30)
        run_body = r.content if r.status_code == 200 else b""
    try:
        report = SuiteReport.model_validate_json(run_body).model_dump()
        counts = {}
        for item in report["results"]:
            counts[item["outcome"]] = counts.get(item["outcome"], 0) + 1
        check("report validates as SuiteReport", True, f"{len(report['results'])} results {json.dumps(counts)}")
        print("coverage:", json.dumps({k: [v["covered"], v["total"]] for k, v in report["coverage"].items()}))
        for item in report["results"]:
            if item["outcome"] in ("fail", "error"):
                print(f"  {item['test_id']}: {item['outcome']}"
                      + (f" ({item['source']})" if item.get("source") else "") + f" {item['message']}")
    except ValueError as error:
        check("report validates as SuiteReport", False, str(error)[:300])

    r = client.get("/test/report", params={"session_id": session}, timeout=30)
    check("stored report == run body", r.status_code == 200 and r.content == run_body, str(r.status_code))
    r = client.post("/test/run", json={"session_id": session}, timeout=30)
    check("second run -> 409", r.status_code == 409, str(r.status_code))

    print(f"\n{'all checks passed' if not failures else f'{len(failures)} check(s) failed'}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
