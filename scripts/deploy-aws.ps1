param(
    [Parameter(Mandatory = $true)][string]$Region,
    [ValidatePattern('^[a-z][a-z0-9-]{2,40}$')][string]$StackName = 'workbook-service',
    [string]$Profile,
    [switch]$Deploy
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$template = Join-Path $projectRoot 'infrastructure/aws.yaml'
$awsOptions = @('--region', $Region)
if ($Profile) { $awsOptions += @('--profile', $Profile) }

function Invoke-Aws {
    param([string[]]$Arguments)
    $result = & aws @Arguments @awsOptions
    if ($LASTEXITCODE -ne 0) { throw "AWS command failed: $($Arguments[0..1] -join ' ')" }
    return $result
}

Get-Command aws -ErrorAction Stop | Out-Null
# Default invocation performs read-only checks; -Deploy explicitly creates billable resources.
$identity = (Invoke-Aws -Arguments @('sts', 'get-caller-identity', '--output', 'json')) | ConvertFrom-Json
Invoke-Aws -Arguments @('cloudformation', 'validate-template', '--template-body', "file://$template", '--output', 'json') | Out-Null
Write-Host "Template validated. AWS account: $($identity.Account); region: $Region; stack: $StackName"
if (-not $Deploy) {
    Write-Host 'No resources created. Run again with -Deploy to build, publish the image to ECR, and deploy AWS resources.'
    return
}
Get-Command docker -ErrorAction Stop | Out-Null
& docker info | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Start Docker Desktop with Linux containers before deploying.' }
$repositoryName = "$StackName-images"
$repositories = (Invoke-Aws -Arguments @('ecr', 'describe-repositories', '--output', 'json')) | ConvertFrom-Json
$repository = $repositories.repositories | Where-Object { $_.repositoryName -eq $repositoryName }
if (-not $repository) {
    $created = (Invoke-Aws -Arguments @('ecr', 'create-repository', '--repository-name', $repositoryName,
        '--image-scanning-configuration', 'scanOnPush=true', '--image-tag-mutability', 'IMMUTABLE', '--output', 'json')) | ConvertFrom-Json
    $repository = $created.repository
}
$registry = ($repository.repositoryUri -split '/')[0]
$tag = [Guid]::NewGuid().ToString('N')
$imageUri = "$($repository.repositoryUri):$tag"
# Use a deployment-only config so broken Windows credential helpers cannot
# interrupt registry login. Preserve the selected Docker engine explicitly.
$engineHost = & docker context inspect --format '{{.Endpoints.docker.Host}}'
if ($LASTEXITCODE -ne 0 -or -not $engineHost) { throw 'Cannot determine the selected Docker engine.' }
$temporaryRoot = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
$dockerConfig = Join-Path $temporaryRoot ("workbook-docker-" + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $dockerConfig | Out-Null
try {
    # An existing auth entry also prevents Docker's automatic helper detection.
    $authEntries = @{}
    $authEntries[$registry] = @{}
    @{ auths = $authEntries } | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $dockerConfig 'config.json') -Encoding Ascii
    $dockerOptions = @('--config', $dockerConfig, '--host', $engineHost)
    $password = Invoke-Aws -Arguments @('ecr', 'get-login-password')
    $password | & docker @dockerOptions login --username AWS --password-stdin $registry
    $loginExitCode = $LASTEXITCODE
    $password = $null
    if ($loginExitCode -ne 0) { throw 'Docker registry login failed.' }
    & docker @dockerOptions build --platform linux/amd64 --tag $imageUri $projectRoot
    if ($LASTEXITCODE -ne 0) { throw 'Docker build failed.' }
    & docker @dockerOptions push $imageUri
    if ($LASTEXITCODE -ne 0) { throw 'Container image upload failed.' }
}
finally {
    $password = $null
    # Verify the cleanup target is the directory generated under the temp root.
    $resolvedConfig = [System.IO.Path]::GetFullPath($dockerConfig)
    if ([System.IO.Path]::GetDirectoryName($resolvedConfig) -eq $temporaryRoot.TrimEnd('\', '/') -and
        [System.IO.Path]::GetFileName($resolvedConfig).StartsWith('workbook-docker-')) {
        Remove-Item -LiteralPath $resolvedConfig -Recurse -Force
    }
}
Invoke-Aws -Arguments @('cloudformation', 'deploy', '--stack-name', $StackName,
    '--template-file', $template, '--parameter-overrides', "ImageUri=$imageUri",
    '--capabilities', 'CAPABILITY_IAM', '--no-fail-on-empty-changeset') | Out-Host
Invoke-Aws -Arguments @('cloudformation', 'describe-stacks', '--stack-name', $StackName,
    '--query', 'Stacks[0].Outputs', '--output', 'table') | Out-Host
