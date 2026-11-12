"""Build the analytical gold tables (dashboard + baseline model) from silver.

One script, six tables. Each Glue job runs this script with a different
--TABLE, so the jobs run in parallel and fail independently:

  product_monthly_kpis   fecha_dato x product
      Holders, penetration, adds, drops and their rates, plus the product's
      popularity rank by adds that month (the popularity baseline).
  customer_profile       fecha_dato x segmento x age_band x sexo x income_band
      Sociodemographic profile: clients, activity, average age, seniority,
      income and number of products.
  product_penetration    fecha_dato x dimension x dimension_value x product
      Share of clients holding each product by segment, age band, income
      band, tenure band, sex, province and activity (heat maps).
  product_affinity       fecha_dato x product_a x product_b
      Co-holding of every ordered pair of products: support, confidence,
      lift and phi correlation (product correlation matrix).
  product_transitions    fecha_dato x from_product x to_product
      For clients who acquired to_product in month t, which products they
      held in t-1 ('sin_productos' if none). Sankey diagrams.
  baseline_popularity    fecha_dato
      Popularity model: rank products by adds in month t, recommend the top 7
      not already held, and score it with MAP@7 against the real adds of t+1.

Shared rules (same as gold_train and gold_segment_conversion):
  - "Previous/next month" means the calendar month, so a skipped month is
    "no data", never an older or newer row.
  - A missing product value (null) counts as "not held".
  - An add of product p in month t: the client has a row in t-1 without p and
    holds p in t. A drop: held p in t-1 and not in t.
  - A missing dimension value becomes 'desconocido' (unknown) in the group
    keys. Nothing is imputed: averages ignore missing values.
  - Nothing reads beyond month t except the baseline evaluation, which reads
    t+1 on purpose (it is the answer the baseline is scored against).

The output schema of every table is TABLES[name]["columns"]; it must match
gold_analytics_tables.json, which Terraform reads to create the Athena tables.

Job parameters (Glue Job parameters):
  --BUCKET   S3 bucket (required)
  --TABLE    one of the TABLES keys (required)
  --SILVER   silver input folder        (default silver/train/)
  --GOLD     gold output folder         (default gold/<TABLE>/)
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
NO_PRODUCTS = "sin_productos"
PRODUCT_NAMES = {
    "ind_ahor_fin_ult1": "Cuenta de ahorros",
    "ind_aval_fin_ult1": "Garantias",
    "ind_cco_fin_ult1": "Cuenta corriente",
    "ind_cder_fin_ult1": "Cuenta de derivados",
    "ind_cno_fin_ult1": "Cuenta de nomina",
    "ind_ctju_fin_ult1": "Cuenta junior",
    "ind_ctma_fin_ult1": "Cuenta Mas particular",
    "ind_ctop_fin_ult1": "Cuenta Particular",
    "ind_ctpp_fin_ult1": "Cuenta Particular Plus",
    "ind_deco_fin_ult1": "Deposito corto plazo",
    "ind_deme_fin_ult1": "Deposito mediano plazo",
    "ind_dela_fin_ult1": "Deposito largo plazo",
    "ind_ecue_fin_ult1": "Cuenta electronica",
    "ind_fond_fin_ult1": "Fondos",
    "ind_hip_fin_ult1": "Hipoteca",
    "ind_plan_fin_ult1": "Plan de pensiones",
    "ind_pres_fin_ult1": "Prestamos",
    "ind_reca_fin_ult1": "Impuestos",
    "ind_tjcr_fin_ult1": "Tarjeta de credito",
    "ind_valo_fin_ult1": "Valores",
    "ind_viv_fin_ult1": "Cuenta vivienda",
    "ind_nomina_ult1": "Nomina",
    "ind_nom_pens_ult1": "Pensiones",
    "ind_recibo_ult1": "Debito directo",
    NO_PRODUCTS: "Sin productos",
}
UNKNOWN = "desconocido"
TOP_K = 7

# Bands: (exclusive upper bound, label); the last bound is None ("and above").
# Labels sort alphabetically in their natural order, and 'desconocido' last.
AGE_BANDS = [
    (18, "00-17"),
    (25, "18-24"),
    (35, "25-34"),
    (45, "35-44"),
    (55, "45-54"),
    (65, "55-64"),
    (None, "65+"),
]
INCOME_BANDS = [
    (50_000, "000-050k"),
    (100_000, "050-100k"),
    (200_000, "100-200k"),
    (500_000, "200-500k"),
    (None, "500k+"),
]
TENURE_BANDS = [  # antiguedad, in months
    (7, "000-006m"),
    (13, "007-012m"),
    (37, "013-036m"),
    (61, "037-060m"),
    (121, "061-120m"),
    (None, "121m+"),
]


# --- shared helpers ----------------------------------------------------------


def prepare(silver):
    """fecha_dato as a date plus _month, a calendar month index."""
    df = silver.withColumn("fecha_dato", F.to_date(F.col("fecha_dato").cast("string")))
    return df.withColumn("_month", F.year("fecha_dato") * 12 + F.month("fecha_dato"))


def held(column):
    """True when the product is held; a null value counts as not held."""
    if isinstance(column, str):
        column = F.col(column)
    return F.coalesce(column, F.lit(0)) == 1


def count_if(condition):
    """Rows where condition is true (a null condition counts as false)."""
    return F.sum(F.when(condition, 1).otherwise(0)).cast("long")


def ratio(numerator, denominator):
    """numerator / denominator as a double; null when the denominator is 0."""
    num, den = F.col(numerator), F.col(denominator)
    return F.when(den > 0, num.cast("double") / den)


def with_neighbor_month(df, offset, prefix, flag):
    """Add flag (the client has a row offset calendar months away) and that
    month's value of every product as <prefix><product>."""
    by_client = Window.partitionBy("ncodpers").orderBy("_month")
    month = by_client.rangeBetween(offset, offset)
    return df.select(
        "*",
        (F.count(F.lit(1)).over(month) > 0).alias(flag),
        *[F.first(p).over(month).alias(f"{prefix}{p}") for p in PRODUCTS],
    )


