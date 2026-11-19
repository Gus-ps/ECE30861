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

## SYS-010 — Accept due periodic audits on test clock advance (2026-11-18)

- **Source / scope:** Shared specification §§7, 9–12 and the Phase 5 cadence vectors. This extends SYS-009 with scheduled-audit acceptance. The clock response still has an empty notification list.
- **Selection and cadence:** Read enabled schedules in the request namespace and compare parsed UTC instants. After fencing, re-read eligible schedules and sort by old due instant, then workbook ID. Select the highest `p4_resources.seq` among versions, including remediation outputs. For old due time `d`, interval `I` and advance time `t`, schedule one audit and set the next due time to `d + ((t - d) // I + 1) * I`. Integer time arithmetic preserves microseconds and the original cadence after missed periods. An unrepresentable next time returns 400 `TIME_RANGE_EXCEEDED`.
- **Atomicity and replay:** The clock writes the proposed effective time first. Dispatch rechecks eligibility, rejects over 1,000 due audits or any busy selected version, and calculates the batch before inserting audits or moving deadlines. Clock, audit records, version pointers, jobs and deadlines commit together. A validation or storage error rolls the transaction back. An equal-time replay finds the accepted occurrences' deadlines already in the future. The worker drains committed jobs independently.
- **Lock order:** The clock path takes the session row lock used by cleanup, then the clock row lock. Dispatch takes the existing workbook fence in ascending workbook ID order, independent of audit acceptance order. The fence moved from the HTTP closure to `Store.fence` with the same PostgreSQL advisory lock and SQLite write serialization. Remediation publication uses the same fence so the selected version cannot change between dispatch selection and acceptance. Delete can remove the schedule before dispatch acquires the fence, or see the committed active job and return 409.
- **Acceptance and timestamps:** `phase4_jobs.begin_audit` handles upload, manual re-audit and scheduled acceptance with the installed ruleset. Scheduled jobs carry `trigger=schedule` and leave `audit_failures` available to upload or manual re-audit. Audit timestamps use effective UTC, including failure completion and remediation output audit publication. Completion is bounded below by the recorded start. Job leases and execution bounds continue on the existing real-time paths. Version `createdAt` stays on real UTC because the specification defines audit timestamps and sequence-based version ordering, leaving the version timestamp policy open.
- **Reuse:** A future real-time loop can call `phase5_schedule.dispatch_due_audits(store, db, None, instant, request_id)` within a write transaction using real UTC. The default busy policy leaves a busy occurrence due for retry on a later tick. For reminders, extend `phase5_clock.process_due_work` within the clock transaction and capture evidence needed for suppression before dispatch changes latest-audit pointers.
- **Approval status:** Developer work request only. No Pod approval.
- **Implementation / verification status:** Implemented and tested locally on SQLite, including batch rollback, cadence, history preservation, and a running worker retaining its lease across a clock jump. PostgreSQL locking and deadlock behavior, production deployment, and multiple service processes remain unverified. Real-time dispatch, reminders, notifications, scheduled-audit fault injection, and deletion reservations remain pending.

## SYS-011 — Record isolated deadline reminders and notifications (2026-11-18)

- **Thresholds and configuration:** Subtract 90, 30 and 7 UTC calendar days from the configured deadline and use midnight UTC. Thresholds before year 0001 are outside the observable timeline. Consider thresholds from the deadline's `deadline_set_at` through the effective processing time, inclusive. A deadline change refreshes this timestamp. An interval-only change or identical replacement preserves it. A null deadline stops future reminders and retains prior records.
- **Legacy migration:** The previous schema did not record when a deadline changed. Use its last saved `updated_at` as the conservative upper bound, as directed by the developer. A later schedule save can exclude an earlier otherwise eligible threshold. Starting at migration time would discard more history.
- **Durable decisions and notifications:** Store every considered `(workbook_id, deadline, offset)` key, including clean suppressions, separately from notification records. This preserves deduplication across edits, replay and restart without exposing internal decisions through operation 12. Consider in threshold, workbook ID and descending offset order. Operation 12 returns records in threshold and durable insertion sequence order after workbook authorization.
- **Processing order and transaction:** In operation 13, fence the union of reminder and audit candidates in ascending workbook ID order. Evaluate the newest version's latest audit before accepting scheduled audits. Only a successful clean audit suppresses an occurrence. All clock, notification, considered-key, audit and cadence updates share one transaction. Count suppressed occurrences toward the 3,000-occurrence limit. Rejection or database failure rolls back all changes.
- **Message and fault:** Each record states the deadline, offset and stored version and includes the external-workbook notice from §16. Delivery is recorded inside the app. The first eligible occurrence in a session armed with `notification_failures` consumes the counter and records FAILED with a safe explanation. Suppression preserves the counter. The fault leaves audits unchanged and creates no automatic retry.
- **Deletion and reuse:** Successful owner deletion removes the workbook's notification records and considered keys, completing the notification portion of Jon's D4. A pre-delete fault preserves both. Session cleanup removes both tables' rows for the target namespace. A future real-time loop can call `dispatch_due_reminders` with real UTC and `namespace=None` inside a write transaction. When combining reminders with audit dispatch, acquire the union of candidates once and pass the shared locked schedules to both functions, evaluating reminders first.
- **Approval status:** Developer work request only. No Pod approval.
- **Implementation / verification status:** Operation 12, clock-driven reminders, isolated notification failures and deletion cleanup are implemented and verified locally on SQLite. PostgreSQL, production deployment and multiple service processes remain unverified. Real-time dispatch, UI changes and deletion reservations remain pending.

