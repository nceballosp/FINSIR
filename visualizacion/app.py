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

# ---------------------------------------------------------------------------
# Paleta (validada para daltonismo) y estilo de gráficos
# ---------------------------------------------------------------------------
BLUE = "#2a78d6"       # serie principal / modelo
ORANGE = "#eb6834"     # serie de comparación / modelo base
GRAY = "#c3c2b7"       # contexto (emphasis: resaltar uno, gris el resto)
INK = "#0b0b0b"
INK_2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
SURFACE = "#fcfcfb"
SEQ_BLUE = [[0.0, "#f4f8fd"], [0.15, "#cde2fb"], [0.3, "#9ec5f4"], [0.45, "#6da7ec"],
            [0.6, "#3987e5"], [0.75, "#256abf"], [0.9, "#184f95"], [1.0, "#0d366b"]]
DIVERGING = [[0.0, "#c43c3c"], [0.25, "#ec9a99"], [0.5, "#f0efec"],
             [0.75, "#86b6ef"], [1.0, "#1c5cab"]]
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
MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]


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
        hoverlabel=dict(bgcolor="white", font_size=13, font_family=FONT, bordercolor=GRID),
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
    cfg = {"displaylogo": False, "modeBarButtonsToRemove": ["lasso2d", "select2d"]}
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
    d["calidad"] = json.loads((DATA / "calidad.json").read_text(encoding="utf-8"))
    for key in ("kpis_mensuales", "resumen_mensual", "baseline_popularidad"):
        d[key]["fecha"] = pd.to_datetime(d[key]["fecha"])
    return d


