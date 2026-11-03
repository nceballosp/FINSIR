#!/usr/bin/env bash
# Interactive deploy for the FINSIR API on ECS Fargate.
# Prompts for the values a new user would otherwise set by hand (account id,
# profile, region, auth secret), optionally builds and pushes the image to ECR,
# writes terraform.tfvars, and runs terraform init/apply in terraform-ecs/.
set -euo pipefail

API_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TF_DIR="$API_DIR/terraform-ecs"

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

ask_secret() {
  local __var="$1" __prompt="$2" __reply
  read -r -s -p "$__prompt: " __reply; echo
  printf -v "$__var" '%s' "$__reply"
}

ask_yes_no() {
  local __var="$1" __prompt="$2" __default="${3:-n}" __reply
  read -r -p "$__prompt [$([[ $__default == y ]] && echo Y/n || echo y/N)]: " __reply
  __reply="${__reply:-$__default}"
  [[ "$__reply" =~ ^[Yy] ]] && printf -v "$__var" '%s' "true" || printf -v "$__var" '%s' "false"
}

echo "== FINSIR API (ECS Fargate) deploy =="

ask AWS_PROFILE "AWS profile" "terraform"
ask REGION      "AWS region"  "us-east-1"
ask PROJECT     "Project prefix" "finsir"
export AWS_PROFILE

# Resolve account id for the ECR URL; let the user override it.
ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text 2>/dev/null || true)"
ask ACCOUNT_ID "AWS account id" "$ACCOUNT_ID"
while [[ ! "$ACCOUNT_ID" =~ ^[0-9]{12}$ ]]; do
  echo "Account id must be 12 digits."
  ask ACCOUNT_ID "AWS account id" ""
done

ask ECR_REPO  "ECR repository name" "${PROJECT}-api"
ask IMAGE_TAG "Image tag" "latest"
ECR_URL="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com/${ECR_REPO}"

# Auth secret for dev-mode HS256 (>= 16 chars). Never written to a committed file.
while :; do
  ask_secret AUTH_DEV_SECRET "Auth dev secret (>= 16 chars, hidden)"
  [[ ${#AUTH_DEV_SECRET} -ge 16 ]] && break
  echo "Secret must be at least 16 characters."
done
ask AUTH_SCOPE  "Required auth scope" "gold:read"
ask ATHENA_DB   "Athena database"     "$PROJECT"
ask ATHENA_WG   "Athena workgroup"    "$PROJECT"
ask ATHENA_TBL  "Athena table"        "gold_train"
ask SERVICE_ENV "Service environment (local|dev|uat|prod)" "dev"

# Optional: build and push the image to ECR before applying.
ask_yes_no DO_BUILD "Build and push the Docker image to ECR now?" "n"
if [[ "$DO_BUILD" == "true" ]]; then
  if ! aws ecr describe-repositories --repository-names "$ECR_REPO" --region "$REGION" >/dev/null 2>&1; then
    echo "Creating ECR repository $ECR_REPO..."
    aws ecr create-repository --repository-name "$ECR_REPO" --region "$REGION" >/dev/null
  fi
  aws ecr get-login-password --region "$REGION" \
    | docker login --username AWS --password-stdin "${ECR_URL%/*}"
  docker build -t "${ECR_URL}:${IMAGE_TAG}" "$API_DIR"
  docker push "${ECR_URL}:${IMAGE_TAG}"
fi

cat > "$TF_DIR/terraform.tfvars" <<EOF
region              = "${REGION}"
project             = "${PROJECT}"
ecr_repository_name = "${ECR_REPO}"
image_tag           = "${IMAGE_TAG}"
athena_database     = "${ATHENA_DB}"
athena_workgroup    = "${ATHENA_WG}"
athena_table        = "${ATHENA_TBL}"
auth_required_scope = "${AUTH_SCOPE}"
service_environment = "${SERVICE_ENV}"
EOF
echo "Wrote $TF_DIR/terraform.tfvars (secret passed via TF_VAR, not written to disk)"

cd "$TF_DIR"
terraform init
# Secret goes through the environment so it never lands in a committed file.
TF_VAR_auth_dev_secret="$AUTH_DEV_SECRET" terraform apply

# Resolve the task's public IP (there is no ALB; the IP changes on every redeploy).
# The Fargate task takes a moment to start, so poll for the task and its IP.
echo "Resolving the public IP (waiting for the Fargate task to start)..."
CLUSTER="$(terraform output -raw cluster_name)"
SERVICE="$(terraform output -raw service_name)"
PUBLIC_IP=""
for _ in $(seq 1 30); do
  TASK="$(aws ecs list-tasks --cluster "$CLUSTER" --service-name "$SERVICE" \
    --desired-status RUNNING --region "$REGION" --query 'taskArns[0]' --output text 2>/dev/null || true)"
  if [[ -n "$TASK" && "$TASK" != "None" ]]; then
    ENI="$(aws ecs describe-tasks --cluster "$CLUSTER" --tasks "$TASK" --region "$REGION" \
      --query 'tasks[0].attachments[0].details[?name==`networkInterfaceId`].value | [0]' --output text 2>/dev/null || true)"
    if [[ -n "$ENI" && "$ENI" != "None" ]]; then
      PUBLIC_IP="$(aws ec2 describe-network-interfaces --network-interface-ids "$ENI" --region "$REGION" \
        --query 'NetworkInterfaces[0].Association.PublicIp' --output text 2>/dev/null || true)"
      [[ -n "$PUBLIC_IP" && "$PUBLIC_IP" != "None" ]] && break
    fi
  fi
  sleep 10
done

echo
echo "================ FINSIR API deployed ================"
if [[ -n "$PUBLIC_IP" && "$PUBLIC_IP" != "None" ]]; then
  echo "Public URL : http://${PUBLIC_IP}:${SERVICE_PORT:-8080}"
  echo "Health     : http://${PUBLIC_IP}:${SERVICE_PORT:-8080}/health"
else
  echo "Public URL : task not RUNNING yet; re-run the IP lookup in terraform-ecs/README.md shortly."
fi
echo "Auth secret: ${AUTH_DEV_SECRET}"
echo "Auth scope : ${AUTH_SCOPE}"
echo "====================================================="
echo "Mint a dev token with this secret (see terraform-ecs/README.md 'Call the API')."
