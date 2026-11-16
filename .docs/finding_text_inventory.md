# Finding text inventory — ruleset 2.0.0

This is preparation for AC-05 explanation/recommendation review and the outstanding
Phase 5 human explanation review. It does not replace human review, establish
full WCAG coverage, or claim legal compliance. Scope: the six active rules only.
legacy_table_headers.py and workbook_title.py are inactive and excluded.

## Review criteria and authority

The shared finding contract requires nonblank plain-text message/recommendation,
each 1–500 Unicode code points. Prose must accurately explain the issue and remain
stable for the same target on repeated identical audits. Limitations are
deterministic, deduplicated and sorted by Unicode code point; their individual
length has no specified 500-code-point bound. Cross-team prose need not be identical.
Finding IDs hash compact JSON of (source SHA256, ruleset, ruleId, worksheet, target);
message/recommendation/limitations are excluded. Wording changes would preserve
IDs but may break other teams' text assertions. All changes are therefore deferred
pending Pod coordination. Developer requested this inventory, not wording changes.

Sources reviewed: shared Phase 4 contract sections 3 and 7 (text, ordering and
identity), AC-05 human review, and Phase 5 specification 3.0.0 section 2 (human
explanation review still open). The requirements are summarized here so reviewers
do not need unpublished materials. See [AE-023](assumptions_and_extensions.md).
Requirement traceability: shared finding-text contract (§3/§7), AC-05.
A specific REQ-XX mapping for prose was not established by the reviewed shared
contract; no new requirement ID is invented. Criterion references
are mappings, not approval of prototype behavior:

| Rule | Partial criterion reference |
|---|---|
| ALT_TEXT | 1.1.1 Non-text Content |
| WORKSHEET_NAME | 2.4.2 Page Titled; related 2.4.6 Headings and Labels |
| TABLE_HEADER / MERGED_CELLS | 1.3.1 Info and Relationships |
| LINK_TEXT | 2.4.4 Link Purpose (In Context) |
| COLOR_CONTRAST | 1.4.1 Use of Color; 1.4.3 Contrast (Minimum) |

## Reproduction and scope

