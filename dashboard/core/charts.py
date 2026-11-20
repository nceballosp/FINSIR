"""Constructores de gráficos con las reglas de marca del tablero.

- Barras finas con esquinas redondeadas en el extremo del dato.
- Énfasis: el dato clave en ámbar (siempre etiquetado), el resto en azul o gris.
- Rejilla mínima, sin dobles ejes, etiquetas directas selectivas.
"""

from __future__ import annotations

from typing import Callable, Iterable, Sequence

import numpy as np
import plotly.graph_objects as go

from core.theme import AMBER, GRAY, HEAT_SCALE, INK, INK_2, NAVY, NAVY_900


def _colors(n: int, highlight: Iterable[int] = (), base: str = NAVY,
            muted: Iterable[int] = ()) -> list[str]:
    colors = [base] * n
    for i in muted:
        colors[i] = GRAY
    for i in highlight:
        colors[i] = AMBER
    return colors


def hbar(labels: Sequence[str], values: Sequence[float], *, text: Sequence[str] | None = None,
         highlight: Iterable[int] = (), muted: Iterable[int] = (), base: str = NAVY,
         hover: str = "%{y}<br>%{x}<extra></extra>", customdata=None,
         x_title: str | None = None, show_axis: bool = False) -> go.Figure:
    """Barras horizontales; el primer elemento queda arriba."""
    labels, values = list(labels)[::-1], list(values)[::-1]
    n = len(labels)
    hl = [n - 1 - i for i in highlight]
    mu = [n - 1 - i for i in muted]
    fig = go.Figure(go.Bar(
        x=values, y=labels, orientation="h",
        marker=dict(color=_colors(n, hl, base, mu), cornerradius=3),
        text=list(text)[::-1] if text is not None else None,
        textposition="outside", cliponaxis=False,
        textfont=dict(color=INK_2, size=12),
        customdata=list(customdata)[::-1] if customdata is not None else None,
        hovertemplate=hover,
    ))
    vmax = max([v for v in values if v is not None] or [1])
    fig.update_layout(
        xaxis=dict(visible=show_axis, range=[0, vmax * (1.22 if text is not None else 1.05)],
                   title=x_title, showgrid=show_axis, gridcolor="#EDF0F4"),
        yaxis=dict(showgrid=False, tickfont=dict(color=INK, size=12)),
        margin=dict(l=8, r=36, t=8, b=8), bargap=0.32,
    )
    return fig


def vbar(labels: Sequence[str], values: Sequence[float], *, text: Sequence[str] | None = None,
         highlight: Iterable[int] = (), muted: Iterable[int] = (),
         hover: str = "%{x}<br>%{y}<extra></extra>", y_title: str | None = None) -> go.Figure:
    n = len(labels)
    fig = go.Figure(go.Bar(
        x=list(labels), y=list(values),
        marker=dict(color=_colors(n, highlight, NAVY, muted), cornerradius=3),
        text=text, textposition="outside", cliponaxis=False,
        textfont=dict(color=INK_2, size=12), hovertemplate=hover,
    ))
    vmax = max([v for v in values if v is not None] or [1])
    fig.update_layout(yaxis=dict(title=y_title, range=[0, vmax * 1.18], showgrid=True),
                      xaxis=dict(type="category", tickangle=0),
                      bargap=0.55 if n <= 5 else 0.35)
    return fig


def heatmap(z: np.ndarray, x: Sequence[str], y: Sequence[str], *, text_fmt: Callable[[float], str],
            hover: str, colorbar_title: str, zmax: float | None = None,
            customdata=None) -> go.Figure:
    text = [[text_fmt(v) if v is not None and not np.isnan(v) else "" for v in row] for row in z]
    fig = go.Figure(go.Heatmap(
        z=z, x=list(x), y=list(y), colorscale=HEAT_SCALE, zmin=0, zmax=zmax,
        xgap=2, ygap=2, text=text, texttemplate="%{text}",
        textfont=dict(size=11), customdata=customdata, hovertemplate=hover,
        colorbar=dict(title=dict(text=colorbar_title, side="right", font=dict(size=11, color=INK_2)),
                      thickness=10, outlinewidth=0, tickfont=dict(size=11, color=INK_2), len=0.8),
    ))
    fig.update_layout(
        xaxis=dict(side="top", showline=False, tickfont=dict(color=INK, size=12), type="category"),
        yaxis=dict(autorange="reversed", showgrid=False, tickfont=dict(color=INK, size=12),
                   type="category"),
        margin=dict(l=8, r=8, t=8, b=8),
    )
    return fig


def annotate(fig: go.Figure, x, y, text: str, ax: int = 0, ay: int = -34,
             xanchor: str = "center") -> None:
    fig.add_annotation(
        x=x, y=y, text=text, showarrow=True, arrowhead=0, arrowwidth=1, arrowcolor="#9AA5B4",
        ax=ax, ay=ay, xanchor=xanchor, font=dict(size=12, color=NAVY_900),
        bgcolor="rgba(255,255,255,0.92)", borderpad=3,
    )