def with_previous_month(df):
    return with_neighbor_month(df, -1, "_prev_", "_has_prev")


def products_where(condition_for):
    """Array with the products whose condition is true, in PRODUCTS order."""
    flagged = F.array(*[F.when(condition_for(p), F.lit(p)) for p in PRODUCTS])
    return F.filter(flagged, lambda x: x.isNotNull())


def product_name(column):
    """Readable product name (built per call: Columns need an active Spark)."""
    names = F.create_map(*[F.lit(x) for kv in PRODUCT_NAMES.items() for x in kv])
    return names[F.col(column)]


def band(column, bands):
    """Label of the band the value falls in; 'desconocido' when null."""
    value = F.col(column)
    expr = F.when(value.isNull(), F.lit(UNKNOWN))
    for upper, label in bands:
        expr = expr.when(value < upper, F.lit(label)) if upper is not None else expr.otherwise(F.lit(label))
    return expr


def known(column):
    return F.coalesce(F.col(column).cast("string"), F.lit(UNKNOWN))


def unpivot_products(wide, keys, metrics):
    """Wide columns <metric>__<product> into one row per product."""
    rows = [
        F.struct(F.lit(p).alias("product"), *[F.col(f"{m}__{p}").alias(m) for m in metrics])
        for p in PRODUCTS
    ]
    return wide.select(*keys, F.explode(F.array(*rows)).alias("_r")).select(*keys, "_r.*")


def conform(df, table):
    """Select the table's columns in order, cast to their declared types, and
    fecha_dato last (still a date; main() formats it for the partition)."""
    cols = [F.col(c["name"]).cast(c["type"]).alias(c["name"]) for c in TABLES[table]["columns"]]
    return df.select(*cols, "fecha_dato")


# --- 1. product_monthly_kpis -------------------------------------------------


