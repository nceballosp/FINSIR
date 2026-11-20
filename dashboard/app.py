"""Tablero FINSIR — punto de entrada.

Ejecutar desde la raíz del repositorio (así Streamlit encuentra
.streamlit/config.toml y .streamlit/secrets.toml):

    streamlit run dashboard/app.py

Las páginas siguen el orden de la historia: contexto -> clientes -> productos
-> transiciones -> modelo -> impacto -> caso aplicado.
"""

from __future__ import annotations

import streamlit as st

from pathlib import Path

from core import api, theme  # noqa: F401  (theme registra la plantilla de Plotly)
from core.ui import inject_css

ASSETS = Path(__file__).parent / "assets"

st.set_page_config(
    page_title="FINSIR · Recomendación de productos financieros",
    page_icon=":material/account_balance:",
    layout="wide",
    initial_sidebar_state="expanded",
)
inject_css()
st.logo(str(ASSETS / "logo.svg"), size="large")


@st.cache_data(ttl=60, show_spinner=False)
def api_online() -> bool:
    return api.health()


pages = {
    "Resumen": [
        st.Page("views/resumen.py", title="Resumen ejecutivo", icon=":material/space_dashboard:",
                default=True),
    ],
    "Entender los datos": [
        st.Page("views/clientes.py", title="1 · Clientes", icon=":material/groups:"),
        st.Page("views/productos.py", title="2 · Productos", icon=":material/stacked_line_chart:"),
        st.Page("views/transiciones.py", title="3 · Transiciones", icon=":material/alt_route:"),
    ],
    "Modelo y decisión": [
        st.Page("views/modelo.py", title="4 · Desempeño del modelo", icon=":material/insights:"),
        st.Page("views/impacto.py", title="5 · Impacto de negocio", icon=":material/payments:"),
        st.Page("views/recomendador.py", title="6 · Recomendador por cliente",
                icon=":material/person_search:"),
    ],
}

navigation = st.navigation(pages, position="sidebar", expanded=True)

with st.sidebar:
    st.divider()
    online = api_online()
    color = "#3FB27F" if online else "#E5484D"
    state = "API en línea" if online else "API sin conexión"
    st.markdown(
        '<div class="fs-brand-sub">Recomendación de productos financieros · '
        'Santander, ene 2015 – may 2016</div>'
        f'<div class="fs-status"><span class="fs-dot" style="background:{color}"></span>{state}'
        '<br/>Datos: tablas gold en S3 vía Athena · FastAPI en AWS ECS'
        '<br/>Modelo: LightGBM multiclase (versión 20261118)</div>',
        unsafe_allow_html=True,
    )

navigation.run()
