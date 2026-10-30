# Accessibility Checker Notes — Phase 4 Common Foundation

Stage 2 (2026-10-30): `checks.table_headers.check_table_headers` now inspects referenced formal tables, including hidden sheets, with ruleset 2.0.0 IDs and actual table-part targets. Only proven disabled-header candidates are user-input; other defects/ownership ambiguity are manual. Rich-text origin is retained by the common reader. Unstructured screening is pending, so TABLE_HEADER is not registered in runner. The provisional detector and its original tests/snapshot remain explicitly historical in `legacy_table_headers.py`. Seven formal-table tests and all 117 tests pass.

Current increment (2026-10-30): MERGED_CELLS is now active after ALT_TEXT and WORKSHEET_NAME. It screens populated declared merges (including titles), deduplicates identical rectangles, and discloses overlapping declarations, including empty conflicts. Sparse stored cells are used; chartsheets are excluded from grid inspection. Direct call: `checks.merged_cells.check_merged_cells(path, *, source_sha256=None)`. Four focused tests and all 110 tests pass. The remaining three new rules and remediation are not implemented. Earlier two-rule evidence below is historical.

## Current decisions and usage

All four readiness increments are verified: **106 tests pass**, including
automated complete-XLSX integration (2026-10-29, Python 3.14.0). The runner still
executes only ALT_TEXT and WORKSHEET_NAME; no new rule/editor is present. See
[the readiness report](checker_readiness.md) for per-stage commits/evidence and
the remaining manual profiles. Excel UI validation remains unperformed.

Readiness stage 3 (AE-015) classifies matched names using the whole-workbook
reference inventory. Supported ordinary formulas/names/chart series/validation/
formatting/internal links remain REQUIRES_USER_INPUT; unsafe/unknown profiles
are manual with reasons. Targets and IDs are unchanged. See the self-contained
[rename profile](rename_safety_profile.md) for grammar/schema limits. No rewrite
or output preservation is claimed. Validation: 4 name tests, 14 preflight tests
and all 104 tests pass (2026-10-29).

Readiness stage 2 (AE-014) inventories actual drawing owners before checking
alt fields. Missing fields in a drawing shared by multiple sheet definitions
are manual with an ownership limitation; complete objects acquire no new defect.
Repeated references from one sheet and unused relationships do not imply shared
ownership. Hidden/chart tabs and shared worksheet parts are included. The small
read-only helper is `part_ownership.py`; no editor/currentValue is implemented.
Validation: 24 ALT_TEXT tests and all 90 tests pass (2026-10-29).

Readiness stage 1 (AE-013) preserves safe child traversal when group nonvisual
properties or decorative markers are ambiguous. The parent retains its review
and limitation; children do not inherit decorative flags. Unknown wrappers stay
manual and are not selected. No missing-alt finding is issued solely for a
container. Validation: 21 ALT_TEXT tests and all 87 tests pass (2026-10-29,
Python 3.14.0). This is developer-authorized partial 1.1.1 behavior, not a claim
of whole-spec adoption or an implemented editor.

The developer authorized the Phase 4 common foundation on 2026-10-29:
new ruleset 2.0.0 identity, deterministic aggregation and sparse cell input.
Only ALT_TEXT and WORKSHEET_NAME run. This is not six-rule completion or shared
adoption of the whole specification. See [the foundation contract](phase4_common_foundation.md)
and AE-011; the earlier decisions below still govern detector behavior.
The developer separately authorized only missing/duplicate DrawingML-ID target
alignment with specification 2.1.0 Sections 7.1/7.2 (AE-012). That increment
does not establish team-wide adoption or change the detection policy.

The pod-alignment changes imported from Gustavo `bda0383` and the subsequent
streaming/background/cNvPr-target update from
`437b1859a1f00821391f7a6c9f737afe02938a2a` are confirmed decisions, as stated by
the developer on 2026-10-18. This status applies to these specific changes,
not automatically to future changes from that branch.
[The shared suite guide](team12-shared-test-suite-guide.md), Section 5
(manifest 1.4.0, ruleset/profile 1.0.0), remains a reference. Agreement and
implementation verification are separate; full WCAG coverage is not claimed.

