# Accessibility Checker Notes — Phase 4 Common Foundation

Performance (2026-11-16, AE-022 worker): B c 5/5 succeeds; A c 5/5 timeout; A/B d 5/5 JSON MemoryError. Report-array lower bounds exceed 64 MiB for c/d.

Current status (2026-11-15): the checker now matches the deployed Gustavo-branch engine (AE-021); the developer treats that branch as canonical. Ruleset 2.0.0 and the six-rule order are unchanged. Behavior changes:

- **LINK_TEXT:** every HYPERLINK-formula finding targets its indexed cell element (`<part>#xml=/worksheet[1]/sheetData[1]/row[n]/c[m]`). Screened literal formulas previously used `#cell=`; their finding IDs change. Simple text-cell links keep `#cell=`.
- **TABLE_HEADER:** a candidate becomes MANUAL_REVIEW when in-cell image/rich-data (`vm`) metadata overlaps it, or when a drawing anchor overlaps it or cannot be proven disjoint. When the reason is in-cell metadata, a limitation is recorded.
- **WORKSHEET_NAME rename inventory:** `invertIfNegative`, the `horzOverflow`, `vertOverflow` and `rtlCol` attributes, and numeric-only `cx`/`cy` drawing extensions are known non-reference content.

Verification: `tests/test_deployment_regressions.py` (5 tests, using the deployed fixtures in `tests/fixtures/deployment/`) and the full suite of 155 tests pass. Whether this resolves the Team 12 rename mismatch is unverified. No Excel UI evidence exists. Statements below that describe formula-link `#cell=` targets are historical.

Current verified status: all six screening rules run in contract order under corrected pack 2.1.1 (specification 2.1.0, ruleset 2.0.0; suite target 2.1.1, no executable manifest added). Eleven helper tests, three color-check tests, three dedicated six-rule integration tests and all 150 regression tests pass. Dependency, whitespace and seven pack hash checks pass. Old fixture/snapshot bytes remain historical; new complete six-rule clean/seeded inputs have independent tuples/IDs, five-repeat and source-preservation checks. No remediation/API/tester implementation or Excel manual no-repair verification is claimed. Historical pending/unregistered statements below describe earlier stages, not current status.

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

Update: the developer supplied `phase4-policy-vectors.json`. Its 64-color palette matches openpyxl 3.1.5 `COLOR_INDEX`; whitespace, identity and label vectors match. Stage 5 remains blocked by two tint vectors contradicting §7.7 half-up rounding: 336699 at -0.5 gives exact channels (25.5,51,76.5) → 1A334D, but the file says 19334D; +0.5 gives (140.25,178.5,216.75) → 8CB3D9, but says 8CB2D9. Confirmed independently with Fraction arithmetic. Contrast vectors agree within floating-point precision. The supplied file is unchanged. All 140 existing tests pass; this does not mean all supplied vectors pass. No commit/push or stage 6/7 work.

Stage 5 is **incomplete and uncommitted** (2026-10-30). The draft `color_styles.py` and reader provenance additions cover explicit/row/column/default styles, base/apply flags, concrete RGB/ARGB, workbook theme/system lastClr, Decimal HSL tint with half-up channels, explicit workbook indexed palettes, font defaults, unsupported patterns/rich/table overlays, and luminance math. Nine independent helper tests pass; total working-tree regression is 140. These are not the absent frozen vectors. The normative `phase4-policy-vectors.json` was not found even with ignored/hidden repository files included. No fallback palette is silently substituted. The draft rejects that unresolved case; this does not satisfy the full required indexed-color profile. No COLOR_CONTRAST check is registered, and stages 6–7 have not been completed. Supply the frozen pack or explicitly resolve the normative palette before continuing. Excel no-repair manual inspection is unperformed.

Section 11 safety follow-up: detected hyperlink label issues in signed packages are manual; a descriptive link does not acquire a new finding merely because the package is signed. Ten link tests pass. Current regression: 140 passing (including nine incomplete/uncommitted color-helper tests).

