# Phase 5 system decisions

Updated 2026-11-16. Configuration only: operations 11/G, ruleset 2.0.0 unchanged.
These decisions summarize the shared schedule/strict JSON/authorization contract
so no unpublished source file is needed. No claim of full Phase 5 acceptance.

## SYS-001 — Dedicated additive schedule persistence (2026-11-16)

- **Source / scope:** REQ-12 / AC-12 schedule durability; existing resource tables remain unchanged.
- **Exact rule / interpretation:** Use p5_schedules keyed by workbook_id with namespace/owner, normalized configuration, due and update timestamps; index next_audit_at.
- **Rationale / alternatives / risks:** A dedicated table was explicitly authorized. Reusing resource payloads was rejected by the work request. No foreign-key migration or change to existing tables is introduced.
- **Approval status:** Developer explicitly approved the dedicated-table direction; developer work request only, no recorded Pod approval.
- **Implementation / verification status:** Implemented in phase5_schedule.initialize/read/write; store test passes. SQLite verified; PostgreSQL not executed.

## SYS-002 — Effective UTC time and due calculation (2026-11-16)

- **Source / scope:** Schedule replacement and initial_due policy: fixed 86400-second UTC days, years 0001–9999.
- **Exact rule / interpretation:** effective_now(db, namespace) returns aware real UTC time. Tests patch it. Enabled/interval changes recalculate; deadline-only/replay preserve due; disable clears due. Overflow returns TIME_RANGE_EXCEEDED before writes.
- **Rationale / alternatives / risks:** Central function is the requested future virtual-clock seam. No clock state, dispatch, reminders or external time library is added.
- **Approval status:** Developer work request only; no recorded Pod approval of implementation details.
- **Implementation / verification status:** Implemented in phase5_schedule.write/effective_now. Tests cover 2027/2028 +90 days, interval, replay, deadline, disable/re-enable and overflow rollback.

## SYS-003 — Authorization before strict body interpretation (2026-11-16)

- **Source / scope:** AC-15: authentication, namespace, lookup, authorization, then body/state validation; strict JSON and ProjectError.
- **Exact rule / interpretation:** Use Request bytes, authorize through existing user/lookup inside the transaction, then UTF-8 decode and json.loads with duplicate-key/nonfinite rejection, then strict Contract validation and exact date form plus calendar validation.
- **Rationale / alternatives / risks:** A typed FastAPI body parameter could validate before lookup/authorization. Existing dependencies and stdlib suffice. OpenAPI supplies request schema explicitly while response model and bearer dependency remain native.
- **Approval status:** Developer work request only; no recorded Pod approval of implementation details.
- **Implementation / verification status:** Implemented in phase4_service routes and phase5_schedule.parse_body. Tests cover bool/string/float/exponent integers, duplicate/unknown keys, invalid dates/UTF-8/NaN and invalid unauthorized bodies. Existing global body-size middleware is unchanged.

## SYS-004 — Read-only defaults and version selection (2026-11-16)

- **Source / scope:** ScheduleResponse defaults, newest committed version, no GET writes.
- **Exact rule / interpretation:** Return disabled/null defaults without inserting rows; select version id by descending p4_resources.seq among kind=version. Include generated outputs; old re-audits do not affect selection.
- **Rationale / alternatives / risks:** Persisting a default during GET would add hidden side effects. UUID/name/audit timestamps do not encode creation order. Stored schedule does not pin versionId.
- **Approval status:** Developer work request only; no recorded Pod approval of implementation details.
- **Implementation / verification status:** Implemented in phase5_schedule.read. Tests verify no GET row increase, newer upload, actual remediation output and old re-audit.

## SYS-005 — Transactional update and namespace cleanup (2026-11-16)

- **Source / scope:** REQ-12 / AC-12, AC-15: atomic read/compare/write and namespace cleanup.
- **Exact rule / interpretation:** Use one write transaction, SQLite BEGIN IMMEDIATE; PostgreSQL locks the existing workbook resource row FOR UPDATE before reading the schedule, including first configuration. Identical normalized PUT is a no-op, including absent default configuration. Cleanup deletes only rows matching namespace after existing ownership/active-job checks.
- **Rationale / alternatives / risks:** Locking only a schedule row would not serialize initial inserts when no row exists. A per-workbook existing row avoids a new global lock. PostgreSQL behavior is inferred from transaction SQL and remains unverified.
- **Approval status:** Developer work request only; dedicated table approved, no recorded Pod approval. No scheduler/concurrency service is introduced.
- **Implementation / verification status:** Implemented in API and test_interface cleanup. Tests exercise active p4_jobs rejecting cleanup and completed jobs allowing cleanup. Existing active-operation semantics are unchanged.

