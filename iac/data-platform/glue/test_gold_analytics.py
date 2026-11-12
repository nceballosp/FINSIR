"""Tests for the analytical gold tables (gold_analytics.py), with local Spark.

pip install pyspark pytest
python -m pytest glue
"""

import importlib.util
import json
import os
import sys
from datetime import date
from pathlib import Path

import pytest
from pyspark.sql import SparkSession, functions as F
from pyspark.sql.types import (
    DateType,
    DoubleType,
    IntegerType,
    LongType,
    StringType,
    StructField,
    StructType,
)

os.environ.setdefault("PYSPARK_PYTHON", sys.executable)

HERE = Path(__file__).parent
spec = importlib.util.spec_from_file_location("gold_analytics", HERE / "gold_analytics.py")
ga = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ga)

AHOR = "ind_ahor_fin_ult1"
CCO = "ind_cco_fin_ult1"
TJCR = "ind_tjcr_fin_ult1"


@pytest.fixture(scope="module")
def spark():
    session = (
        SparkSession.builder.master("local[2]")
        .config("spark.sql.shuffle.partitions", "2")
        .config("spark.ui.enabled", "false")
        .getOrCreate()
    )
    yield session
    session.stop()


FIELDS = [
    StructField("ncodpers", LongType()),
    StructField("fecha_dato", DateType()),
    StructField("segmento", StringType()),
    StructField("sexo", StringType()),
    StructField("age", IntegerType()),
    StructField("antiguedad", IntegerType()),
    StructField("renta", DoubleType()),
    StructField("ind_actividad_cliente", IntegerType()),
    StructField("ind_nuevo", IntegerType()),
    StructField("nomprov", StringType()),
] + [StructField(p, IntegerType()) for p in ga.PRODUCTS]


def silver(spark, rows):
    schema = StructType(FIELDS)
    return spark.createDataFrame([tuple(r.get(f.name) for f in FIELDS) for r in rows], schema)


def rec(ncodpers, month, *held, **extra):
    """A client-month (month 13 = 2016-01) holding the given products."""
    year, m = (2015, month) if month <= 12 else (2016, month - 12)
    base = {
        "ncodpers": ncodpers,
        "fecha_dato": date(year, m, 28),
        "segmento": "02 - PARTICULARES",
        "sexo": "V",
        "age": 30,
        "antiguedad": 24,
        "renta": 80_000.0,
        "ind_actividad_cliente": 1,
        "ind_nuevo": 0,
        "nomprov": "MADRID",
    }
    products = {p: (1 if p in held else 0) for p in ga.PRODUCTS}
    return {**base, **products, **extra}


def collect(spark, table, rows):
    return ga.TABLES[table]["build"](silver(spark, rows)).collect()


# --- schema: script, JSON (Terraform) and Spark output agree -----------------

SPARK_TYPES = {"string": "string", "bigint": "bigint", "int": "int", "double": "double"}


def test_json_schema_matches_the_script():
    spec_json = json.loads((HERE / "gold_analytics_tables.json").read_text(encoding="utf-8"))
    assert sorted(spec_json) == sorted(ga.TABLES)
    for name, table in ga.TABLES.items():
        from_json = [{"name": c["name"], "type": c["type"]} for c in spec_json[name]["columns"]]
        assert from_json == table["columns"], name
        assert all(c.get("comment") for c in spec_json[name]["columns"]), name


@pytest.mark.parametrize("table", sorted(ga.TABLES))
def test_output_columns_and_types(spark, table):
    rows = [rec(1, 1), rec(1, 2, CCO), rec(1, 3, CCO, TJCR), rec(2, 2), rec(2, 3, AHOR)]
    df = ga.TABLES[table]["build"](silver(spark, rows))
    expected = [(c["name"], SPARK_TYPES[c["type"]]) for c in ga.TABLES[table]["columns"]]
    actual = [(f.name, f.dataType.simpleString()) for f in df.schema.fields]
    assert actual == expected + [("fecha_dato", "date")]
    assert df.count() > 0


