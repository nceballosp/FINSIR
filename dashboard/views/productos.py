"""02 · Productos: qué se contrata, cuándo y con qué estacionalidad."""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core import charts, data, ui
from core.api import ApiError
from core.catalog import FAMILIES, MONTHS_WITH_FLOWS, month_label, month_short
from core.theme import AMBER, GRAY, INK_2, NAVY, NAVY_900

ui.page_header(
    "02", "Entender los datos · Productos",
    "Pocos productos mueven las altas, y algunos dependen fuertemente del mes",
    "Una <b>alta</b> es un cliente que no tenía el producto el mes anterior y sí lo tiene este mes: "
    "exactamente lo que el modelo debe anticipar. Aquí se ve qué productos se contratan, cómo "
    "evoluciona cada uno y qué tan estacional es la demanda.",
)

try:
    with ui.loading():
        kpis = data.product_kpis_all_months()
except ApiError as error:
    ui.api_error(error)

kpis = kpis[kpis["fecha_dato"].isin(MONTHS_WITH_FLOWS)].copy()

# --- Filtros ---------------------------------------------------------------------
f1, f2, _ = st.columns([1, 2.4, 1])
month = f1.selectbox("Mes", MONTHS_WITH_FLOWS[::-1], format_func=month_label, key="prod_month")
families = f2.pills("Familia de producto", FAMILIES, selection_mode="multi", default=FAMILIES,
                    key="prod_families")
if not families:
    st.warning("Selecciona al menos una familia de producto.")
    st.stop()

view = kpis[kpis["family"].isin(families)]
cur = view[view["fecha_dato"] == month].sort_values("adds", ascending=False)
prev_month = MONTHS_WITH_FLOWS[MONTHS_WITH_FLOWS.index(month) - 1] if month != MONTHS_WITH_FLOWS[0] else None
prev = view[view["fecha_dato"] == prev_month] if prev_month else None

adds, drops = int(cur["adds"].sum()), int(cur["drops"].sum())
delta = (adds / prev["adds"].sum() - 1) if prev is not None and prev["adds"].sum() else None
leader = cur.iloc[0]
ui.kpi_row([
    {"label": "Altas del mes", "value": ui.fmt_int(adds),
     "note": (f"{'+' if delta >= 0 else '−'}{abs(delta) * 100:.0f} % vs. {month_label(prev_month)}"
              if delta is not None else "primer mes con altas")},
    {"label": "Bajas del mes", "value": ui.fmt_int(drops), "note": "clientes que dejan un producto"},
    {"label": "Altas netas", "value": ui.fmt_int(adds - drops),
     "note": "altas − bajas de los productos filtrados"},
    {"label": "Producto más contratado", "value": leader["product_label"], "small": True,
     "note": f"{ui.fmt_int(leader['adds'])} altas · {ui.fmt_pct(leader['adds'] / max(adds, 1), 0)} del total"},
])

# --- Ranking (clic para profundizar) + detalle -------------------------------------------
# Un solo estado para el producto seleccionado: lo cambian el clic en la barra y el selector.
if st.session_state.get("prod_pick") not in set(cur["product_label"]):
    st.session_state["prod_pick"] = leader["product_label"]

left, right = st.columns([1, 1.25], gap="large")
with left:
    with ui.card():
        top = cur.head(12)
        ui.chart_title(
            f"{leader['product_label']} encabeza las altas de {month_label(month)}",
            "Altas por producto en el mes (12 primeros). <b>Haz clic en una barra</b> o elige el "
            "producto en el selector para ver su evolución; el seleccionado aparece en ámbar.",
        )
        labels = list(top["product_label"])
        selected = st.session_state["prod_pick"]
        hl = [labels.index(selected)] if selected in labels else []
        fig = charts.hbar(
            labels, top["adds"], text=[ui.fmt_int(v) for v in top["adds"]], highlight=hl,
            hover="%{y}<br>%{x:,.0f} altas<extra></extra>",
        )
        event = ui.plot(fig, key="prod_rank", height=440, on_select="rerun",
                        selection_mode="points")
        points = (event or {}).get("selection", {}).get("points", []) if event else []
        if points:
            clicked = points[0].get("y")
            if clicked and clicked != st.session_state["prod_pick"]:
                st.session_state["prod_pick"] = clicked
                st.rerun()

