"""05 · Impacto de negocio: de MAP@7 a contactos, conversiones y costo."""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core import data, ui
from core.catalog import EVAL_BAND_LABELS, EVAL_BAND_ORDER, EVAL_DIMENSIONS, segment_name
from core.theme import AMBER, GRAY, INK_2, NAVY, NAVY_900

metrics = data.model_metrics()
test = {r["modelo"]: r for r in metrics["test_metrics"]}
hit_model = test["lightgbm"]["hit_rate@7"]
hit_base = test["popularidad"]["hit_rate@7"]
seg_metrics = data.model_csv("test_metrics_by_segment.csv")

ui.page_header(
    "05", "Modelo y decisión · Impacto de negocio",
    "Priorizar a quién contactar con el modelo rinde más que contactar al azar",
    "La decisión que apoya el modelo es <b>a quién contactar y con qué productos</b>. Este simulador "
    "traduce el desempeño medido en el mes de prueba a conversiones y beneficio de una campaña, con "
    "supuestos explícitos que puedes ajustar.",
)

# --- Supuestos -------------------------------------------------------------------------
with ui.card():
    st.markdown("**Supuestos de la campaña** · ajústalos para ver el efecto")
    a1, a2, a3, a4 = st.columns(4, gap="medium")
    contacts = a1.number_input("Clientes a contactar", 1_000, 900_000, 100_000, step=10_000,
                               key="imp_contacts")
    cost = a2.number_input("Costo por contacto (COP)", 0, 100_000, 3_000, step=500,
                           key="imp_cost")
    value = a3.number_input("Margen por producto contratado (COP)", 0, 5_000_000, 150_000,
                            step=10_000, key="imp_value")
    dim = a4.selectbox("Priorizar por", ["segmento", "age_band", "income_band"],
                       format_func=EVAL_DIMENSIONS.get, key="imp_dim")
    ui.note("Conversión = el cliente contrata al menos uno de los 7 productos ofrecidos el mes "
            "siguiente (tasa de acierto medida en el mes de prueba, abril → mayo 2016). Costos y "
            "márgenes son supuestos ilustrativos, no datos del banco.")

# --- Grupos ordenados por tasa de acierto del modelo -----------------------------------------
part = seg_metrics[(seg_metrics["segmento"] == dim) & seg_metrics["segmento_valor"].notna()
                   & (seg_metrics["clientes"] >= 1000)].copy()
if dim == "segmento":
    part["label"] = part["segmento_valor"].map(segment_name)
    part = part[part["label"] != "Sin dato"]
else:
    part["label"] = part["segmento_valor"].map(lambda v: EVAL_BAND_LABELS.get(v, v))
    part.loc[~part["segmento_valor"].isin(EVAL_BAND_ORDER.get(dim, [])), "label"] = "Sin dato"
part = part.sort_values("hit_rate_at_7", ascending=False).reset_index(drop=True)
universe = int(part["clientes"].sum())
contacts = min(int(contacts), universe)

# Llenado por prioridad: primero el grupo con mayor tasa de acierto.
remaining, rows = contacts, []
for r in part.itertuples():
    take = min(remaining, int(r.clientes))
    rows.append((r.label, take, r.hit_rate_at_7, take * r.hit_rate_at_7))
    remaining -= take
plan = pd.DataFrame(rows, columns=["Grupo", "Contactados", "Tasa de acierto", "Conversiones"])
conv_prior = plan["Conversiones"].sum()
avg_hit_universe = (part["clientes"] * part["hit_rate_at_7"]).sum() / universe
conv_random_model = contacts * avg_hit_universe
conv_random_base = contacts * hit_base


def profit(conv: float) -> float:
    return conv * value - contacts * cost


scenarios = pd.DataFrame({
    "Escenario": ["Sin modelo: los 7 más populares a clientes al azar",
                  "Modelo: Top-7 personalizado a clientes al azar",
                  "Modelo + priorización por " + EVAL_DIMENSIONS[dim].lower()],
    "Conversiones": [conv_random_base, conv_random_model, conv_prior],
})
scenarios["Beneficio neto (COP)"] = scenarios["Conversiones"].map(profit)
scenarios["Costo por conversión (COP)"] = (contacts * cost) / scenarios["Conversiones"].clip(lower=1e-9)
gain = conv_prior / conv_random_base - 1

ui.kpi_row([
    {"label": "Conversiones esperadas", "value": ui.fmt_int(conv_prior), "accent": True,
     "note": f"vs. {ui.fmt_int(conv_random_base)} sin modelo"},
    {"label": "Mejora en conversiones", "value": f"+{gain * 100:.0f} %".replace(".", ","),
     "note": "modelo + priorización vs. sin modelo"},
    {"label": "Costo por conversión", "value": f"{ui.fmt_int(scenarios.iloc[2, 3])} COP",
     "note": f"sin modelo: {ui.fmt_int(scenarios.iloc[0, 3])} COP"},
    {"label": "Beneficio neto de la campaña", "value": f"{ui.fmt_compact(profit(conv_prior))} COP"
     if profit(conv_prior) >= 0 else f"−{ui.fmt_compact(-profit(conv_prior))} COP",
     "note": "conversiones × margen − contactos × costo"},
])

