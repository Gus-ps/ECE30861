# Phase 4 common checker foundation

COLOR_CONTRAST is now registered, completing six-rule execution (not Phase 4/remediation acceptance). Static low contrast/color meaning combine per cell; visual conditional ranges are deduplicated and suppress static results. Unknown visual extension scope receives whole-part manual disclosure, not an invented range/ratio. Formula caches are never calculated. Three color-check tests and all 147 tests pass. Historical two-rule mocks remain explicit; five-rule fixtures now run through the current six-rule runner without rewriting their bytes or five-rule tuples. Dedicated six-rule fixtures follow.

Color foundation verified against corrected pack 2.1.1: exact Fraction HSL intermediates, final half-up channels, all supplied tint/contrast vectors, exact-half neighbors and frozen 64-color palette equality. Palette is packaged as code, independent of runtime .docs. Eleven helper tests and full 144-test regression pass. Unsupported rendering remains explicit; COLOR_CONTRAST is not yet registered. No Excel UI evidence or shared deployment claim.

Current adoption: corrected pack revision 2.1.1 resolves AE-020; implementation resumes using CORRECTIONS.md. Specification remains 2.1.0, ruleset 2.0.0, suite target 2.1.1 (no executable tester created). All seven SHA256SUMS members verified. Earlier pending statements below are historical; neither team deployment nor complete implementation is established. See [corrected pack](phase4_agent_context_pack/README.md).

## Current status — five-rule integration (2026-10-30)

The runner executes ALT_TEXT → WORKSHEET_NAME → TABLE_HEADER → MERGED_CELLS →
LINK_TEXT. COLOR_CONTRAST is unregistered; six-rule integration and remediation
are not complete. Color helper/reader extensions remain incomplete, uncommitted
work and are excluded from this integration commit.

The 64-color policy palette has been supplied. Missing reference material is no
longer the blocker: two tint vectors conflict with the specification's half-up
rule, and the pod's rounding decision is pending. Proposed corrections are not
approved; neither the specification nor vectors have been changed. See AE-020
in [the assumptions log](assumptions_and_extensions.md) for exact values/history.

Executed verification: committed HEAD baseline **131 tests**; new real-runner
five-rule integration **2 tests**; proposed commit snapshot **133 tests**; working
tree including the nine uncommitted color-helper tests **142 tests**. Passing
regression does not establish color completion or agreement with all vectors;
the two previously observed normative tint mismatches remain unresolved.

The new complete clean/seeded packages verify exact finding tuples and independent
IDs, both classifications, hidden/veryHidden tabs, five repeated executions,
unchanged source bytes, direct-call aggregation, and actual call order/exclusion
of color and legacy Title/Table. No checker is mocked to succeed. See
[fixture recipe and scope](../tests/fixtures/five_rule_fixtures.md).
Openpyxl reading is automated evidence, not Microsoft Excel no-repair inspection;
that manual check remains unperformed. Developer authorization is distinct from
whole-spec cross-team adoption.


## Historical records (superseded status statements below)

Stage 5 is **incomplete and uncommitted** (2026-10-30). The draft `color_styles.py` and reader provenance additions cover explicit/row/column/default styles, base/apply flags, concrete RGB/ARGB, workbook theme/system lastClr, Decimal HSL tint with half-up channels, explicit workbook indexed palettes, font defaults, unsupported patterns/rich/table overlays, and luminance math. Nine independent helper tests pass; total working-tree regression is 140. These are not the absent frozen vectors. The normative `phase4-policy-vectors.json` was not found even with ignored/hidden repository files included. No fallback palette is silently substituted. The draft rejects that unresolved case; this does not satisfy the full required indexed-color profile. No COLOR_CONTRAST check is registered, and stages 6–7 have not been completed. Supply the frozen pack or explicitly resolve the normative palette before continuing. Excel no-repair manual inspection is unperformed.

Current extension status (2026-10-30): five rules are active, in order ALT_TEXT, WORKSHEET_NAME, TABLE_HEADER, MERGED_CELLS, LINK_TEXT. The following two-rule readiness results are historical. New screening stages have 129 passing tests; COLOR_CONTRAST and remediation are not implemented. See AE-016–AE-019 and checker notes. No complete six-rule clean/seeded claim is made.

