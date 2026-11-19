# Deploying the Team 12 tester

Host-agnostic files for putting the tester at the root of its own subdomain,
`https://tester.<host>`. Team 12's tester is at `https://tester.13.184.14.226.sslip.io`, beside its
system at `https://13.184.14.226.sslip.io` (neither has a trailing slash). sslip.io resolves every
subdomain to the IP it embeds, so both run on one host behind one proxy and are told apart by
host name. Pick **one** way to run the process (Docker or systemd) and **one** HTTPS reverse
proxy (nginx or Caddy). Nothing here assumes AWS or any particular provider. A path prefix
(`https://<host>/tester`) still works; see "Path-prefix alternative" below.

| File | Purpose |
| --- | --- |
| `tester.env.example` | Production settings template, shared by every option |
| `Dockerfile`, `compose.yaml`, `../.dockerignore` | Container option |
| `systemd/team12-tester.service` | Plain Linux VM option, no Docker |
| `nginx/team12-tester.conf` | nginx server block for `tester.<host>` |
| `caddy/Caddyfile` | Caddy site for `tester.<host>` with automatic HTTPS |
| `../scripts/make_operator_token.py` | Generates an operator token and its hash |
| `../scripts/smoke_test.py` | Runs one suite against the deployed tester |

Fixed requirements, whichever option you pick:

- **One process.** Run a single uvicorn worker per SQLite file; restart recovery assumes it.
- **No path prefix.** At a subdomain root the proxy forwards paths unchanged and uvicorn runs
  with no `--root-path` (`ROOT_PATH` empty), so `https://tester.<host>/test/setup` reaches
  `/test/setup`. The tester's base URL is the bare origin, with no `/test` suffix and no trailing slash.
