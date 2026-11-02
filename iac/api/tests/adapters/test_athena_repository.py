"""Athena adapter tests using a fake boto3 client (no real AWS)."""

from __future__ import annotations

import pytest
from botocore.exceptions import ClientError

from app.adapters.driven.athena.athena_gold_train_repository import (
    AthenaGoldTrainRepository,
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
        return {
            "Data": [
                {"VarCharValue": value} if value is not None else {} for value in values
            ]
        }

    return [_cells(header), *[_cells(row) for row in data_rows]]


def _make_repository(client) -> AthenaGoldTrainRepository:
    return AthenaGoldTrainRepository(
        athena_client=client,
        database="finsir",
        workgroup="finsir",
        output_location="s3://bucket/athena-results/",
        table="gold_train",
        poll_interval_seconds=0,
        max_poll_attempts=3,
    )


def test_get_client_records_maps_rows_and_preserves_null():
    rows = _rows_from(
        ["ncodpers", "fecha_dato", "sexo", "label_next_ind_cco_fin_ult1"],
        ["1", "2015-01-28", None, "1"],
    )
    client = FakeAthenaClient(rows)
    repo = _make_repository(client)
    records = repo.get_client_records(1)
    assert len(records) == 1
    assert records[0].ncodpers == 1
    assert records[0].get("sexo") is None
    assert records[0].get("label_next_ind_cco_fin_ult1") == "1"
    assert '"finsir"."gold_train"' in client.last_query


def test_month_filter_compares_the_string_partition():
    client = FakeAthenaClient(_rows_from(["total"], ["0"]))
    _make_repository(client).list_by_month("2016-05-28", page=1, size=10)
    assert "fecha_dato = '2016-05-28'" in client.last_query
    assert "DATE '" not in client.last_query


class SequencedClient(FakeAthenaClient):
    """Returns scripted results in order and records every query run."""

    def __init__(self, responses):
        super().__init__(rows=[])
        self._responses = responses
        self._index = 0
        self.queries = []

    def start_query_execution(self, **kwargs):
        self.queries.append(kwargs["QueryString"])
        return super().start_query_execution(**kwargs)

    def get_query_results(self, **_):
        response = {"ResultSet": {"Rows": self._responses[self._index]}}
        self._index += 1
        return response


def test_list_by_month_builds_page_with_count():
    count_rows = _rows_from(["total"], ["2"])
    data_rows = _rows_from(
        ["ncodpers", "fecha_dato"], ["1", "2015-01-28"], ["2", "2015-01-28"]
    )
    repo = _make_repository(SequencedClient([count_rows, data_rows]))
    page = repo.list_by_month("2015-01-28", page=1, size=10)
    assert page.total == 2
    assert len(page.items) == 2


def test_month_page_query_puts_offset_before_limit():
    # Athena (Trino) rejects "LIMIT n OFFSET m"; OFFSET must come first.
    client = SequencedClient([_rows_from(["total"], ["5"]), _rows_from(["ncodpers"])])
    _make_repository(client).list_by_month("2016-04-28", page=2, size=3)
    page_query = client.queries[-1]
    assert "OFFSET 3 LIMIT 3" in page_query
    assert "LIMIT 3 OFFSET" not in page_query


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