@st.cache_data(show_spinner=False)
def load_model_results() -> dict:
    """Resultados del notebook; si existe la salida de train.py, la usa en su lugar."""
    res = json.loads((DATA / "resultados_modelo.json").read_text(encoding="utf-8"))
    res["origen"] = "notebook"
    full = DATA / "modelo" / "metrics.json"
    if full.exists():
        m = json.loads(full.read_text(encoding="utf-8"))
        label = {"popularidad": "Popularidad (base)", "lightgbm": "LightGBM"}
        res["prueba"] = [{"modelo": label.get(r["modelo"], r["modelo"]), "map7": r["MAP@7"],
                          "hit_rate": r["hit_rate@7"]} for r in m["test_metrics"]]
        res["comparacion_validacion"] = [
            {"modelo": label.get(r["modelo"], r["modelo"]), "map7": r["MAP@7"], "pr_auc": None}
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
st.set_page_config(page_title="FINSIR · Recomendación de productos financieros",
                   page_icon="🏦", layout="wide")
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

missing = [f for f in REQUIRED + ["resultados_modelo.json"] if not (DATA / f).exists()]
if missing:
    st.title("FINSIR · faltan los datos del dashboard")
    st.error("No encuentro estos archivos en `visualizacion/datos/`: " + ", ".join(missing))
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
RES["pct_compran"] = RES.clients_with_adds / RES.clients_with_prev.where(RES.clients_with_prev > 0)
LAST = pd.Timestamp(Q["mes_referencia"])
KPI_LAST = KPI[KPI.fecha == LAST]

SECCIONES = ["1 · El problema", "2 · Los datos", "3 · Patrones de contratación",
             "4 · Cómo lo hicimos", "5 · Resultados", "6 · Conclusiones"]
if "seccion" not in st.session_state:
    st.session_state.seccion = SECCIONES[0]


def mover(delta: int) -> None:
    i = SECCIONES.index(st.session_state.seccion)
    st.session_state.seccion = SECCIONES[max(0, min(len(SECCIONES) - 1, i + delta))]


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
    st.markdown("## 🏦 FINSIR")
    st.caption("Sistema Inteligente de Recomendación de Productos Financieros")
    st.radio("Recorrido (≈ 5 min)", SECCIONES, key="seccion")
    i_sec = SECCIONES.index(st.session_state.seccion)
    st.progress((i_sec + 1) / len(SECCIONES), text=f"Sección {i_sec + 1} de {len(SECCIONES)}")
    st.divider()
    st.caption("**Equipo:** Juan Felipe Restrepo Buitrago · Manuela Castaño Franco · "
               "Juan Esteban García Galvis · Eduardo Andrés Piñeros Manjarres · "
               "Natalia Ceballos Posada")
    st.caption("Proyecto Integrador · Énfasis en Ciencia de Datos · Universidad EAFIT · 2026")
    st.caption("Datos: *Santander Product Recommendation* (Kaggle, 2016).")

sec = st.session_state.seccion

# ===========================================================================
# 1 · EL PROBLEMA
# ===========================================================================
if sec == SECCIONES[0]:
    st.markdown('<p class="kicker">Proyecto Integrador · FINSIR</p>', unsafe_allow_html=True)
    st.title("¿Qué producto financiero querrá cada cliente el próximo mes?")
    st.markdown(
        '<p class="lead">Los bancos suelen vender por <b>campañas masivas</b>: le ofrecen lo '
        'mismo a todos. Eso cuesta dinero, satura los canales y desgasta la relación con el '
        'cliente (spam comercial). <b>FINSIR</b> usa el historial de 1,5 años de clientes del '
        'Banco Santander para recomendarle a cada persona los <b>7 productos</b> que es más '
        'probable que adquiera el mes siguiente.</p>', unsafe_allow_html=True)

    c = st.columns(4)
    c[0].metric("Registros cliente-mes", f"{Q['filas'] / 1e6:,.1f} M".replace(".", ","))
    c[1].metric("Clientes únicos", num(Q["clientes"]))
    c[2].metric("Meses de historia", f"{Q['meses']}", help=f"{mes(Q['fecha_min'])} a {mes(Q['fecha_max'])}")
    c[3].metric("Productos del portafolio", f"{Q['productos']}")

    st.subheader("La justificación: comprar algo nuevo es un evento raro")
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
        fig.add_hline(y=avg_buy, line=dict(color=MUTED, width=1),
                      annotation_text=f"promedio {pct(avg_buy, 2)}",
                      annotation_font_color=INK_2, annotation_position="top right")
        fig.update_yaxes(tickformat=".1%", rangemode="tozero", title=None)
        fig.update_layout(title="% de clientes que adquiere al menos un producto nuevo en el mes")
        chart(style(fig, 340), "buyers")
    with right:
        st.markdown(f'<div class="big">{pct(avg_buy, 1)}</div>', unsafe_allow_html=True)
        st.markdown(f'<p class="big-sub">de los clientes adquiere un producto nuevo en un mes '
                    f'típico. Si se le ofrece lo mismo a todos, <b>~{round((1 - avg_buy) * 100)} '
                    f'de cada 100</b> contactos llegan a alguien que ese mes no va a comprar '
                    f'nada.</p>', unsafe_allow_html=True)
        st.markdown("Por eso no basta con saber **qué es popular**: hay que saber **qué le "
                    "sirve a cada cliente y en qué orden ofrecérselo**.")

    st.subheader("🎯 Objetivo")
    st.success(
        "**Predecir, para cada cliente, un ranking de los 7 productos que tiene más "
        "probabilidad de adquirir el mes siguiente** (excluyendo los que ya tiene) y "
        "**superar al modelo base de popularidad** —ofrecer a todos los productos más vendidos— "
        "en la métrica oficial de la competencia, **MAP@7**.")
    st.caption("Además del modelo, el proyecto entrega la plataforma de datos en AWS que lo "
               "alimenta, una API REST que sirve las recomendaciones y este tablero.")
    nav_buttons("s1")

# ===========================================================================
# 2 · LOS DATOS
# ===========================================================================
elif sec == SECCIONES[1]:
    st.markdown('<p class="kicker">Comprensión de los datos</p>', unsafe_allow_html=True)
    st.title("¿Cómo son los clientes y qué productos tienen?")
    st.markdown(f'<p class="lead">Cada fila es un cliente en un mes: su perfil '
                f'(edad, renta, segmento, antigüedad…) y 24 banderas 0/1 que dicen qué productos '
                f'tiene. Las cifras de esta sección son del mes más reciente '
                f'(<b>{mes(LAST)}</b>, {num(KPI_LAST.clients.iloc[0])} clientes).</p>',
                unsafe_allow_html=True)

    left, right = st.columns([1, 1])
    with left:
        k = KPI_LAST.sort_values("penetration_rate")
        top = k.iloc[-1]
        fig = go.Figure(go.Bar(
            x=k.penetration_rate, y=k.nombre, orientation="h",
            marker=dict(color=BLUE, cornerradius=4),
            customdata=k[["holders"]],
            hovertemplate="<b>%{y}</b><br>%{x:.2%} de los clientes<br>%{customdata[0]:,} "
                          "titulares<extra></extra>"))
        fig.update_xaxes(tickformat=".0%", title=None)
        fig.update_layout(title="Penetración: % de clientes que tiene cada producto", bargap=0.25)
        chart(style(fig, 620), "pen")
    with right:
        callout(f"**Portafolio muy concentrado.** La **{top.nombre}** la tiene el "
                f"{pct(top.penetration_rate, 0)} de los clientes, mientras que "
                f"**{int((KPI_LAST.penetration_rate < 0.01).sum())} de los 24** productos no "
                f"llegan al 1 %. En promedio cada cliente tiene "
                f"**{dec(Q['productos_promedio'], 2)}** productos.")
        prof = D["perfil_clientes"].copy()
        prof["Segmento"] = prof.segmento.map(SEGMENT_LABELS).fillna(prof.segmento)
        seg_opts = ["Todos"] + [s for s in ["VIP", "Particulares", "Universitario"]
                                if s in set(prof.Segmento)]
        seg = st.segmented_control("Filtrar perfil por segmento", seg_opts, default="Todos",
                                   key="seg_perfil") if hasattr(st, "segmented_control") else \
            st.radio("Filtrar perfil por segmento", seg_opts, horizontal=True)
        seg = seg or "Todos"
        p = prof if seg == "Todos" else prof[prof.Segmento == seg]
        tabs = st.tabs(["Edad", "Renta", "Segmento", "Actividad"])
        with tabs[0]:
            ages = D["edades"]
            if seg == "Todos":
                fig = go.Figure(go.Bar(x=ages.age, y=ages.clients, marker_color=BLUE,
                                       hovertemplate="%{x} años: %{y:,} clientes<extra></extra>"))
                fig.update_layout(title="Clientes por edad", bargap=0.05)
                fig.update_xaxes(range=[0, 100], title=None)
            else:
                a = p.groupby("age_band", as_index=False).clients.sum().sort_values("age_band")
                fig = go.Figure(go.Bar(x=a.age_band, y=a.clients, marker=dict(color=BLUE, cornerradius=4),
                                       hovertemplate="%{x}: %{y:,} clientes<extra></extra>"))
                fig.update_layout(title=f"Clientes por rango de edad · {seg}")
            chart(style(fig, 300), "ages")
            st.caption("Dos grupos claros: jóvenes de 21-25 años (universitarios) y adultos "
                       "de 40-50 años.")
        with tabs[1]:
            a = p.groupby("income_band", as_index=False).clients.sum().sort_values("income_band")
            a["income_band"] = a.income_band.replace({"desconocido": "Sin dato"})
            fig = go.Figure(go.Bar(x=a.income_band, y=a.clients / a.clients.sum(),
                                   marker=dict(color=BLUE, cornerradius=4),
                                   hovertemplate="%{x}: %{y:.1%}<extra></extra>"))
            fig.update_yaxes(tickformat=".0%")
            fig.update_layout(title="Renta bruta del hogar (EUR/año)")
            chart(style(fig, 300), "renta")
            st.caption(f"La renta falta en el {pct(Q['pct_renta_nula'], 0)} de los registros; "
                       "no se imputa, se trata como 'Sin dato'.")
        with tabs[2]:
            a = prof.groupby("Segmento", as_index=False).agg(clients=("clients", "sum"),
                                                              prods=("sum_products", "sum"))
            a["avg"] = a.prods / a.clients
            fig = go.Figure(go.Bar(x=a.Segmento, y=a.clients, marker=dict(color=BLUE, cornerradius=4),
                                   customdata=a[["avg"]],
                                   hovertemplate="%{x}: %{y:,} clientes<br>%{customdata[0]:.2f} "
                                                 "productos promedio<extra></extra>"))
            fig.update_layout(title="Clientes por segmento (todos los segmentos)")
            chart(style(fig, 300), "segm")
        with tabs[3]:
            a = p.groupby("actividad", as_index=False).clients.sum()
            fig = go.Figure(go.Bar(x=a.actividad.str.capitalize(), y=a.clients / a.clients.sum(),
                                   marker=dict(color=BLUE, cornerradius=4),
                                   hovertemplate="%{x}: %{y:.1%}<extra></extra>"))
            fig.update_yaxes(tickformat=".0%")
            fig.update_layout(title="Clientes activos vs. inactivos")
            chart(style(fig, 300), "activ")

    st.subheader("¿Quién tiene qué? Penetración por tipo de cliente")
    dim = st.selectbox("Comparar por", list(DIMENSIONS), format_func=DIMENSIONS.get, key="dim_heat")
    pen = D["penetracion"]
    pen = pen[(pen.dimension == dim) & (pen.dimension_value != "desconocido")].copy()
    order_products = KPI_LAST.sort_values("penetration_rate", ascending=False)["product"].tolist()[:16]
    pen = pen[pen["product"].isin(order_products)]
    mat = pen.pivot(index="dimension_value", columns="product", values="penetration_rate")[order_products]
    rows = [SEGMENT_LABELS.get(v, v) for v in mat.index]
    fig = go.Figure(go.Heatmap(
        z=mat.values, x=[pname(p) for p in mat.columns], y=rows, colorscale=SEQ_BLUE,
        zmin=0, zmax=min(1, float(mat.values.max())),
        colorbar=dict(title="% clientes", tickformat=".0%", thickness=12),
        texttemplate="%{z:.0%}", textfont=dict(size=10),
        hovertemplate="<b>%{x}</b><br>%{y}: %{z:.1%} lo tiene<extra></extra>", xgap=2, ygap=2))
    fig.update_layout(title=f"% de clientes con cada producto, por {DIMENSIONS[dim].lower()} "
                            "(16 productos más comunes)")
    fig.update_xaxes(tickangle=-35, showgrid=False)
    fig.update_yaxes(showgrid=False, autorange="reversed")
    chart(style(fig, 360 + 18 * len(rows)), "heat")
    st.caption("Ejemplos de lectura: los universitarios casi solo tienen cuenta corriente; "
               "nómina, pensión y débito automático se concentran en clientes activos (en los "
               "inactivos son casi 0 %) y en el segmento VIP. El perfil del cliente sí cambia "
               "qué conviene ofrecer.")
    nav_buttons("s2")

# ===========================================================================
# 3 · PATRONES DE CONTRATACIÓN
# ===========================================================================
elif sec == SECCIONES[2]:
    st.markdown('<p class="kicker">Exploración de patrones</p>', unsafe_allow_html=True)
    st.title("¿Cuándo, qué y después de qué compran los clientes?")

    st.subheader("Altas mensuales: hay estacionalidad")
    adds = KPI.dropna(subset=["popularity_rank"])
    topk = adds.groupby("product").adds.sum().sort_values(ascending=False).index[:12].tolist()
    a = adds[adds["product"].isin(topk)]
    mat = a.pivot(index="product", columns="fecha", values="adds").loc[topk]
    # Índice: altas del mes ÷ promedio mensual del producto (1 = mes normal). Así los
    # productos pequeños (p. ej. Impuestos) se comparan con los grandes.
    idx = mat.div(mat.mean(axis=1), axis=0)
    fig = go.Figure(go.Heatmap(
        z=idx.values, x=[mes(f) for f in mat.columns], y=[pname(p) for p in mat.index],
        customdata=mat.values, colorscale=DIVERGING, zmin=0, zmax=2, zmid=1,
        colorbar=dict(title="vs. su<br>promedio", thickness=12, tickvals=[0, 0.5, 1, 1.5, 2],
                      ticktext=["0×", "0,5×", "1× (normal)", "1,5×", "≥2×"]),
        xgap=2, ygap=2,
        hovertemplate="<b>%{y}</b><br>%{x}: %{customdata:,} altas<br>%{z:.1f}× su promedio "
                      "mensual<extra></extra>"))
    fig.update_layout(title="Altas de cada producto mes a mes, comparadas con su propio promedio "
                            "(azul = más de lo normal, rojo = menos)")
    fig.update_yaxes(autorange="reversed", showgrid=False)
    fig.update_xaxes(showgrid=False)
    chart(style(fig, 430), "season")

    col1, col2 = st.columns([1, 2])
    with col1:
        prod = st.selectbox("Ver detalle de un producto", topk, format_func=pname, key="prod_det")
        kp = adds[adds["product"] == prod]
        best = kp.loc[kp.adds.idxmax()]
        st.metric("Mes con más altas", mes(best.fecha), help=f"{num(best.adds)} altas ese mes")
        st.metric("Tasa de adopción promedio", pct(kp.add_rate.mean(), 2),
                  help="Altas ÷ clientes que podían adquirirlo (no lo tenían el mes anterior)")
    with col2:
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=kp.fecha.map(mes), y=kp.adds, name="Altas", mode="lines+markers",
                                 line=dict(color=BLUE, width=2), marker=dict(size=8),
                                 hovertemplate="%{x}: %{y:,} altas<extra></extra>"))
        fig.add_trace(go.Scatter(x=kp.fecha.map(mes), y=kp.drops, name="Bajas", mode="lines+markers",
                                 line=dict(color=ORANGE, width=2), marker=dict(size=8),
                                 hovertemplate="%{x}: %{y:,} bajas<extra></extra>"))
        fig.update_layout(title=f"{pname(prod)}: altas vs. bajas por mes", hovermode="x unified")
        fig.update_yaxes(rangemode="tozero")
        chart(style(fig, 300, legend=True), "detail")
    callout("Las altas no son parejas en el año: **Impuestos** se dispara en **junio** "
            "(temporada de declaración de renta en España), **cuenta corriente** tiene picos en "
            "junio y diciembre, y **nómina/pensión** en junio 2015 y febrero 2016. Por eso el "
            "modelo recibe el **mes del año** como variable (y junio, el mes que pide Kaggle, es "
            "un riesgo identificado).")

    st.subheader("¿Qué tenía el cliente justo antes de adquirir un producto?")
    tr = D["transiciones"]
    to_opts = tr.groupby("to_product").to_product_adds.first().sort_values(ascending=False).index.tolist()
    sel = st.multiselect("Productos adquiridos (destino)", to_opts, default=to_opts[:5],
                         format_func=pname, max_selections=8, key="sankey_to")
    if sel:
        t = tr[tr.to_product.isin(sel)].copy()
        top_from = t.groupby("from_product").clients.sum().sort_values(ascending=False).index[:8]
        t["src"] = t.from_product.where(t.from_product.isin(top_from), "otros")
        t = t.groupby(["src", "to_product"], as_index=False).clients.sum()
        srcs = t.groupby("src").clients.sum().sort_values(ascending=False).index.tolist()
        labels = [("Otros productos" if s == "otros" else pname(s)) + " (antes)" for s in srcs] + \
                 [pname(p) for p in sel]
        idx_s = {s: i for i, s in enumerate(srcs)}
        idx_t = {p: len(srcs) + i for i, p in enumerate(sel)}
        fig = go.Figure(go.Sankey(
            arrangement="snap",
            node=dict(label=labels, pad=14, thickness=14, line=dict(width=0),
                      color=[GRAY] * len(srcs) + [BLUE] * len(sel),
                      hovertemplate="%{label}: %{value:,}<extra></extra>"),
            link=dict(source=t.src.map(idx_s), target=t.to_product.map(idx_t), value=t.clients,
                      color="rgba(42,120,214,0.22)",
                      hovertemplate="%{source.label} → %{target.label}<br>%{value:,} clientes"
                                    "<extra></extra>")))
        fig.update_layout(title="Productos que tenía en el mes anterior → producto que adquirió "
                                "(acumulado feb 2015 – may 2016)")
        chart(style(fig, 470), "sankey")
        st.caption("Un cliente con 3 productos que adquiere 1 aporta 3 enlaces. La mayoría de "
                   "quienes adquieren débito automático, cuenta nómina o depósitos ya tenía "
                   "**cuenta corriente**, y quien llega sin productos casi siempre empieza por "
                   "cuenta junior o cuenta corriente: la **historia de tenencia** es una gran "
                   "pista de lo que viene.")

    st.subheader("¿Qué productos se tienen juntos?")
    aff = D["afinidad"]
    c1, c2 = st.columns([1, 3])
    with c1:
        metric = st.radio("Medida", ["phi", "lift"], key="aff_metric",
                          format_func={"phi": "Correlación (phi)", "lift": "Lift"}.get)
        n_top = st.slider("Productos (más comunes)", 6, 20, 14, key="aff_n")
        st.caption("**phi**: correlación entre tener A y tener B (−1 a 1). **lift**: cuántas "
                   "veces más se tienen juntos que si fuera azar (1 = azar).")
    keep = KPI_LAST.sort_values("penetration_rate", ascending=False)["product"].tolist()[:n_top]
    a = aff[aff.product_a.isin(keep) & aff.product_b.isin(keep)]
    mat = a.pivot(index="product_a", columns="product_b", values=metric).reindex(index=keep, columns=keep)
    names = [pname(p) for p in keep]
    if metric == "phi":
        z, zmin, zmax, zmid, scale, fmt = mat.values, -0.5, 0.5, 0, DIVERGING, ".2f"
    else:
        z = np.log2(mat.values.astype(float))
        zmin, zmax, zmid, scale, fmt = -3, 3, 0, DIVERGING, ".2f"
    with c2:
        fig = go.Figure(go.Heatmap(
            z=z, x=names, y=names, colorscale=scale, zmin=zmin, zmax=zmax, zmid=zmid,
            customdata=mat.values, xgap=2, ygap=2,
            colorbar=dict(title="phi" if metric == "phi" else "log₂ lift", thickness=12),
            hovertemplate="<b>%{y}</b> y <b>%{x}</b><br>" + metric + ": %{customdata:" + fmt
                          + "}<extra></extra>"))
        fig.update_xaxes(tickangle=-40, showgrid=False)
        fig.update_yaxes(autorange="reversed", showgrid=False)
        fig.update_layout(title=f"Afinidad entre productos · {mes(LAST)} (azul = van juntos)")
        chart(style(fig, 560), "aff")
    callout("Nómina, pensión, cuenta nómina y débito automático forman un **bloque** que se "
            "tiene junto (azul intenso): quien tiene uno es candidato a los otros. Estas "
            "relaciones son las que el modelo aprende a partir de la tenencia actual y pasada.")
    nav_buttons("s3")

