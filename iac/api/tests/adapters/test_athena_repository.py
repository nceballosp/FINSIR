"""Athena adapter tests using a fake boto3 client (no real AWS)."""

from __future__ import annotations

import pytest
from botocore.exceptions import ClientError

from app.adapters.driven.athena.athena_silver_repository import (
    AthenaSilverRepository,
)
from app.domain.errors import InvalidQueryError, RepositoryError


class FakeAthenaClient:
    """Minimal boto3 Athena stand-in returning scripted results."""

    def __init__(self, rows, state="SUCCEEDED", raise_on_start=False):
        self._rows = rows
        self._state = state
        self._raise_on_start = raise_on_start
        self.last_query = None

    def start_query_execution(self, **kwargs):
        self.last_query = kwargs["QueryString"]
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
        return {"ResultSet": {"Rows": self._rows}}


def _rows_from(header, *data_rows):
    def _cells(values):
        return {"Data": [{"VarCharValue": value} if value is not None else {} for value in values]}

    return [_cells(header), *[_cells(row) for row in data_rows]]


def _make_repository(client) -> AthenaSilverRepository:
    return AthenaSilverRepository(
        athena_client=client,
        database="finsir",
        workgroup="finsir",
        output_location="s3://bucket/athena-results/",
        table="silver_train",
        poll_interval_seconds=0,
        max_poll_attempts=3,
    )


def test_get_client_records_maps_rows_and_preserves_null():
    rows = _rows_from(["ncodpers", "fecha_dato", "sexo"], ["1", "2015-01-28", None])
    repo = _make_repository(FakeAthenaClient(rows))
    records = repo.get_client_records(1)
    assert len(records) == 1
    assert records[0].ncodpers == 1
    assert records[0].get("sexo") is None


def test_get_client_latest_returns_none_when_no_rows():
    rows = _rows_from(["ncodpers", "fecha_dato"])
    repo = _make_repository(FakeAthenaClient(rows))
    assert repo.get_client_latest(1) is None


def test_list_by_month_builds_page_with_count():
    count_rows = _rows_from(["total"], ["2"])
    data_rows = _rows_from(
        ["ncodpers", "fecha_dato"], ["1", "2015-01-28"], ["2", "2015-01-28"]
    )

    class SequencedClient(FakeAthenaClient):
        def __init__(self):
            super().__init__(rows=[])
            self._responses = [count_rows, data_rows]
            self._index = 0

        def get_query_results(self, **_):
            response = {"ResultSet": {"Rows": self._responses[self._index]}}
            self._index += 1
            return response

    repo = _make_repository(SequencedClient())
    page = repo.list_by_month("2015-01-28", page=1, size=10)
    assert page.total == 2
    assert len(page.items) == 2


def test_validation_rejects_sql_injection_in_ncodpers():
    repo = _make_repository(FakeAthenaClient(rows=[]))
    with pytest.raises(InvalidQueryError):
        repo.get_client_records("1 OR 1=1")  # type: ignore[arg-type]


def test_validation_rejects_bad_fecha_dato():
    repo = _make_repository(FakeAthenaClient(rows=[]))
    with pytest.raises(InvalidQueryError):
        repo.list_by_month("not-a-date", page=1, size=10)


def test_validation_rejects_unknown_sort_column():
    repo = _make_repository(FakeAthenaClient(rows=[]))
    with pytest.raises(InvalidQueryError):
        repo.list_by_month("2015-01-28", page=1, size=10, sort="; DROP TABLE")


def test_client_error_is_translated_to_repository_error():
    repo = _make_repository(FakeAthenaClient(rows=[], raise_on_start=True))
    with pytest.raises(RepositoryError):
        repo.get_client_records(1)


def test_failed_query_state_is_translated_to_repository_error():
    rows = _rows_from(["ncodpers"])
    repo = _make_repository(FakeAthenaClient(rows, state="FAILED"))
    with pytest.raises(RepositoryError):
        repo.get_client_records(1)


def test_timeout_raises_repository_error():
    rows = _rows_from(["ncodpers"])
    repo = _make_repository(FakeAthenaClient(rows, state="RUNNING"))
    with pytest.raises(RepositoryError):
        repo.get_client_records(1)


def test_negative_ncodpers_rejected():
    repo = _make_repository(FakeAthenaClient(rows=[]))
    with pytest.raises(InvalidQueryError):
        repo.get_client_records(-5)
