"""03 · Transiciones: qué tenía el cliente antes de contratar un producto."""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core import charts, data, ui
from core.api import ApiError
from core.catalog import MONTHS, MONTHS_WITH_FLOWS, month_label, product_name
from core.theme import AMBER, GRAY, INK, INK_2, NAVY, NAVY_900

ui.page_header(
    "03", "Entender los datos · Transiciones",
    "Lo que un cliente ya tiene anticipa lo que contratará después",
    "Para cada producto contratado en un mes, se mira qué productos tenía ese cliente el mes "
    "anterior. Estos patrones de tenencia previa son la señal principal del modelo: por eso usa "
    "la tenencia actual y sus rezagos de 1, 3 y 6 meses como variables.",
)

f1, f2, f3 = st.columns([1, 1.6, 1.2])
month = f1.selectbox("Mes de contratación", MONTHS_WITH_FLOWS[::-1], format_func=month_label,
                     key="tr_month")

try:
    with ui.loading("Consultando transiciones y tenencia por producto…"):
        trans = data.product_transitions(month)
        kpis = data.product_kpis_all_months()
except ApiError as error:
    ui.api_error(error)

adds = (trans.groupby("to_product_label")["to_product_adds"].first()
        .sort_values(ascending=False))
destinations = list(adds.index)
default_dest = destinations[0]
target = f2.selectbox("Producto contratado (destino)", destinations,
                      index=destinations.index(st.session_state.get("tr_target", default_dest))
                      if st.session_state.get("tr_target") in destinations else 0,
                      key="tr_target_box")
st.session_state["tr_target"] = target
n_origins = f3.slider("Productos de origen a mostrar", 4, 12, 8, key="tr_n")

prev_month = MONTHS[MONTHS.index(month) - 1]
prev_pen = (kpis[kpis["fecha_dato"] == prev_month]
            .set_index("product_label")["penetration_rate"])

# --- Sankey general ------------------------------------------------------------------
with ui.card():
    top_dest = destinations[:6] if target in destinations[:6] else destinations[:5] + [target]
    sub = trans[trans["to_product_label"].isin(top_dest)].copy()
    origin_rank = sub.groupby("from_product_label")["clients"].sum().sort_values(ascending=False)
    keep = list(origin_rank.index[:n_origins])
    sub["origin"] = np.where(sub["from_product_label"].isin(keep), sub["from_product_label"],
                             "Otros productos")
    links = sub.groupby(["origin", "to_product_label"], as_index=False)["clients"].sum()
    left_nodes = keep + (["Otros productos"] if (links["origin"] == "Otros productos").any() else [])
    right_nodes = top_dest
    labels = [f"{n} " for n in left_nodes] + [f" {n}" for n in right_nodes]
    index_left = {n: i for i, n in enumerate(left_nodes)}
    index_right = {n: len(left_nodes) + i for i, n in enumerate(right_nodes)}
    link_colors = ["rgba(35,84,154,0.55)" if d == target else "rgba(184,193,204,0.45)"
                   for d in links["to_product_label"]]
    node_colors = ([GRAY] * len(left_nodes)
                   + [AMBER if n == target else NAVY for n in right_nodes])
    fig = go.Figure(go.Sankey(
        arrangement="snap",
        node=dict(label=labels, color=node_colors, pad=14, thickness=14,
                  line=dict(width=0),
                  hovertemplate="%{label}<br>%{value:,.0f} enlaces<extra></extra>"),
        link=dict(source=[index_left[o] for o in links["origin"]],
                  target=[index_right[d] for d in links["to_product_label"]],
                  value=links["clients"], color=link_colors,
                  hovertemplate="Tenía %{source.label}→ contrató%{target.label}<br>"
                                "%{value:,.0f} clientes<extra></extra>"),
    ))
    fig.update_layout(font=dict(size=12, color=INK), margin=dict(l=8, r=8, t=8, b=8))

    row = trans[trans["to_product_label"] == target].sort_values("share", ascending=False)
    top_origin = row.iloc[0]
    ui.chart_title(
        f"El {top_origin['share'] * 100:.0f} % de quienes contrataron {target.lower()} en "
        f"{month_label(month)} ya tenía {top_origin['from_product_label'].lower()}",
        f"Izquierda: productos que el cliente tenía en {month_label(prev_month)}. Derecha: producto "
        f"que contrató en {month_label(month)} (los de más altas y el seleccionado, en ámbar). "
        "Un cliente con varios productos aporta un enlace por cada uno, así que el ancho mide "
        "enlaces, no clientes únicos.",
    )
    ui.plot(fig, key="tr_sankey", height=480)

