"""Domain tests for the analytical gold entities and registry."""

from __future__ import annotations

from app.domain.entities import (
    ANALYTICS_TABLES,
    EXPECTED_ANALYTICS_TABLE_COUNT,
    GoldRow,
    GoldTablePage,
)


def test_gold_row_preserves_nulls_and_column_order():
    row = GoldRow(fecha_dato="2016-04-28", values={"product": "ind_cco", "adds": None})
    flat = row.as_dict(("fecha_dato", "product", "adds"))
    assert list(flat.keys()) == ["fecha_dato", "product", "adds"]
    assert flat["fecha_dato"] == "2016-04-28"
    assert flat["product"] == "ind_cco"
    assert flat["adds"] is None


def test_gold_row_get_returns_none_for_absent_column():
    row = GoldRow(fecha_dato="2016-04-28", values={})
    assert row.get("holders") is None
    assert row.get("fecha_dato") == "2016-04-28"


def test_gold_table_page_has_next_page_true_when_more_remain():
    page = GoldTablePage(items=[], page=1, size=10, total=25)
    assert page.has_next_page is True


def test_gold_table_page_has_next_page_false_on_last_page():
    page = GoldTablePage(items=[], page=3, size=10, total=25)
    assert page.has_next_page is False


def test_registry_has_expected_count():
    assert len(ANALYTICS_TABLES) == EXPECTED_ANALYTICS_TABLE_COUNT


def test_registry_tables_have_columns_and_valid_filters():
    for table in ANALYTICS_TABLES.values():
        assert table.columns, f"{table.key} has no columns"
        for filter_column in table.filter_columns:
            assert filter_column in table.columns


def test_registry_sortable_columns_include_fecha_dato():
    table = ANALYTICS_TABLES["product_monthly_kpis"]
    assert "fecha_dato" in table.sortable_columns
    assert "product" in table.sortable_columns
