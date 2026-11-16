variable "region" {
  description = "AWS Region donde ya existe el bucket FINSIR."
  type        = string
  default     = "us-east-1"
}

variable "bucket_name" {
  description = "Nombre del bucket existente. Vacio deriva <project>-<id de la cuenta AWS autenticada>."
  type        = string
  default     = ""
}

variable "gold_prefix" {
  description = "Prefijo S3 de la tabla Gold usada para entrenar."
  type        = string
  default     = "gold/train/"
}

variable "model_prefix" {
  description = "Prefijo S3 donde el rol puede guardar artefactos del modelo."
  type        = string
  default     = "models/"
}

variable "create_instance" {
  description = "Activa la EC2. Dejelo false para crear y revisar primero IAM sin iniciar costos de computo."
  type        = bool
  default     = false
}

variable "instance_type" {
  description = "Tipo de instancia con memoria suficiente para entrenar el conjunto completo; ajustable segun presupuesto."
  type        = string
  default     = "r7i.4xlarge"
}

variable "root_volume_size_gib" {
  description = "Tamano del volumen raiz cifrado, en GiB."
  type        = number
  default     = 300
}

variable "subnet_id" {
  description = "Subred opcional. Vacio usa una subred publica de la VPC predeterminada."
  type        = string
  default     = ""
}

variable "training_repo_url" {
  description = "Repositorio Git que contiene iac/model-training/train.py."
  type        = string
  default     = "https://github.com/nceballosp/FINSIR.git"
}

variable "training_repo_branch" {
  description = "Rama del repositorio que contiene el codigo de entrenamiento."
  type        = string
  default     = "modelo"
}

variable "training_repo_path" {
  description = "Ruta del checkout del repositorio en la EC2."
  type        = string
  default     = "/opt/finsir-model-training/FINSIR"
}

variable "training_schedule_enabled" {
  description = "Activa un horario opcional para entrenar periodicamente. Apagado por defecto."
  type        = bool
  default     = false
}

variable "training_schedule_expression" {
  description = "Horario UTC de EventBridge para iniciar el entrenamiento, por ejemplo cron(0 8 1 * ? *)."
  type        = string
  default     = "cron(0 8 1 * ? *)"
}

variable "tags" {
  description = "Etiquetas adicionales para los recursos."
  type        = map(string)
  default     = {}
}
