"""Precarga la caché en disco del tablero (dashboard/.cache).

La API resuelve cada consulta en Athena y atiende una a la vez, así que la
primera visita a cada vista puede tardar hasta un minuto. Ejecuta esto antes de
una presentación para que el recorrido por defecto abra al instante:

    python dashboard/warm_cache.py                # último mes
    python dashboard/warm_cache.py 2016-04-28     # otros meses

Debe correrse desde la raíz del repositorio (lee .streamlit/secrets.toml).
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from core import data  # noqa: E402
from core.catalog import DIMENSIONS, LATEST_MONTH  # noqa: E402


def step(label: str, fn) -> None:
    start = time.time()
    fn()
    print(f"  {label:<45} {time.time() - start:6.1f} s", flush=True)


def main(months: list[str]) -> None:
    print("Precargando caché del tablero FINSIR…")
    step("KPIs de producto (17 meses)", data.product_kpis_all_months)
    for month in months:
        print(f"Mes {month}")
        step("perfil de clientes", lambda: data.customer_profiles(month))
        step("transiciones", lambda: data.product_transitions(month))
        step("afinidad", lambda: data.product_affinity(month))
        step("baseline de popularidad", lambda: data.baseline_popularity(month))
        for dim in DIMENSIONS:
            step(f"penetración por {dim}", lambda d=dim: data.product_penetration(month, d))
    print("Listo.")


if __name__ == "__main__":
    main(sys.argv[1:] or [LATEST_MONTH])