## SYS-006 — Inherited failing regression baseline (2026-11-16)

- **Source / scope:** User explicitly authorized continuing with known baseline failures, comparing exact test/subTest IDs; legacy code/tests must not be repaired for this task.
- **Exact rule / interpretation:** Preserve baseline failure/error IDs and compare after each increment. New schedule tests must all pass. Do not count known failures as suite success.
- **Rationale / alternatives / risks:** Baseline 88 tests: 14 failures, 41 errors, 1 skip. Major classes are old checker/ruleset expectations, incomplete historical OOXML fixtures, and Phase 3 API/namespace/cleanup assumptions. These are observations, not proof every failure has one cause.
- **Approval status:** Developer continuation authorization only; no Pod approval and no authorization to fix legacy failures.
- **Implementation / verification status:** After implementation 94 tests: same 14 failures/41 errors/1 skip; 6 new tests pass. Exact 55 event tuples unchanged: new failures 0, resolved failures 0. .perf/baseline.json, storage.json and after_api.json retain subTest IDs; full logs and recorder are gitignored.
- **Baseline for subsequent changes:** Use `scripts/test_gate.py` and `scripts/test_baseline.json` for the regression gate.

## SYS-007 — Content-Type validation: not implemented; decision required (2026-11-16)

- **Source / scope:** Schedule GET / PUT review follow-up.
- **Exact rule / interpretation:** Content-Type validation is deferred for this change. PUT continues to use the existing strict JSON body validation.
- **Approval status:** Not implemented; decision required. Accepted media types and responses to mismatches remain to be decided.
- **Implementation / verification status:** No Content-Type validation or dedicated tests have been added.

Review follow-up verification: schedule GET / PUT now use contracts.Identifier.
Schedule tests cover malformed IDs, unknown test sessions, the seven-field wire
response, and disabled interval retention. All 9 schedule tests pass. Full suite:
97 tests, 14 failures, 41 errors, 1 skip. Exact failure/error event comparisons
against .perf/baseline.json, storage.json, after_api.json and final.json found
0 new and 0 removed events; review.json and review.log record this run.

## SYS-008 — Integrate workbook deletion and schedule configuration (2026-11-18)

- **Source / scope:** Merge `origin/Jon-Gus_branch` into `haruki/phase5-schedule` and apply shared specification §§4, 5, 10 and 11 to operations G, 11 and 14.
- **Locking:** Schedule PUT takes the same per-workbook `fence(db, workbook_id)` as DELETE before resource lookup. This supersedes SYS-005's PostgreSQL row lock. The fence uses a PostgreSQL transaction-scoped advisory lock and SQLite serializes writes with `BEGIN IMMEDIATE`.
- **Deletion:** DELETE removes the workbook's `p5_schedules` row in the same transaction as the workbook. This resolves the schedule portion of Jon's D4 under §10. The notification portion of D4 and cancellation of future work (D7) remain open.
- **Access control:** The access matrix covers schedule GET and PUT, including operation-specific success statuses, ACC-3 checks of denial bodies and headers, and schedule state checks after denials.
- **Approval status:** Developer work request only. No Pod approval.
- **Implementation / verification status:** Implemented and verified locally on SQLite. Tests cover schedule GET and PUT returning 404 after deletion, preservation on an injected pre-delete failure, preservation of other workbooks' schedules, a concurrent PUT and DELETE leaving no schedule row, and session cleanup removing schedule and fault rows. PostgreSQL lock behavior remains unverified.

## SYS-009 — Persist and advance isolated test clocks (2026-11-18)

