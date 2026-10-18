# ECE30861 workbook upload service

Gustavo's scope follows `PROMPT.md`: a Python upload website, authenticated
endpoints, persistent storage, unchanged originals and AWS deployment.
Jonathan's supplied `validity_check.py` is used without modifying it.
Accessibility rules come from Haruki's merged `accessibility_checker` package.

## Run locally

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
$env:API_TOKENS_JSON = '{"replace-with-a-secret-token":"test-user"}'
python -m uvicorn app:app --reload
```

Open http://127.0.0.1:8000. Supply the configured token in the Access token field.
API documentation and schemas are at `/docs` and `/openapi.json`.
`API_TOKENS_JSON` maps bearer tokens to user IDs; there are no default credentials.
SQLite defaults to `data/workbooks.sqlite3`; `DATABASE_PATH` can override it.

## Endpoints from PROMPT.md

| Operation | Endpoint | Response |
| --- | --- | --- |
| 1 | `GET /api/v1/health` | Availability and API/ruleset versions |
| 2 | `POST /api/v1/workbooks` | Multipart `file`; 202 with workbookId, versionId, auditId and PROCESSING |
| 4 | `GET /api/v1/workbooks/{workbookId}/versions/{versionId}` | Filename, SHA-256, timestamps, status and audit/source IDs |
| 5 | `GET /api/v1/workbooks/{workbookId}/versions/{versionId}/audits/{auditId}` | Audit status, findings, limitations and error |

The owner-authorized `/api/v1/workbooks/{workbookId}/versions/{versionId}/original`
download supports the prompt's requirement that unchanged originals remain accessible.
All resource endpoints require `Authorization: Bearer <token>`; health is public.

The upload limit is **25,000,000 bytes**. The validity checker enforces the
50-worksheet and 250,000-nonempty-cell limits, readable workbook format, protection,
and rejection of macro-containing packages. `.xlsm` and renamed macro packages
return HTTP 422; other unsupported extensions return 415. Rejected uploads create
no version or audit. Originals and the initial audit are created atomically.
`contracts.py` enforces the supplied identifier, filename, hash, timestamp,
finding and response schemas. Errors contain code, message, requestId and details.

## Checker integration hooks

The upload passes an absolute temporary `.xlsx` path to Jonathan's checker. The
file is removed after the call. `check_validity(path)` is preferred and its printed
messages are forwarded to the server terminal/container logs. Available rejection
details are also returned to the page. `VALIDATOR_PATH` optionally selects another
validator module. Both boolean returns and older error-list modules are supported.

The default callable is `accessibility_checker.runner.check_workbook(path)`.
Phase 3 enables WORKSHEET_NAME and ALT_TEXT only. Worksheet-name checks include
chartsheets, hidden, and very-hidden tabs. Supported drawing objects require both
alternative-text title and description; decorative or unsupported/ambiguous
objects produce MANUAL_REVIEW findings. Ambiguous locations use an indexed XML
path and disclosures in limitations. External object relationships are not fetched.

The callable returns a list-compatible result with an optional limitations list.
The API validates the eight-field findings and assigns deterministic content,
ruleset, rule, worksheet, and target IDs. Ruleset version is `1.0.0`. Findings
are ordered by ruleId/worksheet/target. Empty results produce AUDIT_COMPLETE;
findings produce REVIEW_REQUIRED; execution failures produce PROCESSING_FAILED
without partial findings. The checker must not modify the source.

Original download remains an optional extension for the shared pod tests.
Error codes, details contents, and prose are implementation-defined; cross-team
checks compare HTTP statuses and the shared response schemas. See
`pod_spec_alignment.md` and the Word contract under `.docs/`.

The page distinguishes invalid files from valid files with findings or an audit
failure. Remediation/report generation is left to subsequent team integration;
this service does not generate corrected workbooks itself.

Background processing uses the application process. Audits interrupted by a
restart require later worker integration; this scoped version has no recovery
worker, leases, re-audit endpoint, scheduling or version-history operations.

## Deploy to AWS

The Dockerfile and `infrastructure/aws.yaml` deploy the service through ECS Express
Mode with HTTPS, an ECR image, private RDS PostgreSQL, networking, IAM roles and
Secrets Manager. PostgreSQL stores workbook bytes and audit records. The schema
is initialized automatically, and source records cannot be updated. Existing
database records are preserved by additive audit-schema changes.

With Docker Desktop running and your AWS CLI profile signed in:

```powershell
aws login --profile coursework --region us-east-2
.\scripts\deploy-aws.ps1 -Region us-east-2 -Profile coursework
.\scripts\deploy-aws.ps1 -Region us-east-2 -Profile coursework -Deploy
```

Without `-Deploy`, the script only validates the account/template. With `-Deploy`,
it creates billable resources, uploads the image and prints ServiceUrl and secret
ARNs. It does not push the Git branch. Deployment requires permissions for the
services above. The database password is managed by RDS; the application reads it
with its IAM role and verifies the database's TLS certificate. Automated backups
are retained for one day. Application tokens are generated and injected from
Secrets Manager. The bootstrap database user creates the schema; a production
deployment should separate migrations from a restricted runtime database user.

Retrieve the generated website token privately:

```powershell
aws secretsmanager get-secret-value --secret-id 'PASTE_TOKEN_SECRET_ARN' --region us-east-2 --profile coursework --query SecretString --output text
```

Database settings are `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_SECRET_ARN`, and
`DB_SSLROOTCERT`; the deployment supplies them. `DB_SECRET_JSON` containing
username/password supports a separate test database. Never commit credentials.

## Verify

```powershell
python -m pip install httpx==0.28.1
python -m unittest discover -s tests -v
```

Focused API tests cover the listed operations, validator integration, source
preservation, errors and owner access. The optional PostgreSQL storage test runs
only with `RUN_POSTGRES_TESTS=1` and a dedicated TLS test database configured.
