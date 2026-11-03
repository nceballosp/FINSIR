#!/usr/bin/env bash
# Interactive teardown for the FINSIR infra (API on ECS + data platform).
# Destroys the API first (it reads the data platform), then the data platform.
# Asks whether to delete the S3 data lake (emptied first, since terraform
# destroy refuses a non-empty bucket) and whether to delete the ECR image.
set -euo pipefail

IAC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
API_TF="$IAC_DIR/api/terraform-ecs"
DATA_TF="$IAC_DIR/data-platform/terraform"

ask() {
  local __var="$1" __prompt="$2" __default="${3:-}" __reply
  if [[ -n "$__default" ]]; then
    read -r -p "$__prompt [$__default]: " __reply
    __reply="${__reply:-$__default}"
  else
    read -r -p "$__prompt: " __reply
  fi
  printf -v "$__var" '%s' "$__reply"
}

ask_yes_no() {
  local __var="$1" __prompt="$2" __default="${3:-n}" __reply
  read -r -p "$__prompt [$([[ $__default == y ]] && echo Y/n || echo y/N)]: " __reply
  __reply="${__reply:-$__default}"
  [[ "$__reply" =~ ^[Yy] ]] && printf -v "$__var" '%s' "true" || printf -v "$__var" '%s' "false"
}

# tf_output <dir> <name> -> value or empty (never aborts the script)
tf_output() {
  terraform -chdir="$1" output -raw "$2" 2>/dev/null || true
}

echo "== FINSIR infra teardown =="

ask AWS_PROFILE "AWS profile" "terraform"
ask REGION      "AWS region"  "us-east-1"
ask PROJECT     "Project prefix" "finsir"
export AWS_PROFILE

ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text 2>/dev/null || true)"
[[ -n "$ACCOUNT_ID" ]] && echo "Account $ACCOUNT_ID (profile $AWS_PROFILE)."

ask_yes_no DELETE_S3    "Delete the S3 data lake (all its objects are lost)?" "n"
ask_yes_no DELETE_IMAGE "Delete the ECR image after destroying the API?" "n"
if [[ "$DELETE_IMAGE" == "true" ]]; then
  ask ECR_REPO  "ECR repository name" "${PROJECT}-api"
  ask IMAGE_TAG "Image tag to delete (empty = delete the whole repository)" ""
fi

# ---------------------------------------------------------------------------
# 1) API (ECS Fargate). The auth secret is required by a variable validation
#    even for destroy, so pass a dummy value through the environment.
# ---------------------------------------------------------------------------
if [[ -d "$API_TF" ]]; then
  echo "-- Destroying the API (ECS Fargate) --"
  terraform -chdir="$API_TF" init -input=false
  TF_VAR_auth_dev_secret="xxxxxxxxxxxxxxxx" \
    terraform -chdir="$API_TF" destroy -auto-approve
else
  echo "Skipping API: $API_TF not found."
fi

# ECR repo is not managed by Terraform, so delete the image/repo by hand.
if [[ "$DELETE_IMAGE" == "true" ]]; then
  if [[ -n "$IMAGE_TAG" ]]; then
    echo "-- Deleting image ${ECR_REPO}:${IMAGE_TAG} --"
    aws ecr batch-delete-image --repository-name "$ECR_REPO" --region "$REGION" \
      --image-ids "imageTag=$IMAGE_TAG" || echo "Image not found (skipping)."
  else
    echo "-- Deleting ECR repository ${ECR_REPO} (with all images) --"
    aws ecr delete-repository --repository-name "$ECR_REPO" --region "$REGION" --force \
      || echo "Repository not found (skipping)."
  fi
fi

# ---------------------------------------------------------------------------
# 2) Data platform (S3 + Glue + Athena).
# ---------------------------------------------------------------------------
if [[ -d "$DATA_TF" ]]; then
  echo "-- Destroying the data platform --"
  terraform -chdir="$DATA_TF" init -input=false

  # Resolve the bucket name: output first, then tfvars, then the derived default.
  BUCKET="$(tf_output "$DATA_TF" bucket)"
  if [[ -z "$BUCKET" ]]; then
    BUCKET="$(awk -F'"' '/^[[:space:]]*bucket_name/ {print $2}' "$DATA_TF/terraform.tfvars" 2>/dev/null || true)"
  fi
  if [[ -z "$BUCKET" && -n "$ACCOUNT_ID" ]]; then
    BUCKET="${PROJECT}-${ACCOUNT_ID}"
  fi

  if [[ "$DELETE_S3" == "true" ]]; then
    if [[ -n "$BUCKET" ]] && aws s3api head-bucket --bucket "$BUCKET" >/dev/null 2>&1; then
      echo "Emptying bucket $BUCKET (objects + versions) before destroy..."
      # Delete current objects.
      aws s3 rm "s3://$BUCKET" --recursive || true
      # Delete any versions / delete markers so a versioned bucket can be removed.
      versions="$(aws s3api list-object-versions --bucket "$BUCKET" \
        --query '{Objects: Versions[].{Key:Key,VersionId:VersionId}}' --output json 2>/dev/null || echo '{"Objects":null}')"
      if [[ "$versions" != '{"Objects":null}' ]]; then
        aws s3api delete-objects --bucket "$BUCKET" --delete "$versions" >/dev/null 2>&1 || true
      fi
      markers="$(aws s3api list-object-versions --bucket "$BUCKET" \
        --query '{Objects: DeleteMarkers[].{Key:Key,VersionId:VersionId}}' --output json 2>/dev/null || echo '{"Objects":null}')"
      if [[ "$markers" != '{"Objects":null}' ]]; then
        aws s3api delete-objects --bucket "$BUCKET" --delete "$markers" >/dev/null 2>&1 || true
      fi
    fi
    # force_destroy may be false in state; force it so destroy can remove the bucket.
    terraform -chdir="$DATA_TF" destroy -auto-approve -var="force_destroy_bucket=true"
  else
    echo "Keeping the S3 bucket. Removing it from Terraform state so destroy leaves it alone..."
    # Drop the bucket and its config from state so destroy won't touch it.
    for addr in \
      'aws_s3_bucket.lake[0]' \
      'aws_s3_bucket_public_access_block.lake[0]' \
      'aws_s3_bucket_server_side_encryption_configuration.lake[0]'; do
      terraform -chdir="$DATA_TF" state rm "$addr" >/dev/null 2>&1 || true
    done
    terraform -chdir="$DATA_TF" destroy -auto-approve
  fi
else
  echo "Skipping data platform: $DATA_TF not found."
fi

echo "Teardown complete."
[[ "$DELETE_S3" == "false" ]] && echo "Note: the S3 bucket $BUCKET was kept."
[[ "$DELETE_IMAGE" == "false" ]] && echo "Note: the ECR image was kept."
exit 0
