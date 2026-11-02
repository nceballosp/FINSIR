# FINSIR

Proyecto **FINSIR** para las materias Aprendizaje Automático, Almacenamiento y
Procesamiento de Grandes Datos, y Visualización de Datos (Énfasis en Ciencia de
Datos, EAFIT).

FINSIR recommends financial products. Using the public _Santander Product
Recommendation_ dataset (Kaggle), it predicts which of the 24 products a client
is likely to get next month and returns a Top-K ranking (metric: MAP@7).

> More context: [`context/context.md`](context/context.md).

## What's built so far

Two pieces, both as Terraform on AWS (`us-east-1`, `aws ~> 5.80`, Terraform `>= 1.5`):

| Part          | Path                 | What it does                                                                                |
| ------------- | -------------------- | ------------------------------------------------------------------------------------------- |
| Data platform | `iac/data-platform/` | S3 lake + Glue cleaning and gold jobs + Athena tables (bronze/silver/rejected/quality/gold) |
| API           | `iac/api/`           | FastAPI that reads the gold training table from Athena, runs on ECS Fargate                 |

Still to do: the other gold tables, the ML model, and the Streamlit dashboard.
The API serves the gold training table (`gold_train`) only.

## How the data flows

```
CSV (Kaggle)
  └─▶ S3 Bronze (raw CSV)
        └─▶ Glue/PySpark cleans + types it
              └─▶ S3 Silver (Parquet)
                    └─▶ Glue/PySpark adds history + next-month labels
                          └─▶ S3 Gold gold_train (Parquet)   ◀── the API reads this
                                └─▶ [future] ML model → dashboard
Athena can query every layer.
```

