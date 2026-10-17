# Accessibility Checker Notes

These local prototypes check selected workbook features. Their detailed rules
are developer-authorized, not established as shared team/pod requirements.
WCAG references below identify partial coverage, not compliance certification.

## Usage

Use Python 3.10+ from the repository root. All checkers use only the standard
library and assume a valid, readable `.xlsx` file. They never modify or save it.

```bash
python3 -m venv .venv
.venv/bin/python
```

```python
from accessibility_checker.checks.worksheet_names import check_worksheet_names
from accessibility_checker.checks.image_alt_text import check_image_alt_text
from accessibility_checker.checks.workbook_title import check_workbook_title

path = "/path/to/workbook.xlsx"
print(check_worksheet_names(path))
print(check_image_alt_text(path))
print(check_workbook_title(path))
```

Replace the path with an actual workbook. `pathlib.Path` is also accepted.
Relative paths are resolved from the working directory. No CLI is provided.

All functions return a list of dictionaries. Worksheet-name and image checks
inspect visible worksheets only; `hidden` and `veryHidden` are excluded.
The Title check examines workbook metadata, independently of worksheet states.
Input validation and custom error handling are not implemented. File/XML errors
propagate to the caller.

## Worksheet Names — 2.4.2 Page Titled

`accessibility_checker/checks/worksheet_names.py`: `check_worksheet_names(path)` checks name features only.
Related criterion: **2.4.6 Headings and Labels**, which reuses sheet-name results
in the project's WCAG mapping guide.

For comparison only, remove whitespace with `"".join(name.split())` and convert
to lowercase. Preserve original names; exclude chartsheets.

| Normalized full match | Message                                         | Interpretation              |
| --------------------- | ----------------------------------------------- | --------------------------- |
| `sheet[0-9]*`         | Name resembles a default name                   | Request a descriptive name  |
| `[0-9]+`              | Numeric name; confirm whether it is descriptive | Meaning requires user input |

Examples: `Sheet`, `sheet1`, `SHEET1`, and `Sheet 1` match the first rule.
`1`, `123`, and `2025` match the second. Year-like names are not exempted or
declared inappropriate. `Sheet1 Budget`, `Worksheet1`, and non-ASCII digits do
not match. Cell content, workbook title properties, and name relevance are not
evaluated.

```json
[
    {
        "findingId": "c2d867af6d68cd291d9654a93c1279f2d9f2f934f14c23ff789a0c128404fba9",
        "ruleId": "WORKSHEET_NAME",
        "category": "WORKSHEET_NAME",
        "worksheet": "Sheet 1",
        "target": "Sheet 1",
        "classification": "REQUIRES_USER_INPUT",
        "message": "Worksheet name resembles a default name.",
        "recommendation": "Confirm the worksheet's meaning and provide a descriptive name if needed."
    }
]
```

## Image Descriptions — 1.1.1 Non-text Content

`accessibility_checker/checks/image_alt_text.py`: `check_image_alt_text(path)` follows workbook → worksheet →
drawing relationships, rather than matching part filename numbers. It reads
`pic/nvPicPr/cNvPr/@descr` for ordinary pictures directly inside `oneCellAnchor`,
`twoCellAnchor`, or `absoluteAnchor`.

| Description state | Message                              |
| ----------------- | ------------------------------------ |
| Attribute absent  | Description is missing               |
| Empty string      | Description is empty                 |
| Whitespace only   | Description contains only whitespace |

Nonblank descriptions are omitted from the missing list; their quality is not
assessed. Titles, image names, and filenames do not substitute for descriptions.
The function does not return the text of descriptions that are present.

An explicit `adec:decorative` extension under `cNvPr/extLst/ext` exempts a picture
when `val` is `1` or `true`. Its namespace is
`http://schemas.microsoft.com/office/drawing/2017/decorative`. No visual or
filename-based inference is used.

```json
[
    {
        "findingId": "49438197251a92da08ff3e90aa4b4ec05ea02a75ce8eb48e3746f8e9a0b44e51",
        "ruleId": "ALT_TEXT",
        "category": "NON_TEXT_CONTENT",
        "worksheet": "Budget",
        "target": "xl/drawings/drawing90.xml#id=1",
        "classification": "REQUIRES_USER_INPUT",
        "message": "Image alternative text description is missing.",
        "recommendation": "Provide an alternative text description that conveys the image's purpose."
    }
]
```

