# Assumptions and Extensions

Output history in AE-001/AE-002 is superseded by AE-003; their detection scope
and developer-only approval remain unchanged.

**Current Phase 3 work:** AE-007 supersedes the active rule scope, IDs, and runner
described in AE-001/002/003/006. Earlier verification results are historical,
not verification of the Phase 3 changes. AE-004/005 remain inactive legacy checks.

## AE-001 — Prototype worksheet-name heuristics (2026-10-16)

- **Criterion:** `2.4.2 Page Titled`; related `2.4.6 Headings and Labels`
  reuses sheet-name results in `WCAG_2.1_Excel_Automated_Validation_Methods.md`.
  This maps the heuristic only, not workbook-title checks or full criteria.
- **Requirement basis:** REQ-03: preserve the source; REQ-04: check generic
  worksheet names; REQ-05: provide actionable findings; REQ-06: leave
  meaning-dependent decisions to people. AC-03–06 cover these behaviors.
  These requirements do not establish the normalization, numeric-name rule,
  or visible-only scope below.
- **Rule:** Inspect visible worksheets only (missing `state` means visible);
  exclude hidden, veryHidden, and chartsheets. For comparison only, remove
  whitespace using `"".join(name.split())` and lowercase using `lower()`.
  Full-match `sheet[0-9]*` → `DEFAULT_LIKE`; `[0-9]+` →
  `NUMERIC_REQUIRES_REVIEW`. Numeric names, including years, require meaning
  review, not a verdict of inappropriateness; no year exemptions apply.
  Return `{name, reason}` records with original names in workbook order.
- **Rationale and limits:** Developer-requested broader detection; adding a
  reason distinguishes the two heuristics. Assume valid, readable `.xlsx`
  input. Read only; no validation, content-relevance assessment, LLM, or
  renaming. Undetected names are not certified accessible. The local result
  is not the full shared finding schema; no shared API changes are made.
- **Approval:** Authorized by the requesting developer for this prototype only.
  Team/pod approval of these detailed conditions is not established.
- **Implementation:** Implemented in `accessibility_checker/checks/worksheet_names.py`,
  `check_worksheet_names`. Replaces case-sensitive `Sheet[0-9]*` matching and
  `list[str]` output; retains visible-only, read-only processing and workbook order.
- **Verification:** All 6 tests in `tests/test_worksheet_names.py` passed on
  2026-10-16 with `.venv/bin/python -m unittest discover -s tests -v`.
  Coverage: normalization, exclusions, numeric review, reasons, original names,
  ordering, and unchanged source bytes. Tests use minimal ZIP/XML metadata;
  complete-workbook coverage and full shared acceptance criteria remain
  unverified. Passing tests does not establish shared approval.

## AE-002 — Prototype inserted-picture alt-text check (2026-10-16)

- **Criterion:** `1.1.1 Non-text Content`, per
  `WCAG_2.1_Excel_Automated_Validation_Methods.md`; presence-only coverage for
  ordinary inserted pictures, not the complete criterion.
- **Requirement basis:** REQ-03–06 and AC-03–06 cover source preservation,
  missing-alt-text detection, actionable locations, and human judgment;
  they do not define exact OOXML/title/decorative handling. Microsoft's
  [picture example](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.drawing.spreadsheet.picture?view=openxml-3.0.1)
  stores description in `xdr:pic/xdr:nvPicPr/xdr:cNvPr/@descr`;
  [properties](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.drawing.spreadsheet.nonvisualdrawingproperties?view=openxml-3.0.1)
  distinguish `descr`, `title`, and `name`.
- **Scope:** Valid, readable `.xlsx`; visible worksheets and ordinary inserted
  pictures only. Exclude hidden/veryHidden sheets, charts, shapes, backgrounds,
  and in-cell images. Follow worksheet/drawing relationships, not filename
  numbers. Never save, assess descriptions, generate text, or substitute names.