Stage 4 review follow-up: foreign/wrapped hyperlink representations are manual at their actual indexed element locations; local-name matches alone cannot select a supported namespace. Formula recognition also preserves spaced function syntax. Nine LINK_TEXT tests pass; the current working tree passes 139 tests including nine uncommitted color-helper tests. Stage 5 remains incomplete pending normative fallback-palette data.

Stage 4: LINK_TEXT is active after merges. It screens resolved cell labels and literal HYPERLINK/_xlfn.HYPERLINK calls using the finite vocabulary and exact whitespace policy. Unsupported formula/range/competing/rich/merged/shared-owner representations are manual with XML targets and limitations; no destinations are visited. Drawing links have explicit manual-review disclosures. Eight link tests and all 129 tests pass. The runner now executes five rules; COLOR_CONTRAST remains unimplemented. Earlier stage records below are historical. No remediation/editor is implemented.

Stage 3: TABLE_HEADER now includes sparse four-neighbor components outside formal tables and is registered in runner before MERGED_CELLS. Dense safe rectangles ask for first-row confirmation; sparse/unsafe candidates are manual. Single-cell/row/column exclusions are disclosed once per audit. Historical two-rule tests explicitly isolate that historical execution profile; saved fixture bytes and expectations remain unchanged. Eleven table tests and all 121 tests pass. LINK_TEXT and COLOR_CONTRAST remain pending.

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

## Performance measurement — REQ-15 / AC-18 preparation (2026-11-15)

This is checker-only, local and synthetic. It is not AC-18 acceptance evidence: the hosted five-run measurement belongs to the system/tester side. There is no WCAG criterion; the measurement covers all six rules together. Profile compositions and decision status are recorded in AE-022.

**Commands**

```
.venv/bin/python -m scripts.perf_workbooks --out .perf/workbooks            # profiles a-d, prints SHA256
.venv/bin/python -m scripts.perf_harness --workbook X.xlsx --runs 5 \
    [--rlimit-as] [--per-rule] [--cprofile] [--timeout 60] [--output .perf/results/x.json]
.venv/bin/python -m scripts.perf_harness --generate --profile c --runs 5   # generate, then measure
CHECKER_PERF_FULL=1 .venv/bin/python -m unittest tests.test_perf_tools     # opt-in full check
```

- Each run is a fresh child process.
- Engine time is `perf_counter` around `check_workbook`. Child wall time is `time.monotonic` in the parent.
- Peak RSS comes from `os.wait4`, so it is recorded even for a crashed or killed child.
- `--rlimit-as` sets 384 MiB `RLIMIT_AS` after the child's imports, like the deployed worker (Linux only).
- `--per-rule` calls each checker in its own child; the runner is not modified.
- Run comparison uses SHA256 over the ordered tuples, findingIds and limitations, plus a full digest.
- Queue time is `null`, because there is no queue locally.
- Normal `unittest discover` runs only small-size tests; it adds about 6 s.

**Measured** (Python 3.14.4, i7-1360P on WSL2, sequential runs, otherwise idle machine):

| Profile (250,000 cells) | Engine, 5 runs | Peak RSS | 384 MiB + 60 s kill | Findings identical |
|---|---|---|---|---|
| a: 1 sheet numeric | 24.3–28.5 s | 176.6 MiB | 5/5 ok (23.5–24.8 s) | yes |
| b: 50 sheets numeric | 24.8–25.8 s | 37.5 MiB | 5/5 ok (23.3–24.0 s) | yes |
| c: mixed, 10 sheets | **66.4–77.9 s** | 83.8 MiB | **5/5 timeout** | yes (unlimited runs) |
| d: one styled table | 23.8–28.9 s | 338.6 MiB | 5/5 ok (338.5 MiB) | yes |

**Bottlenecks**

Profile c, per rule (clean single run, 67.1 s in total):

