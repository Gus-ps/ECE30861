# AWS demo deployment

Run `scripts/deploy-ec2-demo.ps1` from PowerShell with Docker Desktop running and
an authenticated AWS CLI `coursework` profile. It builds the current workspace,
publishes the image to the existing `workbook-service-images` ECR repository,
and creates the `workbook-demo` CloudFormation stack in Ohio.

This is a single `t3.micro` instance with an encrypted 20 GB EBS root volume.
EC2, storage and public IPv4 consume eligible AWS credits. It is not a permanently
free service. No RDS database or load balancer is created. The validator and
Haruki's runner run in the app container. SQLite stores uploads and audits under
`/opt/workbook/data` on the instance; it survives container restarts and redeploys.
Existing local uploads are not migrated. The disk is retained on termination;
retained disks continue to use storage and must be managed separately.

Caddy serves HTTPS using the instance's `<public-ip>.sslip.io` hostname, with
automatic certificates. This demo hostname depends on the third-party sslip.io
DNS service. Only HTTP (certificate verification and HTTPS redirects) and HTTPS
are exposed; port 8000 is bound to localhost and SSH is closed.

Use AWS Systems Manager Session Manager to administer the instance. The generated
bearer-token mapping is in `/opt/workbook/app.env`, readable by root. Do not
commit it or print it in shared logs. Container logs are available through
`sudo docker logs workbook` and `sudo docker logs workbook-https`.

The public IP, and therefore demo hostname, can change after an instance stop/start.
For a longer-lived installation use a stable address and your own domain, add
database backups, and monitor usage. Re-running the deployment script replaces
the instance when its image/user-data changes; it does not migrate data from the
old disk. To preserve the active database during updates, pull the new image and
replace the app container on the same instance, keeping `/opt/workbook/data` mounted.
