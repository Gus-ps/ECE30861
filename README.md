# ECE30861 workbook upload service

Gustavo's scope follows `PROMPT.md`: a Python upload website, authenticated
endpoints, persistent storage, unchanged originals and AWS deployment.
Jonathan's supplied `validity_check.py` is used without modifying it.
Accessibility rules belong to the team's checker and are not implemented here.

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

The upload limit is **25,000,000 bytes**. Jonathan's validator checks the 50-sheet
and 250,000-cell limits, readable workbook format and protection. Upload guards
also reject macros, encrypted ZIP entries, archives over 100 MiB expanded or
10,000 entries. Rejected uploads create no version or audit. Original bytes and
the initial PROCESSING audit are committed in one database transaction.
`contracts.py` enforces the supplied identifier, filename, hash, timestamp,
finding and response schemas. Errors contain code, message, requestId and details.

## Checker integration hooks

The upload passes an absolute temporary `.xlsx` path to Jonathan's checker. The
file is removed after the call. `check_validity(path)` is preferred and its printed
messages are forwarded to the server terminal/container logs. Available rejection
details are also returned to the page. `VALIDATOR_PATH` optionally selects another
validator module. Both boolean returns and older error-list modules are supported.

To integrate the accessibility checker later, pass its path-based callable to
`create_app(accessibility_checker=...)`. Comments in `app.py` mark the integration
point. It must return a list of findings with the supplied schema's eight fields.
The API validates them, assigns stable workbook/ruleset/location IDs, orders them
by ruleId/worksheet/target and stores the audit result. No findings produces
AUDIT_COMPLETE; unresolved findings produce REVIEW_REQUIRED; failures produce
PROCESSING_FAILED. The checker must not modify the source.

Until a checker is supplied, uploads still validate and save the original, while
their audit reports CHECKER_NOT_CONFIGURED. The page distinguishes invalid files
from valid files whose accessibility audit is unavailable. No Haruki rule modules
are copied into this branch. Remediation/report generation is left to subsequent
team integration; this service does not generate corrected workbooks itself.

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
