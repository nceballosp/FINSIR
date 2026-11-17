<#
.SYNOPSIS
  Applies model-training Terraform and starts the training Step Function.
.DESCRIPTION
  The state machine starts/stops the EC2 and runs the training command through
  Systems Manager. Configure create_instance=true in terraform.tfvars first.
#>
$ErrorActionPreference = "Stop"

$TfDir = Join-Path $PSScriptRoot "terraform"
$TfvarsPath = Join-Path $TfDir "terraform.tfvars"

if (-not (Test-Path -LiteralPath $TfvarsPath)) {
  throw "Missing $TfvarsPath. Copy terraform.tfvars.example, set create_instance=true, and configure the model bucket first."
}

$InstanceEnabled = Select-String -Path $TfvarsPath -Pattern '^\s*create_instance\s*=\s*true\s*(#.*)?$' -Quiet
if (-not $InstanceEnabled) {
  throw "Set create_instance = true in $TfvarsPath before deploying and starting model training."
}

$AwsProfile = Read-Host "AWS profile [terraform]"
if ([string]::IsNullOrWhiteSpace($AwsProfile)) { $AwsProfile = "terraform" }
$Region = Read-Host "AWS region [us-east-1]"
if ([string]::IsNullOrWhiteSpace($Region)) { $Region = "us-east-1" }
$env:AWS_PROFILE = $AwsProfile
$env:TF_VAR_region = $Region

aws sts get-caller-identity --region $Region --output text | Out-Null
if ($LASTEXITCODE -ne 0) { throw "AWS credentials are unavailable for profile '$AwsProfile'." }

Write-Host "Applying model-training Terraform in $Region..."
terraform -chdir="$TfDir" init -input=false
if ($LASTEXITCODE -ne 0) { throw "terraform init failed." }

$PlanFile = Join-Path ([System.IO.Path]::GetTempPath()) ("finsir-training-" + [guid]::NewGuid().ToString("N") + ".tfplan")
try {
  terraform -chdir="$TfDir" plan "-out=$PlanFile"
  if ($LASTEXITCODE -ne 0) { throw "terraform plan failed." }

  terraform -chdir="$TfDir" apply $PlanFile
  if ($LASTEXITCODE -ne 0) { throw "terraform apply failed; training was not started." }
} finally {
  Remove-Item -LiteralPath $PlanFile -Force -ErrorAction SilentlyContinue
}

$StateMachineArn = (terraform -chdir="$TfDir" output -raw training_state_machine_arn).Trim()
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($StateMachineArn)) {
  throw "Training Step Function was not created. Check create_instance=true and review terraform output."
}

$ExecutionArn = aws stepfunctions start-execution `
  --state-machine-arn $StateMachineArn `
  --input '{}' `
  --region $Region `
  --query executionArn `
  --output text
if ($LASTEXITCODE -ne 0) { throw "Could not start the model-training Step Function." }

Write-Host "Model training started: $ExecutionArn"
Write-Host "State machine: $StateMachineArn"
Write-Host "Monitor the execution in AWS Step Functions or use:"
Write-Host "  aws stepfunctions describe-execution --execution-arn $ExecutionArn --region $Region --query status --output text"
