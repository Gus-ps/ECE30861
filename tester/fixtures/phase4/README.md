# Team 12 Phase 4 fixtures (ruleset 2.0.0)

Fixtures for shared specification 2.1.0, with hand-authored six-rule expectations in
`expectations.json` (Team 9's pack format plus the record fields of spec §15.2:
`http_status`, `limitation_facts`, `corrections`, `review`, `excel_open`). This pack is
separate from the Phase 3 pack in `../shared/`; Phase 3 fixtures are not valid Phase 4
oracles (for example, Phase 3 `clean.xlsx` has a blue header fill and an unstructured cost
table, which are COLOR_CONTRAST and TABLE_HEADER findings under ruleset 2.0.0).

| File | SHA256 | Expected result |
| --- | --- | --- |
| `clean_all_six.xlsx` | `216a3e157b63888c855a699ca00b4acb712d614b9abf4079a4dfc7b9b9ecfbcd` | 202, then `AUDIT_COMPLETE`, no findings, no limitations |
| `seeded_all_six.xlsx` | `90ad5e877e933f60466ceb1fb1b685386fa41b356b3ac0fd1ebfb17a26eaac32` | 202, then `REMEDIATION_AVAILABLE`, 9 findings, one limitation fact |
| `alt_supported.xlsx` | `c7d5716f10dbc930f94b0d2d097b9dda69ffcf515c5cc85970498b68093e691c` | 202, then `REMEDIATION_AVAILABLE`, 5 ALT_TEXT findings |
| `rename_references.xlsx` | `81f528ede4f9ce11e4980cf46841dea3911841c9899acd6dc04e26d16a174194` | 202, then `REMEDIATION_AVAILABLE`, 1 WORKSHEET_NAME finding |
| `link_supported.xlsx` | `66583d64645641d3060e972ed0531afe8cbc9a66997ed13997d9e1b3b0d4e9e4` | 202, then `REMEDIATION_AVAILABLE`, 2 LINK_TEXT findings |
| `header_range.xlsx` | `de6d5676ce94da75872da2f8ecf57540d3e6ebfa9511ad452f4756a982cd09c7` | 202, then `REMEDIATION_AVAILABLE`, 1 TABLE_HEADER finding |
| `header_disabled_table.xlsx` | `b9677afe084e7d65b375c9f0e239b377cb54dda778a3913e75e1621374d17cd3` | 202, then `REMEDIATION_AVAILABLE`, 1 TABLE_HEADER finding |

**Status: not reviewed, not opened in Excel.** Spec §15.2 requires review by two members of
Team 9 (fixture hashes, all six rules, targets, classifications, statuses, correction effects
and allowed preservation differences). Record their names, date and decisions in each entry's
`review`, and the Excel-open result in `excel_open`.

## How they were made and checked

- Built by `scripts/build_phase4_fixtures.py` (drawing, chart and ZIP helpers shared with
  the Phase 3 builder); `--check` verifies the committed bytes.
