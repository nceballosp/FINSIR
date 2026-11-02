"""Tests for the gold segment conversion table, with local Spark.

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
    IntegerType,
    LongType,
    StringType,
    StructField,
    StructType,
)

os.environ.setdefault("PYSPARK_PYTHON", sys.executable)

path = Path(__file__).parent / "gold_segment_conversion.py"
spec = importlib.util.spec_from_file_location("gold_segment_conversion", path)
gc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gc)

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


def silver(spark, rows):
    fields = [
        StructField("ncodpers", LongType()),
        StructField("fecha_dato", DateType()),
        StructField("segmento", StringType()),
    ]
    fields += [StructField(p, IntegerType()) for p in gc.PRODUCTS]
    schema = StructType(fields)
    return spark.createDataFrame(
        [tuple(r.get(f.name) for f in fields) for r in rows], schema
    )


def rec(ncodpers, month, segmento="02", **products):
    year, m = (2015, month) if month <= 12 else (2016, month - 12)
    base = {"ncodpers": ncodpers, "fecha_dato": date(year, m, 28), "segmento": segmento}
    return {**base, **{p: 0 for p in gc.PRODUCTS}, **products}


def build(spark, rows):
    out = gc.build_conversion(silver(spark, rows)).collect()
    return {
        (r["segmento"], r["product"], r["fecha_dato"].month): r
        for r in out
        if r["product"] in (CCO, TJCR)
    }


def test_rate_only_uses_months_before(spark):
    # Client 1: eligible in Feb (no CCO in Jan), adopts CCO in Feb.
    # Client 2: eligible in Feb, does not adopt. So before March: 2 eligible, 1 adopt.
    rows = [
        rec(1, 1), rec(1, 2, **{CCO: 1}), rec(1, 3, **{CCO: 1}),
        rec(2, 1), rec(2, 2), rec(2, 3, **{CCO: 1}),
    ]
    g = build(spark, rows)
    jan = g[("02", CCO, 1)]
    assert jan["eligible"] == 0 and jan["conversion_rate"] is None  # nothing before Jan
    march = g[("02", CCO, 3)]
    assert march["eligible"] == 2 and march["adopters"] == 1
    assert march["conversion_rate"] == 0.5


def test_rate_never_sees_its_own_month(spark):
    # A huge adoption in March must not change the March rate (only Feb counts).
    base = [rec(1, 1), rec(1, 2, **{CCO: 1}), rec(2, 1), rec(2, 2)]
    without = build(spark, base + [rec(1, 3), rec(2, 3)])
    spike = [rec(i, 1) for i in range(10, 20)] + [rec(i, 3, **{CCO: 1}) for i in range(10, 20)]
    with_spike = build(spark, base + [rec(1, 3), rec(2, 3)] + spike)
    assert without[("02", CCO, 3)]["conversion_rate"] == with_spike[("02", CCO, 3)]["conversion_rate"]


def test_segments_are_separate(spark):
    rows = [
        rec(1, 1, "01"), rec(1, 2, "01", **{CCO: 1}),
        rec(2, 1, "03"), rec(2, 2, "03"),
        rec(1, 3, "01"), rec(2, 3, "03"),
    ]
    g = build(spark, rows)
    assert g[("01", CCO, 3)]["conversion_rate"] == 1.0  # the one eligible adopted
    assert g[("03", CCO, 3)]["conversion_rate"] == 0.0  # eligible, never adopted


def test_rows_without_segment_are_dropped(spark):
    out = gc.build_conversion(silver(spark, [rec(1, 1, None), rec(1, 2, None, **{CCO: 1})]))
    assert out.where(out.segmento.isNull()).count() == 0