The image target combines the drawing part and its image ID. Together with
`worksheet`, it identifies the image even when object names repeat.

Charts, shapes, backgrounds, and in-cell images are out of scope. Grouped,
compatibility-wrapped, and legacy representations remain unexamined. Image
bytes are not decoded. No descriptions are generated or written.

## Workbook Title — 2.4.2 Page Titled

`accessibility_checker/checks/workbook_title.py`: `check_workbook_title(path)` reads the package's
core-properties relationship in `_rels/.rels`, then the referenced part's
`dc:title` (`http://purl.org/dc/elements/1.1/`). This normally resides in
`docProps/core.xml`; the checker follows the relationship rather than assuming
that filename.

Return exactly one finding if core properties are absent, the title element
is absent, or the title is empty/whitespace-only. Any nonwhitespace text returns
`[]`; generic titles, filename equality, and content relevance are not checked.
No properties or workbooks are saved.

The developer explicitly specifies `REQUIRES_USER_INPUT`. Rule/category
`WORKBOOK_TITLE` and worksheet/target `__WORKBOOK__` are provisional choices,
stored as constants in this module and awaiting team/pod confirmation.
The sentinel can collide with a real worksheet name. `WORKBOOK_TITLE` is not
a confirmed allowed category in the shared HTTP contract, so full contract
conformance is not claimed. Replace these constants after agreement.

The checker reuses `make_finding_id` unchanged: different workbooks with a
missing title currently receive the same ID. No new identity policy is added.

## Finding Format and Temporary IDs

All three checkers use the HTTP contract's eight required string fields:
`findingId`, `ruleId`, `category`, `worksheet`, `target`, `classification`,
`message`, and `recommendation`. Messages/recommendations are 1–500 characters.
The previous `name`/`reason` and image-detail fields are no longer returned;
messages retain the distinctions between detected conditions.

| Checker            | Temporary rule ID | Category                                 | Target                    |
| ------------------ | ----------------- | ---------------------------------------- | ------------------------- |
| Worksheet names    | `WORKSHEET_NAME`  | `WORKSHEET_NAME`                         | Original worksheet name   |
| Image descriptions | `ALT_TEXT`        | `NON_TEXT_CONTENT`                       | Drawing part plus `#id=N` |
| Workbook Title     | `WORKBOOK_TITLE`  | `WORKBOOK_TITLE` (provisional extension) | `__WORKBOOK__`            |

All use `REQUIRES_USER_INPUT`. Multi-finding results are sorted lexicographically by
`ruleId`, `worksheet`, then `target`, rather than workbook order.

**TODO: Update rule IDs when the approved shared catalog is available.**
These temporary IDs are developer-authorized placeholders, not confirmed
catalog entries; WCAG criterion numbers remain separate references.

`accessibility_checker/finding_ids.py` provides `make_finding_id(rule_id, worksheet, target)`, used by
all checkers. It hashes the three strings into a repeatable 64-character hex
ID, within the contract's identifier syntax. Keeping generation in one function
makes a later replacement local to that function and its call sites.

**TODO: Replace temporary ID generation with the agreed workbook/ruleset-aware
policy.** Current IDs omit workbook and ruleset identity, so identical rule,
worksheet, and target values in different workbooks share an ID. This is not
full conformance to the contract's identity semantics. Future context inputs
will need to be added when the policy is agreed; no placeholder workbook IDs
or ruleset versions are fabricated now.

## Verification and Limits

```bash
.venv/bin/python -m unittest discover -s tests -v
```

All 25 tests passed: 7 worksheet-name, 8 image, 8 workbook-title, and 2 temporary-ID
tests. Title tests cover missing/empty/whitespace/nonblank values, absent core
properties, part relationships, finding shape, repeatability, and unchanged
source bytes. Existing detection, exclusion, and finding tests also pass.
Fixtures contain synthetic ZIP/XML metadata, not complete Excel files.

The Title checker also read local `test.xlsx` (one finding, unchanged source
bytes). Its Application metadata says `Microsoft Excel`, but creation provenance
is not independently verified. Full real-Excel validation remains unverified.

An empty result means no findings within the implemented scope. Unsupported
content and the workbook as a whole must not be reported as having passed.
Criterion numbers and names follow
[the WCAG mapping guide](WCAG_2.1_Excel_Automated_Validation_Methods.md);
none of these checkers covers its entire criterion.
