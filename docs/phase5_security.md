# Phase 5 security notes (REQ-14)

Reviewed from the repository only (`P5-MANUAL-HTTPS-CREDENTIALS`). Nothing was deployed or
probed, so behavior on the live hosts still needs a human check.

## Transport

- **App:** uvicorn serves plain HTTP on port 8000 and sends no HSTS header (`Dockerfile`
  CMD, `phase4_service.py` `headers` middleware). TLS is left to the front end.
- **EC2 demo** (`scripts/deploy-ec2-demo.ps1`, the current release target): the app
  listens only on `127.0.0.1:8000` (line 44). Caddy serves `https://<ip>.sslip.io` with an
  automatic certificate (lines 47-48). The security group opens ports 80 and 443 (line 66).
  Caddy's default for port 80 is a redirect to HTTPS, so plain HTTP is **redirected, not
  rejected**. A request sent over HTTP has already exposed its bearer token before the
  redirect. Open as D2.
- **ECS stack** (`infrastructure/aws.yaml` `Service`, an `ExpressGatewayService`): the
  listener, certificate and HTTP behavior are managed by ECS Express Mode and aren't
  declared in the template, so the repository doesn't show whether HTTP is rejected or
  redirected.
- **Database:** RDS is private (`PubliclyAccessible: false`), storage is encrypted, and
  connections use `sslmode=verify-full` with the RDS CA bundle (`Dockerfile` lines 3-5,
  `database.py` line 48). `DATABASE_URL` connections use `sslmode=require` (line 33).

## Credentials

- The service has no passwords. Users authenticate with bearer tokens. `API_TOKENS_JSON`
  maps each **plaintext token** to a user, and `phase4_service.py` `user` compares
  tokens with `secrets.compare_digest`. Test-admin tokens (`TEST_ADMIN_TOKENS_JSON`) work
  the same way.
- **ECS:** the token is a 48-character generated secret in Secrets Manager (`ApiToken`).
  The mapping is a second secret, injected as an environment variable (`aws.yaml` lines
  77-90, 207-209). In the template, only the task execution role is granted read access.
- **EC2 demo:** a 64-hex-digit random token is written to `/opt/workbook/app.env` under
  `umask 077` on an encrypted EBS volume (`deploy-ec2-demo.ps1` lines 40-41, 72).
- **Browser:** `static/index.html` keeps the token only in the page (a password-type input,
  no storage).
- Tokens are stored as plaintext rather than as hashes. Whether that meets "no plaintext
  passwords" is open as D3.

## Deletion, backups and copies (Operation 14)

Assertions: `P5-DELETE-RESTORE`, `P5-DELETE-OBJECT-VERSIONS`, `P5-MANUAL-DELETE-BACKUPS`.
Like the sections above, this is read from the repository only, not observed on AWS.

- **Live rows:** `DELETE /api/v1/workbooks/{id}` removes every row for the workbook (source
  and output bytes, audits, findings, review contexts, reports, remediations, idempotency
  keys, jobs, upload reservations and legacy Phase 3 rows) in one transaction
  (`phase4_service.py` `delete_workbook`). The same code runs on SQLite and PostgreSQL.
  There is no object store: workbook bytes live in `p4_resources.data`, so there are no
  object versions to remove.
- **Physical remnants:** SQLite keeps deleted pages in the file until they are reused.
  `secure_delete` and `VACUUM` aren't used (`database.py`). PostgreSQL keeps dead tuples
  until autovacuum reclaims them. Both are on encrypted volumes (EBS `Encrypted`, RDS
  `StorageEncrypted`). These are provider-level remnants that the spec places outside the
  prototype's physical-erasure claim, but they are reachable by anyone who can read the
  database file.
- **RDS automated backups** (`infrastructure/aws.yaml` line 73, `BackupRetentionPeriod: 1`):
  for about a day after a deletion, a point-in-time restore or the daily snapshot still
  contains the workbook. `DeletionPolicy`/`UpdateReplacePolicy: Snapshot` (lines 60-61)
  also keeps a final manual snapshot when the stack is deleted or the database is
  replaced, and that snapshot doesn't expire.
- **Application-managed copies (EC2 demo):** every release made with the EC2 update script
  first writes `/service/data/pre-deploy-<release>.sqlite3` (script line 55) and never
  removes it. Each copy keeps every workbook that existed at that release, including ones
  deleted later. The EBS volume is retained when the instance is terminated
  (`DeleteOnTermination: false`).
- **Restores:** nothing stops a restore from resurrecting an acknowledged deletion today.
  The service keeps no record of deleted workbook IDs outside the database being restored,
  so restoring an RDS snapshot, a point-in-time copy or a pre-deploy SQLite file brings
  deleted workbooks back. This doesn't yet meet spec §10 ("A restore must never resurrect
  an acknowledged deletion"). The policy choice is open as D6.
