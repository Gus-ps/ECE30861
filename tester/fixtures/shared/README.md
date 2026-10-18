# Team 12 shared Phase 3 fixtures

The three workbooks Team 12 owes Team 9 (`ref/team12-shared-test-suite-guide.md`, "Files requested from Team 12"),
with hand-authored expectations in `expectations.json` (Team 9's format, `origin: "team12"`).

| File | SHA256 | Expected result |
| --- | --- | --- |
| `clean.xlsx` | `20feed4783615c2ef5f5579a53b25524fc75a7316c108e1fc25bf1b5278aeca2` | 202, then `AUDIT_COMPLETE`, no findings |
| `seeded_issues.xlsx` | `24dd6a6da19f4676d3bce27f3d5b4b8d285369beecb3926454c71f2ed0ea692c` | 202, then `REVIEW_REQUIRED`, 8 findings |
| `corrupt.xlsx` | `9cf891ba569c9de0a6b006bca6f481c9e3c17e3eb53342691ecea9f253e2dd09` | 422 project error, no accepted IDs |

Ruleset `1.0.0`; audit policy from the pod profile `team9-defaults-1.0.0` (not yet pod-approved).

## How they were made and checked

- Built by `scripts/build_shared_fixtures.py`, which writes every OOXML part by hand. Entries are stored
  uncompressed with fixed timestamps, so the bytes are reproducible (`--check` verifies the committed files).
- Each sheet has a formatted cost table (header fill, currency format, SUM total). Shapes have a fill, outline
  and visible label; the chart has a visible title and coloured series; each picture has its own placeholder image.
- Expectations were written from the object definitions below, then cross-checked against
  `tester/suite/pod_rules.py`, an independent implementation of the two rules. No system was run to derive them.
- Both valid files load in openpyxl. On 2026-10-17 a scripted read-only open in Excel 16 (hidden instance) kept
  every sheet, sheet state, object, group child, title and description as authored, and a PDF export rendered
  every object at its intended size.

**Manual review:** a two-member Team 12 review of these expectations and a manual Excel open of each valid file
(no repair prompt) were recorded complete on 2026-10-17. The expectations still depend on pod-pending policy; see
"Policy-dependent rows" below.

## Replacing the placeholder images

Put replacement images in `scripts/fixture_images/`, named by picture key, as `.png`, `.jpg` or `.jpeg`:

| Key | Used by |
| --- | --- |
| `logo` | clean Picture 1; seeded Sheet1 Picture 1 |
| `receipt` | seeded Expenses Picture 1 |
| `divider` | seeded Sheet1 Picture 4 (decorative) |
| `totals_icon` | seeded Sheet1 Picture 6 (in Group 5) |
| `archive` | seeded " Sheet03 " Picture 1 |

Then run `uv run python scripts/build_shared_fixtures.py`, and update the SHA256 values above, in
`expectations.json` and the finding IDs below (they include the file hash). Object IDs, anchors and alt-text
fields do not change, so the expected findings stay the same. Do not swap pictures in Excel and save: Excel
rewrites the whole package and may renumber objects or drawing parts, which changes the expected targets.

## `clean.xlsx`

| Sheet (sheetId, part) | Object (id) | Visible content | Title | Description | Finding |
| --- | --- | --- | --- | --- | --- |
| Budget (1, `sheet1.xml`) | Picture 1 (2) | logo image | Team logo | Team 12 logo placeholder. | none |
| Budget | Rectangle 2 (3) | label "Rent is the largest cost" | Budget note | Callout noting that rent is the largest cost. | none |
| Budget | Chart 3 (4) | column chart titled "Costs by item" | Costs by item | Column chart: rent $1,200, travel $300, supplies $200. | none |
| Notes (2, `sheet2.xml`) | no objects | | | | none |

## `seeded_issues.xlsx`

Sheet names deliberately do not match part numbers, and sheetIds are not positional. Visible shape text, chart
titles and object names do not substitute for the alt-text title or description.

| Sheet (sheetId, part) | Object (id) | Visible content | Title | Description | Intended finding |
| --- | --- | --- | --- | --- | --- |
| Expenses (1, `sheet1.xml`) | Picture 1 (2) | receipt image | Receipt | Scanned travel receipt placeholder. | none (descriptive sheet, complete object) |
| Sheet1 (2, `sheet2.xml`) | sheet name | | | | WORKSHEET_NAME |
| Sheet1 | Picture 1 (2) | logo image | Logo | *absent* | ALT_TEXT, REQUIRES_USER_INPUT |
| Sheet1 | Rectangle 2 (3) | label "Totals" | *empty string* | Box around the totals. | ALT_TEXT, REQUIRES_USER_INPUT |
| Sheet1 | Chart 3 (4) | chart titled "Costs by item" | U+00A0 | U+3000 + space | ALT_TEXT, REQUIRES_USER_INPUT (whitespace only) |
| Sheet1 | Picture 4 (5) | divider image | *absent* | *absent* | ALT_TEXT, MANUAL_REVIEW (native decorative flag) |
| Sheet1 | Group 5 (6) | icon and oval | Totals group | Totals icon beside a status oval. | none |
| Sheet1 | Picture 6 (7), in group | totals icon image | Totals icon | Small totals icon placeholder. | none |
| Sheet1 | Oval 7 (8), in group | label "Status: OK" | *absent* | *absent* | ALT_TEXT, REQUIRES_USER_INPUT (one finding for both) |
| " Sheet03 " (5, `sheet3.xml`), hidden | sheet name | | | | WORKSHEET_NAME (trim + leading zero) |
| " Sheet03 " | Picture 1 (2) | archive image | Archive | *absent* | ALT_TEXT, REQUIRES_USER_INPUT (hidden sheet) |
| Sheet0 (4, `sheet4.xml`) | sheet name | | | | none (suffix is zero) |

Expected findings in contract order, with finding IDs computed by `tester/suite/identity.py`:

| ruleId | worksheet | target | classification | findingId |
| --- | --- | --- | --- | --- |
| ALT_TEXT | " Sheet03 " | `xl/drawings/drawing3.xml#id=2` | REQUIRES_USER_INPUT | `886785211d1409121d0643651a238ba56bb4f2a5c9a3ff18db38f910e23c286b` |
| ALT_TEXT | Sheet1 | `xl/drawings/drawing2.xml#id=2` | REQUIRES_USER_INPUT | `5b15fc6f78fee87ba60754e432d2e804373f271990d54a67ce79f26bcbd40b18` |
| ALT_TEXT | Sheet1 | `xl/drawings/drawing2.xml#id=3` | REQUIRES_USER_INPUT | `d8a307dbc0d88458b916c9bb487fb97aeb4d394e1b34281a27bc69b8251e3cf6` |
| ALT_TEXT | Sheet1 | `xl/drawings/drawing2.xml#id=4` | REQUIRES_USER_INPUT | `bf7d76af7433f2916e7563280c4b30bc29f3667e090292540f2880ebe9259edf` |
| ALT_TEXT | Sheet1 | `xl/drawings/drawing2.xml#id=5` | MANUAL_REVIEW | `62e7c31a6edc7f4c6e68f8ea5aed436f02347f85d112a799fd1a64038000a6ce` |
| ALT_TEXT | Sheet1 | `xl/drawings/drawing2.xml#id=8` | REQUIRES_USER_INPUT | `0fdb4b6720e1e9cb76be9bc422018a0550e80767d5ebbecb1147dc735cb9143e` |
| WORKSHEET_NAME | " Sheet03 " | `xl/worksheets/sheet3.xml#sheetId=5` | REQUIRES_USER_INPUT | `3485390254abf10b870da1645e31102474b9d0ccced433ddf0731798919f41c3` |
| WORKSHEET_NAME | Sheet1 | `xl/worksheets/sheet2.xml#sheetId=2` | REQUIRES_USER_INPUT | `a4c3558b08964c7bc7dac2d16814bd5365a2b418f85320ab31eaa0d294d0ac3b` |

### Policy-dependent rows

Seven rows depend on Team 9 defaults that are on the pod confirmation list (`ref/phase3.md`, "Bootstrap
clarification and confirmation list") and are not yet approved. If the pod decides otherwise, update
`tester/fixtures/pod_profile.json` (bump `profile_version`), the findings in `expectations.json`, and the tables
and finding IDs here.

| Setting (current default) | Row | Expected now | If the pod decides otherwise |
| --- | --- | --- | --- |
| `alt_text.require_title` (true) | Sheet1 Rectangle 2 (empty title, has description) | ALT_TEXT | title optional: finding drops |
| `alt_text.require_description` (true) | Sheet1 Picture 1 (title, no description) | ALT_TEXT | description optional: finding drops |
| `alt_text.require_description` (true) | " Sheet03 " Picture 1 (title, no description) | ALT_TEXT | description optional: finding drops |
| `alt_text.decorative_classification` (MANUAL_REVIEW) | Sheet1 Picture 4 (native decorative flag) | ALT_TEXT, MANUAL_REVIEW | no finding, or REQUIRES_USER_INPUT |
| Unicode White_Space trim (not in the profile; fixed in `tester/suite/identity.py`) | Sheet1 Chart 3 (U+00A0 title, U+3000 + space description) | ALT_TEXT | ASCII-only trim: both fields count as present, finding drops |
| Whitespace trim and leading-zero names (`worksheet_name.pattern`) | " Sheet03 " sheet name | WORKSHEET_NAME | no trim, or leading zeroes excluded: finding drops |
| `worksheet_name.suffix_must_exceed_zero` (true) | Sheet0 sheet name | none | false: new WORKSHEET_NAME finding |

Up to five of the eight expected findings can drop, and one can be added. Two rows hold under any of these
choices: Oval 7 (no title or description) and the "Sheet1" sheet name.

## `corrupt.xlsx`

The 4-byte ZIP local-file signature `PK\x03\x04` followed by repeated plain text. Not a readable package.
Only the 422 status and the project error envelope are asserted; no error code is agreed.
