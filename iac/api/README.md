# FINSIR API (gold service)

FastAPI service that serves the FINSIR gold training table. It queries Athena
(`gold_train`) and reads table info from the Glue catalog. It runs on AWS ECS
Fargate at `http://<task-ip>:8080` (plain HTTP, no load balancer). A bearer JWT is
checked inside FastAPI — there's no API Gateway. The silver endpoints were
removed; the columns are documented in
[`../data-platform/README.md`](../data-platform/README.md#gold-layer-gold_train).

## How the code is organized (hexagonal)

Dependencies point inward: `adapters -> use cases -> domain`.

```
app/
  domain/            Entities + typed errors. No framework imports.
  use_cases/         GoldTrainRepository port + the two use cases.
  adapters/
    driving/http/    FastAPI app, routers, auth, logging, error handling.
    driven/athena/   Athena-backed repository (boto3), validation, error mapping.
  config.py          Settings from env vars.
  container.py       Wires the Athena adapter into the use cases.
  main.py            Entry point (uvicorn app.main:app).
```

All boto3/Athena code lives behind the `GoldTrainRepository` port, so tests use
a fake repository and make no AWS calls.

## Endpoints

| Method | Path                                 | Auth | What it returns                                |
| ------ | ------------------------------------ | ---- | ---------------------------------------------- |
| GET    | `/health`                            | no   | Health check (used by ECS)                     |
| GET    | `/v1/gold/train/clients/{ncodpers}`  | yes  | A client's `gold_train` rows, ordered by month |
| GET    | `/v1/gold/train/months/{fecha_dato}` | yes  | `gold_train` rows for a month (paginated)      |

Month listing params: `page` (>= 1), `size` (1..200), `sort` (a `gold_train`
column). Each row comes back as `ncodpers`, `fecha_dato` and an `attributes`
object with the other 167 columns (values as strings, nulls kept). Columns that
start with `label_next_` are the model answers, not features; `added_<product>`
flags are features (the product was added this month).

Success responses wrap data in `data`; errors use `{error.code, error.message,
correlationId}` and never leak internals.

```bash
TOKEN="<bearer-jwt>"
BASE="http://<task-ip>:8080"
curl -H "Authorization: Bearer $TOKEN" "$BASE/v1/gold/train/clients/1375586"
curl -H "Authorization: Bearer $TOKEN" "$BASE/v1/gold/train/months/2016-04-28?page=1&size=50"
```

## Auth

Every `/v1` route needs a bearer JWT (`/health` is open). Nothing is hardcoded —
it all comes from env vars.

- **Dev**: `IS_AUTH_DEV_MODE=true` + `AUTH_DEV_SECRET` → checks HS256 tokens. This
  is what the ECS deploy uses.
- **Prod**: RS256 with keys from `AUTH_JWKS_URL`, checking `AUTH_AUDIENCE` and
  `AUTH_ISSUER`.

Missing/bad token → 401; wrong scope → 403. The token is never logged.

## Environment variables

| Variable                                                   | Needed | Purpose                           |
| ---------------------------------------------------------- | ------ | --------------------------------- |
| `ATHENA_DATABASE`                                          | yes    | Glue database (e.g. `finsir`)     |
| `ATHENA_WORKGROUP`                                         | yes    | Athena workgroup                  |
| `ATHENA_OUTPUT`                                            | yes    | S3 URI for Athena results         |
| `ATHENA_TABLE`                                             | no     | Gold table (default `gold_train`) |
| `AWS_REGION`                                               | no     | Region (default `us-east-1`)      |
| `AUTH_ISSUER` / `AUTH_AUDIENCE` / `AUTH_JWKS_URL`          | prod   | RS256 token checks                |
| `AUTH_REQUIRED_SCOPE`                                      | no     | Scope needed for data routes      |
| `IS_AUTH_DEV_MODE`                                         | no     | `true` turns on HS256 dev mode    |
| `AUTH_DEV_SECRET`                                          | dev    | HS256 secret (dev mode)           |
| `SERVICE_NAME` / `SERVICE_VERSION` / `SERVICE_ENVIRONMENT` | no     | Log metadata                      |

Dev mode needs `AUTH_DEV_SECRET`; prod needs the JWKS/audience/issuer. The app
fails fast if a required value is missing.

## Run locally

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
export ATHENA_DATABASE=finsir ATHENA_WORKGROUP=finsir
export ATHENA_OUTPUT=s3://finsir-<account-id>/athena-results/
export IS_AUTH_DEV_MODE=true AUTH_DEV_SECRET=dev-secret AUTH_REQUIRED_SCOPE=gold:read
uvicorn app.main:app --host 0.0.0.0 --port 8080   # needs AWS creds for the data routes
```

## Tests

```bash
pip install -r requirements.txt -r requirements-dev.txt
pytest --cov=app --cov-report=term-missing
```

Coverage floors: domain > 90%, use cases >= 85%, adapters >= 70%, global >= 80%.
Tests use a fake repository and fake boto3 — no real AWS.

## Build and push the image

The ECS task pulls from the `finsir-api` ECR repo, so build and push first:

```bash
ECR_URL="663505294799.dkr.ecr.us-east-1.amazonaws.com/finsir-api"   # use your account's URL
aws --profile terraform ecr get-login-password --region us-east-1 \
  | docker login --username AWS --password-stdin "${ECR_URL%/*}"
docker build -t "$ECR_URL:latest" .    # run from iac/api
docker push "$ECR_URL:latest"
```

If the repo doesn't exist:
`aws --profile terraform ecr create-repository --repository-name finsir-api --region us-east-1`.
Keep `ECR_URL` set in the same shell and quote `:latest`. After a later push,
re-run `terraform apply` in `terraform-ecs/` so the service pulls the new image.

## Deploy

The API is deployed by the Terraform in `terraform-ecs/` (ECS cluster, Fargate
task + service on port 8080, task/execution roles, security group, log group). It
reuses the existing ECR repo and reads the data platform's bucket/database/
workgroup from variables.

```bash
cd terraform-ecs
cp terraform.tfvars.example terraform.tfvars   # set auth_dev_secret (>= 16 chars)
AWS_PROFILE=terraform terraform init
AWS_PROFILE=terraform terraform apply
```

See [`terraform-ecs/README.md`](terraform-ecs/README.md) for finding the public
IP, making a token, and tearing it down.

> The old App Runner Terraform root was removed (App Runner isn't available on
> this account). It left two unused, free IAM roles (`finsir-api-instance-role`,
> `finsir-api-access-role`) — delete them by hand if you want.
