# Integrating remediation into the upload service

Gustavo — these are notes on connecting `remediation.py` (Jonathan's Phase 4 piece)
to your FastAPI app. Nothing in your branch has been changed. The module is on the
`Jonathan` branch, and `REMEDIATION_REPORT.md` explains how it works.

## What the module gives you

`review()` and `remediate()` work on file paths and return plain dicts, the same pattern
`process_audit` already uses with temp files. The command-line prompts live only in
`main()`, so importing the module never prompts.

| Function | Use |
| --- | --- |
| `review(path)` | Runs the six-rule checker. Each finding gains `location` (readable position) and `input` (the value template the user fills in; `None` means manual review only). Use it to build the findings form. |
| `remediate(src, dst, decisions)` | Applies the approved decisions to a copy at `dst` and returns a report dict. On any problem it raises `RemediationError` and writes nothing. |

## Steps

### 1. Switch the ruleset version to 2.0.0

`process_audit` computes `findingId` from `audit['ruleset_version']`, which is currently
`1.0.0`. `remediate()` matches decisions against IDs built with `2.0.0`, using the same
formula. Until the versions match, every decision the site submits fails with
`FINDING_NOT_FOUND`. Phase 4 requires 2.0.0 anyway.

### 2. Update the checker and its dependencies

- Replace `accessibility_checker/` with Haruki's current six-rule package. It is on
  `origin/haruki/accessibility-checker`, and a copy is on `Jonathan`.
- Add these lines to `requirements.txt`:
  ```
  openpyxl==3.1.5
  defusedxml==0.7.1
  et-xmlfile==2.0.0
  ```
- Add `remediation.py` to the Dockerfile's `COPY app.py database.py ...` line.
- `remediation.py` imports `validate_file` from `validity_check`. Your copy of that file
  has it, so nothing changes there.

### 3. Derive audit status the Phase 4 way (spec Section 9)

```python
if not findings:
    status = 'AUDIT_COMPLETE'
elif any(f['classification'] == 'REQUIRES_USER_INPUT' for f in findings):
    status = 'REMEDIATION_AVAILABLE'
else:
    status = 'REVIEW_REQUIRED'
```

### 4. Operation 7: `POST /api/v1/workbooks/{workbookId}/versions/{versionId}/remediations`

1. Store the decision batch.
2. Return `202 {remediationId, sourceVersionId, status: "REMEDIATING"}`.
3. Run the work in a background task, as you do for audits:

```python
from remediation import RemediationError, remediate

def process_remediation(database, remediation_id):
    # load the source version's bytes and the stored decisions
    try:
        with tempfile.TemporaryDirectory(prefix='workbook-remediation-') as directory:
            src, dst = Path(directory) / 'source.xlsx', Path(directory) / 'output.xlsx'
            src.write_bytes(source_bytes)
            report = remediate(str(src), str(dst), decisions)
            output_bytes = dst.read_bytes()
        # in one transaction, insert:
        #   - a new version (original=output_bytes, source_version_id=<source>, status REMEDIATED)
        #   - an output record
        #   - an audit holding report['unresolvedFindings'] and report['limitations']
        # then mark the remediation REMEDIATED with outputVersionId, outputId and auditId
    except RemediationError as error:
        ...  # mark PROCESSING_FAILED with {'code': error.code, 'message': str(error), ...}
```

The source bytes are never modified. `remediate` also refuses to write over its input.

**Error codes.** The spec wants a bad request rejected before the 202, but `remediate`
raises validation errors only when it runs. There are two ways to handle that:

- **Option A:** call `remediate` inside the request with `await asyncio.to_thread(...)`.
  It re-audits the file, which takes seconds for normal workbooks. Map errors with:

  ```python
  STATUS = {'INVALID_REQUEST': 400, 'MISSING_VALUE': 400, 'DUPLICATE_DECISION': 400,
            'FINDING_NOT_FOUND': 404, 'CONFLICTING_CORRECTIONS': 422,
            'INVALID_CORRECTION': 422, 'UNSUPPORTED_CORRECTION': 422,
            'PRESERVATION_FAILED': 500}
  ```
- **Option B:** ask Jonathan for a public `validate_decisions(path, decisions)` function,
  so the request can validate synchronously and leave the edit to the background task.

**Still yours:** idempotency keys (spec 9.1), and allowing one active operation per version.

### 5. Operation 8: `GET /api/v1/remediations/{remediationId}`

Return the stored record.

### 6. Operation 9: `GET /api/v1/outputs/{outputId}/workbook`

Return the output bytes with the `.xlsx` content type.

### 7. Audit report (spec Section 12)

The report from `remediate()` already supplies these fields:

- `decisions` and `approvedChanges`
- `unresolvedFindings` and `manualReviewItems`
- `limitations`, `checksPerformed`
- `sourceSha256` and `outputSha256`

Add the IDs, `fileName`, `auditDate` and `rulesetVersion`, plus `sourceAuditId` on each
decision.

### 8. Upload page

After the audit, render one block per finding from `review()`:

- Show `location`, `message`, `recommendation` and `classification`.
- If `input` is not `None`, offer Apply, Decline or Manual review, with fields that
  depend on the rule:

  | Rule | Fields |
  | --- | --- |
  | `ALT_TEXT` | Two text boxes, `title` and `description`, pre-filled from `input` |
  | `WORKSHEET_NAME` | One `name` box, with a warning that references to the sheet will be updated |
  | `LINK_TEXT` | One `text` box |
  | `TABLE_HEADER` | A confirm checkbox for row `input.headerRow`, sent back unchanged |

Leave every choice unselected by default. Submit
`{auditId, decisions: [{findingId, action, value}]}`, with `value` only on Apply.

## Before release

Open each corrected fixture in Microsoft Excel and confirm there's no repair prompt.
The spec makes this a release gate, and it hasn't been done yet.
