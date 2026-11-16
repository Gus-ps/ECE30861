# Assumptions and Extensions

Performance status (2026-11-16, AE-022 repeat): all 40 runs match baseline; c below 60 s in all five runs under both conditions. Production remains unverified.

Current verified status (2026-11-15): the deployed Gustavo-branch checker corrections are adopted (AE-021). All 155 regression tests pass. Formula-link LINK_TEXT targets and their finding IDs changed; earlier `#cell=` formula-link results below are historical.

## AE-022 — Synthetic boundary workbooks and checker-only performance measurement (2026-11-15)

- **Criterion reference:** none. This is not a WCAG check. It measures all six rules together: 1.1.1, 1.3.1, 1.4.1/1.4.3, 2.4.2 (related 2.4.6) and 2.4.4. It serves the performance requirement REQ-15 / AC-18.
- **Source/scope:** Phase 5 specification 3.0.0 §12 and §17. AC-18 requires five documented runs of supported boundary work. Each run must finish within 60 seconds or end in a controlled failure. Successful findings must be identical across runs. Queue time and execution time are reported separately, using monotonic real time. The supported bounds are 25,000,000 bytes, 50 worksheets and 250,000 nonempty cells, and the audit engine bound is 60 s. Ruleset 2.0.0 is unchanged.
  - **Not specified:** the composition of a "boundary workbook", and any engine memory bound. The 384 MiB `RLIMIT_AS` comes from the deployed worker (`origin/Gustavo` `service_worker.py`). It is not a specification value.
- **Prototype choices (not specification values):**
  - **(a)** One sheet with 25,000 × 10 numeric cells.
  - **(b)** 50 sheets, each with 500 × 10 numeric cells.
  - **(c) "Mixed realistic":** 10 sheets of 25,000 cells each. Each sheet has:
    - a bold 14 pt title merged over A1:J1, and a blank row 2;
    - a bold header row on a neutral grey fill;
    - a dense 10-column data block (2,496 rows) with these columns: unique ID string, a category from 20 repeating strings, an integer, a money-format decimal, a numeric formula `C*D` with a cached value, a score, a date serial, a status (every 20th row "Late" in a red font), a link column and a note (every 25th row on a yellow fill);
    - conditional formatting on the formula column (`cellIs` with a fill dxf) and on the score column (`colorScale`);
    - after a blank row, 29 notes rows, each merged A:J (30 merges per sheet, 300 in total).

    Link column: every 10th data row is an external hyperlink with a descriptive label (2,490 in total), each sheet has one "click here" hyperlink, and each sheet has two `HYPERLINK(...,"here")` formulas. Sheets 1 and 6 hold formal tables with `TableStyleMedium2`. The last sheet keeps the default name `Sheet10`, so the whole-workbook rename preflight runs. 25,553 unique shared strings.
  - **(d)** One sheet that is a single `TableStyleMedium2` table: header plus 24,999 rows of the same 10 columns, with no hyperlinks, merges or conditional formatting. Excel's "Format as Table" always assigns a style, which makes every populated cell a COLOR_CONTRAST manual review (table-style overlay).
  - Workbooks are written as raw OOXML with fixed ZIP timestamps and member order. The theme is openpyxl 3.1.5's bundled default theme.
- **Rationale/limits:** Profiles a and b are minimal grids. Profiles c and d are guesses at ordinary business workbooks, not human-reviewed boundary fixtures; those are owned by the tester team (`origin/Logan`). Byte determinism holds for the same Python/zlib build (verified with zlib 1.3.1), not across zlib versions. Excel UI validity of the generated packages has not been checked.
- **Local vs deployed:**
  - Python 3.14.4 locally, versus `python:3.13-slim` in production.
  - Local hardware: i7-1360P, WSL2, 16 logical CPUs, 7.6 GiB RAM. Production hardware is unknown.
  - The harness measures `check_workbook` only. It excludes intake validation, queue, HTTP, storage and service_worker's review-item and JSON-output step; that step opens a further WorkbookReader for each LINK_TEXT user-input finding.
  - Queue time is reported as `null`.
