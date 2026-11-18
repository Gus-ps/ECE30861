# AGENTS.md

ECE 30861 (Team 12) Excel accessibility hub. This repository holds several separate
components, and each one lives on its own branch. `main` contains only a stub README.
Before working, find out which branch you are on: each branch has different files,
dependencies and test commands.

## Project

Pod E (Teams 9 and 12) is building a web service with the following workflow:

1. Users upload `.xlsx` workbooks.
2. The service audits each workbook against shared WCAG 2.1 A/AA rules (28 C.F.R. § 35.200).
3. It applies user-approved fixes to a **new copy** of the workbook.
4. It reports findings, keeps version history, and re-audits stored versions on a schedule.

`ECE 30861 Phase 2 Pod E.pdf` (untracked, at the repo root) records the project's intent:
requirements REQ-01 to REQ-15, acceptance tests AC-01 to AC-18, a planned `/api/v1`
contract (Operations 1 to 14) and a phase plan.

Use the PDF to understand **what** to build next and **why**. It is not the authority
on how things must be done:
- Don't audit or "correct" existing code because it differs from the PDF.
- The current decisions live in the code and in the newer team documents:
  - **Phase 5 (current):** `ref/Phase5_Agent_Context_Pack/` on `Logan-tester-phase5`
    (specification and pack 3.0.0, ruleset 2.0.0). Read `Phase5_Shared_Specification.md`
    first, then `CHANGELOG.md`. Its `baseline_phase4/` folder keeps the Phase 4 pack
    unchanged.
  - **Phase 4 baseline:** `.docs/phase4_agent_context_pack/` on Haruki's branch (pack 2.1.1).
  - **Schedule implementation decisions:** `docs/phase5_system_decisions.md` on
    `haruki/phase5-schedule`.
- When the PDF and those sources differ, follow the current sources. Raise the difference
  with the team instead of changing code to match the PDF.

Guiding principles from the project's intent:
- **The source workbook is immutable.** Never modify, overwrite or publish it. Remediation
  always writes a separate version.
- **Never invent meaning.** Alt text, worksheet names, table structure and the meaning of
  color need user input or manual review.
- **Failures never yield output.** A failure records an error and returns
  `PROCESSING_FAILED`. Never expose a partial file or report as successful.
- **Use only the shared statuses:** `PROCESSING`, `AUDIT_COMPLETE`, `REVIEW_REQUIRED`,
  `REMEDIATION_AVAILABLE`, `REMEDIATING`, `REMEDIATED`, `PROCESSING_FAILED`. Never use
  "ADA compliant", and make no legal determinations.
- **The HTTP contract is shared.** Cross-team tests swap only the base URL. Change
  endpoints, schemas or status codes only by pod agreement.
- **Results must be deterministic.** The same workbook with the same ruleset must give the
  same finding IDs, categories and locations.
- **Findings are ordered** by rule ID, then worksheet, then target.
- **Upload limits:** `.xlsx` only, at most 25,000,000 bytes, 50 worksheets and 250,000
  nonempty cells.
- **Rejected file types:** `.xls`, `.xlsm`/macros, CSV, encrypted, password-protected and
  corrupted files.

## Phase roadmap

This roadmap follows the PDF's phase plan. Treat it as a guide to what to work on, not as
a checklist for judging work that is already done. The REQ and AC numbers point to the
intent behind each item.

### Phase 3: complete

What was delivered:
- Authentication
- Upload and validation
- ALT_TEXT and WORKSHEET_NAME audits
- Operations 1, 2, 4 and 5 (on `Gustavo`)
- The tester's session interface (on `Logan`)

Keep the Phase 3 tests (AC-01, AC-02, the audit-only part of AC-03, and the Phase 3 parts
of AC-04/05) passing as regression tests.

### Phase 4: complete

Phase 4 covered REQ-03 to REQ-11 and AC-03 to AC-11, with AC-01/02 rerun. The integrated
service is commit `c880566` on `Gustavo`. That commit merged Jonathan's remediation module
and exposed the Phase 4 workbook API.

What was delivered:

| Area | What was delivered | Where |
| --- | --- | --- |
| Audit rules | All six rules run in the fixed order ALT_TEXT, WORKSHEET_NAME, TABLE_HEADER, MERGED_CELLS, LINK_TEXT, COLOR_CONTRAST, under ruleset `2.0.0` | `accessibility_checker/` (from `haruki/accessibility-checker`), run through `service_worker.py` |
| Human review | `GET .../audits/{auditId}/review` returns `REQUIRES_USER_INPUT` and `MANUAL_REVIEW` findings with suggested value templates. Decisions are validated before any write | `phase4_service.py`, `remediation.py` (`review`, `validate_decisions`) |
| Remediation | Applies only approved fixes: alt text, worksheet rename (with reference rewrites), hyperlink text and a confirmed table header row. Writes a new version, never the source | `remediation.py` (Jonathan), Op 7/8 |
| Preservation (REQ-09) | Each output is compared with its source. Every changed part must be explained by an approved change, or the remediation fails with no output | `remediation.py` (`_verify`, `_check_preservation`) |
| Endpoints | Op 3 (new version), Op 6 (re-audit; 409 `ACTIVE_OPERATION` while one is active), Op 7 (submit remediation), Op 8 (remediation status), Op 9 (download output), Op 10 (history), plus review, report and source download | `phase4_service.py` |
| Audit report (REQ-10) | `GET .../audits/{auditId}/report` | `phase4_service.py`, `phase4_contracts.py` |
| Versioning (REQ-11) | Every upload, remediation output and re-audit is a new record, and earlier records stay unchanged | `phase4_store.py` |
| Background jobs | A job queue with leases. On startup, interrupted jobs are failed with `WORKER_LOST` and publish no output. The checker and remediation run in a memory-limited child process | `phase4_jobs.py`, `service_worker.py` |
| Test interface | Isolated test sessions (namespaces) and a one-shot injected audit fault | `test_interface.py`, `p4_faults` table |
| Reviewer access | Read-only reviewer grants through `REVIEWER_GRANTS_JSON`. Reviewers can't change a workbook | `phase4_service.py` (`lookup`) |
| Validator | Remediation, user-input handling and sample workbooks (`sample_files/`) | `Jonathan` |
| Tester | All 215 hosted cases of the Phase 4 test plan have checks, through manifest `2.1.1-team12-draft`. They all pass against the local stand-in service | `Logan` |

Phase 4 items still open (carried into Phase 5 as acceptance work):
- Human evidence for AC-09: opening outputs in Excel without a repair prompt, and the
  five-workbook precision check.
