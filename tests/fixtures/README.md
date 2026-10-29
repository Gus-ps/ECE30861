# Library migration fixture

`migration_complete.xlsx` is a complete package created with openpyxl 3.1.5
on 2026-10-29 **before** modifying checker behavior. It contains:

- `Sheet01`, a visible worksheet with Japanese text, a formula using IMAGE,
  a formal table with `headerRowCount=0`, and a bar chart without alternative
  text title/description;
- `sheet2`, a veryHidden worksheet;
- `Sheet3`, a hidden chartsheet containing a second bar chart;
- absent workbook Title metadata.

This exercises partial `1.1.1 Non-text Content`, `2.4.2 Page Titled` (related
`2.4.6 Headings and Labels`), and inactive `1.3.1 Info and Relationships`.

`migration_complete.expected.json` records the original source SHA-256 and
the pre-migration outputs of the runner plus inactive Title/Table functions.
It is a **migration regression snapshot**, not an independently reviewed
accessibility oracle or evidence of full requirements conformance. Exact
comparison includes messages, IDs, targets, ordering and limitations.
Do not regenerate expectations using the implementation under test.

The Phase 4 common foundation does not rewrite this 1.0.0 snapshot.
`tests/test_library_migration.py` verifies the stored historical identities,
then independently computes the authorized 2.0.0 IDs and normalizes expected
limitations in memory. All other finding fields and inactive-check results
remain exact comparisons.

The file is read successfully with openpyxl, but has not been opened in the
Excel UI to check for repair warnings. openpyxl's full workbook loader drops
the hidden chartsheet state; the original XML and ChildSheet model preserve it.
Checker tests verify that metadata separately. Checks never save this fixture.
Existing synthetic ZIP/XML tests remain unchanged and complement this package.