- **Approval:** developer work request only (2026-11-15). No pod approval of the profiles, and these results are not AC-18 acceptance evidence.
- **Implementation:** `scripts/perf_workbooks.py` (generator; checks the limits before and after writing and deletes an oversized output), `scripts/perf_harness.py` (fresh child per run, `os.wait4` peak RSS, optional `--rlimit-as`, `--per-rule`, `--cprofile`, findings fingerprints and run comparison), `tests/test_perf_tools.py` (10 tests plus 1 opt-in test, `CHECKER_PERF_FULL=1`). Outputs go to the gitignored `.perf/`. The runner and all rules are unchanged.
- **Verification (executed 2026-11-15, sequential, otherwise idle machine):**
  - Generator output: all four profiles are 1.14–1.66 MB with exactly 250,000 nonempty cells, and regeneration gave identical SHA256.
  - Results, 5 runs each:
    - **a:** engine 24.3–28.5 s, peak RSS 176.6 MiB.
    - **b:** 24.8–25.8 s, 37.5 MiB.
    - **c:** **66.4–77.9 s, over 60 s on every run**, 83.8 MiB.
    - **d:** 23.8–28.9 s, **338.6 MiB**.
  - With 384 MiB `RLIMIT_AS` and a 60 s kill (production conditions):
    - **a, b and d:** 5/5 ok. d's peak was 338.5 MiB, about 46 MiB below the limit.
    - **c:** **5/5 timeouts**, a controlled failure with no successful audit.
  - Every successful set had identical tuples, findingIds and limitations.
  - Profile c bottleneck (clean per-rule run, 67.1 s in total): MERGED_CELLS 31.1 s (each of 300 merge rectangles is tested against every populated cell, and `contains` re-parses the range strings each time, about 7.2M calls), COLOR_CONTRAST 12.1 s, LINK_TEXT 10.3 s (pairwise hyperlink `overlaps`), TABLE_HEADER 7.5 s, WORKSHEET_NAME rename preflight 3.8 s.
  - Across rules, each sheet's XML is streamed many times: `worksheet_features` is called per feature, and `read_cells` runs about 4 times per sheet.
  - d's memory is held by the COLOR_CONTRAST results: 250,000 findings plus 250,000 limitation strings.
  - **One-off probe (not committed):** emulating service_worker's items list and `json.dumps` for d under 384 MiB raised MemoryError (peak 370 MiB). c serialized fine (38.3 MB JSON, 119 MiB peak).
  - An earlier exploratory pass was distorted by concurrent work and is not used as evidence.
- **Unverified:** Python 3.13, production hardware, the full service_worker child process, hosted P5-PERFORMANCE runs, hyperlink-dense sheets (LINK_TEXT pairwise cost grows quadratically), and the Excel UI.
- **Status:** no optimization was made, as the work request specified. Improvement options are listed in the checker notes and need separate authorization.

- **Verification / Status update (2026-11-16):** Developer authorized stage 1 optimization; no shared requirement change or new pod approval. Earlier no-optimization status above is historical.

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

## AE-021 — Adopt deployed checker corrections from Gustavo branch (2026-11-15)

- **Source/scope:** Phase 4 specification 2.1.0 §7.6 (partial 2.4.4 Link Purpose (In Context)): supported simple text-cell links use the cell target, while unsupported representations use indexed XML targets, and formula links are never edited. §7.4/§8.6 (partial 1.3.1 Info and Relationships) and §8.5 rename safety (partial 2.4.2 Page Titled; related 2.4.6 Headings and Labels). The specification does not list every OOXML attribute that is safe for the rename inventory, or say how drawings near a header candidate should be judged. Phase 5 specification 3.0.0 keeps ruleset 2.0.0 and the six rules unchanged.
- **Adopted behavior:** This is the deployed `origin/Gustavo` commit `c880566`, copied unchanged.
  1. Every reported HYPERLINK-formula finding uses its indexed cell-element target `#xml=/worksheet[1]/sheetData[1]/row[n]/c[m]`. This now includes screened literal formulas, which previously used `#cell=`.
  2. A TABLE_HEADER candidate becomes MANUAL_REVIEW when either of these overlaps the candidate rectangle: a cell with `vm` (in-cell image/rich-data) metadata, or a drawing anchor. A drawing anchor also counts if it is unknown, absolute, external or unparseable. Only proven disjoint one/two-cell anchors are ignored.
  3. The rename inventory treats `c:invertIfNegative`, the `horzOverflow`, `vertOverflow` and `rtlCol` attributes, and a drawing extension element with only numeric `cx`/`cy` as known non-reference content.
- **Rationale/evidence:** The deployed system is canonical, as the developer stated on 2026-11-15. Team 12 tester vectors (`origin/Logan` `formula_link_identity_vectors.json`) expect the indexed formula targets. Item 1 matches §7.6. Items 2 and 3 are prototype classification choices. They only add manual review or recognize scalar layout metadata, and generate no content. **Risk:** finding IDs for formula links differ from earlier outputs of this branch. Earlier stored results are not rewritten. Whether item 3 resolves the outstanding Team 12 rename mismatch is unverified.
- **Approval:** The developer authorized adopting the deployed branch as canonical and dropping the old `#cell=` expectations (2026-11-15). Recorded pod adoption of these specific classification details has not been found.
- **Implementation/verification:** `checks/link_text.py`, `checks/table_headers.py` and `rename_safety.py` now match `origin/Gustavo`. `tests/test_deployment_regressions.py` (5 tests) adds the deployed fixtures `tests/fixtures/deployment/` and checks the following:
  - exact finding tuples and independently calculated IDs
  - source preservation
  - no `#cell=` target for any formula link
  - the disjoint/overlapping drawing cases, an unknown extension, and in-cell metadata

  `tests/test_link_text.py` now expects the indexed target. A temporary revert of each module made the new tests fail. The full suite (155 tests) passed on 2026-11-15. A redundant second `_formula_location` call (an extra sheet stream) is kept unchanged to match the deployed code. No Excel UI evidence exists.

Current verified status: all six screening rules run in contract order under corrected pack 2.1.1 (specification 2.1.0, ruleset 2.0.0; suite target 2.1.1, no executable manifest added). Eleven helper tests, three color-check tests, three dedicated six-rule integration tests and all 150 regression tests pass. Dependency, whitespace and seven pack hash checks pass. Old fixture/snapshot bytes remain historical; new complete six-rule clean/seeded inputs have independent tuples/IDs, five-repeat and source-preservation checks. No remediation/API/tester implementation or Excel manual no-repair verification is claimed. Historical pending/unregistered statements below describe earlier stages, not current status.

