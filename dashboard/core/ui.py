"""Componentes de interfaz: encabezados, indicadores, tarjetas y notas.

Estilo editorial (informe financiero): jerarquía tipográfica clara, reglas
finas, sin sombras ni degradados. Cada gráfico lleva un título declarativo
(el hallazgo, no la descripción) y una línea de "cómo leerlo".
"""

from __future__ import annotations

import html
from contextlib import contextmanager
from typing import Iterator

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core import theme
from core.theme import AMBER, INK, INK_2, INK_3, NAVY, NAVY_900

_CSS = f"""
<style>
.block-container {{ padding-top: 2.2rem; padding-bottom: 4rem; max-width: 1320px; }}
h1, h2, h3, h4 {{ color: {NAVY_900}; letter-spacing: -0.01em; }}
.fs-eyebrow {{
  font-size: 0.74rem; font-weight: 600; letter-spacing: 0.12em; text-transform: uppercase;
  color: {NAVY}; margin: 0 0 0.35rem 0; display: flex; gap: 0.6rem; align-items: center;
}}
.fs-eyebrow .fs-step {{
  display: inline-flex; align-items: center; justify-content: center; min-width: 1.6rem; height: 1.25rem;
  padding: 0 0.35rem; border-radius: 3px; background: {NAVY_900}; color: #fff; letter-spacing: 0.04em;
}}
.fs-title {{ font-size: 2.05rem; line-height: 1.18; font-weight: 700; color: {NAVY_900};
  margin: 0 0 0.6rem 0; max-width: 62rem; letter-spacing: -0.015em; }}
.fs-lede {{ font-size: 1.02rem; line-height: 1.55; color: {INK_2}; max-width: 54rem; margin: 0 0 0.4rem 0; }}
.fs-rule {{ border: 0; border-top: 1px solid #E3E8EF; margin: 1.1rem 0 1.3rem 0; }}
.fs-kpis {{ display: grid; grid-template-columns: repeat(var(--fs-n, 4), minmax(0, 1fr)); gap: 0;
  border-top: 1px solid #E3E8EF; border-bottom: 1px solid #E3E8EF; margin: 0.2rem 0 1.4rem 0; }}
@media (max-width: 1100px) {{ .fs-kpis {{ grid-template-columns: repeat(3, minmax(0, 1fr)); }}
  .fs-kpi:nth-child(3n+1) {{ border-left: 0; padding-left: 0.1rem; }} }}
.fs-kpi {{ padding: 0.95rem 1.1rem 0.9rem 1.1rem; border-left: 1px solid #E3E8EF; }}
.fs-kpi:first-child {{ border-left: 0; padding-left: 0.1rem; }}
.fs-kpi-label {{ font-size: 0.78rem; color: {INK_3}; font-weight: 500; margin-bottom: 0.3rem; }}
.fs-kpi-value {{ font-size: 1.7rem; font-weight: 600; color: {NAVY_900}; line-height: 1.1; }}
.fs-kpi-value.fs-accent {{ color: {NAVY_900}; box-shadow: inset 0 -0.32em 0 rgba(224,154,0,0.35); display: inline; }}
.fs-kpi-value.fs-small {{ font-size: 1.15rem; line-height: 1.3; padding-top: 0.3rem; }}
.fs-kpi-note {{ font-size: 0.78rem; color: {INK_2}; margin-top: 0.35rem; line-height: 1.35; }}
.fs-chart-title {{ font-size: 1.08rem; font-weight: 600; color: {NAVY_900}; margin: 0 0 0.2rem 0; line-height: 1.35; }}
.fs-chart-sub {{ font-size: 0.86rem; color: {INK_3}; margin: 0 0 0.6rem 0; line-height: 1.45; }}
.fs-insight {{ border-left: 3px solid {AMBER}; background: #FDF8EC; padding: 0.75rem 1rem;
  margin: 0.4rem 0 0.9rem 0; color: {INK}; font-size: 0.93rem; line-height: 1.5; border-radius: 0 4px 4px 0; }}
.fs-insight b {{ color: {NAVY_900}; }}
.fs-note {{ font-size: 0.82rem; color: {INK_3}; line-height: 1.5; margin-top: 0.3rem; }}
.fs-method {{ background: #F4F6F9; border-radius: 6px; padding: 0.9rem 1.1rem; font-size: 0.88rem;
  color: {INK_2}; line-height: 1.55; }}
.fs-method b {{ color: {NAVY_900}; }}
.fs-chip {{ display: inline-block; padding: 0.18rem 0.6rem; margin: 0 0.35rem 0.4rem 0; border-radius: 999px;
  border: 1px solid #D5DDE8; font-size: 0.82rem; color: {INK}; background: #fff; }}
.fs-chip.fs-on {{ background: {NAVY}; border-color: {NAVY}; color: #fff; }}
.fs-step-card {{ border-top: 2px solid {NAVY_900}; padding-top: 0.7rem; }}
.fs-step-card .n {{ font-size: 0.74rem; font-weight: 600; color: {NAVY}; letter-spacing: 0.1em; }}
.fs-step-card .t {{ font-size: 1.0rem; font-weight: 600; color: {NAVY_900}; margin: 0.15rem 0 0.25rem 0; }}
.fs-step-card .d {{ font-size: 0.86rem; color: {INK_2}; line-height: 1.45; min-height: 3.8rem; }}
.fs-flow {{ display: flex; flex-wrap: wrap; gap: 0; align-items: stretch; margin: 0.2rem 0 0.4rem 0; }}
.fs-flow .s {{ flex: 1 1 140px; padding: 0.6rem 0.8rem; border: 1px solid #E3E8EF; margin-left: -1px; background: #fff; }}
.fs-flow .s .k {{ font-size: 0.7rem; letter-spacing: 0.1em; text-transform: uppercase; color: {INK_3}; font-weight: 600; }}
.fs-flow .s .v {{ font-size: 0.9rem; color: {NAVY_900}; font-weight: 600; margin-top: 0.1rem; }}
.fs-flow .s .x {{ font-size: 0.78rem; color: {INK_2}; margin-top: 0.15rem; line-height: 1.35; }}
[data-testid="stSidebarHeader"] img {{ height: 2.1rem !important; max-width: 100%; }}
[data-testid="stSidebar"] .fs-brand {{ font-size: 1.35rem; font-weight: 700; letter-spacing: 0.08em; color: #fff; margin-bottom: 0.1rem; }}
[data-testid="stSidebar"] .fs-brand-sub {{ font-size: 0.78rem; color: #A9BBD3; line-height: 1.4; margin-bottom: 0.6rem; }}
[data-testid="stSidebar"] .fs-status {{ font-size: 0.76rem; color: #A9BBD3; line-height: 1.5; }}
[data-testid="stSidebar"] .fs-dot {{ display: inline-block; width: 7px; height: 7px; border-radius: 50%; margin-right: 6px; }}
div[data-testid="stExpander"] details summary p {{ font-size: 0.86rem; color: {INK_2}; }}
</style>
"""


