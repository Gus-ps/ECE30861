# Remediation module: change report

Phase 4 work by Jonathan: show the checker's findings to the user, collect their
corrections, and write a remediated copy of the workbook.

## Files

| File | Status | Purpose |
| --- | --- | --- |
| `remediation.py` | New | `review()`, `remediate()` and an interactive command-line flow |
| `test_remediation.py` | New | End-to-end tests (`python -m unittest test_remediation`) |
| `accessibility_checker/` | **Copied unchanged** from `origin/haruki/accessibility-checker` (commit `d2b355d`) | The six-rule checker that `remediation.py` calls |
| `requirements.txt` | **Copied unchanged** from the same branch | `openpyxl`, `defusedxml`, `et-xmlfile` |
| `validity_check.py`, `validity_check_error_return.py`, `validity_check_object.py` | Modified | Fixed a file-handle leak (see below); behavior unchanged |
| `AGENTS.md` | New | Repository guide for coding agents and teammates (see below) |
| `INTEGRATION_NOTES.md` | New | Notes for Gustavo on wiring this module into the upload service |

None of these files are committed yet. To install the dependencies, run
`pip install -r requirements.txt`. If Haruki's package changes, copy it again or
merge his branch before committing.

## How it fits the website flow

1. **Upload.** `validity_check.validate_file(path)` rejects files that can't be accepted.
2. **Review.** `review(path)` runs `check_workbook` and returns each finding with two
   added fields:
   - `location`: a readable position, for example `sheet 'Data', cell E5 (xl/worksheets/sheet1.xml)`.
   - `input`: the value the user fills in to apply a fix. It is `None` when the finding
     can only be reviewed manually.

   The web page can render one form per finding directly from `input`:

   | Rule | `input` |
   | --- | --- |
   | `ALT_TEXT` | `{title, description}`, pre-filled with any existing values |
   | `WORKSHEET_NAME` | `{name}` |
   | `LINK_TEXT` | `{text}` |
   | `TABLE_HEADER` | `{headerRow}`; the user only confirms it |

3. **Decide.** The user's choices become
   `[{"findingId", "action": "APPLY" | "DECLINE" | "MANUAL_REVIEW", "value"}]`. This is the
   body of Operation 7 in the Phase 4 spec.
4. **Remediate.** `remediate(src, dst, decisions)` writes the copy and returns a report
   with these fields:
   - `decisions` and `approvedChanges`
   - `unresolvedFindings` and `manualReviewItems` (from re-auditing the copy)
   - `limitations`
   - `sourceSha256` and `outputSha256`

   Any problem raises `RemediationError`, whose `.code` is the spec's error code
   (`MISSING_VALUE`, `INVALID_CORRECTION`, `UNSUPPORTED_CORRECTION`,
   `DUPLICATE_DECISION`, `FINDING_NOT_FOUND`, `CONFLICTING_CORRECTIONS`,
   `INVALID_REQUEST`, `PRESERVATION_FAILED`). The service can map these to HTTP statuses.

`python remediation.py file.xlsx [out.xlsx]` runs the same flow in a terminal. It prints
each finding with its location and suggestion, asks for values, and writes
`out.xlsx` and `out-report.json`.

## Decisions and why

- **Targeted XML edits, not an openpyxl load and save.** Spec Section 11 requires every
  untouched ZIP entry to stay byte-identical. openpyxl drops content it doesn't model.
  The editor rewrites only the specific elements involved, and copies every other entry
  as-is with its original ZIP metadata.
- **Only `REQUIRES_USER_INPUT` findings can be applied.** Haruki's checker already
  decides which findings are safe to edit, for example through its rename-safety and
  shared-drawing rules. Not repeating that logic keeps this module small, and keeps the
  two from disagreeing. Everything else stays manual (spec Section 8.2).
- **Each rule makes the minimum change** the spec allows:
  - **ALT_TEXT:** set `title` and `descr` on that object's `cNvPr`.
  - **LINK_TEXT:** replace the cell with an inline string, and update the hyperlink
    `display` attribute if it has one. The shared-strings table is never touched.
  - **TABLE_HEADER on an existing table:** change only `headerRowCount` to 1.
  - **TABLE_HEADER on an unstructured range:** add a minimal `A11yTable<N>` table, plus
    its relationship, `tablePart` and content type.
  - **WORKSHEET_NAME:** change the sheet's name. Then rewrite references to it in cell,
    defined-name, chart, table, data-validation and conditional-formatting formulas, and
    in internal hyperlink locations. String literals are skipped, and new names are
    always quoted.