COLOR_CONTRAST is now registered, completing six-rule execution (not Phase 4/remediation acceptance). Static low contrast/color meaning combine per cell; visual conditional ranges are deduplicated and suppress static results. Unknown visual extension scope receives whole-part manual disclosure, not an invented range/ratio. Formula caches are never calculated. Three color-check tests and all 147 tests pass. Historical two-rule mocks remain explicit; five-rule fixtures now run through the current six-rule runner without rewriting their bytes or five-rule tuples. Dedicated six-rule fixtures follow.

Color foundation verified against corrected pack 2.1.1: exact Fraction HSL intermediates, final half-up channels, all supplied tint/contrast vectors, exact-half neighbors and frozen 64-color palette equality. Palette is packaged as code, independent of runtime .docs. Eleven helper tests and full 144-test regression pass. Unsupported rendering remains explicit; COLOR_CONTRAST is not yet registered. No Excel UI evidence or shared deployment claim.

Current adoption: corrected pack revision 2.1.1 resolves AE-020; implementation resumes using CORRECTIONS.md. Specification remains 2.1.0, ruleset 2.0.0, suite target 2.1.1 (no executable tester created). All seven SHA256SUMS members verified. Earlier pending statements below are historical; neither team deployment nor complete implementation is established. See [corrected pack](phase4_agent_context_pack/README.md).

## AE-020 — Tint rounding conflict; pod decision pending (2026-10-30)

- **Source/scope:** Specification 2.1.0 §7.7, partial 1.4.1 Use of Color and
  1.4.3 Contrast (Minimum), versus the developer-supplied policy vectors.
- **Current evidence:** The previously absent 64-color palette has been supplied;
  missing data is no longer the blocker. Comparison found two tint conflicts for
  base 336699. At −0.5 the vector says 19334D, but exact channels
  (25.5,51,76.5) with half-up give 1A334D. At +0.5 the vector says 8CB2D9,
  but exact channels (140.25,178.5,216.75) give 8CB3D9. Fraction arithmetic
  independently confirmed these pre-round values. Palette/whitespace/identity/
  label comparisons matched; contrast comparisons agreed within floating precision.
- **Proposal/authority:** Correct the two vector values to the half-up results,
  or explicitly revise the rounding policy. Neither alternative is approved.
  The pod's response is pending; developer implementation authorization alone
  does not establish shared adoption. No normative file/vector is changed here.
- **Implementation:** Stage 5 color helper, its tests and reader additions remain
  uncommitted/incomplete. COLOR_CONTRAST is not registered; stages 6–7 are not
  complete. No further color implementation is part of this increment.
- **Verification:** Committed baseline 131, additional five-rule integration 2,
  proposed snapshot 133; working tree with nine draft color tests 142 passing.
  These regression results do not resolve the two normative vector mismatches.
  New fixtures are generated complete XLSX packages with independent tuple/ID
  expectations; no Microsoft Excel manual no-repair evidence exists.
- **History:** Initial stage-5 investigation stopped for missing companion data.
  The developer subsequently supplied it; the blocker changed to the concrete
  rounding conflict above. Earlier absence statements are historical, not the
  current reason for waiting. See `tests/fixtures/five_rule_fixtures.md`.


## Historical records (superseded status statements below)

### Earlier AE-020 draft — historical missing-palette investigation (2026-10-30)

**Revised after developer supplied the companion file:** missing-data blocker resolved; normative conflict remains. The 64 fallback entries match installed `openpyxl.styles.colors.COLOR_INDEX` (the earlier question used the incorrect constant name COLOR_INDEXED). Whitespace, ID and label vectors match. Tint vectors for 336699 disagree with §7.7 half-up: -0.5 requires 1A334D (file 19334D), +0.5 requires 8CB3D9 (file 8CB2D9). Exact Fraction arithmetic independently yields pre-round channels (25.5,51,76.5) and (140.25,178.5,216.75). Contrast vectors agree within floating-point precision. Do not silently privilege either normative source or alter the supplied user file. Await a decision to correct the two vectors to half-up, or explicitly revise the rounding policy. All 140 existing tests pass; the direct new-vector comparison has two mismatches, not a successful complete policy test. Stage 5 remains uncommitted/incomplete; stages 6/7 remain pending. Earlier absence statements below are historical.


- Source: specification 2.1.0 §7.7, partial 1.4.1 Use of Color and 1.4.3 Contrast (Minimum). The text normatively selects indices 0–63 from `phase4-policy-vectors.json`, but the companion file is absent from this repository (including hidden/ignored-file search). Workstation theme or another implementation's palette cannot establish that frozen choice.
- Developer authorized implementing the checks, not silently replacing missing normative data. A question is pending: supply the frozen vectors, or explicitly adopt the installed openpyxl 3.1.5 COLOR_INDEXED values for this implementation. Such local authorization would remain distinct from cross-team adoption. No substitute has been adopted.
- Independent draft helper code resolves explicit workbook colors/theme/palette and the specified tint/luminance math, retains rich-run and custom-row provenance, and refuses unsupported rendering. Missing fallback indexed colors raise UnsupportedRendering; they are not reported as passing. This is a temporary unresolved profile, not completed color detection.
- Nine helper tests and full working-tree 140-test regression pass; no frozen-vector equality is claimed. Existing dependencies pass pip check, whitespace checks pass. No dependency added. Stage 5 draft code/docs remain uncommitted; COLOR_CONTRAST is unregistered. Stages 6/7, full six-rule fixtures and Microsoft Excel no-repair verification are outstanding.

