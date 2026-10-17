# Accessibility Checker Notes — Phase 3 Work in Progress

## Authority and current status

The developer adopted Section 5 of
[the shared suite guide](team12-shared-test-suite-guide.md) for this increment:
suite manifest **1.4.0**, ruleset **1.0.0**, Team 9 profile **1.0.0**, source
revision `66d588c`. This is not confirmation of wider team/pod agreement.

Only the determined subset has been implemented. Full Section 5 conformance is
**not claimed**: the referenced contract/profile and schema are not available.
Unsupported cases currently stop with `NotImplementedError`; they do not yet
produce the guide's required review finding and limitation.

## Usage and runner

Use Python 3.10+ from the repository root; only the standard library is needed.
Input is an already validated, readable local `.xlsx`. Files are never saved.

```python
from accessibility_checker.runner import check_workbook

findings = check_workbook("/path/to/workbook.xlsx")
```

The Phase 3 runner explicitly calls `check_worksheet_names`, then
`check_image_alt_text`. It computes the source SHA-256 once and passes that
value to both functions. Each still reads the workbook independently. Findings
are combined and sorted by `(ruleId, worksheet, target)` in Unicode code-point
order. Exceptions propagate; no successful partial result is returned.

The current return type remains `list[dict[str, str]]` with eight fields:
`findingId`, `ruleId`, `category`, `worksheet`, `target`, `classification`,
`message`, `recommendation`. No limitations container is invented. This return
shape needs confirmation before the required limitations can be transported.
An empty list means no findings in the handled subset, not an overall PASS.

Direct calls are also available. They hash the file themselves when the runner
has not supplied the optional keyword-only `source_sha256` context:

```python
from accessibility_checker.checks.worksheet_names import check_worksheet_names
from accessibility_checker.checks.image_alt_text import check_image_alt_text

names = check_worksheet_names("/path/to/workbook.xlsx")
objects = check_image_alt_text("/path/to/workbook.xlsx")
```

## WORKSHEET_NAME — 2.4.2 Page Titled

Related reference: `2.4.6 Headings and Labels`.

- Inspect all worksheets, including hidden/veryHidden. Exclude chartsheets.
- Trim only leading/trailing characters in the exact White_Space list below.
  Do not remove internal whitespace or normalize Unicode.
- Fully match case-insensitive **ASCII** `Sheet` plus one or more ASCII digits,
  with numeric value greater than zero. Leading zeroes are allowed.
- `Sheet1`, `sheet2`, `Sheet01`, and whitespace-surrounded `Sheet3` trigger.
  `Sheet0`, `Sheet000`, `Sheet`, `Sheet 1`, numeric-only names, and non-ASCII
  letter/digit substitutes do not.
- Preserve the original name in `worksheet` and in finding-ID input.
- Rule/category: `WORKSHEET_NAME`; classification: `REQUIRES_USER_INPUT`.
- Target: actual worksheet part plus `#sheetId=<stored-sheetId>`, resolved from
  the workbook relationship, not guessed from part numbers.
- No name generation, renaming, or evaluation of meaning/content relevance.

## ALT_TEXT — 1.1.1 Non-text Content

The determined implementation handles standard DrawingML pictures, shapes,
connection shapes, chart graphicFrames, and recursively grouped children on all
worksheets, including hidden/veryHidden. Group containers are traversed; their
children are assessed individually. Chartsheets are excluded.

Read accessibility `title` and `descr` from each object's nonvisual `cNvPr`.
Visible chart titles, captions, object names, and filenames do not substitute.
For a non-decorative object, either field absent/empty/White_Space-only yields
**one** finding, even when both fields are missing. The message explicitly
identifies `title` and/or `description (descr)`. Classification is
`REQUIRES_USER_INPUT`.

A native `adec:decorative` flag with `val="1"` or `"true"` yields one
`MANUAL_REVIEW` finding asking to confirm the decorative designation, even if
both text attributes are present. Explicit `0`/`false` is not decorative.
Rule/category: `ALT_TEXT` / `NON_TEXT_CONTENT`.

Targets are actual drawing part paths plus `#id=<stored-object-id>`.
Worksheet/drawing/chart relationships are followed rather than matched by
filename numbering. IDs must be available and unambiguous in the handled
representation. No descriptions are generated or written; no semantic quality
or visible text is evaluated.

### Unresolved/unsupported cases

**TODO — obtain the contract before implementing these cases:**

1. Exact review-finding values for unsupported/ambiguous representations.
2. `limitations` element fields/types and how the runner returns them alongside
   findings; the guide only specifies that limitations is an array.
