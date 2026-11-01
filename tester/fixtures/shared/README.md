# Team 12 shared Phase 3 fixtures

The three workbooks Team 12 owes Team 9 (`ref/team12-shared-test-suite-guide.md`, "Files requested from Team 12"),
plus Team 12 versions of the manifest's three accepted edge fixtures and seven rejected-input fixtures, with
hand-authored expectations in `expectations.json` (Team 9's format, `origin: "team12"`). The pack names every
fixture the Phase 3 manifest uses.

| File | SHA256 | Expected result |
| --- | --- | --- |
| `clean.xlsx` | `20feed4783615c2ef5f5579a53b25524fc75a7316c108e1fc25bf1b5278aeca2` | 202, then `AUDIT_COMPLETE`, no findings |
| `seeded_issues.xlsx` | `24dd6a6da19f4676d3bce27f3d5b4b8d285369beecb3926454c71f2ed0ea692c` | 202, then `REVIEW_REQUIRED`, 8 findings |
| `corrupt.xlsx` | `9cf891ba569c9de0a6b006bca6f481c9e3c17e3eb53342691ecea9f253e2dd09` | 422 project error, no accepted IDs |
| `unicode.xlsx` | `1b2c03d81c1e0998e375f733f852fdc074aa3e581e7328649b30297cfe72a8ab` | 202, then `REVIEW_REQUIRED`, 6 findings, no limitations |
| `repeated_ids.xlsx` | `35cfc7580bff622018741ca9dc7f72da2cadd9998e02948360ebc55aabc10424` | 202, then `REVIEW_REQUIRED`, 4 findings, nonempty limitations |
| `multiple_drawings.xlsx` | `82fff168f7569daabea4951859c8828f8d1deca6055f468e4b443b45d1f9870a` | 202, then `REVIEW_REQUIRED`, 4 findings, no limitations |
| `zip_traversal.xlsx` | `b2d07b501310ca89cc38c4dfa9dae6c35451f7a53c15be0630dbe79fc3942af5` | 422 project error, no accepted IDs |
| `zip_duplicate.xlsx` | `d97e27eea8d46d69d96cab1eeba004932768992dd7f2e6fcdd066d67f2f2af83` | 422 project error, no accepted IDs |
| `xml_dtd.xlsx` | `0b05bf86d94eb855ab4db603a56d88822fcddaa8acbe66d7ec53ea396c187108` | 422 project error, no accepted IDs |
| `macro_parts.xlsx` | `d5fb9d0fca22aaee67ae5cb387b068a5daaa73d892da62a1290a45e33a946d06` | 422 project error, no accepted IDs |
| `encrypted_zip.xlsx` | `58a2d8c291c64c8184c4d86c631e1638823843dfd1bec975ec2a43e600859551` | 422 project error, no accepted IDs |
| `protected_sheet.xlsx` | `1bbe7342deae053aedd301d69010aec0aa6d86cb8fbf021b1d9faefd4942ee43` | 422 project error, no accepted IDs |
| `protected_structure.xlsx` | `53835c995e98201b2a097c2115ad168c211337a20fad9ddeb574ab6acd6e948d` | 422 project error, no accepted IDs |

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

**Manual review:** a two-member Team 12 review of the clean and seeded expectations and a manual Excel open of
those two files (no repair prompt) were recorded complete on 2026-10-17. That is an internal review; the Phase 4
specification (§15.2) asks for review by two members of the other implementation team, which has not happened.
The ten fixtures added on 2026-10-31 have had no review and no Excel open. The expectations still depend on
pod-pending policy; see "Policy-dependent rows" below.

## Replacing the placeholder images

Put replacement images in `scripts/fixture_images/`, named by picture key, as `.png`, `.jpg` or `.jpeg`:

| Key | Used by |
| --- | --- |
| `logo` | clean Picture 1; seeded Sheet1 Picture 1; edge fixtures |
| `chart_icon` | edge fixtures |
| `receipt` | seeded Expenses Picture 1; edge fixtures |
| `divider` | seeded Sheet1 Picture 4 (decorative); edge fixtures |
| `totals_icon` | seeded Sheet1 Picture 6 (in Group 5); repeated_ids Picture 5 |
| `archive` | seeded " Sheet03 " Picture 1; edge fixtures |

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

## Accepted edge fixtures (added 2026-10-31)

The manifest's `edge_upload` / `edge_audit` cases. Each should be accepted (202) and audited to
`REVIEW_REQUIRED` with exactly the findings below. Limitations must be an empty array except for
`repeated_ids`, where they must be nonempty; their wording is not compared. Characters are given as code points
because several are invisible.

### `unicode.xlsx`

Tests the explicit White_Space set against characters that look blank but are not White_Space, raw worksheet
spelling (no normalization), ASCII-only worksheet-name matching, and code-point ordering.

| Sheet (sheetId, part) | Object (id) | Title | Description | Intended finding |
| --- | --- | --- | --- | --- |
| `Cafe` + U+0301 + ` costs` (1, `sheet1.xml`), NFD | Picture 1 (2) | Team logo | U+200B only | none (U+200B is not White_Space) |
| same | Picture 2 (3) | U+2003 U+205F | Scanned receipt placeholder. | ALT_TEXT, REQUIRES_USER_INPUT |
| same | Rectangle 3 (4) | Totals | U+0085 U+2028 U+1680 | ALT_TEXT, REQUIRES_USER_INPUT |
| same | Rectangle 4 (5) | 東京オフィス | Büro München: Übersicht der Kosten. | none |
| same | Picture 5 (6) | U+FEFF only | Divider line placeholder. | none (U+FEFF is not White_Space) |
| same | Picture 6 (7) | Chart icon | tab, LF, CR, space (as character references) | ALT_TEXT, REQUIRES_USER_INPUT |
| U+3000 `Sheet2` U+3000 (2, `sheet2.xml`) | sheet name | | | WORKSHEET_NAME (trims to Sheet2) |
| `Sheet` + U+FF13 (3, `sheet3.xml`) | sheet name | | | none (fullwidth digit is not [0-9]) |
| U+017F + `heet4` (4, `sheet4.xml`) | sheet name | | | none (long s is not ASCII s) |
| U+1F4CA + ` Summary` (5, `sheet5.xml`) | Picture 1 (2), `drawing2.xml` | Chart icon | *absent* | ALT_TEXT, REQUIRES_USER_INPUT |
| U+FF7E U+FF70 U+FF99 U+FF7D (6, `sheet6.xml`) | Rectangle 1 (2), `drawing3.xml` | Sales | *empty string* | ALT_TEXT, REQUIRES_USER_INPUT |

The U+1F4CA sheet sorts after the halfwidth-katakana sheet by code point, but before it by UTF-16 code unit, so
an implementation that sorts UTF-16 strings directly gets the order wrong.

| ruleId | worksheet | target | findingId |
| --- | --- | --- | --- |
| ALT_TEXT | `Cafe`+U+0301+` costs` | `xl/drawings/drawing1.xml#id=3` | `21252d8a4cab1e21acbd603bcbec5c07964bf7624e4012279ad818204542952d` |
| ALT_TEXT | `Cafe`+U+0301+` costs` | `xl/drawings/drawing1.xml#id=4` | `6a58bd7b07714d8362fe6e0e90b889c6e63668c4d0d979da4aff4a1e67077d92` |
| ALT_TEXT | `Cafe`+U+0301+` costs` | `xl/drawings/drawing1.xml#id=7` | `bc41ddfb5e343f41c13f2dc0642600542c63a3e438890f55cf64ce3bcb377767` |
| ALT_TEXT | U+FF7E U+FF70 U+FF99 U+FF7D | `xl/drawings/drawing3.xml#id=2` | `1ce6177b53946a219da12b222dc206c5e57a8c849fe3228c61cc50143566c116` |
| ALT_TEXT | U+1F4CA+` Summary` | `xl/drawings/drawing2.xml#id=2` | `2e5383f47f4c4cd130ca7684ee460309c925bbe7fac132af0ea028dd975fe6cf` |
| WORKSHEET_NAME | U+3000+`Sheet2`+U+3000 | `xl/worksheets/sheet2.xml#sheetId=2` | `1c82e055c8b0f62b4fea85a3940294787e983e23a24e912f970db275a9fcc351` |

All classifications are REQUIRES_USER_INPUT.

### `repeated_ids.xlsx`

Object IDs repeat inside one drawing part, so each repeated occurrence is targeted by its indexed XML path
(`ref/phase3.md`, "Object target"). The same ID in a different part is not a repeat.

| Sheet (sheetId, part) | Anchor | Object (id) | Title | Description | Intended finding |
| --- | --- | --- | --- | --- | --- |
| Expenses (1, `sheet1.xml`), `drawing1.xml` | 1 | Picture 1 (**2**) | Receipt | *absent* | ALT_TEXT via `#xml=` path; limitation |
| Expenses | 2 | Picture 2 (**2**) | Team logo | Team 12 logo placeholder. | none; limitation |
| Expenses | 3 | Rectangle 3 (3) | Totals | *absent* | ALT_TEXT via `#id=3` |
| Expenses | 4 | Group 4 (**4**) | Totals group | Totals icon beside a status label. | none; limitation |
| Expenses | 4 | Picture 5 (**4**), in group | *absent* | Small totals icon placeholder. | ALT_TEXT via `#xml=` path; limitation |
| Expenses | 4 | Rectangle 6 (5), in group | Status | Status label reading OK. | none |
| Receipts (2, `sheet2.xml`), `drawing2.xml` | 1 | Picture 1 (2) | Archive | *absent* | ALT_TEXT via `#id=2` |

| ruleId | worksheet | target | findingId |
| --- | --- | --- | --- |
| ALT_TEXT | Expenses | `xl/drawings/drawing1.xml#id=3` | `7a8a8a06d00af9088ae46ffbc967e5c830aa9efdfe92752be4a139974c0870de` |
| ALT_TEXT | Expenses | `xl/drawings/drawing1.xml#xml=/wsDr[1]/twoCellAnchor[1]/pic[1]/nvPicPr[1]/cNvPr[1]` | `55cc8485e66a3c0a6de3fd7c0c2024226f0d094d2b8411b02e44a9fdd7869420` |
| ALT_TEXT | Expenses | `xl/drawings/drawing1.xml#xml=/wsDr[1]/twoCellAnchor[4]/grpSp[1]/pic[1]/nvPicPr[1]/cNvPr[1]` | `efe2d622ffd60839bc11bd4e5e2c68f143c7cae74581ba6e3ddc5384b88315f5` |
| ALT_TEXT | Receipts | `xl/drawings/drawing2.xml#id=2` | `afbc43e5b8e0831f93bdff5d6a7ce1fb6412bb571181411cc7760b95c456e010` |

### `multiple_drawings.xlsx`

Drawings must be found through each sheet's relationships, not by number or sheet order. Object IDs restart at 2
in every part, and the Archive relationship uses an absolute target (`/xl/drawings/drawing4.xml`).

| Sheet (sheetId, part, state) | Drawing | Object (id) | Title | Description | Intended finding |
| --- | --- | --- | --- | --- | --- |
| Summary (1, `sheet1.xml`) | `drawing3.xml` | Chart 1 (2) | Costs by item | Column chart: rent $1,200, travel $300, supplies $200. | none |
| Summary | `drawing3.xml` | Picture 2 (3) | Team logo | one space | ALT_TEXT |
| Expenses (2, `sheet2.xml`) | `drawing1.xml` | Picture 1 (2) | Receipt | Scanned travel receipt placeholder. | none |
| Expenses | `drawing1.xml` | Rectangle 2 (3) | *absent* | Callout noting that rent is the largest cost. | ALT_TEXT |
| Hidden costs (3, `sheet3.xml`, hidden) | `drawing2.xml` | Picture 1 (2) | *absent* | *absent* | ALT_TEXT (one finding) |
| Notes (4, `sheet4.xml`) | none | | | | none |
| Archive (5, `sheet5.xml`, veryHidden) | `drawing4.xml` | Picture 1 (2) | Divider | *absent* | ALT_TEXT |

| ruleId | worksheet | target | findingId |
| --- | --- | --- | --- |
| ALT_TEXT | Archive | `xl/drawings/drawing4.xml#id=2` | `ada2f2de8bc5c50f2ea99b6142edb0710131be667039c542423f7e8864d66b87` |
| ALT_TEXT | Expenses | `xl/drawings/drawing1.xml#id=3` | `e4769cfcd2e3a2c1c9cf55b75c7e19b6d675adc7b7bfe787edea5901da99b1ae` |
| ALT_TEXT | Hidden costs | `xl/drawings/drawing2.xml#id=2` | `93eb347d74c5667fe3213cd294684dc12f9f8b96703fbc585c3e3267f4e30337` |
| ALT_TEXT | Summary | `xl/drawings/drawing3.xml#id=3` | `632f6a1476f41499aa6db6ae92e71a1ca666d61f417222b285c54bc91e453891` |

### Edge-fixture policy notes

- **U+200B and U+FEFF count as present.** Neither is in the contract's explicit White_Space list, so a field
  holding only one of them is not blank. A system that trims with its language's default instead of that list
  may disagree, which is what these rows are meant to catch. U+0085 is in the list; Python's `str.strip()`
  removes it too, but some trims do not.
- **The long s.** The contract says ASCII `(?i)^Sheet[0-9]+$`. Python's `re` without `re.ASCII` matches
  U+017F against `s` under `(?i)`; the cross-check caught this in Team 12's own oracle, which now uses `re.ASCII`.
- **Repeated-ID disclosure** is required to be nonempty only; the spec says to disclose but fixes no wording.
- All three rely on the same pod-pending title/description defaults as the seeded rows above.

## `corrupt.xlsx`

The 4-byte ZIP local-file signature `PK\x03\x04` followed by repeated plain text. Not a readable package.
Only the 422 status and the project error envelope are asserted; no error code is agreed.

## Rejected fixtures (added 2026-10-31)

The Phase 3 manifest's seven `rejected_fixture` cases. Each starts from the same valid one-sheet workbook
(sheet "Notes", no drawings) and adds exactly one defect, so a rejection can only come from that defect. As for
`corrupt.xlsx`, only the 422 status and the project error envelope are asserted. Built by the same script.

| Fixture | Case | The one defect |
| --- | --- | --- |
| `zip_traversal` | P3-INPUT-ZIP-TRAVERSAL | An extra entry named `../outside.xml` |
| `zip_duplicate` | P3-INPUT-ZIP-DUPLICATE | `xl/worksheets/sheet1.xml` appears twice, with different contents |
| `xml_dtd` | P3-INPUT-XML-DTD | `sheet1.xml` declares `<!DOCTYPE worksheet [<!ENTITY team "Team 12">]>` and uses `&team;`; internal entity only |
| `macro_parts` | P3-INPUT-MACRO-PARTS | A `.xlsx` (non-macro main content type) with `xl/vbaProject.bin`, its content type and relationship; the part is a compound-file signature plus inert padding, no macro code |
| `encrypted_zip` | P3-INPUT-ENCRYPTED-ZIP | Every entry encrypted with traditional PKWARE (ZipCrypto) encryption; the encryption header is derived from the entry name so the bytes are reproducible. Not Office CFB encryption |
| `protected_sheet` | P3-INPUT-PROTECTED-SHEET | Active worksheet protection (`sheet="1"`) with a real SHA-512 password hash; structure unprotected |
| `protected_structure` | P3-INPUT-PROTECTED-STRUCTURE | `workbookProtection lockStructure="1"` with a real SHA-512 password hash; no worksheet protection |

The fixture password is `team12-fixture`; it protects nothing. `protected_sheet`, `protected_structure` and
`macro_parts` load in openpyxl. These seven have not been opened in Excel or reviewed.
