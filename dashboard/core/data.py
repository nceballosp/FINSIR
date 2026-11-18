"""Carga de datos con caché.

Las tablas gold vienen de la API (Athena detrás), así que cada consulta tarda
unos segundos. Se guardan en caché por sesión del servidor: la primera visita
a una página consulta la API y las siguientes son instantáneas.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pandas as pd
import streamlit as st

from core import api
from core.catalog import MONTHS, PRODUCT_CODES, product_family, product_name

SEGMENT_VALUES = ["01 - TOP", "02 - PARTICULARES", "03 - UNIVERSITARIO", "desconocido"]

ASSETS = Path(__file__).resolve().parent.parent / "assets" / "model"
CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache"
TTL = 6 * 3600


def _disk_cached(name: str, loader) -> pd.DataFrame:
    """Caché en disco (parquet) para tablas históricas que no cambian.

    La API resuelve cada consulta en Athena (segundos por consulta); con esta
    caché la segunda carga es instantánea incluso tras reiniciar el tablero.
    Borra la carpeta dashboard/.cache para forzar datos frescos.
    """
    path = CACHE_DIR / f"{name}.parquet"
    if path.exists():
        try:
            return pd.read_parquet(path)
        except (OSError, ValueError):
            path.unlink(missing_ok=True)  # archivo corrupto: se vuelve a consultar
    frame = loader()
    if not frame.empty:
        # En Streamlit Community Cloud el disco es efímero (se borra al reiniciar la app);
        # si no se puede escribir, el tablero sigue funcionando con la caché en memoria.
        try:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            frame.to_parquet(path, index=False)
        except OSError:
            pass
    return frame


def _with_names(frame: pd.DataFrame, *columns: str) -> pd.DataFrame:
    for column in columns:
        if column in frame.columns:
            frame[f"{column}_label"] = frame[column].map(product_name)
    return frame


@st.cache_data(ttl=TTL, show_spinner=False)
def product_kpis_all_months() -> pd.DataFrame:
    frame = _disk_cached("product_kpis", lambda: api.fetch_analytics_months("product_kpis", MONTHS))
    frame = _with_names(frame, "product")
    frame["family"] = frame["product"].map(product_family)
    return frame.sort_values(["fecha_dato", "product"]).reset_index(drop=True)


@st.cache_data(ttl=TTL, show_spinner=False)
def customer_profiles(month: str) -> pd.DataFrame:
    return _disk_cached(f"customer_profiles_{month}", lambda: api.fetch_analytics_split(
        "customer_profiles", month, "segmento", SEGMENT_VALUES))


@st.cache_data(ttl=TTL, show_spinner=False)
def product_penetration(month: str, dimension: str) -> pd.DataFrame:
    def load() -> pd.DataFrame:
        if dimension == "provincia":
            # ~53 provincias x 24 productos: se parte por producto (una página cada uno).
            return api.fetch_analytics_split(
                "product_penetration", month, "product", PRODUCT_CODES, dimension=dimension
            )
        # <= 8 valores x 24 productos = <= 192 filas: cabe en una sola página.
        return api.fetch_analytics_split("product_penetration", month, "dimension", [dimension])

    frame = _disk_cached(f"product_penetration_{month}_{dimension}", load)
    return _with_names(frame, "product")


@st.cache_data(ttl=TTL, show_spinner=False)
def product_affinity(month: str) -> pd.DataFrame:
    frame = _disk_cached(f"product_affinity_{month}", lambda: api.fetch_analytics_split(
        "product_affinity", month, "product_a", PRODUCT_CODES))
    return _with_names(frame, "product_a", "product_b")


@st.cache_data(ttl=TTL, show_spinner=False)
def product_transitions(month: str) -> pd.DataFrame:
    frame = _disk_cached(f"product_transitions_{month}", lambda: api.fetch_analytics_split(
        "product_transitions", month, "to_product", PRODUCT_CODES))
    return _with_names(frame, "from_product", "to_product")


@st.cache_data(ttl=TTL, show_spinner=False)
def baseline_popularity(month: str) -> pd.DataFrame:
    return _disk_cached(f"baseline_popularity_{month}",
                        lambda: api.fetch_analytics("baseline_popularity", month))


@st.cache_data(ttl=600, show_spinner=False)
def client_history(ncodpers: int) -> pd.DataFrame:
    frame = api.fetch_client_history(ncodpers)
    if not frame.empty:
        frame = frame.sort_values("fecha_dato").reset_index(drop=True)
    return frame


@st.cache_data(ttl=600, show_spinner=False)
def client_recommendations(ncodpers: int) -> dict:
    return api.fetch_recommendations(ncodpers)


# --- Resultados del entrenamiento (iac/model-training/train.py) -------------
# Son archivos pequeños y estáticos de la corrida que produjo el modelo que
# sirve la API; se versionan junto al tablero en assets/model/.

@st.cache_data(show_spinner=False)
def model_metrics() -> dict:
    return json.loads((ASSETS / "metrics.json").read_text(encoding="utf-8"))


@st.cache_data(show_spinner=False)
def model_csv(name: str) -> pd.DataFrame:
    return pd.read_csv(ASSETS / name)


@st.cache_data(show_spinner=False)
def case_studies() -> pd.DataFrame:
    frame = pd.read_csv(ASSETS / "test_case_studies.csv")
    for column in ("recommendations", "actual_additions", "held_products"):
        frame[column] = frame[column].map(ast.literal_eval)
    return frame