- **Rule:** Missing, empty, or whitespace-only `descr` is missing alt
  text. Title alone does not substitute. Exclude explicitly decorative pictures
  (`adec:decorative/@val` true), per the
  [decorative flag](https://learn.microsoft.com/en-us/openspecs/office_standards/ms-odrawxml/1c5cfa5e-0042-48e3-ba41-2cc88fcc0266).
- **Rationale/limits:** Minimal metadata-only presence check. Unsupported or
  unexamined content is not a pass. No Excel-created sample was found in the
  repository or referenced project materials; actual Excel output is unverified.
- **Approval:** The requesting developer authorized proceeding with the proposed
  title-only and decorative handling after the pre-implementation question.
  This authorizes the prototype only, not shared team/pod requirements.
- **Implementation:** `accessibility_checker/checks/image_alt_text.py`, `check_image_alt_text` returns
  worksheet, drawing part, image ID/name, and missing/empty/whitespace reason.
  No dependencies or worksheet-name changes.
  Ordinary pictures directly anchored in DrawingML are examined; grouped,
  compatibility-wrapped, legacy, and other unsupported representations remain
  unexamined, never passed. Empty results describe only this limited check.
- **Verification:** `.venv/bin/python -m unittest discover -s tests -v` passed
  all 13 tests (7 image and 6 existing name tests). New tests cover descriptions,
  title-only, decorative true/false, three anchor types, mismatched part numbers,
  multiple sheets/images, relative/absolute targets, exclusions, and unchanged
  source bytes. These are synthetic ZIP/XML fixtures. No Excel-created sample
  was available; real Excel serialization and unsupported content remain
  unverified. Passing tests does not establish shared approval or accessibility.

## AE-003 — Temporary finding identifiers and contract mapping (2026-10-16)

- **Basis:** The HTTP contract requires eight string fields: `findingId`,
  `ruleId`, `category`, `worksheet`, `target`, `classification`, `message`,
  `recommendation`. IDs are 1–64 characters matching `[A-Za-z0-9_-]+`;
  messages/recommendations are 1–500 characters. Results sort by rule, sheet,
  target. The shared rule catalog and concrete object-target syntax are absent.
- **Authorized mapping:** `WORKSHEET_NAME` and `ALT_TEXT` are temporary rule IDs
  awaiting catalog confirmation. Categories are `WORKSHEET_NAME` and
  `NON_TEXT_CONTENT`; both classifications are `REQUIRES_USER_INPUT`.
  Worksheet target is its original name; image target is `drawing-part#id=N`.
  Existing detection conditions and exclusions remain unchanged; prior reason
  distinctions move into messages. This supersedes earlier local output formats
  and workbook-order results, not their detection rules (AE-001/AE-002).
- **Temporary ID:** A dedicated `make_finding_id` function hashes rule ID,
  worksheet, and target into 64 hex characters. It is deterministic but lacks
  workbook/ruleset identity: identical locations across workbooks can share IDs.
  Replace it when the final identity policy is available; full contract identity
  semantics and approved-catalog conformance are not claimed.
- **Approval:** The requesting developer authorized these temporary choices;
  team/pod approval is not established. Scope: WCAG 2.1 `2.4.2 Page Titled`
  (related `2.4.6 Headings and Labels`) and `1.1.1 Non-text Content`, partially.
- **Implementation:** `accessibility_checker/finding_ids.py`, `accessibility_checker/checks/worksheet_names.py`, `accessibility_checker/checks/image_alt_text.py`;
  TODO comments and `.docs/checker_notes_en.md` explicitly flag both ID updates.
- **Verification:** All 17 tests passed with
  `.venv/bin/python -m unittest discover -s tests -v`: 7 worksheet, 8 image,
  2 ID tests. They verify unchanged detection/exclusions and source bytes,
  exact field sets/types, category/classification values, message lengths,
  target mapping, sorting, ID syntax, and local determinism. Workbook/ruleset
  identity semantics and approved catalog conformance remain unimplemented.

## AE-004 — Missing workbook title (2026-10-17)

- **Basis/scope:** `2.4.2 Page Titled` in the WCAG mapping guide covers missing
  workbook titles. The developer additionally specifies absent core properties,
  absent/empty/whitespace-only title as missing, with one finding per workbook.
  Any nonwhitespace text is accepted; generic titles, filename equality, and
  content relevance are not evaluated. Assume a valid, readable `.xlsx`; never
  save it. Read `dc:title` from the package's core-properties relationship.
- **Temporary mapping:** Rule/category `WORKBOOK_TITLE`; worksheet/target
  `__WORKBOOK__`. These constants identify workbook scope but the sentinel can
  collide with a real worksheet name. This category is not a confirmed HTTP
  contract value; the existing contract has no workbook-title category.
- **Rationale/approval:** A separate small checker preserves existing rules.
  The developer explicitly requires `REQUIRES_USER_INPUT`; the other mapping
  values were chosen under developer permission and await team/pod agreement.
  Do not describe them as approved shared values.
- **ID limits:** Reuse `make_finding_id` unchanged (AE-003). It omits workbook
  and ruleset identity; missing-title findings across workbooks share an ID.
- **Implementation:** `accessibility_checker/checks/workbook_title.py`, `tests/test_workbook_title.py`, and
  shared English notes; no new ID policy, dependencies, or checker framework.
- **Verification:** All 25 tests pass (8 new title tests, 17 existing), using
  `.venv/bin/python -m unittest discover -s tests -v`. New tests cover title
  states, absent core properties, relationship targets, eight-field output,
  temporary values, ID reuse, and unchanged bytes. Synthetic metadata fixtures
  are not complete Excel files. Local `test.xlsx` was also read (one finding,
  unchanged bytes); its Application metadata says `Microsoft Excel`, but origin
  is not independently verified. Full real-Excel validation remains unverified.

## AE-005 — Excel Tables without a header row (2026-10-17)

- **Basis/scope:** WCAG guide section 3, `1.3.1 Info and Relationships`, and
  section 8.6 specify detection of `headerRowCount="0"` in Excel Tables.
  Inspect visible worksheets only; exclude hidden/veryHidden and chartsheets.
  Follow workbook → worksheet → table relationships, not part filename numbers.
  Report one finding per table with an explicit zero header-row count. Absent
  or nonzero counts, ordinary cell ranges, and header-name quality are outside
  this detection rule; no result certifies their accessibility.
- **Mapping/approval:** The requesting developer approved the recommended
  visible-only scope, category `TABLE_STRUCTURE`, and table `ref` range as
  target. Rule ID `1.3.1-TABLE-NO-HEADER` is provisional pending agreement with
  the other team; keep a TODO. Classification is `REQUIRES_USER_INPUT`, since
  choosing meaningful headers needs human input. This is developer approval,
  not confirmed team/pod approval of a shared rule ID.
- **Limits:** Existing eight-field findings and `make_finding_id` are unchanged;
  workbook/ruleset identity limitations in AE-003 still apply. Read only; no
  header creation, table repair, input validation, or new dependencies.
- **Implementation:** `accessibility_checker/checks/table_headers.py`,
  `tests/test_table_headers.py`, shared English notes. No existing checker or
  ID-generation behavior was changed.
- **Verification:** All 8 table tests pass, and all 33 tests pass with
  `.venv/bin/python -m unittest discover -s tests -v`. Synthetic fixtures test
  explicit zero/nonzero/omitted counts, multiple tables/sheets, relationship
  mapping, exclusions, orphan parts, finding fields/IDs, ordering, unchanged
  bytes. Local `test.xlsx` read successfully with unchanged bytes and zero
  findings, but has no table parts: real-Excel missing-header detection remains
  unverified. No table coverage or accessibility is inferred from that result.

## AE-006 — Explicit workbook runner (2026-10-17)

- **Scope/approval:** The developer requested `check_workbook(path)` to call
  every currently implemented checker. This is a local entry point, not a
  shared HTTP interface or team/pod-approved overall compliance assessment.
  It covers only the existing partial checks for `1.1.1 Non-text Content`,
  `1.3.1 Info and Relationships`, and `2.4.2 Page Titled` (related: `2.4.6
  Headings and Labels`). No new detection rule is introduced.
- **Behavior:** Explicitly call worksheet names, image descriptions, workbook
  Title, and table headers in that order. Each checker opens the same path
  independently. Combine unchanged findings and sort by ruleId/worksheet/target.
  Propagate any exception; never return partial findings as a successful result.
  No validation, hashing, new identity policy, CLI, or overall PASS/FAIL.
- **Limits:** Existing exclusions, provisional values, and cross-workbook ID
  limitations remain. No findings does not certify unchecked content.
- **Implementation:** `accessibility_checker/runner.py`, `tests/test_runner.py`,
  and shared usage notes. No existing checker or ID algorithm was modified.
- **Verification:** All 5 runner tests and all 38 tests passed using
  `.venv/bin/python -m unittest discover -s tests -v`. Tests cover four-checker
  integration on one synthetic ZIP/XML fixture, empty results, global sorting,
  unchanged findings, explicit invocation order, exceptions from each checker,
  and unchanged source bytes. No new real-Excel verification was performed.

## AE-007 — Partial Section 5 alignment and required confirmations (2026-10-17)

- **Authority:** The developer adopts Section 5 of the Team 9 → Team 12 guide
  (manifest 1.4.0, ruleset/profile 1.0.0, revision `66d588c`) for this work.
  This does not establish unverified team/pod-wide agreement.
- **Confirmed changes:** All worksheets, excluding chartsheets; exact listed
  Unicode White_Space. WORKSHEET_NAME trims ends only, matches ASCII Sheet plus
  ASCII digits representing a positive number, and targets actual part#sheetId.
  ALT_TEXT requires both accessibility title and descr on supported DrawingML
  pictures/charts/shapes and grouped children; explicit native decorative
  objects receive MANUAL_REVIEW. Normal missing fields receive REQUIRES_USER_INPUT.
- **Identity/runner:** Ruleset 1.0.0; compact UTF-8 JSON SHA-256 over raw-file
  SHA-256, ruleset, rule, original sheet name, and actual target. Runner computes
  the source digest once and passes it to the two active checkers. Retain the
  legacy ID helper for inactive Title/Table callers; do not break them silently.
- **REQUIRES CONFIRMATION:** The referenced Phase 3 contract/profile and schema
  are unavailable. Obtain limitations element schema, exact unsupported-object
  review values, and indexed #xml= rules (namespaces, index base/counting,
  missing/duplicate IDs). Also confirm runner transport of limitations; its
  current return type is still a list of findings. No schema or #xml= is invented.
  Group-level decorative inheritance and unsupported representations remain
  deferred; only grouped children with independently interpretable metadata
  are handled. Unsupported/ambiguous cases recognized by this partial
  implementation raise NotImplementedError rather than return a successful
  partial list. This is a temporary stop, not the required final review/limitation
  behavior. Full Section 5 coverage/conformance is not claimed.