## SYS-012 — Dispatch ordinary schedules in real time and isolate scheduled audit faults (2026-11-18)

- **Runtime and cadence:** Start one scheduler thread per service process in the FastAPI lifespan. It polls immediately and uses monotonic waits at the configured `SCHEDULER_INTERVAL_SECONDS` interval, default 1 second with allowed values in (0, 5]. Each tick takes its processing instant from real UTC and selects only `namespace IS NULL`. Tests can disable the thread with `create_app(enable_scheduler=False)`. Shutdown stops and joins the scheduler before stopping the existing worker.
- **Transaction and limits:** Share the candidate selection, lock order and reminder-first dispatch with operation 13. Ordinary ticks process their due candidates in one write transaction without the clock's work limits or extra batching. Busy versions retain their deadlines for a later tick. On restart, persisted deadlines determine the next tick's work and the existing cadence calculation coalesces missed intervals. The in-process thread reuses the service's storage and lifecycle and avoids a separate scheduler deployment.
- **Multiple instances and D7:** Acquire existing workbook fences in ID order and re-read candidate schedules under the fence. SQLite uses `BEGIN IMMEDIATE`. PostgreSQL uses the existing transactional advisory lock. Cadence updates and unique considered keys commit with the new jobs and notifications. The same fence serializes deletion against both dispatch paths. After a successful delete, dispatch finds no schedule to process. An already accepted pending or running audit causes deletion to return 409 `ACTIVE_OPERATION`. This closes D7 for future audits and reminders.
- **Monitoring:** The `phase5_scheduler` logger emits work-bearing ticks at INFO and empty ticks at DEBUG. Each includes a scheduler request ID, committed audit and notification counts and dispatch lag in seconds, measured from the oldest recorded occurrence to the tick's UTC timestamp. Failed ticks report the exception type and zero committed counts, and the loop continues. Logs exclude exception text, workbook contents and tokens. The accepted jobs carry the same scheduler request ID for correlation.
- **Scheduled audit fault:** The first accepted scheduled audit in an armed test session consumes `p5_faults(kind='scheduled_audit')` in the acceptance transaction and records the result in the job payload. The worker verifies source bytes and fails before running rules, using `TEST_SCHEDULED_AUDIT_FAILURE` and `stage=scheduled_audit`. The failure report has empty findings and checks performed. Source bytes and prior audits are preserved. The committed cadence remains advanced and later manual or scheduled audits run normally.
- **Approval status:** Developer work request only. No Pod approval.
- **Implementation / verification status:** Implemented and tested locally, including startup tick within five seconds, busy deferral, two concurrent stores sharing one SQLite database, restart coalescing, deletion, and one-shot fault rollback. PostgreSQL, actual multiple service processes, production deployment and release drain behavior remain unverified.

## SYS-013 — Version new audit reports and complete isolated fault controls (2026-11-18)

- **Report compatibility:** Operation R serves the snapshot saved when an audit reaches a terminal state. Label new snapshots `specificationVersion=3.0.0` and accept both specification versions in the read contract. Keep `reportVersion=2.0.0`, the report shape and the stored Phase 4 snapshots. Putting the version at write time keeps the saved record authoritative and avoids regenerating it on download.
- **Remediation:** Claim the one-shot counter in the acceptance transaction after decision validation and idempotency checks. The worker verifies the source and records `TEST_REMEDIATION_FAILURE` before editing or publishing, including for decision-only requests. A replay with the original key returns the saved acceptance. A fresh attempt uses a new key.
- **Report finalization:** Claim the counter when accepting an upload or manual audit, including an upload of a new version. Scheduled audits and remediation output audits do not consume it. After the engine completes, save a `PROCESSING_FAILED` audit and `TEST_REPORT_FAILURE` snapshot with all six checks listed and empty findings. If snapshot persistence fails, roll back that attempt and record the genuine `STORAGE_FAILED` against the audit and job when storage permits. Its report endpoint returns HTTP 500 while the snapshot is unavailable. A failure to persist even the terminal state is logged.
- **Upload storage:** Validate the upload and recheck its namespace and workbook access before claiming the counter. Commit the claim without creating a workbook, version, audit or job. Release any new-version staging reservation in the same transaction and return `TEST_STORAGE_FAILURE` after commit. Use `{"stage":"storage","testOnly":true}` for the synchronous details, following the deletion fault convention.
- **Setup:** Reject `audit_failures` combined with `report_failures` before preparing or cleaning any session. Preserve the existing audit fault and its pre-rule failure snapshot. The other fault combinations remain valid.
- **Approval status:** Developer work request only. No Pod approval.
- **Implementation / verification status:** Implemented and verified locally on SQLite. The new report was checked against the shared `NewAuditReport` schema. A test forces an actual SQLite report INSERT rejection and verifies the terminal fallback. PostgreSQL, hosted deployment and a real storage outage remain unverified.