# --- 1. product_monthly_kpis -------------------------------------------------


def kpis(spark, rows):
    return {(r["fecha_dato"].month, r["product"]): r for r in collect(spark, "product_monthly_kpis", rows)}


def test_kpis_holders_adds_and_drops(spark):
    rows = [
        rec(1, 1), rec(1, 2, CCO), rec(1, 3),               # adds CCO in Feb, drops it in Mar
        rec(2, 1, CCO), rec(2, 2, CCO), rec(2, 3, CCO, TJCR),  # always CCO, adds TJCR in Mar
        rec(3, 2),                                           # new in Feb: no previous month
    ]
    k = kpis(spark, rows)
    feb = k[(2, CCO)]
    assert feb["clients"] == 3 and feb["holders"] == 2
    assert feb["penetration_rate"] == pytest.approx(2 / 3)
    assert feb["eligible"] == 1 and feb["adds"] == 1 and feb["add_rate"] == 1.0
    assert feb["holders_prev"] == 1 and feb["drops"] == 0
    assert feb["product_name"] == "Cuenta corriente"

    mar = k[(3, CCO)]
    assert mar["eligible"] == 0 and mar["add_rate"] is None  # nobody could add it
    assert mar["holders_prev"] == 2 and mar["drops"] == 1 and mar["drop_rate"] == 0.5
    assert mar["net_adds"] == -1


def test_kpis_popularity_rank(spark):
    rows = [rec(1, 1), rec(1, 2, TJCR), rec(2, 1), rec(2, 2, TJCR), rec(3, 1), rec(3, 2, CCO)]
    k = kpis(spark, rows)
    assert k[(2, TJCR)]["popularity_rank"] == 1  # 2 adds
    assert k[(2, CCO)]["popularity_rank"] == 2  # 1 add
    assert k[(2, AHOR)]["popularity_rank"] == 3  # 0 adds: ties broken by name
    assert sorted(k[(2, p)]["popularity_rank"] for p in ga.PRODUCTS) == list(range(1, 25))
    assert k[(1, TJCR)]["popularity_rank"] is None  # first month: nothing to observe


def test_kpis_missing_product_counts_as_not_held(spark):
    rows = [rec(1, 1, **{CCO: None}), rec(1, 2, CCO)]
    feb = kpis(spark, rows)[(2, CCO)]
    assert feb["eligible"] == 1 and feb["adds"] == 1


# --- 2. customer_profile -----------------------------------------------------


def test_customer_profile_groups_and_averages(spark):
    rows = [
        rec(1, 1, CCO, renta=100_000.0, age=30),
        rec(2, 1, CCO, TJCR, renta=None, age=33, ind_actividad_cliente=0, ind_nuevo=1),
        rec(3, 1, age=None, segmento=None, renta=600_000.0),
    ]
    out = collect(spark, "customer_profile", rows)
    groups = {(r["segmento"], r["age_band"], r["income_band"]): r for r in out}

    with_income = groups[("02 - PARTICULARES", "25-34", "100-200k")]
    assert with_income["clients"] == 1 and with_income["avg_renta"] == 100_000.0

    no_income = groups[("02 - PARTICULARES", "25-34", "desconocido")]
    assert no_income["clients"] == 1
    assert no_income["avg_renta"] is None and no_income["renta_known"] == 0  # never imputed
    assert no_income["active_clients"] == 0 and no_income["active_rate"] == 0.0
    assert no_income["new_clients"] == 1 and no_income["avg_n_products"] == 2.0

    unknown = groups[("desconocido", "desconocido", "500k+")]
    assert unknown["avg_age"] is None and unknown["clients_without_products"] == 1


def test_bands_edges(spark):
    rows = [rec(i, 1, age=a) for i, a in enumerate([17, 18, 24, 25, 64, 65, 100])]
    by_band = {r["age_band"]: r["clients"] for r in collect(spark, "customer_profile", rows)}
    assert by_band == {"00-17": 1, "18-24": 2, "25-34": 1, "55-64": 1, "65+": 2}


