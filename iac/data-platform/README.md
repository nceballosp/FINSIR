# Plataforma de datos FINSIR (lakehouse silver + gold)

Terraform que construye las capas silver y gold de FINSIR: un data lake en S3,
un job de Glue que limpia el dataset crudo `train` de Santander, dos jobs de
Glue que construyen las tablas gold y un workgroup de Athena con una base de
datos y seis tablas en el catálogo de Glue.

> ¿Solo quieres desplegar rápido? Hay un script interactivo
> (`deploy.sh` / `deploy.ps1`) que hace todo esto por ti. El paso a paso manual
> de abajo es para entender qué ocurre. Deploy y destroy simples:
> [README de la raíz](../../README.md#deploy-rápido-con-los-scripts).

## Qué crea

- **Data lake en S3** (`aws_s3_bucket.lake`): cifrado, sin acceso público.
  Guarda el CSV crudo, los scripts de Glue y las salidas silver / rechazados /
  calidad / gold.
- **Job de Glue** `finsir-limpieza-train`: corre `glue/limpieza_train.py`
  (Glue 5.0 / Spark) para limpiar y tipar los datos, escribiendo Parquet
  particionado por `fecha_dato`, más un dataset de filas rechazadas y un reporte
  de calidad.
- **Job de Glue** `finsir-gold-train`: corre `glue/gold_train.py` para construir
  `gold_train` desde silver (ver [Capa gold](#capa-gold-gold_train)).
- **Job de Glue** `finsir-gold-segment-conversion`: corre
  `glue/gold_segment_conversion.py` para construir `gold_segment_conversion`
  desde silver (ver [Conversión por segmento](#conversión-por-segmento-gold_segment_conversion)).
- **IAM**: un rol de Glue de mínimo privilegio (lee datos crudos + scripts,
  escribe las carpetas silver, rechazados, calidad y gold, y `tmp/`).
- **Athena**: un workgroup, la base de datos `finsir` y seis tablas:
    - `bronze_train`: CSV crudo tal cual, todo string.
    - `silver_train`: Parquet limpio, particionado por `fecha_dato`.
    - `rechazados_train`: filas rechazadas con su motivo.
    - `calidad_train`: reporte de calidad de la última corrida.
    - `gold_train`: tabla de entrenamiento del modelo, particionada por `fecha_dato`.
    - `gold_segment_conversion`: tasas de conversión de producto por segmento, particionada por `fecha_dato`.

## Estructura

```
iac/data-platform/
  glue/      limpieza_train.py            Job de limpieza: bronze -> silver (lo sube s3.tf)
             gold_train.py                Job gold: silver -> gold_train (lo sube s3.tf)
             gold_segment_conversion.py   Job gold: silver -> gold_segment_conversion (lo sube s3.tf)
             test_*.py                    Tests PySpark local (sin AWS)
  athena/    01_tablas.sql, 02_calidad.sql   SQL de referencia (las tablas las crea Terraform)
  terraform/ el módulo
```

`glue/` debe quedar junto a `terraform/` porque `s3.tf` sube los scripts desde
`../glue/`.

## Paso a paso (manual)

```bash
cd terraform
cp terraform.tfvars.example terraform.tfvars
terraform init
terraform apply
BUCKET=$(terraform output -raw bucket)
```

Luego sube el CSV crudo y corre el job de limpieza. El archivo pesa ~2.3 GB y no
lo maneja Terraform, así que **ponlo en `data/train_ver2.csv` primero**
(descárgalo del dataset Santander Product Recommendation en Kaggle):

```bash
aws s3 cp ../../../data/train_ver2.csv "s3://$BUCKET/raw/train/train_ver2.csv"
aws glue start-job-run --job-name finsir-limpieza-train --region us-east-1
```

Cuando el job de limpieza esté en `SUCCEEDED`, construye las tablas gold:

```bash
aws glue start-job-run --job-name finsir-gold-train --region us-east-1
aws glue start-job-run --job-name finsir-gold-segment-conversion --region us-east-1
aws glue get-job-runs --job-name finsir-gold-train --region us-east-1 \
  --max-items 1 --query 'JobRuns[0].JobRunState'
```

Ambos jobs gold leen silver, así que córrelos después de que la limpieza tenga
éxito; son independientes entre sí y pueden correr en paralelo.

El nombre del bucket y estos comandos también son outputs de Terraform
(`bucket`, `subir_el_csv`, `ejecutar_la_limpieza`, `run_gold_train`,
`run_gold_segment_conversion`). `silver_train`, `gold_train` y
`gold_segment_conversion` quedan consultables en Athena apenas termina su job
(no hace falta `MSCK REPAIR TABLE`: usan partition projection).

## Capa gold: `gold_train`

La tabla sobre la que entrena el modelo de propensión. Vive en
`s3://<bucket>/gold/train/` como Parquet particionado por `fecha_dato`.

**Filas.** Una fila por cliente (`ncodpers`) por mes (`fecha_dato`), una por cada
fila de silver. No se descarta ninguna: el job compara el conteo de filas de
silver y gold y falla si difieren.

**Qué significa una fila.** Para el cliente `c` en el mes `t`, la fila tiene el
perfil y productos de `c` en el mes `t`, los productos que tenía 1, 3 y 6 meses
antes, y las respuestas: qué productos adquiere `c` en el mes `t+1`.

**Origen** en las tablas de abajo:

- **raw**: copiado sin cambios desde `silver_train`, que es la columna del CSV
  de Kaggle tras limpieza y tipado.
- **computed**: calculado por `glue/gold_train.py`.

### Columnas clave y de perfil

| Columna                 | Tipo               | Origen   | Descripción                                                                                               |
| ----------------------- | ------------------ | -------- | --------------------------------------------------------------------------------------------------------- |
| `ncodpers`              | bigint             | raw      | ID del cliente.                                                                                           |
| `fecha_dato`            | string (partición) | raw      | Mes del registro, `YYYY-MM-DD` (2015-01-28 a 2016-05-28).                                                 |
| `month_of_year`         | int                | computed | Número de mes (1-12) de `fecha_dato`, para estacionalidad.                                                |
| `ind_empleado`          | string             | raw      | Estado de empleado: A activo, B ex-empleado, F filial, N no empleado, P pasivo.                           |
| `pais_residencia`       | string             | raw      | País de residencia.                                                                                       |
| `sexo`                  | string             | raw      | Sexo.                                                                                                     |
| `age`                   | int                | raw      | Edad (null si es imposible en el CSV, ver limpieza silver).                                               |
| `antiguedad`            | int                | raw      | Antigüedad en meses (null si es negativa en el CSV).                                                      |
| `ind_nuevo`             | int                | raw      | 1 si el cliente se registró en los últimos 6 meses.                                                       |
| `indrel`                | int                | raw      | 1 cliente primario; 99 primario durante el mes pero no al cierre.                                         |
| `indrel_1mes`           | string             | raw      | Tipo de cliente al inicio del mes: 1 primario, 2 co-titular, P potencial, 3 ex primario, 4 ex co-titular. |
| `tiprel_1mes`           | string             | raw      | Relación al inicio del mes: A activo, I inactivo, P ex cliente, R potencial.                              |
| `indresi`               | string             | raw      | S/N: vive en el mismo país que el banco.                                                                  |
| `indext`                | string             | raw      | S/N: nació en un país distinto al del banco.                                                              |
| `canal_entrada`         | string             | raw      | Canal por el que entró el cliente.                                                                        |
| `indfall`               | string             | raw      | S/N: fallecido.                                                                                           |
| `cod_prov`              | int                | raw      | Código de provincia de la dirección del cliente.                                                          |
| `ind_actividad_cliente` | int                | raw      | 1 cliente activo, 0 inactivo.                                                                             |
| `renta`                 | double             | raw      | Ingreso bruto del hogar (null si se desconoce; nunca se imputa).                                          |
| `segmento`              | string             | raw      | 01 VIP, 02 particulares, 03 recién graduados.                                                             |

### Columnas de producto

Cada uno de los 24 productos tiene cinco columnas. Las familias:

| Patrón de columna      | Tipo | Origen   | Descripción                                                                                                                                       |
| ---------------------- | ---- | -------- | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| `<product>`            | int  | raw      | 1 si el cliente tiene el producto en el mes `t`, 0 si no, null si falta en el CSV.                                                                |
| `<product>_lag1`       | int  | computed | `<product>` en el mes `t-1`. Null si el cliente no tiene fila ese mes o el valor falta.                                                           |
| `<product>_lag3`       | int  | computed | `<product>` en el mes `t-3`. Misma regla de null.                                                                                                 |
| `<product>_lag6`       | int  | computed | `<product>` en el mes `t-6`. Misma regla de null.                                                                                                 |
| `added_<product>`      | int  | computed | 1 si el cliente adquirió el producto **este** mes (no lo tenía en `t-1`, lo tiene en `t`), 0 si no. Null si no hay fila en `t-1`. Feature segura. |
| `label_next_<product>` | int  | computed | **Etiqueta.** 1 si el cliente lo adquiere en `t+1` (no lo tiene en `t`, lo tiene en `t+1`), 0 si no. Null si el cliente no tiene fila en `t+1`.   |

`added_<product>` (este mes) y `label_next_<product>` (mes siguiente) usan la
misma regla 0→1 desplazada un mes: la primera es una feature de entrada, la
segunda es la respuesta.

Los lags miran meses de calendario, no la fila anterior: si un cliente se salta
un mes, el lag es null en vez de un valor más viejo.

Los 24 productos y sus nombres de columna (cada uno tiene también `added_<product>`):

| Producto                 | Tenencia (raw)      | Lags (computed)                            | Etiqueta (computed)            |
| ------------------------ | ------------------- | ------------------------------------------ | ------------------------------ |
| Cuenta de ahorros        | `ind_ahor_fin_ult1` | `ind_ahor_fin_ult1_lag1`, `_lag3`, `_lag6` | `label_next_ind_ahor_fin_ult1` |
| Garantías                | `ind_aval_fin_ult1` | `ind_aval_fin_ult1_lag1`, `_lag3`, `_lag6` | `label_next_ind_aval_fin_ult1` |
| Cuenta corriente         | `ind_cco_fin_ult1`  | `ind_cco_fin_ult1_lag1`, `_lag3`, `_lag6`  | `label_next_ind_cco_fin_ult1`  |
| Cuenta de derivados      | `ind_cder_fin_ult1` | `ind_cder_fin_ult1_lag1`, `_lag3`, `_lag6` | `label_next_ind_cder_fin_ult1` |
| Cuenta de nómina         | `ind_cno_fin_ult1`  | `ind_cno_fin_ult1_lag1`, `_lag3`, `_lag6`  | `label_next_ind_cno_fin_ult1`  |
| Cuenta junior            | `ind_ctju_fin_ult1` | `ind_ctju_fin_ult1_lag1`, `_lag3`, `_lag6` | `label_next_ind_ctju_fin_ult1` |
| Cuenta "Más particular"  | `ind_ctma_fin_ult1` | `ind_ctma_fin_ult1_lag1`, `_lag3`, `_lag6` | `label_next_ind_ctma_fin_ult1` |
| Cuenta "Particular"      | `ind_ctop_fin_ult1` | `ind_ctop_fin_ult1_lag1`, `_lag3`, `_lag6` | `label_next_ind_ctop_fin_ult1` |
| Cuenta "Particular Plus" | `ind_ctpp_fin_ult1` | `ind_ctpp_fin_ult1_lag1`, `_lag3`, `_lag6` | `label_next_ind_ctpp_fin_ult1` |
| Depósito corto plazo     | `ind_deco_fin_ult1` | `ind_deco_fin_ult1_lag1`, `_lag3`, `_lag6` | `label_next_ind_deco_fin_ult1` |
| Depósito mediano plazo   | `ind_deme_fin_ult1` | `ind_deme_fin_ult1_lag1`, `_lag3`, `_lag6` | `label_next_ind_deme_fin_ult1` |
| Depósito largo plazo     | `ind_dela_fin_ult1` | `ind_dela_fin_ult1_lag1`, `_lag3`, `_lag6` | `label_next_ind_dela_fin_ult1` |
| Cuenta electrónica       | `ind_ecue_fin_ult1` | `ind_ecue_fin_ult1_lag1`, `_lag3`, `_lag6` | `label_next_ind_ecue_fin_ult1` |
| Fondos                   | `ind_fond_fin_ult1` | `ind_fond_fin_ult1_lag1`, `_lag3`, `_lag6` | `label_next_ind_fond_fin_ult1` |
| Hipoteca                 | `ind_hip_fin_ult1`  | `ind_hip_fin_ult1_lag1`, `_lag3`, `_lag6`  | `label_next_ind_hip_fin_ult1`  |
| Plan de pensiones        | `ind_plan_fin_ult1` | `ind_plan_fin_ult1_lag1`, `_lag3`, `_lag6` | `label_next_ind_plan_fin_ult1` |
| Préstamos                | `ind_pres_fin_ult1` | `ind_pres_fin_ult1_lag1`, `_lag3`, `_lag6` | `label_next_ind_pres_fin_ult1` |
| Impuestos                | `ind_reca_fin_ult1` | `ind_reca_fin_ult1_lag1`, `_lag3`, `_lag6` | `label_next_ind_reca_fin_ult1` |
| Tarjeta de crédito       | `ind_tjcr_fin_ult1` | `ind_tjcr_fin_ult1_lag1`, `_lag3`, `_lag6` | `label_next_ind_tjcr_fin_ult1` |
| Valores                  | `ind_valo_fin_ult1` | `ind_valo_fin_ult1_lag1`, `_lag3`, `_lag6` | `label_next_ind_valo_fin_ult1` |
| Cuenta vivienda          | `ind_viv_fin_ult1`  | `ind_viv_fin_ult1_lag1`, `_lag3`, `_lag6`  | `label_next_ind_viv_fin_ult1`  |
| Nómina                   | `ind_nomina_ult1`   | `ind_nomina_ult1_lag1`, `_lag3`, `_lag6`   | `label_next_ind_nomina_ult1`   |
| Pensiones                | `ind_nom_pens_ult1` | `ind_nom_pens_ult1_lag1`, `_lag3`, `_lag6` | `label_next_ind_nom_pens_ult1` |
| Débito directo           | `ind_recibo_ult1`   | `ind_recibo_ult1_lag1`, `_lag3`, `_lag6`   | `label_next_ind_recibo_ult1`   |

### Columnas de conteo

| Columna              | Tipo | Origen   | Descripción                                                                                                                                                 |
| -------------------- | ---- | -------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `n_products`         | int  | computed | Productos que tiene en el mes `t`.                                                                                                                          |
| `n_products_added`   | int  | computed | Productos adquiridos en el mes `t` (no en `t-1`, sí en `t`). Null si el cliente no tiene fila en `t-1`.                                                     |
| `n_products_dropped` | int  | computed | Productos dados de baja en el mes `t` (sí en `t-1`, no en `t`). Null si el cliente no tiene fila en `t-1`.                                                  |
| `has_previous_month` | int  | computed | 1 si el cliente tiene fila en `t-1`, 0 si no (cliente nuevo o mes saltado).                                                                                 |
| `label_next_n_added` | int  | computed | **Etiqueta.** Número de productos adquiridos en `t+1`. Null si no tiene fila en `t+1`. Usa `label_next_n_added > 0` para elegir las filas de entrenamiento. |

En total: 168 columnas más la partición `fecha_dato` (2 clave, 17 perfil, 24
tenencias, 72 lags, 24 `added_`, 4 conteos, 24 `label_next_`, 1 `label_next_n_added`).

### Columnas de silver que quedaron fuera

| Columna                                   | Por qué                                      |
| ----------------------------------------- | -------------------------------------------- |
| `nomprov`                                 | Misma información que `cod_prov`.            |
| `tipodom`                                 | Siempre 1.                                   |
| `conyuemp`, `ult_fec_cli_1t`              | Casi siempre vacías.                         |
| `fecha_alta`                              | `antiguedad` ya mide la antigüedad.          |
| `campos_rescatados`, `campos_invalidados` | Seguimiento de calidad, no info del cliente. |

Siguen en `silver_train`; no se borra nada del lake.

## Conversión por segmento: `gold_segment_conversion`

Qué tan seguido cada tipo de cliente adopta cada producto. Ayuda al modelo con
clientes de poca historia y alimenta el dashboard. Vive en
`s3://<bucket>/gold/segment_conversion/` como Parquet particionado por
`fecha_dato`.

**Filas.** Una fila por `fecha_dato` × `segmento` × producto (24 productos × los
segmentos presentes cada mes). Las filas sin `segmento` se descartan: la tasa se
define por segmento.

**Qué significa una fila.** Para un segmento y producto en el mes `t`, la tasa
de conversión es adoptantes ÷ elegibles, contando sobre todos los meses
**estrictamente anteriores** a `t`:

- **elegibles**: clientes del segmento que no tenían el producto el mes anterior
  y que tienen fila ese mes (para poder observar una adopción),
- **adoptantes**: esos elegibles que empezaron a tenerlo ese mes.

| Columna           | Tipo               | Origen   | Descripción                                                                                     |
| ----------------- | ------------------ | -------- | ----------------------------------------------------------------------------------------------- |
| `segmento`        | string             | raw      | Segmento del cliente (01 VIP, 02 particulares, 03 recién graduados).                            |
| `product`         | string             | computed | Uno de los 24 nombres de producto `ind_*_ult1`.                                                 |
| `eligible`        | bigint             | computed | Clientes del segmento elegibles a adoptar, sumados sobre todos los meses antes de `fecha_dato`. |
| `adopters`        | bigint             | computed | Clientes elegibles que lo adoptaron, sumados sobre todos los meses antes de `fecha_dato`.       |
| `conversion_rate` | double             | computed | `adopters / eligible`. Null cuando `eligible` es 0 (el primer mes no tiene datos previos).      |
| `fecha_dato`      | string (partición) | raw      | El mes al que aplica la tasa, `YYYY-MM-DD`.                                                     |

**Sin fuga de información.** La tasa del mes `t` usa solo meses anteriores a `t`,
así que unir `gold_segment_conversion` en `gold_train` por (`fecha_dato`,
`segmento`, `product`) da una feature que nunca ve las compras ni la etiqueta del
propio mes `t`. La tasa del primer mes es null.

## Reglas para usar gold_train sin fuga de información

- **Features** son todas las columnas sin el prefijo `label_next_`, incluidas
  las banderas `added_`. Solo leen meses hasta `t`.
- **Etiquetas** son las columnas `label_next_`. Leen el mes `t+1`. Nunca las
  uses como entrada del modelo.
- Un valor de producto faltante cuenta como "no tenido" al calcular adquisiciones,
  así que un producto que pasa de null a 1 cuenta como adquirido.
- **Mayo 2016 no tiene etiquetas** (no hay junio 2016 en el CSV). Esas filas son
  la entrada para recomendaciones reales.
- **Split fuera de tiempo:** entrena con filas hasta `fecha_dato` 2016-02-28,
  valida con 2016-03-28 (las etiquetas son las adquisiciones de abril) y prueba
  con 2016-04-28 (etiquetas de mayo). Nunca entrenes con el mes de prueba.

## Toggles

| Variable                 | Default | Qué hace                                                                                       |
| ------------------------ | ------- | ---------------------------------------------------------------------------------------------- |
| `create_bucket`          | `true`  | Crear el bucket, o reutilizar uno (entonces `bucket_name` es obligatorio).                     |
| `create_athena`          | `true`  | Crear la base de datos, el workgroup y las tablas.                                             |
| `existing_glue_role_arn` | `""`    | Reutilizar un rol de Glue existente en vez de crear uno.                                       |
| `partition_projection`   | `true`  | Autodescubrir las particiones `fecha_dato=...`.                                                |
| `force_destroy_bucket`   | `false` | Permitir que `terraform destroy` borre un bucket no vacío. Déjalo en `false` con datos reales. |

La carpeta de salida gold es `gold_prefix` (default `gold/train/`).

La región por defecto es `us-east-1`; `aws ~> 5.80`, Terraform `>= 1.5`.

## Orquestación (EventBridge → Step Functions → Glue)

El batch puede correr solo. Terraform crea una Step Functions que ejecuta la
limpieza y, cuando termina, lanza **todos los jobs gold en paralelo**; una regla
de EventBridge la dispara según un horario.

- `finsir-batch-diario` (Step Functions): estado `Limpieza` (síncrono) → estado
  `TablasGold`, un `Map` que corre en paralelo cada job de `local.gold_job_names`.
- `finsir-pipeline-diario` (EventBridge): regla programada que arranca la Step
  Functions y le pasa la lista de jobs gold como input.

**Agregar una tabla gold nueva:** añade su job a `local.gold_job_names` en
`main.tf`. El `Map` lo recoge solo; no hay que tocar la state machine.

| Variable               | Default             | Qué hace                                           |
| ---------------------- | ------------------- | -------------------------------------------------- |
| `create_orchestration` | `true`              | Crear la Step Functions + la regla de EventBridge. |
| `schedule_expression`  | `cron(0 6 * * ? *)` | Cuándo dispara (UTC). cron o rate.                 |
| `schedule_enabled`     | `false`             | `false` deja la regla creada pero apagada.         |

La regla nace **apagada** para que no corra sola hasta que lo decidas. El cron
por defecto es `cron(0 6 * * ? *)` (06:00 UTC = 01:00 Colombia, diario).

### Activar o desactivar el horario

Con el script `deploy.sh` / `deploy.ps1`: te pregunta "Enable the EventBridge
daily schedule now?" (default **no**). Responde según quieras.

A mano: cambia `schedule_enabled` en `terraform.tfvars` y vuelve a aplicar.

```bash
# activar          -> schedule_enabled = true
# desactivar       -> schedule_enabled = false
terraform apply
```

También puedes encender/apagar la regla sin Terraform (se revierte en el próximo
apply):

```bash
aws events disable-rule --name finsir-pipeline-diario --region us-east-1
aws events enable-rule  --name finsir-pipeline-diario --region us-east-1
```

### Correr el batch a mano

El `deploy.sh` / `deploy.ps1` te pregunta al final _"Start the batch now?"_: si
dices que sí, arranca la Step Functions completa (limpieza → tablas gold en
paralelo), no solo la limpieza. También imprime el comando listo para volver a
correrlo. Y lo da Terraform:

```bash
terraform output -raw run_batch   # imprime el aws stepfunctions start-execution listo
```

Para seguir una ejecución:

```bash
aws stepfunctions describe-execution --execution-arn <arn-que-imprime-start-execution> \
  --region us-east-1 --query status
```

> El patrón `.sync` de Glue hace que la Step Functions espere a que cada job
> termine antes de seguir, así que la limpieza acaba `SUCCEEDED` antes de que
> arranquen los jobs gold.

## Pendiente

Las demás tablas gold (agregados del dashboard, resultados del test) se agregan
sumando su job a `local.gold_job_names`. El modelo de ML y el dashboard
Streamlit vienen después.

## Tests

```bash
pip install pyspark pytest
python -m pytest glue
```

Los tests de `gold_train` verifican las etiquetas, los lags, las banderas
`added_`, la regla de mes saltado, que no se pierda ninguna fila, que las
features no cambien al agregar meses futuros y que la lista de columnas de la API
coincida con la del job. Los tests de `gold_segment_conversion` verifican que la
tasa solo use meses anteriores (nunca el propio), que los segmentos queden
separados y que las filas sin segmento se descarten.
