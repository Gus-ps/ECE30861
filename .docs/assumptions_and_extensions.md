# Assumptions and Extensions

## AE-010 — Library migration with preserved Phase 3 behavior (2026-10-29)

- **Source/scope:** Developer authorizes openpyxl plus defusedxml migration,
  preserving the existing Phase 3 rules and public interfaces. Partial
  `1.1.1 Non-text Content`, `2.4.2 Page Titled` (related `2.4.6 Headings and
  Labels`), and inactive `1.3.1 Info and Relationships`. AE-004/005/008/009
  remain the behavioral reference. This is not adoption of Phase 4 policies.
- **Approval:** Developer approved the proposed library plan on 2026-10-29.
  No new shared rule, HTTP contract, or ruleset is approved by this migration.
- **Rule/design:** Parse original parts with defusedxml, explicitly forbidding
  DTDs, entity declarations and external XML resources. OOXML external
  relationships remain unfetched and receive the existing reviews. Reuse
  openpyxl's sheet, core-property and table models on already parsed elements;
  retain original lexical IDs, paths, names and table counts where needed.
  Model TypeError/ValueError/OverflowError triggers original-XML interpretation,
  not file rejection or a clean result. Other processing errors still propagate.
- **Rationale/limits:** defusedxml retains ElementTree and streaming APIs.
  lxml adds facilities not needed here and needs additional DTD rejection logic.
  Whole-workbook loading would parse unrelated features and reject existing
  minimal fixtures; model-level reuse avoids that dependency and double XML
  parsing. No cells need Excel value interpretation for the current rules:
  IMAGE formula/value-metadata screening needs raw cells and indexed locations.
  This is not an upload validator or a claim about all unexamined package parts.
  Performance, real Excel round-tripping and unsupported formats remain limited.
- **Phase 4 differences:** Keep ruleset 1.0.0, two active rules, cNvPr targets
  for missing/duplicate IDs, existing limitation ordering, and inactive legacy
  checks/IDs. Future six-rule coverage, object-element fallback targets, new
  table targets and limitation normalization are outside this increment.
- **Implementation/verification:** `safe_xml.py`, `excel_metadata.py`, four
  checker modules and pinned `requirements.txt` implemented. Baseline run on
  2026-10-29: 48 tests passed on Python 3.14.0. After migration, all 61 tests
  passed, including `tests/test_library_migration.py`. Existing tests unchanged.
  Complete-package outputs match snapshots captured before checker edits,
  including findings, limitations, IDs, text, ordering and inactive checks.
  Repeatability/source bytes, model rejection/coercion, foreign-title namespace
  isolation, original hidden
  chartsheet metadata, malformed XML/missing parts, and UTF-8/UTF-16 unsafe XML
  rejection are covered. A local workbook's four checker outputs and source
  bytes also match the baseline (zero active findings/limitations). Snapshots
  are compatibility evidence, not independent rule oracles. Full openpyxl
  workbook loading lost hidden chartsheet state in an initial integration test;
  raw ChildSheet reading preserved it, and the test now verifies the stored
  state directly. Excel UI, actual Excel escape serialization, Python 3.10,
  performance and HTTP integration remain unverified. Fixture provenance and
  limits: `tests/fixtures/README.md`.

Current decisions and verification are recorded separately. The developer
confirmed pod alignment for the specific imports in AE-008/AE-009 on 2026-10-18.
This does not automatically approve future Gustavo-branch changes or establish
full accessibility/HTTP conformance. This log preserves decision IDs while
omitting obsolete implementation descriptions.

## Superseded entries — AE-001/002/003/006/007

| Entry  | Original date | Decision history and current replacement                                                                                                                                                                    |
| ------ | ------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| AE-001 | 2026-10-16    | Prototype worksheet-name heuristics (`2.4.2 Page Titled`, related `2.4.6 Headings and Labels`), including numeric-only review and internal whitespace removal. Replaced by AE-008's current scope/matching. |
| AE-002 | 2026-10-16    | Prototype description-only inserted-picture check (`1.1.1 Non-text Content`). Replaced by AE-008's title/description and review policy.                                                                     |
| AE-003 | 2026-10-16    | Eight-field findings with provisional values and three-component IDs. Active Phase 3 identity is now AE-008; the old ID helper remains only for inactive checks.                                            |
| AE-006 | 2026-10-17    | Initial four-checker runner. Replaced by AE-008's two-checker runner and limitation aggregation.                                                                                                            |
| AE-007 | 2026-10-17    | Partial Phase 3 implementation temporarily stopped on unsupported objects while contract details were unavailable. Replaced by AE-008's agreed reviews and AE-009's streaming/targets.                      |

These initial proposals were developer-authorized prototypes, not evidence of
pod agreement at that time. REQ-03–06 / AC-03–06 establish source preservation,
issue detection, actionable findings, and human judgment; they do not alone
define the detailed heuristics. Current behavior is documented below and in
[the checker notes](checker_notes_en.md).

## AE-004 — Inactive workbook Title check (2026-10-17)

- **Source/rule:** Partial `2.4.2 Page Titled`; developer requests missing Title
  detection for valid readable `.xlsx`. Missing core properties or absent,
  empty, or whitespace-only Title yields one finding; no quality judgment.
