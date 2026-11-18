#!/usr/bin/env python3
"""Precalcula los datos del dashboard FINSIR desde el CSV de Kaggle.

Replica en local (con DuckDB) las reglas de las tablas gold analíticas de
``iac/data-platform/glue/gold_analytics.py`` para que el dashboard funcione sin
AWS: lee ``data/train_ver2.csv`` (~2.3 GB) y escribe archivos pequeños
(Parquet/JSON, < 1 MB en total) en ``visualizacion/datos/``.

Reglas compartidas con la capa gold:
- "Mes anterior/siguiente" es el mes de calendario (si el cliente se salta un
  mes, no hay dato).
- Un producto nulo cuenta como "no lo tiene".
- Alta del producto p en t: el cliente tiene fila en t-1 sin p y tiene p en t.
  Baja: tenía p en t-1 y no en t.
- Edad fuera de 0..122 y antigüedad negativa se vuelven nulas (limpieza silver).
- Dimensiones faltantes se agrupan como 'desconocido'; nada se imputa.

Uso (desde la raíz del repo o desde visualizacion/):
    python visualizacion/preparar_datos.py
    python visualizacion/preparar_datos.py --csv ruta/a/train_ver2.csv

Tarda de 2 a 6 minutos en un portátil (8 hilos, 16 GB de RAM).
"""

from __future__ import annotations

import argparse
import json
import tempfile
import time
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
OUT = HERE / "datos"

PRODUCTS = [
    "ind_ahor_fin_ult1", "ind_aval_fin_ult1", "ind_cco_fin_ult1",
    "ind_cder_fin_ult1", "ind_cno_fin_ult1", "ind_ctju_fin_ult1",
    "ind_ctma_fin_ult1", "ind_ctop_fin_ult1", "ind_ctpp_fin_ult1",
    "ind_deco_fin_ult1", "ind_deme_fin_ult1", "ind_dela_fin_ult1",
    "ind_ecue_fin_ult1", "ind_fond_fin_ult1", "ind_hip_fin_ult1",
    "ind_plan_fin_ult1", "ind_pres_fin_ult1", "ind_reca_fin_ult1",
    "ind_tjcr_fin_ult1", "ind_valo_fin_ult1", "ind_viv_fin_ult1",
    "ind_nomina_ult1", "ind_nom_pens_ult1", "ind_recibo_ult1",
]
N = len(PRODUCTS)
K = 7
UNKNOWN = "desconocido"


def bit(i: int, col: str = "mask") -> str:
    """SQL: 1 si el producto i está en la máscara de bits, 0 si no."""
    return f"(({col} >> {i}) & 1)"


def band_sql(col: str, bands: list[tuple[int | None, str]]) -> str:
    """SQL CASE equivalente a band() de gold_analytics.py."""
    parts = [f"WHEN {col} IS NULL THEN '{UNKNOWN}'"]
    for upper, label in bands:
        parts.append(f"WHEN {col} < {upper} THEN '{label}'" if upper is not None
                     else f"ELSE '{label}'")
    return "CASE " + " ".join(parts) + " END"


AGE_BANDS = [(18, "00-17"), (25, "18-24"), (35, "25-34"), (45, "35-44"),
             (55, "45-54"), (65, "55-64"), (None, "65+")]
INCOME_BANDS = [(50_000, "000-050k"), (100_000, "050-100k"),
                (200_000, "100-200k"), (500_000, "200-500k"), (None, "500k+")]
TENURE_BANDS = [(7, "000-006m"), (13, "007-012m"), (37, "013-036m"),
                (61, "037-060m"), (121, "061-120m"), (None, "121m+")]


def log(msg: str, t0: float) -> None:
    print(f"[{time.time() - t0:6.1f}s] {msg}", flush=True)


