#!/usr/bin/env bash
# Interactive deploy for the FINSIR data platform (S3 + Glue + Athena).
# Prompts for the values a new user would otherwise set by hand, writes
# terraform.tfvars, runs terraform init/apply, and optionally uploads the raw
# CSV and starts the Glue jobs.
set -euo pipefail

TF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/terraform" && pwd)"
cd "$TF_DIR"

# ask <var> <prompt> <default>
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

echo "== FINSIR data platform deploy =="

ask AWS_PROFILE "AWS profile" "terraform"
ask REGION      "AWS region"  "us-east-1"
ask PROJECT     "Project prefix" "finsir"

# Resolve the account id from the chosen profile (used to show the derived bucket name).
ACCOUNT_ID="$(AWS_PROFILE="$AWS_PROFILE" aws sts get-caller-identity --query Account --output text 2>/dev/null || true)"
if [[ -n "$ACCOUNT_ID" ]]; then
  echo "Using account $ACCOUNT_ID (profile $AWS_PROFILE)."
  DEFAULT_BUCKET="${PROJECT}-${ACCOUNT_ID}"
else
  echo "Warning: could not resolve account id from profile '$AWS_PROFILE'. Continuing."
  DEFAULT_BUCKET=""
fi

ask_yes_no CREATE_BUCKET "Create a new S3 bucket?" "y"
if [[ "$CREATE_BUCKET" == "true" ]]; then
  ask BUCKET_NAME "Bucket name (empty = ${DEFAULT_BUCKET:-<project>-<account-id>})" ""
else
  ask BUCKET_NAME "Existing bucket name" ""
  while [[ -z "$BUCKET_NAME" ]]; do
    echo "A bucket name is required when not creating one."
    ask BUCKET_NAME "Existing bucket name" ""
  done
fi

# EventBridge schedule: off by default (the Step Functions still runs on demand).
ask_yes_no SCHEDULE_ENABLED "Enable the EventBridge daily schedule now? (no = keep it off, run by hand)" "n"

cat > terraform.tfvars <<EOF
region           = "${REGION}"
project          = "${PROJECT}"
create_bucket    = ${CREATE_BUCKET}
bucket_name      = "${BUCKET_NAME}"
schedule_enabled = ${SCHEDULE_ENABLED}
EOF
echo "Wrote $TF_DIR/terraform.tfvars"

export AWS_PROFILE
terraform init
terraform apply

BUCKET="$(terraform output -raw bucket)"
echo "Bucket: $BUCKET"

# Optional: upload the raw CSV (~2.3 GB) and start the Glue jobs.
DEFAULT_CSV="$(cd "$TF_DIR/../../.." && pwd)/data/train_ver2.csv"
ask_yes_no DO_UPLOAD "Upload the raw CSV now?" "n"
if [[ "$DO_UPLOAD" == "true" ]]; then
  ask CSV_PATH "Path to train_ver2.csv" "$DEFAULT_CSV"
  if [[ -f "$CSV_PATH" ]]; then
    aws s3 cp "$CSV_PATH" "s3://$BUCKET/raw/train/train_ver2.csv" --region "$REGION"
  else
    echo "File not found: $CSV_PATH (skipping upload)."
  fi
fi

# Run the whole batch via Step Functions: cleaning -> gold tables in parallel.
# run_batch is the ready-made "aws stepfunctions start-execution ..." command;
# it always carries the current gold jobs, so just run it.
RUN_BATCH="$(terraform output -raw run_batch 2>/dev/null || true)"
ask_yes_no DO_BATCH "Start the batch now (Step Functions: cleaning -> gold tables)?" "n"
if [[ "$DO_BATCH" == "true" ]]; then
  if [[ -n "$RUN_BATCH" ]]; then
    EXEC_ARN="$(eval "$RUN_BATCH --query executionArn --output text")"
    echo "Batch started: $EXEC_ARN"
    echo "Follow it with:"
    echo "  aws stepfunctions describe-execution --execution-arn $EXEC_ARN --region $REGION --query status"
  else
    echo "No orchestration found (create_orchestration is false?). Skipping."
  fi
fi

# Show how to run the batch again and the schedule state.
echo
echo "================ FINSIR batch orchestration ================"
if [[ "$SCHEDULE_ENABLED" == "true" ]]; then
  echo "EventBridge schedule: ENABLED (cron default: 06:00 UTC daily)."
else
  echo "EventBridge schedule: DISABLED. Run the batch by hand with the command below."
fi
if [[ -n "$RUN_BATCH" ]]; then
  echo "Run the batch (cleaning -> gold tables in parallel):"
  echo "  $RUN_BATCH"
fi
echo "Enable/disable the schedule: set schedule_enabled in terraform.tfvars and re-apply."
echo "============================================================"

echo "Done."
