param(
    [string]$Region = 'us-east-2',
    [string]$Profile = 'coursework',
    [string]$InstanceId = 'i-0b6df01f860ba04fd'
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
    Remove-Item -LiteralPath (Join-Path $configDirectory 'config.json') -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $configDirectory -ErrorAction SilentlyContinue
}
$script = @'
#!/bin/bash
set -euo pipefail
aws ecr get-login-password --region __REGION__ | docker login --username AWS --password-stdin __REGISTRY__
docker pull __IMAGE__
release="__REVISION__-$(date -u +%Y%m%dT%H%M%SZ)"
previous="workbook-previous-$release"
# SQLite's backup API includes committed WAL data and leaves the live source unchanged.
docker exec workbook python -c "import sqlite3; source=sqlite3.connect('/service/data/workbooks.sqlite3'); backup=sqlite3.connect('/service/data/pre-deploy-$release.sqlite3'); source.backup(backup); print('Pre-deploy versions:', source.execute('SELECT COUNT(*) FROM versions').fetchone()[0]); backup.close(); source.close()"
rollback() {
    trap - ERR
    docker rm -f workbook >/dev/null 2>&1 || true
    docker rename "$previous" workbook
    docker start workbook
    echo "Update failed; previous app restored."
    exit 1
}
docker rename workbook "$previous"
trap rollback ERR
docker stop --time 200 "$previous"
docker run -d --restart unless-stopped --name workbook --env-file /opt/workbook/app.env -e DATABASE_PATH=/service/data/workbooks.sqlite3 -v /opt/workbook/data:/service/data -p 127.0.0.1:8000:8000 __IMAGE__
ready=false
for attempt in $(seq 1 30); do
    if curl --max-time 3 -fsS http://127.0.0.1:8000/api/v1/health; then ready=true; break; fi
    sleep 2
done
test "$ready" = true
docker exec workbook python -c "import sqlite3; db=sqlite3.connect('/service/data/workbooks.sqlite3'); print('Post-deploy versions:', db.execute('SELECT COUNT(*) FROM versions').fetchone()[0]); print('Integrity:', db.execute('PRAGMA integrity_check').fetchone()[0])"
docker inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' workbook
trap - ERR
echo "Update succeeded; existing token, database, HTTPS proxy, and instance preserved."
'@
$script = $script.Replace('__REGION__',$Region).Replace('__REGISTRY__',$registry).Replace('__IMAGE__',$image).Replace('__REVISION__',$revision.Substring(0,12))
$deployDirectory = Join-Path $projectRoot 'data/deploy'
New-Item -ItemType Directory -Path $deployDirectory -Force | Out-Null
$parametersPath = Join-Path $deployDirectory 'update-command.json'
@{commands=@($script);executionTimeout=@('600')} | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $parametersPath -Encoding Ascii
$command = Invoke-Aws @('ssm','send-command','--instance-ids',$InstanceId,'--document-name','AWS-RunShellScript','--parameters',"file://$parametersPath",'--query','Command.CommandId','--output','text')
Write-Host "Updating instance $InstanceId; SSM command: $command"
for ($attempt=0; $attempt -lt 120; $attempt++) {
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
