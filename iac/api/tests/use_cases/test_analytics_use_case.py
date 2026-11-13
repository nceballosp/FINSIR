"""Use-case tests for ListAnalyticsMonth with a fake repository (no AWS)."""

from __future__ import annotations

from app.use_cases.list_analytics_month import ListAnalyticsMonth
from tests.conftest import FakeGoldAnalyticsRepository, make_gold_row


def _seeded_repository() -> FakeGoldAnalyticsRepository:
    return FakeGoldAnalyticsRepository(
        records_by_table_month={
            ("product_monthly_kpis", "2016-04-28"): [
                make_gold_row("2016-04-28", product="ind_cco_fin_ult1"),
                make_gold_row("2016-04-28", product="ind_recibo_ult1"),
            ],
        }
    )


def test_paginates_and_reports_total():
    use_case = ListAnalyticsMonth(_seeded_repository())
    page = use_case.execute("product_monthly_kpis", "2016-04-28", page=1, size=1)
    assert page.total == 2
    assert len(page.items) == 1
    assert page.has_next_page is True


def test_filters_are_passed_through():
    use_case = ListAnalyticsMonth(_seeded_repository())
    page = use_case.execute(
        "product_monthly_kpis",
        "2016-04-28",
        page=1,
        size=10,
        sort=None,
        filters={"product": "ind_recibo_ult1"},
    )
    assert page.total == 1
    assert page.items[0].get("product") == "ind_recibo_ult1"


def test_empty_month_returns_zero_total():
    use_case = ListAnalyticsMonth(_seeded_repository())
    page = use_case.execute("product_monthly_kpis", "2099-01-28", page=1, size=10)
    assert page.total == 0
    assert page.items == []
