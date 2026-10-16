# Accessibility Checker Notes

These local prototypes check selected workbook features. Their detailed rules
are developer-authorized, not established as shared team/pod requirements.
WCAG references below identify partial coverage, not compliance certification.

## Usage

Use Python 3.10+ from the repository root. Both checkers use only the standard
library and assume a valid, readable `.xlsx` file. They never modify or save it.

```bash
python3 -m venv .venv
.venv/bin/python
```

```python
from worksheet_names import check_worksheet_names
from image_alt_text import check_image_alt_text

path = "/path/to/workbook.xlsx"
print(check_worksheet_names(path))
print(check_image_alt_text(path))
```

Replace the path with an actual workbook. `pathlib.Path` is also accepted.
Relative paths are resolved from the working directory. No CLI is provided.

Both functions return a list of dictionaries and inspect visible worksheets
only; `hidden` and `veryHidden` are excluded. Input validation and custom error
handling are not implemented. File/XML errors propagate to the caller.

## Worksheet Names — 2.4.2 Page Titled

`worksheet_names.py`: `check_worksheet_names(path)` checks name features only.
Related criterion: **2.4.6 Headings and Labels**, which reuses sheet-name results
in the project's WCAG mapping guide.

For comparison only, remove whitespace with `"".join(name.split())` and convert
to lowercase. Return original names in workbook order; exclude chartsheets.

| Normalized full match | Reason | Interpretation |
| --- | --- | --- |
| `sheet[0-9]*` | `DEFAULT_LIKE` | Similar to a default name |
| `[0-9]+` | `NUMERIC_REQUIRES_REVIEW` | Confirm whether the name is descriptive |

Examples: `Sheet`, `sheet1`, `SHEET1`, and `Sheet 1` match the first rule.
`1`, `123`, and `2025` match the second. Year-like names are not exempted or
declared inappropriate. `Sheet1 Budget`, `Worksheet1`, and non-ASCII digits do
not match. Cell content, workbook title properties, and name relevance are not
evaluated.

```python
[
    {"name": "Sheet 1", "reason": "DEFAULT_LIKE"},
    {"name": "2025", "reason": "NUMERIC_REQUIRES_REVIEW"},
]
```

## Image Descriptions — 1.1.1 Non-text Content

`image_alt_text.py`: `check_image_alt_text(path)` follows workbook → worksheet →
drawing relationships, rather than matching part filename numbers. It reads
`pic/nvPicPr/cNvPr/@descr` for ordinary pictures directly inside `oneCellAnchor`,
`twoCellAnchor`, or `absoluteAnchor`.

| Description state | Reason |
| --- | --- |
| Attribute absent | `MISSING_DESCRIPTION` |
| Empty string | `EMPTY_DESCRIPTION` |
| Whitespace only | `WHITESPACE_DESCRIPTION` |

Nonblank descriptions are omitted from the missing list; their quality is not
assessed. Titles, image names, and filenames do not substitute for descriptions.
The function does not return the text of descriptions that are present.

An explicit `adec:decorative` extension under `cNvPr/extLst/ext` exempts a picture
when `val` is `1` or `true`. Its namespace is
`http://schemas.microsoft.com/office/drawing/2017/decorative`. No visual or
filename-based inference is used.

```python
[
    {
        "worksheet": "Budget",
        "drawing": "xl/drawings/drawing90.xml",
        "image_id": "1",
        "image_name": "photo1.png",
        "reason": "MISSING_DESCRIPTION",
    }
]
```

Use worksheet, drawing part, and image ID together to identify an image.
Results follow worksheet order and drawing XML traversal order.

Charts, shapes, backgrounds, and in-cell images are out of scope. Grouped,
compatibility-wrapped, and legacy representations remain unexamined. Image
bytes are not decoded. No descriptions are generated or written.

## Verification and Limits

```bash
.venv/bin/python -m unittest discover -s tests -v
```

The implementation was verified with 13 passing tests: 6 worksheet-name tests
and 7 image tests. They cover matching/exclusions, original names and ordering,
description states, decorative flags, relationship mapping, and unchanged source
bytes. Fixtures contain synthetic ZIP/XML metadata, not complete Excel files.
Reading an actual Excel-created workbook remains unverified.

An empty result means no findings within the implemented scope. Unsupported
content and the workbook as a whole must not be reported as having passed.
Criterion numbers and names follow
[the WCAG mapping guide](WCAG_2.1_Excel_Automated_Validation_Methods.md);
neither checker covers its entire criterion.