- **Long read timeout.** A run waits for the whole suite before answering: the profile's suite
  budget plus a 30 s guard, so up to 2,430 s with the Phase 5 profile (2,400 s budget), 1,830 s
  with Phase 4 and 630 s with Phase 3. Spec 3.0.0 §12 requires a proxy upstream read timeout of
  at least 2,430 s; the proxy files allow 2,460 s. Never set less than 2,430 s. Anything else
  between the grader and the tester (a load balancer, a tunnel, the caller's own client) needs
  the same allowance.
- **Persistent, private database.** Reports live only in the SQLite file; losing it loses them.
- **Loopback only.** The tester listens on 127.0.0.1:8001; only the proxy is public.

## 1. Prepare settings

1. Generate an operator token for graders and podmates:

   ```sh
   uv run python scripts/make_operator_token.py --subject team12-operator
   ```

   Give the raw token out through a private channel. Only the hash entry goes in the settings.
2. Copy `tester.env.example` and fill in:
   - `TESTER_OPERATOR_TOKEN_HASHES_JSON`: the hash entry from step 1.
   - `ALLOWED_TARGET_URLS`: each system base URL exactly as the operator will send it. Team 12's
     is `https://13.184.14.226.sslip.io` and Team 9's is `https://3.139.178.70.sslip.io/system`; neither
     has a trailing slash, and matching is exact.
   - `TARGET_AUTH_MAP_JSON`: the userA, userB, reviewer and test-admin tokens each system team
     provided privately. The optional `reviewer-ungranted` and `test-admin-2` identities are
     deferred to Phase 6, so leave them out for Phase 5.
3. Keep the file private (`chmod 600`), and never commit it. `deploy/*.env` is gitignored
   and excluded from the Docker build context.

The tester checks these settings at startup and refuses to start if a target is not HTTPS,
or a target is missing one of the four role tokens.

## 2a. Run with Docker Compose

```sh
cp deploy/tester.env.example deploy/tester.env      # then fill it in
docker compose -f deploy/compose.yaml up -d --build
docker compose -f deploy/compose.yaml logs -f tester
```

The database is on the `tester-data` volume at `/data/tester.db`. Compose sets this path
itself, overriding the systemd path in the env file. The port is published on 127.0.0.1 only.

## 2b. Run with systemd (no Docker)

On a Linux host with Python 3.12 and [uv](https://docs.astral.sh/uv/):

```sh
sudo useradd --system --home /opt/team12-tester --shell /usr/sbin/nologin team12-tester
sudo git clone <repo-url> /opt/team12-tester        # the branch you deploy
cd /opt/team12-tester && sudo uv sync --locked --no-dev
sudo install -d -m 700 /etc/team12-tester
sudo install -m 600 deploy/tester.env.example /etc/team12-tester/tester.env   # then fill it in
sudo cp deploy/systemd/team12-tester.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now team12-tester
journalctl -u team12-tester -f
```

systemd creates `/var/lib/team12-tester` for the database (`TESTER_DB_PATH` in the template).
If uv installed its Python under a home directory, use `uv sync --python /usr/bin/python3.12`,
because the unit runs with `ProtectHome=true`.

## 3. Put HTTPS in front

- **nginx:** get a certificate for the subdomain (e.g. `sudo certbot certonly --nginx -d
  tester.13.184.14.226.sslip.io`), copy `nginx/team12-tester.conf` to
  `/etc/nginx/conf.d/` with `tester.<host>` replaced by the subdomain, then
  `sudo nginx -t && sudo systemctl reload nginx`.
- **Caddy:** add the site block from `caddy/Caddyfile`, with `tester.<host>` replaced by the subdomain,
  next to the system's own site block. Caddy obtains the certificate itself.

The system keeps its own server or site block for the bare host name, so neither needs a path
prefix. Check `https://tester.<host>/openapi.json` afterwards. It should answer, and it should list no
`servers` prefix. A `/tester` prefix there means `ROOT_PATH` was left at `/tester`.

### Path-prefix alternative

To serve the tester under a path on a shared host instead (`https://<host>/tester`), use the
commented alternative in the nginx or Caddy file, and run uvicorn with `--root-path /tester`
(Docker: `ROOT_PATH=/tester`; systemd: append it to `ExecStart`). The proxy must strip `/tester`
before forwarding, since an unstripped `/tester/test/setup` returns 404 (checked by the rehearsal,
scenario D).

## 4. Smoke test

Once a real system is up and allowlisted:

```sh
TESTER_TOKEN=<operator token> uv run python scripts/smoke_test.py \
    --tester-url https://tester.13.184.14.226.sslip.io --target-url https://13.184.14.226.sslip.io
```

On PowerShell, set `$env:TESTER_TOKEN = '<operator token>'` first, and put the command on one line.

The script makes one real session on the target. It checks setup 201, a 409 report before the
run, run 200 with a valid report, a stored report identical to the run body, and a 409 second
run. It also prints the outcome counts, the coverage, and every fail or error. Exit code 0
means every check passed. Before a host exists, `scripts/rehearsal/rehearse.py` covers the
same interface locally (see the repo README).

## 5. Register

Fill in Team 12's row in the instructor endpoint registry:

| Field | Value |
| --- | --- |
| Tester base URL | `https://tester.13.184.14.226.sslip.io` (no `/test` suffix, no trailing slash) |
| Access / run notes | How to request an operator token (never the token itself); time limits: tester setup 45 s, tester run up to 2,430 s (Phase 5; callers and proxies need a read timeout of at least 2,430 s), system setup 30 s |

## Operating notes

- **Restarts:** stopping or restarting the tester mid-run aborts that suite. The next start
  stores an aborted report, keeping the results recorded so far. Setup and run are never replayed.
- **Phase 4:** set `MANIFEST_PATH=tester/fixtures/manifest_phase4.json`,
  `POD_PROFILE_PATH=tester/fixtures/pod_profile_phase4.json` and
  `EXPECTATIONS_PATH=tester/fixtures/phase4/expectations.json` (paths inside the image or
  checkout). The manifest is Team 12's draft until Team 9's 2.1.0 exists. A Phase 4 run creates
  up to five extra system sessions (fault, failed-audit, wrong-namespace and two cleanup-case
  sessions); they are listed in the run record as `fault_session_ids` and sent as
  `cleanup_session_ids` on the next setup.
- **Phase 5:** set `MANIFEST_PATH=tester/fixtures/manifest_phase5.json`,
  `POD_PROFILE_PATH=tester/fixtures/pod_profile_phase5.json`,
  `EXPECTATIONS_PATH=tester/fixtures/expectations_phase5.json`, `TESTER_TEAM_ID=team12`,
  `TARGET_TEAMS_JSON` (the team of every URL in `ALLOWED_TARGET_URLS`, same exact strings) and
  `DESIGN_MAP_PATH=tester/fixtures/design_map_team12.json`. Before the first Phase 5 run:
  - raise every proxy, tunnel and caller read timeout to at least 2,430 s (above);
  - check the deployment protection for the target system covers a 2,400 s run plus setup and
    coverage retrieval (spec §12: an expiring lease must never delete a session or interrupt a
    protected run; Team 9 sets its proxy timeout and renewable lease to 2,700 s each, as of
    2026-11-17);
  - leave out the `reviewer-ungranted` and `test-admin-2` tokens: both identities are deferred to
    Phase 6, and the five cases needing them skip, naming the missing identity;
  - expect many extra system sessions: every Phase 5 case that moves the clock or arms a fault
    prepares its own namespace (79 per run against the conforming stand-in, measured 2026-11-17).
    They are queued for cleanup once the run is stored, and each later setup sends at most 100 of
    them as `cleanup_session_ids` (Team 12's system refuses more), so a backlog drains over a few
    setups.
- **Pod profile or manifest changes:** each setup reads `tester/fixtures/pod_profile.json` and
  the manifest fresh, so new sessions pick up edits without affecting existing ones. With
  Docker, the files are baked into the image, so rebuild it (or mount overrides via
  `POD_PROFILE_PATH` / `MANIFEST_PATH`). A fixture pack (`EXPECTATIONS_PATH`) is re-hashed at
  each setup; a changed workbook refuses setup with a 500 naming the fixture.
- **Run records:** each finished run stores a record beside its report (versions, fixture
  hashes, revisions, start and end times, counts, per-operation outcomes, coverage evidence,
  fails and errors). Read one with `uv run python scripts/run_record.py --db <TESTER_DB_PATH>
  --session <id>` (Docker: `docker compose exec tester python scripts/run_record.py --db
  /data/tester.db --session <id>`); set `TESTER_REVISION` and `TARGET_REVISIONS_JSON` so it
  names the revisions.
- **Updating:** pull the new revision, then either rebuild the container, or run
  `uv sync --locked --no-dev` and `systemctl restart team12-tester`. Avoid updating during a run.
- **Backups:** copy the SQLite file while the tester is stopped, or use
  `sqlite3 tester.db ".backup copy.db"` while it runs.
- **Outbound traffic:** where the host allows it, restrict egress to the allowlisted targets.
