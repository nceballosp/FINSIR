# FINSIR

Proyecto **FINSIR** para las materias Aprendizaje Automático, Almacenamiento y
Procesamiento de Grandes Datos, y Visualización de Datos (Énfasis en Ciencia de
Datos, EAFIT).

FINSIR recomienda productos financieros. Usando el dataset público _Santander
Product Recommendation_ (Kaggle), predice cuál de los 24 productos es más
probable que un cliente adquiera el mes siguiente y devuelve un ranking Top-K
(métrica: MAP@7).

> Más contexto: [`context/context.md`](context/context.md).
> Uso de IA en el proyecto: [`USO_DE_IA.md`](USO_DE_IA.md).

## Qué hay construido

Dos piezas, ambas con Terraform sobre AWS (`us-east-1`, `aws ~> 5.80`,
Terraform `>= 1.5`):

| Pieza               | Carpeta              | Qué hace                                                                                                                 |
| ------------------- | -------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| Plataforma de datos | `iac/data-platform/` | Data lake en S3 + jobs de Glue (limpieza y 8 tablas gold) + tablas en Athena + orquestación (Step Functions/EventBridge) |
| API                 | `iac/api/`           | FastAPI que lee las tablas gold (entrenamiento + 6 analíticas) desde Athena, corre en ECS Fargate                        |

## Cómo fluyen los datos

```
CSV (Kaggle)
  └─▶ S3 Bronze (CSV crudo)
        └─▶ Glue/PySpark limpia y tipa
              └─▶ S3 Silver (Parquet)
                    ├─▶ Glue/PySpark agrega historia + etiquetas del mes siguiente
                    │     └─▶ S3 Gold gold_train (Parquet)   ◀── la API lee esto
                    ├─▶ Glue/PySpark: tasas de conversión por segmento
                    │     └─▶ S3 Gold gold_segment_conversion
                    └─▶ Glue/PySpark: 6 tablas analíticas (KPIs, perfil, penetración,
                          afinidad, transiciones, modelo base de popularidad + MAP@7)
                          └─▶ S3 Gold gold_product_monthly_kpis, gold_customer_profile, …
```

