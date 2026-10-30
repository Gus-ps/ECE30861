# Assumptions and Extensions

Color foundation verified against corrected pack 2.1.1: exact Fraction HSL intermediates, final half-up channels, all supplied tint/contrast vectors, exact-half neighbors and frozen 64-color palette equality. Palette is packaged as code, independent of runtime .docs. Eleven helper tests and full 144-test regression pass. Unsupported rendering remains explicit; COLOR_CONTRAST is not yet registered. No Excel UI evidence or shared deployment claim.

Current adoption: corrected pack revision 2.1.1 resolves AE-020; implementation resumes using CORRECTIONS.md. Specification remains 2.1.0, ruleset 2.0.0, suite target 2.1.1 (no executable tester created). All seven SHA256SUMS members verified. Earlier pending statements below are historical; neither team deployment nor complete implementation is established. See [corrected pack](phase4_agent_context_pack/README.md).

## AE-020 — Tint rounding conflict; pod decision pending (2026-10-30)

- **Source/scope:** Specification 2.1.0 §7.7, partial 1.4.1 Use of Color and
  1.4.3 Contrast (Minimum), versus the developer-supplied policy vectors.
- **Current evidence:** The previously absent 64-color palette has been supplied;
  missing data is no longer the blocker. Comparison found two tint conflicts for
  base 336699. At −0.5 the vector says 19334D, but exact channels
  (25.5,51,76.5) with half-up give 1A334D. At +0.5 the vector says 8CB2D9,
  but exact channels (140.25,178.5,216.75) give 8CB3D9. Fraction arithmetic
  independently confirmed these pre-round values. Palette/whitespace/identity/
  label comparisons matched; contrast comparisons agreed within floating precision.
- **Proposal/authority:** Correct the two vector values to the half-up results,
  or explicitly revise the rounding policy. Neither alternative is approved.
  The pod's response is pending; developer implementation authorization alone
  does not establish shared adoption. No normative file/vector is changed here.
- **Implementation:** Stage 5 color helper, its tests and reader additions remain
  uncommitted/incomplete. COLOR_CONTRAST is not registered; stages 6–7 are not
  complete. No further color implementation is part of this increment.
- **Verification:** Committed baseline 131, additional five-rule integration 2,
  proposed snapshot 133; working tree with nine draft color tests 142 passing.
  These regression results do not resolve the two normative vector mismatches.
  New fixtures are generated complete XLSX packages with independent tuple/ID
  expectations; no Microsoft Excel manual no-repair evidence exists.
- **History:** Initial stage-5 investigation stopped for missing companion data.
  The developer subsequently supplied it; the blocker changed to the concrete
  rounding conflict above. Earlier absence statements are historical, not the
  current reason for waiting. See `tests/fixtures/five_rule_fixtures.md`.


## Historical records (superseded status statements below)

### Earlier AE-020 draft — historical missing-palette investigation (2026-10-30)

**Revised after developer supplied the companion file:** missing-data blocker resolved; normative conflict remains. The 64 fallback entries match installed `openpyxl.styles.colors.COLOR_INDEX` (the earlier question used the incorrect constant name COLOR_INDEXED). Whitespace, ID and label vectors match. Tint vectors for 336699 disagree with §7.7 half-up: -0.5 requires 1A334D (file 19334D), +0.5 requires 8CB3D9 (file 8CB2D9). Exact Fraction arithmetic independently yields pre-round channels (25.5,51,76.5) and (140.25,178.5,216.75). Contrast vectors agree within floating-point precision. Do not silently privilege either normative source or alter the supplied user file. Await a decision to correct the two vectors to half-up, or explicitly revise the rounding policy. All 140 existing tests pass; the direct new-vector comparison has two mismatches, not a successful complete policy test. Stage 5 remains uncommitted/incomplete; stages 6/7 remain pending. Earlier absence statements below are historical.


