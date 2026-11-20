"""Resumen ejecutivo: el problema, el resultado y el recorrido del tablero."""

from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from core import data, ui
from core.api import ApiError
from core.catalog import LATEST_MONTH, MONTHS_WITH_FLOWS, month_label, month_short
from core.theme import AMBER, GRAY, INK_2, NAVY, NAVY_900

metrics = data.model_metrics()
test = {row["modelo"]: row for row in metrics["test_metrics"]}
map_model = test["lightgbm"]["MAP@7"]
map_base = test["popularidad"]["MAP@7"]
lift = map_model / map_base - 1

ui.page_header(
    "00", "Resumen ejecutivo",
    f"El modelo ordena las ofertas un {lift * 100:.0f} % mejor que ofrecer a todos lo más popular",
    "Cada mes el banco debe decidir qué productos ofrecer a cada uno de sus ~930 mil clientes. "
    "FINSIR estima, para cada cliente, la propensión a contratar cada uno de los 24 productos el "
    "mes siguiente y entrega un <b>Top-7 personalizado</b>, excluyendo lo que ya tiene. La calidad "
    "del ranking se mide con MAP@7, la métrica oficial de la competencia de Kaggle.",
)

try:
    with ui.loading():
        kpis = data.product_kpis_all_months()
except ApiError as error:
    ui.api_error(error)

last = kpis[kpis["fecha_dato"] == LATEST_MONTH]
clients_last = int(last["clients"].iloc[0])

ui.kpi_row([
    {"label": f"Clientes en {month_label(LATEST_MONTH)}", "value": ui.fmt_int(clients_last),
     "note": "con registro ese mes"},
    {"label": "Registros procesados", "value": "13,6 M",
     "note": "17 meses · 2,3 GB de CSV crudo"},
    {"label": "Productos del portafolio", "value": "24",
     "note": "cuentas, ahorro, crédito y pagos"},
    {"label": "MAP@7 del modelo (prueba)", "value": ui.fmt_dec(map_model), "accent": True,
     "note": "LightGBM · altas de mayo 2016"},
    {"label": "MAP@7 del baseline", "value": ui.fmt_dec(map_base),
     "note": "ofrecer los 7 más populares"},
    {"label": "Mejora sobre el baseline", "value": f"+{lift * 100:.0f} %".replace(".", ","),
     "note": "misma partición fuera de tiempo"},
])

# --- Volumen mensual de altas ---------------------------------------------------
flows = (kpis[kpis["fecha_dato"].isin(MONTHS_WITH_FLOWS)]
         .groupby("fecha_dato", as_index=False)[["adds", "drops"]].sum())
flows["label"] = flows["fecha_dato"].map(month_label)
flows["tick"] = flows["fecha_dato"].map(month_short)
peak = flows.loc[flows["adds"].idxmax()]
avg_adds = flows["adds"].mean()

top_month = last.sort_values("adds", ascending=False)
top5_share = top_month["adds"].head(5).sum() / top_month["adds"].sum()

left, right = st.columns([1.35, 1], gap="large")
with left:
    with ui.card():
        ui.chart_title(
            f"Cada mes se contratan unos {ui.fmt_compact(avg_adds)} productos nuevos; "
            f"el pico fue {month_label(peak['fecha_dato'])}",
            "Altas mensuales de productos (cliente que no tenía el producto el mes anterior y "
            "sí lo tiene este mes). Es el evento que el modelo aprende a anticipar.",
        )
        fig = go.Figure()
        fig.add_scatter(
            x=flows["tick"], y=flows["adds"], mode="lines+markers", name="Altas",
            customdata=flows["label"],
            line=dict(color=NAVY, width=2), marker=dict(size=7, color=NAVY),
            hovertemplate="%{x}<br>%{y:,.0f} altas<extra></extra>",
        )
        fig.add_scatter(
            x=[month_short(peak["fecha_dato"])], y=[peak["adds"]], mode="markers+text",
            marker=dict(size=11, color=AMBER, line=dict(color="white", width=2)),
            text=[f"{ui.fmt_int(peak['adds'])}"], textposition="top center",
            textfont=dict(color=NAVY_900, size=12), showlegend=False, hoverinfo="skip",
        )
        fig.add_hline(y=avg_adds, line=dict(color=GRAY, width=1),
                      annotation_text=f"promedio {ui.fmt_int(avg_adds)}",
                      annotation_position="top left",
                      annotation_font=dict(color=INK_2, size=11))
        fig.update_layout(showlegend=False, yaxis_title="Altas en el mes",
                          yaxis=dict(rangemode="tozero"), xaxis=dict(tickangle=0))
        ui.plot(fig, key="res_trend", height=330)
        ui.data_table(flows.rename(columns={"label": "Mes", "adds": "Altas", "drops": "Bajas"})
                      [["Mes", "Altas", "Bajas"]])