Todo el batch lo orquesta una Step Functions (limpieza → los 8 jobs gold en
paralelo) que dispara una regla de EventBridge. Detalle de cada tabla en
[`iac/data-platform/README.md`](iac/data-platform/README.md#tablas-gold-analíticas-dashboard-y-modelo-base).

## Qué necesitas

- **Python** 3.10+
- **Terraform** >= 1.5
- **Docker** (para construir la imagen de la API)
- **AWS CLI** v2, con un perfil `terraform` que pueda usar S3, Glue, Athena,
  IAM, ECR y ECS en `us-east-1`
- El archivo de Kaggle **`train_ver2.csv`** (~2.3 GB). No está en el repo (muy
  grande para git). Descárgalo y ponlo en **`data/train_ver2.csv`**.

Los secretos nunca se escriben en el código. Los scripts te los piden al vuelo
y no los guardan en archivos versionados.

## Desplegar en AWS

Sigue este orden: prepara y ejecuta la plataforma de datos; opcionalmente
entrena el modelo; y despliega la API al final. La API depende del bucket y las
tablas Gold. Los lanzadores `.ps1` son para PowerShell; los `.sh`, para Bash en
Linux/macOS, WSL o Git Bash. Ejecuta los comandos desde la raíz del repositorio.
Necesitas AWS CLI v2, Terraform y credenciales válidas en el perfil que
indicarás. Para desplegar la API también necesitas Docker.

### 1. Plataforma de datos

El script pregunta perfil, región, nombre del bucket y si quieres activar el
horario diario. Aplica Terraform y ofrece subir `data/train_ver2.csv` y
arrancar el batch de Step Functions. Confirma que el batch completo termine
con estado `SUCCEEDED` antes de seguir; incluye la limpieza y la creación de
las tablas Gold.

```bash
# Linux / macOS, WSL o Git Bash
./iac/data-platform/deploy.sh
```

```powershell
# Windows PowerShell
.\iac\data-platform\deploy.ps1
```

Si el CSV aún no está en `data/train_ver2.csv`, el script permite indicar su
ruta. El horario de EventBridge queda desactivado por defecto; el batch también
se puede iniciar manualmente con el comando que imprime el script.

### 2. Entrenamiento del modelo (opcional)

Si quieres habilitar recomendaciones basadas en el modelo, configura una vez
el módulo de entrenamiento. Copia el archivo de ejemplo y edita
`terraform.tfvars`: selecciona el bucket de la plataforma y establece
`create_instance = true`.

```bash
# Linux / macOS, WSL o Git Bash
cp iac/model-training/terraform/terraform.tfvars.example iac/model-training/terraform/terraform.tfvars
./iac/model-training/deploy.sh
```

```powershell
# Windows PowerShell
Copy-Item iac/model-training/terraform/terraform.tfvars.example iac/model-training/terraform/terraform.tfvars
# Edita terraform.tfvars con el bucket existente y create_instance = true.
.\iac\model-training\deploy.ps1
```

El lanzador aplica Terraform e inicia automáticamente una ejecución de
`finsir-model-training`. Espera a que termine antes de desplegar la API con el
artefacto. Cada ejecución del lanzador inicia un entrenamiento nuevo. El
artefacto se guarda en `s3://<bucket>/models/production/finsir.joblib`.

### 3. API

Despliega la API después de que el batch de datos haya terminado. Si ejecutaste
el entrenamiento, indica al lanzador el URI del artefacto S3 cuando lo solicite
y acepta construir y subir la imagen actualizada a ECR.

```bash
# Linux / macOS, WSL o Git Bash
./iac/api/deploy.sh
```

```powershell
# Windows PowerShell
.\iac\api\deploy.ps1
```

Te pregunta perfil, región, cuenta y el secreto de auth; opcionalmente
construye y sube la imagen a ECR, aplica Terraform y al final imprime la URL
pública (`http://<ip>:8080`), el secreto y el scope para generar tokens.

> La IP es pública y cambia en cada redeploy. El script la resuelve y la
> muestra al terminar.

## Eliminar la infraestructura

Un solo script derriba todo en el orden correcto (API primero, luego
entrenamiento y plataforma). Te pregunta si borrar el data lake de S3 y la
imagen de ECR.

```bash
# Linux / macOS, WSL o Git Bash
./iac/destroy.sh
```

```powershell
# Windows PowerShell
.\iac\destroy.ps1
```

Al terminar nada queda corriendo ni facturando (solo los datos de S3 que
decidas conservar cuestan unos centavos).

## Correr la API local (sin desplegar en AWS)

El modo dev valida tokens HS256 sin ningún secreto versionado. Las rutas de
datos sí necesitan credenciales de AWS porque consultan Athena/Glue.

```bash
cd iac/api
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
export ATHENA_DATABASE=finsir ATHENA_WORKGROUP=finsir
export ATHENA_OUTPUT=s3://finsir-<account-id>/athena-results/
export IS_AUTH_DEV_MODE=true AUTH_DEV_SECRET=dev-secret AUTH_REQUIRED_SCOPE=gold:read
uvicorn app.main:app --host 0.0.0.0 --port 8080
```

## App de Streamlit (demo)

`.streamlit/app.py` es una interfaz mínima que consulta las recomendaciones del
modelo por ID de cliente (`GET /v1/recommendations/clients/{ncodpers}`) contra la
API desplegada. Necesita la API corriendo y un `.streamlit/secrets.toml` con
`API_BASE_URL` y `AUTH_DEV_SECRET`. Paso a paso en
[`.streamlit/README.md`](.streamlit/README.md).

## Tests

```bash
# API (sin llamadas reales a AWS)
cd iac/api
pip install -r requirements.txt -r requirements-dev.txt
pytest --cov=app --cov-report=term-missing

# Script de limpieza de Glue (PySpark local, sin AWS)
cd iac/data-platform
pip install pyspark pytest
python -m pytest glue
```

## Más documentación

Cada carpeta tiene su README con el detalle técnico y el paso a paso manual:

- API — [`iac/api/README.md`](iac/api/README.md)
- API en ECS — [`iac/api/terraform-ecs/README.md`](iac/api/terraform-ecs/README.md)
- Plataforma de datos — [`iac/data-platform/README.md`](iac/data-platform/README.md)
- App de Streamlit — [`.streamlit/README.md`](.streamlit/README.md)

## APM (Agent Package Manager)

Este repo usa **APM** para compartir los estándares de código del equipo y la
configuración de memoria Engram entre asistentes de IA (Kiro, Claude, Codex).
Manifiesto: [`apm.yml`](apm.yml); las dependencias caen en `apm_modules/`
(ignorado por git).

```bash
apm install            # en el proyecto local
apm install --global   # a nivel de usuario
```

El hook `engram-save-on-stop.json` no lo instala APM directamente: cópialo a
mano y reinstala.

```bash
mkdir -p .apm/hooks
cp engram-save-on-stop.json .apm/hooks/
apm install
```

## Equipo

Juan Felipe Restrepo Buitrago, Manuela Castaño Franco, Juan Esteban García Galvis,
Eduardo Andrés Piñeros Manjarres, Natalia Ceballos Posada.

## Licencia

MIT.
