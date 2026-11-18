# Phase 5 local and manual plan entries: owners and evidence

The Phase 5 test plan (`ref/Phase5_Agent_Context_Pack/phase5-test-plan.json`) has 435 entries:
357 hosted (run by the tester, `tester/fixtures/manifest_phase5.json`), 57 `local_integration`
and 21 `manual_release`. This file maps each of the 78 non-hosted entries to an owner and to the
evidence that satisfies it: a test in this repository, or an open task.

Owners:

- **Tester:** Team 12's tester (this repository).
- **System:** each team's system implementation. For Team 12's system that is the deployment branch
  (`origin/Gustavo`), not this tester branch.
- **People:** human review, Excel or deployment work that no automated test replaces.

Status as of 2026-11-17. **Covered** means a named test exercises the assertion. **Open** means
nothing has produced the evidence yet.

## Tester-owned entries (19)

| Entry | Assertion (short) | Evidence | Status |
| --- | --- | --- | --- |
| P5-TESTER-TRUSTED-IDENTITY | Own/cross from exact approved target metadata; no caller override | `tests/test_phase5_suite.py::test_classification_comes_only_from_exact_configured_targets`; setup accepts exactly `{target_url}`: `tests/test_lifecycle.py::test_setup_rejects_invalid_requests` | Covered |
| P5-TESTER-MISSING-MAP | Own-team setup without a valid map fails 500/tester before ready | `test_phase5_suite.py::test_an_own_team_setup_without_a_valid_map_fails_500_tester`, `::test_a_phase5_suite_without_a_tester_team_cannot_be_set_up` | Covered |
| P5-TESTER-UNTESTED-DESIGN | Untested requirements stay in the total and earn nothing | `test_phase5_suite.py::test_abort_and_recovery_reports_keep_the_profile_model_rule` (0 of 38 when nothing ran), `::test_an_own_team_report_counts_each_design_requirement_once_from_executed_tests` | Covered |
| P5-TESTER-NO-DOUBLE-COUNT | Several qualifying tests count a requirement once | `test_phase5_suite.py::test_an_own_team_report_counts_each_design_requirement_once_from_executed_tests`, `::test_the_stored_own_team_report_and_record_keep_the_frozen_map` | Covered |
| P5-TESTER-NO-SETUP-CREDIT | Preparation, skips and unexecuted checks earn no coverage | `test_phase5_suite.py::test_inherited_and_built_cases_pass_and_pending_ones_skip_against_a_conforming_target` (coverage equals the declarations of executed cases only); `tests/test_runner.py::test_error_never_provides_a_resource` | Covered |
| P5-TESTER-UNAVAILABLE | An unavailable measure is paired nulls, never 0 | `tests/test_lifecycle.py::test_code_coverage_unavailable_is_paired_nulls` | Covered |
| P5-TESTER-ERROR-SOURCE | Internal target failure is error/system, no response is error/communication, an expected fault passes | `test_lifecycle.py::test_check_failures_are_classified`; `tests/test_checks.py::test_a_failed_boundary_audit_is_reported_by_the_profile_rule_without_a_retry`; the fault cases pass against the stand-in (`test_phase5_suite.py`) | Covered |
| P5-TESTER-EVALUABLE-FAIL | Wrong results are fail; a wrongly accepted rejection keeps its failure and only its own job is drained | `test_checks.py::test_a_wrongly_accepted_rejection_keeps_its_failure_and_its_job_is_drained`, `::test_drain_follows_reaudits_and_remediations_and_ignores_rejections_and_transport_errors`; the 14 broken-target cases in `test_phase5_suite.py::test_a_target_breaking_one_rule_fails_exactly_that_case` | Covered |
| P5-TESTER-ABORT | Abort keeps outcomes, one interrupted error, skips; run returns 500/tester | `test_lifecycle.py::test_deadline_abort_returns_500_and_stores_available_results`, `::test_restart_recovers_interrupted_sessions` | Covered |
| P5-TESTER-ONE-RUN | Concurrent, repeated and post-abort runs are 409; an invalid request does not consume the session | `test_lifecycle.py::test_concurrent_run_and_lost_response_recovery`, `::test_invalid_run_request_does_not_consume_session` | Covered |
| P5-TESTER-SETUP-FORWARD | System setup errors forwarded unchanged; no suite begins | `test_lifecycle.py::test_setup_forwards_system_error_and_session_is_not_runnable` | Covered |
| P5-TESTER-EVERY-ID | Every planned ID once, in frozen order | `test_phase5_suite.py::test_manifest_is_generated_from_the_plan` (357 hosted IDs in plan order), `::test_inherited_and_built_cases_pass_and_pending_ones_skip_against_a_conforming_target` (357 results) | Covered |
| P5-LOCAL-SCHEMA-PROFILES | Own reports need `model` and cross reports must not have it, for the normal, abort and recovery builders | `test_phase5_suite.py::test_abort_and_recovery_reports_keep_the_profile_model_rule`, `::test_a_cross_team_report_omits_the_model_key_entirely`, `::test_earlier_profiles_never_report_model_coverage` | Covered |
| P5-LOCAL-MANIFEST-GENERATION | Manifest covers 18 ACs, 12 components and strict own design mappings | `test_phase5_suite.py::test_manifest_is_generated_from_the_plan`, `::test_the_draft_design_map_lists_every_requirement_and_only_real_hosted_cases`, `::test_the_phase5_profile_pairs_only_with_a_phase5_manifest` | Covered (the design map is still a draft; see the adoption record) |
| P4-LOCAL-FIXTURE-SNAPSHOT | A changed fixture hash prevents setup; a session uses its frozen plan | `tests/test_fixtures_and_record.py::test_pack_is_verified_and_frozen`, `::test_changed_fixture_is_rejected_at_setup_before_any_session`, `::test_fixture_changed_after_setup_is_a_tester_error` | Covered |
| P4-LOCAL-TESTER-ABORT | Abort stores results, one interrupted error, skips and a retrievable report | `test_lifecycle.py::test_deadline_abort_returns_500_and_stores_available_results`; `test_fixtures_and_record.py::test_restart_abort_gets_a_record` | Covered |
| P4-LOCAL-TESTER-LOST-RESPONSE | A lost run response is recovered by report GET | `test_lifecycle.py::test_concurrent_run_and_lost_response_recovery` | Covered |
| P4-LOCAL-PALETTE-VECTORS | Independent palette, tint and contrast vectors (tester side) | `tests/test_phase4_fixtures.py::test_tint_matches_the_policy_vectors_and_the_theme_rows`, `::test_contrast_matches_the_policy_vectors`, `::test_contrast_vectors_large_text_and_palette` | Tester side covered; each system must show its own |
| P4-LOCAL-RESTART | Restart without losing reports or measurements (tester side) | `test_lifecycle.py::test_restart_recovers_interrupted_sessions` | Tester side covered; system side open |

