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

@"
region        = "$Region"
project       = "$Project"
create_bucket = $CreateBucket
bucket_name   = "$BucketName"
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

if ((AskYesNo "Start the cleaning Glue job now?" "n") -eq "true") {
  aws glue start-job-run --job-name "$Project-limpieza-train" --region $Region
  Write-Host "Cleaning job started. Build the gold tables only after it SUCCEEDED:"
  Write-Host "  aws glue start-job-run --job-name $Project-gold-train --region $Region"
  Write-Host "  aws glue start-job-run --job-name $Project-gold-segment-conversion --region $Region"
}

Write-Host "Done."