## AE-019 — Finite hyperlink label screening (2026-10-30)

Section 11 follow-up: signed-package link-label defects are manual; descriptive links get no signature-only defect. Ten LINK_TEXT tests pass; full working tree: 140 passing, including nine incomplete color-helper tests.

Review follow-up: namespace checks now explicitly reject foreign/wrapped link representations as manual at their actual indexed locations. Nine link tests pass; full working-tree regression is 139, including nine tests for the separately uncommitted, incomplete color helper. This does not complete stage 5.

- Source: specification §§6, 7.1, 7.6, 8.5; partial 2.4.4 Link Purpose (In Context). Developer-authorized implementation; whole-spec team adoption and editor availability remain separate.
- Element labels use resolved cell content, not display attributes. Comparisons trim/collapse only policy White_Space, casefold, ignore one trailing ASCII .!? for the finite word list, and check raw-address prefixes. Literal one/two argument HYPERLINK calls parse commas outside strings and doubled quotes; unsupported calls are manual without evaluation. Plain URLs outside hyperlinks are ignored.
- Editable classification is limited to simple single-cell text/empty labels with unambiguous ownership. Unsupported/range/competing/merged/rich/formula representations are manual; indexed locations are based on actual XML. Drawing hyperlinks are disclosed as unperformed manual review, without fetching destinations.
- Eight focused tests, full 129-test regression pass; original bytes and historical snapshots are preserved. Runner now has five active checks. No color rule, editor, API or new dependency. Generated xlsx reader checks are not Microsoft Excel no-repair evidence.

## AE-018 — Unstructured table candidates (2026-10-30)

- Source: specification §§6, 7.4, 8.6; partial 1.3.1 Info and Relationships. Developer authorizes this increment; shared adoption is separate.
- Four-neighbor components exclude formal-table cells. Bounding boxes of at least 2×2 are candidates; density uses count versus area, never empty rectangle expansion. Only dense, plain-label, unambiguous supported candidates request first-row confirmation. Merges, overlapping filters/formal tables, shared worksheet ownership and unsupported attached features prevent that classification. Small components produce one audit-level limitation. No semantic header inference or table creation.
- TABLE_HEADER is now registered after names and before merges. Historical two-rule tests explicitly isolate their old execution profile rather than relabeling snapshots as four-rule results.
- Eleven table tests and 121 regression tests pass, including sparse/diagonal/far-away cells, body formula/0/false, exclusions and unsafe boundaries. No Excel UI/manual verification or editing is claimed.

## AE-017 — Formal-table header classification (2026-10-30)

- Source: specification §§6, 7.4, 8.3, 8.6; partial 1.3.1 Info and Relationships. Developer-authorized implementation, not whole-spec shared adoption.
- All referenced formal tables are checked; omitted header count is 1. Invalid IDs use table-root paths; duplicate physical IDs affect all members. Shared ownership prevents user-input classification. Only disabled headers with matching distinct plain first-row strings, body, consistent metadata and no known unsafe features are candidates. Formula/header/query/extension/merge/overlap/totals/reference ambiguities are manual with limitations. No edits.
- Existing historical provisional implementation moved intact to `checks/legacy_table_headers.py`; its tests and saved observations use that explicit historical import. No snapshot bytes changed. Common reader now retains shared/inline rich-text provenance.
- Seven focused tests and 117 regression tests pass. No new dependencies; no Excel UI evidence. Unstructured screening and runner registration are deferred to stage 3; TABLE_HEADER as a whole is not complete at this increment.

## AE-016 — Populated merges (2026-10-30)

- Source: specification 2.1.0 §§6, 7.5, partial 1.3.1 Info and Relationships.
- Developer explicitly authorizes the four new checks; shared adoption is separate.
- Identical canonical declarations are one target. Overlapping declarations each receive manual review and a limitation even if empty; ordinary non-conflicting empty/style-only and single-cell declarations produce no finding. No rectangle expansion or editing. External worksheets are disclosed without fetching.
- Implemented in `checks/merged_cells.py`, using the existing reader and a streaming worksheet-feature reader. `tests/test_merged_cells.py`: 4 tests; full regression: 110 passing. Original fixtures/snapshots preserved. Existing runner mock tests isolate merge execution explicitly; their synthetic root relationship now includes the required officeDocument relationship.
- Excel UI, minimum-Python execution and performance benchmarks remain unverified. No dependencies added.

Readiness stage 4 verification (2026-10-29): all 106 tests pass, including
24 ALT_TEXT, 14 rename-preflight and 2 new generated/complete-package integration
tests. No new production behavior was added in stage 4. Historical XLSX/JSON
snapshots and dependencies match task-starting commit 52274c8. See
`checker_readiness.md` for exact scope, commands and per-stage evidence.
This verifies AE-013–AE-015 without declaring an editor, six-rule completion,
whole-spec team adoption or unperformed Microsoft Excel UI validation.