## System-owned entries (37)

These are assertions about a system implementation. The tester cannot observe them over HTTP, so
each system team runs its own local integration tests. Where a hosted case covers the observable
part, it is named.

| Entry | Hosted part already run by the tester | Status |
| --- | --- | --- |
| P5-CLOCK-WORK-LIMIT | none (needs over 1,000 due audits) | Open (system) |
| P5-CLOCK-STORAGE-ROLLBACK | none | Open (system) |
| P5-CLOCK-LOST-ACK | P5-CLOCK-SAME and P5-SCHEDULE-SAME-TIME (a replayed timestamp adds nothing) | Open (system: real lost acknowledgment) |
| P5-CLOCK-REAL-TIME | none | Open (system) |
| P5-DELETE-ACTIVE-UPLOAD | none (a staging reservation is not observable) | Open (system) |
| P5-DELETE-RECOVER | P5-DELETE-FAIL-ONCE (injected pre-delete failure only) | Open (system) |
| P5-DELETE-RACE | none | Open (system) |
| P5-DELETE-RESTORE | none | Open (system) |
| P5-DELETE-OBJECT-VERSIONS | P5-DELETE-OLD-URLS (API-visible removal only) | Open (system) |
| P5-TESTER-DIRECT-STAFF | none (staff call the system directly) | Open (system) |
| P5-TESTER-REPORT-READONLY | none | Open (system) |
| P5-LOCAL-SCHEDULER-RESTART | none | Open (system) |
| P5-LOCAL-SCHEDULER-TICK | none (test namespaces schedule only through the clock) | Open (system) |
| P5-LOCAL-NOTIFICATION-RESTART | none | Open (system) |
| P5-LOCAL-CLOCK-RESTART | none | Open (system) |
| P5-LOCAL-DELETE-RESTART | none | Open (system) |
| P5-LOCAL-GENUINE-FAULTS | the seven injected fault cases | Open (system: real failures) |
| P5-LOCAL-MIGRATION | none | Open (system) |
| P4-LOCAL-FAULT-DISABLED | P5-FAULT-REJECT-DISABLED (skips on a deployment with faults enabled; local evidence, agreed with Team 9 on 2026-11-17) | Open (system: a deployment with the switch off) |
| P4-LOCAL-CONCURRENT-AUDIT | none | Open (system) |
| P4-LOCAL-CONCURRENT-KEY | inherited idempotency cases (sequential replays only) | Open (system) |
| P4-LOCAL-WORKER-TIMEOUT | none | Open (system) |
| P4-LOCAL-WORKER-LOSS | none | Open (system) |
| P4-LOCAL-PRESERVATION-FAILURE | none | Open (system) |
| P4-LOCAL-OUTPUT-AUDIT-FAILURE | none | Open (system) |
| P4-LOCAL-STORAGE-FAILURE | P5-FAULT-STORAGE (injected only) | Open (system) |
| P4-LOCAL-SOURCE-CORRUPTION | none | Open (system) |
| P4-LOCAL-OUTPUT-BOUND | none | Open (system) |
| P4-LOCAL-NOT-READY | inherited not-ready cases where producible; also stands in for hosted P5-CLOCK-NOT-READY, which no request can produce (agreed with Team 9 on 2026-11-17) | Open (system) |
| P4-LOCAL-STATE-TRANSITIONS | inherited audit and remediation cases | Open (system) |
| P4-LOCAL-MIGRATION | none | Open (system) |
| P4-LOCAL-CLEANUP-ACTIVE | inherited cleanup cases | Open (system) |
| P4-LOCAL-REVIEWER-NO-GRANT | P5-ACCESS-*-UNGRANTED-REVIEWER (once a `reviewer-ungranted` token is configured) | Open (system) |
| P4-LOCAL-XML-ESCAPING | inherited remediation cases with Unicode values | Open (system) |
| P4-LOCAL-NAMING-COLLISIONS | inherited header-table cases | Open (system) |
| P4-LOCAL-SCHEMA-NEGATIVES | every hosted response is validated against strict schemas | Open (system: request-side negatives) |
| P4-LOCAL-LOGGING | none | Open (system) |