- **Approval/status:** Developer authorizes implementing only the determined
  subset while leaving the above decisions pending. Implemented in the two
  active checkers, `finding_ids.py`, `phase3_policy.py`, and runner. The canonical
  function is `make_phase3_finding_id`; the old three-argument helper is retained
  solely for the inactive legacy checkers. No unavailable schema is fabricated.
  Conservative stops cover recognized VML/background/control content, potential
  IMAGE formulas, rich-data/value metadata, wrappers, and object ambiguity;
  exhaustive unsupported-format detection is unverified.
- **Verification:** Initially deferred by instruction; the developer subsequently
  authorized focused tests and a push if satisfactory. All 40 tests pass with
  `.venv/bin/python -m unittest discover -s tests -v`: Phase 3 predicates,
  identity, targets, decorative review, grouped children, runner aggregation,
  temporary unsupported-case failures, unchanged bytes, and retained legacy
  checks. Updated tests: `test_worksheet_names.py`, `test_image_alt_text.py`,
  `test_finding_ids.py`, `test_runner.py` under `tests/`. Synthetic XML fixtures
  cannot represent literal XML 1.0-prohibited controls; the full whitespace set
  is independently checked at policy level. Real-Excel output, escaped-string
  handling, exhaustive unsupported detection, and final pending-contract
  behavior remain unverified. Passing tests does not resolve the above decisions.
