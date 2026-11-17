# Ejecutar la app de Streamlit

La app consume la API FINSIR que corre en ECS. Consulta las recomendaciones
por ID de cliente mediante `GET /v1/recommendations/clients/{ncodpers}`.

## Requisitos

- Python 3.10 o posterior.
- La API desplegada y su artefacto de modelo disponible en S3.
- El archivo local `.streamlit/secrets.toml` configurado.

El archivo `secrets.toml` debe tener estos nombres de configuración:

```toml
API_BASE_URL = "http://<IP-actual-de-la-API>:8080"
AUTH_DEV_SECRET = "<secreto-configurado-en-la-API>"
```

No subas `secrets.toml` a Git. Está agregado a `.gitignore`. Si cambia la IP
pública de ECS después de un redeploy, actualiza `API_BASE_URL`.

## Instalar y ejecutar en Windows

Abre PowerShell en la raíz del repositorio y ejecuta:

```powershell
python -m venv .venv-streamlit
.\.venv-streamlit\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install streamlit requests PyJWT
streamlit run .streamlit/app.py
```

Si PowerShell bloquea la activación del entorno, puedes ejecutar Streamlit sin
activarlo:

```powershell
.\.venv-streamlit\Scripts\python.exe -m streamlit run .streamlit/app.py
```

La app se abre normalmente en `http://localhost:8501`. Ingresa un ID de cliente
que exista en la tabla `gold_train` y pulsa **Consultar recomendaciones**.
La página muestra la versión del modelo y el ranking de productos.

## Errores frecuentes

- **401 o 403:** verifica `AUTH_DEV_SECRET` y que el token tenga el scope
  `gold:read`. La app genera un token de 15 minutos para cada consulta.
- **No se pudo conectar:** confirma que ECS esté corriendo y que
  `API_BASE_URL` tenga la IP actual y el puerto `8080`.
- **404 o cliente sin datos:** usa un `ncodpers` que exista en `gold_train`.
- **503 `model_unavailable`:** revisa que ECS se haya desplegado con
  `MODEL_S3_URI` apuntando al `.joblib` correcto.

> Esta configuración usa el modo de autenticación de desarrollo y HTTP. Es
> adecuada para pruebas locales; para publicar Streamlit en Internet, configura
> HTTPS para la API y autenticación de producción antes de exponerla.
