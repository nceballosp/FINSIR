"""FINSIR · Dashboard del Proyecto Integrador.

Recorrido narrativo de 6 secciones pensado para explicarse solo en ~5 minutos:
problema y justificación → datos → patrones de contratación → metodología →
resultados → conclusiones.

Datos:
- Agregados del dataset completo (13,6 M filas) que genera
  ``preparar_datos.py`` en ``visualizacion/datos/`` con las mismas reglas que
  las tablas gold de ``iac/data-platform/glue/gold_analytics.py``.
- Resultados del modelo en ``datos/resultados_modelo.json`` (notebook) o, si
  existe, ``datos/modelo/metrics.json`` (salida de ``iac/model-training/train.py``).
- Opcional: la API FINSIR en ECS para recomendaciones en vivo.

Ejecutar desde esta carpeta:  streamlit run app.py
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

HERE = Path(__file__).resolve().parent
DATA = HERE / "datos"
REPO = HERE.parent
ARCH_IMG = REPO / "documentation" / "architecture" / "aws_architecture_diagram.png"

BLUE = "#12305a"       # serie principal / modelo
ORANGE = "#f2a93b"     # serie de comparación / modelo base
GRAY = "#c3c2b7"       # contexto (emphasis: resaltar uno, gris el resto)
INK = "#0b0b0b"
INK_2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
SURFACE = "#fcfcfb"

FONT = 'system-ui, -apple-system, "Segoe UI", Roboto, sans-serif'

PRODUCT_LABELS = {
    "ind_ahor_fin_ult1": "Cuenta de ahorros",
    "ind_aval_fin_ult1": "Garantías",
    "ind_cco_fin_ult1": "Cuenta corriente",
    "ind_cder_fin_ult1": "Cuenta de derivados",
    "ind_cno_fin_ult1": "Cuenta nómina",
    "ind_ctju_fin_ult1": "Cuenta junior",
    "ind_ctma_fin_ult1": "Cuenta Más Particular",
    "ind_ctop_fin_ult1": "Cuenta Particular",
    "ind_ctpp_fin_ult1": "Cuenta Particular Plus",
    "ind_deco_fin_ult1": "Depósito corto plazo",
    "ind_deme_fin_ult1": "Depósito mediano plazo",
    "ind_dela_fin_ult1": "Depósito largo plazo",
    "ind_ecue_fin_ult1": "Cuenta electrónica",
    "ind_fond_fin_ult1": "Fondos de inversión",
    "ind_hip_fin_ult1": "Hipoteca",
    "ind_plan_fin_ult1": "Plan de pensiones",
    "ind_pres_fin_ult1": "Préstamos",
    "ind_reca_fin_ult1": "Impuestos",
    "ind_tjcr_fin_ult1": "Tarjeta de crédito",
    "ind_valo_fin_ult1": "Valores",
    "ind_viv_fin_ult1": "Cuenta vivienda",
    "ind_nomina_ult1": "Nómina (abono)",
    "ind_nom_pens_ult1": "Pensión (abono)",
    "ind_recibo_ult1": "Débito automático",
    "sin_productos": "Sin productos",
}
SEGMENT_LABELS = {"01 - TOP": "VIP", "02 - PARTICULARES": "Particulares",
                  "03 - UNIVERSITARIO": "Universitario", "desconocido": "Sin dato"}
DIMENSIONS = {
    "segmento": "Segmento", "age_band": "Rango de edad", "income_band": "Renta del hogar",
    "tenure_band": "Antigüedad (meses)", "actividad": "Actividad del cliente",
}
FEATURE_LABELS = {
    "ind_actividad_cliente": "Cliente activo", "tiprel_1mes": "Tipo de relación",
    "antiguedad": "Antigüedad", "canal_entrada": "Canal de entrada",
    "n_products": "N.º de productos", "age": "Edad", "month_of_year": "Mes del año",
    "renta": "Renta", "n_products_dropped": "Productos dados de baja",
    "segmento": "Segmento", "cod_prov": "Provincia",
}
MESES = ["ene", "feb", "mar", "abr", "may", "jun",
         "jul", "ago", "sep", "oct", "nov", "dic"]


def pname(code: str) -> str:
    return PRODUCT_LABELS.get(code, code)


def fname(feature: str) -> str:
    """Nombre legible de una feature de gold_train."""
    if feature in FEATURE_LABELS:
        return FEATURE_LABELS[feature]
    for suffix, txt in (("_lag1", " (hace 1 mes)"), ("_lag3", " (hace 3 meses)"),
                        ("_lag6", " (hace 6 meses)")):
        if feature.endswith(suffix):
            return pname(feature[: -len(suffix)]) + txt
    if feature.startswith("added_"):
        return "Adquirió " + pname(feature[6:]) + " este mes"
    if feature in PRODUCT_LABELS:
        return pname(feature) + " (lo tiene hoy)"
    return feature


def mes(fecha) -> str:
    f = pd.Timestamp(fecha)
    return f"{MESES[f.month - 1]} {f.year}"


def pct(x: float, d: int = 1) -> str:
    """Porcentaje en formato es-CO; espacio no separable para que '%' no se parta de línea."""
    return f"{x * 100:,.{d}f} %".replace(",", "X").replace(".", ",").replace("X", ".")


def num(x: float) -> str:
    return f"{x:,.0f}".replace(",", ".")


def dec(x: float, d: int = 2) -> str:
    """Número con coma decimal (formato es-CO)."""
    return f"{x:,.{d}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def style(fig: go.Figure, height: int = 380, legend: bool = False) -> go.Figure:
    fig.update_layout(
        height=height, margin=dict(l=8, r=8, t=72 if legend else 40, b=8),
        paper_bgcolor=SURFACE, plot_bgcolor=SURFACE, separators=",.",
        font=dict(family=FONT, size=13, color=INK_2),
        title=dict(font=dict(size=15, color=INK), y=0.985, yanchor="top", yref="container",
                   x=0.01, xanchor="left"),
        hoverlabel=dict(bgcolor="white", font_size=13,
                        font_family=FONT, bordercolor=GRID),
        showlegend=legend,
        legend=dict(orientation="h", yanchor="bottom", y=1.01, xanchor="left", x=0,
                    font=dict(color=INK_2)),
    )
    fig.update_xaxes(gridcolor=GRID, linecolor=GRAY, zerolinecolor=GRAY,
                     tickfont=dict(color=MUTED))
    fig.update_yaxes(gridcolor=GRID, linecolor=GRAY, zerolinecolor=GRAY,
                     tickfont=dict(color=MUTED))
    return fig


def chart(fig: go.Figure, key: str | None = None) -> None:
    cfg = {"displaylogo": False,
           "modeBarButtonsToRemove": ["lasso2d", "select2d"]}
    try:
        st.plotly_chart(fig, width="stretch", config=cfg, key=key)
    except TypeError:  # Streamlit < 1.46
        st.plotly_chart(fig, use_container_width=True, config=cfg, key=key)


def callout(text: str, kind: str = "info") -> None:
    {"info": st.info, "ok": st.success, "warn": st.warning}[kind](text)


# ---------------------------------------------------------------------------
# Carga de datos
# ---------------------------------------------------------------------------
REQUIRED = ["kpis_mensuales.parquet", "resumen_mensual.parquet", "perfil_clientes.parquet",
            "edades.parquet", "penetracion.parquet", "afinidad.parquet",
            "transiciones.parquet", "baseline_popularidad.parquet", "calidad.json"]


@st.cache_data(show_spinner=False)
def load_data() -> dict:
    d = {name.split(".")[0]: pd.read_parquet(DATA / name)
         for name in REQUIRED if name.endswith(".parquet")}
    d["calidad"] = json.loads(
        (DATA / "calidad.json").read_text(encoding="utf-8"))
    for key in ("kpis_mensuales", "resumen_mensual", "baseline_popularidad"):
        d[key]["fecha"] = pd.to_datetime(d[key]["fecha"])
    return d


@st.cache_data(show_spinner=False)
def load_model_results() -> dict:
    """Resultados del notebook; si existe la salida de train.py, la usa en su lugar."""
    res = json.loads(
        (DATA / "resultados_modelo.json").read_text(encoding="utf-8"))
    res["origen"] = "notebook"
    full = DATA / "modelo" / "metrics.json"
    if full.exists():
        m = json.loads(full.read_text(encoding="utf-8"))
        label = {"popularidad": "Popularidad (base)", "lightgbm": "LightGBM"}
        res["prueba"] = [{"modelo": label.get(r["modelo"], r["modelo"]), "map7": r["MAP@7"],
                          "hit_rate": r["hit_rate@7"]} for r in m["test_metrics"]]
        res["comparacion_validacion"] = [
            {"modelo": label.get(r["modelo"], r["modelo"]),
             "map7": r["MAP@7"], "pr_auc": None}
            for r in m["validation_comparison"]]
        res["importancia_variables"] = [{"feature": r["feature"], "gain": r["importance"]}
                                        for r in m["top_global_features"][:15]]
        cuts = m["temporal_cuts"]
        res["cortes_temporales"].update({
            "train_hasta": cuts["train_max_feature_month"], "validacion": cuts["validation_month"],
            "prueba": cuts["test_month"], "inferencia": cuts["inference_month"]})
        diag = m.get("bias_variance_diagnosis", {})
        if diag:
            res["diagnostico"] = {"train_map7": diag["train_MAP_at_7"],
                                  "validacion_map7": diag["validation_MAP_at_7"],
                                  "gap": diag["train_validation_gap"]}
        biz = m.get("business_simulation", {})
        if biz:
            n = biz["assumed_contacts"] / 1000
            res["negocio_por_1000_contactos"] = {
                "modelo": biz["observed_model_successes_at_7"] / n,
                "base": biz["observed_baseline_successes_at_7"] / n}
        if m.get("example_recommendations"):
            res["ejemplo_recomendacion"] = {
                "ncodpers": m.get("example_customer_id"),
                "mes_base": cuts["inference_month"],
                "items": [{"product": r["producto"], "score": r["score"]}
                          for r in m["example_recommendations"]]}
        seg_csv = DATA / "modelo" / "test_metrics_by_segment.csv"
        if seg_csv.exists():
            seg = pd.read_csv(seg_csv)
            dim = {"age_band": "Edad", "income_band": "Renta", "segmento": "Segmento",
                   "sexo": "Sexo"}
            res["por_segmento"] = [
                {"dimension": dim.get(r.segmento, r.segmento), "valor": str(r.segmento_valor),
                 "clientes": int(r.clientes), "map7": r.MAP_at_7, "hit_rate": r.hit_rate_at_7}
                for r in seg.itertuples()]
        res["alcance"] = (f"Dataset completo ({num(m['rows']['train'])} filas de "
                          "entrenamiento)")
        res["origen"] = "train.py"
    return res


# ---------------------------------------------------------------------------
# Página
# ---------------------------------------------------------------------------
st.set_page_config(page_title="FINSIR",
                   page_icon="", layout="wide")
st.markdown("""
<style>
  .block-container {padding-top: 2.2rem; max-width: 1250px;}
  [data-testid="stMetricValue"] {font-size: 1.9rem;}
  .kicker {color:#2a78d6; font-weight:600; letter-spacing:.06em; text-transform:uppercase;
           font-size:.8rem; margin-bottom:-.4rem;}
  .lead {font-size:1.12rem; color:#52514e; line-height:1.55;}
  .step {border:1px solid rgba(11,11,11,.10); border-radius:10px; padding:.9rem 1rem;
         background:#fcfcfb; height:100%;}
  .step b {color:#0b0b0b;}
  .step .n {color:#2a78d6; font-weight:700; font-size:.85rem;}
  .big {font-size:3.2rem; font-weight:700; color:#0b0b0b; line-height:1;}
  .big-sub {color:#52514e;}
</style>
""", unsafe_allow_html=True)

missing = [f for f in REQUIRED +
           ["resultados_modelo.json"] if not (DATA / f).exists()]
if missing:
    st.title("FINSIR · faltan los datos del dashboard")
    st.error(
        "No encuentro estos archivos en `visualizacion/datos/`: " + ", ".join(missing))
    st.markdown("Genéralos una vez (tarda unos minutos) con el CSV de Kaggle en "
                "`data/train_ver2.csv`:")
    st.code("python preparar_datos.py", language="bash")
    st.stop()

D = load_data()
M = load_model_results()
Q = D["calidad"]
KPI = D["kpis_mensuales"].copy()
KPI["nombre"] = KPI["product"].map(pname)
RES = D["resumen_mensual"].copy()
RES["pct_compran"] = RES.clients_with_adds / \
    RES.clients_with_prev.where(RES.clients_with_prev > 0)
LAST = pd.Timestamp(Q["mes_referencia"])
KPI_LAST = KPI[KPI.fecha == LAST]

SECCIONES = ["1 · El problema", "2 · Los datos",
             "3 · Cómo lo hicimos", "4 · Conclusiones"]
if "seccion" not in st.session_state:
    st.session_state.seccion = SECCIONES[0]


def mover(delta: int) -> None:
    i = SECCIONES.index(st.session_state.seccion)
    st.session_state.seccion = SECCIONES[max(
        0, min(len(SECCIONES) - 1, i + delta))]


def nav_buttons(where: str) -> None:
    st.write("")
    i = SECCIONES.index(st.session_state.seccion)
    c1, _, c2 = st.columns([1, 3, 1])
    if i > 0:
        with c1:
            st.button("← Anterior", on_click=mover, args=(-1,), key=f"prev_{where}",
                      width="stretch")
    if i < len(SECCIONES) - 1:
        with c2:
            st.button("Siguiente →", on_click=mover, args=(1,), key=f"next_{where}",
                      type="primary", width="stretch")


with st.sidebar:
    st.markdown("## FINSIR")
    st.caption("Sistema Inteligente de Recomendación de Productos Financieros")
    st.radio("Recorrido", SECCIONES, key="seccion")
    i_sec = SECCIONES.index(st.session_state.seccion)
    st.progress((i_sec + 1) / len(SECCIONES),
                text=f"Sección {i_sec + 1} de {len(SECCIONES)}")
    st.divider()
    st.caption("**Equipo:** Manuela Castaño Franco y Natalia Ceballos Posada")
    st.caption(
        "Proyecto Integrador · Énfasis en Ciencia de Datos · Universidad EAFIT · 2026")
    st.caption("Datos: *Santander Product Recommendation* (Kaggle, 2016).")

sec = st.session_state.seccion

# ===========================================================================
# 1 · EL PROBLEMA
# ===========================================================================
if sec == SECCIONES[0]:
    st.title("¿Qué producto financiero querrá cada cliente el próximo mes?")

    c = st.columns(4)
    c[0].metric("Registros cliente-mes",
                f"{Q['filas'] / 1e6:,.1f} M".replace(".", ","))
    c[1].metric("Clientes únicos", num(Q["clientes"]))
    c[2].metric("Meses de historia", f"{Q['meses']}",
                help=f"{mes(Q['fecha_min'])} a {mes(Q['fecha_max'])}")
    c[3].metric("Productos del portafolio", f"{Q['productos']}")

    st.subheader("Comprar algo nuevo es un evento raro")
    avg_buy = RES.pct_compran.mean()
    left, right = st.columns([3, 2])
    with left:
        r = RES.dropna(subset=["pct_compran"])
        fig = go.Figure(go.Scatter(
            x=r.fecha.map(mes), y=r.pct_compran, mode="lines+markers",
            line=dict(color=BLUE, width=2), marker=dict(size=8, color=BLUE),
            customdata=r[["clients_with_adds", "clients_with_prev"]],
            hovertemplate="%{x}<br><b>%{y:.2%}</b> de los clientes adquirió algo"
                          "<br>%{customdata[0]:,} de %{customdata[1]:,}<extra></extra>"))
        months_x = r.fecha.map(mes)
        fig.add_trace(go.Scatter(
            x=months_x,
            y=[avg_buy] * len(months_x),
            mode="lines",  # Solo dibuja la línea, sin puntos visibles
            name="Promedio",
            line=dict(color=ORANGE, width=1.5, dash="dash"),
            hovertemplate=f"Promedio: {pct(avg_buy, 2)}<extra></extra>",
            hoverlabel=dict(bgcolor=ORANGE, font_color="white")
        ))
        fig.update_yaxes(tickformat=".1%", rangemode="tozero", title=None)
        fig.update_layout(
            title="% de clientes que adquiere al menos un producto nuevo en el mes")
        chart(style(fig, 340), "buyers")
    with right:
        st.markdown(
            f'<div class="big">{pct(avg_buy, 1)}</div>', unsafe_allow_html=True)
        st.markdown(
            f'<p class="big-sub">de los clientes adquiere un producto nuevo en un mes típico', unsafe_allow_html=True)
        st.markdown("Por eso no basta con saber **qué es popular**: hay que saber **qué le "
                    "sirve a cada cliente**.")

    st.subheader("Objetivo")
    st.success(
        "**Recomendar a cada cliente sus 7 productos más probables para el próximo mes.**")
    nav_buttons("s1")

# ===========================================================================
# 2 · LOS DATOS
# ===========================================================================
elif sec == SECCIONES[1]:
    st.title("¿Cómo son los clientes y qué productos tienen?")
    k = KPI_LAST.sort_values("penetration_rate")
    top = k.iloc[-1]
    colors_pen = [ORANGE if name == top.nombre else BLUE for name in k.nombre]

    left, right = st.columns([4, 1])

    with left:
        fig = go.Figure(go.Bar(
            x=k.penetration_rate, y=k.nombre, orientation="h",
            marker=dict(color=colors_pen, cornerradius=4),
            customdata=k[["holders"]],
            hovertemplate="<b>%{y}</b><br>%{x:.2%} de los clientes<br>%{customdata[0]:,} "
            "titulares<extra></extra>"))
        fig.update_xaxes(tickformat=".0%", title=None)
        fig.update_layout(
            title="Penetración: % de clientes que tiene cada producto", bargap=0.25)
        chart(style(fig, 620), "pen")

        prof = D["perfil_clientes"].copy()
        prof["Segmento"] = prof.segmento.map(
            SEGMENT_LABELS).fillna(prof.segmento)
        seg_opts = ["Todos"] + [s for s in ["VIP", "Particulares", "Universitario"]
                                if s in set(prof.Segmento)]

        st.subheader("Filtrar perfil por segmento")

        seg = st.segmented_control("", seg_opts, default="Todos",
                                   key="seg_perfil", label_visibility="collapsed") if hasattr(st, "segmented_control") else \
            st.radio("", seg_opts, horizontal=True,
                     label_visibility="collapsed")
        seg = seg or "Todos"
        p = prof if seg == "Todos" else prof[prof.Segmento == seg]
        tabs = st.tabs(["Edad", "Renta", "Segmento", "Actividad"])
        with tabs[0]:
            ages = D["edades"]
            if seg == "Todos":
                max_age = ages.clients.idxmax()
                age_colors = [ORANGE if idx ==
                              max_age else BLUE for idx in ages.index]
                fig = go.Figure(go.Bar(x=ages.age, y=ages.clients, marker_color=age_colors,
                                       hovertemplate="%{x} años: %{y:,} clientes<extra></extra>"))
                fig.update_layout(title="Clientes por edad", bargap=0.05)
                fig.update_xaxes(range=[0, 100], title=None)
            else:
                a = p.groupby("age_band", as_index=False).clients.sum(
                ).sort_values("age_band")
                age_colors = [ORANGE if idx ==
                              a.clients.idxmax() else BLUE for idx in a.index]
                fig = go.Figure(go.Bar(x=a.age_band, y=a.clients, marker=dict(color=age_colors, cornerradius=4),
                                       hovertemplate="%{x}: %{y:,} clientes<extra></extra>"))
                fig.update_layout(title=f"Clientes por rango de edad · {seg}")
            chart(style(fig, 300), "ages")
        with tabs[1]:
            a = p.groupby("income_band", as_index=False).clients.sum(
            ).sort_values("income_band")
            a["income_band"] = a.income_band.replace(
                {"desconocido": "Sin dato"})
            income_colors = [ORANGE if idx ==
                             a.clients.idxmax() else BLUE for idx in a.index]
            fig = go.Figure(go.Bar(x=a.income_band, y=a.clients / a.clients.sum(),
                                   marker=dict(color=income_colors,
                                               cornerradius=4),
                                   hovertemplate="%{x}: %{y:.1%}<extra></extra>"))
            fig.update_yaxes(tickformat=".0%")
            fig.update_layout(title="Renta bruta del hogar (EUR/año)")
            chart(style(fig, 300), "renta")
            st.caption(f"Renta sin dato: {pct(Q['pct_renta_nula'], 0)}.")
        with tabs[2]:
            a = prof.groupby("Segmento", as_index=False).agg(clients=("clients", "sum"),
                                                             prods=("sum_products", "sum"))
            a["avg"] = a.prods / a.clients
            segment_colors = [ORANGE if idx ==
                              a.clients.idxmax() else BLUE for idx in a.index]
            fig = go.Figure(go.Bar(x=a.Segmento, y=a.clients, marker=dict(color=segment_colors, cornerradius=4),
                                   customdata=a[["avg"]],
                                   hovertemplate="%{x}: %{y:,} clientes<br>%{customdata[0]:.2f} "
                                   "productos promedio<extra></extra>"))
            fig.update_layout(
                title="Clientes por segmento (todos los segmentos)")
            chart(style(fig, 300), "segm")
        with tabs[3]:
            a = p.groupby("actividad", as_index=False).clients.sum()
            activity_colors = [ORANGE if idx ==
                               a.clients.idxmax() else BLUE for idx in a.index]
            fig = go.Figure(go.Bar(x=a.actividad.str.capitalize(), y=a.clients / a.clients.sum(),
                                   marker=dict(color=activity_colors,
                                               cornerradius=4),
                                   hovertemplate="%{x}: %{y:.1%}<extra></extra>"))
            fig.update_yaxes(tickformat=".0%")
            fig.update_layout(title="Clientes activos vs. inactivos")
            chart(style(fig, 300), "activ")
    nav_buttons("s2")

elif sec == SECCIONES[2]:
    st.title("¿Cómo lo construimos?")

    steps = [
        ("1", "Ingesta · Bronze",
         f"{dec(Q['filas'] / 1e6, 1)} M filas de Kaggle a S3."),
        ("2", "Limpieza · Silver", "Glue + PySpark: validación y Parquet mensual."),
        ("3", "Variables · Gold", "Perfil e historial de productos (168 variables)."),
        ("4", "Modelo", "LightGBM ordena productos nuevos por probabilidad."),
        ("5", "Servicio", "API en ECS entrega recomendaciones."),
        ("6", "Dashboard", "Streamlit muestra perfiles y resultados."),
    ]
    cols = st.columns(3)
    for i, (n, title, body) in enumerate(steps):
        with cols[i % 3]:
            st.markdown(f'<div class="step"><span class="n">PASO {n}</span><br><b>{title}</b>'
                        f'<br><span style="color:#52514e">{body}</span></div>',
                        unsafe_allow_html=True)
            st.write("")

    with st.expander("Arquitectura AWS · Terraform", expanded=True):
        a, b = st.columns([3, 2])
        if ARCH_IMG.exists():
            a.image(str(ARCH_IMG))
        b.markdown(
            "- **EventBridge + Step Functions** orquestan Glue.\n"
            "- **S3** organiza Bronze, Silver y Gold; **Athena** consulta Gold.\n"
            "- **EC2** entrena el modelo; **ECS Fargate** sirve la API.\n"
            "- Infraestructura definida con **Terraform**.")

    st.subheader("Cómo se plantea el problema")
    l, r = st.columns([3, 2])
    with l:
        cuts = M["cortes_temporales"]
        months = pd.date_range("2015-01-01", "2016-05-01",
                               freq="MS") + pd.Timedelta(days=27)
        roles = []
        for f in months:
            fs = f.strftime("%Y-%m-%d")
            if fs <= cuts["train_hasta"]:
                roles.append("Entrenamiento")
            elif fs == cuts["validacion"]:
                roles.append("Validación")
            elif fs == cuts["prueba"]:
                roles.append("Prueba")
            else:
                roles.append("Inferencia (sin respuesta)")
        colors = {"Entrenamiento": BLUE, "Validación": "#2a78d6", "Prueba": ORANGE,
                  "Inferencia (sin respuesta)": GRAY}
        fig = go.Figure()
        for role, color in colors.items():
            xs = [mes(f) for f, rr in zip(months, roles) if rr == role]
            fig.add_trace(go.Bar(x=xs, y=[1] * len(xs), name=role,
                                 marker=dict(color=color, cornerradius=4),
                                 hovertemplate="%{x}: " + role + "<extra></extra>"))
        fig.update_yaxes(visible=False)
        fig.update_xaxes(categoryorder="array", categoryarray=[mes(f) for f in months],
                         tickangle=-45, showgrid=False)
        fig.update_layout(title="Corte temporal: cada mes predice las compras del mes siguiente",
                          bargap=0.15)
        chart(style(fig, 230, legend=True), "split")
    with r:
        st.markdown(
            "**Entrada:** perfil e historial hasta *t*.\n\n"
            "**Objetivo:** productos nuevos en *t+1*.\n\n"
            "**Evaluación:** meses futuros no vistos; mayo 2016 se reserva para recomendar.")
    nav_buttons("s3")

# ===========================================================================
# 4 · RESULTADOS
# ===========================================================================
elif sec == SECCIONES[3]:
    st.title("Conclusiones")

    test = {r["modelo"]: r for r in M["prueba"]}
    lgb_t, base_t = test["LightGBM"], test["Popularidad (base)"]
    lift = lgb_t["map7"] / base_t["map7"] - 1
    cuts = M["cortes_temporales"]

    l, r = st.columns([3, 2])
    with l:
        v = pd.DataFrame(M["comparacion_validacion"]).sort_values("map7")
        colors = [
            ORANGE if m == "LightGBM" else BLUE if "base" in m else GRAY for m in v.modelo]
        fig = go.Figure(go.Bar(
            x=v.map7, y=v.modelo, orientation="h", marker=dict(color=colors, cornerradius=4),
            text=[f"{x:.4f}".replace(".", ",") for x in v.map7], textposition="outside",
            textfont=dict(color=INK_2),
            hovertemplate="<b>%{y}</b><br>MAP@7 = %{x:.4f}<extra></extra>"))
        fig.update_xaxes(range=[0, v.map7.max() * 1.25], title=None)
        fig.update_layout(title=f"Validación ({mes(cuts['validacion'])}): MAP@7 por modelo",
                          bargap=0.45)
        chart(style(fig, 300), "val")
    with r:
        validacion = {row["modelo"]: row["map7"]
                      for row in M["comparacion_validacion"]}
        map_base = validacion["Popularidad (base)"]
        map_lightgbm = validacion["LightGBM"]
        mejora_validacion = map_lightgbm / map_base - 1
        escala = max(map_base, map_lightgbm)
        ancho_base = map_base / escala * 100
        ancho_lgb = map_lightgbm / escala * 100
        mejora_txt = f"{mejora_validacion * 100:.1f}".replace(".", ",")
        st.markdown(
            f'''
              <div style="color:#176b39;font-size:3rem;font-weight:750;line-height:1.15;margin:5px 0">
                ↑ {mejora_txt}%</div>
              <div style="color:#52514e;font-size:.9rem;margin-bottom:14px">LightGBM frente al baseline</div>
              ''',
            unsafe_allow_html=True)

    st.subheader("Recomendaciones para un cliente")

    ex = M["ejemplo_recomendacion"]
    st.caption(
        f"Cliente {ex['ncodpers']} · datos de {mes(ex['mes_base'])} · mes siguiente")
    e = pd.DataFrame(ex["items"])
    base_rows = D["baseline_popularidad"]
    base_rows = base_rows[base_rows.fecha == pd.Timestamp(ex["mes_base"])]
    if base_rows.empty:
        base_rows = D["baseline_popularidad"].sort_values("fecha").tail(1)
    baseline_products = str(base_rows.iloc[0]["top_7_products"]).split(",")
    baseline_products = [p for p in baseline_products if p and p != "nan"][:7]

    left, right = st.columns(2)
    with left:
        model_plot = e.sort_values("score", ascending=False).copy()
        model_plot["puesto"] = range(1, len(model_plot) + 1)
        model_plot["prioridad"] = len(model_plot) + 1 - model_plot["puesto"]
        colors_model = [ORANGE if rank ==
                        1 else BLUE for rank in model_plot.puesto]
        fig = go.Figure(go.Bar(
            x=model_plot.prioridad, y=model_plot["product"].map(pname), orientation="h",
            marker=dict(color=colors_model, cornerradius=4),
            customdata=model_plot[["puesto", "score"]],
            hovertemplate="Puesto %{customdata[0]} · propensión %{customdata[1]:.4f}"
                          "<br><b>%{y}</b><extra></extra>"))
        fig.update_layout(title="FINSIR · LightGBM", xaxis_title="Propensión %",
                          xaxis=dict(range=[0, 7.5], dtick=1),
                          yaxis=dict(categoryorder="array",
                                     categoryarray=model_plot["product"].map(
                                         pname).tolist(),
                                     autorange="reversed"))
        chart(style(fig, 340), "example_model")
    with right:
        baseline_plot = pd.DataFrame({"product": baseline_products,
                                      "puesto": range(1, len(baseline_products) + 1)})
        baseline_plot["prioridad"] = len(
            baseline_plot) + 1 - baseline_plot["puesto"]
        colors_base = [ORANGE if rank ==
                       1 else BLUE for rank in baseline_plot.puesto]
        fig = go.Figure(go.Bar(
            x=baseline_plot.prioridad, y=baseline_plot["product"].map(pname), orientation="h",
            marker=dict(color=colors_base, cornerradius=4), customdata=baseline_plot.puesto,
            hovertemplate="Puesto %{customdata}<br><b>%{y}</b><extra></extra>"))
        fig.update_layout(title="Baseline · popularidad", xaxis_title="Prioridad",
                          xaxis=dict(range=[0, 7.5], dtick=1),
                          yaxis=dict(categoryorder="array",
                                     categoryarray=baseline_plot["product"].map(
                                         pname).tolist(),
                                     autorange="reversed"))
        chart(style(fig, 340), "example_baseline")
        test_metrics = {r["modelo"]: r for r in M["prueba"]}
        baseline_map7 = test_metrics["Popularidad (base)"]["map7"]
    nav_buttons("s4")
