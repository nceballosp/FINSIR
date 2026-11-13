"""HTTP tests for the analytical gold endpoints (fake repository, no AWS)."""

from __future__ import annotations

import pytest

from tests.conftest import FakeGoldAnalyticsRepository

ALL_ROUTES = [
    "/v1/gold/product-kpis",
    "/v1/gold/customer-profiles",
    "/v1/gold/product-penetration",
    "/v1/gold/product-affinity",
    "/v1/gold/product-transitions",
    "/v1/gold/baseline-popularity",
]
KPIS = "/v1/gold/product-kpis/months"
BASELINE = "/v1/gold/baseline-popularity/months"


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_product_kpis_happy_path(client, valid_token):
    response = client.get(f"{KPIS}/2016-04-28?page=1&size=1", headers=_auth(valid_token))
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["meta"]["total"] == 2
    assert data["meta"]["has_next_page"] is True
    assert data["items"][0]["fecha_dato"] == "2016-04-28"
    assert "product" in data["items"][0]["attributes"]


def test_baseline_no_filter_happy_path(client, valid_token):
    response = client.get(f"{BASELINE}/2016-04-28", headers=_auth(valid_token))
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["meta"]["total"] == 1


def test_filter_param_flows_into_result(client, valid_token):
    response = client.get(
        f"{KPIS}/2016-04-28?product=ind_recibo_ult1", headers=_auth(valid_token)
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["meta"]["total"] == 1
    assert data["items"][0]["attributes"]["product"] == "ind_recibo_ult1"


def test_empty_month_returns_zero_total(client, valid_token):
    response = client.get(f"{KPIS}/2099-01-28", headers=_auth(valid_token))
    assert response.status_code == 200
    assert response.json()["data"]["meta"]["total"] == 0


def test_page_zero_returns_422(client, valid_token):
    response = client.get(f"{KPIS}/2016-04-28?page=0", headers=_auth(valid_token))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_bad_date_path_returns_422(client, valid_token):
    response = client.get(f"{KPIS}/not-a-date", headers=_auth(valid_token))
    assert response.status_code == 422


@pytest.mark.parametrize("resource", ALL_ROUTES)
def test_missing_token_returns_401(client, resource):
    response = client.get(f"{resource}/months/2016-04-28")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "missing_token"


@pytest.mark.parametrize("resource", ALL_ROUTES)
def test_insufficient_scope_returns_403(client, token_without_scope, resource):
    response = client.get(
        f"{resource}/months/2016-04-28", headers=_auth(token_without_scope)
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "insufficient_scope"


@pytest.mark.parametrize("resource", ALL_ROUTES)
def test_all_routes_are_mounted(client, valid_token, resource):
    response = client.get(
        f"{resource}/months/2016-04-28", headers=_auth(valid_token)
    )
    assert response.status_code == 200


def test_repository_error_maps_to_500(build_test_client, fake_repository, valid_token):
    failing = FakeGoldAnalyticsRepository(should_raise_repository_error=True)
    failing_client = build_test_client(fake_repository, failing)
    response = failing_client.get(f"{KPIS}/2016-04-28", headers=_auth(valid_token))
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert "Traceback" not in response.text
