"""06 · Recomendador por cliente: el modelo en uso sobre casos concretos."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core import charts, data, ui
from core.api import ApiError
from core.catalog import (LATEST_MONTH, PRODUCT_CODES, month_label, month_short, product_name,
                          segment_name)
from core.theme import AMBER, GRAY, INK, INK_2, NAVY, NAVY_900

ui.page_header(
    "06", "Modelo y decisión · Caso aplicado",
    "Para cada cliente, el Top-7 de productos que conviene ofrecerle el próximo mes",
    "Escribe el ID de un cliente (<i>ncodpers</i>). El tablero consulta en vivo la API desplegada en "
    "AWS: su historial en la tabla gold y la recomendación del modelo LightGBM sobre su mes más "
    "reciente. Así lo usaría un asesor o una campaña digital.",
)

cases = data.case_studies()
EXAMPLES = [1375586, 15945, 18007, 27775, 29850]

if "rec_input" not in st.session_state:
    st.session_state["rec_input"] = EXAMPLES[0]


def _use_example() -> None:
    if st.session_state.get("rec_examples"):
        st.session_state["rec_input"] = int(st.session_state["rec_examples"])


f1, f2 = st.columns([1, 2.4], gap="medium")
f1.number_input("ID del cliente", min_value=1, step=1, format="%d", key="rec_input")
f2.pills("O elige un cliente de ejemplo", EXAMPLES, format_func=lambda v: f"Cliente {v}",
         key="rec_examples", on_change=_use_example)
client = int(st.session_state["rec_input"])


def load(ncodpers: int):
    with ThreadPoolExecutor(max_workers=3) as pool:
        h = pool.submit(data.client_history, ncodpers)
        r = pool.submit(data.client_recommendations, ncodpers)
        b = pool.submit(data.baseline_popularity, LATEST_MONTH)
        return h.result(), r.result(), b.result()


try:
    with ui.loading(f"Consultando el cliente {client} en la API…"):
        history, recs, baseline = load(client)
except ApiError as error:
    if error.status == 404:
        st.warning(f"El cliente {client} no existe en la tabla gold. Prueba con uno de los ejemplos.")
        st.stop()
    ui.api_error(error)

if history.empty:
    st.warning(f"No hay historial para el cliente {client}.")
    st.stop()

latest = history.iloc[-1]
items = recs["items"][0]
top7 = pd.DataFrame(items["recommendations"])
top7["name"] = top7["product"].map(product_name)
held = [p for p in PRODUCT_CODES if pd.to_numeric(latest.get(p), errors="coerce") == 1]

# --- Ficha del cliente ----------------------------------------------------------------------
renta = pd.to_numeric(latest.get("renta"), errors="coerce")
ui.kpi_row([
    {"label": "Cliente", "value": str(client), "note": f"último mes: {month_label(latest['fecha_dato'])}"},
    {"label": "Edad", "value": f"{int(latest['age'])} años" if pd.notna(latest.get("age")) else "—",
     "note": segment_name(latest.get("segmento"))},
    {"label": "Antigüedad", "value": f"{int(latest['antiguedad'])} meses"
     if pd.notna(latest.get("antiguedad")) else "—",
     "note": f"canal de entrada {latest.get('canal_entrada') or '—'}"},
    {"label": "Renta del hogar", "value": f"{ui.fmt_compact(renta)} €" if pd.notna(renta) else "Sin dato",
     "note": "anual, según el banco"},
    {"label": "Productos que tiene", "value": str(len(held)),
     "note": "activo este mes" if latest.get("ind_actividad_cliente") == 1 else "inactivo este mes"},
])

left, right = st.columns([1.15, 1], gap="large")
with left:
    with ui.card():
        first = top7.iloc[0]
        ui.chart_title(
            f"Primera oferta recomendada: {first['name']}",
            f"Top-7 del modelo para el mes siguiente a {month_label(latest['fecha_dato'])}, ordenado "
            "por puntaje. Ya excluye los productos que el cliente tiene. El puntaje es relativo "
            "(ranking multiclase), no una probabilidad de compra.",
        )
        fig = charts.hbar(
            [f"{i + 1}. {n}" for i, n in enumerate(top7["name"])], top7["score"],
            text=[f"{v:.3f}".replace(".", ",") for v in top7["score"]], highlight=[0],
            hover="%{y}<br>Puntaje %{x:.3f}<extra></extra>",
        )
        ui.plot(fig, key="rec_top7", height=330)
        st.caption(f"Versión del modelo: {recs['model_version']} · respuesta de "
                   "GET /v1/recommendations/clients/{ncodpers}")

with right:
    with ui.card():
        ui.chart_title(
            "Qué tiene hoy el cliente",
            "Productos activos en su mes más reciente. Son la entrada principal del modelo.",
        )
        ui.chips([product_name(p) for p in held] or ["Ningún producto"], on=set(product_name(p) for p in held))
        # Comparación con la popularidad.
        if not baseline.empty:
            ranking = str(baseline.iloc[0]["popularity_ranking"]).split(",")
            pop7 = [p for p in ranking if p not in held][:7]
            personal = [p for p in top7["product"] if p not in pop7]
            st.markdown("**Frente a ofrecer lo más popular**")
            if personal:
                ui.insight(
                    "El modelo incluye " + ", ".join(f"<b>{product_name(p)}</b>" for p in personal)
                    + ", que no estaría en el Top-7 de popularidad para este cliente: es la parte "
                    "personalizada de la recomendación."
                )
            else:
                order_changes = [p for i, p in enumerate(top7["product"]) if i < len(pop7) and pop7[i] != p]
                ui.insight("El modelo recomienda los mismos productos que la popularidad, pero "
                           + ("en otro orden, ajustado al perfil del cliente." if order_changes
                              else "en el mismo orden: para este perfil la popularidad ya acierta."))
            comp = pd.DataFrame({
                "Puesto": range(1, 8),
                "Modelo (FINSIR)": list(top7["name"]) + [""] * (7 - len(top7)),
                "Popularidad": [product_name(p) for p in pop7] + [""] * (7 - len(pop7)),
            })
            st.dataframe(comp, hide_index=True, height=290)

# --- Historial ------------------------------------------------------------------------------
with ui.card():
    ever = [p for p in PRODUCT_CODES
            if pd.to_numeric(history[p], errors="coerce").fillna(0).max() == 1] if not history.empty else []
    rec_products = list(top7["product"])
    rows = ever + [p for p in rec_products if p not in ever]
    months = list(history["fecha_dato"])
    z = np.array([[1.0 if pd.to_numeric(history.loc[i, p], errors="coerce") == 1 else 0.0
                   for i in history.index] for p in rows])
    ui.chart_title(
        f"Historial de {len(months)} meses: qué productos tuvo el cliente y cuáles se le recomiendan",
        "Azul: el cliente tenía el producto ese mes. Las filas marcadas con ★ son productos del Top-7 "
        "recomendado. Los cambios recientes (altas y bajas) pesan en el modelo a través de los rezagos.",
    )
    labels = [f"★ {product_name(p)}" if p in rec_products else product_name(p) for p in rows]
    fig = go.Figure(go.Heatmap(
        z=z, x=[month_short(m).replace("<br>", " ") for m in months], y=labels,
        colorscale=[[0, "#F4F7FB"], [1, NAVY]], zmin=0, zmax=1, showscale=False, xgap=2, ygap=2,
        hovertemplate="%{y}<br>%{x}: %{customdata}<extra></extra>",
        customdata=np.where(z == 1, "lo tenía", "no lo tenía"),
    ))
    fig.update_layout(yaxis=dict(autorange="reversed", showgrid=False, tickfont=dict(size=12, color=INK)),
                      xaxis=dict(side="top", showline=False, tickangle=0, tickfont=dict(size=11)),
                      margin=dict(l=8, r=8, t=8, b=8))
    ui.plot(fig, key="rec_history", height=max(220, 26 * len(rows) + 60))

# --- Por qué: patrones de transición ------------------------------------------------------------
with ui.card():
    ui.chart_title(
        "Por qué tiene sentido la recomendación: lo que hicieron clientes con productos parecidos",
        f"Para los 3 primeros productos recomendados: entre quienes los contrataron en "
        f"{month_label(LATEST_MONTH)}, qué porcentaje ya tenía algún producto que este cliente tiene.",
    )
    try:
        with ui.loading("Consultando transiciones del último mes…"):
            trans = data.product_transitions(LATEST_MONTH)
    except ApiError:
        trans = pd.DataFrame()
    if trans.empty or not held:
        st.caption("No hay información suficiente para explicar con transiciones (el cliente no tiene "
                   "productos o la consulta falló).")
    else:
        bullets = []
        for p in top7["product"].head(3):
            t = trans[(trans["to_product"] == p) & (trans["from_product"].isin(held))]
            if t.empty:
                bullets.append(f"<b>{product_name(p)}</b>: pocos clientes con sus productos lo "
                               "contrataron; lo sugiere su perfil (edad, antigüedad, segmento).")
                continue
            best = t.sort_values("share", ascending=False).iloc[0]
            bullets.append(
                f"<b>{product_name(p)}</b>: el {best['share'] * 100:.0f} % de quienes lo contrataron ya "
                f"tenía <b>{product_name(best['from_product']).lower()}</b>, igual que este cliente "
                f"({ui.fmt_int(best['to_product_adds'])} altas en el mes)."
            )
        ui.insight("<br/>".join(bullets))

# --- Casos de prueba: aciertos y fallos --------------------------------------------------------
with ui.card():
    hits = int(cases["hit_at_7"].sum())
    all_hits = hits == len(cases)
    ui.chart_title(
        "Casos reales del mes de prueba: qué recomendó el modelo y qué contrató el cliente",
        "Clientes del conjunto de prueba (abril → mayo 2016). En ámbar, el producto que el cliente "
        "contrató dentro de su Top-7; la posición determina su AP@7."
        + (" Estos ejemplos los seleccionó el script de entrenamiento entre clientes con acierto: "
           "ilustran cómo se usa el ranking, no la tasa de acierto (que está en la página 4)."
           if all_hits else ""),
    )
    options = list(cases.index)
    pick = st.selectbox(
        "Caso", options,
        format_func=lambda i: (f"Cliente {cases.loc[i, 'ncodpers']} · {segment_name(cases.loc[i, 'segmento'])}"
                               f" · {int(cases.loc[i, 'age'])} años · "
                               + ("acierto" if cases.loc[i, "hit_at_7"] else "fallo")),
        key="rec_case",
    )
    case = cases.loc[pick]
    actual = set(case["actual_additions"])
    recs_case = case["recommendations"]
    c1, c2 = st.columns([1.2, 1], gap="large")
    with c1:
        pos = [i for i, p in enumerate(recs_case) if p in actual]
        fig = charts.hbar(
            [f"{i + 1}. {product_name(p)}" for i, p in enumerate(recs_case)],
            [7 - i for i in range(len(recs_case))],
            highlight=pos, base=GRAY,
            hover="%{y}<extra></extra>",
        )
        fig.update_layout(xaxis=dict(visible=False))
        ui.plot(fig, key="rec_case_chart", height=280)
    with c2:
        st.markdown("**Contrató realmente**")
        ui.chips([product_name(p) for p in actual] or ["Nada"], on=set(product_name(p) for p in actual))
        st.markdown("**Tenía antes**")
        ui.chips([product_name(p) for p in case["held_products"]] or ["Ningún producto"])
        if pos:
            ui.insight(f"Acierto en la posición <b>{pos[0] + 1}</b>: su AP@7 es "
                       f"{1 / (pos[0] + 1):.2f}".replace(".", ",")
                       + " (1,00 si hubiera quedado primero). Así se construye el MAP@7.")
        else:
            ui.insight("Fallo: lo que contrató no estaba en su Top-7. Suele pasar con productos poco "
                       "frecuentes o clientes con poca historia.")