# ===========================================================================
# 4 · CÓMO LO HICIMOS
# ===========================================================================
elif sec == SECCIONES[3]:
    st.markdown('<p class="kicker">Metodología (CRISP-DM)</p>', unsafe_allow_html=True)
    st.title("¿Cómo lo construimos?")

    steps = [
        ("1", "Ingesta (Bronze)", f"CSV de Kaggle de 2,3 GB ({dec(Q['filas'] / 1e6, 1)} M filas) "
                                  "en un data lake en Amazon S3, sin modificar."),
        ("2", "Limpieza (Silver)", f"PySpark en AWS Glue tipa y valida: {num(Q['edades_invalidas'])} "
                                   f"edades imposibles y {num(Q['antiguedades_invalidas'])} "
                                   "antigüedades negativas pasan a nulo. Parquet por mes."),
        ("3", "Features (Gold)", "Por cliente-mes: perfil, productos de hoy y de hace 1, 3 y 6 "
                                 "meses, altas del mes y tasas por segmento. 168 columnas."),
        ("4", "Modelo", "Clasificador LightGBM que da a cada producto una probabilidad; se "
                        "ordenan y se quitan los que el cliente ya tiene → Top-7."),
        ("5", "Servicio", "API REST (FastAPI + Docker) en ECS Fargate que lee Gold vía Athena y "
                          "devuelve las recomendaciones de un cliente."),
        ("6", "Tablero", "Este dashboard (Streamlit + Plotly) sobre las 6 tablas gold analíticas."),
    ]
    cols = st.columns(3)
    for i, (n, title, body) in enumerate(steps):
        with cols[i % 3]:
            st.markdown(f'<div class="step"><span class="n">PASO {n}</span><br><b>{title}</b>'
                        f'<br><span style="color:#52514e">{body}</span></div>',
                        unsafe_allow_html=True)
            st.write("")

    with st.expander("🗺️ Arquitectura en AWS (orquestada con Terraform)", expanded=True):
        a, b = st.columns([3, 2])
        if ARCH_IMG.exists():
            a.image(str(ARCH_IMG))
        b.markdown(
            "- **EventBridge → Step Functions** disparan el batch: limpieza y luego los 8 jobs "
            "gold **en paralelo** en **AWS Glue** (Spark).\n"
            "- **S3** guarda las capas Bronze, Silver y Gold en Parquet (arquitectura "
            "*Medallion / Lakehouse*).\n"
            "- **Athena + Glue Data Catalog** permiten consultar Gold con SQL.\n"
            "- El modelo se entrena en **EC2** y su artefacto queda en S3.\n"
            "- **ECS Fargate** expone la API que consume el tablero.\n"
            "- Toda la infraestructura es código (**Terraform**) y se crea/destruye con un script.")

    st.subheader("Cómo se plantea el problema sin hacer trampa con el tiempo")
    l, r = st.columns([3, 2])
    with l:
        cuts = M["cortes_temporales"]
        months = pd.date_range("2015-01-01", "2016-05-01", freq="MS") + pd.Timedelta(days=27)
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
        colors = {"Entrenamiento": BLUE, "Validación": "#86b6ef", "Prueba": ORANGE,
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
            "- **Entrada (mes *t*)**: perfil del cliente + productos de hoy y de meses "
            "anteriores.\n"
            "- **Respuesta (mes *t+1*)**: qué productos **nuevos** adquirió (no los tenía y "
            "ahora sí).\n"
            "- Se entrena con el pasado y se evalúa en meses **posteriores** que el modelo "
            "nunca vio. Mayo 2016 no tiene respuesta: es el mes que se usa para recomendar.")

    st.subheader("La métrica: MAP@7, en un ejemplo interactivo")
    st.markdown("Le mostramos al cliente 7 productos en orden. MAP@7 premia **acertar** y "
                "acertar **arriba** en la lista. Prueba: ¿cuántos productos adquirió de verdad "
                "y en qué posiciones de nuestro Top-7 estaban?")
    e1, e2, e3 = st.columns([1, 2, 1])
    n_real = e1.number_input("Productos que adquirió de verdad", 1, 3, 1, key="ap_n")
    hits = e2.multiselect("Posiciones del Top-7 donde acertamos", list(range(1, 8)), default=[1],
                          max_selections=int(n_real), key="ap_hits")
    hits = sorted(hits)
    terms, h = [], 0
    for pos in range(1, 8):
        if pos in hits:
            h += 1
            terms.append((pos, h / pos))
    ap = sum(v for _, v in terms) / min(n_real, 7)
    e3.metric("AP@7 de este cliente", f"{ap:.3f}".replace(".", ","))
    detail = " + ".join(f"{int(round(v * pos))}/{pos}" for pos, v in terms) or "0"
    st.caption(f"AP@7 = ({detail}) ÷ {min(n_real, 7)} = {ap:.3f}. **MAP@7** es el promedio de "
               "AP@7 sobre todos los clientes; quien no compra nada aporta 0, así que los valores "
               "absolutos son bajos (≈ 0,02-0,03) y lo que importa es **comparar contra el modelo "
               "base**.")

    st.subheader("Modelos comparados")
    st.markdown(
        "| Modelo | Idea | Rol |\n|---|---|---|\n"
        "| **Popularidad** | Ofrecer a todos los productos más adquiridos (sin los que ya tiene) | Línea base a superar |\n"
        "| Regresión logística | Modelo lineal por producto | Comparación |\n"
        "| Random Forest | Ensamble de árboles (*bagging*) | Comparación |\n"
        "| **LightGBM** | *Gradient boosting* de árboles; maneja nulos, categorías e interacciones | Modelo elegido |")
    st.caption("La familia y los hiperparámetros se eligen **solo con validación**; el mes de "
               "prueba se usa una única vez al final.")
    nav_buttons("s4")