- Source: specification 2.1.0 §7.7, partial 1.4.1 Use of Color and 1.4.3 Contrast (Minimum). The text normatively selects indices 0–63 from `phase4-policy-vectors.json`, but the companion file is absent from this repository (including hidden/ignored-file search). Workstation theme or another implementation's palette cannot establish that frozen choice.
- Developer authorized implementing the checks, not silently replacing missing normative data. A question is pending: supply the frozen vectors, or explicitly adopt the installed openpyxl 3.1.5 COLOR_INDEXED values for this implementation. Such local authorization would remain distinct from cross-team adoption. No substitute has been adopted.
- Independent draft helper code resolves explicit workbook colors/theme/palette and the specified tint/luminance math, retains rich-run and custom-row provenance, and refuses unsupported rendering. Missing fallback indexed colors raise UnsupportedRendering; they are not reported as passing. This is a temporary unresolved profile, not completed color detection.
- Nine helper tests and full working-tree 140-test regression pass; no frozen-vector equality is claimed. Existing dependencies pass pip check, whitespace checks pass. No dependency added. Stage 5 draft code/docs remain uncommitted; COLOR_CONTRAST is unregistered. Stages 6/7, full six-rule fixtures and Microsoft Excel no-repair verification are outstanding.

## AE-019 — Finite hyperlink label screening (2026-10-30)

Section 11 follow-up: signed-package link-label defects are manual; descriptive links get no signature-only defect. Ten LINK_TEXT tests pass; full working tree: 140 passing, including nine incomplete color-helper tests.

Review follow-up: namespace checks now explicitly reject foreign/wrapped link representations as manual at their actual indexed locations. Nine link tests pass; full working-tree regression is 139, including nine tests for the separately uncommitted, incomplete color helper. This does not complete stage 5.

- Source: specification §§6, 7.1, 7.6, 8.5; partial 2.4.4 Link Purpose (In Context). Developer-authorized implementation; whole-spec team adoption and editor availability remain separate.
- Element labels use resolved cell content, not display attributes. Comparisons trim/collapse only policy White_Space, casefold, ignore one trailing ASCII .!? for the finite word list, and check raw-address prefixes. Literal one/two argument HYPERLINK calls parse commas outside strings and doubled quotes; unsupported calls are manual without evaluation. Plain URLs outside hyperlinks are ignored.
- Editable classification is limited to simple single-cell text/empty labels with unambiguous ownership. Unsupported/range/competing/merged/rich/formula representations are manual; indexed locations are based on actual XML. Drawing hyperlinks are disclosed as unperformed manual review, without fetching destinations.
- Eight focused tests, full 129-test regression pass; original bytes and historical snapshots are preserved. Runner now has five active checks. No color rule, editor, API or new dependency. Generated xlsx reader checks are not Microsoft Excel no-repair evidence.

## AE-018 — Unstructured table candidates (2026-10-30)

- Source: specification §§6, 7.4, 8.6; partial 1.3.1 Info and Relationships. Developer authorizes this increment; shared adoption is separate.
- Four-neighbor components exclude formal-table cells. Bounding boxes of at least 2×2 are candidates; density uses count versus area, never empty rectangle expansion. Only dense, plain-label, unambiguous supported candidates request first-row confirmation. Merges, overlapping filters/formal tables, shared worksheet ownership and unsupported attached features prevent that classification. Small components produce one audit-level limitation. No semantic header inference or table creation.
- TABLE_HEADER is now registered after names and before merges. Historical two-rule tests explicitly isolate their old execution profile rather than relabeling snapshots as four-rule results.
- Eleven table tests and 121 regression tests pass, including sparse/diagonal/far-away cells, body formula/0/false, exclusions and unsafe boundaries. No Excel UI/manual verification or editing is claimed.

## AE-017 — Formal-table header classification (2026-10-30)

- Source: specification §§6, 7.4, 8.3, 8.6; partial 1.3.1 Info and Relationships. Developer-authorized implementation, not whole-spec shared adoption.
- All referenced formal tables are checked; omitted header count is 1. Invalid IDs use table-root paths; duplicate physical IDs affect all members. Shared ownership prevents user-input classification. Only disabled headers with matching distinct plain first-row strings, body, consistent metadata and no known unsafe features are candidates. Formula/header/query/extension/merge/overlap/totals/reference ambiguities are manual with limitations. No edits.
- Existing historical provisional implementation moved intact to `checks/legacy_table_headers.py`; its tests and saved observations use that explicit historical import. No snapshot bytes changed. Common reader now retains shared/inline rich-text provenance.
- Seven focused tests and 117 regression tests pass. No new dependencies; no Excel UI evidence. Unstructured screening and runner registration are deferred to stage 3; TABLE_HEADER as a whole is not complete at this increment.

