# Accessibility Checker Notes — Phase 3

## Current decisions and usage

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

The runner explicitly calls worksheet names, then ALT_TEXT. It computes the
source SHA-256 once; each checker opens the workbook independently. Results
are sorted by `(ruleId, worksheet, target)` in Unicode code-point order.
Read/XML/relationship failures propagate without a successful partial result.
Recognized unsupported representations instead produce manual reviews.

`check_workbook` and `check_image_alt_text` return `results.Findings`, a
`list[dict[str, str]]` subclass with `limitations: list[str]`.
`check_worksheet_names` returns an ordinary list. Each finding has eight string
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

Phase 4 is a future compatibility reference: its ruleset 2.0.0, six active
rules, object-element targets for missing/duplicate IDs, new table targets and
limitation sorting/deduplication are not adopted. Current ruleset is 1.0.0,
with the existing cNvPr targets and limitation order preserved.

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
- Rule/category: `WORKSHEET_NAME`; classification: `REQUIRES_USER_INPUT`.
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

A native `adec:decorative` marker with `val="1"` or `"true"` produces
`MANUAL_REVIEW`, even with complete text; `0`/`false` is not decorative.
Decorative groups receive a review and limitation while children are checked
individually without inheriting the designation.
Rule/category: `ALT_TEXT` / `NON_TEXT_CONTENT`.

Targets use actual drawing parts plus `#id=<stored-object-id>`. Relationships
are followed rather than inferred from filenames. Missing/duplicate IDs receive
review targets pointing to **cNvPr**, for example:

```text
xl/drawings/drawing90.xml#xml=/wsDr[1]/twoCellAnchor[2]/pic[1]/nvPicPr[1]/cNvPr[1]
```

XML paths start at `/root[1]` and count siblings of the same local name from one,
ignoring namespaces. Other unsupported fallback targets identify the relevant
object or XML element. Changing a missing/duplicate-ID target from its former
parent-object location changes the affected findingId, even for identical source
bytes; the identity recipe, ruleset, and ordinary `#id=` targets are unchanged.

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
`[sourceSha256,"1.0.0",ruleId,originalWorksheetName,target]`, with
`ensure_ascii=False`, `separators=(",", ":")`. Source SHA-256 hashes original
bytes. No Unicode normalization, BOM, newline, randomness, or timestamp is added.
Messages/recommendations are stable. Unsupported-case diagnostic text describes
manual-review reasons rather than claiming that agreed policies are pending.

Workbook Title (**2.4.2**) and table headers (**1.3.1 Info and Relationships**)
remain callable but inactive in the runner. Their detection and legacy ID helper
are unchanged; see the assumptions log for their provisional values.

## Verification and limits

On 2026-10-29, `.venv/bin/python -m unittest discover -s tests -q` passed
**61 tests** on Python 3.14.0, following a fresh **48-test** pre-migration run.
Coverage includes the background-only/no-relationships case, 10,000-row
grid/IMAGE path, and exact missing/duplicate-ID cNvPr targets. Existing tests
cover names, hidden/chart tabs, supported objects/groups, reviews/limitations,
runner behavior, stable identity, source preservation, and inactive checkers.

The original synthetic ZIP/XML fixtures are unchanged. A complete generated
workbook is now included with pre-migration regression snapshots; see
`tests/fixtures/README.md` and `tests/test_library_migration.py`. Exact output,
limitations, determinism and source bytes match. Tests also cover model
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
[the assumptions log](assumptions_and_extensions.md), especially **AE-008/AE-009/AE-010**.