3. Exact indexed `#xml=` grammar for missing/duplicate object IDs: namespaces,
   index base, sibling-counting rules, and duplicate-ID handling.
4. Group-level decorative designation/inheritance and treatment of unsupported
   DrawingML, VML, compatibility wrappers, controls, cell images, and other
   representations.

Currently, recognized ambiguity stops processing instead of being silently
ignored: missing/duplicate object IDs, unexpected anchors/object namespaces,
nonstandard graphicFrames, AlternateContent, and ambiguous decorative metadata.
Group-level decoration also stops because inheritance is undefined.
Conservative stops also cover legacy/background/control objects, value metadata,
rich-data/cell-image package parts, and potential IMAGE formulas. Some may be
unrelated to a covered image; that uncertainty is deliberately not resolved by
inventing a review schema. Detection of every possible unsupported representation
is not verified. These stops are **not** final contract-compliant reporting.

## Exact whitespace and identity

`accessibility_checker/phase3_policy.py` defines the guide's Unicode White_Space
set explicitly: U+0009–000D, 0020, 0085, 00A0, 1680, 2000–200A, 2028, 2029,
202F, 205F, 3000. U+200B is not whitespace. No-argument `strip()`/`isspace()`
are not used as substitutes for this set.

`accessibility_checker/finding_ids.py` provides shared `get_source_sha256` and
`make_phase3_finding_id` utilities. `sourceSha256` is lowercase SHA-256 of the
original file bytes. The finding digest is lowercase SHA-256 of UTF-8 JSON:

```text
[sourceSha256, "1.0.0", ruleId, originalWorksheetName, target]
```

JSON uses `ensure_ascii=False`, `separators=(",", ":")`, with no normalization,
BOM, newline, random value, or timestamp. Messages and recommendations use
stable wording. Runner and checkers do not independently rehash the same input
when called through the runner.

## Retained inactive checkers

`checks/workbook_title.py` (`2.4.2 Page Titled`) and `checks/table_headers.py`
(`1.3.1 Info and Relationships`) remain available but are not run in Phase 3.
Their detection and legacy ID policy are unchanged. The old three-argument
`make_finding_id` is retained only for these callers; it lacks workbook/ruleset
identity. Do not treat those legacy values as the Phase 3 identity format.

## Verification and remaining handoff

After the initial no-test increment, the developer authorized focused tests.
On 2026-10-17, `.venv/bin/python -m unittest discover -s tests -v` passed all
**40 tests** (4 identity, 11 ALT_TEXT, 5 runner, 4 worksheet-name, 8 Title,
8 table-header tests). Fixtures are synthetic ZIP/XML metadata, not complete
Excel-created workbooks; real-Excel serialization remains unverified.

Tests cover the Phase 3 predicates, hidden sheets, pictures/shapes/charts,
group children, decorative review, original targets/names, stable eight-field
findings, literal compact-JSON identity, one source hash per runner call,
sorting, source preservation, and exception propagation. Missing/duplicate IDs,
unknown objects, and backgrounds confirm temporary failure behavior only,
not final contract-compliant review/limitations reporting.

The whitespace policy is checked against all 25 listed code points and excludes
U+001C–001F and U+200B. XML fixtures omit U+000B/U+000C and U+001C–001F because
XML 1.0 cannot contain those literal characters; policy checks are not proof of
Excel's escaped-string serialization handling.

The verification owner should independently check:

- All listed White_Space characters versus U+200B and U+001C–001F; prefix/suffix
  trimming only, internal spaces, ASCII-only case/digits, positive/zero suffixes.
- Hidden/veryHidden worksheets and chartsheet exclusion; renamed/absolute and
  relative worksheet/drawing parts; original spelling and sheetId targets.
- Pictures, charts, shapes, nested groups; title-only, description-only, neither,
  blank fields, U+200B content; visible captions/names not used as replacements.
- Native decorative true/false, one review per object, and stable prose.
- Missing/duplicate IDs, group decoration, wrappers, legacy/cell-image formats,
  and every conservative stop: errors must not return a successful partial list.
- Independently calculated source/digest bytes and compact JSON, non-ASCII and
  canonically distinct Unicode names, repeatability, changed source bytes, and
  global code-point sorting. Runner must execute only the two Phase 3 rules.
- Original bytes remain unchanged on successful and failed processing; inactive
  checkers remain callable with their previous behavior.

See `AE-007` in [the assumptions log](assumptions_and_extensions.md) for the
confirmed developer scope and outstanding contract questions.