## AE-016 — Populated merges (2026-10-30)

- Source: specification 2.1.0 §§6, 7.5, partial 1.3.1 Info and Relationships.
- Developer explicitly authorizes the four new checks; shared adoption is separate.
- Identical canonical declarations are one target. Overlapping declarations each receive manual review and a limitation even if empty; ordinary non-conflicting empty/style-only and single-cell declarations produce no finding. No rectangle expansion or editing. External worksheets are disclosed without fetching.
- Implemented in `checks/merged_cells.py`, using the existing reader and a streaming worksheet-feature reader. `tests/test_merged_cells.py`: 4 tests; full regression: 110 passing. Original fixtures/snapshots preserved. Existing runner mock tests isolate merge execution explicitly; their synthetic root relationship now includes the required officeDocument relationship.
- Excel UI, minimum-Python execution and performance benchmarks remain unverified. No dependencies added.

Readiness stage 4 verification (2026-10-29): all 106 tests pass, including
24 ALT_TEXT, 14 rename-preflight and 2 new generated/complete-package integration
tests. No new production behavior was added in stage 4. Historical XLSX/JSON
snapshots and dependencies match task-starting commit 52274c8. See
`checker_readiness.md` for exact scope, commands and per-stage evidence.
This verifies AE-013–AE-015 without declaring an editor, six-rule completion,
whole-spec team adoption or unperformed Microsoft Excel UI validation.

## AE-015 — Whole-workbook rename classification (2026-10-29)

- **Source/approval:** Developer authorizes readiness stage 3 under 7.3/8.4/11.
  Partial `2.4.2 Page Titled`, related `2.4.6 Headings and Labels`; not whole-spec
  adoption, an editor or a new name-detection heuristic.
- **Rule:** Preserve matching, original names, targets and IDs. Classify matched
  names from the whole-workbook inventory: supported profiles yield
  REQUIRES_USER_INPUT; blockers yield MANUAL_REVIEW with deterministic limitations.
  List-compatible Findings now carries those limitations without new fields or
  arguments. Shared worksheet/drawing/table ownership is a blocker.
- **Implementation/rationale:** `rename_safety.py` uses installed Tokenizer plus
  a checked token grammar and quote-aware sheet/address/scoped-name parsing.
  Cell formulas, names, charts, validation, conditional formatting, table formulas
  and internal links are recognized. Strings remain literals. 3D/external/dynamic
  references, unsupported extensions, shared/array formulas, signed/opaque/
  pivot/cache/query/slicer structures and unknown markup are disclosed blockers.
  `part_ownership.py` now also reads actual table ownership.
- **Limits:** Tokenization is not proof of rewriting. Structured-reference
  operands, intersections, unknown functions/attribute profiles remain manual.
  Builtin catalog names plus IMAGE are recognized; INDIRECT/EVALUATE/HYPERLINK
  are not safe. `rename_safety_profile.md` records the self-contained contract.
  No rewrite, output, review context or preservation guarantee is implemented.
- **Verification:** Stage 2 baseline 90 tests. Name suite 4 pass, preflight suite
  14 pass, full suite 104 pass on Python 3.14.0/.venv. Coverage includes mandatory
  ordinary families, quotes/apostrophes/literals, manual families, other/hidden/
  chart sheets, target/ID stability and source preservation. Minimal name fixtures
  gained actual empty sheet parts; matching assertions and historical snapshots
  are unchanged. Excel UI, Python 3.10, performance and rewriting are unverified.

## AE-014 — Drawing ownership gates user-input findings (2026-10-29)

- **Source/approval:** Developer authorizes readiness stage 2 under 7.2/8.3,
  partial `1.1.1 Non-text Content`. No cross-team adoption or editor is implied.
