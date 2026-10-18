# Deploy Gustavo on Render

The root `render.yaml` creates a Docker web service and a PostgreSQL database
in the same region. Uploaded originals and audit results are stored in PostgreSQL,
not in the web service's temporary filesystem. Schema creation happens at startup.

Both resources use the free plan for a demo. Free web services sleep when idle;
the first request can take longer. The free database expires after 30 days and
has no backups. Choose a paid database before expiration to retain the data.

1. Sign in to https://dashboard.render.com using your GitHub account.
2. Ensure the reviewed deployment files and merged checker are published to the
   repository's **Gustavo** branch. Nothing is pushed automatically by this setup.
3. Choose **New > Blueprint**, connect the repository and select **Gustavo**.
4. Review `render.yaml`. For `API_TOKENS_JSON`, enter a private token-to-user map,
   for example `{"YOUR_RANDOM_SECRET_TOKEN":"test-user"}`. Generate a token in
   PowerShell with `python -c "import secrets; print(secrets.token_urlsafe(32))"`.
   Keep the actual token in Render's environment settings, not in Git.
5. Create the Blueprint. Render supplies `DATABASE_URL` automatically; no AWS
   credentials are needed. Do not add `DB_HOST` or AWS database environment values.
6. Open the service's assigned HTTPS URL. `/api/v1/health` should return
   `AVAILABLE`. Enter your token on the website and upload a workbook.
7. A rejected workbook returns HTTP 422. An accepted workbook starts an audit;
   the website displays the runner's findings after polling the audit endpoint.

Automatic deployments are disabled. After publishing later updates to Gustavo,
use **Manual Deploy > Deploy latest commit** on the service.

Existing local SQLite uploads are not copied into this new database.
Changing hosts does not delete any resources previously created in AWS.