`gold_train` columns: [`iac/data-platform/README.md`](iac/data-platform/README.md#gold-layer-gold_train).

## What you need

- **Python** 3.10+
- **Terraform** >= 1.5
- **Docker** (to build the API image)
- **AWS CLI** v2, logged in with a `terraform` profile that can use S3, Glue,
  Athena, IAM, ECR and ECS in `us-east-1`
- The Kaggle file **`train_ver2.csv`** (~2.3 GB). It is not in the repo (too big
  for git). Download it and **put it at `data/train_ver2.csv`** — that exact path
  is what step 2 uploads.

Secrets are never hardcoded. Copy each `*.tfvars.example` to `terraform.tfvars`
(git-ignored) and fill in the values before running `apply`.

## Deploy

Deploy the data platform first, then the API (the API uses the platform's bucket
and tables). Put `AWS_PROFILE=terraform` in front of each command, or run
`export AWS_PROFILE=terraform` once.

The API runs on **ECS Fargate** with a public IP and no load balancer. The URL is
`http://<task-ip>:8080` (plain HTTP; the `/v1/*` routes are still protected by a
JWT). App Runner was the first choice but this account can't use it.

### 1. Data platform

```bash
cd iac/data-platform/terraform
cp terraform.tfvars.example terraform.tfvars
AWS_PROFILE=terraform terraform init
AWS_PROFILE=terraform terraform apply
BUCKET=$(AWS_PROFILE=terraform terraform output -raw bucket)
```

### 2. Upload the CSV and run the cleaning job

Make sure the file is at `data/train_ver2.csv` first (see "What you need").

```bash
aws --profile terraform s3 cp data/train_ver2.csv "s3://$BUCKET/raw/train/train_ver2.csv"
aws --profile terraform glue start-job-run --job-name finsir-limpieza-train --region us-east-1
```

Wait until the job says `SUCCEEDED`:

```bash
aws --profile terraform glue get-job-runs --job-name finsir-limpieza-train \
  --region us-east-1 --max-items 1 --query 'JobRuns[0].JobRunState'
```

After that, the `silver_train` table is ready in Athena. Then build the gold
table and wait for `SUCCEEDED` the same way:

```bash
aws --profile terraform glue start-job-run --job-name finsir-gold-train --region us-east-1
aws --profile terraform glue get-job-runs --job-name finsir-gold-train \
  --region us-east-1 --max-items 1 --query 'JobRuns[0].JobRunState'
```

After that, the `gold_train` table is ready in Athena.

### 3. Build and push the API image

```bash
ECR_URL="663505294799.dkr.ecr.us-east-1.amazonaws.com/finsir-api"   # use your account's URL
aws --profile terraform ecr get-login-password --region us-east-1 \
  | docker login --username AWS --password-stdin "${ECR_URL%/*}"
cd iac/api                              # the Dockerfile is here
docker build -t "$ECR_URL:latest" .
docker push "$ECR_URL:latest"
```

If the repo doesn't exist yet:
`aws --profile terraform ecr create-repository --repository-name finsir-api --region us-east-1`.

### 4. Deploy the API

```bash
cd iac/api/terraform-ecs
cp terraform.tfvars.example terraform.tfvars
# Set auth_dev_secret (at least 16 chars). Remember it — you need the same value to make tokens.
AWS_PROFILE=terraform terraform init
AWS_PROFILE=terraform terraform apply
```

### 5. Find the URL and call it

The public IP changes every redeploy, so look it up:

```bash
cd iac/api/terraform-ecs
CLUSTER=$(AWS_PROFILE=terraform terraform output -raw cluster_name)
SERVICE=$(AWS_PROFILE=terraform terraform output -raw service_name)
TASK=$(aws --profile terraform ecs list-tasks --cluster "$CLUSTER" --service-name "$SERVICE" \
  --region us-east-1 --query 'taskArns[0]' --output text)
ENI=$(aws --profile terraform ecs describe-tasks --cluster "$CLUSTER" --tasks "$TASK" \
  --region us-east-1 --query 'tasks[0].attachments[0].details[?name==`networkInterfaceId`].value | [0]' --output text)
IP=$(aws --profile terraform ec2 describe-network-interfaces --network-interface-ids "$ENI" \
  --region us-east-1 --query 'NetworkInterfaces[0].Association.PublicIp' --output text)
echo "http://$IP:8080"
```

`/health` is open. For `/v1/*` you need a token signed with the same
`auth_dev_secret` and a `gold:read` scope:

```bash
cd iac/api
TOKEN=$(.venv/bin/python -c "import jwt,time; print(jwt.encode({'sub':'demo','scope':'gold:read','exp':int(time.time())+86400},'<your-auth_dev_secret>',algorithm='HS256'))")
curl "http://$IP:8080/health"
curl -H "Authorization: Bearer $TOKEN" "http://$IP:8080/v1/gold/train/clients/1375586"
curl -H "Authorization: Bearer $TOKEN" "http://$IP:8080/v1/gold/train/months/2016-04-28?size=10"
```

Swagger UI is at `http://$IP:8080/docs` — click **Authorize** and paste the token
(no `Bearer ` prefix).

## Tear down (so it stops costing money)

Destroy in reverse: API first, then the data platform. Once destroyed, nothing
keeps running or billing (only kept S3 data costs a few cents).

### 1. API

```bash
cd iac/api/terraform-ecs
AWS_PROFILE=terraform terraform destroy
```

This stops the Fargate task (the main cost). The ECR image stays; delete it too
if you want:

```bash
aws --profile terraform ecr delete-repository --repository-name finsir-api --region us-east-1 --force
```

### 2. Data platform

The S3 bucket isn't empty, so a plain destroy fails. Pick one:

**Delete everything, data included:**

```bash
cd iac/data-platform/terraform
AWS_PROFILE=terraform terraform destroy -var="force_destroy_bucket=true"
```

**Keep the data in S3** (so you don't re-upload 2.3 GB later), remove the rest:

```bash
cd iac/data-platform/terraform
AWS_PROFILE=terraform terraform state rm \
  'aws_s3_bucket.lake[0]' \
  'aws_s3_bucket_public_access_block.lake[0]' \
  'aws_s3_bucket_server_side_encryption_configuration.lake[0]' \
  'aws_s3_object.script'
AWS_PROFILE=terraform terraform destroy
```

### 3. Check nothing is left

```bash
aws --profile terraform ecs list-clusters --region us-east-1   # should be empty
aws --profile terraform s3 ls | grep finsir                    # empty if you deleted the bucket
```

> The old App Runner attempt left two unused IAM roles (`finsir-api-instance-role`,
> `finsir-api-access-role`). They're free; delete them by hand if you want a clean account.

## Run the API locally (no AWS deploy)

Dev mode checks HS256 tokens without any committed secret. The data routes still
need AWS credentials because they hit Athena/Glue.

```bash
cd iac/api
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
export ATHENA_DATABASE=finsir ATHENA_WORKGROUP=finsir
export ATHENA_OUTPUT=s3://finsir-<account-id>/athena-results/
export IS_AUTH_DEV_MODE=true AUTH_DEV_SECRET=dev-secret AUTH_REQUIRED_SCOPE=gold:read
uvicorn app.main:app --host 0.0.0.0 --port 8080
```

## Tests

```bash
# API (no real AWS calls)
cd iac/api
pip install -r requirements.txt -r requirements-dev.txt
pytest --cov=app --cov-report=term-missing

# Glue cleaning script (PySpark local, no AWS)
cd iac/data-platform
pip install pyspark pytest
python -m pytest glue
```

## More docs

- API — [`iac/api/README.md`](iac/api/README.md)
- Data platform — [`iac/data-platform/README.md`](iac/data-platform/README.md)

## APM (Agent Package Manager)

This repo uses **APM** to share the team's coding standards and the Engram memory
setup across AI assistants (Kiro, Claude, Codex). Manifest: [`apm.yml`](apm.yml);
dependencies land in `apm_modules/` (git-ignored).

```bash
apm install            # into the local project
apm install --global   # at user level instead
```

It pulls 9 coding-standard files plus 2 Engram files, and declares two MCP
servers: `document-loader` and `engram`. Engram needs the `engram` CLI on `PATH`
and `DEFAULT_ENGRAM_PROJECT` exported.

The hook `engram-save-on-stop.json` can't be installed by APM directly — copy it
by hand and reinstall:

```bash
mkdir -p .apm/hooks
cp engram-save-on-stop.json .apm/hooks/
apm install
```

## Team

Juan Felipe Restrepo Buitrago, Manuela Castaño Franco, Juan Esteban García Galvis,
Eduardo Andrés Piñeros Manjarres, Natalia Ceballos Posada.

## License

MIT.