Run `.venv/bin/python -m scripts.export_finding_texts` from the repository root.
Optional positional workbook paths and --output select inputs/output. Default:
six_rule_seeded.xlsx and every deployment/*.xlsx fixture, sorted by relative path.
The exporter calls the real check_workbook, normalizes only formatted contrast
numbers into placeholders, deduplicates by rule/classification/message template/
recommendation, and sorts output. Limitation strings retain exact locations and
text; they are not heuristically reduced into reasons. Source tables below supply
the limitation templates and unexercised branches. No new dependencies.

## Message families and bounds

Counts below are distinct message forms with placeholders, not finding counts or
unique IDs. COLOR_CONTRAST resolver reasons have additional finite subvariants
listed in its source table. Observed examples do not prove branch coverage.

| Rule | Message forms | Classification / reason | Dynamic message values and maximum analysis |
|---|---:|---|---|
| ALT_TEXT | 5 | REQUIRES_USER_INPUT: missing title, description, or both; MANUAL_REVIEW: decorative or unsupported | Missing-field labels are a finite set; no title/description values embedded. emit slices both fields to 500. |
| WORKSHEET_NAME | 1 | REQUIRES_USER_INPUT safe rename / MANUAL_REVIEW unsafe inventory; recommendations differ | Fixed message; sheet name does not enter message/recommendation (maximum valid name 31 code points). |
| TABLE_HEADER | 2 | REQUIRES_USER_INPUT confirm first row / MANUAL_REVIEW unsafe structure | Both fixed; existing labels (even very long) are not embedded. |
| MERGED_CELLS | 3 | MANUAL_REVIEW external worksheet / conflicting declarations / populated merge | Fixed; location and sheet name are separate fields. Conflict takes precedence. |
| LINK_TEXT | 1 | REQUIRES_USER_INPUT simple editable label / MANUAL_REVIEW formula or unsupported representation | Fixed; label, destination and formula text are not embedded. |
| COLOR_CONTRAST | 7 | MANUAL_REVIEW: low ratio, nonneutral, both, external worksheet, unresolved extension, conditional range, unresolved rendering | Ratio bounded 1–21 (formatted to two decimals), threshold 3.0/4.5. Combined low/nonneutral maximum 150 code points. Resolver errors use finite fixed reasons; style-index kind is a controlled identifier. |

All recommendations are fixed strings (maximum across source recommendations 93
code points). No unbounded user text enters active message/recommendation.
No reproducible >500 case found by source analysis. This is not arbitrary-package
fuzzing. Large/hostile package paths, XML names, formula function names and sheet
names CAN make limitations long; no truncation or aggregation has been added.
The 100,000-code-point raw cell fixture tests that values do not leak into prose;
a 31-code-point sheet name and long hyperlink destination are included.
Style/color helper errors that propagate as processing failures are not findings.

## Observed message/recommendation pairs

Exact examples from the default fixture export; fixtures and all exact limitations
can be reproduced with the script. “Template” normalizes contrast numbers only.

| Rule | Classification | Message template | Actual example | Recommendation | Notes |
|---|---|---|---|---|---|

| ALT_TEXT | MANUAL_REVIEW | Object is marked decorative; confirm that it conveys no information. | Object is marked decorative; confirm that it conveys no information. | Confirm the decorative designation or provide alternative text title and description. | Fixture observed; human accuracy/actionability review pending. |
| ALT_TEXT | MANUAL_REVIEW | Object requires manual accessibility review. | Object requires manual accessibility review. | Inspect the object and confirm its alternative text or decorative designation. | Fixture observed; human accuracy/actionability review pending. |
| ALT_TEXT | REQUIRES_USER_INPUT | Object is missing alternative text description (descr). | Object is missing alternative text description (descr). | Provide the missing accessibility title and/or description. | Fixture observed; human accuracy/actionability review pending. |
| ALT_TEXT | REQUIRES_USER_INPUT | Object is missing alternative text title and description (descr). | Object is missing alternative text title and description (descr). | Provide the missing accessibility title and/or description. | Fixture observed; human accuracy/actionability review pending. |
| ALT_TEXT | REQUIRES_USER_INPUT | Object is missing alternative text title. | Object is missing alternative text title. | Provide the missing accessibility title and/or description. | Fixture observed; human accuracy/actionability review pending. |
| COLOR_CONTRAST | MANUAL_REVIEW | Static text contrast {ratio:.2f}:1 is below {threshold:.1f}:1. | Static text contrast 2.85:1 is below 4.5:1. | Review the displayed colors and provide equivalent text or structure; no colors were changed. | Fixture observed; human accuracy/actionability review pending. |
| COLOR_CONTRAST | MANUAL_REVIEW | Static text contrast {ratio:.2f}:1 is below {threshold:.1f}:1. Nonneutral font or fill color may convey meaning without equivalent text or structure. | Static text contrast 4.00:1 is below 4.5:1. Nonneutral font or fill color may convey meaning without equivalent text or structure. | Review the displayed colors and provide equivalent text or structure; no colors were changed. | Fixture observed; human accuracy/actionability review pending. |
| LINK_TEXT | MANUAL_REVIEW | Hyperlink label requires review for descriptive link purpose. | Hyperlink label requires review for descriptive link purpose. | Provide descriptive link text while preserving the destination; no link was changed. | Fixture observed; human accuracy/actionability review pending. |
| LINK_TEXT | REQUIRES_USER_INPUT | Hyperlink label requires review for descriptive link purpose. | Hyperlink label requires review for descriptive link purpose. | Provide descriptive link text while preserving the destination; no link was changed. | Fixture observed; human accuracy/actionability review pending. |
| MERGED_CELLS | MANUAL_REVIEW | Populated merged cells may impede navigation, including title merges. | Populated merged cells may impede navigation, including title merges. | Review the merged range and its effect on navigation; no cells were changed. | Fixture observed; human accuracy/actionability review pending. |
| TABLE_HEADER | REQUIRES_USER_INPUT | Confirm the existing first row as the header. | Confirm the existing first row as the header. | Review the reported rectangle and its existing labels; no table or cells were changed. | Fixture observed; human accuracy/actionability review pending. |
| WORKSHEET_NAME | MANUAL_REVIEW | Worksheet name is a default Sheet name with a positive numeric suffix. | Worksheet name is a default Sheet name with a positive numeric suffix. | Review workbook reference safety before renaming this worksheet. | Fixture observed; human accuracy/actionability review pending. |
| WORKSHEET_NAME | REQUIRES_USER_INPUT | Worksheet name is a default Sheet name with a positive numeric suffix. | Worksheet name is a default Sheet name with a positive numeric suffix. | Provide a descriptive worksheet name based on its purpose. | Fixture observed; human accuracy/actionability review pending. |

## Complete source prose index, including unexercised reasons

The tables enumerate source prose literals/formatted templates, not just fixture
output. Message/recommendation literals above are repeated here for traceability.
Reason fragments are combined with the wrapper described under each rule.
Constant labels used in formulas/errors may be supporting fragments rather than
standalone findings. XML/path placeholders and reason wrappers have no separate
500-point bound. Processing exceptions are not counted as message forms.
All source branches were inspected; source presence is not execution evidence.


### ALT_TEXT

REQUIRES_USER_INPUT only for the three missing-field forms; decorative/unsupported reasons are MANUAL_REVIEW.

Limitation wrapper: {worksheet}: {target}: {reason}; audit-only exclusions may use a rule prefix.

Dynamic values in limitations include location/sheet and, where indicated, source metadata. They do not enter the corresponding generic message.

| Source | Prose template / reason | Dynamic values | Length / observation |
|---|---|---|---|
| [checks/image_alt_text.py:89](../accessibility_checker/checks/image_alt_text.py#L89) | Ambiguous chart relationship requires manual review. | none | 52 code points, fixed literal/fragment |
| [checks/image_alt_text.py:76](../accessibility_checker/checks/image_alt_text.py#L76) | Ambiguous decorative metadata requires manual review. | none | 53 code points, fixed literal/fragment |
| [checks/image_alt_text.py:301](../accessibility_checker/checks/image_alt_text.py#L301) | Cell-image or IMAGE-formula representation requires manual review. | none | 66 code points, fixed literal/fragment |
| [checks/image_alt_text.py:211](../accessibility_checker/checks/image_alt_text.py#L211) | Cell-image/rich-data representation is not automatically assessed. | none | 66 code points, fixed literal/fragment |
| [checks/image_alt_text.py:409](../accessibility_checker/checks/image_alt_text.py#L409) | Confirm the decorative designation or provide alternative text title and description. | none | 85 code points, fixed literal/fragment |
| [checks/image_alt_text.py:364](../accessibility_checker/checks/image_alt_text.py#L364) | Decorative group inheritance requires manual review. | none | 52 code points, fixed literal/fragment |
| [checks/image_alt_text.py:425](../accessibility_checker/checks/image_alt_text.py#L425) | Drawing part is shared by multiple owning sheets; alternative-text editing is ambiguous. | none | 88 code points, fixed literal/fragment |
| [checks/image_alt_text.py:395](../accessibility_checker/checks/image_alt_text.py#L395) | External object content is not fetched. | none | 39 code points, fixed literal/fragment |
| [checks/image_alt_text.py:54](../accessibility_checker/checks/image_alt_text.py#L54) | External object content is not fetched; manual review is required. | none | 66 code points, fixed literal/fragment |
| [checks/image_alt_text.py:315](../accessibility_checker/checks/image_alt_text.py#L315) | External or nonstandard drawing relationship is not automatically assessed. | none | 75 code points, fixed literal/fragment |
| [checks/image_alt_text.py:222](../accessibility_checker/checks/image_alt_text.py#L222) | External sheet content is not fetched. | none | 38 code points, fixed literal/fragment |
| [checks/image_alt_text.py:197](../accessibility_checker/checks/image_alt_text.py#L197) | Inspect the object and confirm its alternative text or decorative designation. | none | 78 code points, fixed literal/fragment |
| [checks/image_alt_text.py:279](../accessibility_checker/checks/image_alt_text.py#L279) | Legacy VML object requires manual review. | none | 41 code points, fixed literal/fragment |
| [checks/image_alt_text.py:286](../accessibility_checker/checks/image_alt_text.py#L286) | Legacy, background, control, embedded, or external object is not automatically assessed. | none | 88 code points, fixed literal/fragment |
| [checks/image_alt_text.py:66](../accessibility_checker/checks/image_alt_text.py#L66) | Missing or ambiguous nonvisual properties require manual review. | none | 64 code points, fixed literal/fragment |
| [checks/image_alt_text.py:352](../accessibility_checker/checks/image_alt_text.py#L352) | Missing or duplicate drawing ID; indexed XML location used. | none | 59 code points, fixed literal/fragment |
| [checks/image_alt_text.py:86](../accessibility_checker/checks/image_alt_text.py#L86) | Nonstandard graphicFrame requires manual review. | none | 48 code points, fixed literal/fragment |
| [checks/image_alt_text.py:408](../accessibility_checker/checks/image_alt_text.py#L408) | Object is marked decorative; confirm that it conveys no information. | none | 68 code points, fixed literal/fragment |
| [checks/image_alt_text.py:432](../accessibility_checker/checks/image_alt_text.py#L432) | Object is missing alternative text  | none | 35 code points, fixed literal/fragment |
| [checks/image_alt_text.py:196](../accessibility_checker/checks/image_alt_text.py#L196) | Object requires manual accessibility review. | none | 44 code points, fixed literal/fragment |
| [checks/image_alt_text.py:435](../accessibility_checker/checks/image_alt_text.py#L435) | Provide the missing accessibility title and/or description. | none | 59 code points, fixed literal/fragment |
| [checks/image_alt_text.py:79](../accessibility_checker/checks/image_alt_text.py#L79) | Unspecified decorative flag value requires manual review. | none | 57 code points, fixed literal/fragment |
| [checks/image_alt_text.py:452](../accessibility_checker/checks/image_alt_text.py#L452) | Unsupported drawing anchor or alternate content requires review. | none | 64 code points, fixed literal/fragment |
| [checks/image_alt_text.py:329](../accessibility_checker/checks/image_alt_text.py#L329) | Unsupported drawing namespace or representation. | none | 48 code points, fixed literal/fragment |
| [checks/image_alt_text.py:342](../accessibility_checker/checks/image_alt_text.py#L342) | Unsupported drawing object: {kind}. | kind | Template; inspect wrapper and finite/unbounded metadata distinction above |
| [checks/image_alt_text.py:254](../accessibility_checker/checks/image_alt_text.py#L254) | Worksheet background picture requires manual accessibility review. | none | 66 code points, fixed literal/fragment |
| [checks/image_alt_text.py:416](../accessibility_checker/checks/image_alt_text.py#L416) | description (descr) | none | 19 code points, fixed literal/fragment |
| [checks/image_alt_text.py:189](../accessibility_checker/checks/image_alt_text.py#L189) | {worksheet}: {target}: {limitation} | worksheet; target; limitation | Template; inspect wrapper and finite/unbounded metadata distinction above |

### WORKSHEET_NAME

Inventory reasons force MANUAL_REVIEW; otherwise REQUIRES_USER_INPUT.

Limitation wrapper: {worksheet}: {target}: {reason}; audit-only exclusions may use a rule prefix.

Dynamic values in limitations include location/sheet and, where indicated, source metadata. They do not enter the corresponding generic message.

| Source | Prose template / reason | Dynamic values | Length / observation |
|---|---|---|---|
| [checks/worksheet_names.py:71](../accessibility_checker/checks/worksheet_names.py#L71) | Provide a descriptive worksheet name based on its purpose. | none | 58 code points, fixed literal/fragment |
| [checks/worksheet_names.py:83](../accessibility_checker/checks/worksheet_names.py#L83) | Review workbook reference safety before renaming this worksheet. | none | 64 code points, fixed literal/fragment |
| [checks/worksheet_names.py:70](../accessibility_checker/checks/worksheet_names.py#L70) | Worksheet name is a default Sheet name with a positive numeric suffix. | none | 70 code points, fixed literal/fragment |
| [checks/worksheet_names.py:86](../accessibility_checker/checks/worksheet_names.py#L86) | {finding['worksheet']}: {finding['target']}: {reason} | finding['worksheet']; finding['target']; reason | Template; inspect wrapper and finite/unbounded metadata distinction above |
| [rename_safety.py:366](../accessibility_checker/rename_safety.py#L366) | Ambiguous case-insensitive sheet names | none | 38 code points, fixed literal/fragment |
| [rename_safety.py:357](../accessibility_checker/rename_safety.py#L357) | Ambiguous defined-name scope | none | 28 code points, fixed literal/fragment |
| [rename_safety.py:310](../accessibility_checker/rename_safety.py#L310) | Empty formula group | none | 19 code points, fixed literal/fragment |
| [rename_safety.py:273](../accessibility_checker/rename_safety.py#L273) | Empty or unsupported formula | none | 28 code points, fixed literal/fragment |
| [rename_safety.py:369](../accessibility_checker/rename_safety.py#L369) | External sheet prevents complete reference inventory | none | 52 code points, fixed literal/fragment |
| [rename_safety.py:237](../accessibility_checker/rename_safety.py#L237) | External workbook or unsupported structured reference | none | 53 code points, fixed literal/fragment |
| [rename_safety.py:338](../accessibility_checker/rename_safety.py#L338) | Incomplete formula expression | none | 29 code points, fixed literal/fragment |
| [rename_safety.py:326](../accessibility_checker/rename_safety.py#L326) | Missing formula operand | none | 23 code points, fixed literal/fragment |
| [rename_safety.py:318](../accessibility_checker/rename_safety.py#L318) | Missing function operand | none | 24 code points, fixed literal/fragment |
| [rename_safety.py:333](../accessibility_checker/rename_safety.py#L333) | Missing postfix operand | none | 23 code points, fixed literal/fragment |
| [rename_safety.py:216](../accessibility_checker/rename_safety.py#L216) | Multiple sheet qualifiers | none | 25 code points, fixed literal/fragment |
| [rename_safety.py:301](../accessibility_checker/rename_safety.py#L301) | Reference construction or string destination: {function} | function | Template; inspect wrapper and finite/unbounded metadata distinction above |
| [rename_safety.py:263](../accessibility_checker/rename_safety.py#L263) | Reference outside the supported address bounds | none | 46 code points, fixed literal/fragment |
| [rename_safety.py:308](../accessibility_checker/rename_safety.py#L308) | Unbalanced formula grouping | none | 27 code points, fixed literal/fragment |
| [rename_safety.py:220](../accessibility_checker/rename_safety.py#L220) | Unclosed quoted sheet name | none | 26 code points, fixed literal/fragment |
| [rename_safety.py:297](../accessibility_checker/rename_safety.py#L297) | Unexpected formula opening token | none | 32 code points, fixed literal/fragment |
| [rename_safety.py:330](../accessibility_checker/rename_safety.py#L330) | Unexpected formula prefix | none | 25 code points, fixed literal/fragment |
| [rename_safety.py:322](../accessibility_checker/rename_safety.py#L322) | Unexpected function argument separator | none | 38 code points, fixed literal/fragment |
| [rename_safety.py:243](../accessibility_checker/rename_safety.py#L243) | Unknown or ambiguous sheet qualifier | none | 36 code points, fixed literal/fragment |
| [rename_safety.py:267](../accessibility_checker/rename_safety.py#L267) | Unrecognized reference/name operand | none | 35 code points, fixed literal/fragment |
| [rename_safety.py:286](../accessibility_checker/rename_safety.py#L286) | Unsupported adjacent operands/intersection | none | 42 code points, fixed literal/fragment |
| [rename_safety.py:335](../accessibility_checker/rename_safety.py#L335) | Unsupported formula construct/array | none | 35 code points, fixed literal/fragment |
| [rename_safety.py:303](../accessibility_checker/rename_safety.py#L303) | Unsupported formula function/extension: {function} | function | Template; inspect wrapper and finite/unbounded metadata distinction above |
| [rename_safety.py:292](../accessibility_checker/rename_safety.py#L292) | Unsupported formula operand | none | 27 code points, fixed literal/fragment |
| [rename_safety.py:277](../accessibility_checker/rename_safety.py#L277) | Unsupported formula tokenization ({type(error).__name__}) | type(error).__name__ | Template; inspect wrapper and finite/unbounded metadata distinction above |
| [rename_safety.py:227](../accessibility_checker/rename_safety.py#L227) | Unsupported sheet quoting | none | 25 code points, fixed literal/fragment |
| [rename_safety.py:107](../accessibility_checker/rename_safety.py#L107) | comments authors author commentList comment text t r rPr rFont charset family b i u sz scheme strike outline shadow condense extend vertAlign color rPh phoneticPr | none | 162 code points, fixed literal/fragment |
| [rename_safety.py:104](../accessibility_checker/rename_safety.py#L104) | sst si t r rPr rFont charset family b i u sz scheme strike outline shadow condense extend vertAlign color rPh phoneticPr | none | 120 code points, fixed literal/fragment |
| [rename_safety.py:363](../accessibility_checker/rename_safety.py#L363) | xl/workbook.xml: defined name: {reason} | reason | Template; inspect wrapper and finite/unbounded metadata distinction above |
| [rename_safety.py:564](../accessibility_checker/rename_safety.py#L564) | {part}: conditional threshold: {reason} | part; reason | Template; inspect wrapper and finite/unbounded metadata distinction above |
| [rename_safety.py:573](../accessibility_checker/rename_safety.py#L573) | {part}: internal hyperlink: {reason} | part; reason | Template; inspect wrapper and finite/unbounded metadata distinction above |
| [rename_safety.py:374](../accessibility_checker/rename_safety.py#L374) | {part}: multiple owning sheets make worksheet editing ambiguous | part | Template; inspect wrapper and finite/unbounded metadata distinction above |
| [rename_safety.py:523](../accessibility_checker/rename_safety.py#L523) | {part}: pivot/external/dynamic reference representation: {local} | part; local | Template; inspect wrapper and finite/unbounded metadata distinction above |
| [rename_safety.py:377](../accessibility_checker/rename_safety.py#L377) | {part}: shared drawing ownership prevents safe reference editing | part | Template; inspect wrapper and finite/unbounded metadata distinction above |
| [rename_safety.py:380](../accessibility_checker/rename_safety.py#L380) | {part}: shared table ownership prevents safe reference editing | part | Template; inspect wrapper and finite/unbounded metadata distinction above |
| [rename_safety.py:555](../accessibility_checker/rename_safety.py#L555) | {part}: shared/array/dynamic/data-table formula is outside rename profile | part | Template; inspect wrapper and finite/unbounded metadata distinction above |
| [rename_safety.py:434](../accessibility_checker/rename_safety.py#L434) | {part}: signed package cannot be safely renamed | part | Template; inspect wrapper and finite/unbounded metadata distinction above |
| [rename_safety.py:465](../accessibility_checker/rename_safety.py#L465) | {part}: unrecognized metadata element: {local} | part; local | Template; inspect wrapper and finite/unbounded metadata distinction above |
| [rename_safety.py:458](../accessibility_checker/rename_safety.py#L458) | {part}: unrecognized metadata extension may contain references | part | Template; inspect wrapper and finite/unbounded metadata distinction above |
| [rename_safety.py:463](../accessibility_checker/rename_safety.py#L463) | {part}: unrecognized metadata namespace | part | Template; inspect wrapper and finite/unbounded metadata distinction above |
| [rename_safety.py:438](../accessibility_checker/rename_safety.py#L438) | {part}: unrecognized/opaque package part may contain references | part | Template; inspect wrapper and finite/unbounded metadata distinction above |
| [rename_safety.py:506](../accessibility_checker/rename_safety.py#L506) | {part}: unsupported attribute on {local}: {attr_local} | part; local; attr_local | Template; inspect wrapper and finite/unbounded metadata distinction above |
| [rename_safety.py:544](../accessibility_checker/rename_safety.py#L544) | {part}: unsupported drawing graphicData | part | Template; inspect wrapper and finite/unbounded metadata distinction above |
| [rename_safety.py:526](../accessibility_checker/rename_safety.py#L526) | {part}: unsupported drawing hyperlink action | part | Template; inspect wrapper and finite/unbounded metadata distinction above |
| [rename_safety.py:541](../accessibility_checker/rename_safety.py#L541) | {part}: unsupported macro/query/object formula binding on {local} | part; local | Template; inspect wrapper and finite/unbounded metadata distinction above |
| [rename_safety.py:514](../accessibility_checker/rename_safety.py#L514) | {part}: unsupported namespaced attribute on {local} | part; local | Template; inspect wrapper and finite/unbounded metadata distinction above |
| [rename_safety.py:502](../accessibility_checker/rename_safety.py#L502) | {part}: unsupported reference-bearing element: {local} | part; local | Template; inspect wrapper and finite/unbounded metadata distinction above |
| [rename_safety.py:560](../accessibility_checker/rename_safety.py#L560) | {part}: {reason} | part; reason | Template; inspect wrapper and finite/unbounded metadata distinction above |
| [rename_safety.py:409](../accessibility_checker/rename_safety.py#L409) | {rel_path}: external {kind} prevents complete reference inventory | rel_path; kind | Template; inspect wrapper and finite/unbounded metadata distinction above |
| [rename_safety.py:396](../accessibility_checker/rename_safety.py#L396) | {rel_path}: internal hyperlink: {reason} | rel_path; reason | Template; inspect wrapper and finite/unbounded metadata distinction above |
| [rename_safety.py:406](../accessibility_checker/rename_safety.py#L406) | {rel_path}: unsupported reference-bearing relationship: {kind} | rel_path; kind | Template; inspect wrapper and finite/unbounded metadata distinction above |

### TABLE_HEADER

Any defect/preservation reason is MANUAL_REVIEW; safe first-row confirmation is REQUIRES_USER_INPUT.

Limitation wrapper: {worksheet}: {target}: {reason}; audit-only exclusions may use a rule prefix.

Dynamic values in limitations include location/sheet and, where indicated, source metadata. They do not enter the corresponding generic message.

| Source | Prose template / reason | Dynamic values | Length / observation |
|---|---|---|---|
| [checks/table_headers.py:203](../accessibility_checker/checks/table_headers.py#L203) | Attached {kind} requires preservation review. | kind | Template; inspect wrapper and finite/unbounded metadata distinction above |
| [checks/table_headers.py:392](../accessibility_checker/checks/table_headers.py#L392) | Column query binding or extension is unsupported. | none | 49 code points, fixed literal/fragment |
| [checks/table_headers.py:57](../accessibility_checker/checks/table_headers.py#L57) | Confirm the existing first row as the header. | none | 45 code points, fixed literal/fragment |
| [checks/table_headers.py:185](../accessibility_checker/checks/table_headers.py#L185) | Existing auto-filter overlaps the candidate. | none | 44 code points, fixed literal/fragment |
| [checks/table_headers.py:375](../accessibility_checker/checks/table_headers.py#L375) | External sheet references cannot be checked for header dependencies. | none | 68 code points, fixed literal/fragment |
| [checks/table_headers.py:432](../accessibility_checker/checks/table_headers.py#L432) | External worksheet table content is not fetched. | none | 48 code points, fixed literal/fragment |
| [checks/table_headers.py:270](../accessibility_checker/checks/table_headers.py#L270) | External/unsupported table relationships are not inspected or fetched. | none | 70 code points, fixed literal/fragment |
| [checks/table_headers.py:315](../accessibility_checker/checks/table_headers.py#L315) | Formal table rectangles overlap. | none | 32 code points, fixed literal/fragment |
| [checks/table_headers.py:338](../accessibility_checker/checks/table_headers.py#L338) | Header confirmation needs two columns and a remaining body row. | none | 63 code points, fixed literal/fragment |
| [checks/table_headers.py:157](../accessibility_checker/checks/table_headers.py#L157) | In-cell image/rich-data metadata overlaps the header candidate. | none | 63 code points, fixed literal/fragment |
| [checks/table_headers.py:164](../accessibility_checker/checks/table_headers.py#L164) | Merged cells overlap the candidate. | none | 35 code points, fixed literal/fragment |
| [checks/table_headers.py:333](../accessibility_checker/checks/table_headers.py#L333) | Merged cells overlap the table. | none | 31 code points, fixed literal/fragment |
| [checks/table_headers.py:91](../accessibility_checker/checks/table_headers.py#L91) | Missing/ambiguous table relationship ID | none | 39 code points, fixed literal/fragment |
| [checks/table_headers.py:410](../accessibility_checker/checks/table_headers.py#L410) | Non-cell structured references may depend on table headers. | none | 59 code points, fixed literal/fragment |
| [checks/table_headers.py:331](../accessibility_checker/checks/table_headers.py#L331) | Plain first-row labels and distinct column metadata do not match. | none | 65 code points, fixed literal/fragment |
| [checks/table_headers.py:60](../accessibility_checker/checks/table_headers.py#L60) | Review the reported rectangle and its existing labels; no table or cells were changed. | none | 86 code points, fixed literal/fragment |
| [checks/table_headers.py:371](../accessibility_checker/checks/table_headers.py#L371) | Signed or opaque embedded package content prevents safe header confirmation. | none | 76 code points, fixed literal/fragment |
| [checks/table_headers.py:485](../accessibility_checker/checks/table_headers.py#L485) | Signed or opaque embedded package content prevents safe table creation. | none | 71 code points, fixed literal/fragment |
| [checks/table_headers.py:399](../accessibility_checker/checks/table_headers.py#L399) | Structured formula references may depend on table headers. | none | 58 code points, fixed literal/fragment |
| [checks/table_headers.py:497](../accessibility_checker/checks/table_headers.py#L497) | TABLE_HEADER: Single cells, one-row regions and one-column lists are not inferred tables under this profile. | none | 108 code points, fixed literal/fragment |
| [checks/table_headers.py:307](../accessibility_checker/checks/table_headers.py#L307) | Table ID is missing, invalid or duplicated across table parts. | none | 62 code points, fixed literal/fragment |
| [checks/table_headers.py:59](../accessibility_checker/checks/table_headers.py#L59) | Table header structure requires manual review. | none | 46 code points, fixed literal/fragment |
| [checks/table_headers.py:309](../accessibility_checker/checks/table_headers.py#L309) | Table part has multiple owning sheets. | none | 38 code points, fixed literal/fragment |
| [checks/table_headers.py:381](../accessibility_checker/checks/table_headers.py#L381) | Table query binding or extension is unsupported for enabling headers. | none | 69 code points, fixed literal/fragment |
| [checks/table_headers.py:479](../accessibility_checker/checks/table_headers.py#L479) | The candidate bounding rectangle overlaps a formal table. | none | 57 code points, fixed literal/fragment |
| [checks/table_headers.py:473](../accessibility_checker/checks/table_headers.py#L473) | The connected component is not a dense rectangle. | none | 49 code points, fixed literal/fragment |
| [checks/table_headers.py:476](../accessibility_checker/checks/table_headers.py#L476) | The first row lacks distinct nonblank plain-string labels of at most 255 characters. | none | 84 code points, fixed literal/fragment |
| [checks/table_headers.py:343](../accessibility_checker/checks/table_headers.py#L343) | Totals-row metadata makes enabling the header ambiguous. | none | 56 code points, fixed literal/fragment |
| [checks/table_headers.py:248](../accessibility_checker/checks/table_headers.py#L248) | Unrecognized or reference-bearing worksheet metadata requires preservation review. | none | 82 code points, fixed literal/fragment |
| [checks/table_headers.py:364](../accessibility_checker/checks/table_headers.py#L364) | Unrecognized table attributes require header-operation review. | none | 62 code points, fixed literal/fragment |
| [checks/table_headers.py:329](../accessibility_checker/checks/table_headers.py#L329) | Unsupported headerRowCount; only 0 and 1 are understood. | none | 56 code points, fixed literal/fragment |
| [checks/table_headers.py:188](../accessibility_checker/checks/table_headers.py#L188) | Unsupported or overlapping drawing requires header preservation review. | none | 71 code points, fixed literal/fragment |
| [checks/table_headers.py:205](../accessibility_checker/checks/table_headers.py#L205) | Unsupported worksheet feature {kind} may affect header confirmation. | kind | Template; inspect wrapper and finite/unbounded metadata distinction above |
| [checks/table_headers.py:162](../accessibility_checker/checks/table_headers.py#L162) | Worksheet part has multiple owning sheets. | none | 42 code points, fixed literal/fragment |
| [checks/table_headers.py:64](../accessibility_checker/checks/table_headers.py#L64) | {sheet.name}: {target}: {reason} | sheet.name; target; reason | Template; inspect wrapper and finite/unbounded metadata distinction above |

### MERGED_CELLS

All findings MANUAL_REVIEW. Populated nonconflicting merges have no limitation; conflicts/external sheets do.

Limitation wrapper: {worksheet}: {target}: {reason}; audit-only exclusions may use a rule prefix.

Dynamic values in limitations include location/sheet and, where indicated, source metadata. They do not enter the corresponding generic message.

| Source | Prose template / reason | Dynamic values | Length / observation |
|---|---|---|---|
| [checks/merged_cells.py:22](../accessibility_checker/checks/merged_cells.py#L22) | External worksheet merge content is not fetched. | none | 48 code points, fixed literal/fragment |
| [checks/merged_cells.py:45](../accessibility_checker/checks/merged_cells.py#L45) | Overlapping merge declarations require manual review. | none | 53 code points, fixed literal/fragment |
| [checks/merged_cells.py:47](../accessibility_checker/checks/merged_cells.py#L47) | Populated merged cells may impede navigation, including title merges. | none | 69 code points, fixed literal/fragment |
| [checks/merged_cells.py:80](../accessibility_checker/checks/merged_cells.py#L80) | Review the merged range and its effect on navigation; no cells were changed. | none | 76 code points, fixed literal/fragment |
| [checks/merged_cells.py:84](../accessibility_checker/checks/merged_cells.py#L84) | {worksheet}: {target}: {reason} | worksheet; target; reason | Template; inspect wrapper and finite/unbounded metadata distinction above |

### LINK_TEXT

Unsafe/formula reasons are MANUAL_REVIEW; safe simple labels REQUIRES_USER_INPUT. Drawing disclosures are limitations without findings.

Limitation wrapper: {worksheet}: {target}: {reason}; audit-only exclusions may use a rule prefix.

Dynamic values in limitations include location/sheet and, where indicated, source metadata. They do not enter the corresponding generic message.

| Source | Prose template / reason | Dynamic values | Length / observation |
|---|---|---|---|
| [checks/link_text.py:201](../accessibility_checker/checks/link_text.py#L201) | Ambiguous hyperlink relationship ID | none | 35 code points, fixed literal/fragment |
| [checks/link_text.py:230](../accessibility_checker/checks/link_text.py#L230) | Competing hyperlink declarations affect this representation. | none | 60 code points, fixed literal/fragment |
| [checks/link_text.py:146](../accessibility_checker/checks/link_text.py#L146) | External worksheet hyperlink content is not fetched. | none | 52 code points, fixed literal/fragment |
| [checks/link_text.py:308](../accessibility_checker/checks/link_text.py#L308) | Formula hyperlink cell location is missing | none | 42 code points, fixed literal/fragment |
| [checks/link_text.py:264](../accessibility_checker/checks/link_text.py#L264) | Formula hyperlink text is not edited; its formula was not calculated. | none | 69 code points, fixed literal/fragment |
| [checks/link_text.py:234](../accessibility_checker/checks/link_text.py#L234) | Hyperlink intersects merged cells. | none | 34 code points, fixed literal/fragment |
| [checks/link_text.py:125](../accessibility_checker/checks/link_text.py#L125) | Hyperlink label requires review for descriptive link purpose. | none | 61 code points, fixed literal/fragment |
| [checks/link_text.py:319](../accessibility_checker/checks/link_text.py#L319) | Missing/ambiguous drawing relationship | none | 38 code points, fixed literal/fragment |
| [checks/link_text.py:226](../accessibility_checker/checks/link_text.py#L226) | Multi-cell hyperlink representation is unsupported. | none | 51 code points, fixed literal/fragment |
| [checks/link_text.py:269](../accessibility_checker/checks/link_text.py#L269) | Only one or two literal string HYPERLINK arguments are supported for screening. | none | 79 code points, fixed literal/fragment |
| [checks/link_text.py:126](../accessibility_checker/checks/link_text.py#L126) | Provide descriptive link text while preserving the destination; no link was changed. | none | 84 code points, fixed literal/fragment |
| [checks/link_text.py:246](../accessibility_checker/checks/link_text.py#L246) | Signed package prevents safe hyperlink label editing. | none | 53 code points, fixed literal/fragment |
| [checks/link_text.py:240](../accessibility_checker/checks/link_text.py#L240) | The label is not a simple editable text cell. | none | 45 code points, fixed literal/fragment |
| [checks/link_text.py:212](../accessibility_checker/checks/link_text.py#L212) | Unsupported hyperlink relationship type. | none | 40 code points, fixed literal/fragment |
| [checks/link_text.py:232](../accessibility_checker/checks/link_text.py#L232) | Worksheet part has multiple owning sheets. | none | 42 code points, fixed literal/fragment |
| [checks/link_text.py:175](../accessibility_checker/checks/link_text.py#L175) | Wrapped or foreign-namespace hyperlink representation is unsupported. | none | 69 code points, fixed literal/fragment |
| [checks/link_text.py:338](../accessibility_checker/checks/link_text.py#L338) | {sheet.name}: {part}#xml={location}: Drawing hyperlink requires manual review; label and purpose were not screened. | sheet.name; part; location | Template; inspect wrapper and finite/unbounded metadata distinction above |
| [checks/link_text.py:323](../accessibility_checker/checks/link_text.py#L323) | {sheet.name}: {sheet.part}#xml=/: External drawing hyperlink content was not fetched. | sheet.name; sheet.part | Template; inspect wrapper and finite/unbounded metadata distinction above |
| [checks/link_text.py:130](../accessibility_checker/checks/link_text.py#L130) | {sheet.name}: {target}: {reason} | sheet.name; target; reason | Template; inspect wrapper and finite/unbounded metadata distinction above |

### COLOR_CONTRAST

All findings MANUAL_REVIEW. Rendering/conditional reasons create limitations; ordinary contrast/color-meaning findings do not. Default assumptions and missing formula cache are audit limitations.

Limitation wrapper: COLOR_CONTRAST: {assumption}; or {sheet}: {target}: {reason}.

Dynamic values in limitations include location/sheet and, where indicated, source metadata. They do not enter the corresponding generic message.

| Source | Prose template / reason | Dynamic values | Length / observation |
|---|---|---|---|
| [checks/color_contrast.py:39](../accessibility_checker/checks/color_contrast.py#L39) | Ambiguous styles relationships | none | 30 code points, fixed literal/fragment |
| [checks/color_contrast.py:182](../accessibility_checker/checks/color_contrast.py#L182) | COLOR_CONTRAST:  | none | 16 code points, fixed literal/fragment |
| [checks/color_contrast.py:185](../accessibility_checker/checks/color_contrast.py#L185) | COLOR_CONTRAST: Formula text without a usable saved cache was not calculated; only color meaning was screened. | none | 110 code points, fixed literal/fragment |
| [checks/color_contrast.py:135](../accessibility_checker/checks/color_contrast.py#L135) | Conditional visual formatting was not evaluated; static color screening is suppressed in this range. | none | 100 code points, fixed literal/fragment |
| [checks/color_contrast.py:112](../accessibility_checker/checks/color_contrast.py#L112) | External worksheet colors are not fetched. | none | 42 code points, fixed literal/fragment |
| [checks/color_contrast.py:178](../accessibility_checker/checks/color_contrast.py#L178) | Nonneutral font or fill color may convey meaning without equivalent text or structure. | none | 86 code points, fixed literal/fragment |
| [checks/color_contrast.py:26](../accessibility_checker/checks/color_contrast.py#L26) | Review the displayed colors and provide equivalent text or structure; no colors were changed. | none | 93 code points, fixed literal/fragment |
| [checks/color_contrast.py:157](../accessibility_checker/checks/color_contrast.py#L157) | Static rendering could not be resolved:  | none | 40 code points, fixed literal/fragment |
| [checks/color_contrast.py:174](../accessibility_checker/checks/color_contrast.py#L174) | Static text contrast {ratio}:1 is below {threshold}:1. | ratio; threshold | Template; inspect wrapper and finite/unbounded metadata distinction above |
| [checks/color_contrast.py:124](../accessibility_checker/checks/color_contrast.py#L124) | Visual extension has no resolvable declared range; worksheet static rendering was not assessed. | none | 95 code points, fixed literal/fragment |
| [checks/color_contrast.py:30](../accessibility_checker/checks/color_contrast.py#L30) | {sheet.name}: {target}: {reason} | sheet.name; target; reason | Template; inspect wrapper and finite/unbounded metadata distinction above |
| [color_styles.py:140](../accessibility_checker/color_styles.py#L140) | Ambiguous workbook  | none | 19 code points, fixed literal/fragment |
| [color_styles.py:73](../accessibility_checker/color_styles.py#L73) | Automatic color has no concrete RGB fallback. | none | 45 code points, fixed literal/fragment |
| [color_styles.py:38](../accessibility_checker/color_styles.py#L38) | Color has no supported concrete RGB value. | none | 42 code points, fixed literal/fragment |
| [color_styles.py:220](../accessibility_checker/color_styles.py#L220) | Column style interval outside worksheet bounds | none | 46 code points, fixed literal/fragment |
| [color_styles.py:266](../accessibility_checker/color_styles.py#L266) | Conflicting covering column styles. | none | 35 code points, fixed literal/fragment |
| [color_styles.py:67](../accessibility_checker/color_styles.py#L67) | Conflicting or missing active color sources. | none | 44 code points, fixed literal/fragment |
| [color_styles.py:342](../accessibility_checker/color_styles.py#L342) | Disabled style component has no referenced base style. | none | 54 code points, fixed literal/fragment |
| [color_styles.py:334](../accessibility_checker/color_styles.py#L334) | Explicit rich-text run styling is not yet resolved. | none | 51 code points, fixed literal/fragment |
| [color_styles.py:145](../accessibility_checker/color_styles.py#L145) | External style/theme content is not fetched. | none | 44 code points, fixed literal/fragment |
| [color_styles.py:239](../accessibility_checker/color_styles.py#L239) | External table style overlay cannot be resolved. | none | 48 code points, fixed literal/fragment |
| [color_styles.py:299](../accessibility_checker/color_styles.py#L299) | Gradient or ambiguous fill rendering is unsupported. | none | 52 code points, fixed literal/fragment |
| [color_styles.py:87](../accessibility_checker/color_styles.py#L87) | Indexed color is outside the concrete workbook palette. | none | 55 code points, fixed literal/fragment |
| [color_styles.py:76](../accessibility_checker/color_styles.py#L76) | Invalid theme/indexed color index. | none | 34 code points, fixed literal/fragment |
| [color_styles.py:114](../accessibility_checker/color_styles.py#L114) | Invalid {kind} index. | kind | Template; inspect wrapper and finite/unbounded metadata distinction above |
| [color_styles.py:303](../accessibility_checker/color_styles.py#L303) | Missing fill is screened as white. | none | 34 code points, fixed literal/fragment |
| [color_styles.py:294](../accessibility_checker/color_styles.py#L294) | Missing font color is screened as black. | none | 40 code points, fixed literal/fragment |
| [color_styles.py:278](../accessibility_checker/color_styles.py#L278) | Missing font color/fill are screened as black on white; default font size is 11 pt. | none | 83 code points, fixed literal/fragment |
| [color_styles.py:318](../accessibility_checker/color_styles.py#L318) | Missing font size is screened as 11 pt. | none | 39 code points, fixed literal/fragment |
| [color_styles.py:235](../accessibility_checker/color_styles.py#L235) | Missing/ambiguous table relationship | none | 36 code points, fixed literal/fragment |
| [color_styles.py:332](../accessibility_checker/color_styles.py#L332) | Mixed rich-text styling is unsupported. | none | 39 code points, fixed literal/fragment |
| [color_styles.py:312](../accessibility_checker/color_styles.py#L312) | Multiple font colors are ambiguous. | none | 35 code points, fixed literal/fragment |
| [color_styles.py:310](../accessibility_checker/color_styles.py#L310) | Patterned fill rendering is unsupported. | none | 40 code points, fixed literal/fragment |
| [color_styles.py:285](../accessibility_checker/color_styles.py#L285) | Recursive base-style inheritance is unsupported. | none | 48 code points, fixed literal/fragment |
| [color_styles.py:270](../accessibility_checker/color_styles.py#L270) | Referenced cell style is unavailable. | none | 37 code points, fixed literal/fragment |
| [color_styles.py:307](../accessibility_checker/color_styles.py#L307) | Solid fill has no unambiguous foreground color. | none | 47 code points, fixed literal/fragment |
| [color_styles.py:327](../accessibility_checker/color_styles.py#L327) | Superscript/subscript rendered font size is unsupported. | none | 56 code points, fixed literal/fragment |
| [color_styles.py:253](../accessibility_checker/color_styles.py#L253) | Table-style overlay prevents a static rendering result. | none | 55 code points, fixed literal/fragment |
| [color_styles.py:80](../accessibility_checker/color_styles.py#L80) | Theme color has no concrete RGB fallback. | none | 41 code points, fixed literal/fragment |
| [color_styles.py:46](../accessibility_checker/color_styles.py#L46) | Tint is outside -1..1. | none | 22 code points, fixed literal/fragment |
| [color_styles.py:316](../accessibility_checker/color_styles.py#L316) | Unsupported font size. | none | 22 code points, fixed literal/fragment |
| [color_styles.py:108](../accessibility_checker/color_styles.py#L108) | Unsupported style boolean value. | none | 32 code points, fixed literal/fragment |
| [color_styles.py:175](../accessibility_checker/color_styles.py#L175) | Unsupported theme namespace. | none | 28 code points, fixed literal/fragment |
| [color_styles.py:162](../accessibility_checker/color_styles.py#L162) | Unsupported workbook indexed palette representation. | none | 52 code points, fixed literal/fragment |
| [color_styles.py:117](../accessibility_checker/color_styles.py#L117) | {kind} index is not available. | kind | Template; inspect wrapper and finite/unbounded metadata distinction above |

## Reviewer observations (not verdicts)

- “requires review”, “static rendering”, “nonneutral” and “preservation review”
  can be technical or vague; explain these to users in proposed revisions.
- TABLE_HEADER manual messages omit the reason; it is available in limitations.
  LINK_TEXT uses the same message for editable and unsupported links.
- “Provide descriptive link text” can sound like a supported edit even for
  formula links; limitations and permitted actions must remain visible.
- ALT_TEXT detects presence, not semantic adequacy. “Confirm decorative” requires
  human judgment. It must not be presented as a successful accessibility check.
- Contrast is static screening, not a legal or comprehensive WCAG verdict.
  No reviewed active literal claims legal compliance.
- “No cells/colors/link were changed” accurately describes the read-only checker,
  but “title”, “description”, “label”, “header” need consistent UI terminology.
- Large limitations are a size/readability concern (AE-022), not a new 500-point
  contract violation. Long paths/functions can produce very long limitations.

## Human reviewer sign-off (leave unfilled)

| Rule | Accurate | Understandable | Recommendation actionable | Reviewer / date / comments |
|---|---|---|---|---|
| ALT_TEXT | [ ] | [ ] | [ ] | |
| WORKSHEET_NAME | [ ] | [ ] | [ ] | |
| TABLE_HEADER | [ ] | [ ] | [ ] | |
| MERGED_CELLS | [ ] | [ ] | [ ] | |
| LINK_TEXT | [ ] | [ ] | [ ] | |
| COLOR_CONTRAST | [ ] | [ ] | [ ] | |

## Unapproved proposals — Pod coordination required

Keep current wording unchanged. Consider plain-language alternatives to static
rendering/nonneutral, reason-specific header/link explanations, wording that
distinguishes suggested human action from available APPLY actions, consistent
labels, and clearer partial-screening caveats. Any limitation aggregation or
truncation also changes evidence/output and requires coordination. Check other
teams' text expectations before changes even though finding IDs exclude prose.

## Executed verification

Three added tests in tests/test_finding_texts.py check default-fixture bounds,
repeat-target prose and limitations determinism, exporter determinism/deduplication,
and a long raw-cell input. These tests do not certify semantic accuracy or HTML
rendering safety. Human review and proposed wording remain unapproved/unperformed.

