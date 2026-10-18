# ECE30861
Repository for EC30861 class

## Team 12 tester

Cross-team tester for the Excel accessibility hub. It exposes the instructor
testing interface (`POST /test/setup`, `POST /test/run`, `GET /test/report`)
and runs Team 9's 53-case Phase 3 manifest against an approved target system.

| Path | Purpose |
| --- | --- |
| `tester/main.py` | App factory and routes |
| `tester/service.py` | Setup / run / report lifecycle |
| `tester/store.py` | SQLite sessions, frozen plans, progress, immutable reports |
| `tester/target.py` | Bounded HTTP client for the target system |
| `tester/suite/` | Plan loading, ordered runner, check functions |
| `tester/fixtures/manifest.json` | Copy of Team 9 suite manifest 1.4.0 |
| `tester/fixtures/pod_profile.json` | Pod-pending defaults (Team 9 values, not pod-approved) |
| `tester/wcag/` | WCAG 2.1 workbook checker, kept for Phase 4 remediation checks |
| `ref/` | Instructor spec and Team 9 contract documents |
| `deploy/` | Host-agnostic deployment files and runbook (`deploy/README.md`) |

Setup (Python 3.12 via [uv](https://docs.astral.sh/uv/)):

```sh
uv sync --group dev
cp .env.example .env      # then fill in real values
uv run uvicorn tester.main:create_app --factory --port 8001
uv run pytest
```

### Local rehearsal over real HTTP

`scripts/rehearsal/` exercises the deployed shape on one machine: the tester and a
rehearsal-only stand-in system (`stand_in_system.py`, never deployed) run as separate
uvicorn processes on 127.0.0.1, and `rehearse.py` drives the instructor interface. No
`.env` is needed; it supplies its own throwaway tokens and a fresh SQLite file.

```sh
uv run python scripts/rehearsal/rehearse.py
```

It needs free ports 8100–8102 (nothing may listen on 8199), takes about a minute, prints
one PASS/FAIL line per check and exits 0 when all 29 pass. Logs and the happy-path report
are written to `scripts/rehearsal/work/` (gitignored). Scenarios:

| Scenario | Checks |
| --- | --- |
| A. Happy path | 401/400 rejections, setup 201, system setup body and token, 409 before and after run, 53 valid results (2 pass, 51 skip), code coverage, stored report identical to the run body |
| B. Setup failures | system error forwarded unchanged, invalid 5xx body, unreachable system, failed IDs sent as `cleanup_session_ids` |
| C. Timeout | a stalled system report is cut off at 10 s as error/communication |
| D. Base path | `--root-path /tester` works when the proxy strips `/tester`; an unstripped path is 404 |
| E. Crash | tester killed mid-run; after restart the report is aborted with the interrupted case as error/tester |

Deployment note from scenario D: the reverse proxy must strip `/tester` before
forwarding (nginx: `location /tester/ { proxy_pass http://127.0.0.1:8001/; }`) and
uvicorn runs with `--root-path /tester`.

Only the session-interface checks (`P3-SESSION-DUPLICATE`, `P3-CODE-REPORT`)
are implemented so far; every other case reports `skip` with
"not implemented in this tester build" until its check is added.