Current readiness: the two existing checks now include safe group traversal,
drawing ownership and whole-workbook rename classification (AE-013–AE-015).
See [the final readiness evidence](checker_readiness.md) and
[rename profile](rename_safety_profile.md). The increment history below is
retained; its earlier exclusions are not current claims of missing rename
classification. No additional active rule or editor has been introduced.

This increment is developer-authorized infrastructure for specification 2.1.0,
ruleset 2.0.0. It does not establish cross-team adoption, six-rule completion,
WCAG compliance or a whole-workbook PASS/FAIL. Source bytes are never saved or
changed. See AE-011 in [the decision log](assumptions_and_extensions.md).

## Identity and aggregation

New ALT_TEXT and WORKSHEET_NAME findings use lowercase SHA-256 of UTF-8 JSON:
`[sourceSha256,"2.0.0",ruleId,worksheet,target]`. The hash is over all original
workbook bytes; JSON uses `ensure_ascii=False`, `separators=(",", ":")`, no BOM,
newline or Unicode normalization. Preserve raw sheet spelling. File names,
timestamps, resource IDs, classification and messages are not identity inputs.
`make_phase4_finding_id` uses 2.0.0; `make_phase3_finding_id` still uses 1.0.0.
The inactive three-component ID helper is unchanged. No saved audit or fixture
snapshot is relabeled. New IDs differ from historical IDs for the same bytes.

The future execution order is ALT_TEXT, WORKSHEET_NAME, TABLE_HEADER,
MERGED_CELLS, LINK_TEXT, COLOR_CONTRAST. **Only the first two are registered and
executed**; the remaining names reserve order and have no success/empty stubs.
The existing provisional table check is not enabled. Existing detector scopes,
classifications and prose were unchanged in the original foundation. Later
readiness increments gate classifications on ownership/reference safety.
The original common-foundation
increment retained cNvPr fallback targets; the subsequent, separately authorized
AE-012 update now uses owning object paths for missing/duplicate DrawingML IDs.
Unique `#id=` targets and ruleset 2.0.0 remain unchanged. Rename classification
was outside those increments and is now covered by AE-015. Historical snapshots
and audit results are not rewritten.

`finalize_findings` sorts findings by `(ruleId, worksheet, target)` in Unicode
code-point order, independently of execution order. It never deduplicates
finding records. It replaces limitations with `sorted(set(limitations))`:
only exactly equal strings collapse; whitespace and normalization variants do
not. The runner and direct ALT_TEXT results use this normalization. Finding
fields remain the existing eight strings. `Findings` stays list-compatible;
its separate `limitations` attribute still needs explicit JSON transport.
Processing exceptions propagate without successful partial/empty results.

## Sparse reading API

```python
from accessibility_checker.cell_reader import WorkbookReader

with WorkbookReader("/path/to/workbook.xlsx") as reader:
    for sheet in reader.sheets:
        if sheet.kind == "worksheet" and not sheet.external:
            cells = reader.read_cells(sheet)
            populated = [cell for cell in cells if cell.populated]
            intake_count = sum(cell.intake_nonempty for cell in cells)
```

This example selects local grids; it makes no accessibility claim about other
representations. Sheets include hidden/veryHidden tabs and chartsheets, with
original names/IDs, state, kind, relationship ID/target and resolved part.
Workbook, worksheet and shared-string paths come from actual relationships,
including nonstandard package paths. External sheets remain explicit inventory
entries with `external=True`, `part=None`; their content is never fetched.
Calling `read_cells` on an external sheet or chartsheet raises WorkbookReadError
instead of pretending that a worksheet inspection completed without cells.

`read_cells` returns a tuple sorted by numeric `(row, column)` of **stored**
cells, including formatting-only cells. It streams worksheet XML with the
existing safe parser and removes processed elements. It does not expand the
dimension/used-range rectangle. Memory includes stored cell records, row/address
tracking and resolved shared strings; constant memory/performance is not claimed.
The existing two checks do not use this reader yet, avoiding unnecessary new
dependencies on cell interpretation in their execution paths.

## Cell contract

Each CellData holds `reference`, numeric `row`/`column`, original OOXML
`data_type` (default `n`), resolved `value`, `raw_value`, optional `formula` and
raw optional `style_id`. It is a reading record, not a finding or shared DTO.

- `s` resolves the stored index through the shared-string relationship;
  `inlineStr` resolves its `is` body. Direct `t` and rich `r/t` text are joined
  in document order. `rPh` and `phoneticPr` do not contribute. Run formatting is
  not interpreted; future color checks must inspect it before assessing rich
  text rendering. Unknown body wrappers raise instead of becoming empty text.