| Rule | Time | What dominates |
|---|---|---|
| MERGED_CELLS | 31.1 s | each merge × each populated cell; `contains` → `range_sort_key` re-parses the range string about 7.2M times |
| COLOR_CONTRAST | 12.1 s | |
| LINK_TEXT | 10.3 s | pairwise hyperlink `overlaps` |
| TABLE_HEADER | 7.5 s | |
| WORKSHEET_NAME | 3.8 s | rename preflight |
| ALT_TEXT | 2.2 s | |

Profile a, per rule: COLOR_CONTRAST 9.8 s (exact Fraction `tinted` math per cell), TABLE_HEADER 6.5 s, LINK_TEXT 4.1 s.

Every rule re-opens the package and re-streams each sheet. `worksheet_features` is called separately for each feature, and `read_cells` runs about 4 times per sheet.

Memory peaks while full cell tuples are held (TABLE_HEADER/LINK_TEXT: about 160–176 MiB for one 250k-cell sheet) and while findings accumulate. In profile d, COLOR_CONTRAST holds 250,000 findings plus 250,000 limitation strings (337 MiB).

**Historical improvement options (2026-11-15; items 1–2 implemented below)**

1. **Cache the parsed rectangle and cell positions** (`lru_cache` on `range_sort_key`/`cell_position`, or pre-parse merges to integer bounds). This is the smallest change: the functions are pure, so findings should be unchanged. It mainly helps MERGED_CELLS, LINK_TEXT and COLOR_CONTRAST. The cache uses bounded extra memory.
2. **Rewrite MERGED_CELLS as a single pass over the cells**, using numeric merge bounds or a row index. This would remove the M×N cost. It must keep finding order and IDs exact; verify with the fixtures and these fingerprints.
3. **Fix LINK_TEXT's pairwise overlap test** with pre-parsed bounds or a sweep. Hyperlink-dense sheets are not measured yet, and the cost there is quadratic.
4. **Memoize COLOR_CONTRAST style resolution** for each distinct style input.
5. **Share sheet reads and feature scans across rules for each sheet.** This is a larger cross-module change. Caching all cells for every sheet would increase memory; caching one sheet at a time would not.
6. **Profile-d memory:** the number of findings is a behavior/contract matter. Compacting limitation text needs pod agreement. Streaming serialization in the worker, or a different memory bound, is a deployment decision.

**Unverified**

- Python 3.13 and production hardware.
- The full service_worker child, which also builds review items and JSON. A one-off local emulation for profile d hit MemoryError at 370 MiB in `json.dumps`; profile c produced 38.3 MB JSON.
- Hosted P5-PERFORMANCE runs, tester-owned boundary fixtures, hyperlink-dense workbooks, and the Excel UI.
- An earlier exploratory pass was distorted by concurrent work; it is not used.

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
exhaustively tested. Performance was not benchmarked at that time (see the 2026-11-15 performance section).

Decision status and remaining limits are recorded in
[the assumptions log](assumptions_and_extensions.md), especially **AE-008–AE-015**.

### Stage 1 executed (2026-11-16)

| Profile / limit | Before engine s / RSS MiB / ok | Stage 1 engine s / RSS MiB / ok | Baseline fingerprint |
|---|---|---|---|
| a / unlimited | 24.3–28.5 / 176.6 / 5/5 | 51.7–53.7 / 176.7 / 5/5 | exact |
| a / rlimit384_t60 | 23.5–24.8 / 176.7 / 5/5 | 22.4–23.8 / 176.7 / 5/5 | exact |
| b / unlimited | 24.8–25.8 / 37.5 / 5/5 | 51.0–52.2 / 93.9 / 5/5 | exact |
| b / rlimit384_t60 | 23.3–24.0 / 37.5 / 5/5 | 21.6–22.6 / 37.4 / 5/5 | exact |
| c / unlimited | 66.4–77.9 / 83.8 / 5/5 | 54.0–72.3 / 93.9 / 5/5 | exact |
| c / rlimit384_t60 | N/A (timeout) / 67.9 / 0/5 | 28.3–29.7 / 84.9 / 5/5 | exact |
| d / unlimited | 23.8–28.9 / 338.6 / 5/5 | 21.3–31.4 / 340.4 / 5/5 | exact |
| d / rlimit384_t60 | 22.7–24.8 / 338.5 / 5/5 | 19.6–20.7 / 339.9 / 5/5 | exact |

