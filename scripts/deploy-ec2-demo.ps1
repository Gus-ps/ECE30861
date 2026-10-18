param([string]$Region = 'us-east-2', [string]$Profile = 'coursework')
$ErrorActionPreference = 'Stop'
$env:Path += ";$env:LOCALAPPDATA\Programs\Amazon\AWSCLIV2"
$projectRoot = Split-Path -Parent $PSScriptRoot
function Invoke-Aws {
    param([string[]]$Arguments)
    $result = & aws @Arguments --region $Region --profile $Profile --no-cli-pager
    if ($LASTEXITCODE -ne 0) { throw "AWS failed: $($Arguments[0..1] -join ' ')" }
    return $result
}
$account = Invoke-Aws @('sts','get-caller-identity','--query','Account','--output','text')
$vpc = Invoke-Aws @('ec2','describe-vpcs','--filters','Name=is-default,Values=true','--query','Vpcs[0].VpcId','--output','text')
$subnet = Invoke-Aws @('ec2','describe-subnets','--filters',"Name=vpc-id,Values=$vpc",'--query','Subnets[0].SubnetId','--output','text')
$ami = Invoke-Aws @('ssm','get-parameter','--name','/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64','--query','Parameter.Value','--output','text')
$registry = "$account.dkr.ecr.$Region.amazonaws.com"
$image = "$registry/workbook-service-images:demo-$([Guid]::NewGuid().ToString('N'))"
$configDirectory = Join-Path $projectRoot 'data/deploy/docker'
New-Item -ItemType Directory -Path $configDirectory -Force | Out-Null
$authEntries = @{}; $authEntries[$registry] = @{}
@{auths=$authEntries} | ConvertTo-Json -Depth 4 | Set-Content (Join-Path $configDirectory 'config.json') -Encoding Ascii
$engine = & docker context inspect --format '{{.Endpoints.docker.Host}}'
if ($LASTEXITCODE -ne 0) { throw 'Docker Desktop is unavailable' }
try {
    Invoke-Aws @('ecr','get-login-password') | & docker --config $configDirectory --host $engine login --username AWS --password-stdin $registry
    if ($LASTEXITCODE -ne 0) { throw 'Docker login failed' }
    & docker --config $configDirectory --host $engine build --platform linux/amd64 -t $image $projectRoot
    if ($LASTEXITCODE -ne 0) { throw 'Docker build failed' }
    & docker --config $configDirectory --host $engine push $image
    if ($LASTEXITCODE -ne 0) { throw 'Docker push failed' }
} finally {
    Remove-Item -LiteralPath (Join-Path $configDirectory 'config.json') -Force -ErrorAction SilentlyContinue
}
$bootstrap = @'
#!/bin/bash
set -euo pipefail
dnf install -y docker
systemctl enable --now docker
mkdir -p /opt/workbook/data /opt/workbook/caddy
chown 1000:1000 /opt/workbook/data
umask 077
printf 'API_TOKENS_JSON={"%s":"test-user"}\n' "$(openssl rand -hex 32)" > /opt/workbook/app.env
aws ecr get-login-password --region __REGION__ | docker login --username AWS --password-stdin __REGISTRY__
docker pull __IMAGE__
docker run -d --restart unless-stopped --name workbook --env-file /opt/workbook/app.env -e DATABASE_PATH=/service/data/workbooks.sqlite3 -v /opt/workbook/data:/service/data -p 127.0.0.1:8000:8000 __IMAGE__
METADATA_TOKEN=$(curl -fsS -X PUT -H 'X-aws-ec2-metadata-token-ttl-seconds: 300' http://169.254.169.254/latest/api/token)
PUBLIC_IP=$(curl -fsS -H "X-aws-ec2-metadata-token: $METADATA_TOKEN" http://169.254.169.254/latest/meta-data/public-ipv4)
printf '%s.sslip.io {\n reverse_proxy 127.0.0.1:8000\n}\n' "$PUBLIC_IP" > /opt/workbook/caddy/Caddyfile
docker run -d --restart unless-stopped --name workbook-https --network host -v /opt/workbook/caddy/Caddyfile:/etc/caddy/Caddyfile:ro -v workbook-caddy-data:/data -v workbook-caddy-config:/config caddy:2
'@
$bootstrap = $bootstrap.Replace('__REGION__', $Region).Replace('__REGISTRY__', $registry).Replace('__IMAGE__', $image)
$template = @{
    AWSTemplateFormatVersion='2010-09-09'
    Description='Single-instance workbook demo with persistent SQLite and HTTPS; no load balancer or RDS'
    Resources=@{
        Role=@{Type='AWS::IAM::Role';Properties=@{
            AssumeRolePolicyDocument=@{Version='2012-10-17';Statement=@(@{Effect='Allow';Principal=@{Service='ec2.amazonaws.com'};Action='sts:AssumeRole'})}
            ManagedPolicyArns=@('arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore')
            Policies=@(@{PolicyName='PullWorkbookImage';PolicyDocument=@{Version='2012-10-17';Statement=@(
                @{Effect='Allow';Action='ecr:GetAuthorizationToken';Resource='*'},
                @{Effect='Allow';Action=@('ecr:BatchCheckLayerAvailability','ecr:GetDownloadUrlForLayer','ecr:BatchGetImage');Resource="arn:aws:ecr:${Region}:${account}:repository/workbook-service-images"}
            )}})
        }}
        InstanceProfile=@{Type='AWS::IAM::InstanceProfile';Properties=@{Roles=@(@{Ref='Role'})}}
        SecurityGroup=@{Type='AWS::EC2::SecurityGroup';Properties=@{
            GroupDescription='Workbook demo HTTPS and certificate verification; no SSH';VpcId=$vpc
            SecurityGroupIngress=@(@{IpProtocol='tcp';FromPort=80;ToPort=80;CidrIp='0.0.0.0/0'},@{IpProtocol='tcp';FromPort=443;ToPort=443;CidrIp='0.0.0.0/0'})
        }}
        Instance=@{Type='AWS::EC2::Instance';Properties=@{
            ImageId=$ami;InstanceType='t3.micro';IamInstanceProfile=@{Ref='InstanceProfile'}
            MetadataOptions=@{HttpTokens='required';HttpEndpoint='enabled'}
            NetworkInterfaces=@(@{DeviceIndex='0';AssociatePublicIpAddress=$true;SubnetId=$subnet;GroupSet=@(@{Ref='SecurityGroup'})})
            BlockDeviceMappings=@(@{DeviceName='/dev/xvda';Ebs=@{VolumeSize=20;VolumeType='gp3';Encrypted=$true;DeleteOnTermination=$false}})
            UserData=@{'Fn::Base64'=$bootstrap};Tags=@(@{Key='Name';Value='workbook-demo'})
        }}
    }
    Outputs=@{
        InstanceId=@{Value=@{Ref='Instance'}}
        ServiceUrl=@{Value=@{'Fn::Sub'='https://${Instance.PublicIp}.sslip.io'}}
    }
}
$templatePath = Join-Path $projectRoot 'data/deploy/ec2-demo.json'
$template | ConvertTo-Json -Depth 30 | Set-Content -LiteralPath $templatePath -Encoding Ascii
Invoke-Aws @('cloudformation','deploy','--stack-name','workbook-demo','--template-file',$templatePath,'--capabilities','CAPABILITY_IAM','--no-fail-on-empty-changeset') | Out-Host
Invoke-Aws @('cloudformation','describe-stacks','--stack-name','workbook-demo','--query','Stacks[0].Outputs','--output','table') | Out-Host
