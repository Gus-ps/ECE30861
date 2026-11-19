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

The implementation and EC2 configuration below were verified locally or inspected in
the repository. Production deployment and infrastructure restores still need evidence.

- **Live rows:** DELETE reserves the workbook, fences it against new work, and removes
  its jobs, idempotency keys, schedules, notifications, reminder decisions, upload
  reservations, legacy rows and workbook resources in committed stages. Workbook bytes
  live in the database, so the current application has no object-store versions.
  Startup resumes any pending reservation before starting workers or the scheduler.
- **SQLite physical storage:** Every application SQLite connection enables
  `PRAGMA secure_delete=ON` to overwrite deleted database content. Existing backups
  and filesystem-level copies can still contain earlier bytes.
- **EC2 demo:** Both EC2 scripts provision the private host directory
  `/opt/workbook/deletion-ledger` and mount it at `/service/deletion-ledger`.
  The container uses `DELETION_LEDGER_PATH=/service/deletion-ledger/deletions.jsonl`.
  This directory is separate from the SQLite data directory and outside the update
  script's database backups. On a successful update, only the backup taken for that
  update is retained. Its raw SQLite bytes can still contain workbooks deleted later.
- **Restore on EC2:** Stop the live service before restoring a database, preserve the
  current ledger separately, and start the ledger-aware image with the original mount.
  The application fsyncs the intent before removing live rows and reapplies each recorded
  deletion before startup finishes. This protection applies to deletes recorded after the
  ledger was enabled. When the path is unset, startup warns and a restore can reintroduce
  deleted data. A new ledger file can be created in the configured directory. Startup
  discards only an unterminated final record and refuses other corruption or file errors.
- **ECS/RDS handoff to Jon:** ECS still needs a durable ledger outside the database and
  task filesystem, such as an S3-backed store, plus a backup retention and snapshot
  policy. The current RDS configuration retains automated backups for about one day and
  retains final snapshots on deletion or replacement. Restoring those copies can
  reintroduce deleted workbooks while the ECS ledger is absent. The infrastructure
  template is unchanged.