Per-rule seconds (one independent child per rule and mode):

| Rule | c before | c unlimited | c limited | d before | d unlimited | d limited |
|---|---|---|---|---|---|---|
| ALT_TEXT | 2.24 | 3.95 | 2.16 | 2.31 | 2.32 | 2.21 |
| WORKSHEET_NAME | 3.82 | 6.88 | 3.79 | 0.00 | 0.00 | 0.00 |
| TABLE_HEADER | 7.45 | 12.83 | 7.15 | 8.29 | 7.74 | 7.25 |
| MERGED_CELLS | 31.14 | 5.74 | 3.14 | 0.65 | 0.71 | 0.65 |
| LINK_TEXT | 10.34 | 8.83 | 4.74 | 4.99 | 5.33 | 4.83 |
| COLOR_CONTRAST | 12.09 | 15.89 | 8.65 | 6.58 | 6.16 | 5.48 |

Stage 1 uses a 4,096-entry LRU only on pure range_sort_key (immutable tuples;
exceptions are not retained). A local tracemalloc probe of 4,096 distinct valid
rectangles retained 1,111,556 bytes (about 1.06 MiB, 0.28% of 384 MiB; not a
universal bound on arbitrary input-string sizes). Avoiding cell_position and
canonical_range caches limits retained strings and per-cell cache churn.
Caller-side parsing was an alternative but would touch several rules.
MERGED_CELLS (1.3.1 Info and Relationships, partial) now builds sorted populated
row/column indexes, bisects rows and columns and never expands rectangles.
It streams cells without retaining full Cell objects. Conflict precedence,
single-cell handling and append order remain unchanged. Merge/merge overlap
remains quadratic; populated-row search can still visit many rows.

Executed sequentially with no concurrent tests/cProfile: regenerated a–d SHA256
matched every baseline; all 40 successful runs matched every baseline run's
complete fingerprint, including counts and ordered full digest. Per-rule
fingerprints also match the earlier clean c/d measurements. Files:
.perf/results/stage1_{unlimited,rlimit384_t60}_{a,b,c,d}.json.
The interrupted d fragment is excluded; d was restarted for five complete runs.
The unlimited a–c pass before the interruption was markedly slower than the
resumed runs; the cause is unverified, so speed ratios are not controlled
comparisons. Its RSS includes the generator parent's inherited high-water mark
(b/c floor 93.9 MiB); the resumed measurements use existing files without
generation. These values must not be interpreted as cache memory growth.

The limited c pass meets the local target: 5/5, 28.33–29.73 s, 84.9 MiB peak;
engine headroom 30.27 s, RSS headroom 299.1 MiB. RLIMIT_AS limits virtual memory,
so RSS subtraction is not guaranteed allocation headroom. Limited d has 44.1
MiB RSS headroom; its service_worker JSON problem is unchanged.
Unlimited c still exceeded 60 s in 3/5 runs; there is no environment-independent
performance guarantee. Largest measured c candidates are COLOR_CONTRAST style
resolution and TABLE_HEADER, followed by LINK_TEXT; sharing reads or changing
these algorithms needs separate authorization. LINK_TEXT overlap and merge
overlap remain quadratic for dense declarations.

