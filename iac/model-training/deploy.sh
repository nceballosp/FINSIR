#!/usr/bin/env bash
# Applies model-training Terraform and starts the training Step Function.
# Configure create_instance=true in terraform.tfvars before running this script.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TF_DIR="$SCRIPT_DIR/terraform"
TFVARS_PATH="$TF_DIR/terraform.tfvars"

if [[ ! -f "$TFVARS_PATH" ]]; then
  echo "Missing $TFVARS_PATH. Copy terraform.tfvars.example, set create_instance=true, and configure the model bucket first." >&2
  exit 1
fi

if ! grep -Eq '^[[:space:]]*create_instance[[:space:]]*=[[:space:]]*true([[:space:]]*(#.*)?)?$' "$TFVARS_PATH"; then
  echo "Set create_instance = true in $TFVARS_PATH before deploying and starting model training." >&2
  exit 1
fi

read -r -p 'AWS profile [terraform]: ' AWS_PROFILE
AWS_PROFILE="${AWS_PROFILE:-terraform}"
read -r -p 'AWS region [us-east-1]: ' REGION
REGION="${REGION:-us-east-1}"
export AWS_PROFILE TF_VAR_region="$REGION"

if ! aws sts get-caller-identity --region "$REGION" --output text >/dev/null; then
  echo "AWS credentials are unavailable for profile '$AWS_PROFILE'." >&2
  exit 1
fi

echo "Applying model-training Terraform in $REGION..."
terraform -chdir="$TF_DIR" init -input=false

PLAN_FILE="$(mktemp "${TMPDIR:-/tmp}/finsir-training-XXXXXX.tfplan")"
cleanup() { rm -f -- "$PLAN_FILE"; }
trap cleanup EXIT

terraform -chdir="$TF_DIR" plan "-out=$PLAN_FILE"
terraform -chdir="$TF_DIR" apply "$PLAN_FILE" || {
  echo 'terraform apply failed; training was not started.' >&2
  exit 1
}

STATE_MACHINE_ARN="$(terraform -chdir="$TF_DIR" output -raw training_state_machine_arn)"
if [[ -z "$STATE_MACHINE_ARN" ]]; then
  echo 'Training Step Function was not created. Check create_instance=true and review terraform output.' >&2
  exit 1
fi

EXECUTION_ARN="$(aws stepfunctions start-execution \
  --state-machine-arn "$STATE_MACHINE_ARN" \
  --input '{}' \
  --region "$REGION" \
  --query executionArn \
  --output text)"

echo "Model training started: $EXECUTION_ARN"
echo "State machine: $STATE_MACHINE_ARN"
echo 'Monitor the execution in AWS Step Functions or use:'
echo "  aws stepfunctions describe-execution --execution-arn $EXECUTION_ARN --region $REGION --query status --output text"
