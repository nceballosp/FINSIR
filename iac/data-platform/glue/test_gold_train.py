"""Tests for the gold training table, with local Spark.

pip install pyspark pytest
python -m pytest glue
"""

import importlib.util
import os
import sys
from datetime import date
from pathlib import Path

import pytest
from pyspark.sql import SparkSession
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

path = Path(__file__).parent / "gold_train.py"
spec = importlib.util.spec_from_file_location("gold_train", path)
gt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gt)

INT_PROFILE = {
    "age",
    "antiguedad",
    "ind_nuevo",
    "indrel",
    "cod_prov",
    "ind_actividad_cliente",
}


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


def silver(spark, rows):
    """Silver-shaped rows: the columns gold reads, plus one it must drop."""
    fields = [
        StructField("ncodpers", LongType()),
        StructField("fecha_dato", DateType()),
    ]
    for c in gt.PROFILE_COLUMNS:
        kind = (
            IntegerType()
            if c in INT_PROFILE
            else DoubleType()
            if c == "renta"
            else StringType()
        )
        fields.append(StructField(c, kind))
    fields += [StructField(p, IntegerType()) for p in gt.PRODUCTS]
    fields.append(StructField("nomprov", StringType()))
    schema = StructType(fields)
    return spark.createDataFrame(
        [tuple(r.get(f.name) for f in fields) for r in rows], schema
    )


def row(ncodpers, month, **products):
    """A client in a 2015/2016 month (month 13 = 2016-01); products default to 0."""
    year, m = (2015, month) if month <= 12 else (2016, month - 12)
    base = {
        "ncodpers": ncodpers,
        "fecha_dato": date(year, m, 28),
        "age": 30,
        "nomprov": "MADRID",
    }
    return {**base, **{p: 0 for p in gt.PRODUCTS}, **products}


def build(spark, rows):
    out = gt.build_gold(silver(spark, rows)).collect()
    return {
        (r["ncodpers"], r["fecha_dato"].month + 12 * (r["fecha_dato"].year - 2015)): r
        for r in out
    }


CCO = "ind_cco_fin_ult1"
TJCR = "ind_tjcr_fin_ult1"


def test_keeps_every_row_and_the_documented_columns(spark):
    rows = [row(1, 1), row(1, 2), row(2, 5)]
    gold = gt.build_gold(silver(spark, rows))
    assert gold.count() == len(rows)
    assert gold.columns == gt.gold_columns() + ["fecha_dato"]
    assert "nomprov" not in gold.columns
    assert len(gold.columns) == 169


def test_label_is_an_addition_in_the_next_month(spark):
    g = build(spark, [row(1, 1), row(1, 2, **{CCO: 1}), row(1, 3, **{CCO: 1})])
    assert g[(1, 1)][gt.label_column(CCO)] == 1  # 0 in Jan -> 1 in Feb
    assert g[(1, 1)]["label_next_n_added"] == 1
    assert g[(1, 2)][gt.label_column(CCO)] == 0  # already held: not new
    assert g[(1, 3)][gt.label_column(CCO)] is None  # no next month: unknown
    assert g[(1, 3)]["label_next_n_added"] is None


def test_added_flag_marks_the_month_a_product_starts(spark):
    g = build(spark, [row(1, 1), row(1, 2, **{CCO: 1}), row(1, 3, **{CCO: 1})])
    assert g[(1, 1)][gt.added_column(CCO)] is None  # no previous month
    assert g[(1, 2)][gt.added_column(CCO)] == 1  # 0 in Jan -> 1 in Feb
    assert g[(1, 2)]["n_products_added"] == 1
    assert g[(1, 3)][gt.added_column(CCO)] == 0  # already held in Feb
    # added_ is this month; label_next_ is next month: they must differ in Jan
    assert (
        g[(1, 1)][gt.label_column(CCO)] == 1 and g[(1, 1)][gt.added_column(CCO)] is None
    )


def test_a_skipped_month_gives_null_not_an_older_value(spark):
    g = build(spark, [row(1, 1, **{CCO: 1}), row(1, 3)])
    assert g[(1, 1)][gt.label_column(CCO)] is None  # February is missing
    assert g[(1, 3)][gt.lag_column(CCO, 1)] is None
    assert g[(1, 3)]["has_previous_month"] == 0
    assert g[(1, 3)]["n_products_added"] is None
    assert g[(1, 3)][gt.added_column(CCO)] is None


def test_lags_counts_and_month_of_year(spark):
    rows = [
        row(1, m, **{CCO: 1 if m in (1, 6) else 0, TJCR: 1 if m == 7 else 0})
        for m in range(1, 8)
    ]
    g = build(spark, rows)
    july = g[(1, 7)]
    assert july[gt.lag_column(CCO, 1)] == 1  # June
    assert july[gt.lag_column(CCO, 3)] == 0  # April
    assert july[gt.lag_column(CCO, 6)] == 1  # January
    assert july["n_products"] == 1
    assert july["n_products_added"] == 1 and july["n_products_dropped"] == 1
    assert july["month_of_year"] == 7


def test_a_missing_product_counts_as_not_held(spark):
    g = build(spark, [row(1, 1, **{CCO: None}), row(1, 2, **{CCO: 1})])
    assert g[(1, 1)][CCO] is None  # the silver value is kept
    assert g[(1, 1)][gt.label_column(CCO)] == 1


def test_features_do_not_depend_on_the_future(spark):
    past = [row(1, 1), row(1, 2, **{CCO: 1})]
    without_future = build(spark, past)[(1, 2)]
    with_future = build(spark, past + [row(1, 3, **{TJCR: 1}, age=99)])[(1, 2)]
    features = [c for c in gt.gold_columns() if not c.startswith(gt.LABEL_PREFIX)]
    assert [without_future[c] for c in features] == [with_future[c] for c in features]
    assert with_future[gt.label_column(TJCR)] == 1


def test_api_column_list_matches_the_job():
    entities_path = Path(__file__).parents[2] / "api" / "app" / "domain" / "entities.py"
    api_spec = importlib.util.spec_from_file_location("api_entities", entities_path)
    api = importlib.util.module_from_spec(api_spec)
    sys.modules["api_entities"] = api  # dataclasses needs the module registered
    api_spec.loader.exec_module(api)
    assert list(api.GOLD_TRAIN_COLUMN_NAMES) == gt.gold_columns() + ["fecha_dato"]