Use Python 3.10+ with the dependencies pinned in `requirements.txt`. Install
with `.venv/bin/python -m pip install -r requirements.txt` in the project-local
environment. Input is a valid, readable local
`.xlsx`. Original files are never modified or saved. No CLI is provided.

```python
from accessibility_checker.runner import check_workbook

findings = check_workbook("/path/to/workbook.xlsx")
for finding in findings:
    print(finding)
print(findings.limitations)
```

## Results and runner

The runner explicitly calls ALT_TEXT, then worksheet names. It computes the
source SHA-256 once; each checker opens the workbook independently. Results
are sorted by `(ruleId, worksheet, target)` in Unicode code-point order.
Read/XML/relationship failures propagate without a successful partial result.
Recognized unsupported representations instead produce manual reviews.
Both runner and direct ALT_TEXT results deduplicate exactly identical limitation
strings and sort them in Unicode code-point order. Findings are never collapsed
by aggregation. The remaining four rules have no implementation or success stub.

`check_workbook` and `check_image_alt_text` return `results.Findings`, a
`list[dict[str, str]]` subclass with `limitations: list[str]`.
`check_worksheet_names` now also returns Findings to carry rename limitations;
ordinary list consumers remain compatible. Each finding has eight string
fields: `findingId`, `ruleId`, `category`, `worksheet`, `target`, `classification`,
`message`, `recommendation`. Limitations use `<worksheet>: <target>: <reason>`.

**Consumers must preserve limitations explicitly.** `json.dumps(findings)`
serializes list entries only; ordinary list copying/sorting also loses the
attribute. HTTP/report consumers must transfer limitations separately.
This package does not implement HTTP transport or an overall PASS/FAIL.
An empty finding list is not certification of accessibility.

## Library reading and XML safety

The developer approved openpyxl + defusedxml on 2026-10-29 (AE-010).
`excel_metadata.py` reuses openpyxl 3.1.5's `ChildSheet`, `DocumentProperties`
and `Table` models on XML elements already parsed once by `safe_xml.py`.
It does not load or save an entire workbook or invoke openpyxl's XML parsers.
This avoids interpreting unrelated features merely to read a sheet name or
property and continues to support the existing minimal ZIP/XML fixtures.
The original worksheet/chart relationships, lexical sheet IDs, drawing parts
and indexed paths remain the source of locations and identity.

All checker XML tree and streaming entry points use defusedxml 0.7.1 with
`forbid_dtd=True`, `forbid_entities=True`, and `forbid_external=True` explicitly.
Unsafe XML raises a processing exception; it is not returned as a successful
partial result. XML built-in escapes such as `&amp;` remain supported.
External XML entities/DTDs are different from OOXML external relationships:
the latter are never fetched and retain existing manual-review behavior.
This safety applies to parts the checks read; the package does not implement
upload validation or assert that all other parts have been examined.

defusedxml was chosen over lxml because ElementTree-compatible objects and
`iterparse` meet the current needs with less migration work; lxml's XPath and
other facilities are unnecessary here, and disabling entity loading alone
does not reject DTD declarations. Only one safety parser is added.

Models may validate more strictly or coerce values. TypeError, ValueError and
OverflowError during model construction fall back to inspection of the same
original XML, without treating a library rejection as an invalid workbook or
a clean result. Unexpected failures propagate. Raw table counts other than
the literal `0` stay excluded, raw ranges stay unchanged, and duplicate core
Title elements retain the first-element behavior. Unknown fields remain in
raw metadata. Foreign-namespace Title elements cannot supply or replace the
Dublin Core title, even though the model matches child elements by local name.
Full `load_workbook` drops hidden chartsheet state in the tested
version; using the original `ChildSheet` definition avoids that loss.

DrawingML, alternative text, decorative flags, unsupported objects, IMAGE
formula/value-metadata screening and XML positions stay in direct OOXML
inspection. The current checks do not need cell value/shared-string resolution;
loading all cells only to look for original formulas would duplicate work.
ZIP access, hashing, JSON identity, regular expressions and runner policy remain
standard-library code. Table/Title checks remain inactive in the runner.