- **All-or-nothing with verification.** All edits are made in memory and written to a
  temporary file. The temporary file is moved into place only after three checks pass:
  - the ZIP passes its integrity test;
  - every entry matches what was planned;
  - re-running all six rules no longer reports any approved finding.

  If anything fails, no output exists (spec Sections 8.2 and 9).
- **The source can't be overwritten.** `remediate` refuses when `dst` is the source file.
- **IDs, storage and idempotency are left to the service.** Workbook, version and audit
  IDs, job state and `Idempotency-Key` handling belong in Gustavo's API layer. This
  module stays a pure "file in, file and report out" function.
- **The checker runs again on the source inside `remediate`.** This lets the function
  stand alone. The checker is deterministic, so the finding IDs match the ones the user
  saw in the review.

## Fixes made while reviewing the module

Each issue turned up in a review pass, was fixed, and the tests were run again.

- **Malformed decisions.** A decision that isn't an object, or whose `findingId` isn't a
  string, used to crash with a Python error. It now returns `INVALID_REQUEST`.
- **`headerRow` type.** `headerRow` must now be a real integer. Before, `True` was treated
  as row 1.
- **`#REF!` in formulas.** During sheet-reference rewrites, `#REF!` could be mistaken for a
  sheet named `REF`. It no longer is.
- **Overwriting the source.** `remediate` now refuses an output path that is the source file.
- **Output check.** The output check originally called `validate_file`, which leaked a
  file handle and could lock the temp file on Windows. It now uses `zipfile.testzip()`
  instead; editing can't change protection, sheet count or cell count anyway.
- **Test corrections.**
  - Added a merged title cell to the test workbook, so the manual-review rejection case
    has a finding to use.
  - Added a second table candidate on a sheet that already has a table, so the code that
    appends to an existing `<tableParts>` is exercised.
  - Corrected the expected new table IDs: fixes apply in source finding order, so
    `Budget` sorts before `Data`.

## Verification performed

- `test_remediation.py` (3 tests, all passing):
  - All six supported fix types run in one batch: alt text, link text, sheet rename
    (with formula, defined-name and hyperlink references, and an apostrophe in the new
    name), an existing-table header, and two new tables. One of the new tables goes on a
    sheet that already has a table.
  - The source hash is unchanged.
  - Exactly the expected ZIP entries change or are added.
  - Every rejection case leaves no output and no temporary files.
- Haruki's committed fixtures (`six_rule_seeded`, `five_rule_seeded`,
  `migration_complete`) all remediate successfully. Only the manual-review findings
  remain. This includes renaming a chartsheet and a lowercase `sheet2`, with chart
  series references rewritten.
- Every changed XML part parses as well-formed, and every output opens in openpyxl.

## Known limitations and open items

- **Not yet opened in Microsoft Excel.** The spec requires a manual Excel check with no
  repair prompt as a release gate. No Excel was available here, so this still needs doing.
- **Strict OOXML workbooks:** creating a new table on them is refused.
- **`docProps/app.xml`** still lists the old sheet names after a rename. The spec says to
  leave untouched parts unchanged, and Excel rewrites this list when the file is saved.
- **Gustavo's copy of `validity_check.py` still has the file-handle leak.** It is on his
  branch, so it was not changed here.
- **Service integration is still to do:**
  - Operations 7 to 9.
  - Storing the output as a new version with `sourceVersionId`.
  - The downloadable report (spec Section 12). The report fields above already line up
    with that section.

  `INTEGRATION_NOTES.md` has the steps. The most urgent one: Gustavo's service must move
  to ruleset 2.0.0, or the finding IDs won't match.

## Other changes this session

- **Validator leak fix.** In all three validator versions, the two `ET.iterparse` loops
  (worksheet protection and cell count) now open each worksheet in a `with` block.
  Before, the handles were never closed: Python raised `ResourceWarning` and Windows
  could keep the file locked. All files in `sample_files/` gave the same results before
  and after, with no leaked handles.
- **`AGENTS.md`.** Written after exploring all remote branches (`git fetch`) and running
  each branch's tests in temporary worktrees, which were removed afterwards. It covers:
  - a branch map and the verified setup and test commands;
  - Windows-only test failures;
  - a Phase 3–5 roadmap based on `ECE 30861 Phase 2 Pod E.pdf`.

  The PDF is treated as a guide to intent and to what to build next, not as a rulebook
  for judging existing code.
- **`INTEGRATION_NOTES.md`.** A step-by-step note for Gustavo that covers:
  - the ruleset version;
  - the checker and dependency updates;
  - Phase 4 status derivation;
  - Operations 7 to 9, with an error-code-to-HTTP-status table;
  - the audit report fields;
  - the findings form on the upload page.
