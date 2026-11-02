# FINSIR Data Platform (silver lakehouse)

Terraform that builds the silver layer of FINSIR: an S3 data lake, a Glue job
that cleans the raw Santander `train` dataset, and an Athena workgroup with a
Glue catalog database and four tables.

## What it creates

- **S3 lake** (`aws_s3_bucket.lake`): encrypted, no public access. Holds the raw
  CSV, the Glue script, and the silver / rejected / quality outputs.
- **Glue job** `finsir-limpieza-train`: runs `glue/limpieza_train.py` (Glue 5.0 /
  Spark) to clean and type the data, writing Parquet partitioned by `fecha_dato`,
  plus a rejected-rows dataset and a data-quality report.
- **IAM**: a least-privilege Glue role (reads the raw data + script, writes the
  three output folders and `tmp/`).
- **Athena**: a workgroup, the `finsir` database, and four tables:
    - `bronze_train` — raw CSV as-is, all strings.
    - `silver_train` — cleaned Parquet, partitioned by `fecha_dato`.
    - `rechazados_train` — rejected rows with a reason.
    - `calidad_train` — the quality report of the last run.

## Layout

```
iac/data-platform/
  glue/      limpieza_train.py        Glue ETL script (uploaded to S3 by s3.tf)
             test_limpieza_train.py   PySpark-local tests (no AWS)
  athena/    01_tablas.sql, 02_calidad.sql   Reference SQL (tables are made by Terraform)
  terraform/ the module
```

`glue/` must stay next to `terraform/` because `s3.tf` uploads the script from
`../glue/limpieza_train.py`.

## How to run

```bash
cd terraform
cp terraform.tfvars.example terraform.tfvars
terraform init
terraform apply
BUCKET=$(terraform output -raw bucket)
```

Then upload the raw CSV and run the cleaning job. The file is ~2.3 GB and is not
managed by Terraform, so **put it at `data/train_ver2.csv` first** (download it
from the Kaggle Santander Product Recommendation dataset):

```bash
aws s3 cp ../../../data/train_ver2.csv "s3://$BUCKET/raw/train/train_ver2.csv"
aws glue start-job-run --job-name finsir-limpieza-train --region us-east-1
```

The bucket name and these commands are also Terraform outputs (`bucket`,
`subir_el_csv`, `ejecutar_la_limpieza`). When the job finishes, `silver_train` is
queryable in Athena (no `MSCK REPAIR TABLE` needed — it uses partition projection).

## Toggles

| Variable                 | Default | What it does                                                                         |
| ------------------------ | ------- | ------------------------------------------------------------------------------------ |
| `create_bucket`          | `true`  | Create the bucket, or reuse one (`bucket_name` then required).                       |
| `create_athena`          | `true`  | Create the database, workgroup, and tables.                                          |
| `existing_glue_role_arn` | `""`    | Reuse an existing Glue role instead of making one.                                   |
| `partition_projection`   | `true`  | Auto-discover `fecha_dato=...` partitions.                                           |
| `force_destroy_bucket`   | `false` | Allow `terraform destroy` to delete a non-empty bucket. Keep `false` with real data. |

Region defaults to `us-east-1`; `aws ~> 5.80`, Terraform `>= 1.5`.

## Not done yet

The gold layer is not built here. The architecture diagram adds it later as a
batch pipeline: EventBridge → Step Functions → gold Glue jobs → gold tables.

## Tests

```bash
pip install pyspark pytest
python -m pytest glue
```