def inject_css() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)


def page_header(step: str, eyebrow: str, title: str, lede: str) -> None:
    st.markdown(
        f'<div class="fs-eyebrow"><span class="fs-step">{html.escape(step)}</span>'
        f'{html.escape(eyebrow)}</div>'
        f'<div class="fs-title">{html.escape(title)}</div>'
        f'<p class="fs-lede">{lede}</p><hr class="fs-rule"/>',
        unsafe_allow_html=True,
    )


def kpi_row(items: list[dict]) -> None:
    """items: [{label, value, note?, accent?}]"""
    cells = []
    for item in items:
        accent = " fs-accent" if item.get("accent") else ""
        accent += " fs-small" if item.get("small") else ""
        note = f'<div class="fs-kpi-note">{item["note"]}</div>' if item.get("note") else ""
        cells.append(
            f'<div class="fs-kpi"><div class="fs-kpi-label">{html.escape(item["label"])}</div>'
            f'<div class="fs-kpi-value{accent}">{html.escape(str(item["value"]))}</div>{note}</div>'
        )
    st.markdown(f'<div class="fs-kpis" style="--fs-n:{len(items)}">{"".join(cells)}</div>',
                unsafe_allow_html=True)


def chart_title(title: str, subtitle: str | None = None) -> None:
    sub = f'<div class="fs-chart-sub">{subtitle}</div>' if subtitle else ""
    st.markdown(f'<div class="fs-chart-title">{html.escape(title)}</div>{sub}',
                unsafe_allow_html=True)


def insight(text: str) -> None:
    st.markdown(f'<div class="fs-insight">{text}</div>', unsafe_allow_html=True)


def note(text: str) -> None:
    st.markdown(f'<div class="fs-note">{text}</div>', unsafe_allow_html=True)


def method(text: str) -> None:
    st.markdown(f'<div class="fs-method">{text}</div>', unsafe_allow_html=True)


def chips(labels: list[str], on: set[str] | None = None) -> None:
    on = on or set()
    st.markdown(
        "".join(
            f'<span class="fs-chip{" fs-on" if label in on else ""}">{html.escape(label)}</span>'
            for label in labels
        ),
        unsafe_allow_html=True,
    )


@contextmanager
def card() -> Iterator[None]:
    with st.container(border=True):
        yield


def plot(fig: go.Figure, key: str | None = None, height: int | None = None,
         on_select: str | None = None, selection_mode=None):
    if height:
        fig.update_layout(height=height)
    kwargs = {"theme": None, "config": theme.PLOTLY_CONFIG, "key": key}
    if on_select:
        kwargs["on_select"] = on_select
        if selection_mode:
            kwargs["selection_mode"] = selection_mode
    return st.plotly_chart(fig, **kwargs)


def data_table(frame: pd.DataFrame, label: str = "Ver datos del gráfico",
               column_config: dict | None = None) -> None:
    with st.expander(label):
        st.dataframe(frame, hide_index=True, column_config=column_config)


def fmt_int(value: float) -> str:
    return f"{value:,.0f}".replace(",", ".")


def fmt_pct(value: float, digits: int = 1) -> str:
    return f"{value * 100:,.{digits}f} %".replace(".", ",")


def fmt_dec(value: float, digits: int = 4) -> str:
    return f"{value:.{digits}f}".replace(".", ",")


def fmt_compact(value: float) -> str:
    if value >= 1e6:
        return f"{value / 1e6:,.1f} M".replace(".", ",")
    if value >= 1e3:
        return f"{value / 1e3:,.0f} mil".replace(",", ".")
    return fmt_int(value)


def api_error(error: Exception) -> None:
    st.error(f"{error}", icon=":material/cloud_off:")
    st.caption("El tablero consulta las tablas gold a través de la API desplegada en AWS ECS. "
               "Si la infraestructura está apagada, despliégala con iac/api/deploy.ps1. La IP "
               "pública cambia en cada despliegue: obtén la actual con dashboard/get_api_url.ps1 "
               "y actualiza API_BASE_URL en los secretos (local o Streamlit Cloud).")
    st.stop()


def loading(message: str = "Consultando las tablas gold en Athena a través de la API…"):
    return st.spinner(message, show_time=True)