def build_product_monthly_kpis(silver):
    df = with_previous_month(prepare(silver))
    prev = F.col("_has_prev")
    aggs = [
        F.count(F.lit(1)).alias("clients"),
        count_if(prev).alias("clients_with_prev"),
    ]
    for p in PRODUCTS:
        now, before = held(p), held(f"_prev_{p}")
        aggs += [
            count_if(now).alias(f"holders__{p}"),
            count_if(prev & ~before).alias(f"eligible__{p}"),
            count_if(prev & ~before & now).alias(f"adds__{p}"),
            count_if(prev & before).alias(f"holders_prev__{p}"),
            count_if(prev & before & ~now).alias(f"drops__{p}"),
        ]
    wide = df.groupBy("fecha_dato").agg(*aggs)
    long = unpivot_products(
        wide,
        ["fecha_dato", "clients", "clients_with_prev"],
        ["holders", "eligible", "adds", "holders_prev", "drops"],
    )
    by_adds = Window.partitionBy("fecha_dato").orderBy(F.col("adds").desc(), F.col("product"))
    result = long.select(
        "*",
        product_name("product").alias("product_name"),
        ratio("holders", "clients").alias("penetration_rate"),
        ratio("adds", "eligible").alias("add_rate"),
        ratio("drops", "holders_prev").alias("drop_rate"),
        (F.col("adds") - F.col("drops")).alias("net_adds"),
        F.when(F.col("clients_with_prev") > 0, F.row_number().over(by_adds)).alias(
            "popularity_rank"
        ),
    )
    return conform(result, "product_monthly_kpis")


# --- 2. customer_profile -----------------------------------------------------


def build_customer_profile(silver):
    df = prepare(silver)
    n_products = sum((held(p).cast("int") for p in PRODUCTS), F.lit(0))
    df = df.select(
        "fecha_dato",
        known("segmento").alias("segmento"),
        band("age", AGE_BANDS).alias("age_band"),
        known("sexo").alias("sexo"),
        band("renta", INCOME_BANDS).alias("income_band"),
        "age",
        "antiguedad",
        "renta",
        "ind_actividad_cliente",
        "ind_nuevo",
        n_products.alias("_n_products"),
    )
    result = df.groupBy("fecha_dato", "segmento", "age_band", "sexo", "income_band").agg(
        F.count(F.lit(1)).alias("clients"),
        count_if(F.col("ind_actividad_cliente") == 1).alias("active_clients"),
        count_if(F.col("ind_nuevo") == 1).alias("new_clients"),
        F.avg("age").alias("avg_age"),
        F.avg("antiguedad").alias("avg_antiguedad_months"),
        F.avg("renta").alias("avg_renta"),
        F.percentile_approx("renta", 0.5).alias("median_renta"),
        F.count("renta").alias("renta_known"),
        F.avg("_n_products").alias("avg_n_products"),
        count_if(F.col("_n_products") == 0).alias("clients_without_products"),
    )
    result = result.withColumn("active_rate", ratio("active_clients", "clients"))
    return conform(result, "customer_profile")


# --- 3. product_penetration --------------------------------------------------


def penetration_dimensions():
    """(dimension name, value expression) pairs for the heat maps."""
    actividad = (
        F.when(F.col("ind_actividad_cliente") == 1, F.lit("activo"))
        .when(F.col("ind_actividad_cliente") == 0, F.lit("inactivo"))
        .otherwise(F.lit(UNKNOWN))
    )
    return [
        ("segmento", known("segmento")),
        ("age_band", band("age", AGE_BANDS)),
        ("income_band", band("renta", INCOME_BANDS)),
        ("tenure_band", band("antiguedad", TENURE_BANDS)),
        ("sexo", known("sexo")),
        ("provincia", known("nomprov")),
        ("actividad", actividad),
    ]


