"""Analytics Athena adapter tests using a fake boto3 client (no real AWS)."""

from __future__ import annotations

import pytest
from botocore.exceptions import ClientError

from app.adapters.driven.athena.athena_gold_analytics_repository import (
    AthenaGoldAnalyticsRepository,
)
from app.domain.errors import InvalidQueryError, RepositoryError


class FakeAthenaClient:
    """Minimal boto3 Athena stand-in returning scripted results in order."""

    def __init__(self, responses, state="SUCCEEDED", raise_on_start=False):
        self._responses = responses
        self._state = state
        self._raise_on_start = raise_on_start
        self._index = 0
        self.queries = []

    def start_query_execution(self, **kwargs):
        self.queries.append(kwargs["QueryString"])
        if self._raise_on_start:
            raise ClientError(
                {"Error": {"Code": "AccessDenied", "Message": "denied"}},
                "StartQueryExecution",
            )
        return {"QueryExecutionId": "exec-1"}

    def get_query_execution(self, **_):
        return {
            "QueryExecution": {
                "Status": {"State": self._state, "StateChangeReason": "boom"}
            }
        }

    def get_query_results(self, **_):
        response = {"ResultSet": {"Rows": self._responses[self._index]}}
        self._index += 1
        return response


def _rows_from(header, *data_rows):
    def _cells(values):
        return {
            "Data": [
                {"VarCharValue": value} if value is not None else {} for value in values
            ]
        }

    return [_cells(header), *[_cells(row) for row in data_rows]]


def _make_repository(client) -> AthenaGoldAnalyticsRepository:
    return AthenaGoldAnalyticsRepository(
        athena_client=client,
        database="finsir",
        workgroup="finsir",
        output_location="s3://bucket/athena-results/",
        table_prefix="gold_",
        poll_interval_seconds=0,
        max_poll_attempts=3,
    )


def test_unknown_table_key_raises_invalid_query():
    repo = _make_repository(FakeAthenaClient([]))
    with pytest.raises(InvalidQueryError):
        repo.list_by_month("does_not_exist", "2016-04-28", page=1, size=10)


def test_bad_fecha_dato_raises_invalid_query():
    repo = _make_repository(FakeAthenaClient([]))
    with pytest.raises(InvalidQueryError):
        repo.list_by_month("product_monthly_kpis", "not-a-date", page=1, size=10)


def test_unknown_sort_column_raises_invalid_query():
    repo = _make_repository(FakeAthenaClient([]))
    with pytest.raises(InvalidQueryError):
        repo.list_by_month(
            "product_monthly_kpis", "2016-04-28", page=1, size=10, sort="; DROP"
        )


def test_unknown_filter_name_raises_invalid_query():
    repo = _make_repository(FakeAthenaClient([]))
    with pytest.raises(InvalidQueryError):
        repo.list_by_month(
            "product_monthly_kpis",
            "2016-04-28",
            page=1,
            size=10,
            filters={"segmento": "x"},
        )


def test_filter_value_failing_literal_pattern_raises_invalid_query():
    repo = _make_repository(FakeAthenaClient([]))
    with pytest.raises(InvalidQueryError):
        repo.list_by_month(
            "product_monthly_kpis",
            "2016-04-28",
            page=1,
            size=10,
            filters={"product": "x'; DROP TABLE t; --"},
        )


def test_happy_path_builds_qualified_table_filter_and_pagination():
    count_rows = _rows_from(["total"], ["2"])
    data_rows = _rows_from(
        ["fecha_dato", "product"],
        ["2016-04-28", "ind_cco_fin_ult1"],
    )
    client = FakeAthenaClient([count_rows, data_rows])
    repo = _make_repository(client)
    page = repo.list_by_month(
        "product_monthly_kpis",
        "2016-04-28",
        page=2,
        size=3,
        sort="popularity_rank",
        filters={"product": "ind_cco_fin_ult1"},
    )
    page_query = client.queries[-1]
    assert '"finsir"."gold_product_monthly_kpis"' in page_query
    assert "fecha_dato = '2016-04-28'" in page_query
    assert "AND product = 'ind_cco_fin_ult1'" in page_query
    assert "ORDER BY popularity_rank" in page_query
    assert "OFFSET 3 LIMIT 3" in page_query
    assert "LIMIT 3 OFFSET" not in page_query
    assert page.total == 2
    assert page.items[0].get("product") == "ind_cco_fin_ult1"


def test_count_filter_is_applied_in_count_query():
    client = FakeAthenaClient([_rows_from(["total"], ["0"]), _rows_from(["fecha_dato"])])
    _make_repository(client).list_by_month(
        "product_monthly_kpis",
        "2016-04-28",
        page=1,
        size=10,
        filters={"product": "ind_cco_fin_ult1"},
    )
    count_query = client.queries[0]
    assert "COUNT(*)" in count_query
    assert "AND product = 'ind_cco_fin_ult1'" in count_query


def test_client_error_is_translated_to_repository_error():
    repo = _make_repository(FakeAthenaClient([], raise_on_start=True))
    with pytest.raises(RepositoryError):
        repo.list_by_month("baseline_popularity", "2016-04-28", page=1, size=10)


def test_failed_query_state_is_translated_to_repository_error():
    client = FakeAthenaClient([_rows_from(["total"])], state="FAILED")
    repo = _make_repository(client)
    with pytest.raises(RepositoryError):
        repo.list_by_month("baseline_popularity", "2016-04-28", page=1, size=10)


def test_timeout_raises_repository_error():
    client = FakeAthenaClient([_rows_from(["total"])], state="RUNNING")
    repo = _make_repository(client)
    with pytest.raises(RepositoryError):
        repo.list_by_month("baseline_popularity", "2016-04-28", page=1, size=10)


def test_empty_count_rows_yield_zero_total():
    client = FakeAthenaClient([[], _rows_from(["fecha_dato"])])
    page = _make_repository(client).list_by_month(
        "baseline_popularity", "2016-04-28", page=1, size=10
    )
    assert page.total == 0
