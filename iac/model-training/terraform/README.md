# Entrenamiento de FINSIR en EC2

Este Terraform despliega una EC2 para entrenamiento y una **Step Function independiente** del batch de limpieza y tablas Gold de `iac/data-platform`. Al ejecutar la Step Function de entrenamiento, esta:

1. Enciende la EC2.
2. Espera a que Systems Manager la reporte como `Online`.
3. Clona o actualiza la rama configurada del repositorio.
4. Instala los paquetes de sistema y dependencias de Python que falten.
5. Ejecuta `iac/model-training/train.py`, que lee `gold/train/` desde S3 y guarda el modelo bajo `models/production/`.
6. Apaga la EC2 tanto si el entrenamiento termina bien como si falla.

La ejecución se inicia manualmente desde Step Functions o con el comando que Terraform muestra en `start_training_command`. Hay un horario de EventBridge opcional, apagado por defecto.

## Requisitos

- Terraform >= 1.5 y AWS CLI configurado para la cuenta destino.
- Permisos para crear IAM, EC2, grupos de seguridad, perfiles de instancia, Step Functions y EventBridge si se activa el horario.
- El bucket existente en la misma región, con la tabla Gold ya generada en `gold/train/`.
- Una VPC predeterminada con subred pública o un `subnet_id` de subred pública con salida a Internet. La EC2 usa SSM y no abre puertos entrantes.

## Crear infraestructura

Desde esta carpeta:

```powershell
Copy-Item terraform.tfvars.example terraform.tfvars
# Edita bucket_name si no usas finsir-<id de la cuenta AWS activa>.
terraform init
terraform plan -out tfplan
terraform apply tfplan
```

`create_instance = true` crea la EC2 de entrenamiento. Al terminar la preparación inicial, la instancia se apaga y queda lista para que la Step Function la inicie; así no queda encendida esperando. La máquina `finsir-model-training` queda separada de `finsir-batch-diario`, que pertenece al módulo `iac/data-platform/terraform` y sigue ejecutando limpieza y generación Gold.

## Ejecutar el entrenamiento

En la consola AWS, abre **Step Functions → State machines → `finsir-model-training` → Start execution** y usa `{}` como entrada. También puedes copiar el comando listo para usar:

```powershell
terraform output -raw start_training_command
```

Terraform aplica el comando como salida; ejecútalo en una terminal con AWS CLI configurado. La EC2 se detiene al terminar para evitar que quede facturando como instancia encendida. El volumen raíz se conserva para mantener el checkout y el entorno virtual entre ejecuciones.

El artefacto se escribe en:

```text
s3://<bucket>/models/production/finsir.joblib
```

Si la ejecución falla, revisa los detalles de la ejecución en Step Functions y **Systems Manager → Run Command → Command history → Output**. El comando exporta `HOME=/root` para que DuckDB pueda instalar sus extensiones.

## Entrenamiento periódico (opcional)

Para crear una regla independiente que invoque esta Step Function, configura en `terraform.tfvars`:

```hcl
training_schedule_enabled    = true
training_schedule_expression = "cron(0 8 1 * ? *)"
```

La expresión usa UTC. Activa el horario solo si el momento elegido es posterior a la actualización de Gold; de lo contrario, el modelo podría entrenarse con la versión anterior de los datos.

## Eliminar infraestructura

```powershell
terraform destroy
```

Esto elimina la instancia y recursos IAM/orquestación creados por este módulo, pero no borra el bucket ni sus datos.
