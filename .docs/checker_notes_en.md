# Accessibility Checker Notes — Phase 3

## Implementation basis and limits

The current local implementation incorporates four files from Gustavo commit
`bda038354c4ec1d65178edc44b0a1d1d13ca4e5b`, at the developer's request.
[The shared suite guide](team12-shared-test-suite-guide.md), Section 5
(manifest 1.4.0, ruleset/profile 1.0.0, source revision `66d588c`), remains a
reference. On 2026-10-18, the developer confirmed that these changes align
with the pod implementation and were mutually agreed. This agreement covers
the imported chartsheet scope, review/limitations/location representations,
and runner behavior described below; it does not establish full verification.

## Usage and returned results

Use Python 3.10+ and the standard library. Input is an already validated,
readable local `.xlsx`; the original file is never modified or saved.

```python
from accessibility_checker.runner import check_workbook

findings = check_workbook("/path/to/workbook.xlsx")
for finding in findings:
    print(finding)
print(findings.limitations)
```

The runner explicitly calls worksheet names, then ALT_TEXT, computing the
source SHA-256 once. Each checker still opens the workbook independently.
Results are sorted by `(ruleId, worksheet, target)` in Unicode code-point order.
Actual read/XML/relationship failures propagate without a successful partial
result. Recognized unsupported representations instead produce manual reviews.

`check_workbook` and `check_image_alt_text` return `accessibility_checker.results.Findings`,
a `list` subclass with a separate `limitations: list[str]` attribute.
`check_worksheet_names` returns an ordinary list. All findings retain eight
string fields: `findingId`, `ruleId`, `category`, `worksheet`, `target`,
`classification`, `message`, `recommendation`. Current limitation strings use
`<worksheet>: <target>: <reason>`. This is the mutually agreed representation used to align with the pod
implementation; end-to-end transport still needs verification.

**Serialization:** `json.dumps(findings)` serializes only list entries.
Consumers must explicitly transfer `findings.limitations` to their report or
HTTP response; copying/sorting as an ordinary list also loses that attribute.
HTTP integration is outside this change. No findings is not an overall PASS.

Direct imports remain available:

```python
from accessibility_checker.checks.worksheet_names import check_worksheet_names
from accessibility_checker.checks.image_alt_text import check_image_alt_text
```

Direct calls compute their own digest unless `source_sha256` is provided.

## WORKSHEET_NAME — 2.4.2 Page Titled

Related criterion: **2.4.6 Headings and Labels**. Both worksheets and chartsheet
tabs, including hidden/veryHidden, are inspected in the imported code.

- Trim leading/trailing characters in the exact White_Space set below only.
- Fully match case-insensitive ASCII `Sheet` plus ASCII digits representing a
  positive number. Preserve original spelling; do not remove internal spaces.
- `Sheet1`, `sheet2`, `Sheet01`, and whitespace-surrounded `Sheet3` trigger.
  `Sheet0`, `Sheet`, `Sheet 1`, numeric-only names, and non-ASCII substitutes do not.
- Rule/category: `WORKSHEET_NAME`; classification: `REQUIRES_USER_INPUT`.
- Target: actual relationship-resolved sheet part plus `#sheetId=<stored-id>`.

No name generation, renaming, or meaning/content evaluation occurs. External
sheet relationships are not fetched; the name checker uses their stored target
for location construction, as in the agreed imported implementation.

## ALT_TEXT — 1.1.1 Non-text Content

Standard DrawingML pictures, shapes, connectors, chart graphicFrames, and grouped
children on worksheets and chartsheets are inspected, including hidden tabs.
Accessibility `cNvPr/@title` and `@descr` are both required for non-decorative
objects. Either/both missing, empty, or White_Space-only produces one
`REQUIRES_USER_INPUT` finding identifying the missing fields. Visible chart
titles, captions, object names, and filenames do not substitute. Existing text
quality is not evaluated; no text is generated or written.

A native `adec:decorative` marker with `val="1"` or `"true"` produces one
`MANUAL_REVIEW` finding, even with complete text. `0`/`false` is not decorative.
Decorative groups receive a review and limitation; children are still checked
individually, without inheriting the designation. Rule/category:
`ALT_TEXT` / `NON_TEXT_CONTENT`.

Relationship-resolved targets use actual parts plus `#id=<stored-object-id>`.
Missing/duplicate IDs receive review findings with `#xml=` locations, rather
than invented IDs. Paths start at `/root[1]` and use one-based counts of siblings
with the same local name, ignoring namespaces, for example:
`xl/drawings/drawing90.xml#xml=/wsDr[1]/twoCellAnchor[2]/pic[1]`.
These path conventions are part of the mutually agreed pod alignment.

Recognized unsupported/ambiguous objects receive `MANUAL_REVIEW` and a separate
limitation while other findings are retained: unknown objects/anchors,
compatibility wrappers, ambiguous nonvisual/decorative metadata, nonstandard
chart frames, external object references, VML/background/control/embedded
objects, and potential cell-image/IMAGE-formula representations. Wrapper content
is disclosed rather than automatically selected. VML shapes are located
individually where available. External content is never fetched.

Rich-data/cell-image package parts receive workbook-level reviews using
`worksheet="__WORKBOOK__"` and `<part>#xml=/`; that sentinel can collide with a
real sheet name. Rich-data/value metadata and IMAGE-formula detection are
conservative, not proof of an image. Coverage of every representation is not
guaranteed; unsupported content is not certified as passed.

## Whitespace, identity, and inactive checkers

`phase3_policy.py` explicitly defines Unicode White_Space: U+0009–000D, 0020,
0085, 00A0, 1680, 2000–200A, 2028, 2029, 202F, 205F, 3000. U+200B and
U+001C–001F are excluded. No argument-free `strip()` substitution is used.

Shared identity utilities hash original source bytes and then compact UTF-8 JSON:
`[sourceSha256,"1.0.0",ruleId,originalWorksheetName,target]`, with
`ensure_ascii=False`, `separators=(",", ":")`. The resulting ID is lowercase
SHA-256, with no Unicode normalization, BOM, newline, randomness, or timestamp.
Stable wording is preserved for repeated input.

Workbook Title (**2.4.2**) and table headers (**1.3.1 Info and Relationships**)
remain callable but inactive in the Phase 3 runner. Their behavior and legacy
three-argument ID helper are unchanged.

## Verification and remaining checks

On 2026-10-18, `.venv/bin/python -m unittest discover -s tests -q` passed
**46 tests**. Updated tests cover chartsheet inclusion, exact XML locations,
review-plus-limitation results, preservation of other findings, grouped children,
decorative groups, external references, wrappers, runner propagation, list
serialization, isolation of limitation lists, stable IDs, and unchanged bytes.
The existing Title/table tests also pass.

Fixtures are synthetic ZIP/XML metadata, not complete Excel-created workbooks.
No new real-Excel or shared HTTP suite verification was performed. XML 1.0
prohibits some listed control characters; their policy-set membership is tested,
but Excel escaped-string handling remains unverified. VML, rich-data, and all
unsupported variants are not exhaustively tested.

The imported behavior is mutually agreed; remaining work is verification,
including real-Excel inputs and end-to-end transport of limitations by HTTP
consumers. Earlier approval-pending statements for this import are superseded
by the 2026-10-18 confirmation. See **AE-008** in [the assumptions log](assumptions_and_extensions.md).
