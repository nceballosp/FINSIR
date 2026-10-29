"""Domain entity tests: null preservation and page helpers."""

from __future__ import annotations

from app.domain.entities import SILVER_COLUMN_NAMES, ClientRecord, MonthPage
from app.domain.errors import (
    ClientNotFoundError,
    DomainError,
    InvalidQueryError,
    RepositoryError,
)


def test_as_dict_preserves_nulls_and_schema_order():
    record = ClientRecord(ncodpers=1, fecha_dato="2015-01-28", values={"sexo": None})
    flat = record.as_dict()
    assert list(flat.keys()) == list(SILVER_COLUMN_NAMES)
    assert flat["sexo"] is None
    assert flat["ncodpers"] == 1
    assert flat["fecha_dato"] == "2015-01-28"


def test_get_returns_none_for_absent_column_without_fabricating():
    record = ClientRecord(ncodpers=1, fecha_dato="2015-01-28", values={})
    assert record.get("renta") is None
    assert record.get("ncodpers") == 1
    assert record.get("fecha_dato") == "2015-01-28"


def test_month_page_has_next_page_true_when_more_remain():
    page = MonthPage(items=[], page=1, size=10, total=25)
    assert page.has_next_page is True


def test_month_page_has_next_page_false_on_last_page():
    page = MonthPage(items=[], page=3, size=10, total=25)
    assert page.has_next_page is False


def test_domain_error_hierarchy():
    assert issubclass(ClientNotFoundError, DomainError)
    assert issubclass(InvalidQueryError, DomainError)
    assert issubclass(RepositoryError, DomainError)


def test_client_not_found_error_carries_identifier():
    error = ClientNotFoundError(42)
    assert error.ncodpers == 42
    assert "42" in str(error)
