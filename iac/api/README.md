# FINSIR API (silver service)

FastAPI service that exposes the FINSIR **silver** data over HTTPS, querying
Athena (`silver_train`) and reading table metadata from the Glue Data Catalog.
It is deployed on **AWS App Runner** ("Finsir Service" in the architecture
diagram). The Streamlit client calls it over HTTPS. Authentication is validated
**inside FastAPI** with a bearer JWT — there is **no API Gateway**.

Gold endpoints are future work; this service serves the silver layer only.

## Architecture (hexagonal / ports & adapters)

Dependencies point inward: `adapters -> use cases -> domain`.

```
app/
  domain/            Pure entities (ClientRecord, MonthPage) + typed errors. No framework imports.
  use_cases/         SilverRepository port + the three use cases.
  adapters/
    driving/http/    FastAPI app factory, routers, auth, correlation, JSON logging, exception handler.
    driven/athena/   Athena-backed SilverRepository (boto3), input validation, error translation.
  config.py          pydantic-settings (env vars).
  container.py       DI wiring (Athena adapter -> use cases).
  main.py            ASGI entrypoint (uvicorn app.main:app).
```

The boto3/Athena details live only in the driven adapter, behind the
`SilverRepository` port, so tests swap in a fake repository with no AWS calls.

## Endpoints

| Method | Path | Auth | Description | Status codes |
| --- | --- | --- | --- | --- |
| GET | `/health` | no | Liveness probe for App Runner | 200 |
| GET | `/v1/clients/{ncodpers}` | yes | A client's silver records | 200, 401, 403, 404, 422, 500 |
| GET | `/v1/clients/{ncodpers}/latest` | yes | The client's most recent record | 200, 401, 403, 404, 422, 500 |
| GET | `/v1/months/{fecha_dato}/clients` | yes | Paginated clients for a month | 200, 401, 403, 422, 500 |

Query params for the month listing: `page` (>= 1), `size` (1..200), `sort`
(whitelisted silver column). Successful payloads are wrapped in `data`; errors
use a stable envelope (`error.code`, `error.message`, `correlationId`) and never
leak internal details or stack traces.

### Examples

```bash
TOKEN="<bearer-jwt>"
curl -H "Authorization: Bearer $TOKEN" https://<service-url>/v1/clients/1
curl -H "Authorization: Bearer $TOKEN" https://<service-url>/v1/clients/1/latest
curl -H "Authorization: Bearer $TOKEN" \
  "https://<service-url>/v1/months/2015-01-28/clients?page=1&size=50&sort=ncodpers"
```

## Auth model

A FastAPI dependency validates a bearer JWT on every `/v1` route (`/health` is
open). Issuer, audience, and signing material come from environment variables;
**no secret is hardcoded**.

- **Production**: RS256, keys fetched from `AUTH_JWKS_URL`, verifying
  `AUTH_AUDIENCE` and `AUTH_ISSUER`. An `AUTH_REQUIRED_SCOPE` gates the data
  endpoints.
- **Local/dev**: set `IS_AUTH_DEV_MODE=true` and `AUTH_DEV_SECRET=<dev-secret>`
  to validate HS256 tokens without committing any secret.

Missing/invalid token -> `401`; insufficient scope -> `403`. The token is never
logged.

## Required environment variables

| Variable | Required | Purpose |
| --- | --- | --- |
| `ATHENA_DATABASE` | yes | Glue catalog database (e.g. `finsir`) |
| `ATHENA_WORKGROUP` | yes | Athena workgroup |
| `ATHENA_OUTPUT` | yes | S3 URI for Athena results (e.g. `s3://<bucket>/athena-results/`) |
| `ATHENA_TABLE` | no | Silver table (default `silver_train`) |
| `AWS_REGION` | no | AWS region (default `us-east-1`) |
| `AUTH_ISSUER` | prod | Expected `iss` claim |
| `AUTH_AUDIENCE` | prod | Expected `aud` claim |
| `AUTH_JWKS_URL` | prod | JWKS endpoint (RS256) |
| `AUTH_REQUIRED_SCOPE` | no | Scope required for data endpoints |
| `IS_AUTH_DEV_MODE` | no | `true` enables local HS256 validation |
| `AUTH_DEV_SECRET` | dev | HS256 secret (dev mode only) |
| `SERVICE_NAME` / `SERVICE_VERSION` / `SERVICE_ENVIRONMENT` | no | Log metadata |

In dev mode, `AUTH_DEV_SECRET` is required and the JWKS/audience/issuer are not;
in production the reverse holds. `Settings` fails fast if required values are
missing.

## Run locally

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt

export ATHENA_DATABASE=finsir ATHENA_WORKGROUP=finsir
export ATHENA_OUTPUT=s3://finsir-<account-id>/athena-results/
export IS_AUTH_DEV_MODE=true AUTH_DEV_SECRET=dev-secret AUTH_REQUIRED_SCOPE=silver:read
# AWS credentials with Athena/Glue/S3 access must be available in the environment.

uvicorn app.main:app --host 0.0.0.0 --port 8080
```

## Run tests

```bash
pip install -r requirements.txt -r requirements-dev.txt
pytest --cov=app --cov-report=term-missing
```

Coverage floors (enforced minimums): domain > 90%, use cases >= 85%,
adapters >= 70%, global >= 80%. Tests use a fake `SilverRepository` and a fake
boto3 client — no real AWS calls.

## Build and push the image to ECR

```bash
cd terraform
terraform init && terraform apply   # creates the ECR repo (and the service)
ECR_URL=$(terraform output -raw ecr_repository_url)
AWS_REGION=us-east-1

aws ecr get-login-password --region $AWS_REGION \
  | docker login --username AWS --password-stdin "${ECR_URL%/*}"

cd ..
docker build -t "$ECR_URL:latest" .
docker push "$ECR_URL:latest"
```

Then re-run `terraform apply` (or redeploy the App Runner service) so it pulls
the new image.

## Deploy (Terraform)

`terraform/` is a self-contained root that provisions:

- an **ECR repository** for the image,
- an App Runner **instance role** (least privilege: `athena:StartQueryExecution`
  / `GetQueryExecution` / `GetQueryResults`, `glue:GetTable` / `GetDatabase` /
  `GetPartitions`, S3 read on the data bucket + read/write on the
  `athena-results/` prefix),
- an App Runner **access role** to pull from ECR,
- the **App Runner service** (port 8080) with the env vars above.

It references the data platform's bucket/database/workgroup through variables —
no account-specific values are hardcoded. Provider `aws ~> 5.80`, Terraform
`>= 1.5`, region `us-east-1`.

```bash
cd terraform
cp terraform.tfvars.example terraform.tfvars   # set data_bucket_name, auth_* , etc.
terraform init
terraform apply
```

Outputs: `service_url`, `ecr_repository_url`, `instance_role_arn`.
