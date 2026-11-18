# Dashboard FINSIR (Entrega 2 · Visualización de datos)

Dashboard interactivo en **Streamlit + Plotly** que explica el proyecto en ~5 minutos,
como un recorrido de 6 secciones (barra lateral o botones **Siguiente →**):

| # | Sección | Qué responde | Interacción |
|---|---------|--------------|-------------|
| 1 | El problema | Qué es FINSIR, justificación y objetivo | Tooltips |
| 2 | Los datos | Perfil de clientes y tenencia de productos | Filtro por segmento, pestañas, mapa de calor por dimensión |
| 3 | Patrones de contratación | Estacionalidad, Sankey de transiciones, afinidad | Selector de producto, destinos del Sankey, phi/lift |
| 4 | Cómo lo hicimos | Arquitectura AWS, pipeline, corte temporal, MAP@7 | Calculadora interactiva de AP@7 |
| 5 | Resultados | LightGBM vs. modelo base, variables, segmentos | Filtro por segmento, simulador, API en vivo |
| 6 | Conclusiones | Hallazgos, limitaciones, próximos pasos | — |

## Archivos

```
visualizacion/
  app.py                 el dashboard
  preparar_datos.py      precalcula los agregados desde data/train_ver2.csv (DuckDB, ~30 s)
  requirements.txt
  .streamlit/config.toml tema visual
  datos/                 agregados pequeños (< 200 KB) que lee el dashboard
    resultados_modelo.json  métricas del modelo (salidas de notebooks/prueba_modelo.ipynb)
```

Los agregados replican las reglas de las tablas gold analíticas
(`iac/data-platform/glue/gold_analytics.py`) sobre el dataset completo, así el dashboard
funciona **sin AWS encendido**. Solo la pestaña "API en vivo" necesita la API desplegada.

## Ejecutar (Windows PowerShell, desde la raíz del repo)

```powershell
cd visualizacion
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
# Solo la primera vez (o si cambian los datos). Necesita data/train_ver2.csv:
.\.venv\Scripts\python.exe preparar_datos.py
.\.venv\Scripts\python.exe -m streamlit run app.py
```

Se abre en `http://localhost:8501`. Ejecuta Streamlit **desde `visualizacion/`** para que
cargue el tema de `.streamlit/config.toml`.

Si `datos/` ya tiene los `.parquet` (por ejemplo, porque alguien del equipo los compartió),
puedes saltarte `preparar_datos.py` y no necesitas el CSV.

## Opcional

- **Métricas del entrenamiento completo:** copia la salida de `iac/model-training/train.py`
  (`metrics.json` y `test_metrics_by_segment.csv`) a `visualizacion/datos/modelo/`. El
  dashboard la usa en lugar de los resultados del notebook (muestra del 10 %).
- **API en vivo:** crea `visualizacion/.streamlit/secrets.toml` (está en `.gitignore`):

  ```toml
  API_BASE_URL = "http://<IP-actual-de-la-API>:8080"
  AUTH_DEV_SECRET = "<secreto-configurado-en-la-API>"
  ```

  También puedes escribir la URL y el secreto directamente en la pestaña "API en vivo".

## Guion sugerido (5 minutos)

1. **El problema (45 s):** campañas masivas → solo ~3,6 % compra algo nuevo al mes. Objetivo: Top-7 personalizado que supere a la popularidad en MAP@7.
2. **Los datos (45 s):** portafolio concentrado (cuenta corriente 60 %); el perfil cambia qué tiene cada cliente (cambiar "Comparar por").
3. **Patrones (60 s):** pico de Impuestos en junio; Sankey: lo que se tenía antes predice lo que viene; bloque nómina-pensión-débito.
4. **Cómo (60 s):** arquitectura AWS, corte temporal sin fuga, jugar con la calculadora de AP@7.
5. **Resultados (60 s):** +38 % vs. modelo base, variables rezagadas al tope, mejor en VIP/35-54 años; simulador.
6. **Conclusiones (30 s).**