- Strings are not stripped, casefolded or normalized. XML parsing/character
  references follow XML rules; no additional Excel escape interpretation is
  introduced.
- Numeric values are Decimal, avoiding binary float rounding; booleans are
  bool. `e`, `str` and `d` values remain strings (error codes, cached text,
  raw ISO date text). Numeric/date display formatting is not rendered.
  The original `v` text is retained independently as `raw_value`.
- Formula contains the original `f` text and attributes, including empty shared
  formula references. `has_formula` tests existence, not whether text/cache is
  nonempty. No formula, shared formula expansion or external data is evaluated.
  `cached_value` is the decoded stored value for formula cells, otherwise None.
  `has_cached_value` means a `v` element exists, including an empty one:
  absent `v` gives raw_value None; `<v/>` gives raw_value `""`. Empty numeric
  caches decode to None; this is not a calculated result.
- `intake_nonempty`: formula exists, nonempty raw saved value exists, or
  inline body is nonempty. Numeric 0 and boolean false count; formatting-only
  cells do not. A shared-string index `0` is a nonempty saved value even if the
  resolved string is empty. This is separate from populated text semantics.
- `populated`: formula exists even with no cache; other strings must contain
  something outside the exact Unicode White_Space set; 0 and false count.
  The reused set in `phase3_policy.py` is U+0009–000D, 0020, 0085, 00A0, 1680,
  2000–200A, 2028, 2029, 202F, 205F, 3000. U+200B and U+001C–001F are excluded.

## Coordinates and failures

`cell_position` returns numeric `(row, column)` and `cell_reference` emits
uppercase A1 without `$`/sheet qualifiers, bounded by A1:XFD1048576.
Lowercase columns and leading-zero row spellings canonicalize; duplicate
canonical addresses still fail. `canonical_range` always emits both endpoints
(a single cell becomes A1:A1). Reversed rectangles, absolute/qualified or
out-of-bounds references fail rather than being silently repaired.
`range_sort_key` is `(firstRow, firstColumn, lastRow, lastColumn)`.

An omitted row `r` follows the previous stored row, starting at 1. An omitted
cell `r` follows the previous stored column in its owning row, starting at A.
Explicit cell row must match its owning row. Duplicate row declarations,
duplicate cell addresses, misplaced grid elements and inferred overflow raise
CoordinateError (a ValueError subclass). Out-of-order explicit rows/cells are
read by their coordinates then sorted numerically; they are not reordered
before inferring subsequent omitted addresses.

Missing/ambiguous relationships, unsafe internal targets, invalid shared-string
indices, malformed typed values and unsupported string/type representations
fail explicitly (WorkbookReadError, KeyError for missing entries/attributes,
or parser/ZIP exceptions). DTDs/entities/external XML resources are rejected by
the existing explicit safe-parser settings. Failures never become empty success.
This module does not implement whole-package ZIP/intake validation, resource
ceilings, HTTP status mapping, style inheritance, rendered values or individual
accessibility screening.

## Verification and remaining work

On 2026-10-29 the fresh baseline was 61 passing tests. The common-foundation
increment passes 82 tests with `.venv/bin/python -m unittest discover -s tests -q`
on Python 3.14.0, using the installed pinned dependencies without additions.
Tests cover the three supplied independent ID vectors, historical identity,
execution/result order, exact limitation normalization, duplicate finding
retention, coordinate inference/errors, sparse huge dimensions, shared/inline/
rich/phonetic text, formula/cache distinctions, 0/false, exact whitespace,
hidden/chartsheet inventory, source byte preservation and the complete fixture.
The saved 1.0.0 regression snapshot is unchanged: test code independently
applies only new IDs and limitation normalization when comparing new outputs.

The later target-only increment passes 85 tests (19 image-checker tests), using
object paths for missing/duplicate IDs as recorded in AE-012. It does not change
the reader or the foundation's original 82-test verification record above.

Current verification is 106 passing tests; see `checker_readiness.md`.
Table/merge/link/color checks, reference rewriting,
remediation, HTTP/storage/UI and six-rule integration remain unimplemented in
this increment. Excel UI validation, exhaustive unsupported-format handling,
minimum-Python-version execution and performance benchmarks remain unverified.
