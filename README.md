# FINSIR

Repositorio del proyecto **FINSIR**, desarrollado para las materias Aprendizaje
Automático, Almacenamiento y Procesamiento de Grandes Datos, y Visualización de
Datos (Línea de Énfasis en Ciencia de Datos, EAFIT).

FINSIR is an intelligent **financial-product recommendation system** based on
**adoption propensity**, built on the public _Santander Product Recommendation_
dataset (Kaggle). For each client it estimates the probability of contracting
each of the 24 portfolio products next month and returns a **Top-K ranking**.
The problem is modelled as **multi-label classification with propensity
ranking** (official metric: **MAP@7**), not as classic recommendation, because
the data is tabular-temporal with discontinuous acquisition.

> Full business and methodology context: [`context/context.md`](context/context.md).

## Purpose

Replace static, mass cross-selling campaigns with a propensity engine that:

- optimises CLV by anticipating client needs by life moment,
- lowers CAC by targeting only high-propensity prospects,
- hyper-personalises the digital experience via a REST API,
- prioritises campaigns through propensity ranking dashboards.

## What is implemented today

The repository currently contains the **data platform (silver lakehouse)** and
the **read API over the silver layer**. Both are provisioned as Terraform
(Infrastructure as Code) and target **AWS** (`us-east-1`, provider `aws ~> 5.80`,
Terraform `>= 1.5`).

| Component                                                                             | Path                          | Status                               |
| ------------------------------------------------------------------------------------- | ----------------------------- | ------------------------------------ |
| Data platform — S3 lake + Glue cleaning job + Athena (bronze/silver/rejected/quality) | `iac/data-platform/`          | Implemented, PySpark-local tests     |
| API — FastAPI over Athena `silver_train`, deployed on AWS App Runner                  | `iac/api/`                    | Implemented, 43 tests, ~96% coverage |
| Architecture diagrams                                                                 | `documentation/architecture/` | Diagrams only                        |

**Not implemented yet** (declared as future work, see the module READMEs and
`context/context.md`): the **gold layer** and its batch pipeline
(EventBridge → Step Functions → gold Glue jobs), the **ML model** (LightGBM /
XGBoost / CatBoost) and its MAP@7 evaluation, and the **Streamlit dashboard**.
The API serves the silver layer only; gold endpoints are future work.

> `silver-clean/` is the legacy Terraform from the Big Data _Trabajo 1_, kept for
> reference. The live, maintained module is `iac/data-platform/` (derived from it,
> with `project` renamed to `finsir`). `data_service/` is a reserved, empty folder.

## Architecture (end-to-end target)

```
CSV (Kaggle)
  └─▶ S3 Bronze (raw CSV, all STRING)
        └─▶ Glue/PySpark: validation + typing + quality rules
              └─▶ S3 Silver (Parquet, partitioned by fecha_dato)   ◀── served by the API
                    └─▶ [future] S3 Gold (ML-ready matrix)
                          └─▶ [future] GBDT model → MAP@7
                                └─▶ FastAPI (Top-K) + Streamlit dashboard
Amazon Athena queries every layer.
```

## Prerequisites

Local tooling (versions this repo was validated with in parentheses):

- **Python** 3.10+ (3.14).
- **Terraform** >= 1.5 (1.17).
- **Docker** (29.9) — to build and push the API image.
- **AWS CLI** v2 (2.38), configured with credentials that can manage
  **S3, Glue, Athena, IAM, ECR and App Runner** in `us-east-1`.
- The raw **Kaggle dataset** `train_ver2.csv` (~2.3 GB) for the cleaning job. It
  is **not** stored in the repo and **not** managed by Terraform.

Secrets are never hardcoded: auth material and account-specific values are passed
through Terraform variables / environment variables. Copy each
`*.tfvars.example` to `terraform.tfvars` (git-ignored) before applying.

## Execution (step by step)

Everything is AWS-backed; order matters because the API references the data
platform's bucket, database and workgroup. Terraform state is local by default;
to use an S3 backend, copy `backend.tf.example` to `backend.tf` first.

### 1. Deploy the data platform

```bash
cd iac/data-platform/terraform
cp terraform.tfvars.example terraform.tfvars   # adjust region/project if needed
terraform init
terraform apply   # S3 lake, Glue job finsir-limpieza-train, Athena workgroup + db + 4 tables
```

