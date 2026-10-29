"""Use-case tests with a fake repository (no AWS)."""

from __future__ import annotations

import pytest

from app.domain.errors import ClientNotFoundError
from app.use_cases.get_client_latest import GetClientLatest
from app.use_cases.get_client_records import GetClientRecords
from app.use_cases.list_month import ListMonth
from tests.conftest import FakeSilverRepository, make_client_record


def _seeded_repository() -> FakeSilverRepository:
    jan = make_client_record(1, "2015-01-28")
    feb = make_client_record(1, "2015-02-28")
    return FakeSilverRepository(
        records_by_client={1: [jan, feb]},
        records_by_month={"2015-01-28": [jan, make_client_record(2, "2015-01-28")]},
    )


def test_get_client_records_returns_all_records():
    use_case = GetClientRecords(_seeded_repository())
    records = use_case.execute(1)
    assert len(records) == 2


def test_get_client_records_raises_not_found_for_unknown_client():
    use_case = GetClientRecords(_seeded_repository())
    with pytest.raises(ClientNotFoundError):
        use_case.execute(999)


def test_get_client_latest_returns_most_recent():
    use_case = GetClientLatest(_seeded_repository())
    record = use_case.execute(1)
    assert record.fecha_dato == "2015-02-28"


def test_get_client_latest_raises_not_found_when_none():
    use_case = GetClientLatest(_seeded_repository())
    with pytest.raises(ClientNotFoundError):
        use_case.execute(999)


def test_list_month_paginates():
    use_case = ListMonth(_seeded_repository())
    page = use_case.execute("2015-01-28", page=1, size=1)
    assert page.total == 2
    assert len(page.items) == 1
    assert page.has_next_page is True


def test_list_month_empty_for_unknown_month():
    use_case = ListMonth(_seeded_repository())
    page = use_case.execute("2099-01-28", page=1, size=10)
    assert page.total == 0
    assert page.items == []