- **Source / scope:** Shared specification §§4, 5, 9, 10, 12 and 13, and the Phase 5 clock wire schemas. This stage covers setup, cleanup, effective time and operation 13.
- **Capability and effective time:** The service reads `ENABLE_TEST_CLOCK=true` at startup and requires the test interface to be enabled. Fresh sessions get a clock initialized to `2027-01-01T00:00:00Z` or the explicit `setup.clock.currentTime`. Explicit clock setup with the capability disabled returns testing 403. Operation 13 returns project 404 `TEST_CLOCK_DISABLED` if the capability is disabled or the namespace header is absent. Ordinary data and namespaces without clock rows use real UTC time for schedule configuration. An existing ready session without a clock row returns 409 `LEGACY_SESSION_CLOCK` on advance. Existing sessions are kept as prepared because adding clocks later would silently change their time basis.
- **Storage and normalization:** `p5_clocks` stores one RFC3339 UTC timestamp per session. The canonical form ends in `Z`, omits the fractional part for whole seconds and uses exactly six digits when microseconds are nonzero. This preserves microsecond precision and keeps whole-second values in the shared default form. Advance compares aware UTC datetimes and treats equivalent encodings as equal.
- **Concurrency:** PostgreSQL locks the existing clock row with `SELECT … FOR UPDATE` inside the advance transaction. A row lock uses the same key as storage and cleanup and avoids an advisory lock key. If cleanup removes the row first, advance checks the session state again before reporting a legacy clock. SQLite uses its existing `BEGIN IMMEDIATE` write transaction. Cleanup deletes the clock in the same transaction as the session's other state.
- **Next stage:** `phase5_clock.process_due_work(db, session_id, instant)` runs inside the advance transaction after publishing the proposed time to that transaction and before commit, including on equal-time calls. It currently returns two empty lists. Future work can validate and record audit and notification acceptance there and return the newly recorded IDs. Raising an error rolls back clock and work together. `DELETION_IN_PROGRESS` is deferred because workbook deletion is synchronous and has no durable deletion reservation to check. Due-work limits and active-work checks are deferred with dispatch.
- **Approval status:** Developer work request only. No Pod approval.
- **Implementation / verification status:** Implemented and tested locally on SQLite. Coverage includes setup and cleanup, schedule due-time calculation, request precedence, namespace isolation, replay, restart persistence, and rollback on a simulated storage failure. PostgreSQL locking, production deployment, and real-time lease behavior during clock jumps remain unverified.

## Investigated inherited discrepancies (not fixed)

- test_cleanup_rejects_active_audits updates only the legacy audits table to
  PROCESSING. Current cleanup queries p4_jobs for PENDING/RUNNING. The upload has
  already drained that job, so changing the legacy row cannot make it active;
  cleanup returns 201 instead of the test's 409. The new schedule cleanup test
  uses actual p4_jobs states and preserves the existing guard.
- test_namespace_and_user_ownership_are_both_required expects 403 even without
  the matching namespace. Current lookup hides namespace mismatch with 404 before
  owner/grant checks. The first mismatched-namespace assertion aborts that test;
  it does not establish a same-namespace ownership regression.

## Executed verification and remaining limits

SQLite only, local Python 3.14. Dedicated storage test plus five API tests pass.
Existing tests and checker behavior were not changed. Existing service and cleanup
files received only integration needed for the authorized endpoints.
The tests cover the configuration portions of P5-SCHEDULE-DEFAULT/MIN/MAX,
PUT-REPLAY, DEADLINE-ONLY, INTERVAL-CHANGE, DISABLE, REENABLE, LATEST-UPLOAD,
LATEST-OUTPUT, OLD-REAUDIT, REJECT-* and UNKNOWN-FIELD, plus applicable
P5-ACCESS-SCHEDULE-READ/WRITE-* boundaries. No claim is made for operation 13,
actual dispatch, coalescing, cadence, notifications or deletion.

PostgreSQL (RUN_POSTGRES_TESTS not enabled), Python 3.13, production deployment,
virtual clock and scheduler remain unverified/out of scope. Duplicate-key and
strict-number behavior are intentionally stronger than default JSON coercion.
No new dependency was added beyond the requested requirements and httpx.

## Exact inherited failure/error events

This preserves subTest descriptions as returned by unittest. Counts alone are
not the baseline oracle. Final comparison found no added or removed events.

| Kind | Test/subTest ID |
|---|---|

