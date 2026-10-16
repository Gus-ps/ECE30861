# Assumptions and Extensions

Output history in AE-001/AE-002 is superseded by AE-003; their detection scope
and developer-only approval remain unchanged.

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
- **Implementation:** Implemented in `worksheet_names.py`,
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
- **Implementation:** `image_alt_text.py`, `check_image_alt_text` returns
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
- **Implementation:** `finding_ids.py`, `worksheet_names.py`, `image_alt_text.py`;
  TODO comments and `.docs/checker_notes_en.md` explicitly flag both ID updates.
- **Verification:** All 17 tests passed with
  `.venv/bin/python -m unittest discover -s tests -v`: 7 worksheet, 8 image,
  2 ID tests. They verify unchanged detection/exclusions and source bytes,
  exact field sets/types, category/classification values, message lengths,
  target mapping, sorting, ID syntax, and local determinism. Workbook/ruleset
  identity semantics and approved catalog conformance remain unimplemented.
