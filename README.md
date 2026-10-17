# ECE30861 — workbook upload service

Gustavo's Python API and upload page. Valid original workbook bytes are
stored transactionally in PostgreSQL on AWS (SQLite locally). Source records cannot be updated, and authenticated
owners can download their unchanged uploads for auditing.

## Run locally (PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
$env:API_TOKENS_JSON = '{"replace-with-a-long-random-secret":"test-user"}'
python -m uvicorn app:app --reload
```

Open http://127.0.0.1:8000 and supply the configured token. API documentation is at
`/docs`. No default token is enabled. Tokens map to user IDs; different tokens mapped
to the same user share access. Keep token configuration out of version control.
`DATABASE_PATH` defaults to `data/workbooks.sqlite3`.

## Interface

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/v1/health` | Public service availability |
| POST | `/api/v1/workbooks` | Validate multipart `file`; returns 200 with `valid: true` and saved resource IDs |
| GET | `/api/v1/workbooks/{workbookId}/versions/{versionId}` | Metadata, SHA-256, status |
| GET | `/api/v1/workbooks/{workbookId}/versions/{versionId}/original` | Unmodified original bytes |

All resource endpoints require `Authorization: Bearer <token>`. Errors contain
`code`, `message`, `requestId`, and `details`. Rejected uploads create no records.
Upload guards: 25 MiB uploaded, 100 MiB expanded, 10,000 ZIP entries;
unreadable ZIP archives, encrypted ZIP entries, and macro-enabled files are
rejected. Jonathan's integrated validator checks worksheet/cell limits, XML integrity,
and workbook/sheet protection before saving any upload.
Request IDs are also returned in `X-Request-ID`.

## Checker integration

The supplied `validity_check.py` is loaded automatically from the application
directory and is included in the Docker image. Its source is unchanged.
The service calls its path-based `validate_file(filepath)` function.
The service writes the uploaded bytes to an isolated temporary `.xlsx`
file and passes its absolute path as a string. The validator must read it
synchronously in an isolated process so its file handles close reliably on Windows;
the temporary directory is removed after the call, including on
failure. The permanent original remains unchanged in the database. The supplied
checker currently returns error lists; the loading adapter converts an empty list
to `True` and a nonempty list to `False`. It also supports `True`/`1` and `False`/`0`
directly. Injected callbacks via `create_app(workbook_validator=...)` use the boolean
contract. Other return types are integration errors (HTTP 500). Invalid files are
rejected before creating records. Optionally set `VALIDATOR_PATH` to load a different
validator file, available inside the container when deploying.
Without a configured validator, uploads return HTTP 503 with
`VALIDATOR_NOT_CONFIGURED` and create no records.

Phase 3 checks workbook validity only. Valid uploads return HTTP 200 with
`{"valid": true, "workbookId": "...", "versionId": "..."}`. Invalid workbooks
return HTTP 422 with `message: "Workbook is invalid."` and
`details: {"valid": false}`. The page shows "Workbook is valid" or "Workbook is
invalid" and the response JSON. Uploads do not create audits, start background
processing, or poll audit status. The audit database schema and authenticated
`GET /api/v1/workbooks/{workbookId}/versions/{versionId}/audits/{auditId}` endpoint
are retained for later weeks. An audit must already exist to retrieve it; the
current upload flow only validates and saves the original workbook.

No validator rule implementations were changed. No accessibility audits are started.

## Deploy to AWS (PowerShell)

The deployment uses ECS Express Mode for the website/API and managed HTTPS, ECR
for the container image, and RDS PostgreSQL for original workbook bytes and metadata.
It provisions its own VPC, public application subnets, isolated database
subnets, security groups, IAM roles, and Secrets Manager secrets. No existing VPC,
database password, SSH key, domain, or certificate is required. PostgreSQL tables
and the source-update prevention trigger are created automatically on startup.

Prerequisites:

- AWS CLI v2 and an AWS account/profile, preferably through AWS IAM Identity Center.
- Docker Desktop running with Linux containers.
- A region supporting ECS Express Mode and RDS PostgreSQL, such as `us-east-1`.
- Deployment permissions for CloudFormation, ECR, ECS, RDS, EC2 networking,
  Secrets Manager, IAM role creation/pass-role, and ECS-managed load balancers,
  logging, certificates, and scaling. A restricted class/lab account may need
  an instructor to authorize those services.