The common foundation now uses ruleset 2.0.0, ALT_TEXT-first execution and
limitation sorting/deduplication. A subsequent target-only update uses object
elements for missing/duplicate DrawingML IDs (AE-012). Rename classification
is implemented under AE-015; an editor, six-rule coverage and new table rules
remain absent.
`cell_reader.py` and `coordinates.py`
provide independently tested input for future checks, not additional findings;
the existing detectors have not been rewritten to use them.

Direct imports remain available from `accessibility_checker.checks.worksheet_names`
and `accessibility_checker.checks.image_alt_text`. Direct calls hash the input
unless supplied with the keyword-only `source_sha256` context.

## WORKSHEET_NAME — 2.4.2 Page Titled

Related criterion: **2.4.6 Headings and Labels**.

- Inspect worksheets and chartsheet tabs, including hidden/veryHidden.
- Trim only leading/trailing characters in the White_Space set below.
- Full-match case-insensitive ASCII `Sheet` plus ASCII digits with positive
  numeric value. Leading zeroes are allowed; preserve the original name.
- `Sheet1`, `sheet2`, `Sheet01`, and whitespace-surrounded `Sheet3` trigger.
  `Sheet0`, `Sheet`, `Sheet 1`, numeric-only names, and non-ASCII substitutes do not.
- Rule/category: `WORKSHEET_NAME`; classification: `REQUIRES_USER_INPUT` for
  supported whole-workbook rename profiles, otherwise `MANUAL_REVIEW` with
  limitations.
- Target: relationship-resolved sheet part plus `#sheetId=<stored-id>`.

No names are generated or changed; content relevance is not assessed.
External sheet content is not fetched. The name checker constructs a location
from the stored relationship target, as in the agreed implementation.

## ALT_TEXT — 1.1.1 Non-text Content

Inspect DrawingML pictures, shapes, connectors, chart graphicFrames, and grouped
children on worksheets and chartsheets, including hidden tabs. Non-decorative
objects require both accessibility `cNvPr/@title` and `@descr`. Either/both
missing, empty, or White_Space-only yields one `REQUIRES_USER_INPUT` finding
identifying the missing fields. Visible chart titles, captions, object names,
and filenames do not substitute. Text quality is not assessed or corrected.
The REQUIRES_USER_INPUT classification also requires an unambiguous single
owning sheet; shared drawing parts instead receive MANUAL_REVIEW and a limitation.

A native `adec:decorative` marker with `val="1"` or `"true"` produces
`MANUAL_REVIEW`, even with complete text; `0`/`false` is not decorative.
Decorative groups receive a review and limitation while children are checked
individually without inheriting the designation.
Rule/category: `ALT_TEXT` / `NON_TEXT_CONTENT`.

Targets use actual drawing parts plus `#id=<stored-object-id>`. Relationships
are followed rather than inferred from filenames. Missing/duplicate IDs receive
review targets pointing to the **owning drawing object**, for example:

```text
xl/drawings/drawing90.xml#xml=/wsDr[1]/twoCellAnchor[2]/pic[1]
```

XML paths start at `/root[1]` and count siblings of the same local name from one,
ignoring namespaces. Other unsupported fallback targets identify the relevant
object or XML element. Every member of a duplicate-ID group, including the
first, uses its own fallback. Nested children target themselves, not their group.
pic, sp, cxnSp, graphicFrame and grpSp reuse their existing indexed paths.
MANUAL_REVIEW, category, messages and limitation reason stay unchanged; limitation
locations follow the new target. The 2.0.0 identity recipe and unique `#id=`
locations are unchanged; affected findingIds change because their targets change.
AE-009's former cNvPr policy and historical results remain historical records;
the developer-authorized Phase 4 target policy is AE-012.

Unsupported/ambiguous representations yield `MANUAL_REVIEW` and a limitation
while retaining other findings: unknown objects/anchors, wrappers, ambiguous
properties/decorative metadata, nonstandard charts, external references,
VML/background/control/embedded objects, and potential cell-image/IMAGE formulas.
Wrapper content is disclosed rather than automatically selected. VML shapes
are located individually where available. External content is never fetched.

Rich-data/cell-image parts receive workbook reviews using `__WORKBOOK__` and
`<part>#xml=/`; that sentinel can collide with a real sheet name. Rich-data,
value metadata, and IMAGE-formula detection are conservative indicators.
Unsupported coverage is not exhaustive; unexamined content is not passed.