## AE-015 — Whole-workbook rename classification (2026-10-29)

- **Source/approval:** Developer authorizes readiness stage 3 under 7.3/8.4/11.
  Partial `2.4.2 Page Titled`, related `2.4.6 Headings and Labels`; not whole-spec
  adoption, an editor or a new name-detection heuristic.
- **Rule:** Preserve matching, original names, targets and IDs. Classify matched
  names from the whole-workbook inventory: supported profiles yield
  REQUIRES_USER_INPUT; blockers yield MANUAL_REVIEW with deterministic limitations.
  List-compatible Findings now carries those limitations without new fields or
  arguments. Shared worksheet/drawing/table ownership is a blocker.
- **Implementation/rationale:** `rename_safety.py` uses installed Tokenizer plus
  a checked token grammar and quote-aware sheet/address/scoped-name parsing.
  Cell formulas, names, charts, validation, conditional formatting, table formulas
  and internal links are recognized. Strings remain literals. 3D/external/dynamic
  references, unsupported extensions, shared/array formulas, signed/opaque/
  pivot/cache/query/slicer structures and unknown markup are disclosed blockers.
  `part_ownership.py` now also reads actual table ownership.
- **Limits:** Tokenization is not proof of rewriting. Structured-reference
  operands, intersections, unknown functions/attribute profiles remain manual.
  Builtin catalog names plus IMAGE are recognized; INDIRECT/EVALUATE/HYPERLINK
  are not safe. `rename_safety_profile.md` records the self-contained contract.
  No rewrite, output, review context or preservation guarantee is implemented.
- **Verification:** Stage 2 baseline 90 tests. Name suite 4 pass, preflight suite
  14 pass, full suite 104 pass on Python 3.14.0/.venv. Coverage includes mandatory
  ordinary families, quotes/apostrophes/literals, manual families, other/hidden/
  chart sheets, target/ID stability and source preservation. Minimal name fixtures
  gained actual empty sheet parts; matching assertions and historical snapshots
  are unchanged. Excel UI, Python 3.10, performance and rewriting are unverified.

## AE-014 — Drawing ownership gates user-input findings (2026-10-29)

- **Source/approval:** Developer authorizes readiness stage 2 under 7.2/8.3,
  partial `1.1.1 Non-text Content`. No cross-team adoption or editor is implied.
- **Rule:** Missing alt fields on a drawing part actually referenced by multiple
  sheet definitions yield MANUAL_REVIEW with an ownership limitation, retaining
  target/ID. Complete alt fields do not acquire a new defect solely because of
  sharing. Repeated references from one owner and unreferenced relationships do
  not invent additional owners. Different sheets sharing the same worksheet
  part are distinct owners, including hidden/veryHidden/chart tabs.
- **Implementation/rationale:** `part_ownership.py` exposes sheet owners and a
  drawing-part-to-owner map, resolving actual internal relationships and scanning
  sheet drawing references without retaining grids. The preflight scans each
  distinct sheet part once; existing ALT_TEXT reading remains independent.
  External parts are never fetched. This is read-only evidence for future
  processing, not review context or an editing engine. Existing unsupported
  representations, group traversal, title/description conditions and unique/ID
  fallback locations remain intact.
- **Verification:** ALT_TEXT suite: 24 pass; full suite: 90 pass, following stage
  1's 87-test baseline. Added cases cover actual shared ownership versus repeat/
  unused references, shared sheet parts, hidden/chart tabs, field combinations,
  no invented complete-object defect, deterministic results and source bytes.
  Tests remain synthetic; Excel UI and performance are unverified.

## AE-013 — Group ambiguity must not hide safe children (2026-10-29)

- **Source/approval:** Developer authorizes readiness stage 1 under specification
  7.1/7.2, partial `1.1.1 Non-text Content`; not whole-spec team adoption.
- **Rule:** Missing/ambiguous group nonvisual properties or decorative metadata
  yield the existing parent review/limitation while directly enumerated children
  are independently inspected. Native single 0/false is not decorative; 1/true
  suppresses missing-alt for the parent only. Unknown wrappers are reviewed,
  never selected speculatively. No container missing-alt finding is introduced.
- **Rationale/implementation:** The existing NotImplementedError handler returned
  before group children were visited. It now invokes the existing namespace-aware
  direct-child visitor for grpSp only. Error handling is not otherwise widened;
  object fallback paths, IDs, source bytes and classifications are retained.
- **Verification:** Fresh baseline 85 tests. Related ALT_TEXT suite: 21 pass;
  full suite: 87 pass on Python 3.14.0 in .venv. Added parameterized cases cover
  parent property/marker ambiguity, native flags, complete/missing-alt children,
  nested groups, wrappers, exact targets and deterministic unchanged-source
  results. Fixtures are synthetic; Excel UI validation remains unperformed.

## AE-012 — Phase 4 missing/duplicate object-ID targets (2026-10-29)

- **Source/scope:** Phase 4 specification 2.1.0 Sections 7.1/7.2 and the
  developer's explicit request authorize changing only ALT_TEXT missing/duplicate
  DrawingML ID targets. Partial `1.1.1 Non-text Content`, not full coverage.
