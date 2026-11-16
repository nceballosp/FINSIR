# Terraform para entrenamiento FINSIR en EC2

Este modulo crea un rol IAM, permisos acotados al prefijo `gold/train/` del bucket y al prefijo `models/`, una instancia EC2 Amazon Linux 2023 opcional y acceso administrativo mediante Systems Manager Session Manager. No abre SSH. El ID de cuenta se obtiene de las credenciales AWS activas; si `bucket_name` queda vacio, el bucket se calcula como `finsir-<id-de-cuenta>`. Puedes indicar otro bucket existente en `terraform.tfvars`.

## Requisitos

- Terraform 1.5 o posterior y AWS CLI configurado con permisos para crear IAM, EC2, Security Groups y perfiles de instancia.
- Una VPC predeterminada con una subred publica, o un `subnet_id` de una subred publica con salida a internet.
- El bucket ya existente en `us-east-1`.

## Despliegue

Desde esta carpeta:

```powershell
Copy-Item terraform.tfvars.example terraform.tfvars
terraform init
terraform plan -out tfplan
terraform apply tfplan
```

El primer despliegue deja `create_instance = false`: crea el rol, el perfil y los permisos IAM, pero no inicia una instancia con costo. Para crear la EC2, cambia esa variable a `true`, revisa el plan y aplica de nuevo. La instancia predeterminada `r7i.4xlarge` tiene memoria para el conjunto completo, pero su costo por hora es alto; puedes elegir otro tipo si ajustas los limites de memoria y almacenamiento temporal del entrenamiento.

## Conectarse y entrenar

Cuando la instancia exista, abre Systems Manager > Session Manager en la consola de AWS y conectate a `training_instance_id`. La instancia instala Python 3.12 y prepara `/opt/finsir-model-training`; copia o clona alli el repositorio, instala las dependencias y ejecuta. Obtén el bucket con `terraform output -raw bucket_name` desde esta carpeta y reemplaza el valor de `BUCKET`:

```bash
cd /opt/finsir-model-training
python3.12 -m pip install -r requirements.txt
BUCKET="<bucket mostrado por terraform output>"
python3.12 train.py --bucket "$BUCKET" --region us-east-1 \
  --output-dir ./artifacts --duckdb-temp-dir /mnt/finsir-duckdb-tmp \
  --artifact-s3-uri "s3://$BUCKET/models/production/finsir.joblib"
```

No configures claves AWS en la instancia ni uses `--aws-profile`: boto3 y DuckDB obtienen las credenciales temporales del perfil IAM adjunto. `terraform destroy` elimina la instancia y los recursos IAM creados por este modulo; no elimina el bucket ni sus datos.