# ===========================================================================
# 5 · RESULTADOS
# ===========================================================================
elif sec == SECCIONES[4]:
    st.markdown('<p class="kicker">Evaluación</p>', unsafe_allow_html=True)
    st.title("¿Funcionó?")
    test = {r["modelo"]: r for r in M["prueba"]}
    lgb_t, base_t = test["LightGBM"], test["Popularidad (base)"]
    lift = lgb_t["map7"] / base_t["map7"] - 1
    cuts = M["cortes_temporales"]

    c = st.columns(3)
    c[0].metric("MAP@7 LightGBM (prueba)", f"{lgb_t['map7']:.4f}".replace(".", ","),
                f"+{pct(lift, 0)} vs. modelo base")
    c[1].metric("MAP@7 modelo base (prueba)", f"{base_t['map7']:.4f}".replace(".", ","))
    c[2].metric("Mes de prueba", mes(cuts["prueba"]),
                help="Con los datos de este mes se predicen las compras de " + mes(
                    pd.Timestamp(cuts["prueba"]) + pd.DateOffset(months=1))
                + "; el modelo nunca vio este mes al entrenar.")
    st.caption(f"Alcance de la evaluación: {M['alcance']}. Fuente: "
               f"{'iac/model-training/train.py' if M['origen'] == 'train.py' else 'notebooks/prueba_modelo.ipynb'}.")

    l, r = st.columns(2)
    with l:
        v = pd.DataFrame(M["comparacion_validacion"]).sort_values("map7")
        colors = [BLUE if m == "LightGBM" else ORANGE if "base" in m else GRAY for m in v.modelo]
        fig = go.Figure(go.Bar(
            x=v.map7, y=v.modelo, orientation="h", marker=dict(color=colors, cornerradius=4),
            text=[f"{x:.4f}".replace(".", ",") for x in v.map7], textposition="outside",
            textfont=dict(color=INK_2),
            hovertemplate="<b>%{y}</b><br>MAP@7 = %{x:.4f}<extra></extra>"))
        fig.update_xaxes(range=[0, v.map7.max() * 1.25], title=None)
        fig.update_layout(title=f"Validación ({mes(cuts['validacion'])}): MAP@7 por modelo",
                          bargap=0.45)
        chart(style(fig, 300), "val")
        st.caption("Todos los modelos supervisados le ganan a la popularidad; LightGBM es el "
                   "mejor y se elige para producción.")
    with r:
        b = D["baseline_popularidad"].dropna(subset=["map_at_7"])
        fig = go.Figure(go.Scatter(
            x=b.fecha.map(mes), y=b.map_at_7, mode="lines+markers", name="Modelo base (popularidad)",
            line=dict(color=ORANGE, width=2), marker=dict(size=8),
            hovertemplate="Ranking de %{x}<br>MAP@7 = %{y:.4f}<extra></extra>"))
        tm = pd.Timestamp(cuts["prueba"])
        fig.add_trace(go.Scatter(
            x=[mes(tm)], y=[lgb_t["map7"]], mode="markers+text", name="LightGBM (prueba)",
            marker=dict(size=13, color=BLUE, line=dict(color=SURFACE, width=2)),
            text=["LightGBM"], textposition="top center", textfont=dict(color=INK),
            hovertemplate="LightGBM en prueba<br>MAP@7 = %{y:.4f}<extra></extra>"))
        fig.update_yaxes(rangemode="tozero", title=None)
        fig.update_layout(title="MAP@7 del modelo base mes a mes (dataset completo)")
        chart(style(fig, 300, legend=True), "basemon")
        st.caption("El modelo base de popularidad se evaluó sobre los 13,6 M de registros en la "
                   "capa gold. Su desempeño varía con la estacionalidad.")

    st.subheader("¿Qué aprendió el modelo?")
    l, r = st.columns([3, 2])
    with l:
        fi = pd.DataFrame(M["importancia_variables"]).head(12).iloc[::-1]
        fi["share"] = fi.gain / fi.gain.sum()
        fig = go.Figure(go.Bar(x=fi.share, y=fi.feature.map(fname), orientation="h",
                               marker=dict(color=BLUE, cornerradius=4),
                               hovertemplate="<b>%{y}</b><br>%{x:.1%} de la ganancia (top 12)"
                                             "<extra></extra>"))
        fig.update_xaxes(tickformat=".0%")
        fig.update_layout(title="Variables más importantes (ganancia en LightGBM)")
        chart(style(fig, 420), "fi")
    with r:
        callout("**La historia manda.** Las variables más útiles son los productos que el "
                "cliente tenía **hace un mes** (pensión, nómina, débito automático), si es un "
                "cliente **activo**, su tipo de relación y su **antigüedad**. Las variables "
                "rezagadas (*lags*) que construimos en la capa gold son las que más aportan.", "ok")
        d = M["diagnostico"]
        st.metric("MAP@7 entrenamiento vs. validación",
                  f"{d['train_map7']:.4f} vs {d['validacion_map7']:.4f}".replace(".", ","),
                  f"brecha {d['gap']:.4f}".replace(".", ","), delta_color="off")
        st.caption("Brecha pequeña: no hay sobreajuste fuerte; el techo viene de lo difícil que "
                   "es predecir una compra que ocurre en ~3 % de los clientes.")

    st.subheader("¿Para quién funciona mejor?")
    seg = pd.DataFrame(M["por_segmento"])
    dsel = st.segmented_control("Ver por", seg.dimension.unique().tolist(), default="Segmento",
                                key="segdim") if hasattr(st, "segmented_control") else \
        st.radio("Ver por", seg.dimension.unique().tolist(), horizontal=True, index=2)
    s = seg[seg.dimension == (dsel or "Segmento")]
    fig = go.Figure(go.Bar(x=s.valor, y=s.map7, marker=dict(color=BLUE, cornerradius=4),
                           customdata=s[["clientes", "hit_rate"]],
                           hovertemplate="<b>%{x}</b><br>MAP@7 = %{y:.4f}<br>%{customdata[0]:,} "
                                         "clientes<br>acierto ≥1 en top 7: %{customdata[1]:.1%}"
                                         "<extra></extra>"))
    fig.add_hline(y=lgb_t["map7"], line=dict(color=MUTED, width=1),
                  annotation_text="promedio LightGBM", annotation_font_color=INK_2)
    fig.update_layout(title=f"MAP@7 de LightGBM en prueba por {(dsel or 'Segmento').lower()}",
                      bargap=0.5)
    chart(style(fig, 320), "seg")
    st.caption("Funciona mucho mejor en clientes **VIP** y de **35-54 años** (compran más y con "
               "patrones más claros) y peor en **universitarios** y menores de 25, que casi no "
               "adquieren productos.")

    st.subheader("Pruébalo: recomendaciones para un cliente")
    t1, t2, t3 = st.tabs(["🧪 Simulador del modelo base", "🔌 API en vivo (LightGBM)",
                          "📄 Ejemplo del modelo"])
    with t1:
        base = D["baseline_popularidad"].dropna(subset=["popularity_ranking"])
        ranking = base.sort_values("fecha").iloc[-1]
        rk = ranking.popularity_ranking.split(",")
        st.markdown(f"Marca los productos que **ya tiene** el cliente. El modelo base le ofrece "
                    f"los 7 más adquiridos en {mes(ranking.fecha)} que todavía no tiene: la "
                    "**misma lista para todos**. Esa es la referencia que LightGBM supera "
                    "personalizando con el perfil y la historia.")
        held = st.multiselect("Productos que ya tiene", rk, default=["ind_cco_fin_ult1"],
                              format_func=pname, key="sim_held")
        recs = [p for p in rk if p not in held][:7]
        st.dataframe(pd.DataFrame({"Puesto": range(1, len(recs) + 1),
                                   "Producto recomendado": [pname(p) for p in recs]}),
                     hide_index=True)
    with t2:
        def secret(name: str) -> str:
            try:
                return str(st.secrets.get(name, ""))
            except Exception:
                return ""
        st.markdown("Consulta la API FINSIR desplegada en AWS (ECS Fargate), que corre el "
                    "modelo LightGBM sobre la fila más reciente del cliente en Gold. Requiere la "
                    "infraestructura encendida.")
        a1, a2 = st.columns(2)
        api_url = a1.text_input("URL de la API", secret("API_BASE_URL"),
                                placeholder="http://<ip>:8080", key="api_url")
        api_secret = a2.text_input("Secreto de autenticación (modo dev)",
                                   secret("AUTH_DEV_SECRET"), type="password", key="api_secret")
        client_id = st.number_input("ID del cliente (ncodpers)", min_value=0, step=1,
                                    value=int(M["ejemplo_recomendacion"]["ncodpers"] or 0),
                                    key="api_client")
        if st.button("Consultar recomendaciones", key="api_go", disabled=not api_url):
            try:
                import jwt
                import requests
                now = int(time.time())
                token = jwt.encode({"sub": "dashboard-finsir", "scope": "gold:read",
                                    "iat": now - 120, "nbf": now - 120, "exp": now + 900},
                                   api_secret, algorithm="HS256")
                with st.spinner("Consultando la API..."):
                    resp = requests.get(
                        f"{api_url.rstrip('/')}/v1/recommendations/clients/{int(client_id)}",
                        headers={"Authorization": f"Bearer {token}"}, timeout=60)
                if resp.ok:
                    data = resp.json()["data"]
                    item = data["items"][0]
                    st.caption(f"Modelo {data['model_version']} · cliente {item['ncodpers']} · "
                               f"datos de {item['fecha_dato']}")
                    recs = pd.DataFrame(item["recommendations"])
                    recs.insert(0, "Puesto", range(1, len(recs) + 1))
                    recs["product"] = recs["product"].map(pname)
                    st.dataframe(recs.rename(columns={"product": "Producto",
                                                      "score": "Propensión"}), hide_index=True)
                else:
                    st.error(f"La API respondió {resp.status_code}: {resp.text[:300]}")
            except Exception as err:  # noqa: BLE001 - mostrar cualquier fallo de red/token
                st.error(f"No se pudo consultar la API: {err}")
    with t3:
        ex = M["ejemplo_recomendacion"]
        st.markdown(f"Top-7 que el modelo LightGBM generó para el cliente **{ex['ncodpers']}** "
                    f"con sus datos de {mes(ex['mes_base'])} (predicción para el mes siguiente).")
        e = pd.DataFrame(ex["items"])
        e = e.iloc[::-1]
        fig = go.Figure(go.Bar(x=e.score, y=e["product"].map(pname), orientation="h",
                               marker=dict(color=BLUE, cornerradius=4),
                               hovertemplate="<b>%{y}</b><br>propensión %{x:.4f}<extra></extra>"))
        fig.update_layout(title="Puntaje de propensión por producto")
        chart(style(fig, 300), "example")

    biz = M["negocio_por_1000_contactos"]
    st.info(f"**Lectura de negocio.** En la simulación retrospectiva, por cada 1.000 clientes "
            f"contactados con 7 ofertas, el modelo encontró al menos una compra real en "
            f"**{dec(biz['modelo'], 1)}** clientes frente a **{dec(biz['base'], 1)}** del modelo base, y "
            f"además las ubica **más arriba** en la lista (por eso el MAP@7 sube "
            f"{pct(lift, 0)}). No es un efecto causal de campaña: medirlo requiere un "
            "experimento con grupo de control.")
    nav_buttons("s5")