- **Values/approval:** REQUIRES_USER_INPUT is developer-specified.
  WORKBOOK_TITLE rule/category and `__WORKBOOK__` worksheet/target remain
  developer-authorized provisional values, not confirmed shared contract values.
  The sentinel can collide with a real worksheet name; the legacy ID helper
  lacks workbook/ruleset identity. No new ID scheme or remediation is added.
- **Implementation/verification:** `checks/workbook_title.py` and
  `tests/test_workbook_title.py`; inactive in the Phase 3 runner. Eight synthetic
  tests pass in the current 48-test run. No new real-Excel verification.

## AE-005 — Inactive table-header check (2026-10-17)

- **Source/rule:** Partial `1.3.1 Info and Relationships`; developer-authorized
  detection of referenced tables with explicit headerRowCount="0" on visible
  worksheets. Hidden tabs/chartsheets and unreferenced table parts are excluded;
  omitted/nonzero counts are not flagged. Meaningful header content is unassessed.
- **Values/approval:** Rule `1.3.1-TABLE-NO-HEADER`, category TABLE_STRUCTURE,
  REQUIRES_USER_INPUT, and range target are developer-authorized settings;
  shared rule-catalog agreement remains unconfirmed. The legacy ID limitation
  applies. No header creation or file rewriting.
- **Implementation/verification:** `checks/table_headers.py` and
  `tests/test_table_headers.py`; inactive in the Phase 3 runner. Eight synthetic
  tests pass in the current run. Prior local smoke reading contained no tables;
  real-Excel missing-header detection remains unverified.

## AE-008 — Pod-aligned findings and chartsheets (2026-10-18)

- **Source/approval:** Developer confirms that the four-file import from Gustavo
  `bda038354c4ec1d65178edc44b0a1d1d13ca4e5b` aligns with the pod implementation
  under mutual agreement. Reference: shared suite guide Section 5 (manifest
  1.4.0, ruleset/profile 1.0.0). Partial `1.1.1 Non-text Content` and `2.4.2 Page
Titled`, related `2.4.6 Headings and Labels`. This approval is specific to the
  imported behavior, not unrelated legacy rules or future branch changes.
- **Rules:** Include worksheets/chartsheets and hidden tabs. Trim exact Unicode
  White_Space only at name ends; match case-insensitive ASCII Sheet plus positive
  ASCII digits. ALT_TEXT requires title and descr; native decorative objects
  receive MANUAL_REVIEW. Unsupported/ambiguous objects get review findings and
  limitation strings while other findings are retained. Decorative groups are
  reviewed and children independently assessed. External content is not fetched.
- **Results/identity:** `results.Findings` is list-compatible with separate
  `limitations`; runner combines disclosures and sorts findings. Consumers must
  explicitly transport attributes, which ordinary JSON/list serialization loses.
  IDs use raw-source SHA-256 and compact UTF-8 JSON of source/ruleset/rule/sheet/
  target. Read/XML/relationship failures still propagate. No overall PASS/FAIL.
- **Limits:** Rich-data/cell-image workbook reviews use `__WORKBOOK__` and
  `<part>#xml=/`; a real sheet name can collide with the sentinel. Detection is
  conservative and not exhaustive. No semantics, text generation, or rewriting.
- **Implementation/verification:** `checks/worksheet_names.py`,
  `checks/image_alt_text.py`, `results.py`, `runner.py`, and corresponding tests.
  Initially 46 tests passed; the current 48-test run includes AE-009. Synthetic
  tests confirm scopes, locations, stable findings, disclosure aggregation,
  serialization behavior, and source preservation. Real-Excel, exhaustive
  unsupported formats, and end-to-end HTTP transport remain unverified.

## AE-009 — Streaming, backgrounds, and cNvPr targets (2026-10-18)

- **Source/approval:** Gustavo `437b1859a1f00821391f7a6c9f737afe02938a2a`,
  partial `1.1.1 Non-text Content`. Initially imported by developer instruction;
  the developer subsequently confirmed this specific update as a formal decision.
  This replaces the earlier approval-pending status only for this update.
- **Rule/rationale:** `_sheet_objects()` streams worksheet/chartsheet XML,
  removing ordinary grid elements while retaining selected objects/relevant
  cells and exact XML paths. Background pictures produce MANUAL_REVIEW plus
  limitation before relationships are loaded, even without a relationship file.
  Missing/duplicate object IDs target cNvPr with one-based same-local-name
  sibling indexing, ignoring namespaces. Other fallback locations are unchanged.
- **Identity/limits:** Changing the target changes affected findingIds even for
  identical input bytes. Ruleset 1.0.0, digest recipe, and ordinary #id= targets
  remain unchanged. Drawing trees and selected objects are still retained;
  speed/peak-memory improvement is unmeasured, not a constant-memory guarantee.
- **Implementation/verification:** `checks/image_alt_text.py`, related tests,
  runner/result annotations, and current shared/private notes are aligned.
  Unsupported-case diagnostics now describe manual-review reasons without
  outdated pending-contract claims; classifications and detection stay unchanged.
  All 48 tests pass with `.venv/bin/python -m unittest discover -s tests -q`,
  including the upstream background-only and 10,000-row IMAGE-path cases and
  exact cNvPr locations. Earlier detailed tests are retained. Fixtures are
  synthetic; real-Excel escaped strings, HTTP transport, exhaustive unsupported
  formats, and performance remain unverified. Agreement is distinct from testing.