def load(con: duckdb.DuckDBPyConnection, csv: Path) -> None:
    """Carga y limpia el CSV en la tabla `t` (una fila por cliente-mes).

    Los 24 productos quedan en una máscara de bits (`mask`) para que los joins
    con el mes anterior/siguiente sean livianos en memoria.
    """
    mask = " | ".join(
        f"(COALESCE(TRY_CAST(trim({p}) AS INTEGER), 0)::INTEGER << {i})"
        for i, p in enumerate(PRODUCTS)
    )
    con.execute(f"""
        CREATE TABLE t AS
        SELECT
            CAST(fecha_dato AS DATE)                              AS fecha,
            (year(CAST(fecha_dato AS DATE)) - 2015) * 12
              + month(CAST(fecha_dato AS DATE))                   AS mi,
            CAST(trim(ncodpers) AS BIGINT)                        AS ncodpers,
            NULLIF(trim(sexo), '')                                AS sexo,
            CASE WHEN TRY_CAST(trim(age) AS INTEGER) BETWEEN 0 AND 122
                 THEN TRY_CAST(trim(age) AS INTEGER) END          AS age,
            CASE WHEN TRY_CAST(trim(antiguedad) AS INTEGER) >= 0
                 THEN TRY_CAST(trim(antiguedad) AS INTEGER) END   AS antiguedad,
            TRY_CAST(trim(renta) AS DOUBLE)                       AS renta,
            NULLIF(trim(segmento), '')                            AS segmento,
            TRY_CAST(trim(ind_actividad_cliente) AS INTEGER)      AS actividad,
            TRY_CAST(trim(ind_nuevo) AS INTEGER)                  AS ind_nuevo,
            NULLIF(trim(nomprov), '')                             AS provincia,
            -- Filas crudas con edad/antigüedad imposibles (para el reporte de calidad)
            (TRY_CAST(trim(age) AS INTEGER) IS NOT NULL
               AND TRY_CAST(trim(age) AS INTEGER) NOT BETWEEN 0 AND 122) AS edad_invalida,
            (TRY_CAST(trim(antiguedad) AS INTEGER) < 0)           AS antig_invalida,
            ({mask})::INTEGER                                     AS mask
        FROM read_csv('{csv.as_posix()}', header = true, all_varchar = true)
    """)


def build_joined(con: duckdb.DuckDBPyConnection) -> None:
    """`j`: cada cliente-mes con su máscara del mes anterior y del siguiente."""
    con.execute("""
        CREATE TABLE j AS
        SELECT c.*, p.mask AS pmask, n.mask AS nmask
        FROM t c
        LEFT JOIN t p ON p.ncodpers = c.ncodpers AND p.mi = c.mi - 1
        LEFT JOIN t n ON n.ncodpers = c.ncodpers AND n.mi = c.mi + 1
    """)


def quality(con, t0) -> dict:
    row = con.execute("""
        SELECT count(*), count(DISTINCT ncodpers), count(DISTINCT fecha),
               min(fecha), max(fecha),
               avg((renta IS NULL)::INT), avg((age IS NULL)::INT),
               avg((segmento IS NULL)::INT), avg((sexo IS NULL)::INT),
               sum(edad_invalida::INT), sum(COALESCE(antig_invalida, false)::INT),
               avg(bit_count(mask))
        FROM t
    """).fetchone()
    log("Reporte de calidad listo", t0)
    return {
        "filas": int(row[0]), "clientes": int(row[1]), "meses": int(row[2]),
        "fecha_min": str(row[3]), "fecha_max": str(row[4]),
        "pct_renta_nula": float(row[5]), "pct_edad_nula": float(row[6]),
        "pct_segmento_nulo": float(row[7]), "pct_sexo_nulo": float(row[8]),
        "edades_invalidas": int(row[9]), "antiguedades_invalidas": int(row[10]),
        "productos_promedio": float(row[11]),
        "productos": N, "top_k": K,
    }


