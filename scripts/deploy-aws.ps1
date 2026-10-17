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
$password = Invoke-Aws -Arguments @('ecr', 'get-login-password')
$password | & docker login --username AWS --password-stdin $registry
$password = $null
if ($LASTEXITCODE -ne 0) { throw 'Docker registry login failed.' }
$tag = [Guid]::NewGuid().ToString('N')
$imageUri = "$($repository.repositoryUri):$tag"
& docker build --platform linux/amd64 --tag $imageUri $projectRoot
if ($LASTEXITCODE -ne 0) { throw 'Docker build failed.' }
& docker push $imageUri
if ($LASTEXITCODE -ne 0) { throw 'Container image upload failed.' }
Invoke-Aws -Arguments @('cloudformation', 'deploy', '--stack-name', $StackName,
    '--template-file', $template, '--parameter-overrides', "ImageUri=$imageUri",
    '--capabilities', 'CAPABILITY_IAM', '--no-fail-on-empty-changeset') | Out-Host
Invoke-Aws -Arguments @('cloudformation', 'describe-stacks', '--stack-name', $StackName,
    '--query', 'Stacks[0].Outputs', '--output', 'table') | Out-Host
