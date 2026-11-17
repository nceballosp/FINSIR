import time

import jwt
import requests
import streamlit as st

api_url = st.secrets["API_BASE_URL"].rstrip("/")


def create_token() -> str:
    now = int(time.time())
    claims = {
        "sub": "streamlit-demo",
        "scope": "gold:read",
        "iat": now - 120,
        "nbf": now - 120,
        "exp": now + 900,
    }
    return jwt.encode(
        claims,
        st.secrets["AUTH_DEV_SECRET"],
        algorithm="HS256",
    )


st.title("Recomendaciones FINSIR")
client_id = st.number_input("ID del cliente", min_value=0, step=1)

if st.button("Consultar recomendaciones"):
    try:
        response = requests.get(
            f"{api_url}/v1/recommendations/clients/{int(client_id)}",
            headers={"Authorization": f"Bearer {create_token()}"},
            timeout=60,
        )

        if response.ok:
            payload = response.json()["data"]
            st.caption(f"Versión del modelo: {payload['model_version']}")
            item = payload["items"][0]
            st.write(f"Cliente: {item['ncodpers']} · Fecha: {item['fecha_dato']}")
            st.dataframe(item["recommendations"])
        else:
            st.error(f"Error {response.status_code}: {response.text}")
    except requests.RequestException as error:
        st.error(f"No se pudo conectar con la API: {error}")