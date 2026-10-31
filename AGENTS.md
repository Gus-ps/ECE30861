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
- The current decisions live in the code and in the newer team documents, such as
  `.docs/phase4_agent_context_pack/` on Haruki's branch.
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
of AC-04/05) passing as regression tests. Don't change Phase 3 behavior unless Phase 4
needs it.

### Phase 4: current

The goal is to complete REQ-03 to REQ-11. Validate AC-03 to AC-11 and rerun AC-01/02.

| Area | What to do | Where it stands |
| --- | --- | --- |
| Audit rules | All six rules: ALT_TEXT, WORKSHEET_NAME, TABLE_HEADER, MERGED_CELLS, LINK_TEXT, COLOR_CONTRAST | Done in `haruki/accessibility-checker`. `Gustavo` still runs an older two-rule merge with ruleset `1.0.0` |
| Service integration | Merge the six-rule runner into the service and adopt ruleset 2.0.0 IDs | To do |
| Human review | Return `REQUIRES_USER_INPUT`/`MANUAL_REVIEW` findings. Accept decisions through Op 7 (`APPLY` with `value`, `DECLINE`, `MANUAL_REVIEW`). Reject `APPLY` without a required value with 400 | To do |
| Remediation | Apply only approved fixes: alt text, worksheet rename (with safe reference updates, see `rename_safety.py`), hyperlink text, and a confirmed header row. Write a new version with `sourceVersionId` set | Not started. The checkers are read-only by design, so this needs a separate writer |
| Preservation (REQ-09) | The output keeps all unrelated formulas, values, references, named ranges, formatting and charts, and opens in Excel without a repair prompt. Verify by comparing source and output, then inspect manually in Excel | Not started |
| Endpoints | Op 3 (new version), Op 6 (re-audit; return 409 if one is already processing), Op 7/8 (remediations), Op 9 (download output), Op 10 (history) | Not started on `Gustavo` |
| Audit report (REQ-10) | Include version, date, ruleset, checks performed, findings, approved changes, unresolved items, manual-review items and limitations | Not started |
| Versioning (REQ-11) | Every upload, remediation and re-audit creates a new record, and earlier records stay unchanged | Partial: uploads only |
| Tester | Add the Phase 4 checks from `phase4-test-plan.json`. Only the session checks are implemented now | To do on `Logan` |
| Docs | Update the interface schemas, workflow models, remediation rules, fixtures and known limitations | Ongoing |

To demonstrate Phase 4 is done:
1. Audit a seeded workbook.
2. Supply input, approve one fix and decline another.
3. Download the output.
4. Confirm the source hash is unchanged and the unrelated content is preserved.

### Phase 5: next

The goal is to complete REQ-12 to REQ-15. Implement AC-12 to AC-18 and rerun AC-01 to
AC-11.

- **Scheduling (Op 11):** `PUT /workbooks/{id}/schedule`. `intervalDays` must be 1 to 90;
  reject 0 and 91 with 400. The optional `complianceDeadline` sets reminders at 90, 30 and
  7 days, sent only for workbooks that have unresolved findings or no completed audit.
  Each result states that changes to an external workbook can't be detected.
- **Notifications (Op 12):** store notification records with status
  `PENDING`/`DELIVERED`/`FAILED`. A failed delivery never changes the audit status.
- **Test clock (Op 13):** `POST /api/v1/test/clock` exists only in the test deployment
  (404 elsewhere) and requires the test-runner credential. It triggers any audits and
  reminders that are due.
- **Deletion (Op 14):** removes the source, the outputs and the reports, and cancels any
  scheduled audits.
- **Security (REQ-14):**
  - Users can access only their own records.
  - An explicitly authorized reviewer also has access.
  - Every other user, and any unauthenticated request, is denied without revealing any
    metadata.
  - HTTPS only.
  - No plaintext passwords.
- **Failure handling (REQ-13):** use fault injection for audit, remediation, report,
  storage and scheduled-audit failures. Also add recovery for audits interrupted by a
  restart; `Gustavo` currently has no recovery worker.
- **Interface accessibility (AC-17):** the UI works fully by keyboard, focus is visible,
  form inputs have labels, errors are given as text, and text contrast is at least 4.5:1
  (3:1 for large text).
- **Performance (AC-18):** a workbook at the size limits is audited in 60 seconds or fails
  in a controlled way, and five repeat runs give identical findings.
- **Fallbacks if the schedule slips:** support fewer remediation types, lower the
  limits, or record notifications in the app only. Keep the core flow of upload, audit,
  review, downloadable copy and report.

## Branch map