- **Rule:** Use the actual drawing part plus the existing indexed path of the
  owning pic, sp, cxnSp, graphicFrame or grpSp, including each nested child and
  every member of a duplicate-ID group. Retain unique `#id=` targets,
  MANUAL_REVIEW, category, messages and limitation reason. Location-bearing
  limitation strings use the new target. Existing 2.0.0 identity hashes that
  target; do not relabel historical results or increment the ruleset.
- **Rationale:** `inspect()` already computes this object-level `fallback`.
  Reuse it without new path calculation or changes to detection/group behavior.
  Distinct object paths preserve distinct findings and IDs.
- **Approval:** Developer authorized this exact implementation increment on
  2026-10-29. Team-wide adoption of the whole specification is not established.
  AE-009's cNvPr policy remains historical; AE-012 supersedes only the current
  missing/duplicate-ID target described in AE-009/010/011.
- **Implementation/verification:** `checks/image_alt_text.py` now passes the
  existing object-level `fallback` to review for missing/duplicate IDs.
  Fresh pre-change run: 82 tests passed. After the change, all 85 tests passed
  on Python 3.14.0 using `.venv/bin/python -m unittest discover -s tests -q`;
  the related `test_image_alt_text.py` suite passed 19 tests. Existing target
  assertions changed only for the authorized missing/duplicate-ID cases.
  Added tests cover the exact drawing1 duplicate-pic example, all five object
  kinds, nested groups/children, unique-ID targets, independently calculated
  2.0.0 IDs, repeatability, limitation reasons and unchanged source bytes.
  Historical snapshots and Phase 3 records are unchanged. New cases are
  synthetic ZIP/XML; no Excel UI validation or whole-spec adoption is claimed.

## AE-011 — Authorized Phase 4 common foundation (2026-10-29)

- **Source/approval:** Developer explicitly authorizes only versioned finding
  identity, aggregation and sparse cell-reading infrastructure for specification
  2.1.0/ruleset 2.0.0. This is not evidence of team-wide adoption or completed
  Phase 4 coverage. Partial `1.1.1 Non-text Content` and `2.4.2 Page Titled`
  (related `2.4.6 Headings and Labels`) remain the only active checks.
  Cell data will support future `1.3.1 Info and Relationships`,
  `2.4.4 Link Purpose (In Context)`, `1.4.1 Use of Color` and
  `1.4.3 Contrast (Minimum)` checks; none is added here.
- **Authorized changes:** New runs of the two active checks use ruleset 2.0.0
  identity. Preserve the Phase 3 helper, stored snapshots and inactive legacy
  helpers. Execute implemented checks in ALT_TEXT, WORKSHEET_NAME order, with
  later order reserved for TABLE_HEADER, MERGED_CELLS, LINK_TEXT, COLOR_CONTRAST.
  Sort findings, retain distinct targets and normalize only exact duplicate
  limitation strings. Exceptions remain failures. No unimplemented check is
  registered or reported as performed.
- **Reader contract:** Resolve actual internal workbook/sheet/shared-string
  relationships, preserve hidden/chart metadata, read stored cells sparsely,
  resolve body text in document order excluding phonetics, and distinguish
  formula metadata from stored cached values. Reuse the exact existing Unicode
  White_Space set for populated strings; intake uses stored values instead.
  Canonicalize bounded coordinates, infer omitted rows/columns from previous
  stored positions and fail explicitly on inconsistent/duplicate addresses.
  No formula evaluation, rewriting, findings or HTTP responses are generated.
- **Rationale/limits:** Reuse installed openpyxl coordinate conversion and
  defusedxml tree/stream parsing. Preserve raw cell values alongside typed
  values to avoid float precision loss and text normalization. The reader is
  independent of existing rules, avoiding unrelated parsing or scope changes.
  It is not a full intake validator or a six-rule audit implementation.
- **Implementation/verification:** `finding_ids.py`, `results.py`, `runner.py`
  and the two active checker call sites updated; `coordinates.py` and
  `cell_reader.py` added. Baseline 61 tests passed. After implementation,
  82 tests pass using Python 3.14.0 and the project .venv with openpyxl 3.1.5/
  defusedxml 0.7.1/et-xmlfile 2.0.0; no new dependency required.
  `test_finding_ids.py` retains the historical recipe and verifies three
  independent supplied 2.0.0 vectors. Runner/result tests cover execution vs
  result order, exact limitation normalization, duplicate record retention and
  failures. `test_cell_reader.py` covers sparse/inferred coordinates and errors,
  shared/inline/rich/phonetic text, formulas/caches, 0/false, whitespace, hidden
  and chart tabs, complete-package reading and unchanged input bytes.
  Historical snapshot bytes remain unchanged; regression comparisons independently
  apply only the authorized new identity and limitation normalization in memory.
  No new individual check, safe editor, currentValue or HTTP feature exists.
  Detailed reader fields/limits are in `phase4_common_foundation.md`. Unknown
  string wrappers raise instead of being interpreted as empty text; run/style
  rendering remains unassessed. Excel UI, Python 3.10, six-rule integration and
  performance remain unverified.

AE-010/008/009 below describe historical increments. AE-011 supersedes only
their current-version identity, execution order and limitation normalization;
their detection rules and cNvPr targets remain unchanged in this increment.