## People-owned entries (22)

One `local_integration` entry (P5-LOCAL-RELEASE-DRAIN, deployment work) and all 21
`manual_release` entries.

| Entry | What is needed | Team 12 status |
| --- | --- | --- |
| P5-LOCAL-RELEASE-DRAIN | Deployment protection covers a 2,400 s run plus overhead; expiry never deletes evidence | Open: proxy timeouts are raised to 2,460 s (`deploy/`); the protection lease on the system host still needs review by the deployer |
| P5-MANUAL-EXCEL | Excel no-repair outcomes for each correction family, with hashes, reviewer and platform | Open: correction outputs not opened yet; fixture opens recorded in the Phase 4 pack's `excel_open` |
| P5-MANUAL-FIXTURE-REVIEW | Two members of the other team review each answer-key pack | Open: Phase 4 pack sent to Team 9 (`dist/team12-phase4-pack-review.zip`); `performance_250000_cells` not yet sent |
| P5-MANUAL-REAL-PRECISION | Five real de-identified workbooks, at least 90% precision | Open (system team) |
| P5-MANUAL-KEYBOARD | All primary flows by keyboard | Open (system UI) |
| P5-MANUAL-A11Y-SCAN | Scanner and contrast results for every screen | Open (system UI) |
| P5-MANUAL-EXTERNAL-DISCLOSURE | Stored version and external-change limitation on screens | Open (system UI) |
| P5-MANUAL-HTTPS-CREDENTIALS | HTTP refused or redirected; credentials protected | Tester side: production refuses non-HTTPS targets (`tester/config.py`), operator tokens are stored only as SHA256 and target tokens only in private settings. Open: the HTTP-to-HTTPS check on the deployed host |
| P5-MANUAL-DELETE-BACKUPS | Object-version and backup deletion and restore policy with environment evidence | Open (system) |
| P5-MANUAL-MONITORING | Queue, failure, scheduled-lag and notification signals | Open (system) |
| P5-MANUAL-BOTH-DIRECTIONS | Own-team reports with `model`, reciprocal reports without, with hashes, counts and triage | Open: needs real runs; the run record (`scripts/run_record.py`) keeps the evidence |
| P5-MANUAL-REGISTRY | Both registry rows use the same pod spec and actual time and access bounds | Open: registry note text is in `deploy/README.md` section 5 |
| P4-MANUAL-EXCEL-ALT, -RENAME, -LINK, -HEADER | Open each correction output in Excel | Open |
| P4-MANUAL-REAL-WORKBOOKS, -REAL-DETERMINISM | Real workbooks, precision and five-run determinism | Open (system team) |
| P4-MANUAL-UI-REVIEW, -PROSE-REVIEW | UI and finding-text reviews | Open (system team) |
| P4-MANUAL-POD-FIXTURE-REVIEW | Two members of the other team review each pack | Open: same as P5-MANUAL-FIXTURE-REVIEW |
| P4-MANUAL-RECIPROCAL-RUNS | Both tester-to-other-system directions retained | Open: needs real runs |

Count check: 19 tester + 37 system + 1 people-owned local entries = 57 local, plus 21 manual =
78, each listed once (the four P4-MANUAL-EXCEL entries, the two real-workbook entries and the two
review entries share rows above). `tests/test_phase5_suite.py::test_the_local_and_manual_map_lists_every_entry_once_and_names_real_tests`
checks this against the plan, and checks that every test named here exists.