with right:
    with ui.card():
        product = st.selectbox("Producto en detalle", list(cur["product_label"]), key="prod_pick")
        series = kpis[kpis["product_label"] == product].sort_values("fecha_dato")
        avg = series["adds"].mean()
        peak = series.loc[series["adds"].idxmax()]
        ratio = peak["adds"] / avg if avg else float("nan")
        ui.chart_title(
            f"{product}: su pico de altas fue {month_label(peak['fecha_dato'])}, "
            f"{ratio:.1f} veces su promedio mensual".replace(".", ","),
            "Altas mensuales del producto (línea) y bajas (gris). El mes del filtro se marca en ámbar.",
        )
        x = series["fecha_dato"].map(month_short)
        fig = go.Figure()
        fig.add_scatter(x=x, y=series["drops"], mode="lines", name="Bajas",
                        line=dict(color=GRAY, width=2),
                        customdata=series["fecha_dato"].map(month_label),
                        hovertemplate="%{customdata}<br>%{y:,.0f} bajas<extra></extra>")
        fig.add_scatter(x=x, y=series["adds"], mode="lines+markers", name="Altas",
                        line=dict(color=NAVY, width=2), marker=dict(size=6, color=NAVY),
                        customdata=series["fecha_dato"].map(month_label),
                        hovertemplate="%{customdata}<br>%{y:,.0f} altas<extra></extra>")
        sel = series[series["fecha_dato"] == month]
        if not sel.empty:
            fig.add_scatter(x=[month_short(month)], y=sel["adds"], mode="markers+text",
                            marker=dict(size=12, color=AMBER, line=dict(color="white", width=2)),
                            text=[ui.fmt_int(sel["adds"].iloc[0])], textposition="top center",
                            textfont=dict(color=NAVY_900), showlegend=False, hoverinfo="skip")
        fig.update_layout(yaxis=dict(title="Clientes", rangemode="tozero"),
                          xaxis=dict(tickangle=0), hovermode="x unified")
        ui.plot(fig, key="prod_trend", height=300)
        row = series[series["fecha_dato"] == month].iloc[0]
        ui.kpi_row([
            {"label": "Tenencia en el mes", "value": ui.fmt_pct(row["penetration_rate"], 1),
             "note": f"{ui.fmt_int(row['holders'])} clientes"},
            {"label": "Tasa de alta", "value": ui.fmt_pct(row["add_rate"], 2),
             "note": "altas / clientes que podían contratarlo"},
            {"label": "Tasa de baja", "value": ui.fmt_pct(row["drop_rate"], 1)
             if pd.notna(row["drop_rate"]) else "—", "note": "bajas / tenedores del mes anterior"},
        ])

# --- Estacionalidad ----------------------------------------------------------------------
with ui.card():
    vol = view.groupby("product_label")["adds"].mean()
    keep = vol[vol >= 50].sort_values(ascending=False).index  # productos con volumen relevante
    seasonal = view[view["product_label"].isin(keep)].copy()
    seasonal["index"] = seasonal["adds"] / seasonal["product_label"].map(vol)
    matrix = (seasonal.pivot_table(index="product_label", columns="fecha_dato", values="index")
              .reindex(index=keep))
    stacked = matrix.stack()
    (p_star, m_star), v_star = stacked.idxmax(), stacked.max()
    ui.chart_title(
        f"{p_star} se dispara en {month_label(m_star, long=True)}: "
        f"{v_star:.1f} veces su promedio mensual".replace(".", ","),
        "Altas de cada mes divididas por el promedio mensual del producto (1,0 = mes típico). "
        "Solo productos con al menos 50 altas promedio al mes. La estacionalidad explica por qué "
        "validar en mayo no garantiza el desempeño en junio (riesgo señalado en la propuesta).",
    )
    z = matrix.values.astype(float)
    fig = charts.heatmap(
        z, [month_short(m).replace("<br>", " ") for m in matrix.columns], matrix.index,
        text_fmt=lambda v: f"{v:.1f}".replace(".", ","),
        hover="%{y}<br>%{x}: %{z:.2f} veces su promedio<extra></extra>",
        colorbar_title="Altas / promedio", zmax=float(min(np.nanmax(z), 3.0)),
    )
    ui.plot(fig, key="prod_season", height=max(360, 30 * len(matrix) + 70))
    ui.data_table(
        view.pivot_table(index="product_label", columns="fecha_dato", values="adds")
        .reindex(index=keep).rename(columns=month_label).reset_index()
        .rename(columns={"product_label": "Producto"}),
        label="Ver altas absolutas por mes",
    )

# --- Crecimiento neto ----------------------------------------------------------------------
with ui.card():
    net = cur[["product_label", "net_adds"]].copy()
    net = net[net["net_adds"] != 0].sort_values("net_adds", ascending=False)
    growing, shrinking = (net["net_adds"] > 0).sum(), (net["net_adds"] < 0).sum()
    worst = net.iloc[-1] if shrinking else None
    title = f"En {month_label(month)} crecieron {growing} productos y {shrinking} perdieron clientes"
    if worst is not None:
        title += f"; {worst['product_label']} tuvo la mayor caída neta"
    ui.chart_title(
        title,
        "Altas netas por producto (altas − bajas). Azul: el producto ganó clientes; gris: perdió. "
        "Una caída no es solo churn: también entran y salen clientes del banco.",
    )
    colors = [NAVY if v > 0 else GRAY for v in net["net_adds"]]
    fig = go.Figure(go.Bar(
        x=net["product_label"], y=net["net_adds"], marker=dict(color=colors, cornerradius=3),
        text=[f"{'+' if v > 0 else '−'}{ui.fmt_int(abs(v))}" for v in net["net_adds"]],
        textposition="outside", cliponaxis=False, textfont=dict(size=11, color=INK_2),
        hovertemplate="%{x}<br>%{y:+,.0f} clientes netos<extra></extra>",
    ))
    fig.add_hline(y=0, line=dict(color="#9AA5B4", width=1))
    fig.update_layout(yaxis=dict(title="Altas netas"), xaxis=dict(tickangle=-35),
                      bargap=0.35)
    ui.plot(fig, key="prod_net", height=380)