## AE-010 — Library migration with preserved Phase 3 behavior (2026-10-29)

- **Source/scope:** Developer authorizes openpyxl plus defusedxml migration,
  preserving the existing Phase 3 rules and public interfaces. Partial
  `1.1.1 Non-text Content`, `2.4.2 Page Titled` (related `2.4.6 Headings and
  Labels`), and inactive `1.3.1 Info and Relationships`. AE-004/005/008/009
  remain the behavioral reference. This is not adoption of Phase 4 policies.
- **Approval:** Developer approved the proposed library plan on 2026-10-29.
  No new shared rule, HTTP contract, or ruleset is approved by this migration.
- **Rule/design:** Parse original parts with defusedxml, explicitly forbidding
  DTDs, entity declarations and external XML resources. OOXML external
  relationships remain unfetched and receive the existing reviews. Reuse
  openpyxl's sheet, core-property and table models on already parsed elements;
  retain original lexical IDs, paths, names and table counts where needed.
  Model TypeError/ValueError/OverflowError triggers original-XML interpretation,
  not file rejection or a clean result. Other processing errors still propagate.
- **Rationale/limits:** defusedxml retains ElementTree and streaming APIs.
  lxml adds facilities not needed here and needs additional DTD rejection logic.
  Whole-workbook loading would parse unrelated features and reject existing
  minimal fixtures; model-level reuse avoids that dependency and double XML
  parsing. No cells need Excel value interpretation for the current rules:
  IMAGE formula/value-metadata screening needs raw cells and indexed locations.
  This is not an upload validator or a claim about all unexamined package parts.
  Performance, real Excel round-tripping and unsupported formats remain limited.
- **Phase 4 differences:** Keep ruleset 1.0.0, two active rules, cNvPr targets
  for missing/duplicate IDs, existing limitation ordering, and inactive legacy
  checks/IDs. Future six-rule coverage, object-element fallback targets, new
  table targets and limitation normalization are outside this increment.
- **Implementation/verification:** `safe_xml.py`, `excel_metadata.py`, four
  checker modules and pinned `requirements.txt` implemented. Baseline run on
  2026-10-29: 48 tests passed on Python 3.14.0. After migration, all 61 tests
  passed, including `tests/test_library_migration.py`. Existing tests unchanged.
  Complete-package outputs match snapshots captured before checker edits,
  including findings, limitations, IDs, text, ordering and inactive checks.
  Repeatability/source bytes, model rejection/coercion, foreign-title namespace
  isolation, original hidden
  chartsheet metadata, malformed XML/missing parts, and UTF-8/UTF-16 unsafe XML
  rejection are covered. A local workbook's four checker outputs and source
  bytes also match the baseline (zero active findings/limitations). Snapshots
  are compatibility evidence, not independent rule oracles. Full openpyxl
  workbook loading lost hidden chartsheet state in an initial integration test;
  raw ChildSheet reading preserved it, and the test now verifies the stored
  state directly. Excel UI, actual Excel escape serialization, Python 3.10,
  performance and HTTP integration remain unverified. Fixture provenance and
  limits: `tests/fixtures/README.md`.

Current decisions and verification are recorded separately. The developer
confirmed pod alignment for the specific imports in AE-008/AE-009 on 2026-10-18.
This does not automatically approve future Gustavo-branch changes or establish
full accessibility/HTTP conformance. This log preserves decision IDs while
omitting obsolete implementation descriptions.

## Superseded entries — AE-001/002/003/006/007

| Entry  | Original date | Decision history and current replacement                                                                                                                                                                    |
| ------ | ------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| AE-001 | 2026-10-16    | Prototype worksheet-name heuristics (`2.4.2 Page Titled`, related `2.4.6 Headings and Labels`), including numeric-only review and internal whitespace removal. Replaced by AE-008's current scope/matching. |
| AE-002 | 2026-10-16    | Prototype description-only inserted-picture check (`1.1.1 Non-text Content`). Replaced by AE-008's title/description and review policy.                                                                     |
| AE-003 | 2026-10-16    | Eight-field findings with provisional values and three-component IDs. Active Phase 3 identity is now AE-008; the old ID helper remains only for inactive checks.                                            |
| AE-006 | 2026-10-17    | Initial four-checker runner. Replaced by AE-008's two-checker runner and limitation aggregation.                                                                                                            |
| AE-007 | 2026-10-17    | Partial Phase 3 implementation temporarily stopped on unsupported objects while contract details were unavailable. Replaced by AE-008's agreed reviews and AE-009's streaming/targets.                      |

These initial proposals were developer-authorized prototypes, not evidence of
pod agreement at that time. REQ-03–06 / AC-03–06 establish source preservation,
issue detection, actionable findings, and human judgment; they do not alone
define the detailed heuristics. Current behavior is documented below and in
[the checker notes](checker_notes_en.md).

## AE-004 — Inactive workbook Title check (2026-10-17)

- **Source/rule:** Partial `2.4.2 Page Titled`; developer requests missing Title
  detection for valid readable `.xlsx`. Missing core properties or absent,
  empty, or whitespace-only Title yields one finding; no quality judgment.