Verification: 169 unittest tests, OK, skipped=1 (166 existing unchanged plus
3 new tests). tests/test_stage1_optimization.py covers bounded-cache hits,
uncached invalid-input exceptions and legacy contains-scan equivalence across
interior/boundary/outside, empty/single/overlapping/huge merges and multiple
sheets, including findings order and limitations. No dependencies added.
Ruff is unavailable; whitespace and changed-Python line length checked.
Unverified: production Python 3.13, hardware, full service_worker child,
hosted AC-18 acceptance, hyperlink-dense sheets, sheets with very many merges,
and Excel UI. Ruleset remains 2.0.0; no shared requirement approval is inferred.

### Stage 1 repeat measurement (2026-11-16)

Developer-requested repeat, unchanged implementation and ruleset 2.0.0.
Regenerated inputs in a separate process, verified SHA256 against all four
original baselines, then measured existing files in a new parent. No generator
high-water RSS inheritance this time. All measurements ran sequentially without
concurrent tests or cProfile. All 40 runs succeeded and their entire
fingerprints (including counts and order) exactly match every original baseline
run. All c/d per-rule fingerprints also match the original clean measurements.
Results: .perf/results/stage1_remeasure_{unlimited,rlimit384_t60}_{a,b,c,d}.json;
comparison: .perf/results/stage1_remeasure_comparison.md. Prior results remain
historical; none were overwritten. This repeat supersedes the earlier pass for
current local performance assessment, but does not explain its slowdown.

Limited c: time headroom 29.43 s; RSS difference
299.7 MiB. RSS difference is not virtual-memory
allocation headroom. Both unlimited and limited c now finish under 60 s on
all five runs. No production acceptance claim: Python 3.13, production hardware,
full service_worker child, hyperlink-dense sheets, very many merge declarations,
hosted AC-18 and Excel UI remain unverified. COLOR_CONTRAST and TABLE_HEADER
remain the largest measured c costs; quadratic hyperlink/merge overlap and d's
JSON memory issue are unchanged. No code or test changes for this repeat;
the earlier 169-test result (skip 1) is unchanged and was not rerun.

| Profile / limit | Before: seconds / RSS MiB / ok | Remeasured: seconds / RSS MiB / ok | Fingerprint |
|---|---|---|---|
| a / unlimited | 24.26–28.48 / 176.6 / 5/5 | 22.75–24.74 / 176.6 / 5/5 | exact |
| a / rlimit384_t60 | 23.53–24.76 / 176.7 / 5/5 | 22.49–22.95 / 176.6 / 5/5 | exact |
| b / unlimited | 24.82–25.81 / 37.5 / 5/5 | 23.63–25.54 / 37.4 / 5/5 | exact |
| b / rlimit384_t60 | 23.27–23.99 / 37.5 / 5/5 | 22.76–23.44 / 37.4 / 5/5 | exact |
| c / unlimited | 66.36–77.89 / 83.8 / 5/5 | 29.22–29.88 / 85.1 / 5/5 | exact |
| c / rlimit384_t60 | timeout / 67.9 / 0/5 | 29.56–30.57 / 84.3 / 5/5 | exact |
| d / unlimited | 23.77–28.91 / 338.6 / 5/5 | 20.41–20.93 / 338.6 / 5/5 | exact |
| d / rlimit384_t60 | 22.72–24.75 / 338.5 / 5/5 | 20.41–20.88 / 338.7 / 5/5 | exact |

Per-rule seconds / ルール別秒（各1回）:

| Rule | c before | c unlimited | c limited | d before | d unlimited | d limited |
|---|---|---|---|---|---|---|
| ALT_TEXT | 2.24 | 2.19 | 2.30 | 2.31 | 2.23 | 2.21 |
| WORKSHEET_NAME | 3.82 | 3.69 | 3.80 | 0.00 | 0.00 | 0.00 |
| TABLE_HEADER | 7.45 | 7.17 | 7.15 | 8.29 | 7.27 | 7.33 |
| MERGED_CELLS | 31.14 | 3.15 | 3.19 | 0.65 | 0.65 | 0.66 |
| LINK_TEXT | 10.34 | 4.85 | 4.77 | 4.99 | 4.97 | 4.99 |
| COLOR_CONTRAST | 12.09 | 8.78 | 8.72 | 6.58 | 5.33 | 5.54 |

