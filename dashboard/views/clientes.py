"""01 · Clientes: quiénes son y qué tiene cada perfil."""

from __future__ import annotations

import numpy as np
import pandas as pd
import streamlit as st

from core import charts, data, ui
from core.api import ApiError
from core.catalog import (BAND_LABELS, DIMENSIONS, LATEST_MONTH, MONTHS, SEGMENTS, band_label,
                          month_label, segment_name)

ui.page_header(
    "01", "Entender los datos · Clientes",
    "Quiénes son los clientes y qué productos tiene cada perfil",
    "Antes de recomendar hay que conocer la base: tamaño, edad, renta y segmento, y cómo cambia la "
    "tenencia de cada producto entre perfiles. Estas diferencias son las que el modelo aprovecha "
    "para personalizar el ranking.",
)

# --- Filtros de la página -------------------------------------------------------
f1, f2, _ = st.columns([1, 2.2, 1.2])
month = f1.selectbox("Mes", MONTHS[::-1], format_func=month_label, key="cli_month")
segment_options = list(SEGMENTS)
segments = f2.pills("Segmento (aplica al perfil y a los indicadores)", segment_options,
                    selection_mode="multi", default=segment_options, format_func=segment_name,
                    key="cli_segments")
if not segments:
    st.warning("Selecciona al menos un segmento.")
    st.stop()

try:
    with ui.loading():
        profiles = data.customer_profiles(month)
except ApiError as error:
    ui.api_error(error)

prof = profiles[profiles["segmento"].isin(segments)].copy()
total = prof["clients"].sum()
active = prof["active_clients"].sum()
renta_known = prof["renta_known"].sum()
avg_renta = (prof["avg_renta"].fillna(0) * prof["renta_known"]).sum() / max(renta_known, 1)
avg_products = (prof["avg_n_products"] * prof["clients"]).sum() / max(total, 1)
without = prof["clients_without_products"].sum()

ui.kpi_row([
    {"label": "Clientes", "value": ui.fmt_int(total), "note": month_label(month, long=True)},
    {"label": "Clientes activos", "value": ui.fmt_pct(active / total),
     "note": f"{ui.fmt_int(active)} con actividad en el mes"},
    {"label": "Productos por cliente", "value": f"{avg_products:.2f}".replace(".", ","),
     "note": "promedio de los 24 productos"},
    {"label": "Sin ningún producto", "value": ui.fmt_pct(without / total),
     "note": f"{ui.fmt_int(without)} clientes"},
    {"label": "Renta media del hogar", "value": f"{ui.fmt_compact(avg_renta)} €",
     "note": f"solo quienes la reportan ({ui.fmt_pct(renta_known / total, 0)})"},
])

# --- Edad y renta ------------------------------------------------------------------
AGE_ORDER = ["00-17", "18-24", "25-34", "35-44", "45-54", "55-64", "65+"]
INCOME_ORDER = ["000-050k", "050-100k", "100-200k", "200-500k", "500k+", "desconocido"]

age = prof.groupby("age_band")["clients"].sum().reindex(AGE_ORDER).fillna(0)
young_share = age[["00-17", "18-24", "25-34"]].sum() / max(age.sum(), 1)
income = prof.groupby("income_band")["clients"].sum().reindex(INCOME_ORDER).fillna(0)
unknown_income = income["desconocido"] / max(income.sum(), 1)

c1, c2 = st.columns(2, gap="large")
with c1:
    with ui.card():
        ui.chart_title(
            f"{young_share * 10:.0f} de cada 10 clientes tiene menos de 35 años".replace(".", ","),
            "Clientes por rango de edad. En azul, los rangos menores de 35 años; en gris, el resto.",
        )
        labels = [BAND_LABELS[b] for b in AGE_ORDER]
        fig = charts.vbar(
            labels, age.values,
            text=[ui.fmt_pct(v / age.sum(), 0) for v in age.values],
            muted=[3, 4, 5, 6],
            hover="%{x} años<br>%{y:,.0f} clientes<extra></extra>", y_title="Clientes",
        )
        ui.plot(fig, key="cli_age", height=300)
        ui.data_table(pd.DataFrame({"Rango de edad": labels, "Clientes": age.values.astype(int)}))