- **Rule:** Missing alt fields on a drawing part actually referenced by multiple
  sheet definitions yield MANUAL_REVIEW with an ownership limitation, retaining
  target/ID. Complete alt fields do not acquire a new defect solely because of
  sharing. Repeated references from one owner and unreferenced relationships do
  not invent additional owners. Different sheets sharing the same worksheet
  part are distinct owners, including hidden/veryHidden/chart tabs.
- **Implementation/rationale:** `part_ownership.py` exposes sheet owners and a
  drawing-part-to-owner map, resolving actual internal relationships and scanning
  sheet drawing references without retaining grids. The preflight scans each
  distinct sheet part once; existing ALT_TEXT reading remains independent.
  External parts are never fetched. This is read-only evidence for future
  processing, not review context or an editing engine. Existing unsupported
  representations, group traversal, title/description conditions and unique/ID
  fallback locations remain intact.
- **Verification:** ALT_TEXT suite: 24 pass; full suite: 90 pass, following stage
  1's 87-test baseline. Added cases cover actual shared ownership versus repeat/
  unused references, shared sheet parts, hidden/chart tabs, field combinations,
  no invented complete-object defect, deterministic results and source bytes.
  Tests remain synthetic; Excel UI and performance are unverified.

## AE-013 — Group ambiguity must not hide safe children (2026-10-29)

- **Source/approval:** Developer authorizes readiness stage 1 under specification
  7.1/7.2, partial `1.1.1 Non-text Content`; not whole-spec team adoption.
- **Rule:** Missing/ambiguous group nonvisual properties or decorative metadata
  yield the existing parent review/limitation while directly enumerated children
  are independently inspected. Native single 0/false is not decorative; 1/true
  suppresses missing-alt for the parent only. Unknown wrappers are reviewed,
  never selected speculatively. No container missing-alt finding is introduced.
- **Rationale/implementation:** The existing NotImplementedError handler returned
  before group children were visited. It now invokes the existing namespace-aware
  direct-child visitor for grpSp only. Error handling is not otherwise widened;
  object fallback paths, IDs, source bytes and classifications are retained.
- **Verification:** Fresh baseline 85 tests. Related ALT_TEXT suite: 21 pass;
  full suite: 87 pass on Python 3.14.0 in .venv. Added parameterized cases cover
  parent property/marker ambiguity, native flags, complete/missing-alt children,
  nested groups, wrappers, exact targets and deterministic unchanged-source
  results. Fixtures are synthetic; Excel UI validation remains unperformed.

## AE-012 — Phase 4 missing/duplicate object-ID targets (2026-10-29)

- **Source/scope:** Phase 4 specification 2.1.0 Sections 7.1/7.2 and the
  developer's explicit request authorize changing only ALT_TEXT missing/duplicate
  DrawingML ID targets. Partial `1.1.1 Non-text Content`, not full coverage.
- **Rule:** Use the actual drawing part plus the existing indexed path of the
  owning pic, sp, cxnSp, graphicFrame or grpSp, including each nested child and
  every member of a duplicate-ID group. Retain unique `#id=` targets,
  MANUAL_REVIEW, category, messages and limitation reason. Location-bearing
  limitation strings use the new target. Existing 2.0.0 identity hashes that
  target; do not relabel historical results or increment the ruleset.
- **Rationale:** `inspect()` already computes this object-level `fallback`.
  Reuse it without new path calculation or changes to detection/group behavior.
  Distinct object paths preserve distinct findings and IDs.
- **Approval:** Developer authorized this exact implementation increment on
  2026-10-29. Team-wide adoption of the whole specification is not established.
  AE-009's cNvPr policy remains historical; AE-012 supersedes only the current
  missing/duplicate-ID target described in AE-009/010/011.