- The Team 12 rename mismatch (Haruki's AE-021). It waits on Team 9's report.
- The `Gustavo` README still describes Phase 3 (ruleset `1.0.0`, no recovery worker). The
  code is the authority.
- The `Gustavo` test suite has known failures inherited from Phase 3 tests and older
  fixtures (see the `Gustavo` section). Don't treat them as Phase 4 regressions.

### Phase 5: current

The goal is to complete REQ-12 to REQ-15. Implement AC-12 to AC-18 and rerun AC-01 to
AC-11 as regression tests. The shared target is specification 3.0.0. Ruleset `2.0.0`, the
`/api/v1` prefix and health `apiVersion` `1.0` don't change.

| Area | What to do | Where it stands |
| --- | --- | --- |
| Scheduling (REQ-12, AC-12, Op 11 and G) | `PUT` and `GET /api/v1/workbooks/{id}/schedule`. A `PUT` replaces the whole schedule. When enabled, `intervalDays` must be a strict integer from 1 to 90; reject 0 and 91 with 400. The schedule follows the newest stored version, including remediation outputs. Missed periods are combined into one audit. Every scheduled audit creates a new record | Schedule configuration and deletion cleanup are integrated. Operation 13 accepts due audits for test namespaces. Real-time dispatch is pending |
| Deadline reminders (REQ-12, AC-13) | The optional `complianceDeadline` creates reminders at UTC midnight 90, 30 and 7 days before the date. Send them only for workbooks with unresolved findings or no completed audit. Don't backfill earlier reminders, and never send one twice. Each result states that changes to an external workbook can't be detected | Operation 13 evaluates and deduplicates UTC deadline reminders for test namespaces. Real-time reminder processing is pending |
| Notifications (Op 12) | `GET .../notifications` returns stored records with status `PENDING`, `DELIVERED` or `FAILED`. Deliver inside the app only, not by email. A failed delivery never changes the audit status | Owner and granted reviewer can read durable in-app records. Operation 13 records DELIVERED or FAILED and supports the isolated notification fault |
| Test clock (Op 13) | `POST /api/v1/test/clock` exists only in the test deployment (404 elsewhere) and needs the test-runner credential. Each test namespace has its own durable clock, starting at 2027-01-01 UTC. Advancing it is atomic, gives the same result if repeated with the same time, and triggers any audits and reminders that are due. Real timeouts and leases don't follow the simulated clock | Setup, advancement and cleanup use durable clocks behind `ENABLE_TEST_CLOCK`. Advancing a clock atomically accepts due periodic audits. Reminders and notifications are pending |
| Deletion (Op 14, AC-16) | The owner can delete a workbook. Deletion removes the source, outputs, reports, schedule and notifications, and cancels scheduled audits. It must finish correctly after storage failures, active work or a restart. Never report success while copies remain | Owner deletion and the pre-delete fault are integrated. Successful deletion removes the schedule, notification records and considered reminder keys in one transaction. Durable cleanup recovery, backup handling and cancellation of scheduled work remain pending |
| Access control (REQ-14, AC-15/16) | Only the owner and an explicitly authorized reviewer can access a record. Every other user, and any unauthenticated request, is denied without revealing metadata. HTTPS only, with no plaintext passwords | Owner checks and read-only reviewer grants exist. Needs AC-15 tests, plus deployment evidence for HTTPS and password storage |
| Failure handling (REQ-13, AC-14) | Extend the one-shot injected faults to remediation, report finalization, upload storage, scheduled audits, notifications and failures before deletion. The source stays unchanged, and no partial output is reported as successful | Audit faults and restart recovery exist. The other fault types are not started |
| Interface accessibility (AC-17) | `static/index.html` works fully by keyboard, focus is visible, inputs have labels, errors are given as text, and text contrast is at least 4.5:1 (3:1 for large text). The interface must cover upload, findings, remediation, scheduling and download. Collect automated scan results and a keyboard walkthrough | Not started |
| Performance (AC-18) | A workbook at the size limits is audited in 60 seconds or fails in a controlled way, and five repeat runs give identical findings. Queue time and run time are reported separately | At risk. Haruki's measurements (AE-022) show some boundary workbooks timing out or failing with `MemoryError` in the 384 MiB worker. Further optimization waits on the production instance type |
| Tester | Implement the Phase 5 test plan (435 entries: 249 inherited, 186 new). The suite has a 2,400-second budget. Own-team reports include `coverage.model`, and cross-team reports must leave it out | The pack is on `Logan-tester-phase5`. Checks are not started |
| Adoption and docs | Fill in `ADOPTION.md` (pack hash, base URLs, release SHAs, evidence), and update the schedule model, security docs, accessibility evidence, performance results and known limitations | `ADOPTION.md` is still unfilled. Haruki's AE-021 to AE-023 items are open |

To demonstrate Phase 5 is done:
1. Advance the test clock, and show a scheduled audit and a reminder being triggered.
2. Show that another user's access is denied.
3. Inject a processing failure and show it is controlled.
4. Complete the interface workflow using only the keyboard.

Fallbacks if the schedule slips: support fewer remediation types, lower the limits, or
keep notifications in the app only. Keep the core flow of upload, audit, review,
downloadable copy and report.

## Branch map

| Branch | Owner | Contents |
| --- | --- | --- |
| `Jonathan` | Jon | Upload validity checker (standard library only), remediation module (`remediation.py`) and sample files |
| `haruki/accessibility-checker` | kuwaharr | `accessibility_checker` package: WCAG 2.1 screening rules, plus `.docs/` notes and the Phase 4 pack |
| `haruki/phase5-schedule` | kuwaharr | Integrated service with Phase 5 schedule configuration (Op 11/G), plus access, deletion, test interface and UI work merged from `Jon-Gus_branch` |
| `Gustavo` | Gus-ps | Integrated FastAPI service: validator, six-rule checker, remediation, Phase 4 API; AWS deploy |
| `Jon-Gus_branch` | Jon | Phase 5 workbook access, deletion, test interface and UI work based on `Gustavo`, merged into `haruki/phase5-schedule` |
| `Logan` | Logan Hanson | Cross-team tester service (`tester/`) with Phase 3 and Phase 4 manifests |
| `Logan-tester-phase5` | Logan Hanson | `Logan` plus the Phase 5 context pack (`ref/Phase5_Agent_Context_Pack/`) |
| `Logan-phase5` | Gus-ps | Currently the same commit as `Gustavo` (`c880566`) |

How the branches depend on each other: `Gustavo` merged `haruki/accessibility-checker`
and `Jonathan` (remediation). It also carries copies of the validators, and those copies
can drift from `Jonathan`'s. If you change the validator, checker or remediation on one
branch, check the other copies.

## Jonathan: validity checker and remediation

- `validity_check.py` checks a file path. `validate_file(path)` returns a list of error
  strings, where an empty list means the file is valid. `check_validity(path)` prints the
  result and returns a bool.
- `validity_check_object.py`: `validate_file(file_obj, filename)` checks a file-like object.
- `validity_check_error_return.py`: a variant of the path version that returns a list of errors.
- Limits, all constants at the top of the file: `.xlsx` only, 25 MB, 50 worksheets,
  250,000 nonempty cells. Files that are OLE2/encrypted, corrupted, or have workbook or
  sheet protection are rejected.
- Use the standard library only. Don't add runtime dependencies.
- Run it: `python validity_check.py <file>`. Exit code 0 means valid, 1 means invalid, 2 means usage error.
- There is no unit test suite for the validator. Verify changes against `sample_files/`:
  `valid.xlsx` must pass, and every other file must fail for exactly the one reason its
  name gives.
- To regenerate the samples, run `pip install openpyxl msoffcrypto-tool` and then
  `python sample_files/generate_samples.py`.
- `remediation.py`: `review(path)`, `validate_decisions(path, decisions, findings)` and
  `remediate(src, dst, decisions, findings)`. Remediation writes only to `dst`, then checks
  that every changed part is explained by an approved decision. Any problem raises
  `RemediationError`, and no output is kept. Tests: `test_remediation.py`.

## haruki/accessibility-checker

- Entry point: `accessibility_checker.runner.check_workbook(path)`. It runs the rules in the
  fixed `RULE_ORDER`: ALT_TEXT, WORKSHEET_NAME, TABLE_HEADER, MERGED_CELLS, LINK_TEXT,
  COLOR_CONTRAST.
- Each rule lives in `accessibility_checker/checks/` and has the signature
  `check_x(path, *, source_sha256=None)`.
- `workbook_title.py` and `legacy_table_headers.py` are kept for history and must not be
  called from the runner.
- Setup: `pip install -r requirements.txt` (openpyxl 3.1.5, defusedxml 0.7.1).
- Tests: `python -m unittest discover -s tests`. The last recorded run was 172 tests OK
  with 1 skipped.
- Lint: `ruff format --check .` passes, with line length 100 set in `pyproject.toml`.
  `ruff check` currently reports existing errors, so don't treat it as a gate.
- The Phase 4 contract is `.docs/phase4_agent_context_pack/`, pack 2.1.1, ruleset 2.0.0.
  Read `CORRECTIONS.md` first, and verify `SHA256SUMS.txt` if you touch the pack. Current
  status and open coordination items (AE-021 to AE-023) are in `.docs/checker_notes_en.md`
  and `.docs/assumptions_and_extensions.md`.
- Constraints:
  - Checkers are read-only and must never modify the source workbook.
  - Parse XML through `safe_xml` (defusedxml).
  - Never fetch external relationships or link targets.
  - Represent cases you can't resolve as MANUAL_REVIEW findings with limitations; don't guess.
  - An execution failure propagates. Never return partial findings.
  - Never regenerate fixture expectations (`tests/fixtures/*.expected.json`) using the code
    under test.

## Gustavo: workbook service

- Files:
  - `app.py`: entry point and validator loading
  - `phase4_service.py`: FastAPI routes, authentication and access checks
  - `phase4_jobs.py`: job queue, leases and restart recovery
  - `phase4_store.py`: versioned records
  - `phase4_contracts.py` and `contracts.py`: response schemas
  - `service_worker.py`: child-process bridge to the checker and remediation
  - `remediation.py`, `package_checks.py`, `service_errors.py`
  - `database.py`: SQLite locally, PostgreSQL on AWS
  - `test_interface.py`: test sessions
  - `static/index.html`: the website
- Environment variables:
  - `API_TOKENS_JSON` maps bearer tokens to users.
  - `REVIEWER_GRANTS_JSON` maps a reviewer to the owners whose workbooks they can read.
  - `ENABLE_TEST_INTERFACE`, `TEST_ADMIN_TOKENS_JSON` and `TEST_SESSION_USERS_JSON`
    control the test interface.
  - `VALIDATOR_PATH` can point to a different validator module.
- Setup and run:
  ```powershell
  python -m pip install -r requirements.txt
  $env:API_TOKENS_JSON = '{"<token>":"test-user"}'
  python -m uvicorn app:app --reload
  ```
  There are no default credentials. The SQLite file defaults to `data/workbooks.sqlite3`
  and can be changed with `DATABASE_PATH`.
- Tests:
  ```
  python -m pip install httpx==0.28.1
  python -m unittest discover -s tests
  python -m unittest test_remediation
  ```
  `tests/` has 88 tests. The recorded baseline (Python 3.14) is 14 failures, 41 errors
  and 1 skipped. Those failures come from older checker/ruleset expectations, incomplete
  older fixtures and Phase 3 namespace assumptions. The exact list is in
  `docs/phase5_system_decisions.md` (SYS-006) on `haruki/phase5-schedule`. Compare
  against that list: a change must add no new failures. The skipped PostgreSQL test needs
  `RUN_POSTGRES_TESTS=1` and a TLS test database.
- Constraints:
  - Originals are immutable.
  - A rejected upload creates no version or audit.
  - The upload limit is 25,000,000 bytes.
- `scripts/deploy-aws.ps1 -Deploy` creates billable AWS resources. Never run it without
  explicit approval, and never commit secrets. `scripts/deploy-ec2-demo.ps1` and
  `update-ec2-demo.ps1` manage the EC2 demo deployment.

## Logan: tester

- Uses Python 3.12 and uv (`pyproject.toml`, `uv.lock`). The app factory is
  `tester.main:create_app`.
- Setup and run:
  ```
  uv sync --group dev
  cp .env.example .env
  uv run uvicorn tester.main:create_app --factory --port 8001
  ```
  Set `MANIFEST_PATH=tester/fixtures/manifest_phase4.json` to run the Phase 4 manifest.
- Tests: `uv run pytest`.
- End-to-end rehearsal: `uv run python scripts/rehearsal/rehearse.py`. It needs ports
  8100–8102 to be free.
- `tester/fixtures/manifest.json` is a copy of Team 9's manifest. Don't edit it locally.
  Committed fixture bytes must match `scripts/build_shared_fixtures.py --check`.
- The Phase 5 pack on `Logan-tester-phase5` comes with `validate_pack.py`, which needs
  `jsonschema`. It checks only that the pack is consistent, not any implementation.

## Windows caveats (verified on this machine, Python 3.14)

- `core.autocrlf=true` rewrites Logan's `tester/fixtures/shared/corrupt.xlsx`, because git
  treats it as text. That breaks 2 fixture hash tests.
- Haruki's suite has failed some tests on Windows:
  - Integration tests look for `"/accessibility_checker/"` in profiler paths, which never
    matches Windows backslash paths.
  - 1 test reads a pack file without an explicit encoding. It passes with `PYTHONUTF8=1`.
- In Git Bash, `git show <branch>:<path>` can fail because the path gets converted to
  Windows form. Set `MSYS_NO_PATHCONV=1` first.
- These are environment failures, not logic regressions. Confirm the cause before
  "fixing" checker code because of them.

## General

- Don't commit `__pycache__/`, `.venv/`, `.env` or `data/`.
- The repo root has untracked files that aren't part of any component: `Lab2/`,
  `AGENTS.md`, `ECE 30861 Phase 2 Pod E.pdf`, and on `Jonathan` the `WCAG_2.1_*.txt`
  reference notes.
- Keep changes on the owning branch. Coordinate cross-branch contract changes (finding
  schema, rule IDs, validator interface, schedule and deletion semantics) with the
  branch owner.
