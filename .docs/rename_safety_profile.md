# Worksheet rename classification: read-only profile

Readiness stage 3 implements developer-authorized classification under Phase 4
specification 2.1.0 Sections 7.3, 8.4 and 11. Criterion references are partial
`2.4.2 Page Titled`, related `2.4.6 Headings and Labels`. This is not shared
adoption, an editor, or evidence of serialized output preservation.

## Findings and inventory

The default-name detection rule is unchanged: trim the declared White_Space
set, ASCII-case-insensitive full-match Sheet plus positive ASCII digits. Preserve
original names, targets and the 2.0.0 identity recipe. Hidden/veryHidden and
chartsheet tabs remain included. Only for matching names, preflight the entire
workbook once. A supported reference profile yields REQUIRES_USER_INPUT; blockers
yield MANUAL_REVIEW and deterministic limitations. Descriptive names acquire no
new defect solely because references are complex. `check_worksheet_names` now
returns the existing list-compatible Findings class to carry `.limitations`;
no argument or finding field is added. IDs exclude classification/recommendation.

`rename_safety.py` examines actual relationships and archive entries. Reusable
`part_ownership.py` distinguishes sheet definitions from repeated references
within one owner, including table parts. Ambiguous shared sheets/drawings/tables
block rename. Missing required parts and malformed XML remain failures; external
destinations are never fetched. XML is streamed without expanding used ranges.
Multiple inventory passes are used; performance/peak memory are unmeasured.

Locations include cell formulas, workbook/local defined names, chart series,
validation formula1/formula2, conditional formulas and formula-valued thresholds,
table formula fields, worksheet internal hyperlink locations and internal
hyperlink relationships. Known rendering/properties/styles/shared strings/comments
use explicit structural profiles. Unknown package parts, markup, attributes and
extensions disclose limits instead of being presumed harmless.

## Token grammar and supported cases

Installed openpyxl 3.1.5 Tokenizer separates strings and RANGE operands, but
does not validate all formula syntax. The preflight additionally checks groups,
operand/operator structure, function separators and each reference token.
A quote-aware scanner splits `!` outside quoted sheet names and decodes doubled
apostrophes. Sheet names and scoped defined names are resolved; bounded A1/
absolute addresses, ranges, whole rows/columns and unions are recognized.
`"Sheet1!A1"` remains a literal even if it contains names/function-like words.

Builtin names come from installed FORMULAE plus IMAGE; arguments are parsed,
never executed/fetched. INDIRECT/EVALUATE/HYPERLINK are blocked because strings
can become references/destinations. Unknown functions and `_xlfn` extensions
are manual. Tokenizer errors/incomplete grammar are explicit limitations, not
proof of corrupt workbook bytes; unrelated read/processing failures propagate.

## Manual cases and limits

- 3D/external references, dynamic reference construction, shared/array/data-table
  formulas and dynamic metadata/extensions.
- Pivot/cache/slicer/query connections, signed packages, opaque/embedded
  structures, unknown reference-bearing parts/markup/attributes, and ambiguous
  ownership/names.
- HYPERLINK formulas, unsupported object formula/macro bindings and query-bound
  table metadata.
- Structured reference operands, intersection syntax and other formula dialects
  or schema/rendering variants outside the finite profile.

The required ordinary cases are not universally manual: tests exercise safe
formulas, quoted/apostrophe names, scoped names, charts, validation, conditional
formatting and internal hyperlinks. Additional profiles need evidence before
removing blockers. A future editor must implement all corresponding rewrites,
preserve unselected bytes/semantics and pass independent preservation and real
Excel no-repair checks. No rewrite, saving, output or currentValue is produced.

## Verification

On 2026-10-29, 4 name tests, 14 preflight tests and all 104 tests pass on
Python 3.14.0 using .venv, after stage 2's 90-test baseline. Tests include all
required normal families and blocker families, other/hidden/chart sheets, exact
targets/independent IDs, repeatability and source bytes. The old name-test
builder now supplies actual empty sheet parts needed for the inventory; name
matching assertions and historical workbook/snapshot bytes are unchanged.
Synthetic XML and automated XLSX reading do not establish Excel UI validation,
performance, minimum-Python execution or working remediation.