## Worksheet reading and backgrounds

`_sheet_objects()` uses `ElementTree.iterparse` on ZIP member streams. It keeps
selected objects/relevant cells, removes ordinary grid elements, and preserves
sibling-counted XML paths. Formula children remain until their cell is checked.
Drawing XML is still parsed as a full tree. Runtime/peak-memory improvement is
**unmeasured**; this is not a constant-memory guarantee.

A worksheet background `picture` immediately gets a manual review and limitation
at its worksheet XML location **before relationship loading**. Background-only
sheets therefore do not require a drawing relationship file for this review.
The background image's text or meaning is not automatically assessed.

## Whitespace, identity, and inactive checkers

`phase3_policy.py` explicitly defines Unicode White_Space: U+0009–000D, 0020,
0085, 00A0, 1680, 2000–200A, 2028, 2029, 202F, 205F, 3000. U+200B and
U+001C–001F are excluded; argument-free `strip()` is not a substitute.

Finding IDs are lowercase SHA-256 of compact UTF-8 JSON:
`[sourceSha256,"2.0.0",ruleId,originalWorksheetName,target]`, with
`ensure_ascii=False`, `separators=(",", ":")`. Source SHA-256 hashes original
bytes. No Unicode normalization, BOM, newline, randomness, or timestamp is added.
Messages/recommendations are stable. Unsupported-case diagnostic text describes
manual-review reasons rather than claiming that agreed policies are pending.
Historical `make_phase3_finding_id` and saved snapshots retain 1.0.0; new runs
use `make_phase4_finding_id`. Stored results are not rewritten.

Workbook Title (**2.4.2**) and table headers (**1.3.1 Info and Relationships**)
remain callable but inactive in the runner. Their detection and legacy ID helper
are unchanged; see the assumptions log for their provisional values.

## Verification and limits

On 2026-10-29, `.venv/bin/python -m unittest discover -s tests -q` passed
**106 tests** on Python 3.14.0 after all four readiness increments. Related suites
pass 24 ALT_TEXT, 14 rename-preflight and 2 integration tests. Full generated
XLSX integration covers required ordinary reference families and ownership, in
addition to synthetic XML cases. The historical target-only increment passed
85 tests (19 ALT_TEXT tests), after a fresh 82-test baseline, including drawing1
duplicate-pic example, all five supported object kinds, nested groups,
unique-ID locations, independently calculated 2.0.0 IDs, determinism and unchanged
source bytes. These added cases are synthetic ZIP/XML, not Excel UI validation.
The prior library migration passed 61 tests;
that increment's fresh pre-migration baseline was 48 tests.
Coverage includes the background-only/no-relationships case, 10,000-row
grid/IMAGE path, and exact missing/duplicate-ID object targets. Existing tests
cover names, hidden/chart tabs, supported objects/groups, reviews/limitations,
runner behavior, stable identity, source preservation, and inactive checkers.

Historical XLSX/JSON fixture bytes are unchanged. The minimal name-test builder
now supplies actual empty sheet parts for reference preflight; matching
assertions are unchanged. A complete generated
workbook is now included with pre-migration regression snapshots; see
`tests/fixtures/README.md` and `tests/test_library_migration.py`. Historical
findings match apart from the explicitly authorized new IDs and normalized
limitations; determinism and source preservation also pass. Tests cover model
rejections/coercion, malformed XML/missing parts, and DTD/entity/external-resource
rejection in tree/stream parsing with UTF-8 and UTF-16 inputs. A local existing
workbook was compared with its pre-migration snapshot: all four callable
checker results matched, with zero active findings/limitations and unchanged
bytes. This is a smoke check, not a seeded real-Excel accessibility test.
Excel UI serialization, escaped strings from Excel, and shared HTTP transport
remain unverified. Minimum-version Python 3.10 execution was not available.
Some policy controls cannot appear literally in XML 1.0; their set membership
is checked separately. VML/rich-data and all unsupported variants are not
exhaustively tested. Performance has not been benchmarked.

Decision status and remaining limits are recorded in
[the assumptions log](assumptions_and_extensions.md), especially **AE-008–AE-015**.
