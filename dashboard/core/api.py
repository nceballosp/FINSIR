"""Cliente HTTP de la API FINSIR (FastAPI en ECS).

El tablero no lee S3 ni Athena directamente: todo pasa por la API, que es la
capa de servicio de la arquitectura. Aquí se resuelven el token JWT, la
paginación (máximo 200 filas por página) y la conversión de los valores, que
la API entrega como texto dentro de ``attributes``.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import jwt
import pandas as pd
import requests
import streamlit as st

PAGE_SIZE = 200
TIMEOUT_S = 90
MAX_WORKERS = 6

# Endpoints de las tablas gold analíticas (iac/api/README.md).
ANALYTICS_ENDPOINTS = {
    "product_kpis": "/v1/gold/product-kpis/months/{month}",
    "customer_profiles": "/v1/gold/customer-profiles/months/{month}",
    "product_penetration": "/v1/gold/product-penetration/months/{month}",
    "product_affinity": "/v1/gold/product-affinity/months/{month}",
    "product_transitions": "/v1/gold/product-transitions/months/{month}",
    "baseline_popularity": "/v1/gold/baseline-popularity/months/{month}",
}


class ApiError(RuntimeError):
    """Error legible para mostrar en el tablero."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


def _settings() -> tuple[str, str]:
    try:
        base = str(st.secrets["API_BASE_URL"]).strip().rstrip("/")
        secret = str(st.secrets["AUTH_DEV_SECRET"]).strip()
    except (KeyError, FileNotFoundError) as error:
        raise ApiError(
            "Faltan los secretos API_BASE_URL y AUTH_DEV_SECRET. En local van en "
            ".streamlit/secrets.toml; en Streamlit Community Cloud, en Settings → Secrets."
        ) from error
    if not base.startswith(("http://", "https://")):
        base = f"http://{base}"
    return base, secret


def _token(secret: str) -> str:
    now = int(time.time())
    claims = {
        "sub": "finsir-dashboard",
        "scope": "gold:read",
        "iat": now - 60,
        "nbf": now - 60,
        "exp": now + 900,
    }
    return jwt.encode(claims, secret, algorithm="HS256")


def get_json(path: str, params: dict[str, Any] | None = None) -> dict:
    """GET autenticado; devuelve el JSON o lanza ApiError con un mensaje claro."""
    base, secret = _settings()
    try:
        response = requests.get(
            f"{base}{path}",
            params=params,
            headers={"Authorization": f"Bearer {_token(secret)}"},
            timeout=TIMEOUT_S,
        )
    except requests.RequestException as error:
        raise ApiError(
            f"No se pudo conectar con la API ({base}). Verifica que el servicio de ECS "
            "esté corriendo y que API_BASE_URL tenga la IP actual."
        ) from error
    if response.status_code == 404:
        raise ApiError("No se encontraron datos para esa consulta.", 404)
    if response.status_code in (401, 403):
        raise ApiError("La API rechazó el token: revisa AUTH_DEV_SECRET.", response.status_code)
    if response.status_code == 503:
        raise ApiError("El modelo no está cargado en la API (503).", 503)
    if not response.ok:
        raise ApiError(f"La API respondió {response.status_code}.", response.status_code)
    return response.json()


def _page(path: str, params: dict[str, Any], page: int) -> dict:
    return get_json(path, {**params, "page": page, "size": PAGE_SIZE})


def fetch_all_rows(path: str, params: dict[str, Any] | None = None) -> list[dict]:
    """Descarga todas las páginas de un endpoint de listado (en paralelo)."""
    params = {k: v for k, v in (params or {}).items() if v is not None}
    first = _page(path, params, 1)
    data = first.get("data", {})
    items = list(data.get("items", []))
    meta = data.get("meta") or first.get("meta") or {}
    total = int(meta.get("total", len(items)))
    pages = max(1, -(-total // PAGE_SIZE))
    if pages > 1:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            for result in pool.map(lambda p: _page(path, params, p), range(2, pages + 1)):
                items.extend(result.get("data", {}).get("items", []))
    return items


def rows_to_frame(items: list[dict]) -> pd.DataFrame:
    """Aplana ``attributes`` y convierte a número las columnas numéricas."""
    if not items:
        return pd.DataFrame()
    records = []
    for item in items:
        record = {k: v for k, v in item.items() if k != "attributes"}
        record.update(item.get("attributes") or {})
        records.append(record)
    frame = pd.DataFrame.from_records(records)
    for column in frame.columns:
        if column == "fecha_dato" or pd.api.types.is_numeric_dtype(frame[column]):
            continue
        converted = pd.to_numeric(frame[column], errors="coerce")
        # Solo se convierte si todo lo no nulo era numérico.
        if converted.notna().sum() == frame[column].notna().sum():
            frame[column] = converted
    return frame


def fetch_analytics(table: str, month: str, **filters: Any) -> pd.DataFrame:
    path = ANALYTICS_ENDPOINTS[table].format(month=month)
    return rows_to_frame(fetch_all_rows(path, filters))


def fetch_analytics_split(table: str, month: str, split_key: str, split_values: list[str],
                          **filters: Any) -> pd.DataFrame:
    """Consulta una tabla partiéndola por un filtro para que cada parte quepa en una página.

    La API pagina con LIMIT/OFFSET sin un ORDER BY estable, así que Athena puede
    repetir u omitir filas entre páginas. Con consultas de una sola página el
    resultado es exacto. Si alguna parte no cabe, se avisa en vez de devolver
    datos incompletos.
    """
    path = ANALYTICS_ENDPOINTS[table].format(month=month)

    def one(value: str) -> list[dict]:
        params = {k: v for k, v in {**filters, split_key: value}.items() if v is not None}
        payload = _page(path, params, 1)
        data = payload.get("data", {})
        meta = data.get("meta") or {}
        if meta.get("has_next_page"):
            raise ApiError(f"La consulta {table}/{split_key}={value} supera {PAGE_SIZE} filas.")
        return data.get("items", [])

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        parts = list(pool.map(one, split_values))
    return rows_to_frame([row for part in parts for row in part])


def fetch_analytics_months(table: str, months: list[str], **filters: Any) -> pd.DataFrame:
    """Varias consultas por mes en paralelo, concatenadas."""
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        frames = list(pool.map(lambda m: fetch_analytics(table, m, **filters), months))
    frames = [f for f in frames if not f.empty]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def fetch_client_history(ncodpers: int) -> pd.DataFrame:
    payload = get_json(f"/v1/gold/train/clients/{int(ncodpers)}")
    data = payload.get("data", [])
    items = data if isinstance(data, list) else data.get("items", [])
    return rows_to_frame(items)


def fetch_recommendations(ncodpers: int) -> dict:
    payload = get_json(f"/v1/recommendations/clients/{int(ncodpers)}")
    return payload["data"]


def health() -> bool:
    base, _ = _settings()
    try:
        return requests.get(f"{base}/health", timeout=8).ok
    except requests.RequestException:
        return False
