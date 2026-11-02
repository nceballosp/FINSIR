# FINSIR API on ECS Fargate

A self-contained Terraform root that runs the existing FINSIR API container
(already in ECR) on ECS Fargate with a public IP and no load balancer. This is a
sibling of the App Runner root (`iac/api/terraform/`); both roots coexist and use
separate state and distinct resource names.

## 1. What this provisions

- **ECS cluster** `finsir-api-cluster`.
- **Fargate task definition** `finsir-api` — one container from the existing ECR
  image (port 8080, `awslogs` log driver).
- **ECS service** `finsir-api` — `desired_count = 1`, public IP, no ALB.
- **Execution role** `finsir-api-exec-role` with the AWS-managed
  `AmazonECSTaskExecutionRolePolicy` (ECR pull + log write).
- **Task role** `finsir-api-task-role` with a least-privilege Athena/Glue/S3
  inline policy (replicated from the App Runner root).
- **Security group** `finsir-api-sg` — inbound TCP 8080 from `0.0.0.0/0`, all egress.
- **CloudWatch log group** `/ecs/finsir-api`.

It **reuses the existing ECR repository** (`finsir-api`) and does not create one.
It does not touch the App Runner root or the data-platform root.

The ECS service is named `finsir-api` (not `finsir-service`); `finsir-service` is
carried only in the `SERVICE_NAME` env var.

## 2. Deploy

```bash
cd iac/api/terraform-ecs
cp terraform.tfvars.example terraform.tfvars   # edit non-secret values
export TF_VAR_auth_dev_secret="$(openssl rand -hex 24)"   # strong dev secret, not committed
AWS_PROFILE=terraform terraform init
AWS_PROFILE=terraform terraform apply
```

## 3. Find the public IP

There is no stable endpoint (no ALB); the public IP changes on every redeploy.

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

`terraform output -raw public_ip_hint` reminds you to use this pipeline (the
pipeline itself lives only here, to avoid drift).

## 4. Reach the API

`/health` is open; `/v1/*` needs an HS256 bearer token.

```bash
IP=<public-ip-from-above>
curl "http://$IP:8080/health"

# Mint a dev HS256 token (secret must equal auth_dev_secret; scope must include silver:read)
python - <<'PY'
import jwt, time
secret = "<the same auth_dev_secret>"
print(jwt.encode({"sub":"demo","scope":"silver:read",
                  "iat":int(time.time()),"exp":int(time.time())+3600},
                 secret, algorithm="HS256"))
PY
TOKEN=<token>
curl -H "Authorization: Bearer $TOKEN" "http://$IP:8080/v1/clients/1"
```

Access is over **HTTP on port 8080** (no ALB/TLS).

> Why no `aud`/`iss` in the token: this deploy runs dev mode with
> `AUTH_AUDIENCE`/`AUTH_ISSUER` intentionally unset, so the API skips
> audience/issuer verification and a token with only `sub`/`scope`/`iat`/`exp`
> is accepted. If you later set `AUTH_AUDIENCE` or `AUTH_ISSUER`, this same
> token will return 401 until it also carries matching `aud`/`iss` claims.

## 5. Caveats

Demo-grade: the SG opens `0.0.0.0/0:8080`, traffic is plaintext HTTP, and the
public IP changes whenever the task is replaced. Hardening path (out of scope):
front with an ALB for stable DNS + HTTPS, restrict the SG, and move
`AUTH_DEV_SECRET` into Secrets Manager via the container `secrets` block,
switching to production RS256/JWKS.