def build_product_penetration(silver):
    df = prepare(silver)
    dims = F.array(
        *[
            F.struct(F.lit(name).alias("dimension"), value.alias("dimension_value"))
            for name, value in penetration_dimensions()
        ]
    )
    # One row per client-month and dimension, so a single aggregation covers
    # every dimension (Spark aggregates partially before the shuffle).
    exploded = df.select(
        "fecha_dato",
        F.explode(dims).alias("_d"),
        *[held(p).cast("int").alias(p) for p in PRODUCTS],
    ).select("fecha_dato", "_d.dimension", "_d.dimension_value", *PRODUCTS)
    keys = ["fecha_dato", "dimension", "dimension_value"]
    wide = exploded.groupBy(*keys).agg(
        F.count(F.lit(1)).alias("clients"),
        *[F.sum(p).alias(f"holders__{p}") for p in PRODUCTS],
    )
    long = unpivot_products(wide, keys + ["clients"], ["holders"])
    result = long.select(
        "*",
        product_name("product").alias("product_name"),
        ratio("holders", "clients").alias("penetration_rate"),
    )
    return conform(result, "product_penetration")


# --- 4. product_affinity -----------------------------------------------------


def _pair(a, b):
    return f"both__{min(a, b)}__{max(a, b)}"


def build_product_affinity(silver):
    df = prepare(silver).select(
        "fecha_dato", *[held(p).cast("int").alias(p) for p in PRODUCTS]
    )
    pairs = [(a, b) for i, a in enumerate(PRODUCTS) for b in PRODUCTS[i + 1 :]]
    wide = df.groupBy("fecha_dato").agg(
        F.count(F.lit(1)).alias("clients"),
        *[F.sum(p).alias(f"n__{p}") for p in PRODUCTS],
        *[F.sum(F.col(a) * F.col(b)).alias(_pair(a, b)) for a, b in pairs],
    )
    rows = [
        F.struct(
            F.lit(a).alias("product_a"),
            F.lit(b).alias("product_b"),
            F.col(f"n__{a}").alias("holders_a"),
            F.col(f"n__{b}").alias("holders_b"),
            F.col(_pair(a, b)).alias("holders_both"),
        )
        for a in PRODUCTS
        for b in PRODUCTS
        if a != b
    ]
    long = wide.select("fecha_dato", "clients", F.explode(F.array(*rows)).alias("_r")).select(
        "fecha_dato", "clients", "_r.*"
    )
    n = F.col("clients").cast("double")
    na, nb = F.col("holders_a").cast("double"), F.col("holders_b").cast("double")
    nab = F.col("holders_both").cast("double")
    phi_den = F.sqrt(na * (n - na) * nb * (n - nb))
    result = long.select(
        "*",
        product_name("product_a").alias("product_a_name"),
        product_name("product_b").alias("product_b_name"),
        ratio("holders_both", "clients").alias("support"),
        ratio("holders_both", "holders_a").alias("confidence"),
        F.when((na > 0) & (nb > 0), nab * n / (na * nb)).alias("lift"),
        F.when(phi_den > 0, (n * nab - na * nb) / phi_den).alias("phi"),
    )
    return conform(result, "product_affinity")


# --- 5. product_transitions --------------------------------------------------

_TOTAL = "__total__"


def build_product_transitions(silver):
    df = with_previous_month(prepare(silver)).where(F.col("_has_prev"))
    held_before = products_where(lambda p: held(f"_prev_{p}"))
    acquired = products_where(lambda p: ~held(f"_prev_{p}") & held(p))
    df = df.select(
        "fecha_dato",
        acquired.alias("_to"),
        F.when(F.size(held_before) > 0, held_before)
        .otherwise(F.array(F.lit(NO_PRODUCTS)))
        .alias("_from"),
    ).where(F.size("_to") > 0)
    # The extra __total__ source gives each client one row per acquired
    # product, so the same aggregation also counts the adds of to_product.
    links = (
        df.select("fecha_dato", F.explode("_to").alias("to_product"), "_from")
        .select(
            "fecha_dato",
            "to_product",
            F.explode(F.concat("_from", F.array(F.lit(_TOTAL)))).alias("from_product"),
        )
        .groupBy("fecha_dato", "to_product", "from_product")
        .agg(F.count(F.lit(1)).alias("clients"))
    )
    by_target = Window.partitionBy("fecha_dato", "to_product")
    links = links.withColumn(
        "to_product_adds",
        F.max(F.when(F.col("from_product") == _TOTAL, F.col("clients"))).over(by_target),
    ).where(F.col("from_product") != _TOTAL)
    result = links.select(
        "*",
        product_name("from_product").alias("from_product_name"),
        product_name("to_product").alias("to_product_name"),
        ratio("clients", "to_product_adds").alias("share"),
    )
    return conform(result, "product_transitions")


