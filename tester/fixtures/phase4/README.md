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

**Status: not reviewed. Every accepted fixture opened in Excel on 2026-11-01** without a repair prompt, except
`table_header_vectors`, whose expected repair is explained in its section. The rejected inputs were not opened, and
no correction output has been opened yet (the spec §13 release gate). Spec §15.2 requires review by two members of
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

## Batch 2 fixtures (added 2026-11-01)

Expected findings are hand-written in `expectations.json`; per-fixture intent is in each entry's `notes`.
Worksheet names are shown with invisible characters as code points.

| File | SHA256 | Expected result |
| --- | --- | --- |
| `mixed_decisions.xlsx` | `ccffba16223e3ded186a64189be455fffe099c095f2d93e31a8e6d2d43588ffa` | 202, then `REMEDIATION_AVAILABLE`, 10 findings, 1 limitation fact(s) |
| `review_only.xlsx` | `d542c2afa9e744485530f9fc874ef5365d7917ec54d1a6154d051b8c844ccc39` | 202, then `REVIEW_REQUIRED`, 3 findings, 1 limitation fact(s) |
| `unsupported_edits.xlsx` | `cf27357110fd3e42de442c7b35f9f9440ddb9eb2ccbfdbdf39b1ecc75e33a8d2` | 202, then `REVIEW_REQUIRED`, 7 findings, 3 limitation fact(s) |
| `preservation_rich.xlsx` | `51c85c21aaafec32c78b08d7cdef4c9e3fd9e3fe84879fedb5888c8e238ea7c6` | 202, then `REMEDIATION_AVAILABLE`, 2 findings, 1 limitation fact(s) |
| `large_preservation.xlsx` | `638cd27d42dbeda5785f2c286391eec106a52d045566b867dc72841e0b09fe1c` | 202, then `REMEDIATION_AVAILABLE`, 1 findings, 0 limitation fact(s) |
| `inactive_protection.xlsx` | `602a688e30907f5926526b153831af814945299cbbf1efa2dc0ba5e9d5845b82` | 202, then `AUDIT_COMPLETE`, 0 findings, 0 limitation fact(s) |
| `unicode.xlsx` | `96dec001e70bd7ea82a7843fde02b51a81b4de20bb41e05775070bf49ef9ee67` | 202, then `REMEDIATION_AVAILABLE`, 6 findings, 0 limitation fact(s) |
| `repeated_ids.xlsx` | `586bc55d748daa325fe3d5406dc9218dec63e296ba0fb31d0a46557c4031a13d` | 202, then `REMEDIATION_AVAILABLE`, 4 findings, 1 limitation fact(s) |
| `multiple_drawings.xlsx` | `785816d6ca4f8aff9204ed290cff1afb5e76e069625af3809964fa0d33b96bb2` | 202, then `REMEDIATION_AVAILABLE`, 4 findings, 0 limitation fact(s) |
| `corrupt.xlsx` | `9cf891ba569c9de0a6b006bca6f481c9e3c17e3eb53342691ecea9f253e2dd09` | 422, copied from `../shared/` |
| `zip_traversal.xlsx` | `b2d07b501310ca89cc38c4dfa9dae6c35451f7a53c15be0630dbe79fc3942af5` | 422, copied from `../shared/` |
| `zip_duplicate.xlsx` | `d97e27eea8d46d69d96cab1eeba004932768992dd7f2e6fcdd066d67f2f2af83` | 422, copied from `../shared/` |
| `xml_dtd.xlsx` | `0b05bf86d94eb855ab4db603a56d88822fcddaa8acbe66d7ec53ea396c187108` | 422, copied from `../shared/` |
| `macro_parts.xlsx` | `d5fb9d0fca22aaee67ae5cb387b068a5daaa73d892da62a1290a45e33a946d06` | 422, copied from `../shared/` |
| `encrypted_zip.xlsx` | `58a2d8c291c64c8184c4d86c631e1638823843dfd1bec975ec2a43e600859551` | 422, copied from `../shared/` |
| `protected_sheet.xlsx` | `1bbe7342deae053aedd301d69010aec0aa6d86cb8fbf021b1d9faefd4942ee43` | 422, copied from `../shared/` |
| `protected_structure.xlsx` | `53835c995e98201b2a097c2115ad168c211337a20fad9ddeb574ab6acd6e948d` | 422, copied from `../shared/` |

