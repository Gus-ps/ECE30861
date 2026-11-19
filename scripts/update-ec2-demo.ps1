param(
    [string]$Region = 'us-east-2',
    [string]$Profile = 'coursework',
    [string]$InstanceId = 'i-0b6df01f860ba04fd',
    [switch]$BuildOnInstance
)
$ErrorActionPreference = 'Stop'
$env:Path += ";$env:LOCALAPPDATA\Programs\Amazon\AWSCLIV2"
$projectRoot = Split-Path -Parent $PSScriptRoot
function Invoke-Aws {
    param([string[]]$Arguments)
    $result = & aws @Arguments --region $Region --profile $Profile --no-cli-pager
    if ($LASTEXITCODE -ne 0) { throw "AWS failed: $($Arguments[0..1] -join ' ')" }
    return $result
}
$branch = & git -C $projectRoot branch --show-current
if ($branch -ne 'Gustavo') { throw 'Run the release from Gustavo.' }
$changedCode = & git -C $projectRoot diff HEAD --name-only
$changedCode = $changedCode | Where-Object { $_ -notmatch '\.(md|docx|pdf)$' }
if ($changedCode) { throw 'Commit tracked code changes before releasing.' }
$revision = & git -C $projectRoot rev-parse HEAD
$account = Invoke-Aws @('sts','get-caller-identity','--query','Account','--output','text')
$registry = "$account.dkr.ecr.$Region.amazonaws.com"
$image = "$registry/workbook-service-images:release-$revision-$([Guid]::NewGuid().ToString('N'))"
if (-not $BuildOnInstance) {
$configDirectory = Join-Path ([System.IO.Path]::GetTempPath()) ("workbook-update-" + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $configDirectory | Out-Null
$authEntries = @{}; $authEntries[$registry] = @{}
@{auths=$authEntries} | ConvertTo-Json -Depth 4 | Set-Content (Join-Path $configDirectory 'config.json') -Encoding Ascii
$engine = & docker context inspect --format '{{.Endpoints.docker.Host}}'
if ($LASTEXITCODE -ne 0) { throw 'Docker Desktop is unavailable.' }
try {
    Invoke-Aws @('ecr','get-login-password') | & docker --config $configDirectory --host $engine login --username AWS --password-stdin $registry
    if ($LASTEXITCODE -ne 0) { throw 'Docker login failed.' }
    & docker --config $configDirectory --host $engine build --platform linux/amd64 --label "org.opencontainers.image.revision=$revision" -t $image $projectRoot
    if ($LASTEXITCODE -ne 0) { throw 'Docker build failed.' }
    & docker --config $configDirectory --host $engine push $image
    if ($LASTEXITCODE -ne 0) { throw 'Docker push failed.' }
} finally {
    [System.IO.File]::Delete((Join-Path $configDirectory 'config.json'))
    $resolvedConfig = [System.IO.Path]::GetFullPath($configDirectory)
    $resolvedTemporaryRoot = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath()).TrimEnd('\', '/')
    if ([System.IO.Path]::GetDirectoryName($resolvedConfig) -ne $resolvedTemporaryRoot -or
        -not [System.IO.Path]::GetFileName($resolvedConfig).StartsWith('workbook-update-')) {
        throw 'Unexpected Docker configuration cleanup target.'
    }
    [System.IO.Directory]::Delete($resolvedConfig, $true)
}
}
$script = @'
#!/bin/bash
set -euo pipefail
if [ "__BUILD_ON_INSTANCE__" = "true" ]; then
    # Build the exact pushed commit on the existing host; no new AWS resources.
    source_dir="/opt/workbook/releases/__FULL_REVISION__"
    install -d -m 0700 "$source_dir"
    curl --retry 2 -fsSL "https://codeload.github.com/Gus-ps/ECE30861/tar.gz/__FULL_REVISION__" -o "$source_dir/source.tar.gz"
    tar -xzf "$source_dir/source.tar.gz" --strip-components=1 -C "$source_dir"
    rm "$source_dir/source.tar.gz"
    docker build --platform linux/amd64 --label "org.opencontainers.image.revision=__FULL_REVISION__" -t __IMAGE__ "$source_dir"
    # Gate the installed artifact on the host with adequate disk space, before
    # stopping the live service. Tests use only temporary databases and mocks.
    docker run --rm --user 0:0 --entrypoint sh -v "$source_dir:/review:ro" -w /tmp \
        -e PYTHONPATH=/tmp/release-checks:/review/tests:/review \
        -e DATABASE_PATH=/tmp/release-checks.sqlite3 -e AWS_EC2_METADATA_DISABLED=true \
        __IMAGE__ -c 'python -m pip install --no-cache-dir --target /tmp/release-checks httpx==0.28.1 >/tmp/checks-install.log && cd /review && python scripts/test_gate.py'

else
    aws ecr get-login-password --region __REGION__ | docker login --username AWS --password-stdin __REGISTRY__
    docker pull __IMAGE__
fi
release="__REVISION__-$(date -u +%Y%m%dT%H%M%SZ)"
previous="workbook-previous-$release"
envbackup="/opt/workbook/app.env.before-$release"
cp -p /opt/workbook/app.env "$envbackup"
install -d -m 0700 -o 1000 -g 1000 /opt/workbook/deletion-ledger
# Refuse a release while our hosted tester is running, even against another pod.
if test -f /opt/workbook-tester/data/tester.sqlite3; then
python3 - <<'PYTHON'
import sqlite3
with sqlite3.connect('file:/opt/workbook-tester/data/tester.sqlite3?mode=ro',uri=True) as db:
    if db.execute("SELECT 1 FROM sessions WHERE state IN ('RUNNING','PREPARING') LIMIT 1").fetchone():
        raise SystemExit('Release deferred: hosted tester has an active run.')
PYTHON
fi
# New images protect external testers too. Older releases lack this capability;
# their first upgrade must be coordinated with both teams.
if docker exec workbook test -f /service/release_guard.py; then
    docker exec workbook python /service/release_guard.py arm
    trap 'docker exec workbook python /service/release_guard.py resume >/dev/null 2>&1 || true' ERR
fi

# SQLite's backup API includes committed WAL data and leaves the live source unchanged.
docker exec workbook python -c "import sqlite3; source=sqlite3.connect('/service/data/workbooks.sqlite3'); backup=sqlite3.connect('/service/data/pre-deploy-$release.sqlite3'); source.backup(backup); print('Pre-deploy versions:', source.execute('SELECT COUNT(*) FROM versions').fetchone()[0]); backup.close(); source.close()"
rollback() {
    trap - ERR
    docker rm -f workbook >/dev/null 2>&1 || true
    cp -p "$envbackup" /opt/workbook/app.env
    docker rename "$previous" workbook
    docker start workbook
    echo "Update failed; previous app restored."
    exit 1
}
docker rename workbook "$previous"
trap rollback ERR
docker stop --time 200 "$previous"
# Hash existing credentials without changing the tokens held by users/testers.
# The protected original is retained for release rollback only.
python3 - <<'PYTHON'
import hashlib,json,os
from pathlib import Path
p=Path('/opt/workbook/app.env')
lines=[]
for line in p.read_text().splitlines():
    key,separator,value=line.partition('=')
    if separator and key in ('API_TOKENS_JSON','TEST_ADMIN_TOKENS_JSON'):
        mapping=json.loads(value)
        value=json.dumps({token if token.startswith('sha256:') else 'sha256:'+hashlib.sha256(token.encode()).hexdigest():subject for token,subject in mapping.items()},separators=(',',':'))
        line=key+'='+value
    lines.append(line)
p.write_text('\n'.join(lines)+'\n');os.chmod(p,0o600)
PYTHON
docker run -d --restart unless-stopped --name workbook --env-file /opt/workbook/app.env \
    -e ENABLE_TEST_FAULTS=true -e ENABLE_TEST_CLOCK=true -e DATABASE_PATH=/service/data/workbooks.sqlite3 \
    -e DELETION_LEDGER_PATH=/service/deletion-ledger/deletions.jsonl \
    -v /opt/workbook/data:/service/data -v /opt/workbook/deletion-ledger:/service/deletion-ledger \
    -p 127.0.0.1:8000:8000 __IMAGE__
ready=false
for attempt in $(seq 1 30); do
    if curl --max-time 3 -fsS http://127.0.0.1:8000/api/v1/health; then ready=true; break; fi
    sleep 2
done
test "$ready" = true
docker exec workbook python -c "import sqlite3; db=sqlite3.connect('/service/data/workbooks.sqlite3'); print('Post-deploy versions:', db.execute('SELECT COUNT(*) FROM versions').fetchone()[0]); print('Integrity:', db.execute('PRAGMA integrity_check').fetchone()[0])"
# Apply transport policy while preserving the existing proxy on validation failure.
METADATA_TOKEN=$(curl -fsS -X PUT -H 'X-aws-ec2-metadata-token-ttl-seconds: 300' http://169.254.169.254/latest/api/token)
PUBLIC_IP=$(curl -fsS -H "X-aws-ec2-metadata-token: $METADATA_TOKEN" http://169.254.169.254/latest/meta-data/public-ipv4)
cp -p /opt/workbook/caddy/Caddyfile /opt/workbook/caddy/Caddyfile.before-phase5
cat > /opt/workbook/caddy/Caddyfile <<'CADDY'
__CADDY_CONFIG__
CADDY
sed -i "s/__HOST__/$PUBLIC_IP.sslip.io/g" /opt/workbook/caddy/Caddyfile
if ! docker exec workbook-https caddy validate --config /etc/caddy/Caddyfile; then
    cp -p /opt/workbook/caddy/Caddyfile.before-phase5 /opt/workbook/caddy/Caddyfile
    false
fi
docker exec workbook-https caddy reload --config /etc/caddy/Caddyfile
docker inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' workbook
trap - ERR
find /opt/workbook/data -maxdepth 1 -type f -name 'pre-deploy-*.sqlite3' \
    ! -name "pre-deploy-$release.sqlite3" -delete
echo "Update succeeded; existing token, database, HTTPS proxy, and instance preserved."
'@
$script = $script.Replace('__BUILD_ON_INSTANCE__', $BuildOnInstance.IsPresent.ToString().ToLowerInvariant()).Replace('__FULL_REVISION__', $revision)
$script = $script.Replace('__CADDY_CONFIG__', (Get-Content -Raw (Join-Path $PSScriptRoot 'Caddyfile.template')))
$script = $script.Replace('__REGION__',$Region).Replace('__REGISTRY__',$registry).Replace('__IMAGE__',$image).Replace('__REVISION__',$revision.Substring(0,12))
$script = $script.Replace("`r`n", "`n")
$deployDirectory = Join-Path $projectRoot 'data/deploy'
New-Item -ItemType Directory -Path $deployDirectory -Force | Out-Null
$parametersPath = Join-Path $deployDirectory 'update-command.json'
@{commands=@($script);executionTimeout=@('1800')} | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $parametersPath -Encoding Ascii
$command = Invoke-Aws @('ssm','send-command','--instance-ids',$InstanceId,'--document-name','AWS-RunShellScript','--parameters',"file://$parametersPath",'--query','Command.CommandId','--output','text')
Write-Host "Updating instance $InstanceId; SSM command: $command"
for ($attempt=0; $attempt -lt 360; $attempt++) {
    Start-Sleep -Seconds 5
    $result = (Invoke-Aws @('ssm','get-command-invocation','--command-id',$command,'--instance-id',$InstanceId,'--output','json')) | ConvertFrom-Json
    if ($result.Status -in @('Pending','InProgress','Delayed')) { continue }
    Write-Host $result.StandardOutputContent
    if ($result.Status -ne 'Success') {
        Write-Host $result.StandardErrorContent
        throw "Deployment status: $($result.Status)"
    }
    Write-Host "Released commit $revision"
    return
}
throw "Update is still running. Inspect SSM command $command before retrying."
