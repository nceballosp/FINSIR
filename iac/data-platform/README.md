# FINSIR Data Platform (silver lakehouse)

Terraform module that provisions the **silver layer** of the FINSIR data platform:
an S3 data lake, a Glue ETL job that cleans the raw Santander `train` dataset, and
an Athena workgroup backed by a Glue Data Catalog database with four tables.

This module is a faithful replication of the original `silver-clean` Terraform,
with the default `project` renamed from `train-clean` to **`finsir`** to match the
architecture diagram (the lake is labelled "Finsir Data Lake" and the catalog
database "finsir DB"). The Glue `component` tag stays `limpieza-train` because it
names the job, not the project.

## Responsibility

- **S3 data lake** (`aws_s3_bucket.lake`): AES256 server-side encryption, all public
  access blocked. Holds the raw CSV, the Glue script, and the silver / rejected /
  quality outputs.
- **Glue silver job** (`finsir-limpieza-train`): runs `glue/limpieza_train.py`
  (Glue 5.0 / Spark) to clean and type the raw data, writing Parquet partitioned by
  `fecha_dato`, plus a rejected-records dataset and a data-quality report.
- **IAM** (`iam.tf`): a least-privilege Glue role that can only read the raw data and
  the script, and read/write the job's three output prefixes plus `tmp/`.
- **Athena** (`athena.tf`): a workgroup named after the project, a Glue Data Catalog
  database (`finsir`), and four external tables:
  - `bronze_train` — the raw CSV as-is, all string columns (OpenCSVSerde, header skipped).
  - `silver_train` — cleaned Parquet, partitioned by `fecha_dato` (partition projection).
  - `rechazados_train` — rejected rows with the rejection reason.
  - `calidad_train` — the data-quality report of the last run.

## Layout

```
iac/data-platform/
  glue/      limpieza_train.py        Glue ETL script (uploaded to S3 by s3.tf)
             test_limpieza_train.py   PySpark-local unit tests (no AWS)
  athena/    01_tablas.sql            Reference DDL (the tables are created by Terraform)
             02_calidad.sql           Reference quality queries
  terraform/ *.tf, *.tf.example       The module
```

`s3.tf` uploads the Glue script from `${path.module}/../glue/limpieza_train.py`, so
`glue/` must remain a sibling of `terraform/`.

## How to apply

```bash
cd terraform
cp terraform.tfvars.example terraform.tfvars   # adjust as needed
terraform init
terraform apply

# Upload the raw CSV manually (it is ~2.3 GB and is NOT managed by Terraform):
aws s3 cp train_ver2.csv s3://<bucket>/raw/train/train_ver2.csv

# Run the cleaning job:
aws glue start-job-run --job-name finsir-limpieza-train --region us-east-1
```

The bucket name and the exact commands are also emitted as Terraform outputs
(`bucket`, `subir_el_csv`, `ejecutar_la_limpieza`).

## Toggles

| Variable | Default | Purpose |
| --- | --- | --- |
| `create_bucket` | `true` | Create the bucket, or reuse an existing one (`bucket_name` then required). |
| `create_athena` | `true` | Create the catalog database, workgroup, and tables. |
| `existing_glue_role_arn` | `""` | Reuse an existing Glue role instead of creating the least-privilege one. |
| `partition_projection` | `true` | `silver_train` discovers `fecha_dato=YYYY-MM-DD` partitions automatically (no `MSCK REPAIR TABLE`). |

Region defaults to `us-east-1`; provider `aws ~> 5.80`, Terraform `>= 1.5`.

## Future work (out of scope here)

The gold layer is **not** implemented in this module. The architecture diagram
(`documentation/architecture/aws_architecture_diagram.drawio`) adds it later as a
batch pipeline, in this order:

1. **EventBridge** rule `pipeline-diario` (scheduled trigger).
2. **Step Functions** (`Orquestación`) orchestrating the pipeline.
3. **Glue jobs** `Procesamiento A` and `Procesamiento B` (Gold).
4. **Gold tables** written to `gold/` (Parquet, ready for analysis).

No gold Glue jobs, Step Functions, or EventBridge resources are declared in this
module today.

## Tests

The Glue script has PySpark-local unit tests (no AWS required):

```bash
pip install pyspark pytest
python -m pytest glue
```