| Branch | Owner | Contents |
| --- | --- | --- |
| `Jonathan` | Jon | Upload validity checker (standard library only) and sample files |
| `haruki/accessibility-checker` | kuwaharr | `accessibility_checker` package: WCAG 2.1 screening rules |
| `Gustavo` | Gus-ps | FastAPI upload service that combines the validator and the checker; AWS deploy |
| `Logan` | Logan Hanson | Cross-team tester service (`tester/`) for the instructor test interface |

How the branches depend on each other: `Gustavo` merged `haruki/accessibility-checker`
and carries a copy of `validity_check.py`. That copy has drifted from `Jonathan`'s
version: it adds macro rejection, unsafe-path and duplicate-member checks, and DTD/entity
rejection. If you change the validator on one branch, check the other copy.

## Jonathan: validity checker

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
- There is no unit test suite. Verify changes against `sample_files/`: `valid.xlsx` must pass,
  and every other file must fail for exactly the one reason its name gives.
- To regenerate the samples, run `pip install openpyxl msoffcrypto-tool` and then
  `python sample_files/generate_samples.py`.

## haruki/accessibility-checker

- Entry point: `accessibility_checker.runner.check_workbook(path)`. It runs the rules in the
  fixed `RULE_ORDER`: ALT_TEXT, WORKSHEET_NAME, TABLE_HEADER, MERGED_CELLS, LINK_TEXT,
  COLOR_CONTRAST.
- Each rule lives in `accessibility_checker/checks/` and has the signature
  `check_x(path, *, source_sha256=None)`.
- `workbook_title.py` and `legacy_table_headers.py` are kept for history and must not be
  called from the runner.
- Setup: `pip install -r requirements.txt` (openpyxl 3.1.5, defusedxml 0.7.1).
- Tests: `python -m unittest discover -s tests` (150 tests).
- Lint: `ruff format --check .` passes, with line length 100 set in `pyproject.toml`.
  `ruff check` currently reports existing errors, so don't treat it as a gate.
- The contract is `.docs/phase4_agent_context_pack/`, pack 2.1.1, ruleset 2.0.0. Read
  `CORRECTIONS.md` first, and verify `SHA256SUMS.txt` if you touch the pack.
- Constraints:
  - Checkers are read-only and must never modify the source workbook.
  - Parse XML through `safe_xml` (defusedxml).
  - Never fetch external relationships or link targets.
  - Represent cases you can't resolve as MANUAL_REVIEW findings with limitations; don't guess.
  - An execution failure propagates. Never return partial findings.
  - Never regenerate fixture expectations (`tests/fixtures/*.expected.json`) using the code
    under test.

## Gustavo: upload service

- Files: `app.py` (FastAPI), `database.py` (SQLite locally, PostgreSQL on AWS),
  `contracts.py` (response schemas), `static/index.html`.
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
  ```
  This runs 75 tests, and 1 is skipped: the PostgreSQL test needs `RUN_POSTGRES_TESTS=1`
  and a TLS test database.
- Constraints:
  - Originals are immutable.
  - A rejected upload creates no version or audit.
  - The upload limit is 25,000,000 bytes.
- `scripts/deploy-aws.ps1 -Deploy` creates billable AWS resources. Never run it without
  explicit approval, and never commit secrets.

## Logan: tester

- Uses Python 3.12 and uv (`pyproject.toml`, `uv.lock`). The app factory is
  `tester.main:create_app`.
- Setup and run:
  ```
  uv sync --group dev
  cp .env.example .env
  uv run uvicorn tester.main:create_app --factory --port 8001
  ```
- Tests: `uv run pytest` (71 tests).
- End-to-end rehearsal: `uv run python scripts/rehearsal/rehearse.py`. It needs ports
  8100–8102 to be free.
- `tester/fixtures/manifest.json` is a copy of Team 9's manifest. Don't edit it locally.
  Committed fixture bytes must match `scripts/build_shared_fixtures.py --check`.

## Windows caveats (verified on this machine, Python 3.14)

- `core.autocrlf=true` rewrites Logan's `tester/fixtures/shared/corrupt.xlsx`, because git
  treats it as text. That breaks 2 fixture hash tests.
- Haruki's suite fails 5 tests on Windows:
  - 4 integration tests look for `"/accessibility_checker/"` in profiler paths, which never
    matches Windows backslash paths.
  - 1 test reads a pack file without an explicit encoding. It passes with `PYTHONUTF8=1`.
- These are environment failures, not logic regressions. Confirm the cause before
  "fixing" checker code because of them.

## General

- Don't commit `__pycache__/`, `.venv/`, `.env` or `data/`.
- The repo root on `Jonathan` has untracked files that aren't part of any component:
  `Lab2/` and the `WCAG_2.1_*.txt` reference notes.
- Keep changes on the owning branch. Coordinate cross-branch contract changes (finding
  schema, rule IDs, validator interface) with the branch owner.
