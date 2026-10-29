# Existing-checker readiness before adding four Phase 4 checks

The developer authorized these four increments on 2026-10-29. This records
implementation and executed evidence, separately from cross-team adoption.
Criterion coverage remains partial: `1.1.1 Non-text Content`, `2.4.2 Page Titled`,
related `2.4.6 Headings and Labels`. There is no full-WCAG or six-rule verdict.

## Completed increments

| Stage | Result | Executed regression | Commit |
|---|---|---|---|
| 1 | Ambiguous parent group metadata retains parent review and safe child traversal; no decorative inheritance or wrapper selection | 21 ALT_TEXT / 87 total | `d4ef1cc` |
| 2 | Actual drawing ownership distinguishes multiple sheets from repeated/unused references; shared missing-alt becomes manual | 24 ALT_TEXT / 90 total | `ef6e7b3` |
| 3 | Whole-workbook rename structural preflight gates classification without changing default-name matching, targets or identity | 4 name + 14 preflight / 104 total | `61a5df8` |
| 4 | Integration and documentation consistency; no production behavior added | 2 new integration / 106 total | This verification increment |

AE-013/014/015 in [the decision log](assumptions_and_extensions.md) record the
scope, rationale, approval and verification separately. The earlier 85-test
baseline passed freshly before stage 1. The existing common-foundation and
object-target changes were retained rather than reimplemented. No dependencies
were added and no push was performed for these increments.

## Final common contract

Only ALT_TEXT and WORKSHEET_NAME are registered, in that execution order.
TABLE_HEADER, MERGED_CELLS, LINK_TEXT and COLOR_CONTRAST have no active success
stub; the provisional legacy table function stays inactive. New findings use
the original-byte SHA-256 and ruleset 2.0.0 compact-JSON identity recipe.
Each finding still has the eight existing fields. Findings sort by
`(ruleId, worksheet, target)`; limitations deduplicate only identical strings
then sort by Unicode code point. Different object targets are retained.
Processing/read failures propagate rather than producing empty success.
Source workbooks and historical audits/fixture snapshots are not rewritten.

All three active entry points return list-compatible Findings with separate
limitations. Ordinary JSON list serialization does not carry that attribute;
consumers must explicitly transport it. Rename classification is documented
in [the finite read-only profile](rename_safety_profile.md). No editor or
currentValue, API, persistence, UI, or new individual rule is included.

## Executed verification

Using the existing project .venv on Python 3.14.0:

```bash
.venv/bin/python -m unittest discover -s tests -p test_image_alt_text.py -q
.venv/bin/python -m unittest discover -s tests -p test_rename_safety.py -q
.venv/bin/python -m unittest discover -s tests -p test_readiness_integration.py -q
.venv/bin/python -m unittest discover -s tests -q
.venv/bin/python -m pip check
git diff --check
```

Results: 24 ALT_TEXT, 14 rename-preflight, 2 integration, and all 106 tests pass;
no broken dependencies or whitespace errors. The complete historical
`migration_complete.xlsx` and its expected JSON match starting commit 52274c8
byte-for-byte; the dependency list also matches. Existing tests continue to
cover independent finding-ID vectors, exact limitation normalization, duplicate
finding retention, source bytes and failure propagation.

`test_readiness_integration.py` creates a separate complete XLSX with ordinary
formulas, escaped-apostrophe sheet names, workbook/local defined names, data
validation, conditional formatting, internal hyperlink location and a hidden
chartsheet. openpyxl reads the generated file; both checks retain supported
user-input classifications. A separate copy of the historical complete package
is modified to share a drawing, exercising both manual classifications and
the aggregated output contract. Checkers never save these files.

These are automated generated-XLSX and synthetic-OOXML checks. Microsoft Excel
has not been launched; no manual no-repair, accessibility, rewritten-reference
or output-preservation evidence is claimed. Python 3.10, memory/performance and
exhaustive schema variants remain unverified. Unknown rename profiles, structured
references and intersection syntax stay manual with explicit limitations.

The existing two checks/common infrastructure are ready for the next authorized
individual-check increment within these stated profiles. Four new checks and
remediation still require their own implementation/evidence; this is not a
claim that the whole Phase 4 system or an editing engine is complete.