# --- Detalle: tenencia previa vs tenencia general -------------------------------------------
with ui.card():
    detail = row.head(10).copy()
    detail["general"] = detail["from_product_label"].map(prev_pen)
    detail = detail[detail["from_product"] != "sin_productos"]
    detail["ratio"] = detail["share"] / detail["general"]
    over = detail.sort_values("ratio", ascending=False).iloc[0]
    ui.chart_title(
        f"Entre quienes contratan {target.lower()}, tener {over['from_product_label'].lower()} es "
        f"{over['ratio']:.1f} veces más común que en el total de clientes".replace(".", ","),
        f"Punto azul: % de los que contrataron {target.lower()} que tenía cada producto. Punto gris: "
        f"% del total de clientes que lo tenía en {month_label(prev_month)}. La distancia entre "
        "ambos es la señal que aprovecha el modelo.",
    )
    detail = detail.sort_values("share", ascending=True)
    fig = go.Figure()
    for _, r in detail.iterrows():
        fig.add_shape(type="line", x0=r["general"], x1=r["share"], y0=r["from_product_label"],
                      y1=r["from_product_label"], line=dict(color="#C9D1DB", width=2))
    fig.add_scatter(x=detail["general"], y=detail["from_product_label"], mode="markers",
                    name="Total de clientes", marker=dict(size=10, color=GRAY),
                    hovertemplate="%{y}<br>Total de clientes: %{x:.1%}<extra></extra>")
    fig.add_scatter(x=detail["share"], y=detail["from_product_label"], mode="markers+text",
                    name=f"Contrataron {target.lower()}",
                    marker=dict(size=11, color=NAVY, line=dict(color="white", width=2)),
                    text=[ui.fmt_pct(v, 0) for v in detail["share"]], textposition="middle right",
                    textfont=dict(size=11, color=INK_2),
                    hovertemplate="%{y}<br>Entre quienes contrataron: %{x:.1%}<extra></extra>")
    fig.update_layout(xaxis=dict(tickformat=".0%", title="% que tenía el producto el mes anterior",
                                 showgrid=True, gridcolor="#EDF0F4", rangemode="tozero"),
                      yaxis=dict(showgrid=False), legend=dict(y=1.06))
    ui.plot(fig, key="tr_dumbbell", height=420)
    ui.data_table(
        row[["from_product_label", "clients", "to_product_adds", "share"]].rename(columns={
            "from_product_label": "Tenía (mes anterior)", "clients": "Clientes",
            "to_product_adds": f"Altas de {target}", "share": "Proporción"}),
        column_config={"Proporción": st.column_config.NumberColumn(format="percent")},
    )

# --- Afinidad entre productos ----------------------------------------------------------------
with ui.card():
    try:
        with ui.loading("Consultando la afinidad entre productos…"):
            aff = data.product_affinity(month)
    except ApiError as error:
        ui.api_error(error)
    holders = (aff.groupby("product_a_label")["holders_a"].first().sort_values(ascending=False))
    top_products = list(holders[holders >= 1000].index)[:16]
    m = (aff[aff["product_a_label"].isin(top_products) & aff["product_b_label"].isin(top_products)]
         .pivot_table(index="product_a_label", columns="product_b_label", values="phi")
         .reindex(index=top_products, columns=top_products))
    sym = aff[aff["product_a"] < aff["product_b"]].sort_values("phi", ascending=False).iloc[0]
    ui.chart_title(
        f"{sym['product_a_label']} y {sym['product_b_label'].lower()} casi siempre van juntos "
        f"(correlación φ = {sym['phi']:.2f})".replace(".", ","),
        "Correlación φ entre tener un producto y tener otro (de −1 a 1; 0 = independientes), "
        f"{month_label(month)}. Se muestran los 16 productos con más tenedores. Los valores "
        "negativos se pintan como 0; el valor exacto está en el tooltip.",
    )
    z = m.values.astype(float)
    np.fill_diagonal(z, np.nan)
    fig = charts.heatmap(
        np.clip(z, 0, None), m.columns, m.index,
        text_fmt=lambda v: f"{v:.2f}".replace(".", ",") if v >= 0.1 else "",
        hover="%{y} · %{x}<br>φ = %{customdata:.3f}<extra></extra>",
        colorbar_title="Correlación φ", zmax=float(np.nanmax(z)), customdata=z,
    )
    fig.update_layout(xaxis=dict(tickangle=-40, side="bottom"))
    ui.plot(fig, key="tr_aff", height=620)

    st.markdown("**Profundizar: con qué se combina un producto**")
    a_pick = st.selectbox("Producto", top_products, index=0, key="tr_aff_pick",
                          label_visibility="collapsed")
    pairs = (aff[(aff["product_a_label"] == a_pick) & (aff["holders_both"] >= 100)]
             .sort_values("confidence", ascending=False).head(8))
    if pairs.empty:
        st.caption("No hay combinaciones con al menos 100 clientes.")
    else:
        best = pairs.iloc[0]
        ui.chart_title(
            f"El {best['confidence'] * 100:.0f} % de quienes tienen {a_pick.lower()} también tiene "
            f"{best['product_b_label'].lower()}",
            "Confianza P(B | A): de los clientes con el producto elegido, qué porcentaje tiene cada "
            "otro producto. El lift (en el tooltip) compara contra lo esperado por azar; solo pares "
            "con al menos 100 clientes.",
        )
        fig = charts.hbar(
            pairs["product_b_label"], pairs["confidence"],
            text=[ui.fmt_pct(v, 0) for v in pairs["confidence"]], highlight=[0],
            customdata=pairs["lift"],
            hover="%{y}<br>Confianza: %{x:.1%}<br>Lift: %{customdata:.1f}<extra></extra>",
        )
        ui.plot(fig, key="tr_aff_bar", height=320)
