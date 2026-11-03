<#
.SYNOPSIS
  Interactive deploy for the FINSIR API on ECS Fargate (Windows).
.DESCRIPTION
  Prompts for the values a new user would otherwise set by hand (account id,
  profile, region, auth secret), optionally builds and pushes the image to ECR,
  writes terraform.tfvars, and runs terraform init/apply in terraform-ecs/.
#>
$ErrorActionPreference = "Stop"

$ApiDir = $PSScriptRoot
$TfDir  = Join-Path $ApiDir "terraform-ecs"

function Ask($prompt, $default) {
  if ($default) { $reply = Read-Host "$prompt [$default]"; if ([string]::IsNullOrWhiteSpace($reply)) { return $default } else { return $reply } }
  return Read-Host $prompt
}
function AskSecret($prompt) {
  $sec = Read-Host -AsSecureString $prompt
  return [Runtime.InteropServices.Marshal]::PtrToStringAuto(
    [Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec))
}
function AskYesNo($prompt, $default) {
  $hint = if ($default -eq "y") { "Y/n" } else { "y/N" }
  $reply = Read-Host "$prompt [$hint]"
  if ([string]::IsNullOrWhiteSpace($reply)) { $reply = $default }
  if ($reply -match '^[Yy]') { return "true" } else { return "false" }
}

Write-Host "== FINSIR API (ECS Fargate) deploy =="

$AwsProfile = Ask "AWS profile" "terraform"
$Region     = Ask "AWS region" "us-east-1"
$Project    = Ask "Project prefix" "finsir"
$env:AWS_PROFILE = $AwsProfile

try { $AccountId = (aws sts get-caller-identity --query Account --output text).Trim() } catch { $AccountId = "" }
$AccountId = Ask "AWS account id" $AccountId
while ($AccountId -notmatch '^\d{12}$') {
  Write-Host "Account id must be 12 digits."
  $AccountId = Ask "AWS account id" ""
}

$EcrRepo  = Ask "ECR repository name" "$Project-api"
$ImageTag = Ask "Image tag" "latest"
$EcrUrl   = "$AccountId.dkr.ecr.$Region.amazonaws.com/$EcrRepo"

do {
  $AuthDevSecret = AskSecret "Auth dev secret (>= 16 chars, hidden)"
  if ($AuthDevSecret.Length -lt 16) { Write-Host "Secret must be at least 16 characters." }
} while ($AuthDevSecret.Length -lt 16)

$AuthScope  = Ask "Required auth scope" "gold:read"
$AthenaDb   = Ask "Athena database" $Project
$AthenaWg   = Ask "Athena workgroup" $Project
$AthenaTbl  = Ask "Athena table" "gold_train"
$ServiceEnv = Ask "Service environment (local|dev|uat|prod)" "dev"

if ((AskYesNo "Build and push the Docker image to ECR now?" "n") -eq "true") {
  aws ecr describe-repositories --repository-names $EcrRepo --region $Region 2>$null | Out-Null
  if ($LASTEXITCODE -ne 0) {
    Write-Host "Creating ECR repository $EcrRepo..."
    aws ecr create-repository --repository-name $EcrRepo --region $Region | Out-Null
  }
  $registry = $EcrUrl.Split('/')[0]
  aws ecr get-login-password --region $Region | docker login --username AWS --password-stdin $registry
  docker build -t "${EcrUrl}:${ImageTag}" $ApiDir
  docker push "${EcrUrl}:${ImageTag}"
}

@"
region              = "$Region"
project             = "$Project"
ecr_repository_name = "$EcrRepo"
image_tag           = "$ImageTag"
athena_database     = "$AthenaDb"
athena_workgroup    = "$AthenaWg"
athena_table        = "$AthenaTbl"
auth_required_scope = "$AuthScope"
service_environment = "$ServiceEnv"
"@ | Set-Content -Encoding ascii (Join-Path $TfDir "terraform.tfvars")
Write-Host "Wrote $TfDir\terraform.tfvars (secret passed via TF_VAR, not written to disk)"

Set-Location $TfDir
terraform init
$env:TF_VAR_auth_dev_secret = $AuthDevSecret
try { terraform apply } finally { Remove-Item Env:\TF_VAR_auth_dev_secret -ErrorAction SilentlyContinue }

# Resolve the task's public IP (there is no ALB; the IP changes on every redeploy).
# The Fargate task takes a moment to start, so poll for the task and its IP.
Write-Host "Resolving the public IP (waiting for the Fargate task to start)..."
$Cluster = (terraform output -raw cluster_name).Trim()
$Service = (terraform output -raw service_name).Trim()
$PublicIp = ""
for ($i = 0; $i -lt 30; $i++) {
  $task = (aws ecs list-tasks --cluster $Cluster --service-name $Service --desired-status RUNNING --region $Region --query 'taskArns[0]' --output text 2>$null)
  if ($task -and $task -ne "None") {
    $eni = (aws ecs describe-tasks --cluster $Cluster --tasks $task --region $Region --query 'tasks[0].attachments[0].details[?name==`networkInterfaceId`].value | [0]' --output text 2>$null)
    if ($eni -and $eni -ne "None") {
      $PublicIp = (aws ec2 describe-network-interfaces --network-interface-ids $eni --region $Region --query 'NetworkInterfaces[0].Association.PublicIp' --output text 2>$null)
      if ($PublicIp -and $PublicIp -ne "None") { break }
    }
  }
  Start-Sleep -Seconds 10
}

Write-Host ""
Write-Host "================ FINSIR API deployed ================"
if ($PublicIp -and $PublicIp -ne "None") {
  Write-Host "Public URL : http://${PublicIp}:8080"
  Write-Host "Health     : http://${PublicIp}:8080/health"
} else {
  Write-Host "Public URL : task not RUNNING yet; re-run the IP lookup in terraform-ecs/README.md shortly."
}
Write-Host "Auth secret: $AuthDevSecret"
Write-Host "Auth scope : $AuthScope"
Write-Host "====================================================="
Write-Host "Mint a dev token with this secret (see terraform-ecs/README.md 'Call the API')."
