# FINSIR API on ECS Fargate

Terraform that runs the FINSIR API container (already in ECR) on ECS Fargate with
a public IP and no load balancer.

## What it creates

- ECS cluster `finsir-api-cluster`
- Fargate task `finsir-api` — the ECR image on port 8080, logs to CloudWatch
- ECS service `finsir-api` — 1 task, public IP, no ALB
- Execution role (lets ECS pull the image + write logs)
- Task role (lets the app read Athena/Glue/S3, least privilege)
- Security group — open on TCP 8080 to everyone
- Log group `/ecs/finsir-api`

It reuses the existing `finsir-api` ECR repo (doesn't create one).

## Deploy

```bash
cd iac/api/terraform-ecs
cp terraform.tfvars.example terraform.tfvars   # set auth_dev_secret (>= 16 chars)
AWS_PROFILE=terraform terraform init
AWS_PROFILE=terraform terraform apply
```

## Find the public IP

There's no fixed URL (no ALB); the IP changes on every redeploy.

```bash
CLUSTER=$(terraform output -raw cluster_name)
SERVICE=$(terraform output -raw service_name)
TASK=$(aws ecs list-tasks --cluster "$CLUSTER" --service-name "$SERVICE" \
  --query 'taskArns[0]' --output text)
ENI=$(aws ecs describe-tasks --cluster "$CLUSTER" --tasks "$TASK" \
  --query 'tasks[0].attachments[0].details[?name==`networkInterfaceId`].value | [0]' --output text)
aws ec2 describe-network-interfaces --network-interface-ids "$ENI" \
  --query 'NetworkInterfaces[0].Association.PublicIp' --output text
```

## Call the API

`/health` is open; `/v1/*` needs a token signed with your `auth_dev_secret` and a
`silver:read` scope.

```bash
IP=<public-ip-from-above>
curl "http://$IP:8080/health"

# Make a dev token (same secret as auth_dev_secret)
python - <<'PY'
import jwt, time
secret = "<your auth_dev_secret>"
print(jwt.encode({"sub":"demo","scope":"silver:read",
                  "exp":int(time.time())+3600}, secret, algorithm="HS256"))
PY
TOKEN=<token>
curl -H "Authorization: Bearer $TOKEN" "http://$IP:8080/v1/clients/1"
```

Traffic is plain HTTP on port 8080 (no TLS). The token needs no `aud`/`iss`
because this deploy leaves `AUTH_AUDIENCE`/`AUTH_ISSUER` unset; if you set either,
tokens must include matching claims or they get a 401.

## Tear down

```bash
AWS_PROFILE=terraform terraform destroy
```

Stops the Fargate task and removes everything above. The ECR repo survives (it's
not managed here). For the full platform teardown (data included) see the
repo-root README, "Tear down".

## Heads up

This is demo-grade: port 8080 is open to the world and traffic is plain HTTP. To
harden it: put an ALB in front for a stable HTTPS URL, lock the security group
down, and move the secret into Secrets Manager with production RS256 auth.
