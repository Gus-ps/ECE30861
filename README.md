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
| `tester/fixtures/pod_profile_phase5.json` | Phase 5 bounds (2,400 s suite) and C1-C12 / AC-01 to AC-18 catalogs from spec 3.0.0; needs a Phase 5 manifest |
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

It needs free ports 8100–8103 (nothing may listen on 8199), takes about three minutes, prints
one PASS/FAIL line per check and exits 0 when all 34 pass. Logs and the happy-path report
are written to `scripts/rehearsal/work/` (gitignored). Scenarios:

| Scenario | Checks |
| --- | --- |
| A. Happy path | 401/400 rejections, setup 201, system setup body and token, 409 before and after run, 53 valid results (52 pass; the controlled-failure case skips because no audit failed) with the shared fixture pack, 31 uploads including two 25 MB workbooks, code coverage, stored report identical to the run body |
| B. Setup failures | system error forwarded unchanged, invalid 5xx body, unreachable system, failed IDs sent as `cleanup_session_ids` |
| C. Timeout | a stalled system report is cut off at 10 s as error/communication |
| D. Base path | `--root-path /tester` works when the proxy strips `/tester`; an unstripped path is 404 |
| E. Crash | tester killed mid-run; after restart the report is aborted with the interrupted case as error/tester |
| F. Phase 4 | a second tester runs the draft Phase 4 manifest (215 cases) against the stand-in at ruleset 2.0.0: all 215 pass, and the next setup queues the run's 5 extra sessions for cleanup |
| G. Phase 5 | a third tester, configured as Team 12 against its own (stand-in) system with the Phase 5 pack and both optional access tokens, runs the draft Phase 5 manifest (357 cases) with Phase 5 switched on in the stand-in: 344 pass and 13 skip (the 6 unbuilt tester self-checks, 3 cases no HTTP request can produce, and 4 busy cases the stand-in finishes too fast for), and the report carries `coverage.model` over the 38-requirement design map |

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

### Phase 4

Every hosted case of the Phase 4 test plan has a check. The context pack in
`ref/Phase4_Agent_Context_Pack/` is revision 2.1.1 (specification 2.1.0, ruleset 2.0.0; its
`CORRECTIONS.md` fixes two tint vectors and sets suite target 2.1.1). There is no shared
executable manifest, so `tester/fixtures/manifest_phase4.json` (`2.1.1-team12-draft`) is generated
from the plan by `scripts/build_phase4_manifest.py` (all 215 hosted IDs in plan order; the
check mapping lives in that script). Run Phase 4 by pointing the tester at it:

```sh
MANIFEST_PATH=tester/fixtures/manifest_phase4.json \
POD_PROFILE_PATH=tester/fixtures/pod_profile_phase4.json \
EXPECTATIONS_PATH=tester/fixtures/phase4/expectations.json \
uv run uvicorn tester.main:create_app --factory --port 8001
```

| Path | Purpose |
| --- | --- |
| `tester/suite/checks_phase4.py` | Phase 4 checks: rule vectors, review context, new versions, re-audits, downloads, remediation (judged by the comparator), rejections, idempotency, the 63-case access matrix, session cases |
| `tester/fixtures/phase4/` | 34-entry ruleset 2.0.0 pack: 30 built by `scripts/build_phase4_fixtures.py`, plus Team 9's four pod contract 1.1 fixtures (`in_cell_picture`, `image_formula`, `form_controls`, `vml_comments`; bytes unchanged, expectations re-derived by Team 12); per-fixture intent, hashes and finding IDs in its README |
| `tests/fake_phase4.py` | Phase 4 routes of the test fake |

Against a conforming fake, all 215 cases pass. The
fake answers six-rule audits from the pack's own answer key and edits outputs with the
comparator's change model, so those self-tests prove the tester's plumbing and its judgement
of wrong answers (`tests/test_phase4_suite.py`), not rule agreement; only a real system run
does that. No Phase 4 fixture has been reviewed by Team 9. Every accepted Phase 4 fixture opened in Excel on
2026-11-01 without a repair prompt, except `table_header_vectors`, whose Blank and Duplicate tables Excel
repairs as expected, and Team 9's `form_controls`, which Excel repairs because of a namespace
defect in Team 9's file (reported to them; see the pack README). Correction outputs have not
been opened yet.

### Phase 5 (in progress)

