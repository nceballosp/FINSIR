"""Shared test fixtures: a fake repository and a TestClient (no AWS)."""

from __future__ import annotations

from typing import Optional

import jwt
import pytest
from fastapi.testclient import TestClient

from app.adapters.driving.http.app_factory import create_app
from app.config import Settings
from app.container import build_container_from_repository
from app.domain.entities import ClientRecord, MonthPage
from app.domain.errors import InvalidQueryError, RepositoryError
from app.use_cases.ports import SilverRepository

DEV_SECRET = "test-secret-not-a-real-credential"
AUDIENCE = "finsir-clients"
ISSUER = "finsir-tests"
REQUIRED_SCOPE = "silver:read"


class FakeSilverRepository(SilverRepository):
    """In-memory repository for tests. Optionally raises to exercise errors."""

    def __init__(
        self,
        records_by_client: Optional[dict[int, list[ClientRecord]]] = None,
        records_by_month: Optional[dict[str, list[ClientRecord]]] = None,
        should_raise_repository_error: bool = False,
    ) -> None:
        self._records_by_client = records_by_client or {}
        self._records_by_month = records_by_month or {}
        self._should_raise_repository_error = should_raise_repository_error

    def get_client_records(self, ncodpers: int) -> list[ClientRecord]:
        self._maybe_raise()
        if not isinstance(ncodpers, int) or isinstance(ncodpers, bool):
            raise InvalidQueryError("ncodpers must be an integer")
        return list(self._records_by_client.get(ncodpers, []))

    def get_client_latest(self, ncodpers: int) -> Optional[ClientRecord]:
        self._maybe_raise()
        records = self._records_by_client.get(ncodpers, [])
        if not records:
            return None
        return sorted(records, key=lambda record: record.fecha_dato or "")[-1]

    def list_by_month(
        self,
        fecha_dato: str,
        page: int,
        size: int,
        sort: Optional[str] = None,
    ) -> MonthPage:
        self._maybe_raise()
        all_records = self._records_by_month.get(fecha_dato, [])
        start = (page - 1) * size
        items = all_records[start : start + size]
        return MonthPage(items=items, page=page, size=size, total=len(all_records))

    def _maybe_raise(self) -> None:
        if self._should_raise_repository_error:
            raise RepositoryError("Simulated infrastructure failure")


def make_client_record(ncodpers: int, fecha_dato: str, **values) -> ClientRecord:
    """Build a :class:`ClientRecord` for tests; unset columns stay absent."""
    return ClientRecord(ncodpers=ncodpers, fecha_dato=fecha_dato, values=dict(values))


@pytest.fixture
def dev_settings() -> Settings:
    """Settings in dev auth mode with required Athena/auth values present."""
    return Settings(
        ATHENA_DATABASE="finsir",
        ATHENA_WORKGROUP="finsir",
        ATHENA_OUTPUT="s3://finsir-bucket/athena-results/",
        IS_AUTH_DEV_MODE=True,
        AUTH_DEV_SECRET=DEV_SECRET,
        AUTH_AUDIENCE=AUDIENCE,
        AUTH_ISSUER=ISSUER,
        AUTH_REQUIRED_SCOPE=REQUIRED_SCOPE,
        _env_file=None,
    )


@pytest.fixture
def fake_repository() -> FakeSilverRepository:
    """A fake repository seeded with one client and one month."""
    record_jan = make_client_record(1, "2015-01-28", sexo="V", age="35")
    record_feb = make_client_record(1, "2015-02-28", sexo="V", age=None)
    return FakeSilverRepository(
        records_by_client={1: [record_jan, record_feb]},
        records_by_month={
            "2015-01-28": [record_jan, make_client_record(2, "2015-01-28")]
        },
    )


def _make_token(scope: str = REQUIRED_SCOPE, audience: str = AUDIENCE) -> str:
    return jwt.encode(
        {"sub": "tester", "scope": scope, "aud": audience, "iss": ISSUER},
        DEV_SECRET,
        algorithm="HS256",
    )


@pytest.fixture
def valid_token() -> str:
    """A valid bearer token with the required scope."""
    return _make_token()


@pytest.fixture
def token_without_scope() -> str:
    """A valid token lacking the required scope (drives 403)."""
    return _make_token(scope="other:scope")


@pytest.fixture
def build_test_client(dev_settings: Settings):
    """Factory building a TestClient around a given repository."""

    def _build(repository: SilverRepository) -> TestClient:
        container = build_container_from_repository(repository)
        app = create_app(settings=dev_settings, container=container)
        return TestClient(app)

    return _build


@pytest.fixture
def client(build_test_client, fake_repository) -> TestClient:
    """A TestClient wired to the seeded fake repository."""
    return build_test_client(fake_repository)