# ===========================================================================
# 6 · CONCLUSIONES
# ===========================================================================
elif sec == SECCIONES[5]:
    st.markdown('<p class="kicker">Cierre</p>', unsafe_allow_html=True)
    st.title("Conclusiones")
    test = {r["modelo"]: r for r in M["prueba"]}
    lift = test["LightGBM"]["map7"] / test["Popularidad (base)"]["map7"] - 1
    c = st.columns(3)
    c[0].metric("Mejora en MAP@7 vs. popularidad", f"+{pct(lift, 0)}")
    c[1].metric("Registros procesados", f"{Q['filas'] / 1e6:,.1f} M".replace(".", ","))
    c[2].metric("Tablas gold construidas", "8")

    st.markdown(f"""
1. **Se cumplió el objetivo.** Un modelo LightGBM que personaliza con el perfil y la historia del
   cliente supera al modelo base de popularidad en **{pct(lift, 0)}** de MAP@7 en un mes que
   nunca vio.
2. **La historia del cliente es la mejor señal.** Lo que tenía hace 1-3 meses (nómina, pensión,
   débito automático, tarjeta) y si es un cliente activo pesan más que la demografía. Por eso
   invertir en la capa gold con *lags* fue clave.
3. **Adquirir un producto es raro (≈ {pct(RES.pct_compran.mean(), 1)} de los clientes por mes)**
   y el portafolio está concentrado: los valores absolutos de MAP@7 son bajos; lo relevante es
   la mejora relativa y el orden de las ofertas.
4. **El modelo rinde distinto por segmento**: muy bien en VIP y adultos de 35-54 años, poco en
   universitarios. Conviene usar estrategias diferentes por segmento.
5. **Es un sistema completo, no solo un notebook**: datos en un lakehouse en AWS (S3 + Glue +
   Athena), orquestación automática, modelo servido por una API en contenedores y este tablero,
   todo como código con Terraform.
""")
    l, r = st.columns(2)
    with l:
        st.subheader("Limitaciones")
        st.markdown(
            "- La comparación de familias de modelos se hizo con una muestra del 10 % de los "
            "clientes.\n"
            "- La simulación de negocio es retrospectiva: no mide el efecto causal de una "
            "campaña.\n"
            "- Se valida en abril-mayo; la estacionalidad de otros meses (p. ej. junio) puede "
            "cambiar el desempeño.")
    with r:
        st.subheader("Próximos pasos")
        st.markdown(
            "- Probar XGBoost/CatBoost y variables de interacción entre productos.\n"
            "- Enviar la predicción a Kaggle (*late submission*) para el puntaje oficial de junio "
            "2016.\n"
            "- Un experimento A/B con grupo de control para medir el impacto real en ventas.")
    st.success("**En una frase:** FINSIR convierte 13,6 millones de registros en una lista de 7 "
               "ofertas personalizadas por cliente, que acierta mejor y más arriba que ofrecer a "
               "todos lo mismo.")
    nav_buttons("s6")