# --- 6. baseline_popularity --------------------------------------------------


def average_precision(recommended, actual, k=TOP_K):
    """AP@k of a recommended list against the actual adds (Kaggle formula):
    sum over positions i <= k of precision@i at each hit, divided by
    min(|actual|, k); 0 when there are no actual adds."""
    hits = []
    for i in range(1, k + 1):
        item = F.when(F.size(recommended) >= i, recommended.getItem(i - 1))
        hits.append(F.coalesce(F.array_contains(actual, item), F.lit(False)).cast("int"))
    total, precision_sum = F.lit(0), F.lit(0.0)
    for i, hit in enumerate(hits, start=1):
        total = total + hit
        precision_sum = precision_sum + hit * total / i
    n_actual = F.size(actual)
    ap = F.when(n_actual > 0, precision_sum / F.least(n_actual, F.lit(k))).otherwise(F.lit(0.0))
    return ap, total > 0


def popularity_ranking(df):
    """Per month: products ordered by adds in that month (ties by name).
    Null ranking when the month has no observable adds (the first month)."""
    adds = df.where(F.col("_has_prev")).groupBy("fecha_dato").agg(
        *[count_if(~held(f"_prev_{p}") & held(p)).alias(f"adds__{p}") for p in PRODUCTS]
    )
    long = unpivot_products(adds, ["fecha_dato"], ["adds"])
    ranked = long.groupBy("fecha_dato").agg(
        F.sum("adds").alias("total_adds"),
        F.sort_array(F.collect_list(F.struct((-F.col("adds")).alias("k"), "product"))).alias("_s"),
    )
    return ranked.select(
        "fecha_dato",
        "total_adds",
        F.when(F.col("total_adds") > 0, F.transform("_s", lambda x: x["product"])).alias(
            "_ranking"
        ),
    )


def build_baseline_popularity(silver):
    df = with_previous_month(prepare(silver))
    ranking = popularity_ranking(df)

    df = with_neighbor_month(df, 1, "_next_", "_has_next").where(F.col("_has_next"))
    clients = df.select(
        "fecha_dato",
        products_where(lambda p: held(p)).alias("_held"),
        products_where(lambda p: ~held(p) & held(f"_next_{p}")).alias("_actual"),
    )
    scored = clients.join(
        F.broadcast(ranking.where(F.col("_ranking").isNotNull())), "fecha_dato"
    )
    recommended = F.slice(
        F.filter("_ranking", lambda x: ~F.array_contains(F.col("_held"), x)), 1, TOP_K
    )
    scored = scored.withColumn("_recs", recommended)
    ap, hit = average_precision(F.col("_recs"), F.col("_actual"))
    buyer = F.size("_actual") > 0
    metrics = scored.groupBy("fecha_dato").agg(
        F.count(F.lit(1)).alias("clients_evaluated"),
        count_if(buyer).alias("clients_with_adds"),
        F.avg(ap).alias("map_at_7"),
        F.avg(F.when(buyer, ap)).alias("map_at_7_buyers"),
        F.avg(F.when(buyer, hit.cast("double"))).alias("hit_rate_at_7_buyers"),
    )

    months = prepare(silver).select("fecha_dato").distinct()
    result = (
        months.join(ranking, "fecha_dato", "left")
        .join(metrics, "fecha_dato", "left")
        .select(
            "*",
            F.concat_ws(",", F.slice("_ranking", 1, TOP_K)).alias("top_7_products"),
            F.concat_ws(",", "_ranking").alias("popularity_ranking"),
            F.date_format(F.add_months("fecha_dato", 1), "yyyy-MM-dd").alias("label_fecha_dato"),
        )
        .withColumn("total_adds", F.coalesce("total_adds", F.lit(0)))
        .withColumn("clients_evaluated", F.coalesce("clients_evaluated", F.lit(0)))
        .withColumn("clients_with_adds", F.coalesce("clients_with_adds", F.lit(0)))
        # concat_ws gives '' for a null ranking: keep it null instead.
        .withColumn("top_7_products", F.when(F.col("_ranking").isNotNull(), F.col("top_7_products")))
        .withColumn(
            "popularity_ranking", F.when(F.col("_ranking").isNotNull(), F.col("popularity_ranking"))
        )
    )
    return conform(result, "baseline_popularity")


