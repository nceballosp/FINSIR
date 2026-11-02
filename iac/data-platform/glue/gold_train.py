"""Build the gold training table (gold_train) from the silver layer.

One output row per silver row: no client-month is dropped, so the job fails if
the gold row count differs from the silver row count.

Each row (client ncodpers, month t) holds:
  - Profile features: silver columns as of month t.
  - Holdings: the 24 products held in month t.
  - History features: holdings in months t-1, t-3 and t-6 (calendar months, so
    a skipped month gives null, never an older value), per-product "added in
    month t" flags (prefix added_, 0 in t-1 and 1 in t), and counts of products
    held, added and dropped in month t. The added_ flags are null when month
    t-1 does not exist for the client.
  - Labels (prefix label_next_): 1 if the client adds the product in month t+1
    (0 in t, 1 in t+1). Null when month t+1 does not exist for the client, which
    is always the case for the last month. Labels must never be used as model
    features: they are the answers.

Every feature only reads months <= t and every label only reads t and t+1, so a
model trained on features at t to predict labels at t does not see the future.
A missing product value (null) counts as "not held" when computing additions.

Job parameters (Glue Job parameters):
  --BUCKET   S3 bucket (required)
  --SILVER   silver input folder        (default silver/train/)
  --GOLD     gold output folder         (default gold/train/)
"""

import argparse

from pyspark.sql import SparkSession, Window, functions as F

PRODUCTS = [
    "ind_ahor_fin_ult1",
    "ind_aval_fin_ult1",
    "ind_cco_fin_ult1",
    "ind_cder_fin_ult1",
    "ind_cno_fin_ult1",
    "ind_ctju_fin_ult1",
    "ind_ctma_fin_ult1",
    "ind_ctop_fin_ult1",
    "ind_ctpp_fin_ult1",
    "ind_deco_fin_ult1",
    "ind_deme_fin_ult1",
    "ind_dela_fin_ult1",
    "ind_ecue_fin_ult1",
    "ind_fond_fin_ult1",
    "ind_hip_fin_ult1",
    "ind_plan_fin_ult1",
    "ind_pres_fin_ult1",
    "ind_reca_fin_ult1",
    "ind_tjcr_fin_ult1",
    "ind_valo_fin_ult1",
    "ind_viv_fin_ult1",
    "ind_nomina_ult1",
    "ind_nom_pens_ult1",
    "ind_recibo_ult1",
]
# Silver columns kept as features. Left out: nomprov (same as cod_prov),
# tipodom (constant), conyuemp and ult_fec_cli_1t (almost always empty),
# fecha_alta (antiguedad already measures seniority) and the silver
# quality-tracking columns.
PROFILE_COLUMNS = [
    "ind_empleado",
    "pais_residencia",
    "sexo",
    "age",
    "antiguedad",
    "ind_nuevo",
    "indrel",
    "indrel_1mes",
    "tiprel_1mes",
    "indresi",
    "indext",
    "canal_entrada",
    "indfall",
    "cod_prov",
    "ind_actividad_cliente",
    "renta",
    "segmento",
]
LAGS = (1, 3, 6)
ADDED_PREFIX = "added_"
LABEL_PREFIX = "label_next_"
COUNT_COLUMNS = [
    "n_products",
    "n_products_added",
    "n_products_dropped",
    "has_previous_month",
]


def lag_column(product, months):
    return f"{product}_lag{months}"


def added_column(product):
    return f"{ADDED_PREFIX}{product}"


def label_column(product):
    return f"{LABEL_PREFIX}{product}"


def gold_columns():
    """Output columns in table order, without the fecha_dato partition."""
    return (
        ["ncodpers", "month_of_year"]
        + PROFILE_COLUMNS
        + PRODUCTS
        + [lag_column(p, k) for k in LAGS for p in PRODUCTS]
        + [added_column(p) for p in PRODUCTS]
        + COUNT_COLUMNS
        + [label_column(p) for p in PRODUCTS]
        + [f"{LABEL_PREFIX}n_added"]
    )


def build_gold(silver):
    """Return the gold DataFrame (fecha_dato as a date) from a silver DataFrame."""
    df = silver.withColumn("fecha_dato", F.to_date(F.col("fecha_dato").cast("string")))
    df = df.withColumn("_month", F.year("fecha_dato") * 12 + F.month("fecha_dato"))

    by_month = Window.partitionBy("ncodpers").orderBy("_month")

    def month_at(offset):
        return by_month.rangeBetween(offset, offset)

    def value_at(column, offset):
        return F.first(column).over(month_at(offset))

    def present_at(offset):
        return F.count(F.lit(1)).over(month_at(offset)) > 0

    df = df.select(
        "*",
        present_at(-1).alias("_has_prev"),
        present_at(1).alias("_has_next"),
        *[value_at(p, -k).alias(lag_column(p, k)) for k in LAGS for p in PRODUCTS],
        *[value_at(p, 1).alias(f"_next_{p}") for p in PRODUCTS],
    )

    def held(column):
        return F.coalesce(F.col(column), F.lit(0)) == 1

    def count_true(conditions):
        return sum((c.cast("int") for c in conditions), F.lit(0))

    previous = {p: lag_column(p, 1) for p in PRODUCTS}
    added_now = {p: held(p) & ~held(previous[p]) for p in PRODUCTS}
    dropped = count_true(~held(p) & held(previous[p]) for p in PRODUCTS)
    added_next = {p: held(f"_next_{p}") & ~held(p) for p in PRODUCTS}

    df = df.select(
        "*",
        F.month("fecha_dato").alias("month_of_year"),
        *[
            F.when(F.col("_has_prev"), added_now[p].cast("int")).alias(added_column(p))
            for p in PRODUCTS
        ],
        count_true(held(p) for p in PRODUCTS).alias("n_products"),
        F.when(F.col("_has_prev"), count_true(added_now.values())).alias(
            "n_products_added"
        ),
        F.when(F.col("_has_prev"), dropped).alias("n_products_dropped"),
        F.col("_has_prev").cast("int").alias("has_previous_month"),
        *[
            F.when(F.col("_has_next"), added_next[p].cast("int")).alias(label_column(p))
            for p in PRODUCTS
        ],
        F.when(F.col("_has_next"), count_true(added_next.values())).alias(
            f"{LABEL_PREFIX}n_added"
        ),
    )
    return df.select(*gold_columns(), "fecha_dato")


def main():
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--BUCKET", required=True)
    parser.add_argument("--SILVER", default="silver/train/")
    parser.add_argument("--GOLD", default="gold/train/")
    # Glue adds its own arguments (--JOB_NAME, --JOB_RUN_ID, ...)
    args, _ = parser.parse_known_args()
    base = f"s3://{args.BUCKET}/"

    spark = SparkSession.builder.appName("gold-train").getOrCreate()

    silver = spark.read.parquet(base + args.SILVER)
    silver_rows = silver.count()

    gold = build_gold(silver).withColumn(
        "fecha_dato", F.date_format("fecha_dato", "yyyy-MM-dd")
    )
    (
        gold.repartition("fecha_dato")
        .sortWithinPartitions("ncodpers")
        .write.mode("overwrite")
        .partitionBy("fecha_dato")
        .parquet(base + args.GOLD)
    )

    gold_rows = spark.read.parquet(base + args.GOLD).count()
    print(f"[gold_train] silver_rows={silver_rows} gold_rows={gold_rows}")
    if gold_rows != silver_rows:
        raise RuntimeError(
            f"gold_train lost rows: silver={silver_rows} gold={gold_rows}"
        )

    spark.stop()


if __name__ == "__main__":
    main()