The Phase 5 context pack 3.0.0 is in `ref/Phase5_Agent_Context_Pack/` (byte-for-byte; its own
`validate_pack.py` fails only its last check on Windows, a path-separator bug in the script).
`scripts/build_phase5_manifest.py` generates `tester/fixtures/manifest_phase5.json`
(`3.0.0-team12-draft`): all 357 hosted cases in plan order. The 215 inherited cases keep the
Phase 4 draft's checks. All 142 new ones are built in `tester/suite/checks_phase5.py`:
clock (10), schedule (29), reminders (24), deletion (9), faults (16), access (42), performance
(6) and the hosted tester self-checks (6). Each case that moves time or arms a fault prepares its
own fresh namespace; expected times come from the tester's own UTC arithmetic and the plan's
frozen vectors; access cases take their expected status from the plan's inputs and also require
the §12 code (401 UNAUTHORIZED, 403 FORBIDDEN, 404 NOT_FOUND). As agreed with Team 9, the
self-checks judge a provisional report built by the same `build_report` the run finalizes with;
CODE-COPY reads the target's session report during the run and the report copies it exactly.
The final-versus-stored byte comparison is checked outside the suite (the tests and rehearsal G).

Cases that skip with a stated reason:
- `P5-CLOCK-NOT-READY` and `P5-FAULT-REJECT-DISABLED`: not producible over HTTP (no request can
  hold a namespace not ready; faults are on for every other case). Agreed with Team 9 as local
  evidence (P4-LOCAL-FAULT-DISABLED for the switch).
- `P5-DELETE-RETAIN-TESTER`, when this tester's store holds no earlier finalized report. With one,
  it hashes every finalized report before and after deleting a target workbook.
- `P5-TESTER-SELF-MODEL` on a cross-team run and `P5-TESTER-CROSS-OMIT` on an own-team run.
- The four busy cases, when the target finishes its work before the clock call or DELETE.
- The five access cases needing `reviewer-ungranted` or `test-admin-2`, when the target team has not
  provided that identity (Team 9 has asked that these skip, naming the missing identity).

A setup sends at most 100 queued cleanup IDs; the rest wait. Run it with
`MANIFEST_PATH=tester/fixtures/manifest_phase5.json POD_PROFILE_PATH=tester/fixtures/pod_profile_phase5.json
EXPECTATIONS_PATH=tester/fixtures/expectations_phase5.json`. Against the conforming fake, every
built case passes except those skips, and 14 deliberately broken fakes each fail exactly the
case for their rule (`tests/test_phase5_suite.py`).

The Phase 5 pack, `tester/fixtures/expectations_phase5.json`, is built by
`scripts/build_phase5_fixtures.py`. It holds the Phase 4 pack's entries unchanged (files under
`phase4/`) plus `phase5/performance_250000_cells.xlsx`: exactly 250,000 nonempty cells in one
table, with expected status AUDIT_COMPLETE and no findings. That expectation is hand-authored; it
opened in Excel without a repair prompt on 2026-11-17, and one Team 9 reviewer agreed with it on
2026-11-17 (the two-reviewer form is still pending). `scripts/build_phase5_review_bundle.py` writes Team 9's
add-on review bundle. The 57 local and 21 manual plan entries are mapped to owners and evidence in
`docs/phase5-local-and-manual.md`. Team 12's draft adoption values and open shared decisions are
in `docs/phase5-adoption-team12.md`. Phase 5 rules already applied: a new report must say
`specificationVersion` 3.0.0 (the run's manifest decides), an unexpected PROCESSING_FAILED is
error/source system under the Phase 5 profile (fail under earlier ones), and any wrongly
accepted negative request's job is drained by bounded GETs (all phases). The remaining work
plan is in the shared doc's "Phase 5 tester plan".

Report profiles (spec 3.0.0 §14): under the Phase 5 profile each setup classifies the target as
own- or cross-team from `TESTER_TEAM_ID` and `TARGET_TEAMS_JSON` (exact base URLs; never from the
request) and freezes that with the session. An own-team run also freezes Team 12's design map
(`DESIGN_MAP_PATH`, draft `tester/fixtures/design_map_team12.json`: REQ-01 to REQ-15 plus the 23
state-machine transitions of the Phase 2 specification) and reports `coverage.model`: a requirement
counts once when one of its mapped tests executed its qualifying assertion. A cross-team report has
no `model` key; Phase 3 and 4 reports never do. A missing or invalid map, or an unconfigured team,
fails setup with 500/tester. The run record keeps the profile, map version and hash, and which
executed tests earned each requirement.

Team 12's fixture pack in `tester/fixtures/shared/` covers every fixture the Phase 3
manifest names and loads with `EXPECTATIONS_PATH=tester/fixtures/shared/expectations.json`.
None of its files has had the cross-team review yet, and the ten added on 2026-10-31
have not been opened in Excel; see its README.