def monthly(con, t0) -> tuple[pd.DataFrame, pd.DataFrame]:
    """KPIs mensuales por producto (= gold_product_monthly_kpis) y resumen."""
    exprs = []
    for i in range(N):
        cur, prev = bit(i), bit(i, "pmask")
        exprs += [
            f"sum({cur}) AS holders_{i}",
            f"sum(CASE WHEN pmask IS NOT NULL AND {prev} = 0 THEN 1 ELSE 0 END) AS eligible_{i}",
            f"sum(CASE WHEN pmask IS NOT NULL AND {prev} = 0 AND {cur} = 1 THEN 1 ELSE 0 END) AS adds_{i}",
            f"sum(CASE WHEN pmask IS NOT NULL AND {prev} = 1 THEN 1 ELSE 0 END) AS holders_prev_{i}",
            f"sum(CASE WHEN pmask IS NOT NULL AND {prev} = 1 AND {cur} = 0 THEN 1 ELSE 0 END) AS drops_{i}",
        ]
    wide = con.execute(f"""
        SELECT fecha, count(*) AS clients,
               sum((pmask IS NOT NULL)::INT) AS clients_with_prev,
               sum(COALESCE(ind_nuevo, 0)) AS new_clients,
               sum(COALESCE(actividad, 0)) AS active_clients,
               avg(bit_count(mask)) AS avg_products,
               sum((bit_count(mask) = 0)::INT) AS clients_without_products,
               sum(CASE WHEN pmask IS NOT NULL AND (mask & ~pmask) <> 0 THEN 1 ELSE 0 END)
                   AS clients_with_adds,
               {", ".join(exprs)}
        FROM j GROUP BY fecha ORDER BY fecha
    """).df()
    summary_cols = ["fecha", "clients", "clients_with_prev", "new_clients",
                    "active_clients", "avg_products", "clients_without_products",
                    "clients_with_adds"]
    summary = wide[summary_cols].copy()

    rows = []
    for _, r in wide.iterrows():
        first_month = r["clients_with_prev"] == 0
        for i, p in enumerate(PRODUCTS):
            rows.append({
                "fecha": r["fecha"], "product": p, "clients": r["clients"],
                "holders": r[f"holders_{i}"], "eligible": r[f"eligible_{i}"],
                "adds": r[f"adds_{i}"], "holders_prev": r[f"holders_prev_{i}"],
                "drops": r[f"drops_{i}"], "first_month": first_month,
            })
    kpis = pd.DataFrame(rows)
    kpis["penetration_rate"] = kpis.holders / kpis.clients
    kpis["add_rate"] = kpis.adds / kpis.eligible.replace(0, np.nan)
    kpis["drop_rate"] = kpis.drops / kpis.holders_prev.replace(0, np.nan)
    kpis["net_adds"] = kpis.adds - kpis.drops
    # Ranking por altas (empates por nombre); null el primer mes.
    kpis = kpis.sort_values(["fecha", "adds", "product"], ascending=[True, False, True])
    kpis["popularity_rank"] = kpis.groupby("fecha").cumcount() + 1
    kpis.loc[kpis.first_month, ["popularity_rank", "add_rate", "drop_rate"]] = np.nan
    kpis = kpis.drop(columns="first_month").reset_index(drop=True)
    summary["total_adds"] = kpis.groupby("fecha").adds.sum().values
    log("KPIs mensuales listos", t0)
    return kpis, summary


def profile(con, month: str, t0) -> pd.DataFrame:
    """Perfil sociodemográfico del mes (≈ gold_customer_profile)."""
    df = con.execute(f"""
        SELECT COALESCE(segmento, '{UNKNOWN}') AS segmento,
               {band_sql("age", AGE_BANDS)} AS age_band,
               COALESCE(sexo, '{UNKNOWN}') AS sexo,
               {band_sql("renta", INCOME_BANDS)} AS income_band,
               CASE actividad WHEN 1 THEN 'activo' WHEN 0 THEN 'inactivo'
                    ELSE '{UNKNOWN}' END AS actividad,
               count(*) AS clients,
               sum(bit_count(mask)) AS sum_products,
               sum(COALESCE(ind_nuevo, 0)) AS new_clients
        FROM t WHERE fecha = DATE '{month}'
        GROUP BY ALL
    """).df()
    log("Perfil de clientes listo", t0)
    return df


def ages(con, month: str) -> pd.DataFrame:
    return con.execute(f"""
        SELECT age, count(*) AS clients FROM t
        WHERE fecha = DATE '{month}' AND age IS NOT NULL
        GROUP BY age ORDER BY age
    """).df()