### Real production-worker path measurement (2026-11-16, AE-022)

Executed locally with Python 3.14.4, no new dependencies, no checker/worker edits.
Read-only detached origin/Gustavo worktree at c880566; A imports its checker,
B imports f94330f checker through an explicit sys.path/PYTHONPATH bootstrap.
Import paths were verified separately. Both execute the unchanged real
service_worker.py main through runpy; the worker sets 384 MiB RLIMIT_AS itself.
Fresh child per run; monotonic elapsed includes start/import/items/JSON/stdout;
os.wait4 peak RSS; 60 s timeout. stdout captured to a file, not a pipe, avoiding
parent capture-memory cost; thus parent json.loads/DB/HTTP memory is excluded.
Inputs from .perf/workbooks match all original SHA256. Sequential execution,
no concurrent tests/cProfile/generation. No workbook generation in measurement parent.
Size definition: UTF-8 default json.dumps separators, ensure_ascii=False.
stdout includes worker envelope and print newline; audit size is only the
{findings, limitations} object, not the entire audit HTTP response.

Results: A a/b 5/5 success; A c 5/5 timeout inside check_workbook; A/B d each
5/5 MemoryError, exit 1, no stdout. B a/b/c 5/5 success. Every successful
regular-run fingerprint exactly matches every original baseline run, including
full digest and classification counts. Failed runs have no fingerprint and
are NOT counted as matches or valid <=64 MiB responses.
A c's failure prevents validating its worker findings under production limits.

The earlier one-off d approximation is CONFIRMED by the real worker:
check_workbook and items creation complete, final json.dumps fails while
serializing findings, before stdout writing. Final bounded stage diagnostics
are worker_diag_final_{A,B}_d_bounded.json; neither reached json.dumps:done.
Corrected c diagnostic shows check_workbook:start without completion before
timeout. Initial diagnostic json.dumps event markers were intercepted by
checker-internal JSON calls, so those markers are NOT used as final-serialization
evidence. Their successful outputs and size/fingerprint measurements remain
valid. Diagnostic RSS after a large parent parse can inherit high-water marks;
use the ordinary 40-run RSS and fresh-parent final diagnostics for memory evidence.

Additional unlimited d diagnostic (one per version, NOT production acceptance)
finishes and fingerprints match baseline: 250,000 findings/limitations/items,
220,278,049 stdout bytes (~210.1 MiB), 155,277,911 audit bytes (~148.1 MiB).
Fresh-parent unlimited diagnostic RSS is about 762 MiB.
B c has 44,123 findings/items, 40,034 limitations, 38,316,575 stdout bytes
(~36.5 MiB), 26,849,642 audit bytes (~25.6 MiB).

Report projection, derived from actual phase4_jobs.report fields:
{findings, unresolvedFindings, manualReviewItems, limitations}. This excludes
metadata and is a lower bound, not a DB/HTTP measurement. It is 68,891,505 bytes
for c (~65.7 MiB) and 393,555,838 for d (~375.3 MiB), exceeding 64 MiB
(67,108,864 bytes) before metadata. Manual-review arrays repeat findings.
Audit portions for a/b/c fit; d does not even without worker items.

Impact: B fixes c's worker timeout, but worker success does not establish report
size acceptance. d cannot currently publish a successful worker result under
384 MiB; the parent observes failure rather than usable JSON. Raising memory
alone would not fix response-size limits. Report duplication makes c exceed
64 MiB in the measured projection. No claim about actual endpoint enforcement.

UNAPPROVED / POD COORDINATION ONLY, not implemented:
- Stream worker JSON: reduces transient whole-string memory, but findings/items
  and parent capture/loads/DB memory remain; does not reduce byte size.