Configure your AWS profile, then validate the account and template:

```powershell
aws configure sso --profile coursework
aws sso login --profile coursework
.\scripts\deploy-aws.ps1 -Region us-east-1 -Profile coursework
```

The default script invocation only checks the account and validates the template.
To create the billable deployment:

```powershell
.\scripts\deploy-aws.ps1 -Region us-east-1 -Profile coursework -Deploy
```

This builds a Linux image, uploads it to ECR, deploys the CloudFormation stack,
and prints the service endpoint and secret ARNs. It never performs a Git push.
Repeat the same command to deploy code updates using a new immutable image tag.

Retrieve the generated test-user token privately and check the service:

```powershell
$outputs = (aws cloudformation describe-stacks --stack-name workbook-service --region us-east-1 --profile coursework --query 'Stacks[0].Outputs' --output json) | ConvertFrom-Json
$serviceUrl = ($outputs | Where-Object OutputKey -eq 'ServiceUrl').OutputValue
if ($serviceUrl -notmatch '^https://') { $serviceUrl = "https://$serviceUrl" }
$tokenArn = ($outputs | Where-Object OutputKey -eq 'TokenSecretArn').OutputValue
$token = aws secretsmanager get-secret-value --secret-id $tokenArn --region us-east-1 --profile coursework --query SecretString --output text
Invoke-RestMethod "$($serviceUrl.TrimEnd('/'))/api/v1/health"
# Paste the value of $token into the website's Access token field when testing.
# Do not commit it or share it in chat.
```

`API_TOKENS_JSON` is injected from Secrets Manager; the database password is
generated and rotated by RDS. The application reads the current database secret
when connecting, using its IAM task role. No AWS access keys are embedded in the
application. Connections verify the RDS hostname and certificate using AWS's CA
bundle, included in the image. The database is encrypted and retains automated backups for one day.
Its security group permits PostgreSQL only from application tasks.

Deployment configuration in `database.py`:

| Variable | Source |
| --- | --- |
| `DB_HOST`, `DB_PORT`, `DB_NAME` | CloudFormation RDS endpoint and database settings |
| `DB_SECRET_ARN` | RDS-managed secret; read using the task role |
| `DB_SSLROOTCERT` | CA bundle path set in the Dockerfile |
| `API_TOKENS_JSON` | Generated application token mapping in Secrets Manager |

The bootstrap application currently uses the RDS administrator to create its
schema. A production deployment should run migrations separately and use a
restricted application database user. Updates to the application-token secret
require a fresh deployment to refresh injected values. Database password rotation
does not require a deployment because credentials are retrieved per connection.

Audit/report/correction processing is outside the current phase. Existing local SQLite data is
not automatically migrated to RDS. Larger storage deployments can move workbook
blobs to S3 later; this deployment stores originals in PostgreSQL transactions.

To remove the deployment when you are finished:

```powershell
aws cloudformation delete-stack --stack-name workbook-service --region us-east-1 --profile coursework
aws cloudformation wait stack-delete-complete --stack-name workbook-service --region us-east-1 --profile coursework
```

Deleting the stack removes the live database and takes a final database snapshot.
Snapshots and the separately created ECR repository/images remain and can incur
charges until explicitly removed. Review retained resources in the AWS console.

AWS references: [ECS Express deployment](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/express-service-getting-started.html),
[networking](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/express-service-work.html),
[RDS-managed credentials](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-rds-dbinstance.html).

## Verification

```powershell
python -m pip install httpx==0.28.1
python -m unittest discover -s tests -v
```

The PostgreSQL integration test is skipped unless `RUN_POSTGRES_TESTS=1` is set.
Run it from a machine with network access to a dedicated PostgreSQL test database,
with the `DB_HOST`, `DB_NAME`, `DB_SSLROOTCERT`, and `DB_SECRET_ARN` (or
`DB_SECRET_JSON` containing `username` and `password`) settings configured. It
checks binary storage, source immutability, and transaction rollback. Use an empty
test database: the test initializes the schema.

Infrastructure validation:

```powershell
python -m pip install cfn-lint
cfn-lint infrastructure/aws.yaml
```
