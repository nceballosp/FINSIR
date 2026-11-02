"""Build the gold segment conversion table (gold_segment_conversion) from silver.

One row per (fecha_dato, segmento, product). The rate answers: for a client in
this segment who did NOT hold the product last month, how often did clients like
them start holding it, using only the months strictly before fecha_dato.

  conversion_rate = adopters_before / eligible_before

where, over every month m < fecha_dato:
  - eligible: clients who did not hold the product in month m-1 and have a row
    in month m (so an adoption could be observed),
  - adopters: those eligible clients who hold the product in month m.

The rate for fecha_dato never looks at fecha_dato itself or any later month, so
it is safe to join into gold_train as a feature of that month without leaking
the label. The earliest month has no prior data, so its rate is null.

A missing product value (null) counts as "not held". Rows without a segmento are
dropped: the rate is defined per segment.

Job parameters (Glue Job parameters):
  --BUCKET   S3 bucket (required)
  --SILVER   silver input folder               (default silver/train/)
  --GOLD     gold output folder for this table  (default gold/segment_conversion/)
"""
import argparse

from pyspark.sql import SparkSession, Window, functions as F

PRODUCTS = [
    "ind_ahor_fin_ult1", "ind_aval_fin_ult1", "ind_cco_fin_ult1",
    "ind_cder_fin_ult1", "ind_cno_fin_ult1", "ind_ctju_fin_ult1",
    "ind_ctma_fin_ult1", "ind_ctop_fin_ult1", "ind_ctpp_fin_ult1",
    "ind_deco_fin_ult1", "ind_deme_fin_ult1", "ind_dela_fin_ult1",
    "ind_ecue_fin_ult1", "ind_fond_fin_ult1", "ind_hip_fin_ult1",
    "ind_plan_fin_ult1", "ind_pres_fin_ult1", "ind_reca_fin_ult1",
    "ind_tjcr_fin_ult1", "ind_valo_fin_ult1", "ind_viv_fin_ult1",
    "ind_nomina_ult1", "ind_nom_pens_ult1", "ind_recibo_ult1",
]
OUTPUT_COLUMNS = [
    "segmento", "product", "eligible", "adopters", "conversion_rate", "fecha_dato",
]


def build_conversion(silver):
    """Return the conversion DataFrame (fecha_dato as a date) from silver.

    Shape: one row per (fecha_dato, segmento, product). conversion_rate and the
    cumulative counts only use months strictly before fecha_dato.
    """
    df = silver.withColumn("fecha_dato", F.to_date(F.col("fecha_dato").cast("string")))
    df = df.withColumn("_month", F.year("fecha_dato") * 12 + F.month("fecha_dato"))
    df = df.where(F.col("segmento").isNotNull())

    by_client = Window.partitionBy("ncodpers").orderBy("_month")

    def held(column):
        return F.coalesce(F.col(column), F.lit(0)) == 1

    # Per client-month, flag for each product: was it eligible (not held last
    # calendar month) and was it adopted (eligible and held this month).
    prev_present = F.count(F.lit(1)).over(by_client.rangeBetween(-1, -1)) > 0
    flags = []
    for p in PRODUCTS:
        prev = F.first(p).over(by_client.rangeBetween(-1, -1))
        eligible = prev_present & (F.coalesce(prev, F.lit(0)) == 0)
        flags.append(eligible.alias(f"_elig_{p}"))
        flags.append((eligible & held(p)).alias(f"_adopt_{p}"))
    df = df.select("fecha_dato", "_month", "segmento", *flags)

    # Monthly totals per segment and product: one tall table (one row per
    # month, segment, product) so the expanding sum stays cheap.
    per_product = []
    for p in PRODUCTS:
        agg = (
            df.groupBy("fecha_dato", "_month", "segmento")
            .agg(
                F.sum(F.col(f"_elig_{p}").cast("long")).alias("elig_m"),
                F.sum(F.col(f"_adopt_{p}").cast("long")).alias("adopt_m"),
            )
            .withColumn("product", F.lit(p))
        )
        per_product.append(agg)
    monthly = per_product[0]
    for agg in per_product[1:]:
        monthly = monthly.unionByName(agg)

    # Expanding sum over months strictly before each month, per segment+product.
    before = (
        Window.partitionBy("segmento", "product")
        .orderBy("_month")
        .rangeBetween(Window.unboundedPreceding, -1)
    )
    eligible_before = F.coalesce(F.sum("elig_m").over(before), F.lit(0))
    adopters_before = F.coalesce(F.sum("adopt_m").over(before), F.lit(0))

    result = monthly.select(
        "segmento",
        "product",
        eligible_before.alias("eligible"),
        adopters_before.alias("adopters"),
        F.when(eligible_before > 0, adopters_before / eligible_before).alias(
            "conversion_rate"
        ),
        "fecha_dato",
    )
    return result.select(*OUTPUT_COLUMNS)


def main():
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--BUCKET", required=True)
    parser.add_argument("--SILVER", default="silver/train/")
    parser.add_argument("--GOLD", default="gold/segment_conversion/")
    # Glue adds its own arguments (--JOB_NAME, --JOB_RUN_ID, ...)
    args, _ = parser.parse_known_args()
    base = f"s3://{args.BUCKET}/"

    spark = SparkSession.builder.appName("gold-segment-conversion").getOrCreate()

    silver = spark.read.parquet(base + args.SILVER)
    result = build_conversion(silver).withColumn(
        "fecha_dato", F.date_format("fecha_dato", "yyyy-MM-dd")
    )
    (
        result.repartition("fecha_dato")
        .write.mode("overwrite")
        .partitionBy("fecha_dato")
        .parquet(base + args.GOLD)
    )

    rows = spark.read.parquet(base + args.GOLD).count()
    print(f"[gold_segment_conversion] rows={rows}")

    spark.stop()


if __name__ == "__main__":
    main()
