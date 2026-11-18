"""Paleta y plantilla de gráficos.

Regla de color del equipo: azul marino para la estructura y los datos, ámbar
solo para el dato que el lector debe ver primero, grises para el contexto.
La paleta se validó con el verificador de daltonismo/contraste:
  - NAVY + AMBER: separación CVD ΔE 43 (pasa); el ámbar queda bajo 3:1 de
    contraste, por eso toda marca ámbar lleva etiqueta directa.
  - Rampa secuencial: monótona, un solo tono, extremo claro >= 2:1.
"""

from __future__ import annotations

import plotly.graph_objects as go
import plotly.io as pio

NAVY_900 = "#0B2545"   # títulos, encabezados, barra lateral
NAVY_700 = "#163A6B"
NAVY = "#23549A"       # marca de datos principal
NAVY_300 = "#6F97C6"
NAVY_100 = "#DCE6F2"   # fondos suaves (no como marca de datos)
AMBER = "#E09A00"      # dato clave (siempre con etiqueta)
AMBER_100 = "#FDF3DC"  # fondo de anotaciones
INK = "#1A2433"        # texto principal
INK_2 = "#4A5568"      # texto secundario
INK_3 = "#7A8596"      # texto terciario / ejes
GRAY = "#B8C1CC"       # marcas de contexto
GRAY_LIGHT = "#E3E8EF"  # bordes
GRID = "#EDF0F4"       # rejilla
SURFACE = "#FFFFFF"

SEQUENTIAL = ["#9DB7D8", "#6F97C6", "#3F6EA8", "#23549A", "#163A6B", "#0B2545"]
# Escala continua para mapas de calor: arranca casi blanco solo para la celda
# "cero"; las celdas tienen separación blanca y el valor se lee en el tooltip
# y en la vista de tabla.
HEAT_SCALE = [
    [0.0, "#F4F7FB"], [0.08, "#C9D8EB"], [0.25, "#9DB7D8"], [0.45, "#6F97C6"],
    [0.65, "#3F6EA8"], [0.82, "#23549A"], [1.0, "#0B2545"],
]
FONT = "IBM Plex Sans, -apple-system, Segoe UI, sans-serif"


def _template() -> go.layout.Template:
    t = go.layout.Template()
    t.layout = go.Layout(
        font=dict(family=FONT, size=13, color=INK_2),
        paper_bgcolor=SURFACE,
        plot_bgcolor=SURFACE,
        colorway=[NAVY, AMBER, GRAY],
        margin=dict(l=8, r=16, t=12, b=8),
        hoverlabel=dict(
            bgcolor="white", bordercolor=GRAY_LIGHT,
            font=dict(family=FONT, size=13, color=INK),
        ),
        xaxis=dict(
            automargin=True, showgrid=False, zeroline=False, showline=True, linecolor=GRAY_LIGHT,
            ticks="", tickfont=dict(color=INK_3, size=12),
            title=dict(font=dict(color=INK_3, size=12)),
        ),
        yaxis=dict(
            automargin=True, tickformat=",~r", showgrid=True, gridcolor=GRID, gridwidth=1, zeroline=False,
            showline=False, ticks="", tickfont=dict(color=INK_3, size=12),
            title=dict(font=dict(color=INK_3, size=12)),
        ),
        legend=dict(
            orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0,
            font=dict(size=12, color=INK_2), title=dict(text=""),
        ),
        bargap=0.28,
        separators=",.",
    )
    return t


pio.templates["finsir"] = _template()
pio.templates.default = "finsir"

PLOTLY_CONFIG = {
    "displaylogo": False,
    "modeBarButtonsToRemove": ["lasso2d", "select2d", "autoScale2d", "toggleSpikelines"],
    "toImageButtonOptions": {"format": "png", "scale": 2},
}
