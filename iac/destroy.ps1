<#
.SYNOPSIS
  Interactive teardown for the FINSIR infra (API on ECS + data platform) on Windows.
.DESCRIPTION
  Destroys the API first (it reads the data platform), then the data platform.
  Asks whether to delete the S3 data lake (emptied first, since terraform
  destroy refuses a non-empty bucket) and whether to delete the ECR image.
#>
$ErrorActionPreference = "Stop"

$IacDir = $PSScriptRoot
$ApiTf  = Join-Path $IacDir "api\terraform-ecs"
$DataTf = Join-Path $IacDir "data-platform\terraform"

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
function TfOutput($dir, $name) {
  try { return (terraform -chdir="$dir" output -raw $name 2>$null).Trim() } catch { return "" }
}

Write-Host "== FINSIR infra teardown =="

$AwsProfile = Ask "AWS profile" "terraform"
$Region     = Ask "AWS region" "us-east-1"
$Project    = Ask "Project prefix" "finsir"
$env:AWS_PROFILE = $AwsProfile

try { $AccountId = (aws sts get-caller-identity --query Account --output text).Trim() } catch { $AccountId = "" }
if ($AccountId) { Write-Host "Account $AccountId (profile $AwsProfile)." }

$DeleteS3    = AskYesNo "Delete the S3 data lake (all its objects are lost)?" "n"
$DeleteImage = AskYesNo "Delete the ECR image after destroying the API?" "n"
if ($DeleteImage -eq "true") {
  $EcrRepo  = Ask "ECR repository name" "$Project-api"
  $ImageTag = Ask "Image tag to delete (empty = delete the whole repository)" ""
}

# --- 1) API (ECS Fargate) --------------------------------------------------
# The auth secret is required by a variable validation even for destroy, so
# pass a dummy value through the environment.
if (Test-Path $ApiTf) {
  Write-Host "-- Destroying the API (ECS Fargate) --"
  terraform -chdir="$ApiTf" init -input=false
  $env:TF_VAR_auth_dev_secret = "xxxxxxxxxxxxxxxx"
  try { terraform -chdir="$ApiTf" destroy -auto-approve }
  finally { Remove-Item Env:\TF_VAR_auth_dev_secret -ErrorAction SilentlyContinue }
} else {
  Write-Host "Skipping API: $ApiTf not found."
}

# ECR repo is not managed by Terraform, so delete the image/repo by hand.
if ($DeleteImage -eq "true") {
  if ($ImageTag) {
    Write-Host "-- Deleting image ${EcrRepo}:${ImageTag} --"
    aws ecr batch-delete-image --repository-name $EcrRepo --region $Region --image-ids "imageTag=$ImageTag"
  } else {
    Write-Host "-- Deleting ECR repository $EcrRepo (with all images) --"
    aws ecr delete-repository --repository-name $EcrRepo --region $Region --force
  }
}

# --- 2) Data platform (S3 + Glue + Athena) ---------------------------------
if (Test-Path $DataTf) {
  Write-Host "-- Destroying the data platform --"
  terraform -chdir="$DataTf" init -input=false

  # Resolve the bucket name: output first, then tfvars, then the derived default.
  $Bucket = TfOutput $DataTf "bucket"
  if (-not $Bucket) {
    $tfvars = Join-Path $DataTf "terraform.tfvars"
    if (Test-Path $tfvars) {
      $m = Select-String -Path $tfvars -Pattern '^\s*bucket_name\s*=\s*"([^"]*)"' | Select-Object -First 1
      if ($m) { $Bucket = $m.Matches[0].Groups[1].Value }
    }
  }
  if (-not $Bucket -and $AccountId) { $Bucket = "$Project-$AccountId" }

  if ($DeleteS3 -eq "true") {
    $exists = $false
    if ($Bucket) { aws s3api head-bucket --bucket $Bucket 2>$null; $exists = ($LASTEXITCODE -eq 0) }
    if ($exists) {
      Write-Host "Emptying bucket $Bucket (objects + versions) before destroy..."
      aws s3 rm "s3://$Bucket" --recursive
      # Delete any versions / delete markers so a versioned bucket can be removed.
      foreach ($q in @(
        '{Objects: Versions[].{Key:Key,VersionId:VersionId}}',
        '{Objects: DeleteMarkers[].{Key:Key,VersionId:VersionId}}')) {
        $batch = aws s3api list-object-versions --bucket $Bucket --query $q --output json 2>$null
        if ($batch -and $batch -ne '{"Objects":null}') {
          $tmp = New-TemporaryFile
          Set-Content -Path $tmp -Value $batch -Encoding ascii
          aws s3api delete-objects --bucket $Bucket --delete "file://$tmp" 2>$null | Out-Null
          Remove-Item $tmp -ErrorAction SilentlyContinue
        }
      }
    }
    # force_destroy may be false in state; force it so destroy can remove the bucket.
    terraform -chdir="$DataTf" destroy -auto-approve -var="force_destroy_bucket=true"
  } else {
    Write-Host "Keeping the S3 bucket. Removing it from Terraform state so destroy leaves it alone..."
    foreach ($addr in @(
      'aws_s3_bucket.lake[0]',
      'aws_s3_bucket_public_access_block.lake[0]',
      'aws_s3_bucket_server_side_encryption_configuration.lake[0]')) {
      terraform -chdir="$DataTf" state rm $addr 2>$null | Out-Null
    }
    terraform -chdir="$DataTf" destroy -auto-approve
  }
} else {
  Write-Host "Skipping data platform: $DataTf not found."
}

Write-Host "Teardown complete."
if ($DeleteS3 -eq "false")    { Write-Host "Note: the S3 bucket $Bucket was kept." }
if ($DeleteImage -eq "false") { Write-Host "Note: the ECR image was kept." }