# --- 3. product_penetration --------------------------------------------------


def test_penetration_by_dimension(spark):
    rows = [
        rec(1, 1, CCO, segmento="01 - TOP"),
        rec(2, 1, segmento="01 - TOP"),
        rec(3, 1, CCO, segmento="03 - UNIVERSITARIO", nomprov=None),
    ]
    out = collect(spark, "product_penetration", rows)
    cell = {(r["dimension"], r["dimension_value"], r["product"]): r for r in out}
    top = cell[("segmento", "01 - TOP", CCO)]
    assert top["clients"] == 2 and top["holders"] == 1 and top["penetration_rate"] == 0.5
    assert cell[("segmento", "03 - UNIVERSITARIO", CCO)]["penetration_rate"] == 1.0
    assert cell[("provincia", "desconocido", CCO)]["clients"] == 1
    assert cell[("actividad", "activo", CCO)]["clients"] == 3

    dims = {r["dimension"] for r in out}
    assert dims == {name for name, _ in ga.penetration_dimensions()}
    for d in dims:  # every dimension splits the same 3 clients
        assert sum(r["clients"] for r in out if r["dimension"] == d and r["product"] == CCO) == 3


# --- 4. product_affinity -----------------------------------------------------


def affinity(spark, rows):
    return {(r["product_a"], r["product_b"]): r for r in collect(spark, "product_affinity", rows)}


def test_affinity_independent_products(spark):
    rows = [rec(1, 1, CCO, TJCR), rec(2, 1, CCO), rec(3, 1, TJCR), rec(4, 1)]
    a = affinity(spark, rows)
    pair = a[(CCO, TJCR)]
    assert (pair["holders_a"], pair["holders_b"], pair["holders_both"]) == (2, 2, 1)
    assert pair["support"] == 0.25 and pair["confidence"] == 0.5
    assert pair["lift"] == pytest.approx(1.0) and pair["phi"] == pytest.approx(0.0)
    assert len(a) == 24 * 23  # ordered pairs, no diagonal


def test_affinity_perfectly_linked_and_directional(spark):
    a = affinity(spark, [rec(1, 1, CCO, TJCR), rec(2, 1, CCO, TJCR), rec(3, 1), rec(4, 1)])
    assert a[(CCO, TJCR)]["lift"] == pytest.approx(2.0)
    assert a[(CCO, TJCR)]["phi"] == pytest.approx(1.0)

    b = affinity(spark, [rec(1, 1, CCO, TJCR), rec(2, 1, CCO), rec(3, 1)])
    assert b[(CCO, TJCR)]["confidence"] == 0.5  # P(TJCR | CCO)
    assert b[(TJCR, CCO)]["confidence"] == 1.0  # P(CCO | TJCR)
    assert b[(CCO, AHOR)]["phi"] is None  # nobody holds AHOR: undefined


# --- 5. product_transitions --------------------------------------------------


def test_transitions_from_held_products_to_acquired(spark):
    rows = [
        rec(1, 1, CCO), rec(1, 2, CCO, TJCR),  # held CCO, acquired TJCR
        rec(2, 1), rec(2, 2, TJCR),            # held nothing, acquired TJCR
        rec(3, 2, TJCR),                       # no previous month: not a transition
    ]
    out = collect(spark, "product_transitions", rows)
    links = {(r["from_product"], r["to_product"]): r for r in out}
    assert set(links) == {(CCO, TJCR), (ga.NO_PRODUCTS, TJCR)}
    assert links[(CCO, TJCR)]["clients"] == 1
    assert links[(CCO, TJCR)]["to_product_adds"] == 2
    assert links[(CCO, TJCR)]["share"] == 0.5
    assert links[(ga.NO_PRODUCTS, TJCR)]["from_product_name"] == "Sin productos"
    assert all(r["from_product"] != r["to_product"] for r in out)