### 2. Load the raw CSV and run the cleaning job

```bash
aws s3 cp train_ver2.csv s3://<bucket>/raw/train/train_ver2.csv
aws glue start-job-run --job-name finsir-limpieza-train --region us-east-1
```

The exact commands are emitted as Terraform outputs (`subir_el_csv`,
`ejecutar_la_limpieza`). When the job finishes, `silver_train` is queryable in
Athena (partition projection — no `MSCK REPAIR TABLE`).

### 3. Deploy the API

```bash
cd iac/api/terraform
cp terraform.tfvars.example terraform.tfvars   # set data_bucket_name, auth_*, etc.
terraform init
terraform apply   # ECR repo, least-privilege IAM roles, App Runner service (port 8080)
```

### 4. Build, push the image, and redeploy

App Runner needs an image in ECR before it becomes healthy.

```bash
ECR_URL=$(terraform output -raw ecr_repository_url)
aws ecr get-login-password --region us-east-1 \
  | docker login --username AWS --password-stdin "${ECR_URL%/*}"
cd ..                                  # iac/api
docker build -t "$ECR_URL:latest" .
docker push "$ECR_URL:latest"
cd terraform && terraform apply        # or redeploy the service so it pulls :latest
```

### 5. Call the service

`service_url` is a Terraform output. `/health` is open; `/v1/*` requires a bearer JWT.

```bash
TOKEN="<bearer-jwt>"
SERVICE_URL=$(terraform output -raw service_url)
curl "$SERVICE_URL/health"
curl -H "Authorization: Bearer $TOKEN" "$SERVICE_URL/v1/clients/1/latest"
```

### Run the API locally (no AWS deploy)

Dev mode validates HS256 tokens without any committed secret. Data endpoints
still need AWS credentials because they query Athena/Glue.

```bash
cd iac/api
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
export ATHENA_DATABASE=finsir ATHENA_WORKGROUP=finsir
export ATHENA_OUTPUT=s3://finsir-<account-id>/athena-results/
export IS_AUTH_DEV_MODE=true AUTH_DEV_SECRET=dev-secret AUTH_REQUIRED_SCOPE=silver:read
uvicorn app.main:app --host 0.0.0.0 --port 8080
```

## Tests

```bash
# API (hexagonal, fake repository + fake boto3, no real AWS calls)
cd iac/api
pip install -r requirements.txt -r requirements-dev.txt
pytest --cov=app --cov-report=term-missing

# Glue cleaning script (PySpark-local, no AWS)
cd iac/data-platform
pip install pyspark pytest
python -m pytest glue
```

Coverage floors enforced for the API: domain > 90%, use cases >= 85%,
adapters >= 70%, global >= 80%.

## Module documentation

Each module has its own README with endpoints, variables, toggles and deployment
detail:

- API — [`iac/api/README.md`](iac/api/README.md)
- Data platform — [`iac/data-platform/README.md`](iac/data-platform/README.md)

## APM (Agent Package Manager)

This repo uses **APM** to distribute the team's coding standards and the Engram
memory integration into every AI assistant harness (Kiro, Claude, Codex). The
manifest is [`apm.yml`](apm.yml); the lockfile is `apm.lock.yaml`; installed
dependencies live under `apm_modules/` (git-ignored).

```bash
apm install            # install dependencies into the local harnesses
apm install --global   # install at user scope instead
```

The manifest pulls 9 coding-standard instruction files plus the two Engram
instruction files, and declares two MCP servers: `document-loader` (PDF/DOCX →
text) and `engram` (persistent agent memory, project `final-project-emphasis`).

**Engram prerequisites:** the `engram` CLI must be on `PATH` and the
`DEFAULT_ENGRAM_PROJECT` environment variable exported.

**Hook caveat:** `engram-save-on-stop.json` is **not** installable via a
single-file dependency ref (APM single-file refs only cover
`.instructions.md` / `.agent.md` / `.prompt.md`). Copy it manually after install
and re-run `apm install`:

```bash
mkdir -p .apm/hooks
cp engram-save-on-stop.json .apm/hooks/
apm install
```

## Team

FINSIR — Juan Felipe Restrepo Buitrago, Manuela Castaño Franco,
Juan Esteban García Galvis, Eduardo Andrés Piñeros Manjarres,
Natalia Ceballos Posada.

## License

MIT.