## SYS-014 — Record the Phase 5 implementation handoff and developer choices (2026-11-18)

- **Handoff:** This branch takes over the Phase 5 work left open on `Jon-Gus_branch`. Work remaining at the end of the handoff returns to Jon. Use `PHASE5_TASKS.md` and `PHASE5_DECISIONS.md` as the handoff record.
- **Completed:** D4 selected option 1 and is implemented under SYS-008 and SYS-011. D7 selected option 1 and is implemented under SYS-012. DEL-7 is checked based on its scheduler cancellation test.
- **Selected for later implementation:** On 2026-11-18, the developer selected D1 option 1, D2 option 2, D3 option 1, D5 option 1, D6 option 1, D8 option 2, D9 option 1 and D10 option 1. Implementation remains pending on `haruki/phase5-schedule`, and their task checkboxes still reflect that status.
- **Approval status:** Developer selection only. No Pod approval.
- **Implementation / verification status:** Decision records updated. This entry records choices for subsequent work.

## SYS-015 — Reserve and resume workbook deletion (2026-11-18)

- **Design:** Apply D5 option 1. Create a content-free `p5_deletions` row after namespace and workbook fencing, owner authorization, active-work checks and the pre-delete fault check. Delete each table in its own transaction and remove the reservation last. Delete jobs before version records so resumed steps can still resolve job ownership. This leaves a durable recovery point after a partial failure and keeps each step repeatable.
- **Access and concurrency:** Ordinary lookups exclude reserved workbooks in the same query as the resource lookup. Authorized owner retries can resume the reservation and share the workbook fence on each step. Concurrent admitted requests can both finish the same cleanup. A new request after the reservation and workbook are gone returns 404. The scheduler filters reservations before candidate selection and after taking the fence.
- **Clock and cleanup:** Only operation 13 uses 409 `DELETION_IN_PROGRESS`. It checks for any reservation after locking and authorizing the namespace and before changing time. Test-session cleanup may finish an overlapping deletion. It removes namespace resources, upload reservations and pending deletion rows in one transaction and preserves any ledger entry.
- **Deadline and recovery:** The DELETE route budgets 30 seconds across authorization and deletion with a monotonic deadline, asynchronous request timeout and database time limits. A timed-out request returns `DELETION_FAILED`. Startup resumes reserved steps before starting workers and the scheduler. File and database commit latency under production conditions remains unverified.
- **Approval status:** Developer selection only. No Pod approval.
- **Implementation / verification status:** Implemented and tested locally for partial failure, owner retry, startup recovery, shortened deadline, concurrent retries, clock isolation, scheduler exclusion and cleanup overlap. PostgreSQL and the production deadline remain unverified.

## SYS-016 — Replay deletion intents outside restored databases (2026-11-18)

- **Design and durability:** Apply the application part of D6 option 1. With `DELETION_LEDGER_PATH` configured, append one JSON Lines entry per workbook after committing the reservation and before deleting any content. The only fields are opaque `workbook_id` and UTC `timestamp`. Serialize ledger access through the shared database and fsync the file and, on POSIX, its containing directory before proceeding. An append or sync failure returns 500 and leaves the reservation for recovery.
- **Startup:** Create a missing ledger file in the configured directory. Warn and discard an unterminated final line. Refuse startup on other file or record errors and log the error type and line number without record content. Re-reserve and delete ledger IDs found in the restored database before the service begins accepting work. If the environment variable is unset, warn and start. Restores can reintroduce deletions in that configuration.
- **SQLite and EC2:** Every SQLite connection enables `secure_delete`. The EC2 scripts create and mount a private host ledger directory outside the SQLite backup scope. After a successful update the release script prunes older pre-deploy SQLite files, retaining the newest. Retained copies can contain earlier raw content and require the current ledger for safe restoration.
- **ECS/RDS handoff:** Jon owns selection of an external ECS ledger and the RDS retention and snapshot policy. Existing RDS automated backups can hold deleted content for about a day. Final snapshots may persist. The infrastructure template is unchanged.
- **Approval status:** Developer selection only. No Pod approval.
- **Implementation / verification status:** Verified with a local SQLite backup and restore, append and fsync failure tests and startup file validation. EC2 script changes received syntax checks. Production restore, deployment and infrastructure retention remain unverified.

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
