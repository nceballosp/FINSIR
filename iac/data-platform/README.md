# FINSIR Data Platform (silver + gold lakehouse)

Terraform that builds the silver and gold layers of FINSIR: an S3 data lake, a
Glue job that cleans the raw Santander `train` dataset, two Glue jobs that build
the gold tables, and an Athena workgroup with a Glue catalog database and six
tables.

## What it creates

- **S3 lake** (`aws_s3_bucket.lake`): encrypted, no public access. Holds the raw
  CSV, the Glue scripts, and the silver / rejected / quality / gold outputs.
- **Glue job** `finsir-limpieza-train`: runs `glue/limpieza_train.py` (Glue 5.0 /
  Spark) to clean and type the data, writing Parquet partitioned by `fecha_dato`,
  plus a rejected-rows dataset and a data-quality report.
- **Glue job** `finsir-gold-train`: runs `glue/gold_train.py` to build
  `gold_train` from silver (see [Gold layer](#gold-layer-gold_train)).
- **Glue job** `finsir-gold-segment-conversion`: runs
  `glue/gold_segment_conversion.py` to build `gold_segment_conversion` from
  silver (see [Segment conversion](#segment-conversion-gold_segment_conversion)).
- **IAM**: a least-privilege Glue role (reads the raw data + scripts, writes the
  silver, rejected, quality and gold folders and `tmp/`).
- **Athena**: a workgroup, the `finsir` database, and six tables:
    - `bronze_train`: raw CSV as-is, all strings.
    - `silver_train`: cleaned Parquet, partitioned by `fecha_dato`.
    - `rechazados_train`: rejected rows with a reason.
    - `calidad_train`: the quality report of the last run.
    - `gold_train`: the model training table, partitioned by `fecha_dato`.
    - `gold_segment_conversion`: per-segment product conversion rates, partitioned by `fecha_dato`.

## Layout

```
iac/data-platform/
  glue/      limpieza_train.py            Cleaning job: bronze -> silver (uploaded to S3 by s3.tf)
             gold_train.py                Gold job: silver -> gold_train (uploaded to S3 by s3.tf)
             gold_segment_conversion.py   Gold job: silver -> gold_segment_conversion (uploaded by s3.tf)
             test_*.py                    PySpark-local tests (no AWS)
  athena/    01_tablas.sql, 02_calidad.sql   Reference SQL (tables are made by Terraform)
  terraform/ the module
```

`glue/` must stay next to `terraform/` because `s3.tf` uploads the scripts from
`../glue/`.

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

When the cleaning job is `SUCCEEDED`, build the gold table:

```bash
aws glue start-job-run --job-name finsir-gold-train --region us-east-1
aws glue start-job-run --job-name finsir-gold-segment-conversion --region us-east-1
aws glue get-job-runs --job-name finsir-gold-train --region us-east-1 \
  --max-items 1 --query 'JobRuns[0].JobRunState'
```

Both gold jobs read silver, so run them after cleaning succeeds; they are
independent of each other and can run in parallel.

The bucket name and these commands are also Terraform outputs (`bucket`,
`subir_el_csv`, `ejecutar_la_limpieza`, `run_gold_train`,
`run_gold_segment_conversion`). `silver_train`, `gold_train` and
`gold_segment_conversion` are queryable in Athena as soon as their job finishes
(no `MSCK REPAIR TABLE` needed: they use partition projection).

## Gold layer: `gold_train`

The table the propensity model trains on. It lives at `s3://<bucket>/gold/train/`
as Parquet partitioned by `fecha_dato`.

**Rows.** One row per client (`ncodpers`) per month (`fecha_dato`), one for each
silver row. No row is dropped: the job compares the silver and gold row counts
and fails if they differ.

**What one row means.** For client `c` in month `t`, the row holds the client's
profile and products in month `t`, the products held 1, 3 and 6 months before,
and the answers: which products `c` adds in month `t+1`.

**Origin** in the tables below:

- **raw**: copied unchanged from `silver_train`, which is the Kaggle CSV column
  after cleaning and typing.
- **computed**: calculated by `glue/gold_train.py`.

### Key and profile columns

| Column                  | Type               | Origin   | Description                                                                                          |
| ----------------------- | ------------------ | -------- | ---------------------------------------------------------------------------------------------------- |
| `ncodpers`              | bigint             | raw      | Client ID.                                                                                           |
| `fecha_dato`            | string (partition) | raw      | Month of the record, `YYYY-MM-DD` (2015-01-28 to 2016-05-28).                                        |
| `month_of_year`         | int                | computed | Month number (1-12) of `fecha_dato`, for seasonality.                                                |
| `ind_empleado`          | string             | raw      | Employee status: A active, B ex-employee, F subsidiary, N not an employee, P passive.                |
| `pais_residencia`       | string             | raw      | Country of residence.                                                                                |
| `sexo`                  | string             | raw      | Sex.                                                                                                 |
| `age`                   | int                | raw      | Age (null if impossible in the CSV, see silver cleaning).                                            |
| `antiguedad`            | int                | raw      | Seniority in months (null if negative in the CSV).                                                   |
| `ind_nuevo`             | int                | raw      | 1 if the client registered in the last 6 months.                                                     |
| `indrel`                | int                | raw      | 1 primary client; 99 primary during the month but not at month end.                                  |
| `indrel_1mes`           | string             | raw      | Client type at month start: 1 primary, 2 co-owner, P potential, 3 former primary, 4 former co-owner. |
| `tiprel_1mes`           | string             | raw      | Relation at month start: A active, I inactive, P former client, R potential.                         |
| `indresi`               | string             | raw      | S/N: lives in the same country as the bank.                                                          |
| `indext`                | string             | raw      | S/N: born in a different country than the bank.                                                      |
| `canal_entrada`         | string             | raw      | Channel the client joined through.                                                                   |
| `indfall`               | string             | raw      | S/N: deceased.                                                                                       |
| `cod_prov`              | int                | raw      | Province code of the client's address.                                                               |
| `ind_actividad_cliente` | int                | raw      | 1 active client, 0 inactive.                                                                         |
| `renta`                 | double             | raw      | Gross household income (null when unknown; never imputed).                                           |
| `segmento`              | string             | raw      | 01 VIP, 02 individuals, 03 college graduates.                                                        |

### Product columns

Each of the 24 products has five columns. The families:

| Column pattern         | Type | Origin   | Description                                                                                                                              |
| ---------------------- | ---- | -------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| `<product>`            | int  | raw      | 1 if the client holds the product in month `t`, 0 if not, null if missing in the CSV.                                                    |
| `<product>_lag1`       | int  | computed | `<product>` in month `t-1`. Null if the client has no row that month or the value is missing.                                            |
| `<product>_lag3`       | int  | computed | `<product>` in month `t-3`. Same null rule.                                                                                              |
| `<product>_lag6`       | int  | computed | `<product>` in month `t-6`. Same null rule.                                                                                              |
| `added_<product>`      | int  | computed | 1 if the client added the product **this** month (not held in `t-1`, held in `t`), 0 if not. Null if no row in `t-1`. A safe feature.    |
| `label_next_<product>` | int  | computed | **Label.** 1 if the client adds the product in `t+1` (not held in `t`, held in `t+1`), 0 if not. Null if the client has no row in `t+1`. |

`added_<product>` (this month) and `label_next_<product>` (next month) use the
same 0→1 rule shifted by one month: the first is an input feature, the second is
the answer.

Lags look at calendar months, not at the previous row: if a client skipped a
month, the lag is null instead of an older value.

All 24 products and their column names (each also has `added_<product>`):

| Product                   | Holding (raw)       | Lags (computed)                            | Label (computed)               |
| ------------------------- | ------------------- | ------------------------------------------ | ------------------------------ |
| Savings account           | `ind_ahor_fin_ult1` | `ind_ahor_fin_ult1_lag1`, `_lag3`, `_lag6` | `label_next_ind_ahor_fin_ult1` |
| Guarantees                | `ind_aval_fin_ult1` | `ind_aval_fin_ult1_lag1`, `_lag3`, `_lag6` | `label_next_ind_aval_fin_ult1` |
| Current account           | `ind_cco_fin_ult1`  | `ind_cco_fin_ult1_lag1`, `_lag3`, `_lag6`  | `label_next_ind_cco_fin_ult1`  |
| Derivatives account       | `ind_cder_fin_ult1` | `ind_cder_fin_ult1_lag1`, `_lag3`, `_lag6` | `label_next_ind_cder_fin_ult1` |
| Payroll account           | `ind_cno_fin_ult1`  | `ind_cno_fin_ult1_lag1`, `_lag3`, `_lag6`  | `label_next_ind_cno_fin_ult1`  |
| Junior account            | `ind_ctju_fin_ult1` | `ind_ctju_fin_ult1_lag1`, `_lag3`, `_lag6` | `label_next_ind_ctju_fin_ult1` |
| "Más particular" account  | `ind_ctma_fin_ult1` | `ind_ctma_fin_ult1_lag1`, `_lag3`, `_lag6` | `label_next_ind_ctma_fin_ult1` |
| "Particular" account      | `ind_ctop_fin_ult1` | `ind_ctop_fin_ult1_lag1`, `_lag3`, `_lag6` | `label_next_ind_ctop_fin_ult1` |
| "Particular Plus" account | `ind_ctpp_fin_ult1` | `ind_ctpp_fin_ult1_lag1`, `_lag3`, `_lag6` | `label_next_ind_ctpp_fin_ult1` |
| Short-term deposit        | `ind_deco_fin_ult1` | `ind_deco_fin_ult1_lag1`, `_lag3`, `_lag6` | `label_next_ind_deco_fin_ult1` |
| Medium-term deposit       | `ind_deme_fin_ult1` | `ind_deme_fin_ult1_lag1`, `_lag3`, `_lag6` | `label_next_ind_deme_fin_ult1` |
| Long-term deposit         | `ind_dela_fin_ult1` | `ind_dela_fin_ult1_lag1`, `_lag3`, `_lag6` | `label_next_ind_dela_fin_ult1` |
| e-account                 | `ind_ecue_fin_ult1` | `ind_ecue_fin_ult1_lag1`, `_lag3`, `_lag6` | `label_next_ind_ecue_fin_ult1` |
| Funds                     | `ind_fond_fin_ult1` | `ind_fond_fin_ult1_lag1`, `_lag3`, `_lag6` | `label_next_ind_fond_fin_ult1` |
| Mortgage                  | `ind_hip_fin_ult1`  | `ind_hip_fin_ult1_lag1`, `_lag3`, `_lag6`  | `label_next_ind_hip_fin_ult1`  |
| Pension plan              | `ind_plan_fin_ult1` | `ind_plan_fin_ult1_lag1`, `_lag3`, `_lag6` | `label_next_ind_plan_fin_ult1` |
| Loans                     | `ind_pres_fin_ult1` | `ind_pres_fin_ult1_lag1`, `_lag3`, `_lag6` | `label_next_ind_pres_fin_ult1` |
| Taxes                     | `ind_reca_fin_ult1` | `ind_reca_fin_ult1_lag1`, `_lag3`, `_lag6` | `label_next_ind_reca_fin_ult1` |
| Credit card               | `ind_tjcr_fin_ult1` | `ind_tjcr_fin_ult1_lag1`, `_lag3`, `_lag6` | `label_next_ind_tjcr_fin_ult1` |
| Securities                | `ind_valo_fin_ult1` | `ind_valo_fin_ult1_lag1`, `_lag3`, `_lag6` | `label_next_ind_valo_fin_ult1` |
| Home account              | `ind_viv_fin_ult1`  | `ind_viv_fin_ult1_lag1`, `_lag3`, `_lag6`  | `label_next_ind_viv_fin_ult1`  |
| Payroll                   | `ind_nomina_ult1`   | `ind_nomina_ult1_lag1`, `_lag3`, `_lag6`   | `label_next_ind_nomina_ult1`   |
| Pensions                  | `ind_nom_pens_ult1` | `ind_nom_pens_ult1_lag1`, `_lag3`, `_lag6` | `label_next_ind_nom_pens_ult1` |
| Direct debit              | `ind_recibo_ult1`   | `ind_recibo_ult1_lag1`, `_lag3`, `_lag6`   | `label_next_ind_recibo_ult1`   |

### Count columns

| Column               | Type | Origin   | Description                                                                                                                                   |
| -------------------- | ---- | -------- | --------------------------------------------------------------------------------------------------------------------------------------------- |
| `n_products`         | int  | computed | Products held in month `t`.                                                                                                                   |
| `n_products_added`   | int  | computed | Products added in month `t` (not held in `t-1`, held in `t`). Null if the client has no row in `t-1`.                                         |
| `n_products_dropped` | int  | computed | Products dropped in month `t` (held in `t-1`, not held in `t`). Null if the client has no row in `t-1`.                                       |
| `has_previous_month` | int  | computed | 1 if the client has a row in `t-1`, 0 if not (new client or a skipped month).                                                                 |
| `label_next_n_added` | int  | computed | **Label.** Number of products added in `t+1`. Null if the client has no row in `t+1`. Use `label_next_n_added > 0` to pick the training rows. |

In total: 168 columns plus the `fecha_dato` partition (2 key, 17 profile, 24
holdings, 72 lags, 24 `added_`, 4 counts, 24 `label_next_`, 1 `label_next_n_added`).

### Silver columns left out

| Column                                    | Why                                            |
| ----------------------------------------- | ---------------------------------------------- |
| `nomprov`                                 | Same information as `cod_prov`.                |
| `tipodom`                                 | Always 1.                                      |
| `conyuemp`, `ult_fec_cli_1t`              | Almost always empty.                           |
| `fecha_alta`                              | `antiguedad` already measures seniority.       |
| `campos_rescatados`, `campos_invalidados` | Data-quality tracking, not client information. |

They stay in `silver_train`; nothing is deleted from the lake.

## Segment conversion: `gold_segment_conversion`

How often each type of client adopts each product. It helps the model with
clients who have little history, and it feeds the dashboard. It lives at
`s3://<bucket>/gold/segment_conversion/` as Parquet partitioned by `fecha_dato`.

**Rows.** One row per `fecha_dato` × `segmento` × product (24 products × the
segments present each month). Rows with no `segmento` are dropped: the rate is
defined per segment.

**What one row means.** For a segment and product at month `t`, the conversion
rate is adopters ÷ eligible, counted over every month **strictly before** `t`:

- **eligible**: clients in the segment who did not hold the product the month
  before, and who have a row that month (so an adoption could be observed),
- **adopters**: those eligible clients who started holding it that month.

| Column            | Type               | Origin   | Description                                                                                       |
| ----------------- | ------------------ | -------- | ------------------------------------------------------------------------------------------------- |
| `segmento`        | string             | raw      | Client segment (01 VIP, 02 individuals, 03 college graduates).                                    |
| `product`         | string             | computed | One of the 24 `ind_*_ult1` product names.                                                         |
| `eligible`        | bigint             | computed | Clients in the segment eligible to adopt the product, summed over all months before `fecha_dato`. |
| `adopters`        | bigint             | computed | Eligible clients who adopted it, summed over all months before `fecha_dato`.                      |
| `conversion_rate` | double             | computed | `adopters / eligible`. Null when `eligible` is 0 (the first month has no prior data).             |
| `fecha_dato`      | string (partition) | raw      | The month the rate applies to, `YYYY-MM-DD`.                                                      |

**No leakage.** The rate for month `t` uses only months before `t`, so joining
`gold_segment_conversion` into `gold_train` on (`fecha_dato`, `segmento`,
`product`) gives a feature that never sees month `t`'s own purchases or the
label. The earliest month's rate is null.

## Rules for using gold_train without leakage

- **Features** are every column without the `label_next_` prefix, including the
  `added_` flags. They only read months up to `t`.
- **Labels** are the `label_next_` columns. They read month `t+1`. Never feed
  them to the model as inputs.
- A missing product value counts as "not held" when computing additions, so a
  product going from null to 1 counts as added.
- **May 2016 has no labels** (there is no June 2016 in the CSV). Those rows are
  the input for real recommendations.
- **Out-of-time split:** train on rows with `fecha_dato` up to 2016-02-28,
  validate on 2016-03-28 (labels are the April additions), and test on
  2016-04-28 (labels are the May additions). Never train on the test month.

## Toggles

| Variable                 | Default | What it does                                                                         |
| ------------------------ | ------- | ------------------------------------------------------------------------------------ |
| `create_bucket`          | `true`  | Create the bucket, or reuse one (`bucket_name` then required).                       |
| `create_athena`          | `true`  | Create the database, workgroup, and tables.                                          |
| `existing_glue_role_arn` | `""`    | Reuse an existing Glue role instead of making one.                                   |
| `partition_projection`   | `true`  | Auto-discover `fecha_dato=...` partitions.                                           |
| `force_destroy_bucket`   | `false` | Allow `terraform destroy` to delete a non-empty bucket. Keep `false` with real data. |

The gold output folder is `gold_prefix` (default `gold/train/`).

Region defaults to `us-east-1`; `aws ~> 5.80`, Terraform `>= 1.5`.

## Not done yet

The remaining gold tables (dashboard aggregates, test-set results) and the
orchestration (EventBridge → Step Functions → Glue jobs) come later. Today the
three Glue jobs are started by hand, cleaning first.

## Tests

```bash
pip install pyspark pytest
python -m pytest glue
```

The `gold_train` tests check the labels, the lags, the `added_` flags, the
skipped-month rule, that no row is lost, that features don't change when future
months are added, and that the API's column list matches the job's. The
`gold_segment_conversion` tests check that the rate only uses earlier months
(never its own month), that segments stay separate, and that rows without a
segment are dropped.