def penetration(con, month: str, t0) -> pd.DataFrame:
    """Penetración por dimensión (= gold_product_penetration) del mes."""
    dims = {
        "segmento": f"COALESCE(segmento, '{UNKNOWN}')",
        "age_band": band_sql("age", AGE_BANDS),
        "income_band": band_sql("renta", INCOME_BANDS),
        "tenure_band": band_sql("antiguedad", TENURE_BANDS),
        "sexo": f"COALESCE(sexo, '{UNKNOWN}')",
        "actividad": (f"CASE actividad WHEN 1 THEN 'activo' WHEN 0 THEN 'inactivo' "
                      f"ELSE '{UNKNOWN}' END"),
        "provincia": f"COALESCE(provincia, '{UNKNOWN}')",
    }
    sums = ", ".join(f"sum({bit(i)}) AS h_{i}" for i in range(N))
    frames = []
    for name, expr in dims.items():
        wide = con.execute(f"""
            SELECT {expr} AS dimension_value, count(*) AS clients, {sums}
            FROM t WHERE fecha = DATE '{month}' GROUP BY 1
        """).df()
        long = wide.melt(id_vars=["dimension_value", "clients"],
                         value_vars=[f"h_{i}" for i in range(N)],
                         var_name="product", value_name="holders")
        long["product"] = long["product"].map(lambda c: PRODUCTS[int(c[2:])])
        long.insert(0, "dimension", name)
        frames.append(long)
    df = pd.concat(frames, ignore_index=True)
    df["penetration_rate"] = df.holders / df.clients
    log("Penetración por dimensión lista", t0)
    return df


def affinity(con, month: str, t0) -> pd.DataFrame:
    """Co-tenencia, lift y phi entre pares de productos (= gold_product_affinity)."""
    exprs = [f"count(*) AS clients"] + [f"sum({bit(i)}) AS h_{i}" for i in range(N)]
    exprs += [f"sum({bit(a)} & {bit(b)}) AS b_{a}_{b}"
              for a in range(N) for b in range(a + 1, N)]
    r = con.execute(f"SELECT {', '.join(exprs)} FROM t WHERE fecha = DATE '{month}'").df().iloc[0]
    n = float(r["clients"])
    rows = []
    for a in range(N):
        for b in range(N):
            if a == b:
                continue
            ha, hb = float(r[f"h_{a}"]), float(r[f"h_{b}"])
            both = float(r[f"b_{min(a, b)}_{max(a, b)}"])
            pa, pb = ha / n, hb / n
            conf = both / ha if ha else np.nan
            lift = conf / pb if ha and pb else np.nan
            denom = np.sqrt(pa * (1 - pa) * pb * (1 - pb))
            phi = (both / n - pa * pb) / denom if denom > 0 else np.nan
            rows.append({"product_a": PRODUCTS[a], "product_b": PRODUCTS[b],
                         "clients": n, "holders_a": ha, "holders_b": hb,
                         "holders_both": both, "support": both / n,
                         "confidence": conf, "lift": lift, "phi": phi})
    log("Afinidad entre productos lista", t0)
    return pd.DataFrame(rows)


def transitions(con, t0) -> pd.DataFrame:
    """Qué tenía en t-1 quien adquirió cada producto en t (= gold_product_transitions),
    sumado sobre todos los meses."""
    exprs = []
    for i in range(N):
        added = f"((adds >> {i}) & 1)"
        exprs.append(f"sum({added}) AS adds_{i}")
        exprs.append(f"sum(CASE WHEN pmask = 0 THEN {added} ELSE 0 END) AS f_none_{i}")
        exprs += [f"sum({added} & {bit(j, 'pmask')}) AS f_{j}_{i}" for j in range(N)]
    r = con.execute(f"""
        WITH a AS (SELECT pmask, (mask & ~pmask) AS adds FROM j
                   WHERE pmask IS NOT NULL AND (mask & ~pmask) <> 0)
        SELECT {", ".join(exprs)} FROM a
    """).df().iloc[0]
    rows = []
    for i, to in enumerate(PRODUCTS):
        total = int(r[f"adds_{i}"])
        if total == 0:
            continue
        sources = [("sin_productos", int(r[f"f_none_{i}"]))]
        sources += [(PRODUCTS[j], int(r[f"f_{j}_{i}"])) for j in range(N)]
        for frm, c in sources:
            if c > 0:
                rows.append({"from_product": frm, "to_product": to, "clients": c,
                             "to_product_adds": total, "share": c / total})
    log("Transiciones (Sankey) listas", t0)
    return pd.DataFrame(rows)


def average_precision(recs: list[int], actual: int) -> tuple[float, bool]:
    n_actual = bin(actual).count("1")
    if n_actual == 0:
        return 0.0, False
    hits, score = 0, 0.0
    for pos, p in enumerate(recs[:K], start=1):
        if (actual >> p) & 1:
            hits += 1
            score += hits / pos
    return score / min(n_actual, K), hits > 0


