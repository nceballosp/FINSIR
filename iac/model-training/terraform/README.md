# Entrenamiento de FINSIR en EC2

Este Terraform despliega una EC2 para entrenamiento y una Step Function. Al ejecutar la Step Function de entrenamiento, esta:

1. Enciende la EC2.
2. Espera a que Systems Manager la reporte como `Online`.
3. Clona o actualiza la rama configurada del repositorio.
4. Instala los paquetes de sistema y dependencias de Python que falten.
5. Ejecuta `iac/model-training/train.py`, que lee `gold/train/` desde S3 y guarda el modelo bajo `models/production/`.
6. Apaga la EC2 tanto si el entrenamiento termina bien como si falla.

El script `iac/model-training/deploy.ps1` aplica Terraform y luego inicia una ejecución automáticamente. También puedes iniciar la máquina desde la consola AWS o con `start_training_command`. Hay un horario de EventBridge opcional, apagado por defecto.

## Requisitos

- Terraform >= 1.5 y AWS CLI configurado para la cuenta destino.
- Permisos para crear IAM, EC2, grupos de seguridad, perfiles de instancia, Step Functions y EventBridge si se activa el horario.
- El bucket existente en la misma región, con la tabla Gold ya generada en `gold/train/`.
- Una VPC predeterminada con subred pública o un `subnet_id` de subred pública con salida a Internet. La EC2 usa SSM y no abre puertos entrantes.

## Desplegar e iniciar el entrenamiento

Desde esta carpeta, copia el ejemplo solo si `terraform.tfvars` todavía no
existe y configura `create_instance = true` y el bucket correcto:

```powershell
Copy-Item terraform.tfvars.example terraform.tfvars
# Edita terraform.tfvars antes de seguir.
```

Luego vuelve a la raíz del repositorio y ejecuta:

```powershell
cd ..\..\..
.\iac\model-training\deploy.ps1
```

El script pregunta el perfil y región, ejecuta `terraform init`, `plan` y
`apply`, y después inicia `finsir-model-training` con entrada `{}`. Si vuelves a
ejecutarlo, inicia un nuevo entrenamiento aunque Terraform no tenga cambios.
`create_instance = true` crea la EC2. Su preparación inicial la apaga y la deja
lista para que el flujo la encienda. Esta máquina está separada de
`finsir-batch-diario`, que sigue ejecutando limpieza y generación Gold.

Si solo corres `terraform apply` a mano, Terraform crea la Step Function pero
no inicia el entrenamiento. Después de aplicar, inicia la máquina desde **AWS
Step Functions → State machines → `finsir-model-training` → Start execution**
con `{}` como entrada.

El artefacto se escribe en:

```text
s3://<bucket>/models/production/finsir.joblib
```

Si la ejecución falla, revisa los detalles de la ejecución en Step Functions y **Systems Manager → Run Command → Command history → Output**.

## Eliminar infraestructura

```powershell
terraform destroy
```

Esto elimina la instancia y recursos IAM/orquestación creados por este módulo, pero no borra el bucket ni sus datos.