- **Values/approval:** REQUIRES_USER_INPUT is developer-specified.
  WORKBOOK_TITLE rule/category and `__WORKBOOK__` worksheet/target remain
  developer-authorized provisional values, not confirmed shared contract values.
  The sentinel can collide with a real worksheet name; the legacy ID helper
  lacks workbook/ruleset identity. No new ID scheme or remediation is added.
- **Implementation/verification:** `checks/workbook_title.py` and
  `tests/test_workbook_title.py`; inactive in the Phase 3 runner. Eight synthetic
  tests pass in the current 48-test run. No new real-Excel verification.

## AE-005 — Inactive table-header check (2026-10-17)

- **Source/rule:** Partial `1.3.1 Info and Relationships`; developer-authorized
  detection of referenced tables with explicit headerRowCount="0" on visible
  worksheets. Hidden tabs/chartsheets and unreferenced table parts are excluded;
  omitted/nonzero counts are not flagged. Meaningful header content is unassessed.
- **Values/approval:** Rule `1.3.1-TABLE-NO-HEADER`, category TABLE_STRUCTURE,
  REQUIRES_USER_INPUT, and range target are developer-authorized settings;
  shared rule-catalog agreement remains unconfirmed. The legacy ID limitation
  applies. No header creation or file rewriting.
- **Implementation/verification:** `checks/table_headers.py` and
  `tests/test_table_headers.py`; inactive in the Phase 3 runner. Eight synthetic
  tests pass in the current run. Prior local smoke reading contained no tables;
  real-Excel missing-header detection remains unverified.

## AE-008 — Pod-aligned findings and chartsheets (2026-10-18)

- **Source/approval:** Developer confirms that the four-file import from Gustavo
  `bda038354c4ec1d65178edc44b0a1d1d13ca4e5b` aligns with the pod implementation
  under mutual agreement. Reference: shared suite guide Section 5 (manifest
  1.4.0, ruleset/profile 1.0.0). Partial `1.1.1 Non-text Content` and `2.4.2 Page
Titled`, related `2.4.6 Headings and Labels`. This approval is specific to the
  imported behavior, not unrelated legacy rules or future branch changes.
- **Rules:** Include worksheets/chartsheets and hidden tabs. Trim exact Unicode
  White_Space only at name ends; match case-insensitive ASCII Sheet plus positive
  ASCII digits. ALT_TEXT requires title and descr; native decorative objects
  receive MANUAL_REVIEW. Unsupported/ambiguous objects get review findings and
  limitation strings while other findings are retained. Decorative groups are
  reviewed and children independently assessed. External content is not fetched.
- **Results/identity:** `results.Findings` is list-compatible with separate
  `limitations`; runner combines disclosures and sorts findings. Consumers must
  explicitly transport attributes, which ordinary JSON/list serialization loses.
  IDs use raw-source SHA-256 and compact UTF-8 JSON of source/ruleset/rule/sheet/
  target. Read/XML/relationship failures still propagate. No overall PASS/FAIL.
- **Limits:** Rich-data/cell-image workbook reviews use `__WORKBOOK__` and
  `<part>#xml=/`; a real sheet name can collide with the sentinel. Detection is
  conservative and not exhaustive. No semantics, text generation, or rewriting.
- **Implementation/verification:** `checks/worksheet_names.py`,
  `checks/image_alt_text.py`, `results.py`, `runner.py`, and corresponding tests.
  Initially 46 tests passed; the current 48-test run includes AE-009. Synthetic
  tests confirm scopes, locations, stable findings, disclosure aggregation,
  serialization behavior, and source preservation. Real-Excel, exhaustive
  unsupported formats, and end-to-end HTTP transport remain unverified.

## AE-009 — Streaming, backgrounds, and cNvPr targets (2026-10-18)

- **Source/approval:** Gustavo `437b1859a1f00821391f7a6c9f737afe02938a2a`,
  partial `1.1.1 Non-text Content`. Initially imported by developer instruction;
  the developer subsequently confirmed this specific update as a formal decision.
  This replaces the earlier approval-pending status only for this update.
- **Rule/rationale:** `_sheet_objects()` streams worksheet/chartsheet XML,
  removing ordinary grid elements while retaining selected objects/relevant
  cells and exact XML paths. Background pictures produce MANUAL_REVIEW plus
  limitation before relationships are loaded, even without a relationship file.
  Missing/duplicate object IDs target cNvPr with one-based same-local-name
  sibling indexing, ignoring namespaces. Other fallback locations are unchanged.
- **Identity/limits:** Changing the target changes affected findingIds even for
  identical input bytes. Ruleset 1.0.0, digest recipe, and ordinary #id= targets
  remain unchanged. Drawing trees and selected objects are still retained;
  speed/peak-memory improvement is unmeasured, not a constant-memory guarantee.
- **Implementation/verification:** `checks/image_alt_text.py`, related tests,
  runner/result annotations, and current shared/private notes are aligned.
  Unsupported-case diagnostics now describe manual-review reasons without
  outdated pending-contract claims; classifications and detection stay unchanged.
  All 48 tests pass with `.venv/bin/python -m unittest discover -s tests -q`,
  including the upstream background-only and 10,000-row IMAGE-path cases and
  exact cNvPr locations. Earlier detailed tests are retained. Fixtures are
  synthetic; real-Excel escaped strings, HTTP transport, exhaustive unsupported
  formats, and performance remain unverified. Agreement is distinct from testing.