def baseline(con, kpis: pd.DataFrame, t0) -> pd.DataFrame:
    """Modelo base de popularidad y su MAP@7 por mes (= gold_baseline_popularity).

    Ranking del mes t por altas en t; a cada cliente con fila en t y t+1 se le
    recomiendan los 7 primeros que no tiene en t; se compara con sus altas de t+1.
    Los clientes sin altas en t+1 tienen AP@7 = 0, así que solo se recorren los
    compradores y se divide por el total de evaluados.
    """
    evaluated = con.execute("""
        SELECT fecha, count(*) AS clients_evaluated FROM j
        WHERE nmask IS NOT NULL GROUP BY fecha
    """).df().set_index("fecha")["clients_evaluated"]
    buyers = con.execute("""
        SELECT fecha, mask, (nmask & ~mask) AS actual FROM j
        WHERE nmask IS NOT NULL AND (nmask & ~mask) <> 0
    """).df()
    idx = {p: i for i, p in enumerate(PRODUCTS)}
    rows = []
    for fecha, grp in kpis.dropna(subset=["popularity_rank"]).groupby("fecha"):
        ranking = [idx[p] for p in grp.sort_values("popularity_rank")["product"]]
        b = buyers[buyers.fecha == fecha]
        n_eval = int(evaluated.get(fecha, 0))
        aps, hits = [], []
        for mask, actual in zip(b["mask"].to_numpy(), b["actual"].to_numpy()):
            recs = [p for p in ranking if not (int(mask) >> p) & 1][:K]
            ap, hit = average_precision(recs, int(actual))
            aps.append(ap)
            hits.append(hit)
        rows.append({
            "fecha": fecha,
            "top_7_products": ",".join(PRODUCTS[p] for p in ranking[:K]),
            "popularity_ranking": ",".join(PRODUCTS[p] for p in ranking),
            "clients_evaluated": n_eval,
            "clients_with_adds": len(b),
            "map_at_7": (sum(aps) / n_eval) if n_eval else np.nan,
            "map_at_7_buyers": float(np.mean(aps)) if aps else np.nan,
            "hit_rate_at_7_buyers": float(np.mean(hits)) if hits else np.nan,
        })
    log("Modelo base de popularidad evaluado", t0)
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--csv", type=Path, default=REPO / "data" / "train_ver2.csv")
    parser.add_argument("--memory-limit", default="10GB")
    args = parser.parse_args()
    if not args.csv.exists():
        raise SystemExit(f"No encuentro el CSV en {args.csv}. Descárgalo de Kaggle "
                         "(Santander Product Recommendation) y ponlo en data/train_ver2.csv")

    t0 = time.time()
    OUT.mkdir(exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="finsir_duckdb_"))
    con = duckdb.connect()
    con.execute(f"SET memory_limit = '{args.memory_limit}'")
    con.execute(f"SET temp_directory = '{tmp.as_posix()}'")
    con.execute("SET preserve_insertion_order = false")

    log(f"Leyendo {args.csv} ...", t0)
    load(con, args.csv)
    log("CSV cargado y limpio", t0)
    build_joined(con)
    log("Join con mes anterior/siguiente listo", t0)

    calidad = quality(con, t0)
    last_month = calidad["fecha_max"]
    kpis, summary = monthly(con, t0)
    base = baseline(con, kpis, t0)
    outputs = {
        "kpis_mensuales.parquet": kpis,
        "resumen_mensual.parquet": summary,
        "perfil_clientes.parquet": profile(con, last_month, t0),
        "edades.parquet": ages(con, last_month),
        "penetracion.parquet": penetration(con, last_month, t0),
        "afinidad.parquet": affinity(con, last_month, t0),
        "transiciones.parquet": transitions(con, t0),
        "baseline_popularidad.parquet": base,
    }
    for name, df in outputs.items():
        df.to_parquet(OUT / name, index=False)
    calidad["mes_referencia"] = last_month
    (OUT / "calidad.json").write_text(json.dumps(calidad, indent=2, ensure_ascii=False),
                                      encoding="utf-8")
    con.close()
    log(f"Listo. Archivos en {OUT}", t0)


if __name__ == "__main__":
    main()
