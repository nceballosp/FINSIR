# API FINSIR en ECS Fargate

Terraform que corre el contenedor de la API FINSIR (ya en ECR) sobre ECS Fargate
con IP pública y sin balanceador de carga.

> ¿Solo quieres desplegar o derribar rápido? Usa los scripts interactivos
> (`iac/api/deploy.sh` para desplegar, `iac/destroy.sh` para derribar). El paso a
> paso de abajo es para entender qué ocurre. Deploy y destroy simples:
> [README de la raíz](../../../README.md#deploy-rápido-con-los-scripts).

## Qué crea

- Cluster ECS `finsir-api-cluster`
- Task Fargate `finsir-api` — la imagen de ECR en el puerto 8080, logs a CloudWatch
- Servicio ECS `finsir-api` — 1 task, IP pública, sin ALB
- Rol de ejecución (deja a ECS descargar la imagen + escribir logs)
- Rol de task (deja a la app leer Athena/Glue/S3, mínimo privilegio)
- Security group — abierto en TCP 8080 a todo el mundo
- Log group `/ecs/finsir-api`

Usa el repo ECR `finsir-api` (este Terraform no lo gestiona). El script
`iac/api/deploy.sh` lo crea si no existe antes de subir la imagen; `iac/destroy.sh`
puede borrarlo al final del derribo.

## Deploy (manual)

```bash
cd iac/api/terraform-ecs
cp terraform.tfvars.example terraform.tfvars   # define auth_dev_secret (>= 16 chars)
AWS_PROFILE=terraform terraform init
AWS_PROFILE=terraform terraform apply
```

## Encontrar la IP pública

No hay URL fija (no hay ALB); la IP cambia en cada redeploy.

```bash
CLUSTER=$(terraform output -raw cluster_name)
SERVICE=$(terraform output -raw service_name)
TASK=$(aws ecs list-tasks --cluster "$CLUSTER" --service-name "$SERVICE" \
  --query 'taskArns[0]' --output text)
ENI=$(aws ecs describe-tasks --cluster "$CLUSTER" --tasks "$TASK" \
  --query 'tasks[0].attachments[0].details[?name==`networkInterfaceId`].value | [0]' --output text)
aws ec2 describe-network-interfaces --network-interface-ids "$ENI" \
  --query 'NetworkInterfaces[0].Association.PublicIp' --output text
```

## Llamar la API

`/health` es abierta; `/v1/*` necesita un token firmado con tu `auth_dev_secret`
y un scope `gold:read`.

```bash
IP=<ip-publica-de-arriba>
curl "http://$IP:8080/health"

# Generar un token dev (mismo secreto que auth_dev_secret)
python - <<'PY'
import jwt, time
secret = "<tu auth_dev_secret>"
now = int(time.time())
# iat/nbf retrasados ~120s evitan el 401 por desfase de reloj (ver nota abajo).
print(jwt.encode({"sub":"demo","scope":"gold:read",
                  "iat":now-120, "nbf":now-120, "exp":now+3600},
                 secret, algorithm="HS256"))
PY
TOKEN=<token>
# Tabla de entrenamiento
curl -H "Authorization: Bearer $TOKEN" "http://$IP:8080/v1/gold/train/clients/1"
# Tablas analíticas (una por recurso; ver la lista completa en ../README.md#endpoints)
curl -H "Authorization: Bearer $TOKEN" "http://$IP:8080/v1/gold/product-kpis/months/2016-04-28"
```

El tráfico es HTTP plano en el puerto 8080 (sin TLS). El token no necesita
`aud`/`iss` porque este deploy deja `AUTH_AUDIENCE`/`AUTH_ISSUER` sin definir; si
defines alguno, los tokens deben incluir el claim correspondiente o reciben 401.

> **Desfase de reloj.** Si el reloj de la task Fargate va por delante del tuyo,
> un token recién generado tiene `iat`/`nbf` en el futuro para el servidor y la
> validación lo rechaza con 401 hasta que el tiempo lo alcanza. Generar el token
> con `iat`/`nbf` retrasados unos segundos (como arriba) lo evita. No es un fallo
> de la API.

## Derribar

```bash
AWS_PROFILE=terraform terraform destroy
```

Detiene la task Fargate y elimina todo lo de arriba. El repo ECR sobrevive (no se
maneja aquí). Para el derribo completo de la plataforma (datos incluidos) usa el
script `iac/destroy.sh` o mira el README de la raíz, "Destroy".

## Advertencia

Esto es grado demo: el puerto 8080 está abierto al mundo y el tráfico es HTTP
plano. Para endurecerlo: pon un ALB enfrente para una URL HTTPS estable, cierra
el security group y mueve el secreto a Secrets Manager con auth RS256 de
producción.