# --- registry ----------------------------------------------------------------


def _columns(*spec):
    """("name type", ...) -> [{"name": ..., "type": ...}, ...]"""
    return [dict(zip(("name", "type"), s.split())) for s in spec]


TABLES = {
    "product_monthly_kpis": {
        "build": build_product_monthly_kpis,
        "columns": _columns(
            "product string", "product_name string", "clients bigint", "holders bigint",
            "penetration_rate double", "eligible bigint", "adds bigint", "add_rate double",
            "holders_prev bigint", "drops bigint", "drop_rate double", "net_adds bigint",
            "popularity_rank int",
        ),
    },
    "customer_profile": {
        "build": build_customer_profile,
        "columns": _columns(
            "segmento string", "age_band string", "sexo string", "income_band string",
            "clients bigint", "active_clients bigint", "active_rate double",
            "new_clients bigint", "avg_age double", "avg_antiguedad_months double",
            "avg_renta double", "median_renta double", "renta_known bigint",
            "avg_n_products double", "clients_without_products bigint",
        ),
    },
    "product_penetration": {
        "build": build_product_penetration,
        "columns": _columns(
            "dimension string", "dimension_value string", "product string",
            "product_name string", "clients bigint", "holders bigint",
            "penetration_rate double",
        ),
    },
    "product_affinity": {
        "build": build_product_affinity,
        "columns": _columns(
            "product_a string", "product_a_name string", "product_b string",
            "product_b_name string", "clients bigint", "holders_a bigint",
            "holders_b bigint", "holders_both bigint", "support double",
            "confidence double", "lift double", "phi double",
        ),
    },
    "product_transitions": {
        "build": build_product_transitions,
        "columns": _columns(
            "from_product string", "from_product_name string", "to_product string",
            "to_product_name string", "clients bigint", "to_product_adds bigint",
            "share double",
        ),
    },
    "baseline_popularity": {
        "build": build_baseline_popularity,
        "columns": _columns(
            "total_adds bigint", "top_7_products string", "popularity_ranking string",
            "label_fecha_dato string", "clients_evaluated bigint", "clients_with_adds bigint",
            "map_at_7 double", "map_at_7_buyers double", "hit_rate_at_7_buyers double",
        ),
    },
}


def main():
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--BUCKET", required=True)
    parser.add_argument("--TABLE", required=True, choices=sorted(TABLES))
    parser.add_argument("--SILVER", default="silver/train/")
    parser.add_argument("--GOLD", default="")
    # Glue adds its own arguments (--JOB_NAME, --JOB_RUN_ID, ...)
    args, _ = parser.parse_known_args()
    base = f"s3://{args.BUCKET}/"
    gold = args.GOLD or f"gold/{args.TABLE}/"

    spark = SparkSession.builder.appName(f"gold-{args.TABLE}").getOrCreate()

    silver = spark.read.parquet(base + args.SILVER)
    result = TABLES[args.TABLE]["build"](silver).withColumn(
        "fecha_dato", F.date_format("fecha_dato", "yyyy-MM-dd")
    )
    (
        result.repartition("fecha_dato")
        .write.mode("overwrite")
        .partitionBy("fecha_dato")
        .parquet(base + gold)
    )

    written = spark.read.parquet(base + gold)
    rows, months = written.count(), written.select("fecha_dato").distinct().count()
    print(f"[gold_{args.TABLE}] rows={rows} months={months}")
    if rows == 0:
        raise RuntimeError(f"gold_{args.TABLE} is empty: is silver populated?")

    spark.stop()


if __name__ == "__main__":
    main()