- Aggregate limitations or change finding/output granularity: reduces memory and
  bytes, but changes shared output evidence/contracts and requires pod approval.
- Review memory limit: preserves output format but raises concurrent-host risk;
  does not solve 64 MiB.
- Remove repeated report arrays, paginate or change report delivery: reduces
  responses but changes shared API/schema and needs pod coordination.

No code/test changes; prior 169-test run (skip 1) remains applicable and was not
rerun. git diff --check executed. No commit/push. Production Python 3.13,
production hardware, DB payload persistence and actual HTTP audit/report
responses remain unverified; this is not hosted AC-18 acceptance.
Raw evidence: .perf/results/worker_20261116.json; detailed tables:
.perf/results/worker_20261116_tables.md; wrappers under .perf/ (gitignored).

| Version | Profile | Run | Status / code | Seconds | RSS MiB | stdout bytes | audit bytes | F/L/items | 64 MiB stdout/audit | Fingerprint |
|---|---|---|---|---|---|---|---|---|---|---|
| A | a | 1 | ok / 0 | 22.78 | 180.1 | 1037 | 646 | 1/2/1 | yes/yes | exact |
| A | a | 2 | ok / 0 | 23.54 | 178.8 | 1037 | 646 | 1/2/1 | yes/yes | exact |
| A | a | 3 | ok / 0 | 28.58 | 178.6 | 1037 | 646 | 1/2/1 | yes/yes | exact |
| A | a | 4 | ok / 0 | 25.83 | 178.7 | 1037 | 646 | 1/2/1 | yes/yes | exact |
| A | a | 5 | ok / 0 | 24.69 | 178.6 | 1037 | 646 | 1/2/1 | yes/yes | exact |
| A | b | 1 | ok / 0 | 24.91 | 39.2 | 40705 | 27917 | 50/51/50 | yes/yes | exact |
| A | b | 2 | ok / 0 | 24.58 | 39.1 | 40705 | 27917 | 50/51/50 | yes/yes | exact |
| A | b | 3 | ok / 0 | 25.04 | 39.2 | 40705 | 27917 | 50/51/50 | yes/yes | exact |
| A | b | 4 | ok / 0 | 24.71 | 39.1 | 40705 | 27917 | 50/51/50 | yes/yes | exact |
| A | b | 5 | ok / 0 | 24.97 | 39.3 | 40705 | 27917 | 50/51/50 | yes/yes | exact |
| A | c | 1 | timeout / -9 | 60.01 | 64.7 | 0 | N/A | N/A | N/A (no result) | unavailable |
| A | c | 2 | timeout / -9 | 60.00 | 64.6 | 0 | N/A | N/A | N/A (no result) | unavailable |
| A | c | 3 | timeout / -9 | 60.00 | 64.5 | 0 | N/A | N/A | N/A (no result) | unavailable |
| A | c | 4 | timeout / -9 | 60.00 | 67.4 | 0 | N/A | N/A | N/A (no result) | unavailable |
| A | c | 5 | timeout / -9 | 60.00 | 66.4 | 0 | N/A | N/A | N/A (no result) | unavailable |
| A | d | 1 | failed MemoryError / 1 | 24.27 | 373.2 | 0 | N/A | N/A | N/A (no result) | unavailable |
| A | d | 2 | failed MemoryError / 1 | 24.23 | 373.0 | 0 | N/A | N/A | N/A (no result) | unavailable |
| A | d | 3 | failed MemoryError / 1 | 24.34 | 373.3 | 0 | N/A | N/A | N/A (no result) | unavailable |
| A | d | 4 | failed MemoryError / 1 | 24.72 | 373.4 | 0 | N/A | N/A | N/A (no result) | unavailable |
| A | d | 5 | failed MemoryError / 1 | 24.91 | 373.0 | 0 | N/A | N/A | N/A (no result) | unavailable |
| B | a | 1 | ok / 0 | 24.13 | 178.8 | 1037 | 646 | 1/2/1 | yes/yes | exact |
| B | a | 2 | ok / 0 | 24.93 | 178.7 | 1037 | 646 | 1/2/1 | yes/yes | exact |
| B | a | 3 | ok / 0 | 24.00 | 178.8 | 1037 | 646 | 1/2/1 | yes/yes | exact |
| B | a | 4 | ok / 0 | 24.11 | 178.8 | 1037 | 646 | 1/2/1 | yes/yes | exact |
| B | a | 5 | ok / 0 | 23.10 | 178.7 | 1037 | 646 | 1/2/1 | yes/yes | exact |
| B | b | 1 | ok / 0 | 23.18 | 39.1 | 40705 | 27917 | 50/51/50 | yes/yes | exact |
| B | b | 2 | ok / 0 | 23.03 | 39.2 | 40705 | 27917 | 50/51/50 | yes/yes | exact |
| B | b | 3 | ok / 0 | 24.24 | 39.3 | 40705 | 27917 | 50/51/50 | yes/yes | exact |
| B | b | 4 | ok / 0 | 24.21 | 39.5 | 40705 | 27917 | 50/51/50 | yes/yes | exact |
| B | b | 5 | ok / 0 | 24.68 | 39.3 | 40705 | 27917 | 50/51/50 | yes/yes | exact |
| B | c | 1 | ok / 0 | 36.74 | 170.8 | 38316575 | 26849642 | 44123/40034/44123 | yes/yes | exact |
| B | c | 2 | ok / 0 | 34.49 | 170.7 | 38316575 | 26849642 | 44123/40034/44123 | yes/yes | exact |
| B | c | 3 | ok / 0 | 34.44 | 171.3 | 38316575 | 26849642 | 44123/40034/44123 | yes/yes | exact |
| B | c | 4 | ok / 0 | 34.98 | 171.1 | 38316575 | 26849642 | 44123/40034/44123 | yes/yes | exact |
| B | c | 5 | ok / 0 | 34.96 | 170.8 | 38316575 | 26849642 | 44123/40034/44123 | yes/yes | exact |
| B | d | 1 | failed MemoryError / 1 | 21.99 | 373.2 | 0 | N/A | N/A | N/A (no result) | unavailable |
| B | d | 2 | failed MemoryError / 1 | 21.79 | 373.5 | 0 | N/A | N/A | N/A (no result) | unavailable |
| B | d | 3 | failed MemoryError / 1 | 21.90 | 373.4 | 0 | N/A | N/A | N/A (no result) | unavailable |
| B | d | 4 | failed MemoryError / 1 | 21.92 | 373.0 | 0 | N/A | N/A | N/A (no result) | unavailable |
| B | d | 5 | failed MemoryError / 1 | 21.98 | 373.4 | 0 | N/A | N/A | N/A (no result) | unavailable |

| Diagnostic | stdout bytes | audit bytes | report arrays bytes | findings/limitations/items | 64 MiB stdout/audit/report | fingerprint |
|---|---|---|---|---|---|---|
| A/d/unlimited | 220278049 | 155277911 | 393555838 | 250000/250000/250000 | no/no/no | exact |
| B/d/unlimited | 220278049 | 155277911 | 393555838 | 250000/250000/250000 | no/no/no | exact |
| B/c/bounded | 38316575 | 26849642 | 68891505 | 44123/40034/44123 | yes/yes/no | exact |

## Finding text review preparation (2026-11-16, AE-023)

[Finding text inventory](finding_text_inventory.md) records the six active rules,
source templates and limitation reasons, observed examples, length analysis and
unapproved improvement proposals. scripts/export_finding_texts.py exports actual
fixture output deterministically; tests/test_finding_texts.py adds 3 tests.
Executed: 172 unittest tests OK, skipped=1. No >500 message/recommendation found;
limitations can contain unbounded metadata. Human review remains open, all prose
unchanged, no Pod approval of improvements. See AE-023 for scope and evidence.