with c2:
    with ui.card():
        ui.chart_title(
            f"{unknown_income * 100:.0f} % de los clientes no reporta renta; se deja como «sin dato», "
            "no se imputa",
            "Clientes por renta bruta anual del hogar (euros). La categoría sin dato, en gris, es un "
            "hallazgo de calidad de datos que el modelo trata como valor faltante.",
        )
        labels = [BAND_LABELS[b] for b in INCOME_ORDER]
        fig = charts.vbar(
            labels, income.values,
            text=[ui.fmt_pct(v / income.sum(), 0) for v in income.values],
            muted=[len(INCOME_ORDER) - 1],
            hover="%{x}<br>%{y:,.0f} clientes<extra></extra>", y_title="Clientes",
        )
        ui.plot(fig, key="cli_income", height=300)
        ui.data_table(pd.DataFrame({"Renta": labels, "Clientes": income.values.astype(int)}))

# --- Segmentos ---------------------------------------------------------------------
seg = (profiles.groupby("segmento")
       .apply(lambda g: pd.Series({
           "clients": g["clients"].sum(),
           "avg_products": (g["avg_n_products"] * g["clients"]).sum() / g["clients"].sum(),
           "active_rate": g["active_clients"].sum() / g["clients"].sum(),
           "avg_age": (g["avg_age"].fillna(0) * g["clients"]).sum() / g["clients"].sum(),
       }), include_groups=False)
       .reset_index())
seg = seg[seg["segmento"].isin(SEGMENTS)].sort_values("avg_products", ascending=False)
seg["name"] = seg["segmento"].map(segment_name)
best, worst = seg.iloc[0], seg.iloc[-1]
ratio = best["avg_products"] / worst["avg_products"]

with ui.card():
    ui.chart_title(
        f"Un cliente {best['name']} tiene {ratio:.1f} veces más productos que uno "
        f"{worst['name'].lower()}".replace(".", ","),
        "Productos promedio por cliente según segmento (todos los segmentos, sin filtro). "
        "La profundidad de la relación cambia mucho entre segmentos: por eso el segmento es una "
        "variable del modelo y un eje del análisis de impacto.",
    )
    s1, s2 = st.columns([1, 1.15], gap="large")
    with s1:
        fig = charts.hbar(
            seg["name"], seg["avg_products"],
            text=[f"{v:.2f}".replace(".", ",") for v in seg["avg_products"]],
            highlight=[0],
            hover="%{y}<br>%{x:.2f} productos por cliente<extra></extra>",
        )
        ui.plot(fig, key="cli_seg", height=200)
    with s2:
        table = pd.DataFrame({
            "Segmento": seg["name"],
            "Clientes": seg["clients"].astype(int),
            "Activos": seg["active_rate"],
            "Edad media": seg["avg_age"].round(0).astype(int),
        })
        st.caption("Clientes activos: con actividad transaccional en el mes.")
        st.dataframe(table, hide_index=True, column_config={
            "Clientes": st.column_config.NumberColumn(format="localized"),
            "Activos": st.column_config.ProgressColumn(format="percent", min_value=0, max_value=1,
                                                       width="medium"),
        })