`clean` and `seeded_issues` are aliases of `clean_all_six` and `seeded_all_six` for the Phase 3-numbered cases,
which use six-rule expectations under ruleset 2.0.0 (the test plan's adaptation note).

### `mixed_decisions`

seeded_all_six plus Sheet2 (sheetId 3, sheet3.xml) with formal table 2, so two generic sheets exist for the rename conflict and duplicate-name cases. Same nine findings as seeded_all_six plus WORKSHEET_NAME for Sheet2.

| ruleId | worksheet | target | classification | findingId |
| --- | --- | --- | --- | --- |
| ALT_TEXT | Sheet1 | `xl/drawings/drawing1.xml#id=2` | REQUIRES_USER_INPUT | `e9f19d3e5eb8ee2963ad0ca33c7a547cf6b3fdc77f0abe2612e2eb5e2b646843` |
| ALT_TEXT | Sheet1 | `xl/drawings/drawing1.xml#id=3` | MANUAL_REVIEW | `9e103f504086a40a64150c5d81e7aef016dd6c2cd101c69bf8c0b2b77d5fd974` |
| COLOR_CONTRAST | Sheet1 | `xl/worksheets/sheet1.xml#cell=A11` | MANUAL_REVIEW | `03fb712b57fa6a638ce1a2d4aea2ea90df27972a43a7ab31b10f4d6363324880` |
| COLOR_CONTRAST | Sheet1 | `xl/worksheets/sheet1.xml#cell=A9` | MANUAL_REVIEW | `0d7aa1bcf98231ea068ccdc3b8627bab01a1b681f3dd47d42669c2cb274d6dbc` |
| LINK_TEXT | Sheet1 | `xl/worksheets/sheet1.xml#cell=A7` | REQUIRES_USER_INPUT | `dc48ae3fb38bb662646c8d30fb506bbaa855fcd3464fd878f0f54a8781f6ba6b` |
| MERGED_CELLS | Sheet1 | `xl/worksheets/sheet1.xml#merge=E1:F1` | MANUAL_REVIEW | `53c7bec07103248b073dfc7a290650e1d15d972682091982c0cb4f4507ab104a` |
| TABLE_HEADER | Sheet1 | `xl/worksheets/sheet1.xml#range=A1:C4` | REQUIRES_USER_INPUT | `9a27b0c0f6509d573828429b04afbb13de1ee6a5ea13908df26e62fa62c3a88d` |
| TABLE_HEADER | Summary | `xl/tables/table1.xml#tableId=1` | REQUIRES_USER_INPUT | `8c8a964b2173a6e5b625c1adb33508942e089cf320a6cfdcc2df876c1aa3f790` |
| WORKSHEET_NAME | Sheet1 | `xl/worksheets/sheet1.xml#sheetId=1` | REQUIRES_USER_INPUT | `f6dffae289c576bf701b67a971699e0c8917f2aa84f2cae7cee412cad773bf23` |
| WORKSHEET_NAME | Sheet2 | `xl/worksheets/sheet3.xml#sheetId=3` | REQUIRES_USER_INPUT | `89853ff778675dba00bfc5a7c8fc946d60706399cff3221136b80861580d3f8c` |

Limitation facts: Populated single-cell, one-row or one-column components (Sheet1 E1, A7, A9 and A11) are not inferred as tables; spec 7.4 requires this disclosure once per audit.

### `review_only`

Gallery (sheetId 1): decorative Picture 1 (id 2); merged A1:C1 with the title in A1; A3 'Overdue' in red. Every finding is MANUAL_REVIEW, so the status is REVIEW_REQUIRED and no APPLY is advertised.

| ruleId | worksheet | target | classification | findingId |
| --- | --- | --- | --- | --- |
| ALT_TEXT | Gallery | `xl/drawings/drawing1.xml#id=2` | MANUAL_REVIEW | `e33847466ca631e38fc62dbd498671e495b1a1ac468ef69a083627a7cf35a30d` |
| COLOR_CONTRAST | Gallery | `xl/worksheets/sheet1.xml#cell=A3` | MANUAL_REVIEW | `6525135e74175e731bca1dac88b9bf1c544bd11c9f200bd0ff55016d96494b3a` |
| MERGED_CELLS | Gallery | `xl/worksheets/sheet1.xml#merge=A1:C1` | MANUAL_REVIEW | `4ae5e31b83514fe59de12151c68de2720cf1533d7d9647a9ea59787d1a21006e` |

Limitation facts: Populated single-cell, one-row or one-column components are not inferred as tables; spec 7.4 requires this disclosure once per audit. (Gallery A1 and A3)

### `unsupported_edits`

Sheet1 (sheetId 1): table 1 A1:B3 with B2 'Overdue' in red and B3 =HYPERLINK("https://example.edu/team12","click here"); D1:E1 merged 'Notes'; drawing1.xml has decorative Picture 1 (id 2) and Pictures 2 and 3 sharing id 3. Summary (sheetId 2): table 2 with B2 =INDIRECT("Sheet1!A2"). Target questions for pod contract 1.1: the HYPERLINK formula finding uses #cell=B3.

| ruleId | worksheet | target | classification | findingId |
| --- | --- | --- | --- | --- |
| ALT_TEXT | Sheet1 | `xl/drawings/drawing1.xml#id=2` | MANUAL_REVIEW | `49377c18593e7ffaf8029956532d42f5f82cd3c248bd3c5c1e7548a89a4aaeb7` |
| ALT_TEXT | Sheet1 | `xl/drawings/drawing1.xml#xml=/wsDr[1]/twoCellAnchor[2]/pic[1]` | MANUAL_REVIEW | `1b50cc5e80b846a006acfd92dfcf5717f26599f770c44e31552c579c65b5a182` |
| ALT_TEXT | Sheet1 | `xl/drawings/drawing1.xml#xml=/wsDr[1]/twoCellAnchor[3]/pic[1]` | MANUAL_REVIEW | `570ac22c217edb80ac81e07b190ea4cf4c5f80e80da45d6ed4bf23d1771b63bf` |
| COLOR_CONTRAST | Sheet1 | `xl/worksheets/sheet1.xml#cell=B2` | MANUAL_REVIEW | `5c15d89dc94b46f3f9a7f079dbce34e1a2429a846bbf8641216d1ef3b7641a1a` |
| LINK_TEXT | Sheet1 | `xl/worksheets/sheet1.xml#cell=B3` | MANUAL_REVIEW | `c503e3bd88cd421d9ef871bbc4a97d41ee68b681a39f3bcc119d4b925f0c879a` |
| MERGED_CELLS | Sheet1 | `xl/worksheets/sheet1.xml#merge=D1:E1` | MANUAL_REVIEW | `400d86ae13aad3d97504b55d7072158cb2f24fa3a641a0e87da8fcb4181f1bd8` |
| WORKSHEET_NAME | Sheet1 | `xl/worksheets/sheet1.xml#sheetId=1` | MANUAL_REVIEW | `4d4f537d1f7efd84fc98dfc6b60219efbdc3181a188e9325fe66bc9b9c2d8d0a` |

Limitation facts: Pictures 2 and 3 in drawing1.xml share cNvPr id 3, so they are identified by indexed paths and need manual review. Summary!B2 builds a reference with INDIRECT, so renaming Sheet1 cannot be proven safe. Populated single-cell, one-row or one-column components are not inferred as tables; spec 7.4 requires this disclosure once per audit. (Sheet1 D1)

### `preservation_rich`

Budget (sheetId 1): table 1 A1:B5 with a SUM total and its cached value; data validation D2; bold-only conditional formatting B2:B4; a comment on A2 (comments1.xml plus vmlDrawing1.vml); a printer-settings binary; drawing1.xml with Picture 1 (id 2, title only) and Chart 2 (id 3, complete). Rates (sheetId 2) is hidden with table 2. Defined name BudgetTotal. Pending pod contract 1.1: the VML note's finding and its #id target.

| ruleId | worksheet | target | classification | findingId |
| --- | --- | --- | --- | --- |
| ALT_TEXT | Budget | `xl/drawings/drawing1.xml#id=2` | REQUIRES_USER_INPUT | `4f12e0d0861873cdeaa48cf4da3a91a869897cd2cb3351916c854b45f4d70d7c` |
| ALT_TEXT | Budget | `xl/drawings/vmlDrawing1.vml#id=_x0000_s1025` | MANUAL_REVIEW | `3c2ea1fc8f3950939dedf787cb7356e7c79adc023565be4f32bd0d234fdc4360` |

Limitation facts: The legacy VML comment note in xl/drawings/vmlDrawing1.vml is not interpreted (spec 7.2 keeps the Phase 3 manual-review behavior).

### `large_preservation`

Photos (sheetId 1): table 1 and a 900 x 900 stored PNG (about 2.4 MB) in Picture 1 (id 2, title only), so source and output exceed 2 MiB.

| ruleId | worksheet | target | classification | findingId |
| --- | --- | --- | --- | --- |
| ALT_TEXT | Photos | `xl/drawings/drawing1.xml#id=2` | REQUIRES_USER_INPUT | `aabe54397975db3e6c9538c52b5ceeebef4d1f51c129c22017950175c97d958a` |

### `unicode`

The Phase 3 unicode cases rebuilt on a ruleset 2.0.0 clean background (each sheet a formal 2 x 2 table, black on white). Same sheet names, objects and White_Space vectors; see ../shared/README.md for the per-object intent.

| ruleId | worksheet | target | classification | findingId |
| --- | --- | --- | --- | --- |
| ALT_TEXT | Café costs | `xl/drawings/drawing1.xml#id=3` | REQUIRES_USER_INPUT | `98482724ece69cfb080359b6153bea0ab43f7e2b2f651393d55373a6ca815c80` |
| ALT_TEXT | Café costs | `xl/drawings/drawing1.xml#id=4` | REQUIRES_USER_INPUT | `53c1d298f8da4f86eafc3720bc15896ceea40b30937412130939ff0a51ac0297` |
| ALT_TEXT | Café costs | `xl/drawings/drawing1.xml#id=7` | REQUIRES_USER_INPUT | `6e4df958f34e1b3efe4b1c14069106ddb0a52d3ef68d14e991c7fadfc8ef7c76` |
| ALT_TEXT | ｾｰﾙｽ | `xl/drawings/drawing3.xml#id=2` | REQUIRES_USER_INPUT | `29a75a180ee0ac2d80fd3f42683c15e2529dd319c2a2512dc58452f4978299c4` |
| ALT_TEXT | 📊 Summary | `xl/drawings/drawing2.xml#id=2` | REQUIRES_USER_INPUT | `dd55c4490773663980de6e21ca95e5443ed8fef60ee05f638dbeabcadd08329e` |
| WORKSHEET_NAME | U+3000Sheet2U+3000 | `xl/worksheets/sheet2.xml#sheetId=2` | REQUIRES_USER_INPUT | `01be0c3a918c9a13ac398561215bbd61248afd5deaa7672eba4aafa9000874ca` |

### `repeated_ids`

Spec 7.1's layout: two sibling twoCellAnchor pictures sharing id 2 (both MANUAL_REVIEW at the pic element, even the complete one), Rectangle 3 (id 3, title only), and Receipts' drawing2.xml reusing id 2 (not a repeat).

| ruleId | worksheet | target | classification | findingId |
| --- | --- | --- | --- | --- |
| ALT_TEXT | Expenses | `xl/drawings/drawing1.xml#id=3` | REQUIRES_USER_INPUT | `af5329ca14081aa690f187efe20474873f67eafb81ef290064b49d74b630ab90` |
| ALT_TEXT | Expenses | `xl/drawings/drawing1.xml#xml=/wsDr[1]/twoCellAnchor[1]/pic[1]` | MANUAL_REVIEW | `d3a3fc315ad53f722f0bf016c93cdac8a8bb0662ddce00a14ddd118ef78eb0c3` |
| ALT_TEXT | Expenses | `xl/drawings/drawing1.xml#xml=/wsDr[1]/twoCellAnchor[2]/pic[1]` | MANUAL_REVIEW | `1e0128386a88a71a5099d77060773a47e991da1e325067023ed70e5f8bb3d90a` |
| ALT_TEXT | Receipts | `xl/drawings/drawing2.xml#id=2` | REQUIRES_USER_INPUT | `17e8467d25ebe21c3c8f2c6c15f8464bf2e92ffdf21fa808045b4e1b1505fd77` |

Limitation facts: Pictures 1 and 2 in drawing1.xml share cNvPr id 2, so both are identified by their pic element paths and need manual review.

### `multiple_drawings`

As in ../shared/README.md (drawing numbers out of sheet order, hidden and veryHidden sheets, ids restarting per part, an absolute target), with every sheet's cells in a formal table.

| ruleId | worksheet | target | classification | findingId |
| --- | --- | --- | --- | --- |
| ALT_TEXT | Archive | `xl/drawings/drawing4.xml#id=2` | REQUIRES_USER_INPUT | `ada6d3e1555d799cef0c98aa5cb4e28f84bf9035bbadc8f51e477ec501c3498e` |
| ALT_TEXT | Expenses | `xl/drawings/drawing1.xml#id=3` | REQUIRES_USER_INPUT | `de025419fdcce38eeaf7c3a73023ca2ee70d9abd817606de9d1de0214f0c35b8` |
| ALT_TEXT | Hidden costs | `xl/drawings/drawing2.xml#id=2` | REQUIRES_USER_INPUT | `edcf0802386173ab66cc060c66a76628cd68c61e4fb6004453982d2d92e5c492` |
| ALT_TEXT | Summary | `xl/drawings/drawing3.xml#id=3` | REQUIRES_USER_INPUT | `79806a9dfe36aae84b6b1de13a5b8467a040150b3018d247a5a308fd545d1f0a` |

**Pending pod contract 1.1** (not in the repo): the VML comment finding and `#id=_x0000_s1025` target in
`preservation_rich`, and the `#cell=` target for the HYPERLINK-formula finding in `unsupported_edits`. The
`in_cell_picture`, `image_formula`, `form_controls` and `vml_comments` fixtures are not built until it is available.

## Vector fixtures (added 2026-11-01)

Each `P4-RULE-*` case owns part of one fixture. Its entry under `vectors` gives the rule, a scope (worksheets,
exact targets or a target prefix) and the exact findings and limitation facts expected inside that scope, so a
case fails on a missing, wrong or extra finding in its scope. The vectors of a fixture together cover all its findings.

| File | SHA256 | Expected result |
| --- | --- | --- |
| `table_header_vectors.xlsx` | `128596370884694572f06946b24ed67a115a715deaab811a48240e9ff0fe81c4` | 202, then `REMEDIATION_AVAILABLE`, 5 findings, 7 vector cases |
| `merge_vectors.xlsx` | `1aeb3214788d2ebaed69a03e3071383cc8213aab290edc13d9f3392660875b0b` | 202, then `REVIEW_REQUIRED`, 2 findings, 2 vector cases |
| `link_vectors.xlsx` | `962b5532a307421600568a83b4bef62d4be71a4817c41f72259d0e2b767876aa` | 202, then `REMEDIATION_AVAILABLE`, 14 findings, 6 vector cases |
| `contrast_vectors.xlsx` | `fd83260b1b50d8c35528c48b55944e9ca96227b89ee87c6ed153cece7cb1d4a8` | 202, then `REVIEW_REQUIRED`, 19 findings, 10 vector cases |

### `table_header_vectors`

One sheet per vector. Declared: table 1 (header omitted = 1) and table 2 (headerRowCount 1), distinct matching labels. Blank: table 3 with B1 empty (column metadata Column2). Duplicate: table 4 'Name' and 'name ' (equal after trim and casefold). Formula: table 5 header B1 ="Score". Sparse: L-shaped A1, B1, A2 with no table, plus diagonal D4/E5 that must not be joined. Lists: one row A1:C1, one column E1:E3, title G5. Hidden tables (hidden sheet): table 6 with headerRowCount 0 and matching first row.

**Excel open (2026-11-01): repair prompt, expected.** Excel's repair log names `xl/tables/table3.xml` and
`xl/tables/table4.xml` only. Excel can't store a blank header cell whose column metadata names it, or two column
names equal after trim and casefold, but spec §7.4 requires systems to flag both states, so the fixture keeps them.
Both are MANUAL_REVIEW, so no correction output edits them, and the §13 no-repair gate covers outputs, not sources.
Excel accepted the formula header (table 5). Reviewer, Excel version and platform are still to be recorded in
`excel_open`.

| Case | ruleId | worksheet | target | classification | findingId |
| --- | --- | --- | --- | --- | --- |
| P4-RULE-HEADER-DECLARED | TABLE_HEADER | (scope {"worksheets": ["Declared"]}) | none | | |
| P4-RULE-HEADER-BLANK | TABLE_HEADER | Blank | `xl/tables/table3.xml#tableId=3` | MANUAL_REVIEW | `2ba561bf2daaf92c6b24f2cac83ba91187aabb17753f5a0418d69ba9a5e3226a` |
| P4-RULE-HEADER-DUPLICATE | TABLE_HEADER | Duplicate | `xl/tables/table4.xml#tableId=4` | MANUAL_REVIEW | `554d3ad4b8e09950e180c0a36224e71bbd7b29870f36a7ce3307d7a178e3c15a` |
| P4-RULE-HEADER-FORMULA | TABLE_HEADER | Formula | `xl/tables/table5.xml#tableId=5` | MANUAL_REVIEW | `4685ee0c1a4028d9bf98613f729b714b52e6b6fa342780cbc76a865682404420` |
| P4-RULE-HEADER-SPARSE | TABLE_HEADER | Sparse | `xl/worksheets/sheet5.xml#range=A1:B2` | MANUAL_REVIEW | `c333b92dbe45d062fb5b1fb0269ac5da2a13bf737fea0906ab23b1e9cf6b1fcc` |
| P4-RULE-HEADER-TITLE-LIST | TABLE_HEADER | (scope {"worksheets": ["Lists"]}) | none | | |
| P4-RULE-HEADER-HIDDEN | TABLE_HEADER | Hidden tables | `xl/tables/table6.xml#tableId=6` | REQUIRES_USER_INPUT | `fbe4bfa250eb4d6e4aa30d406344be51d0a47fe64f4aa5c2684b19a98d55dea0` |

Limitation facts: Sparse!A1:B2 is a connected but not dense candidate, so its logical structure could not be established safely (spec 7.4). Populated single-cell, one-row or one-column components are not inferred as tables; spec 7.4 requires this disclosure once per audit. (Sparse D4 and E5, Lists A1:C1, E1:E3 and G5)

### `merge_vectors`

Merges (sheetId 1): A1:D1 title merge with text in A1; B3:C4 with 42 in B3; F1:G1 with no cells; F3:G3 with styled but empty F3 and G3.

| Case | ruleId | worksheet | target | classification | findingId |
| --- | --- | --- | --- | --- | --- |
| P4-RULE-MERGE-POPULATED | MERGED_CELLS | Merges | `xl/worksheets/sheet1.xml#merge=A1:D1` | MANUAL_REVIEW | `db4160693e19a151b24793c14418e49f0a4352270ddfa333a5c9f4b1202bde57` |
| P4-RULE-MERGE-POPULATED | MERGED_CELLS | Merges | `xl/worksheets/sheet1.xml#merge=B3:C4` | MANUAL_REVIEW | `07993b98ecb482174b61ea7b526b90434b85fd994aa7b7663920108e3e8eda80` |
| P4-RULE-MERGE-EMPTY | MERGED_CELLS | (scope {"targets": ["xl/worksheets/sheet1.xml#merge=F1:G1", "xl/worksheets/sheet1.xml#merge=F3:G3"]}) | none | | |

Limitation facts: Populated single-cell, one-row or one-column components are not inferred as tables; spec 7.4 requires this disclosure once per audit. (Merges A1 and B3)

### `link_vectors`

Links (sheetId 1): table 1 A1:B15. Simple links A2 ' click HERE! ', A3 'Read more.', A4 'Learn   more?', A5 'Annual accessibility report' (descriptive), A6 'https://example.edu/d' to another host, A7 'www.example.edu', A8 'mailto:staff@example.edu', A9 'example.edu' equal to its destination, A10 'click here' with display 'Annual report'. Formulas A11 =HYPERLINK(url,"here"), A12 =HYPERLINK(url), A13 =HYPERLINK(B13,"link"). hyperlink[10] spans A14:B14; hyperlink[11] and [12] both declare A15. Formula links use indexed XML cell paths (spec 7.6, confirmed by Team 9 on 2026-11-01): A11-A13 are /worksheet[1]/sheetData[1]/row[11..13]/c[1]. Pending pod contract 1.1: the indexed-path targets for range and duplicate links.

| Case | ruleId | worksheet | target | classification | findingId |
| --- | --- | --- | --- | --- | --- |
| P4-RULE-LINK-GENERIC | LINK_TEXT | Links | `xl/worksheets/sheet1.xml#cell=A2` | REQUIRES_USER_INPUT | `f4f6946c1339d9595626f3b6bf8bbb264056940af0d3723705084aa67438628f` |
| P4-RULE-LINK-GENERIC | LINK_TEXT | Links | `xl/worksheets/sheet1.xml#cell=A3` | REQUIRES_USER_INPUT | `5dc6e9aa05023c9616728f55919bfe10ab10e26f7239fe0c4f08d795cf905254` |
| P4-RULE-LINK-GENERIC | LINK_TEXT | Links | `xl/worksheets/sheet1.xml#cell=A4` | REQUIRES_USER_INPUT | `c50f188b9b691742b11b7dba9a1ec5ce04ac276df51972f43116aeca838e8972` |
| P4-RULE-LINK-RAW-ADDRESS | LINK_TEXT | Links | `xl/worksheets/sheet1.xml#cell=A6` | REQUIRES_USER_INPUT | `6e8f737e7cd5e796f94493185148d7abefd7be1164571b220110ab1b3f6d1335` |
| P4-RULE-LINK-RAW-ADDRESS | LINK_TEXT | Links | `xl/worksheets/sheet1.xml#cell=A7` | REQUIRES_USER_INPUT | `aded0edba0b697b3eb3dd74006669c0ce8705dd8d79d1aad70032cd7e5c62144` |
| P4-RULE-LINK-RAW-ADDRESS | LINK_TEXT | Links | `xl/worksheets/sheet1.xml#cell=A8` | REQUIRES_USER_INPUT | `e49b3784839ea4ca92bdee360ee9cee24d418357dacf1eaf09b3c5c4d99b9591` |
| P4-RULE-LINK-RAW-ADDRESS | LINK_TEXT | Links | `xl/worksheets/sheet1.xml#cell=A9` | REQUIRES_USER_INPUT | `1c9392856a578993e21e19575a3e8c29f6d0b1151343efb130b9245bf00592ef` |
| P4-RULE-LINK-CELL-DISPLAY | LINK_TEXT | Links | `xl/worksheets/sheet1.xml#cell=A10` | REQUIRES_USER_INPUT | `092491a31182c4b083583bbc985880d4b0d125256554bd594cc4ffb10a09b70e` |
| P4-RULE-LINK-FORMULA-LITERAL | LINK_TEXT | Links | `xl/worksheets/sheet1.xml#xml=/worksheet[1]/sheetData[1]/row[11]/c[1]` | MANUAL_REVIEW | `1d423a59f9227fd8304cf7982b7138af1557a9b4c569c00ffd9a8fe2d14d93b0` |
| P4-RULE-LINK-FORMULA-LITERAL | LINK_TEXT | Links | `xl/worksheets/sheet1.xml#xml=/worksheet[1]/sheetData[1]/row[12]/c[1]` | MANUAL_REVIEW | `ade7d1e48d06087c1c734b488ed76e82e207a5dcd68e5f556e68e11eff9aa776` |
| P4-RULE-LINK-FORMULA-DYNAMIC | LINK_TEXT | Links | `xl/worksheets/sheet1.xml#xml=/worksheet[1]/sheetData[1]/row[13]/c[1]` | MANUAL_REVIEW | `6f4892fa45cc49b9e44294bb7e281e360c06a064711dfb2731f9f42ae3df6995` |
| P4-RULE-LINK-RANGE-DUPLICATE | LINK_TEXT | Links | `xl/worksheets/sheet1.xml#xml=/worksheet[1]/hyperlinks[1]/hyperlink[10]` | MANUAL_REVIEW | `e9048b0a2f1e9dcd90ce451617f541de9e35153589d438deb1b0aafd9e55114c` |
| P4-RULE-LINK-RANGE-DUPLICATE | LINK_TEXT | Links | `xl/worksheets/sheet1.xml#xml=/worksheet[1]/hyperlinks[1]/hyperlink[11]` | MANUAL_REVIEW | `9cd08b06c3c8764aac96a1a9354cf9c6bfe428e27bd97dee9a140e6e150cda7d` |
| P4-RULE-LINK-RANGE-DUPLICATE | LINK_TEXT | Links | `xl/worksheets/sheet1.xml#xml=/worksheet[1]/hyperlinks[1]/hyperlink[12]` | MANUAL_REVIEW | `fee5e3f89a798ed9e373e5787667bce802576d3f94507c076153bccf89315663` |

Limitation facts: Links!A13 =HYPERLINK(B13,"link") has a computed argument; it is not evaluated and needs manual review (spec 7.6).

### `contrast_vectors`

All on white unless noted. Default: A1 default style (no colour, no fill), A3 333333 (12.63:1). Contrast: A1 777777 (4.478, fails), A3 767676 (4.542, passes). Large: A1 18 pt 959595 (2.995, fails 3.0), A3 18 pt 949494 (3.033, passes), A5 14 pt bold 949494 (passes), A7 14 pt regular 949494 (fails 4.5). Theme: A1 accent1 336699 tint -1 = 000000 (passes), A3 accent1 tint 0.5 = 8CB2D9 (nonneutral), A5 dk1 tint 0.5 = 808080 (3.949, fails), A7 dk1 tint 0.25 = 404040 (passes). Indexed: the workbook palette sets index 10 to black (passes), index 12 stays 0000FF (nonneutral). Meaning: A1 0000FF text (8.59, nonneutral), A3 black on FFFF00 fill (nonneutral fill). Conditional: A1:A3 has a fill-colour conditional format, so the 777777 cell A2 inside it is suppressed; A5 777777 outside it is not. Unsupported and Overlay: see the limitation fact. Hidden cells: A3 in a hidden row and C1 in a hidden column, both 777777.

| Case | ruleId | worksheet | target | classification | findingId |
| --- | --- | --- | --- | --- | --- |
| P4-RULE-COLOR-DEFAULT | COLOR_CONTRAST | (scope {"worksheets": ["Default"]}) | none | | |
| P4-RULE-COLOR-LOW-CONTRAST | COLOR_CONTRAST | Contrast | `xl/worksheets/sheet2.xml#cell=A1` | MANUAL_REVIEW | `325a2b90e88bd9bf27c27b367562bddc8cde111afdf3b1bc29ff87c2522447b0` |
| P4-RULE-COLOR-LARGE-TEXT | COLOR_CONTRAST | Large | `xl/worksheets/sheet3.xml#cell=A1` | MANUAL_REVIEW | `158e4236b1349849032f20382bbdd0fcde90bfa3d579abef997289d086ed1183` |
| P4-RULE-COLOR-LARGE-TEXT | COLOR_CONTRAST | Large | `xl/worksheets/sheet3.xml#cell=A7` | MANUAL_REVIEW | `baa787fbd6a151efd3d2493d25e3c4ceaa9988d53b97c05ea68a22a6a03603eb` |
| P4-RULE-COLOR-BOUNDARY | COLOR_CONTRAST | Contrast | `xl/worksheets/sheet2.xml#cell=A1` | MANUAL_REVIEW | `325a2b90e88bd9bf27c27b367562bddc8cde111afdf3b1bc29ff87c2522447b0` |
| P4-RULE-COLOR-BOUNDARY | COLOR_CONTRAST | Large | `xl/worksheets/sheet3.xml#cell=A1` | MANUAL_REVIEW | `158e4236b1349849032f20382bbdd0fcde90bfa3d579abef997289d086ed1183` |
| P4-RULE-COLOR-BOUNDARY | COLOR_CONTRAST | Large | `xl/worksheets/sheet3.xml#cell=A7` | MANUAL_REVIEW | `baa787fbd6a151efd3d2493d25e3c4ceaa9988d53b97c05ea68a22a6a03603eb` |
| P4-RULE-COLOR-THEME-TINT | COLOR_CONTRAST | Theme | `xl/worksheets/sheet4.xml#cell=A3` | MANUAL_REVIEW | `4ef71c505a2b99028d641861319b2e3238fe036dc892ea6ea77b06e8f5513e50` |
| P4-RULE-COLOR-THEME-TINT | COLOR_CONTRAST | Theme | `xl/worksheets/sheet4.xml#cell=A5` | MANUAL_REVIEW | `9f68f5c7aef6d13750babb0434f424edbec2e95267caf617eb330cec0595032b` |
| P4-RULE-COLOR-INDEXED | COLOR_CONTRAST | Indexed | `xl/worksheets/sheet5.xml#cell=A3` | MANUAL_REVIEW | `909a4d52b66afd00cfd1079c155147d3213c8115456e2e18303a0bcf9dc0a7aa` |
| P4-RULE-COLOR-MEANING | COLOR_CONTRAST | Meaning | `xl/worksheets/sheet6.xml#cell=A1` | MANUAL_REVIEW | `6099a3eb1e8a696ff3bacada22be6c1fe06fc6bdce7d1149319e07db829875fe` |
| P4-RULE-COLOR-MEANING | COLOR_CONTRAST | Meaning | `xl/worksheets/sheet6.xml#cell=A3` | MANUAL_REVIEW | `34f863faed1a07a20ae7cc4b8f4ef54670772a15453c6b42dbe8ecee960cc937` |
| P4-RULE-COLOR-CONDITIONAL | COLOR_CONTRAST | Conditional | `xl/worksheets/sheet7.xml#cell=A5` | MANUAL_REVIEW | `734a1ef166da94e1ae27cc77dbfad9fc450840379091e39c15798a00760ede8c` |
| P4-RULE-COLOR-CONDITIONAL | COLOR_CONTRAST | Conditional | `xl/worksheets/sheet7.xml#conditional=A1:A3` | MANUAL_REVIEW | `5ec76f8082e4bd904d8207747214fe6b9d70d34159b507fdbff12335a419651d` |
| P4-RULE-COLOR-UNSUPPORTED | COLOR_CONTRAST | Overlay | `xl/worksheets/sheet9.xml#cell=A1` | MANUAL_REVIEW | `385d0f1e7207745bc8f18dd05440b2e85af46c48d7a8380ab49f94fec29dd524` |
| P4-RULE-COLOR-UNSUPPORTED | COLOR_CONTRAST | Overlay | `xl/worksheets/sheet9.xml#cell=A2` | MANUAL_REVIEW | `7bbbd207b55b4b2319c9b1169ed805f02f72efa9447ece2a0d5e86cfd0963d08` |
| P4-RULE-COLOR-UNSUPPORTED | COLOR_CONTRAST | Overlay | `xl/worksheets/sheet9.xml#cell=B1` | MANUAL_REVIEW | `332be1c193ca38df32797b175fe3e2639a06afc0123894064d8119d3b53db8a2` |
| P4-RULE-COLOR-UNSUPPORTED | COLOR_CONTRAST | Overlay | `xl/worksheets/sheet9.xml#cell=B2` | MANUAL_REVIEW | `84fa55c35062ac51bf29d903429190fe6ed4f56bed7dc2d4f8d64d071d67d217` |
| P4-RULE-COLOR-UNSUPPORTED | COLOR_CONTRAST | Unsupported | `xl/worksheets/sheet8.xml#cell=A1` | MANUAL_REVIEW | `0fb1990110e237b05c60190b463bac773bf063bed494af2fe06aa00effcb73dc` |
| P4-RULE-COLOR-UNSUPPORTED | COLOR_CONTRAST | Unsupported | `xl/worksheets/sheet8.xml#cell=A3` | MANUAL_REVIEW | `b6337c8759a3e4eb0e28d8ff65bcb012fee753f3e3bcd87fb9e9ba06b011a249` |
| P4-RULE-COLOR-UNSUPPORTED | COLOR_CONTRAST | Unsupported | `xl/worksheets/sheet8.xml#cell=A5` | MANUAL_REVIEW | `bdd7b86fd03182bce81dbc01733c883fe03cb1226d7fdf4ac17f4e5ef90b7162` |
| P4-RULE-COLOR-HIDDEN | COLOR_CONTRAST | Hidden cells | `xl/worksheets/sheet10.xml#cell=A3` | MANUAL_REVIEW | `1a1c7fc871609f04f04e0cae963d0b738db794ef4e371e9bda69da1053e7c2b5` |
| P4-RULE-COLOR-HIDDEN | COLOR_CONTRAST | Hidden cells | `xl/worksheets/sheet10.xml#cell=C1` | MANUAL_REVIEW | `2218ba722a7e10d605fc7e4b4ca015956038602f8f8152a5439372b025398151` |

Limitation facts: Default!A1 has no font colour and no fill, so the screening assumption (black text on white) is used and disclosed once (spec 7.7). Gradient fill (Unsupported!A1), pattern fill (A3), mixed rich-text styling (A5) and a table style overlay (Overlay!A1:B2) cannot be given a numeric contrast result; each cell needs manual review (spec 7.7). Populated single-cell, one-row or one-column components are not inferred as tables; spec 7.4 requires this disclosure once per audit.

## Still to build

The four pod-contract edge fixtures (`in_cell_picture`, `image_formula`, `form_controls`, `vml_comments`).