- **Implementation/verification:** `checks/image_alt_text.py` now passes the
  existing object-level `fallback` to review for missing/duplicate IDs.
  Fresh pre-change run: 82 tests passed. After the change, all 85 tests passed
  on Python 3.14.0 using `.venv/bin/python -m unittest discover -s tests -q`;
  the related `test_image_alt_text.py` suite passed 19 tests. Existing target
  assertions changed only for the authorized missing/duplicate-ID cases.
  Added tests cover the exact drawing1 duplicate-pic example, all five object
  kinds, nested groups/children, unique-ID targets, independently calculated
  2.0.0 IDs, repeatability, limitation reasons and unchanged source bytes.
  Historical snapshots and Phase 3 records are unchanged. New cases are
  synthetic ZIP/XML; no Excel UI validation or whole-spec adoption is claimed.

## AE-011 — Authorized Phase 4 common foundation (2026-10-29)

- **Source/approval:** Developer explicitly authorizes only versioned finding
  identity, aggregation and sparse cell-reading infrastructure for specification
  2.1.0/ruleset 2.0.0. This is not evidence of team-wide adoption or completed
  Phase 4 coverage. Partial `1.1.1 Non-text Content` and `2.4.2 Page Titled`
  (related `2.4.6 Headings and Labels`) remain the only active checks.
  Cell data will support future `1.3.1 Info and Relationships`,
  `2.4.4 Link Purpose (In Context)`, `1.4.1 Use of Color` and
  `1.4.3 Contrast (Minimum)` checks; none is added here.
- **Authorized changes:** New runs of the two active checks use ruleset 2.0.0
  identity. Preserve the Phase 3 helper, stored snapshots and inactive legacy
  helpers. Execute implemented checks in ALT_TEXT, WORKSHEET_NAME order, with
  later order reserved for TABLE_HEADER, MERGED_CELLS, LINK_TEXT, COLOR_CONTRAST.
  Sort findings, retain distinct targets and normalize only exact duplicate
  limitation strings. Exceptions remain failures. No unimplemented check is
  registered or reported as performed.
- **Reader contract:** Resolve actual internal workbook/sheet/shared-string
  relationships, preserve hidden/chart metadata, read stored cells sparsely,
  resolve body text in document order excluding phonetics, and distinguish
  formula metadata from stored cached values. Reuse the exact existing Unicode
  White_Space set for populated strings; intake uses stored values instead.
  Canonicalize bounded coordinates, infer omitted rows/columns from previous
  stored positions and fail explicitly on inconsistent/duplicate addresses.
  No formula evaluation, rewriting, findings or HTTP responses are generated.
- **Rationale/limits:** Reuse installed openpyxl coordinate conversion and
  defusedxml tree/stream parsing. Preserve raw cell values alongside typed
  values to avoid float precision loss and text normalization. The reader is
  independent of existing rules, avoiding unrelated parsing or scope changes.
  It is not a full intake validator or a six-rule audit implementation.
- **Implementation/verification:** `finding_ids.py`, `results.py`, `runner.py`
  and the two active checker call sites updated; `coordinates.py` and
  `cell_reader.py` added. Baseline 61 tests passed. After implementation,
  82 tests pass using Python 3.14.0 and the project .venv with openpyxl 3.1.5/
  defusedxml 0.7.1/et-xmlfile 2.0.0; no new dependency required.
  `test_finding_ids.py` retains the historical recipe and verifies three
  independent supplied 2.0.0 vectors. Runner/result tests cover execution vs
  result order, exact limitation normalization, duplicate record retention and
  failures. `test_cell_reader.py` covers sparse/inferred coordinates and errors,
  shared/inline/rich/phonetic text, formulas/caches, 0/false, whitespace, hidden
  and chart tabs, complete-package reading and unchanged input bytes.
  Historical snapshot bytes remain unchanged; regression comparisons independently
  apply only the authorized new identity and limitation normalization in memory.
  No new individual check, safe editor, currentValue or HTTP feature exists.
  Detailed reader fields/limits are in `phase4_common_foundation.md`. Unknown
  string wrappers raise instead of being interpreted as empty text; run/style
  rendering remains unassessed. Excel UI, Python 3.10, six-rule integration and
  performance remain unverified.

AE-010/008/009 below describe historical increments. AE-011 supersedes only
their current-version identity, execution order and limitation normalization;
their detection rules and cNvPr targets remain unchanged in this increment.

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