def test_transitions_count_each_held_product(spark):
    rows = [rec(1, 1, CCO, AHOR), rec(1, 2, CCO, AHOR, TJCR)]
    links = {(r["from_product"], r["to_product"]): r for r in collect(spark, "product_transitions", rows)}
    assert links[(CCO, TJCR)]["clients"] == 1 and links[(AHOR, TJCR)]["clients"] == 1
    assert links[(CCO, TJCR)]["to_product_adds"] == 1  # still one client adding TJCR


# --- 6. baseline_popularity --------------------------------------------------

BASELINE_ROWS = [
    rec(1, 1), rec(1, 2, TJCR), rec(1, 3, TJCR, CCO),  # Feb: adds TJCR; Mar: adds CCO
    rec(2, 1), rec(2, 2, TJCR), rec(2, 3, TJCR),       # Feb: adds TJCR; Mar: nothing
    rec(3, 1), rec(3, 2, CCO), rec(3, 3, CCO, AHOR),   # Feb: adds CCO;  Mar: adds AHOR
]


def baseline(spark, rows):
    return {r["fecha_dato"].month: r for r in collect(spark, "baseline_popularity", rows)}


def test_baseline_map_at_7(spark):
    b = baseline(spark, BASELINE_ROWS)
    feb = b[2]
    # Feb ranking: TJCR (2 adds), CCO (1), then the rest by name (AHOR first).
    assert feb["top_7_products"].split(",")[:3] == [TJCR, CCO, AHOR]
    assert len(feb["popularity_ranking"].split(",")) == 24
    assert feb["total_adds"] == 3 and feb["label_fecha_dato"] == "2015-03-28"
    # Client 1 holds TJCR -> recs [CCO, AHOR, ...]: CCO hit at 1 -> AP 1.
    # Client 2 adds nothing -> AP 0.
    # Client 3 holds CCO  -> recs [TJCR, AHOR, ...]: AHOR hit at 2 -> AP 1/2.
    assert feb["clients_evaluated"] == 3 and feb["clients_with_adds"] == 2
    assert feb["map_at_7"] == pytest.approx((1 + 0 + 0.5) / 3)
    assert feb["map_at_7_buyers"] == pytest.approx((1 + 0.5) / 2)
    assert feb["hit_rate_at_7_buyers"] == 1.0


def test_baseline_first_and_last_month(spark):
    b = baseline(spark, BASELINE_ROWS)
    assert b[1]["popularity_ranking"] is None and b[1]["map_at_7"] is None  # no adds observable
    assert b[1]["clients_evaluated"] == 0
    last = b[3]  # no April: ranking exists (for real recommendations), no score
    assert last["top_7_products"].split(",")[:2] == [AHOR, CCO]  # 1 add each, by name
    assert last["map_at_7"] is None and last["clients_evaluated"] == 0


def test_baseline_ranking_ignores_the_future(spark):
    spike = [rec(i, 2) for i in range(10, 20)] + [rec(i, 3, AHOR) for i in range(10, 20)]
    before = baseline(spark, BASELINE_ROWS)[2]["popularity_ranking"]
    after = baseline(spark, BASELINE_ROWS + spike)[2]["popularity_ranking"]
    assert before == after


def test_average_precision_formula(spark):
    df = spark.createDataFrame(
        [(["a", "x", "b"], ["a", "b"]), (["x", "y"], ["a"]), (["a"], [])],
        "recs array<string>, actual array<string>",
    )
    ap, hit = ga.average_precision(F.col("recs"), F.col("actual"))
    got = [(r["ap"], r["hit"]) for r in df.select(ap.alias("ap"), hit.alias("hit")).collect()]
    assert got[0][0] == pytest.approx((1 / 1 + 2 / 3) / 2) and got[0][1] is True
    assert got[1] == (0.0, False)
    assert got[2][0] == 0.0  # no actual adds: AP is 0 (Kaggle)
