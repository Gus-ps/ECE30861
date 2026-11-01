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
| `tester/store.py` | SQLite sessions, frozen plans, progress, immutable reports, run records |
| `tester/suite/checks.py` | Check functions keyed by the manifest's `check` name |
| `tester/suite/workbooks.py` | Workbooks the tester generates for intake checks (exact sizes, sheet/cell counts, chartsheet, protection); not reviewed fixtures |
| `tester/suite/transfer.py` | One-part multipart upload bodies and download header/body checks |
| `tester/suite/comparator.py` | Independent Phase 4 output comparator: entry sets and per-entry SHA256, declared output hash, and semantic comparison of changed XML against the approved alt-text, rename (with formula reference rewrites), link-label and header changes |
| `tester/suite/record.py` | Run record kept outside the suite report; print with `scripts/run_record.py` |
| `tester/target.py` | Bounded HTTP client for the target system |
| `tester/suite/` | Plan loading, ordered runner, check functions |
| `tester/fixtures/manifest.json` | Copy of Team 9 suite manifest 1.4.0 |
| `tester/fixtures/pod_profile.json` | Pod-pending defaults (Team 9 values, not pod-approved) |
| `tester/fixtures/pod_profile_phase4.json` | Phase 4 bounds and coverage catalogs from spec 2.1.0; needs a Phase 4 manifest (`POD_PROFILE_PATH`) |
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
rehearsal-only stand-in system (`stand_in_system.py`, never deployed; its project API is the
test fake in `tests/fake_project.py`) run as separate
uvicorn processes on 127.0.0.1, and `rehearse.py` drives the instructor interface. No
`.env` is needed; it supplies its own throwaway tokens and a fresh SQLite file.

```sh
uv run python scripts/rehearsal/rehearse.py
```

It needs free ports 8100–8102 (nothing may listen on 8199), takes about a minute, prints
one PASS/FAIL line per check and exits 0 when all 30 pass. Logs and the happy-path report
are written to `scripts/rehearsal/work/` (gitignored). Scenarios:

| Scenario | Checks |
| --- | --- |
| A. Happy path | 401/400 rejections, setup 201, system setup body and token, 409 before and after run, 53 valid results (52 pass; the controlled-failure case skips because no audit failed) with the shared fixture pack, 31 uploads including two 25 MB workbooks, code coverage, stored report identical to the run body |
| B. Setup failures | system error forwarded unchanged, invalid 5xx body, unreachable system, failed IDs sent as `cleanup_session_ids` |
| C. Timeout | a stalled system report is cut off at 10 s as error/communication |
| D. Base path | `--root-path /tester` works when the proxy strips `/tester`; an unstripped path is 404 |
| E. Crash | tester killed mid-run; after restart the report is aborted with the interrupted case as error/tester |

Deployment note from scenario D: the reverse proxy must strip `/tester` before
forwarding (nginx: `location /tester/ { proxy_pass http://127.0.0.1:8001/; }`) and
uvicorn runs with `--root-path /tester`.

Every case in the Phase 3 manifest has a check (as does the Phase 4 plan's
`upload_worksheets_chartsheet`):

- **No fixture pack needed (18):** health, upload authentication, unsupported types and
  `.xlsm`, protected structure, the byte, worksheet and cell limits (the tester generates
  these workbooks itself), `P3-NOT-FOUND`, `P3-SESSION-DUPLICATE`, `P3-CODE-REPORT`.
- **Rejected fixtures (8):** `P3-INPUT-CORRUPT` and the seven `rejected_fixture` cases upload
  the pack's files and expect each entry's `http_status` (and `error_code` when not null).
- **Accepted fixtures (10):** clean, seeded and the three edge fixtures are uploaded and their
  audits polled to a finished state, then compared with the pack's hand-authored
  expectations: strict `AuditResponse`, IDs and ruleset, status, recomputed `findingId`s,
  the exact findings in contract order, and limitations (present only for `repeated_ids`;
  wording not compared).
- **Built on those uploads (17):** version metadata and the tester's own SHA256 (before and
  after the audit), 401 without a token, 403 for user B, 200 for the granted reviewer (the
  audit must equal the owner's), 404 for unknown and mismatched ID pairs, an unknown
  `X-Test-Session` (400), four determinism re-uploads whose status, findings (IDs and text)
  and limitations must equal the first seeded audit, and the controlled-failure envelope,
  which inspects every `PROCESSING_FAILED` audit seen and skips when there was none.

Phase 4 controlled audit failure (spec §14.1) has checks ready for the 2.1.0 manifest:
`fault_setup` (test-admin arms a separate fresh session with `faults.audit_failures: 1`;
a refused capability fails), `fault_failure_envelope` (the Phase 4 `P3-AUDIT-FAILURE-ENVELOPE`:
upload `clean_all_six` in that session, then the exact `TEST_AUDIT_FAILURE` envelope, version,
failed report with no checks, and unchanged source download), `fault_recovery` (a manual
re-audit runs normally; the failed audit, its report and history order are unchanged),
`fault_auth` and `fault_invalid` (refused setups: 401/403, or 400 source system, and no
runnable session; `credential`/`vector` parameters select one vector). Fault session IDs go
into the run record as `fault_session_ids` and are queued for `cleanup_session_ids` once the
run is stored; their coverage is never requested.

Without a fixture pack the 35 fixture-based cases skip. A failed prerequisite skips the
cases that depend on it; an audit with wrong findings still counts as usable, a
`PROCESSING_FAILED` audit does not. The test fake audits with `tester/suite/pod_rules.py`,
not the expectations, so the rehearsal compares two independent sources.

Team 12's Phase 4 pack (ruleset 2.0.0) is started in `tester/fixtures/phase4/`:
`clean_all_six`, `seeded_all_six` and the five correction fixtures (`alt_supported`,
`rename_references`, `link_supported`, `header_range`, `header_disabled_table`), built by
`scripts/build_phase4_fixtures.py`, with six-rule expectations and exact correction values
and effects hand-written to the spec §15.2 record fields. None has been reviewed by Team 9
or opened in Excel; the remaining Phase 4 fixtures are listed in its README.

Team 12's fixture pack in `tester/fixtures/shared/` covers every fixture the Phase 3
manifest names and loads with `EXPECTATIONS_PATH=tester/fixtures/shared/expectations.json`.
None of its files has had the cross-team review yet, and the ten added on 2026-10-31
have not been opened in Excel; see its README.
