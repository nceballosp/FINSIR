# API FINSIR (servicio gold)

Servicio FastAPI que sirve la tabla gold de entrenamiento de FINSIR. Consulta
Athena (`gold_train`) y lee la info de la tabla desde el catálogo de Glue. Corre
en AWS ECS Fargate en `http://<task-ip>:8080` (HTTP plano, sin balanceador de
carga). Un JWT bearer se valida dentro de FastAPI (no hay API Gateway). Las
columnas están documentadas en
[`../data-platform/README.md`](../data-platform/README.md#capa-gold-gold_train).

> ¿Solo quieres desplegar rápido? Hay un script interactivo
> (`deploy.sh` / `deploy.ps1`) que construye la imagen, la sube a ECR y aplica
> Terraform por ti. El detalle de abajo es para entender qué ocurre. Deploy y
> destroy simples: [README de la raíz](../../README.md#deploy-rápido-con-los-scripts).

## Cómo está organizado el código (hexagonal)

Las dependencias apuntan hacia adentro: `adapters -> use cases -> domain`.

```
app/
  domain/            Entidades + errores tipados. Sin imports de framework.
  use_cases/         Puertos (GoldTrainRepository, GoldAnalyticsRepository) + casos de uso.
  adapters/
    driving/http/    App FastAPI, routers (gold_train + 6 analíticas), auth, logging, errores.
    driven/athena/   Repositorios sobre Athena (boto3), runner compartido, validación.
  config.py          Settings desde variables de entorno.
  container.py       Conecta el adapter de Athena a los casos de uso.
  main.py            Punto de entrada (uvicorn app.main:app).
```

Todo el código boto3/Athena vive detrás de los puertos `GoldTrainRepository` y
`GoldAnalyticsRepository`, así que los tests usan repositorios falsos y no hacen
llamadas a AWS.

## Endpoints

| Método | Ruta                                 | Auth | Qué devuelve                                        |
| ------ | ------------------------------------ | ---- | --------------------------------------------------- |
| GET    | `/health`                            | no   | Health check (lo usa ECS)                           |
| GET    | `/v1/gold/train/clients/{ncodpers}`  | sí   | Filas `gold_train` de un cliente, ordenadas por mes |
| GET    | `/v1/gold/train/months/{fecha_dato}` | sí   | Filas `gold_train` de un mes (paginado)             |

Parámetros del listado por mes: `page` (>= 1), `size` (1..200), `sort` (una
columna de `gold_train`). Cada fila vuelve como `ncodpers`, `fecha_dato` y un
objeto `attributes` con las otras 167 columnas (valores como strings, nulls
conservados). Las columnas que empiezan con `label_next_` son las respuestas del
modelo, no features; las banderas `added_<product>` sí son features (el producto
se adquirió este mes).

### Tablas gold analíticas

Las 6 tablas analíticas (`gold_<key>`) están particionadas por `fecha_dato` y se
exponen con un endpoint de listado por mes cada una, con la misma forma que el de
`gold_train`:

| Método | Ruta                                               | Auth | Filtros de igualdad (query)                   |
| ------ | -------------------------------------------------- | ---- | --------------------------------------------- |
| GET    | `/v1/gold/product-kpis/months/{fecha_dato}`        | sí   | `product`                                     |
| GET    | `/v1/gold/customer-profiles/months/{fecha_dato}`   | sí   | `segmento`, `age_band`, `sexo`, `income_band` |
| GET    | `/v1/gold/product-penetration/months/{fecha_dato}` | sí   | `dimension`, `dimension_value`, `product`     |
| GET    | `/v1/gold/product-affinity/months/{fecha_dato}`    | sí   | `product_a`, `product_b`                      |
| GET    | `/v1/gold/product-transitions/months/{fecha_dato}` | sí   | `from_product`, `to_product`                  |
| GET    | `/v1/gold/baseline-popularity/months/{fecha_dato}` | sí   | (ninguno)                                     |

Cada endpoint acepta `page` (>= 1), `size` (1..200), `sort` (una columna de esa
tabla o `fecha_dato`) y sus filtros de igualdad opcionales. Cada fila vuelve como
`fecha_dato` y un objeto `attributes` con las columnas de la tabla (valores como
strings, nulls conservados). Los nombres físicos en Athena son `gold_<key>` (ej.
`gold_product_monthly_kpis`); las columnas están documentadas en
[`../data-platform/glue/gold_analytics_tables.json`](../data-platform/glue/gold_analytics_tables.json).

Las respuestas exitosas envuelven los datos en `data` (con `meta` de paginación);
los errores usan `{error.code, error.message, correlationId}` y nunca filtran
detalles internos.

```bash
TOKEN="<bearer-jwt>"
BASE="http://<task-ip>:8080"
curl -H "Authorization: Bearer $TOKEN" "$BASE/v1/gold/train/clients/1375586"
curl -H "Authorization: Bearer $TOKEN" "$BASE/v1/gold/train/months/2016-04-28?page=1&size=50"
curl -H "Authorization: Bearer $TOKEN" "$BASE/v1/gold/product-kpis/months/2016-04-28?sort=popularity_rank"
curl -H "Authorization: Bearer $TOKEN" "$BASE/v1/gold/product-affinity/months/2016-05-28?product_a=ind_cno_fin_ult1"
```

## Auth

Toda ruta `/v1` necesita un JWT bearer (`/health` es abierta). Nada está escrito
en el código: todo viene de variables de entorno.

- **Dev**: `IS_AUTH_DEV_MODE=true` + `AUTH_DEV_SECRET` → valida tokens HS256. Es
  lo que usa el deploy en ECS.
- **Prod**: RS256 con claves desde `AUTH_JWKS_URL`, validando `AUTH_AUDIENCE` y
  `AUTH_ISSUER`.

Token ausente/inválido → 401; scope equivocado → 403. El token nunca se loguea.

## Variables de entorno

| Variable                                                   | ¿Necesaria? | Para qué                                           |
| ---------------------------------------------------------- | ----------- | -------------------------------------------------- |
| `ATHENA_DATABASE`                                          | sí          | Base de datos de Glue (ej. `finsir`)               |
| `ATHENA_WORKGROUP`                                         | sí          | Workgroup de Athena                                |
| `ATHENA_OUTPUT`                                            | sí          | URI de S3 para resultados de Athena                |
| `ATHENA_TABLE`                                             | no          | Tabla gold (default `gold_train`)                  |
| `ATHENA_ANALYTICS_TABLE_PREFIX`                            | no          | Prefijo de las tablas analíticas (default `gold_`) |
| `AWS_REGION`                                               | no          | Región (default `us-east-1`)                       |
| `AUTH_ISSUER` / `AUTH_AUDIENCE` / `AUTH_JWKS_URL`          | prod        | Validación de tokens RS256                         |
| `AUTH_REQUIRED_SCOPE`                                      | no          | Scope requerido para rutas de datos                |
| `IS_AUTH_DEV_MODE`                                         | no          | `true` activa el modo dev HS256                    |
| `AUTH_DEV_SECRET`                                          | dev         | Secreto HS256 (modo dev)                           |
| `SERVICE_NAME` / `SERVICE_VERSION` / `SERVICE_ENVIRONMENT` | no          | Metadata de logs                                   |

El modo dev necesita `AUTH_DEV_SECRET`; prod necesita JWKS/audience/issuer. La
app falla de inmediato si falta un valor requerido.

## Correr local

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
export ATHENA_DATABASE=finsir ATHENA_WORKGROUP=finsir
export ATHENA_OUTPUT=s3://finsir-<account-id>/athena-results/
export IS_AUTH_DEV_MODE=true AUTH_DEV_SECRET=dev-secret AUTH_REQUIRED_SCOPE=gold:read
uvicorn app.main:app --host 0.0.0.0 --port 8080   # necesita credenciales de AWS para las rutas de datos
```

## Tests

```bash
pip install -r requirements.txt -r requirements-dev.txt
pytest --cov=app --cov-report=term-missing
```

Mínimos de cobertura: domain > 90%, use cases >= 85%, adapters >= 70%, global >= 80%.
Los tests usan un repositorio falso y boto3 falso: nada de AWS real.

## Construir y subir la imagen

La task de ECS descarga desde el repo ECR `finsir-api`, así que construye y sube
primero:

```bash
ECR_URL="663505294799.dkr.ecr.us-east-1.amazonaws.com/finsir-api"   # usa la URL de tu cuenta
aws --profile terraform ecr get-login-password --region us-east-1 \
  | docker login --username AWS --password-stdin "${ECR_URL%/*}"
docker build -t "$ECR_URL:latest" .    # córrelo desde iac/api
docker push "$ECR_URL:latest"
```

Si el repo no existe:
`aws --profile terraform ecr create-repository --repository-name finsir-api --region us-east-1`.
Mantén `ECR_URL` en la misma shell y pon `:latest` entre comillas. Tras un push
posterior, vuelve a correr `terraform apply` en `terraform-ecs/` para que el
servicio tome la nueva imagen.

## Deploy

La API la despliega el Terraform de `terraform-ecs/` (cluster ECS, task Fargate

- servicio en el puerto 8080, roles de task/ejecución, security group, log
  group). Reutiliza el repo ECR existente y lee el bucket/base de datos/workgroup
  de la plataforma de datos desde variables.

```bash
cd terraform-ecs
cp terraform.tfvars.example terraform.tfvars   # define auth_dev_secret (>= 16 chars)
AWS_PROFILE=terraform terraform init
AWS_PROFILE=terraform terraform apply
```

Para encontrar la IP pública, generar un token y derribar el servicio, ver
[`terraform-ecs/README.md`](terraform-ecs/README.md).

> El root viejo de Terraform para App Runner se eliminó (App Runner no está
> disponible en esta cuenta). Dejó dos roles IAM sin uso y gratuitos
> (`finsir-api-instance-role`, `finsir-api-access-role`); bórralos a mano si
> quieres.
