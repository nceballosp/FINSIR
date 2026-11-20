# Tablero FINSIR (Streamlit)

Tablero interactivo de la materia **Visualización de Datos**. Consume la API
FINSIR desplegada en AWS ECS (tablas gold vía Athena + modelo LightGBM) y
presenta el análisis como un recorrido narrativo: del contexto del negocio al
Top-7 de un cliente concreto.

## Ejecutar

Requiere la plataforma de datos, el modelo y la API desplegados (ver el
[README de la raíz](../README.md)) y el archivo `.streamlit/secrets.toml`:

```toml
API_BASE_URL = "http://<IP-actual-de-la-API>:8080"
AUTH_DEV_SECRET = "<secreto configurado en la API>"
```

Desde la **raíz del repositorio** (así Streamlit encuentra `.streamlit/`):

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r dashboard\requirements.txt
.\.venv\Scripts\python.exe -m streamlit run dashboard\app.py
```

Antes de una presentación, precarga la caché para que todo abra al instante:

```powershell
.\.venv\Scripts\python.exe dashboard\warm_cache.py
```

La caché queda en `dashboard/.cache/` (ignorada por git). Bórrala para forzar
datos frescos de la API.

## Publicar en Streamlit Community Cloud

El tablero corre en la nube de Streamlit y consulta la API en AWS. Requisitos:
la rama subida a GitHub, la API corriendo en ECS y una cuenta en
[share.streamlit.io](https://share.streamlit.io) conectada a GitHub con acceso
al repositorio.

1. **Obtén la URL actual de la API** (cambia en cada redespliegue de ECS):

   ```powershell
   .\dashboard\get_api_url.ps1
   ```

2. En [share.streamlit.io](https://share.streamlit.io) → **Create app** →
   **Deploy a public app from GitHub**:
   - **Repository:** `nceballosp/FINSIR`
   - **Branch:** la rama del tablero
   - **Main file path:** `dashboard/app.py`
   - **App URL:** el subdominio que quieras (por ejemplo `finsir-dashboard`)
3. **Advanced settings:**
   - **Python version:** 3.12 (pandas 3 necesita Python 3.11 o superior).
   - **Secrets:** pega el contenido de `.streamlit/secrets.toml.example` con
     los valores reales (la URL del paso 1 y el secreto de la API).
4. **Deploy.** Streamlit instala `dashboard/requirements.txt` (lo busca junto a
   `app.py`) y aplica el tema de `.streamlit/config.toml`.

**Si cambia la IP de la API** (después de `iac/api/deploy.ps1` o de destruir y
volver a crear la infraestructura): ejecuta de nuevo `get_api_url.ps1`, entra a
la app en Streamlit → **Settings → Secrets**, reemplaza `API_BASE_URL` y guarda.
La app se reinicia sola.

Tenlo en cuenta:

- **La app es pública.** Cualquiera con el enlace puede verla, igual que la API.
- **La caché en disco de la nube se borra en cada reinicio**, así que las
  primeras cargas tardan lo que tarde la API (hasta ~1 min por vista). Abre
  las páginas una vez antes de presentar.
- **Si apagas la infraestructura de AWS, la app en la nube deja de tener datos.**
  Para presentar sin depender de la red, usa la versión local con la caché
  precargada.

## Recorrido (argumentación visual)

| Página | Pregunta que responde | Interacción |
|---|---|---|
| Resumen ejecutivo | ¿Qué problema resolvemos y cuánto mejora el modelo? | Enlaces al recorrido |
| 1 · Clientes | ¿Quiénes son y qué tiene cada perfil? | Mes, segmento, dimensión del mapa de calor, producto en detalle |
| 2 · Productos | ¿Qué se contrata, cuándo y con qué estacionalidad? | Mes, familia, clic en una barra o selector para ver el detalle de un producto |
| 3 · Transiciones | ¿Qué tenía el cliente antes de contratar? | Mes, producto destino, n.º de orígenes, producto de afinidad |
| 4 · Desempeño del modelo | ¿Cómo se validó y dónde acierta más? | Dimensión de análisis de errores |
| 5 · Impacto de negocio | ¿Qué significa en conversiones y costo? | Contactos, costo, margen, criterio de priorización |
| 6 · Recomendador | ¿Qué se le ofrece a un cliente concreto y por qué? | ID de cliente (consulta en vivo a la API), casos de prueba |

## Decisiones de diseño

- **Títulos declarativos y calculados.** Cada gráfico titula el hallazgo (no la
  descripción) y el texto se calcula con los datos filtrados, así que sigue
  siendo verdadero al cambiar el mes o el segmento.
- **Dos colores con jerarquía.** Azul marino para la estructura y los datos,
  ámbar solo para el dato que se debe ver primero, gris para el contexto. La
  paleta se validó para daltonismo (separación ΔE 43 entre azul y ámbar) y
  contraste. Como el ámbar queda por debajo de 3:1, toda marca ámbar lleva
  etiqueta directa.
- **Tipografía IBM Plex Sans**, estilo de informe financiero: reglas finas, sin
  sombras ni degradados, números con separador de miles en español.
- **Cada gráfico tiene su tabla** (expansor «Ver datos del gráfico») para leer
  valores exactos y por accesibilidad.
- **Honestidad de los números.** Los supuestos de negocio son editables y se
  declaran; las limitaciones (asociación, no causalidad; solo LightGBM contra el
  baseline) se explican en la página correspondiente.

## Estructura

```
dashboard/
  app.py               navegación y barra lateral
  views/               una página por paso del recorrido
  core/api.py          cliente de la API (JWT, paginación, errores)
  core/data.py         carga con caché en memoria y en disco
  core/catalog.py      nombres legibles de productos, segmentos y variables
  core/theme.py        paleta y plantilla de Plotly
  core/charts.py       barras, mapas de calor y anotaciones con la marca
  core/ui.py           encabezados, indicadores, tarjetas y notas
  assets/model/        métricas del entrenamiento (train.py) del modelo servido
  warm_cache.py        precarga de la caché
```

## Nota técnica: paginación de la API

Los endpoints de listado de la API paginan con `LIMIT/OFFSET` sin un
`ORDER BY` estable, así que Athena puede repetir u omitir filas entre páginas.
Por ejemplo, en mayo de 2016 desaparecían las transiciones hacia Tarjeta de
crédito. El tablero lo evita partiendo cada consulta con un filtro (por
producto o segmento) para que cada parte quepa en una sola página.
La corrección de fondo es agregar un orden determinista en
`iac/api/app/adapters/driven/athena/athena_gold_analytics_repository.py`.
