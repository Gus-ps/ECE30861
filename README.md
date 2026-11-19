# ECE30861 workbook upload service

Gustavo's scope follows `PROMPT.md`: a Python upload website, authenticated
endpoints, persistent storage, unchanged originals and AWS deployment.
Jonathan's supplied `validity_check.py` is used without modifying it.
The current Phase 5 service runs the six-rule 2.0.0 checker and supports remediation, report snapshots, version history, scheduling, reminders, notifications, an isolated test clock and recoverable deletion.

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

`DELETION_LEDGER_PATH` points to a persistent JSON Lines file outside the
database backup and restore scope. Startup reapplies its deletion intents.
When unset, startup warns and database restores can reintroduce deleted workbooks.

`SCHEDULER_INTERVAL_SECONDS` sets the polling interval for ordinary data.
It defaults to 1 second and accepts values greater than zero and up to 5.
Tests can disable the scheduler thread with `create_app(enable_scheduler=False)`.

On a test deployment, start the service with `ENABLE_TEST_INTERFACE=true` and
`ENABLE_TEST_CLOCK=true` to enable the clock. New test sessions start at
`2027-01-01T00:00:00Z` unless `POST /test/setup` supplies `setup.clock.currentTime`.
Operation 13 requires the creating test administrator's bearer token and
`X-Test-Session`.

## API endpoints

| Operation | Endpoint | Response |
| --- | --- | --- |
| 1 | `GET /api/v1/health` | Availability and API/ruleset versions |
| 2 | `POST /api/v1/workbooks` | Multipart `file`; 202 with workbookId, versionId, auditId and PROCESSING |
| 3 | `POST /api/v1/workbooks/{workbookId}/versions` | Upload a new version and accept its initial audit with 202 |
| 4 | `GET /api/v1/workbooks/{workbookId}/versions/{versionId}` | Filename, SHA-256, timestamps, status and audit/source IDs |
| 5 | `GET /api/v1/workbooks/{workbookId}/versions/{versionId}/audits/{auditId}` | Audit status, findings, limitations and error |
| 6 | `POST /api/v1/workbooks/{workbookId}/versions/{versionId}/audits` | Accept a manual re-audit with 202 |
| 7 | `POST /api/v1/workbooks/{workbookId}/versions/{versionId}/remediations` | Accept remediation decisions with 202 and require an idempotency key |
| 8 | `GET /api/v1/remediations/{remediationId}` | Read remediation status, output identifiers and any error |
| 9 | `GET /api/v1/outputs/{outputId}/workbook` | Download the generated workbook |
| 10 | `GET /api/v1/workbooks/{workbookId}/history` | List stored versions and audits |
| 11 | `PUT /api/v1/workbooks/{workbookId}/schedule` | Owner replaces the audit interval and supplied deadline |
| 12 | `GET /api/v1/workbooks/{workbookId}/notifications` | Owner or granted reviewer reads the stored in-app notification records |
| 13 | `POST /api/v1/test/clock` | Advance the session clock with `{"currentTime":"…Z"}`. Returns 200 with the time, accepted audit IDs and newly recorded notification IDs |
| 14 | `DELETE /api/v1/workbooks/{workbookId}` | Delete an owned workbook and its related records, returning 204 on completion |
| G | `GET /api/v1/workbooks/{workbookId}/schedule` | Owner or granted reviewer reads schedule and newest version |
| S | `GET /api/v1/workbooks/{workbookId}/versions/{versionId}/source` | Download the stored version without modifying it |
| V | `GET /api/v1/workbooks/{workbookId}/versions/{versionId}/audits/{auditId}/review` | Read review items and available decisions |
| R | `GET /api/v1/workbooks/{workbookId}/versions/{versionId}/audits/{auditId}/report` | Download the stored audit report as JSON |
| Test setup | `POST /test/setup` | Prepare an isolated test session when the test interface is enabled |
| Test report | `GET /test/report?session_id={sessionId}` | Read coverage information for an owned test session |

The legacy `/original` path remains an alias for `/source`. Health is public.
Resource and test endpoints require bearer credentials with the appropriate permissions.

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
Ruleset `2.0.0` checks ALT_TEXT, WORKSHEET_NAME, TABLE_HEADER, MERGED_CELLS,
LINK_TEXT and COLOR_CONTRAST. Findings are deterministic and ordered by
rule, worksheet and target. Execution failures report PROCESSING_FAILED
without partial findings. Remediation creates separate generated versions
and report snapshots while preserving source bytes.

The background worker uses durable job claims and marks interrupted running
jobs as failed on restart. Ordinary scheduling uses real UTC, and the test
clock advances scheduling for the selected isolated test session.

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

Schedule configuration decisions and verification limits: [Phase 5 system decisions](docs/phase5_system_decisions.md).
