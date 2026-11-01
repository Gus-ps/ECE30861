"""Local rehearsal of the Team 12 tester over real HTTP.

Starts the stand-in system and the tester as separate uvicorn processes, then drives the
instructor interface with httpx. Needs free loopback ports 8100-8102; nothing may listen on 8199.

Usage (from the repo root):  uv run python scripts/rehearsal/rehearse.py
Exits 0 when every check passes. Server logs and the happy-path report go to scripts/rehearsal/work/.
"""

import hashlib
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
PYTHON = sys.executable
WORK = HERE / "work"
WORK.mkdir(exist_ok=True)

SYSTEM_PORT, TESTER_PORT, PREFIXED_PORT = 8100, 8101, 8102
SYSTEM = f"http://127.0.0.1:{SYSTEM_PORT}"
TARGET = f"{SYSTEM}/system"
DEAD_TARGET = "http://127.0.0.1:8199/system"       # nothing listens here
OPERATOR = "rehearsal-operator-token"
AUTH = {"Authorization": f"Bearer {OPERATOR}"}
TOKENS = {"userA": "tok-a", "userB": "tok-b", "reviewer": "tok-r", "test-admin": "tok-admin"}

sys.path.insert(0, str(REPO))
from tester.models import SuiteReport  # noqa: E402

##  The stand-in never fails an audit, so the controlled-failure case has nothing to inspect.
NOT_PASSING = ["P3-AUDIT-FAILURE-ENVELOPE"]
results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" -- {detail}" if detail else ""), flush=True)


def wait_for(url, seconds=20):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        try:
            httpx.get(url, timeout=1)
            return
        except httpx.TransportError:
            time.sleep(0.2)
    raise RuntimeError(f"{url} did not start")


def tester_env(db):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("TESTER_", "ALLOWED_", "TARGET_", "APP_ENV"))}
    env.update(APP_ENV="development", TESTER_DB_PATH=str(db),
               TESTER_OPERATOR_TOKEN_HASHES_JSON=json.dumps({hashlib.sha256(OPERATOR.encode()).hexdigest(): "rehearsal"}),
               ALLOWED_TARGET_URLS=json.dumps([TARGET, DEAD_TARGET]),
               TARGET_AUTH_MAP_JSON=json.dumps({TARGET: TOKENS, DEAD_TARGET: TOKENS}),
               EXPECTATIONS_PATH=str(REPO / "tester" / "fixtures" / "shared" / "expectations.json"))
    return env


def start_tester(port, db, *extra):
    log = open(WORK / f"tester-{port}.log", "a", encoding="utf-8")
    proc = subprocess.Popen([PYTHON, "-m", "uvicorn", "tester.main:create_app", "--factory",
                             "--host", "127.0.0.1", "--port", str(port), *extra],
                            cwd=REPO, env=tester_env(db), stdout=log, stderr=subprocess.STDOUT)
    wait_for(f"http://127.0.0.1:{port}/docs")
    return proc


def control(**values):
    httpx.post(f"{SYSTEM}/control", json=values).raise_for_status()


def system_log():
    return httpx.get(f"{SYSTEM}/control/log").json()


def outcomes(report):
    return {r["test_id"]: r for r in report["results"]}