| error | test_api.ApiTests.test_audit_endpoint_reports_unconfigured_checker |
| error | test_api.ApiTests.test_checker_hook_returns_schema_valid_sorted_findings |
| error | test_runner.RunnerTests.test_all_checkers_without_findings_return_empty |
| error | test_runner.RunnerTests.test_explicit_call_order_global_sort_and_unchanged_findings |
| error | test_runner.RunnerTests.test_phase3_runs_only_two_rules_despite_legacy_issues |
| error | test_runner.RunnerTests.test_req03_ac03_source_bytes_unchanged (issues=False) |
| error | test_runner.RunnerTests.test_req03_ac03_source_bytes_unchanged (issues=True) |
| error | test_table_headers.TableHeaderTests.test_req03_ac03_source_bytes_unchanged |
| error | test_table_headers.TableHeaderTests.test_req04_ac04_explicit_missing_header_row |
| error | test_table_headers.TableHeaderTests.test_req04_ac04_hidden_veryhidden_and_chartsheets_excluded |
| error | test_table_headers.TableHeaderTests.test_req04_ac04_multiple_tables_sheets_relationships_and_sorting |
| error | test_table_headers.TableHeaderTests.test_req04_ac04_no_table_parts_does_not_require_sheet_relationships |
| error | test_table_headers.TableHeaderTests.test_req04_ac04_nonzero_or_omitted_count_not_flagged |
| error | test_table_headers.TableHeaderTests.test_req04_ac04_unreferenced_table_part_not_examined |
| error | test_table_headers.TableHeaderTests.test_req05_ac05_finding_fields_id_and_repeatability |
| error | test_worksheet_names.WorksheetNameTests.test_exact_unicode_whitespace_boundaries (point=10) |
| error | test_worksheet_names.WorksheetNameTests.test_exact_unicode_whitespace_boundaries (point=12288) |
| error | test_worksheet_names.WorksheetNameTests.test_exact_unicode_whitespace_boundaries (point=13) |
| error | test_worksheet_names.WorksheetNameTests.test_exact_unicode_whitespace_boundaries (point=133) |
| error | test_worksheet_names.WorksheetNameTests.test_exact_unicode_whitespace_boundaries (point=160) |
| error | test_worksheet_names.WorksheetNameTests.test_exact_unicode_whitespace_boundaries (point=32) |
| error | test_worksheet_names.WorksheetNameTests.test_exact_unicode_whitespace_boundaries (point=5760) |
| error | test_worksheet_names.WorksheetNameTests.test_exact_unicode_whitespace_boundaries (point=8192) |
| error | test_worksheet_names.WorksheetNameTests.test_exact_unicode_whitespace_boundaries (point=8193) |
| error | test_worksheet_names.WorksheetNameTests.test_exact_unicode_whitespace_boundaries (point=8194) |
| error | test_worksheet_names.WorksheetNameTests.test_exact_unicode_whitespace_boundaries (point=8195) |
| error | test_worksheet_names.WorksheetNameTests.test_exact_unicode_whitespace_boundaries (point=8196) |
| error | test_worksheet_names.WorksheetNameTests.test_exact_unicode_whitespace_boundaries (point=8197) |
| error | test_worksheet_names.WorksheetNameTests.test_exact_unicode_whitespace_boundaries (point=8198) |
| error | test_worksheet_names.WorksheetNameTests.test_exact_unicode_whitespace_boundaries (point=8199) |
| error | test_worksheet_names.WorksheetNameTests.test_exact_unicode_whitespace_boundaries (point=8200) |
| error | test_worksheet_names.WorksheetNameTests.test_exact_unicode_whitespace_boundaries (point=8201) |
| error | test_worksheet_names.WorksheetNameTests.test_exact_unicode_whitespace_boundaries (point=8202) |
| error | test_worksheet_names.WorksheetNameTests.test_exact_unicode_whitespace_boundaries (point=8232) |
| error | test_worksheet_names.WorksheetNameTests.test_exact_unicode_whitespace_boundaries (point=8233) |
| error | test_worksheet_names.WorksheetNameTests.test_exact_unicode_whitespace_boundaries (point=8239) |
| error | test_worksheet_names.WorksheetNameTests.test_exact_unicode_whitespace_boundaries (point=8287) |
| error | test_worksheet_names.WorksheetNameTests.test_exact_unicode_whitespace_boundaries (point=9) |
| error | test_worksheet_names.WorksheetNameTests.test_hidden_worksheets_and_chartsheets_included |
| error | test_worksheet_names.WorksheetNameTests.test_req04_ac04_matching_and_nonmatching_names |
| error | test_worksheet_names.WorksheetNameTests.test_req05_ac05_schema_repeatability_and_source_preservation |
| failure | test_api.ApiTests.test_access_control_and_identifiers |
| failure | test_api.ApiTests.test_audit_storage_failure_rolls_back_upload |
| failure | test_api.ApiTests.test_bad_checker_output_is_a_controlled_audit_failure |
| failure | test_api.ApiTests.test_haruki_runner_is_connected_by_default |
| failure | test_api.ApiTests.test_health_auth_and_error_shape |
| failure | test_api.ApiTests.test_upload_contract_metadata_persistence_and_immutable_source |
| failure | test_pod_alignment.PodAlignmentTests.test_ambiguous_object_keeps_other_findings_with_stable_fallback_locations |
| failure | test_pod_alignment.PodAlignmentTests.test_background_picture_returns_manual_review_through_api |
| failure | test_pod_alignment.PodAlignmentTests.test_chartsheet_names_are_audited_and_version_is_semantic |
| failure | test_pod_alignment.PodAlignmentTests.test_image_formula_is_manual_review_and_does_not_fail_audit |
| failure | test_runner.RunnerTests.test_exception_from_any_checker_propagates_without_partial_result (checker='check_image_alt_text') |
| failure | test_runner.RunnerTests.test_exception_from_any_checker_propagates_without_partial_result (checker='check_worksheet_names') |
| failure | test_system_interface.SystemInterfaceTests.test_cleanup_rejects_active_audits |
| failure | test_system_interface.SystemInterfaceTests.test_namespace_and_user_ownership_are_both_required |
