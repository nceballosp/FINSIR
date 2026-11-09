<#
.SYNOPSIS
  Interactive deploy for the FINSIR data platform (S3 + Glue + Athena) on Windows.
.DESCRIPTION
  Prompts for the values a new user would otherwise set by hand, writes
  terraform.tfvars, runs terraform init/apply, and optionally uploads the raw
  CSV and starts the Glue jobs.
#>
$ErrorActionPreference = "Stop"

$TfDir = Join-Path $PSScriptRoot "terraform"
Set-Location $TfDir

function Ask($prompt, $default) {
  if ($default) { $reply = Read-Host "$prompt [$default]"; if ([string]::IsNullOrWhiteSpace($reply)) { return $default } else { return $reply } }
  return Read-Host $prompt
}
function AskYesNo($prompt, $default) {
  $hint = if ($default -eq "y") { "Y/n" } else { "y/N" }
  $reply = Read-Host "$prompt [$hint]"
  if ([string]::IsNullOrWhiteSpace($reply)) { $reply = $default }
  if ($reply -match '^[Yy]') { return "true" } else { return "false" }
}

Write-Host "== FINSIR data platform deploy =="

$AwsProfile = Ask "AWS profile" "terraform"
$Region     = Ask "AWS region" "us-east-1"
$Project    = Ask "Project prefix" "finsir"

$env:AWS_PROFILE = $AwsProfile
try { $AccountId = (aws sts get-caller-identity --query Account --output text).Trim() } catch { $AccountId = "" }
if ($AccountId) {
  Write-Host "Using account $AccountId (profile $AwsProfile)."
  $DefaultBucket = "$Project-$AccountId"
} else {
  Write-Host "Warning: could not resolve account id from profile '$AwsProfile'. Continuing."
  $DefaultBucket = ""
}

$CreateBucket = AskYesNo "Create a new S3 bucket?" "y"
if ($CreateBucket -eq "true") {
  $fallback = if ($DefaultBucket) { $DefaultBucket } else { "<project>-<account-id>" }
  $BucketName = Ask "Bucket name (empty = $fallback)" ""
} else {
  do { $BucketName = Ask "Existing bucket name" "" } while ([string]::IsNullOrWhiteSpace($BucketName))
}

# EventBridge schedule: off by default (the Step Functions still runs on demand).
$ScheduleEnabled = AskYesNo "Enable the EventBridge daily schedule now? (no = keep it off, run by hand)" "n"

@"
region           = "$Region"
project          = "$Project"
create_bucket    = $CreateBucket
bucket_name      = "$BucketName"
schedule_enabled = $ScheduleEnabled
"@ | Set-Content -Encoding ascii (Join-Path $TfDir "terraform.tfvars")
Write-Host "Wrote $TfDir\terraform.tfvars"

terraform init
terraform apply

$Bucket = (terraform output -raw bucket).Trim()
Write-Host "Bucket: $Bucket"

$DefaultCsv = Join-Path (Resolve-Path (Join-Path $TfDir "..\..\..")) "data\train_ver2.csv"
if ((AskYesNo "Upload the raw CSV now?" "n") -eq "true") {
  $CsvPath = Ask "Path to train_ver2.csv" $DefaultCsv
  if (Test-Path $CsvPath) {
    aws s3 cp $CsvPath "s3://$Bucket/raw/train/train_ver2.csv" --region $Region
  } else {
    Write-Host "File not found: $CsvPath (skipping upload)."
  }
}

# Run the whole batch via Step Functions: cleaning -> gold tables in parallel.
try { $SmArn = (terraform output -raw state_machine_arn).Trim() } catch { $SmArn = "" }
if ((AskYesNo "Start the batch now (Step Functions: cleaning -> gold tables)?" "n") -eq "true") {
  if ($SmArn) {
    # Pasar el JSON por archivo evita que Windows PowerShell quite las comillas
    # internas al invocar un ejecutable nativo (aws.exe).
    $GoldInput = @{ gold_jobs = @("$Project-gold-train", "$Project-gold-segment-conversion") } |
      ConvertTo-Json -Compress
    $InputFile = [System.IO.Path]::GetTempFileName()
    try {
      [System.IO.File]::WriteAllText($InputFile, $GoldInput, [System.Text.UTF8Encoding]::new($false))
      $ExecArn = (aws stepfunctions start-execution --state-machine-arn $SmArn `
        --input "file://$InputFile" --region $Region --query executionArn --output text).Trim()
      if ($LASTEXITCODE -ne 0) { throw "No se pudo iniciar el batch de Step Functions." }
    } finally {
      Remove-Item -LiteralPath $InputFile -Force -ErrorAction SilentlyContinue
    }
    Write-Host "Batch started: $ExecArn"
    Write-Host "Follow it with:"
    Write-Host "  aws stepfunctions describe-execution --execution-arn $ExecArn --region $Region --query status"
  } else {
    Write-Host "No orchestration found (create_orchestration is false?). Skipping."
  }
}

# Show how to run the batch again and the schedule state.
Write-Host ""
Write-Host "================ FINSIR batch orchestration ================"
if ($ScheduleEnabled -eq "true") {
  Write-Host "EventBridge schedule: ENABLED (cron default: 06:00 UTC daily)."
} else {
  Write-Host "EventBridge schedule: DISABLED. Run the batch by hand with the command below."
}
try { $RunBatch = (terraform output -raw run_batch).Trim() } catch { $RunBatch = "" }
if ($RunBatch) {
  Write-Host "Run the batch (cleaning -> gold tables in parallel):"
  Write-Host "  $RunBatch"
}
Write-Host "Enable/disable the schedule: set schedule_enabled in terraform.tfvars and re-apply."
Write-Host "============================================================"

Write-Host "Done."