def main():
    for old in WORK.glob("*.db*"):
        old.unlink()
    db = WORK / "tester.db"
    system_proc = subprocess.Popen([PYTHON, "-m", "uvicorn", "stand_in_system:app", "--app-dir", str(HERE),
                                    "--host", "127.0.0.1", "--port", str(SYSTEM_PORT)],
                                   cwd=HERE, stdout=open(WORK / "system.log", "w"), stderr=subprocess.STDOUT)
    procs = [system_proc]
    try:
        wait_for(f"{SYSTEM}/control/log")
        tester = start_tester(TESTER_PORT, db)
        procs.append(tester)
        base = f"http://127.0.0.1:{TESTER_PORT}"
        client = httpx.Client(base_url=base, timeout=700, trust_env=False)

        print("\n== A. Happy path ==")
        r = client.post("/test/setup", json={"target_url": TARGET})
        check("setup without operator token -> 401", r.status_code == 401, str(r.status_code))
        r = client.post("/test/setup", json={"target_url": "http://127.0.0.1:9999/system"}, headers=AUTH)
        check("setup with non-allowlisted URL -> 400", r.status_code == 400 and r.json()["source"] == "tester",
              r.text)
        r = client.post("/test/setup", json={"target_url": TARGET + "/test"}, headers=AUTH)
        check("setup with /test suffix -> 400", r.status_code == 400, r.text)
        started = time.monotonic()
        r = client.post("/test/setup", json={"target_url": TARGET}, headers=AUTH)
        check("setup -> 201 with a session_id", r.status_code == 201 and r.json().get("session_id"), r.text)
        session = r.json()["session_id"]
        setup_call = [e for e in system_log() if e["path"] == "/system/test/setup"][-1]
        check("system setup got test-admin token, the same session_id, no X-Test-Session",
              setup_call["authorization"] == "Bearer tok-admin"
              and setup_call["body"] == {"session_id": session, "setup": {}}
              and setup_call["x_test_session"] is None, json.dumps(setup_call))
        r = client.get("/test/report", params={"session_id": session}, headers=AUTH)
        check("report before run -> 409", r.status_code == 409, r.text)
        r = client.post("/test/run", json={"session_id": session}, headers=AUTH)
        elapsed = time.monotonic() - started
        check("run -> 200", r.status_code == 200, f"{r.status_code} in {elapsed:.1f}s")
        run_bytes = r.content
        report = SuiteReport.model_validate_json(run_bytes).model_dump()
        check("report validates as SuiteReport with 53 results", len(report["results"]) == 53)
        counts = {}
        for item in report["results"]:
            counts[item["outcome"]] = counts.get(item["outcome"], 0) + 1
        by_id = outcomes(report)
        others = [t for t, r in by_id.items() if r["outcome"] != "pass"]
        check("52 pass with the shared fixture pack; only the controlled-failure case skips (none occurred)",
              counts == {"pass": 52, "skip": 1} and others == NOT_PASSING, json.dumps(counts))
        sizes = [e["content_length"] for e in system_log() if e["path"] == "/system/api/v1/workbooks"]
        check("31 uploads reached the stand-in, two of them over 25,000,000 bytes",
              len(sizes) == 31 and sum(size > 25_000_000 for size in sizes) == 2, str(sizes))
        check("code coverage 40/50 read from the system report",
              report["coverage"]["code"]["covered"] == 40 and report["coverage"]["code"]["total"] == 50,
              json.dumps(report["coverage"]))
        report_call = [e for e in system_log() if e["path"] == "/system/test/report"][-1]
        check("system report called with ?session_id and test-admin token",
              report_call["query"] == {"session_id": session} and report_call["authorization"] == "Bearer tok-admin")
        r = client.post("/test/run", json={"session_id": session}, headers=AUTH)
        check("second run -> 409", r.status_code == 409, r.text)
        r = client.get("/test/report", params={"session_id": session}, headers=AUTH)
        check("stored report == run body, byte for byte", r.status_code == 200 and r.content == run_bytes)
        r = client.get("/test/report", params={"session_id": "00000000-0000-0000-0000-000000000000"}, headers=AUTH)
        check("report for unknown session -> 404", r.status_code == 404, r.text)
        (WORK / "happy_report.json").write_bytes(run_bytes)

        print("\n== B. Setup failures and cleanup IDs ==")
        control(setup_reply=[503, {"message": "Database is warming up.", "source": "system"}])
        r = client.post("/test/setup", json={"target_url": TARGET}, headers=AUTH)
        check("system 503 {message, source} forwarded unchanged",
              r.status_code == 503 and r.json() == {"message": "Database is warming up.", "source": "system"}, r.text)
        control(setup_reply=[500, {"error": "boom"}])
        r = client.post("/test/setup", json={"target_url": TARGET}, headers=AUTH)
        check("system 500 with invalid body -> 500 source system", r.status_code == 500 and r.json()["source"] == "system",
              r.text)
        control(setup_reply=None)
        r = client.post("/test/setup", json={"target_url": DEAD_TARGET}, headers=AUTH)
        check("unreachable system -> 500 source communication",
              r.status_code == 500 and r.json()["source"] == "communication", r.text)
        httpx.post(f"{SYSTEM}/control/reset_log")
        r = client.post("/test/setup", json={"target_url": TARGET}, headers=AUTH)
        cleanup_ids = [e for e in system_log() if e["path"] == "/system/test/setup"][-1]["body"]["setup"].get(
            "cleanup_session_ids", [])
        check("next setup succeeds and sends the 2 failed (5xx) session IDs for cleanup",
              r.status_code == 201 and len(cleanup_ids) == 2, json.dumps(cleanup_ids))
        client.post("/test/run", json={"session_id": r.json()["session_id"]}, headers=AUTH)

        print("\n== C. Per-call timeout over a real socket ==")
        control(report_delay=15)
        session = client.post("/test/setup", json={"target_url": TARGET}, headers=AUTH).json()["session_id"]
        started = time.monotonic()
        r = client.post("/test/run", json={"session_id": session}, headers=AUTH)
        elapsed = time.monotonic() - started
        item = outcomes(r.json())["P3-CODE-REPORT"]
        check("slow system report -> error/communication, run still 200",
              r.status_code == 200 and item["outcome"] == "error" and item.get("source") == "communication",
              f"{item['message']} ({elapsed:.1f}s)")
        check("run finished within the 10 s GET budget plus margin", elapsed < 20, f"{elapsed:.1f}s")
        check("code coverage falls back to paired nulls",
              r.json()["coverage"]["code"]["covered"] is None and r.json()["coverage"]["code"]["total"] is None,
              json.dumps(r.json()["coverage"]["code"]))
        control(report_delay=0)

        print("\n== D. Base path prefix (/tester) ==")
        prefixed = start_tester(PREFIXED_PORT, WORK / "prefixed.db", "--root-path", "/tester")
        procs.append(prefixed)
        ##  uvicorn's --root-path expects the proxy to strip the prefix before forwarding.
        prefixed_base = f"http://127.0.0.1:{PREFIXED_PORT}"
        r = httpx.post(f"{prefixed_base}/test/setup", json={"target_url": TARGET}, headers=AUTH, timeout=60,
                       trust_env=False)
        run = httpx.post(f"{prefixed_base}/test/run", json=r.json(), headers=AUTH, timeout=700, trust_env=False) \
            if r.status_code == 201 else None
        check("--root-path /tester: setup and run work when the proxy strips /tester",
              run is not None and run.status_code == 200, f"setup {r.status_code}")
        openapi = httpx.get(f"{prefixed_base}/openapi.json", trust_env=False).json()
        check("--root-path /tester: OpenAPI advertises the /tester server URL",
              openapi.get("servers") == [{"url": "/tester"}], json.dumps(openapi.get("servers")))
        r = httpx.post(f"{prefixed_base}/tester/test/setup", json={"target_url": TARGET}, headers=AUTH,
                       timeout=60, trust_env=False)
        check("--root-path /tester: an unstripped /tester/test/setup is 404 (proxy must strip)",
              r.status_code == 404, str(r.status_code))
        prefixed.kill()
        prefixed.wait()

        print("\n== E. Tester killed mid-run, then restarted ==")
        control(duplicate_delay=25)
        session = client.post("/test/setup", json={"target_url": TARGET}, headers=AUTH).json()["session_id"]
        lost = {}

        def run_in_background():
            try:
                lost["response"] = client.post("/test/run", json={"session_id": session}, headers=AUTH)
            except httpx.TransportError as error:
                lost["error"] = type(error).__name__

        runner = threading.Thread(target=run_in_background)
        runner.start()
        end = time.monotonic() + 30
        while time.monotonic() < end and sum(1 for e in system_log()
                                              if e["path"] == "/system/test/setup"
                                              and e["body"].get("session_id") == session) < 2:
            time.sleep(0.2)
        tester.kill()                       # hard kill, like a crash
        tester.wait()
        runner.join(10)
        check("run response lost when the tester dies", "error" in lost, json.dumps(lost, default=str))
        control(duplicate_delay=0)
        tester = start_tester(TESTER_PORT, db)
        procs.append(tester)
        r = client.get("/test/report", params={"session_id": session}, headers=AUTH)
        ok = r.status_code == 200
        detail = r.text[:200]
        if ok:
            aborted = SuiteReport.model_validate_json(r.content).model_dump()
            by_id = outcomes(aborted)
            interrupted = [t for t, v in by_id.items() if v["outcome"] == "error"]
            ok = interrupted and by_id[interrupted[0]].get("source") == "tester" and "restarted" in \
                by_id[interrupted[0]]["message"]
            detail = f"interrupted case {interrupted}: {by_id[interrupted[0]]['message'] if interrupted else ''}"
        check("after restart, report -> 200 with the interrupted case as error/tester", ok, detail)
        r = client.post("/test/run", json={"session_id": session}, headers=AUTH)
        check("run after abort -> 409", r.status_code == 409, r.text)
        r = client.get("/test/report", params={"session_id": json.loads(run_bytes)["session_id"]}, headers=AUTH)
        check("earlier completed report survives the restart unchanged", r.status_code == 200 and r.content == run_bytes)
        r = client.post("/test/setup", json={"target_url": TARGET}, headers=AUTH)
        check("new setup works after restart", r.status_code == 201, r.text)
    finally:
        for proc in procs:
            if proc.poll() is None:
                proc.kill()
                proc.wait()

    failed = [name for name, ok, _ in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    for name in failed:
        print("FAILED:", name)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