with right:
    with ui.card():
        ui.chart_title(
            f"Cinco productos concentran el {top5_share * 100:.0f} % de las altas",
            f"Participación de cada producto en las altas de {month_label(LATEST_MONTH)}. "
            "Por eso el baseline de popularidad es un rival exigente.",
        )
        show = top_month.head(8).iloc[::-1]
        share = show["adds"] / top_month["adds"].sum()
        # Énfasis: los 5 del título en azul, el resto como contexto en gris.
        colors = [GRAY] * (len(show) - 5) + [NAVY] * 5
        fig = go.Figure(go.Bar(
            x=share, y=show["product_label"], orientation="h",
            marker=dict(color=colors, cornerradius=3),
            text=[f"{v * 100:.0f} %" for v in share], textposition="outside",
            textfont=dict(color=INK_2, size=12), cliponaxis=False,
            hovertemplate="%{y}<br>%{x:.1%} de las altas<extra></extra>",
        ))
        fig.update_layout(xaxis=dict(visible=False, range=[0, share.max() * 1.25]),
                          yaxis=dict(showgrid=False), margin=dict(l=8, r=30, t=8, b=8))
        ui.plot(fig, key="res_share", height=330)

# --- Recorrido ------------------------------------------------------------------
st.markdown("#### Recorrido del análisis")
steps = [
    ("01", "Clientes", "Quiénes son, cómo se distribuyen y qué productos tiene cada perfil.",
     "views/clientes.py"),
    ("02", "Productos", "Qué se contrata, cuándo y qué tan estacional es cada producto.",
     "views/productos.py"),
    ("03", "Transiciones", "Qué tenía el cliente antes de contratar: la señal que usa el modelo.",
     "views/transiciones.py"),
    ("04", "Modelo", "Cómo se validó, cuánto supera al baseline y en qué segmentos acierta más.",
     "views/modelo.py"),
    ("05", "Impacto", "Qué significa en contactos, conversiones y costo para una campaña.",
     "views/impacto.py"),
    ("06", "Recomendador", "El Top-7 de un cliente concreto, consultado en vivo a la API.",
     "views/recomendador.py"),
]
cols = st.columns(len(steps), gap="medium")
for col, (n, title, desc, page) in zip(cols, steps):
    with col:
        st.markdown(f'<div class="fs-step-card"><div class="n">{n}</div><div class="t">{title}</div>'
                    f'<div class="d">{desc}</div></div>', unsafe_allow_html=True)
        st.page_link(page, label="Abrir", icon=":material/arrow_forward:")

# --- De dónde salen los datos ------------------------------------------------------
st.markdown("#### De dónde salen estos datos")
st.markdown(
    '<div class="fs-flow">'
    '<div class="s"><div class="k">Bronze</div><div class="v">CSV de Kaggle en S3</div>'
    '<div class="x">13,6 M filas · 2,3 GB</div></div>'
    '<div class="s"><div class="k">Silver</div><div class="v">Glue · PySpark</div>'
    '<div class="x">Limpieza y tipado · Parquet</div></div>'
    '<div class="s"><div class="k">Gold</div><div class="v">8 tablas Parquet</div>'
    '<div class="x">Entrenamiento + 6 analíticas</div></div>'
    '<div class="s"><div class="k">Consulta</div><div class="v">Athena + Glue Catalog</div>'
    '<div class="x">SQL sobre el data lake</div></div>'
    '<div class="s"><div class="k">Servicio</div><div class="v">FastAPI en ECS</div>'
    '<div class="x">Datos + modelo LightGBM</div></div>'
    '<div class="s"><div class="k">Consumo</div><div class="v">Este tablero</div>'
    '<div class="x">Streamlit + Plotly</div></div>'
    '</div>',
    unsafe_allow_html=True,
)
ui.note("Todo el batch lo orquesta Step Functions y la infraestructura se crea con Terraform. "
        "El tablero no lee S3 directamente: consume la API, igual que lo haría un canal digital.")