- Expectations were written from the definitions below before any check ran. Then:
  ALT_TEXT and WORKSHEET_NAME rows agree with `tester/suite/pod_rules.py`; the other four
  rules are re-derived from the package XML by `tests/test_phase4_fixtures.py` (W3C contrast,
  verified against the spec's contrast vectors; four-neighbour components; populated merges;
  the §7.6 label vocabulary, verified against the spec's label vectors). Those checks are
  not a full implementation of the rules.
- Colour: every style has an explicit font colour and a solid white fill, so no cell relies
  on the "missing fill is white, missing font is black" assumption (which would add a
  limitation), and only the seeded cells are nonneutral or low contrast.

## `clean_all_six.xlsx`

| Sheet (sheetId, part) | Item | Why no finding |
| --- | --- | --- |
| Budget (1, `sheet1.xml`) | formal table 1 `BudgetItems`, A1:B4, header Item / Amount | header row on, distinct plain labels matching the column names; every populated cell is inside it |
| Budget | Picture 1 (id 2), Rectangle 2 (id 3), Chart 3 (id 4) in `drawing1.xml` | each has a nonblank title and description |
| Sources (2, `sheet2.xml`) | formal table 2 `Sources`, A1:B2 | as above |
| Sources | A2 links to `https://example.edu/team12/budget-guidance` as "Team 12 budget guidance" | descriptive label |
| both | all cells black (or bold black) on solid white | neutral, 21:1 |

No merges, no table style overlay, no single-cell or one-row components outside tables, so
the expected limitations array is empty.

## `seeded_all_six.xlsx`

| Sheet (sheetId, part) | Item | Expected finding |
| --- | --- | --- |
| Sheet1 (1, `sheet1.xml`) | sheet name | WORKSHEET_NAME, REQUIRES_USER_INPUT (rename is safe: see below) |
| Sheet1 | A1:C4, Item / Q1 / Q2 and three rows, outside any table | TABLE_HEADER `#range=A1:C4`, REQUIRES_USER_INPUT (dense, distinct plain labels, no merge or overlap) |
| Sheet1 | E1:F1 merged, "Notes" in E1 | MERGED_CELLS `#merge=E1:F1`, MANUAL_REVIEW |
| Sheet1 | A7 "click here" linking externally | LINK_TEXT `#cell=A7`, REQUIRES_USER_INPUT (single inline-string cell, no formula, no merge) |
| Sheet1 | A9 "Overdue" in red FF0000 on white (3.9985:1) | COLOR_CONTRAST `#cell=A9`, MANUAL_REVIEW (nonneutral and low contrast: one finding) |
| Sheet1 | A11 "Draft" in grey 999999 on white (2.849:1) | COLOR_CONTRAST `#cell=A11`, MANUAL_REVIEW (low-contrast grayscale) |
| Sheet1 | Picture 1 (id 2), title "Logo", no description | ALT_TEXT, REQUIRES_USER_INPUT |
| Sheet1 | Picture 2 (id 3), native decorative marker | ALT_TEXT, MANUAL_REVIEW |
| Sheet1 | Chart 3 (id 4), both fields | none |
| Summary (2, `sheet2.xml`) | formal table 1 `QuarterTotals`, A1:B3, `headerRowCount="0"`, first row Item / Total matching the column names | TABLE_HEADER `xl/tables/table1.xml#tableId=1`, REQUIRES_USER_INPUT (safe to switch the header on) |
| Summary | B2:B3 `=Sheet1!B2+Sheet1!C2`, `=Sheet1!B3+Sheet1!C3` with cached values | none (inside the table; plain references a rename can rewrite) |

**Limitation fact:** E1, A7, A9 and A11 are populated single-cell components, which spec §7.4
says are not inferred tables and must be disclosed once. Wording is not compared.

**Rename safety:** no 3D, external-workbook, INDIRECT/EVALUATE, shared/array/dynamic formula,
HYPERLINK formula, pivot or query references, so renaming Sheet1 is a supported correction.
References a rename must rewrite: the two Summary formulas and the chart series
`'Sheet1'!$B$1`, `'Sheet1'!$A$2:$A$4`, `'Sheet1'!$B$2:$B$4`.

**Correction targets** (`corrections` in the entry, each with its APPLY value): alt text for
id 2 (Team logo / Team 12 logo placeholder.); rename of Sheet1 to "Quarterly costs"; the A7
label "Team 12 budget guidance" (an inline string; there is no shared-string table); a new
table over A1:C4, which must be table 2 at `xl/tables/table2.xml` named `A11yTable2` with
worksheet relationship `rId3`; and switching table 1's header on. All five together pass the
comparator in the tests.

Expected findings in contract order (all ruleset 2.0.0):

| ruleId | worksheet | target | classification | findingId |
| --- | --- | --- | --- | --- |
| ALT_TEXT | Sheet1 | `xl/drawings/drawing1.xml#id=2` | REQUIRES_USER_INPUT | `315c47173f8eea2bd0744ed64eb5a55c36b809b034cc08e13fc980aa5c3676c9` |
| ALT_TEXT | Sheet1 | `xl/drawings/drawing1.xml#id=3` | MANUAL_REVIEW | `6e507ac40d6cddd88f831de990766be8977a0fa5a2ef376ba5b4941c86a345d6` |
| COLOR_CONTRAST | Sheet1 | `xl/worksheets/sheet1.xml#cell=A11` | MANUAL_REVIEW | `3caa82c3c63f93b128d3e047bcf6986fdf4855365e80f0cb9959432c74127be6` |
| COLOR_CONTRAST | Sheet1 | `xl/worksheets/sheet1.xml#cell=A9` | MANUAL_REVIEW | `bfd410e8f721902939a5923a64db5c84a44041a3cdd6555faef45ec2fb068e3c` |
| LINK_TEXT | Sheet1 | `xl/worksheets/sheet1.xml#cell=A7` | REQUIRES_USER_INPUT | `69af603363553d15d73a99886f18b12c64922a87d08037ad9c80f73ceeb2df50` |
| MERGED_CELLS | Sheet1 | `xl/worksheets/sheet1.xml#merge=E1:F1` | MANUAL_REVIEW | `047c43cecd8bbaade11b69162a7dac7d9cef3ce63c6d7be6333d2432ed516d08` |
| TABLE_HEADER | Sheet1 | `xl/worksheets/sheet1.xml#range=A1:C4` | REQUIRES_USER_INPUT | `d757f6c4d4cba826b4e23fc1d81985b13b37668cb726dc77a958ee67b8de96dc` |
| TABLE_HEADER | Summary | `xl/tables/table1.xml#tableId=1` | REQUIRES_USER_INPUT | `9f2bb7131ea534c3337a8ae7e5009dc358c71f85ab2b8a5aa631e2b531d6a97d` |
| WORKSHEET_NAME | Sheet1 | `xl/worksheets/sheet1.xml#sheetId=1` | REQUIRES_USER_INPUT | `f858d34c6e1144e468539c1b3d9bc21aec5f44850f72a952b8ba9549f4290a8b` |

`#cell=A11` sorts before `#cell=A9` because ordering is by code point, not by row number.

## Correction fixtures

Each is clean under all six rules except for its correction targets, so its findings are
exactly the targets, all REQUIRES_USER_INPUT, with no limitations. Every entry's
`corrections` gives each target's exact APPLY `value` and the expected `effect`.
`tests/test_phase4_fixtures.py` applies each effect to the source as plain string edits and
requires `tester/suite/comparator.py` to find no unexplained difference, and to reject the
unedited source. That check found and fixed a comparator bug: a header change that has to
create a sheet's relationships part used to crash it.

### `alt_supported.xlsx`

Budget (sheetId 1) holds table 1 (A1:B4) and `drawing1.xml`, with one of each eligible object
type missing alt text, plus a complete group that must stay byte-identical.

| Object (id) | Before | Approved value (title / description) | findingId |
| --- | --- | --- | --- |
| Picture 1 (2) | title "Logo", no description | Team logo / Team 12 logo placeholder. | `74fe61ba14297a3b2e95c0caed1e4e326ed231baf9519da1b36a1ea1d5c87f3a` |
| Chart 2 (3), graphic frame | neither | Costs by item / Column chart: rent $1,200, travel $300, supplies $200. | `5920b698b70faff77193887bd0f634d41529abcc33a18c8f725e8f7f05b1f651` |
| Rectangle 3 (4) | empty title, description present | Budget note / the existing description, approved unchanged | `621f117e2e2248dd669d3f595b21884d7137d0b951724e92b3c3311c72416c01` |
| Straight Arrow Connector 4 (5), `cxnSp` | neither | Arrow to rent / Arrow pointing from the note to the rent row. | `f0956a804569fa5b6e207babacddd81fb622721892d2830ac9f81877ee5f2630` |
| TextBox 5 (6), `sp txBox="1"` | title "Instructions", no description | Instructions / "Text box explaining that amounts are in US dollars. " (trailing space kept) | `c0e2763488785c4b3ef4da58dc55e005ef9cfe0a77d0f135425d295b4232873c` |
| Group 6 (7) with Picture 7 (8), Rectangle 8 (9) | complete | none: must not change | |

### `rename_references.xlsx`

Sheet1 (sheetId 1) is renamed to `Q1 Bob's Costs`; finding WORKSHEET_NAME at
`xl/worksheets/sheet1.xml#sheetId=1`, findingId
`9e0cd998b55afc33b64ad78ad191ebc98289148c782e24a36cd1dc3a5905cbe0`. Every rewritten
reference becomes `'Q1 Bob''s Costs'!` (quoted, apostrophe doubled).

| Where | Before | After |
| --- | --- | --- |
| `xl/workbook.xml` sheet name | Sheet1 | Q1 Bob's Costs |
| defined name Totals (workbook) | `Sheet1!$B$2:$B$4` | `'Q1 Bob''s Costs'!$B$2:$B$4` |
| defined name LocalRent (Summary, `localSheetId` 1) | `Sheet1!$B$2` | `'Q1 Bob''s Costs'!$B$2` |
| Summary B2 | `SUM(Sheet1!B2:B4)` | `SUM('Q1 Bob''s Costs'!B2:B4)` |
| Summary B3 (quoted name; apostrophe name) | `'Sheet1'!B2+'Bob''s Notes'!B2` | `'Q1 Bob''s Costs'!B2+'Bob''s Notes'!B2` |
| Summary B4 (similar name; absolute ref) | `'Sheet1 (old)'!B2+Sheet1!$B$3` | `'Sheet1 (old)'!B2+'Q1 Bob''s Costs'!$B$3` |
| Summary B5 (string literal) | `"Sheet1!B2 is rent"` | unchanged |
| Summary A6 (plain text) | Sheet1 | unchanged |
| Summary B2:B4 conditional format (bold only, no colour) | `Sheet1!$B$2>1000` | `'Q1 Bob''s Costs'!$B$2>1000` |
| Summary D2 data validation | `Sheet1!$A$2:$A$4` | `'Q1 Bob''s Costs'!$A$2:$A$4` |
| Summary A7 internal link location | `Sheet1!A1` | `'Q1 Bob''s Costs'!A1` |
| `xl/charts/chart1.xml` series | `'Sheet1'!$B$1`, `$A$2:$A$4`, `$B$2:$B$4` | `'Q1 Bob''s Costs'!` on all three |

Cached values, Bob's Notes, Sheet1 (old) and all four table parts stay unchanged. No 3D,
external, INDIRECT, shared or HYPERLINK-formula references, so the rename is supported.

### `link_supported.xlsx`

Resources (sheetId 1) holds table 1 (A1:B4). A2 and B2 share string 0 "click here"; only A2
is a link.

| Cell | Before | Approved value | Effect | findingId |
| --- | --- | --- | --- | --- |
| A2 | shared string "click here", `display="click here"` | Team 12 budget guidance | inline string; `display` updated; `sharedStrings.xml` untouched, so B2 still shows "click here" | `a55e39ce7ebe21b3a59ad871798e579ec22fd114c6e413694179f21724c33f94` |
| A3 | inline "here", no `display` | =Board minutes 2026 | inline string text (no formula, no leading apostrophe); `display` may be added | `130bbfbcb57c7dfd41162e148489ade206b6ab955991d9ccb1a600e6760208e9` |
| A4 | "Annual accessibility report" | none | descriptive, unflagged | |

### `header_range.xlsx`

Costs (sheetId 1) has no relationships part and a dense A1:D4 block (Item / Q1 / Q2 / Total,
D2:D4 formulas `=B+C` with cached values). Reference (sheetId 2) holds table 1. Finding
TABLE_HEADER at `xl/worksheets/sheet1.xml#range=A1:D4`, findingId
`564f4fc3685384e1ea20818fc33b1230352adf39f54e02c407ec31881d021946`.

Expected effect: new `xl/tables/table2.xml` (lowest unused part and table ID 2), named
`A11yTable2_1` because the workbook defined name `A11yTable2` already takes `A11yTable2`; ref
A1:D4; columns Item, Q1, Q2, Total; no filter, style or totals row. A new
`xl/worksheets/_rels/sheet1.xml.rels` with `rId1` to it, a `tablePart` in `sheet1.xml`, and a
content-type override. Every cell, formula and cached value is unchanged.

### `header_disabled_table.xlsx`

Ledger (sheetId 1) holds table 1 (A1:C4) with `headerRowCount="0"`; its first row Item /
Amount / Running total matches the column names, and C2:C4 hold running-total formulas.
Archive (sheetId 2) holds an ordinary table 2. Finding TABLE_HEADER at
`xl/tables/table1.xml#tableId=1`, findingId
`5c5f2c2ccebe7b864ff4e933e2973c139b0ab2635f8303a9b97f80f9e4977fc1`. Expected effect:
`headerRowCount` becomes 1 (or is removed); nothing else changes.

## Still to build

`review_only`, `preservation_rich`, `unsupported_edits`, `mixed_decisions`, and Phase 4
versions of the Unicode, repeated-ID, multiple-drawing and rejected-input fixtures.
The repeated-ID expectations change under §7.1: targets name the object element
(`.../pic[1]`), every member of the duplicate group is flagged, and all are MANUAL_REVIEW.