# --- Mapa de calor de tenencia -------------------------------------------------------
with ui.card():
    dim_options = list(DIMENSIONS)
    dimension = st.segmented_control(
        "Ver tenencia por", dim_options, default="segmento", format_func=DIMENSIONS.get,
        key="cli_dim",
    ) or "segmento"
    try:
        with ui.loading("Consultando la penetración de productos…"):
            pen = data.product_penetration(month, dimension)
    except ApiError as error:
        ui.api_error(error)

    pen = pen.copy()
    pen["value_label"] = [band_label(dimension, v) for v in pen["dimension_value"]]
    values = (pen.groupby("value_label")["clients"].first().sort_values(ascending=False))
    if dimension in ("age_band", "income_band", "tenure_band"):
        order = sorted(pen["dimension_value"].unique(), key=lambda v: (v == "desconocido", v))
        cols = [band_label(dimension, v) for v in order]
    else:
        cols = list(values.index)
    if dimension == "provincia":
        cols = cols[:15]
    # Productos ordenados por penetración global del mes.
    overall = (pen.groupby("product_label")
               .apply(lambda g: g["holders"].sum() / g["clients"].sum(), include_groups=False)
               .sort_values(ascending=False))
    matrix = (pen.pivot_table(index="product_label", columns="value_label",
                              values="penetration_rate", aggfunc="first")
              .reindex(index=overall.index, columns=cols))

    # Hallazgo: el producto con mayor brecha entre valores (con base suficiente).
    known_cols = [c for c in cols if c != "Sin dato"]
    spread = (matrix[known_cols].max(axis=1) - matrix[known_cols].min(axis=1)).sort_values(
        ascending=False)
    p_star = spread.index[0]
    hi_col, lo_col = matrix.loc[p_star, known_cols].idxmax(), matrix.loc[p_star, known_cols].idxmin()
    hi_v, lo_v = matrix.loc[p_star, hi_col], matrix.loc[p_star, lo_col]

    ui.chart_title(
        f"{p_star}: la tenencia va de {ui.fmt_pct(lo_v, 0)} ({lo_col}) a "
        f"{ui.fmt_pct(hi_v, 0)} ({hi_col})",
        f"Porcentaje de clientes que tiene cada producto, por {DIMENSIONS[dimension].lower()} · "
        f"{month_label(month)} · todos los clientes del mes. Más oscuro = mayor tenencia."
        + (" Se muestran las 15 provincias con más clientes." if dimension == "provincia" else ""),
    )
    z = matrix.values.astype(float)
    fig = charts.heatmap(
        z, matrix.columns, matrix.index,
        text_fmt=lambda v: f"{v * 100:.0f}" if v >= 0.005 else ("·" if v > 0 else ""),
        hover="%{y}<br>%{x}: %{z:.1%} de los clientes<extra></extra>",
        colorbar_title="% con el producto", zmax=float(np.nanpercentile(z, 98)),
    )
    fig.update_traces(colorbar=dict(tickformat=".0%"))
    ui.plot(fig, key="cli_heat", height=max(520, 24 * len(matrix) + 80))
    ui.note("Los números de cada celda son porcentajes redondeados; «·» indica menos de 0,5 %. "
            "Pasa el cursor para ver el valor exacto.")

    # Profundización: un producto en detalle.
    st.markdown("**Profundizar en un producto**")
    product = st.selectbox("Producto", list(overall.index), index=list(overall.index).index(p_star),
                           key="cli_drill", label_visibility="collapsed")
    row = matrix.loc[product].dropna()
    avg = overall[product]
    idx_max = int(np.argmax(row.values))
    times = row.iloc[idx_max] / avg if avg > 0 else float("nan")
    ui.chart_title(
        f"{product}: en «{row.index[idx_max]}» la tenencia es {times:.1f} veces la del total "
        "del mes".replace(".", ","),
        "Porcentaje de clientes con el producto en cada grupo. La línea gris es el total del mes.",
    )
    fig = charts.vbar(
        row.index, row.values, text=[ui.fmt_pct(v, 1) for v in row.values],
        highlight=[idx_max],
        hover="%{x}<br>%{y:.2%} tiene " + product.lower() + "<extra></extra>",
        y_title="% de clientes con el producto",
    )
    fig.add_hline(y=avg, line=dict(color="#9AA5B4", width=1),
                  annotation_text=f"total del mes {ui.fmt_pct(avg, 1)}",
                  annotation_position="top right", annotation_font=dict(size=11, color="#4A5568"))
    fig.update_layout(yaxis=dict(tickformat=".0%"))
    ui.plot(fig, key="cli_drill_chart", height=300)
    ui.data_table(
        matrix.reset_index().rename(columns={"product_label": "Producto"}),
        label="Ver la tabla completa de tenencia",
        column_config={c: st.column_config.NumberColumn(format="percent") for c in matrix.columns},
    )
