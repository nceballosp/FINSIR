"""HTTP endpoint tests via TestClient with a fake repository (no AWS)."""

from __future__ import annotations

from app.adapters.driving.http.correlation import CORRELATION_ID_HEADER
from tests.conftest import FakeSilverRepository


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_health_is_open_and_ok(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_get_client_records_happy_path(client, valid_token):
    response = client.get("/v1/clients/1", headers=_auth(valid_token))
    assert response.status_code == 200
    body = response.json()
    assert len(body["data"]) == 2
    assert body["data"][0]["ncodpers"] == 1


def test_get_client_latest_happy_path(client, valid_token):
    response = client.get("/v1/clients/1/latest", headers=_auth(valid_token))
    assert response.status_code == 200
    assert response.json()["data"]["fecha_dato"] == "2015-02-28"


def test_get_client_records_not_found(client, valid_token):
    response = client.get("/v1/clients/999", headers=_auth(valid_token))
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "client_not_found"


def test_month_listing_happy_path(client, valid_token):
    response = client.get(
        "/v1/months/2015-01-28/clients?page=1&size=1", headers=_auth(valid_token)
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["meta"]["total"] == 2
    assert data["meta"]["has_next_page"] is True


def test_missing_token_returns_401(client):
    response = client.get("/v1/clients/1")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "missing_token"


def test_invalid_token_returns_401(client):
    response = client.get("/v1/clients/1", headers=_auth("garbage.token.value"))
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_token"


def test_insufficient_scope_returns_403(client, token_without_scope):
    response = client.get("/v1/clients/1", headers=_auth(token_without_scope))
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "insufficient_scope"


def test_bad_query_params_return_422(client, valid_token):
    response = client.get(
        "/v1/months/2015-01-28/clients?page=0", headers=_auth(valid_token)
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_bad_month_path_returns_422(client, valid_token):
    response = client.get("/v1/months/not-a-date/clients", headers=_auth(valid_token))
    assert response.status_code == 422


def test_repository_error_maps_to_500(build_test_client, valid_token):
    failing = FakeSilverRepository(should_raise_repository_error=True)
    failing_client = build_test_client(failing)
    response = failing_client.get("/v1/clients/1", headers=_auth(valid_token))
    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "internal_error"
    assert "Traceback" not in response.text
    assert body["correlationId"]


def test_correlation_id_is_echoed_and_reused(client, valid_token):
    provided = "test-correlation-123"
    response = client.get(
        "/v1/clients/1",
        headers={**_auth(valid_token), CORRELATION_ID_HEADER: provided},
    )
    assert response.headers[CORRELATION_ID_HEADER] == provided


def test_correlation_id_generated_when_absent(client):
    response = client.get("/health")
    assert response.headers.get(CORRELATION_ID_HEADER)