c1, c2 = st.columns([1.2, 1], gap="large")
with c1:
    with ui.card():
        ui.chart_title(
            f"Contactando {ui.fmt_compact(contacts)} clientes, priorizar con el modelo logra "
            f"{ui.fmt_int(conv_prior - conv_random_base)} conversiones más que sin modelo",
            "Conversiones acumuladas a medida que se contactan más clientes. Línea azul: se contacta "
            "primero a los grupos donde el modelo acierta más. Gris: clientes al azar con los 7 "
            "productos más populares. El punto ámbar es la campaña configurada.",
        )
        xs = np.linspace(0, universe, 120)
        cum_sizes = np.concatenate([[0], part["clientes"].cumsum().values])
        cum_conv = np.concatenate([[0], (part["clientes"] * part["hit_rate_at_7"]).cumsum().values])
        ys_prior = np.interp(xs, cum_sizes, cum_conv)
        fig = go.Figure()
        fig.add_scatter(x=xs, y=xs * hit_base, mode="lines", name="Sin modelo, al azar",
                        line=dict(color=GRAY, width=2),
                        hovertemplate="%{x:,.0f} contactos<br>%{y:,.0f} conversiones<extra></extra>")
        fig.add_scatter(x=xs, y=ys_prior, mode="lines", name="Modelo + priorización",
                        line=dict(color=NAVY, width=2),
                        hovertemplate="%{x:,.0f} contactos<br>%{y:,.0f} conversiones<extra></extra>")
        fig.add_scatter(x=[contacts], y=[conv_prior], mode="markers+text", showlegend=False,
                        marker=dict(size=12, color=AMBER, line=dict(color="white", width=2)),
                        text=[ui.fmt_int(conv_prior)], textposition="top left",
                        textfont=dict(color=NAVY_900), hoverinfo="skip")
        fig.update_layout(xaxis=dict(title="Clientes contactados", showgrid=False, tickformat=",d"),
                          yaxis=dict(title="Conversiones esperadas", rangemode="tozero"))
        ui.plot(fig, key="imp_gain", height=360)

with c2:
    with ui.card():
        breakeven = cost / value if value else float("inf")
        above = part[part["hit_rate_at_7"] >= breakeven]
        ui.chart_title(
            f"Con estos supuestos, contactar es rentable en {len(above)} de {len(part)} grupos",
            f"Tasa de acierto del modelo por grupo frente al umbral de equilibrio "
            f"(costo ÷ margen = {ui.fmt_pct(breakeven, 2)}). Por encima de la línea, cada contacto "
            "paga su costo.",
        )
        colors = [NAVY if v >= breakeven else GRAY for v in part["hit_rate_at_7"]]
        fig = go.Figure(go.Bar(
            x=part["label"], y=part["hit_rate_at_7"], marker=dict(color=colors, cornerradius=3),
            text=[ui.fmt_pct(v, 1) for v in part["hit_rate_at_7"]], textposition="outside",
            textfont=dict(color=INK_2, size=12), cliponaxis=False,
            customdata=part["clientes"],
            hovertemplate="%{x}<br>Acierto %{y:.2%}<br>%{customdata:,.0f} clientes<extra></extra>",
        ))
        fig.add_hline(y=breakeven, line=dict(color=AMBER, width=2),
                      annotation_text=f"equilibrio {ui.fmt_pct(breakeven, 2)}",
                      annotation_position="top right", annotation_font=dict(color=NAVY_900, size=11))
        fig.update_layout(yaxis=dict(tickformat=".0%", title="Tasa de acierto (Top-7)",
                                     range=[0, max(part["hit_rate_at_7"].max(), breakeven) * 1.25]),
                          xaxis=dict(tickangle=0), bargap=0.45)
        ui.plot(fig, key="imp_threshold", height=360)

with ui.card():
    ui.chart_title("Comparación de escenarios con los mismos contactos")
    st.dataframe(scenarios.round(0), hide_index=True, column_config={
        "Conversiones": st.column_config.NumberColumn(format="localized"),
        "Beneficio neto (COP)": st.column_config.NumberColumn(format="localized"),
        "Costo por conversión (COP)": st.column_config.NumberColumn(format="localized"),
    })
    st.markdown("**Plan de contacto por prioridad**")
    st.dataframe(plan.assign(Conversiones=plan["Conversiones"].round(0)), hide_index=True, column_config={
        "Contactados": st.column_config.NumberColumn(format="localized"),
        "Tasa de acierto": st.column_config.NumberColumn(format="percent"),
        "Conversiones": st.column_config.NumberColumn(format="%.0f"),
    })

ui.method(
    "<b>Cómo se calcula.</b> Las tasas de acierto salen del mes de prueba (clientes con fila en abril "
    "y mayo de 2016): fracción de clientes con al menos un producto contratado dentro de su Top-7. "
    f"Sin modelo, la tasa es {ui.fmt_pct(hit_base, 2)}; con el modelo, {ui.fmt_pct(hit_model, 2)} en "
    "promedio, y mucho mayor en los grupos de alta actividad. Parte de la ganancia del escenario "
    "priorizado viene de contactar primero a los grupos más activos; el entrenamiento no reporta el "
    "acierto del baseline por grupo, así que esa parte no se puede separar. <b>Limitaciones:</b> es una "
    "simulación sobre datos históricos (asociación, no efecto causal de la campaña); asume que el "
    "cliente contactado se comporta como el observado; el MAP@7 además premia el orden, ventaja que "
    "este cálculo de «al menos un acierto» no captura (ofrecer menos de 7 productos favorece aún más "
    "al modelo)."
)
