variable "region" {
  description = "Region de AWS donde se crea todo"
  type        = string
  default     = "us-east-1"
}

variable "project" {
  description = "Prefijo de los nombres de los recursos"
  type        = string
  default     = "finsir"
}

variable "tags" {
  description = "Etiquetas adicionales para todos los recursos"
  type        = map(string)
  default     = {}
}

# --- S3 ---------------------------------------------------------------------

variable "create_bucket" {
  description = "true crea el bucket. false usa uno que ya existe (bucket_name es obligatorio)"
  type        = bool
  default     = true
}

variable "bucket_name" {
  description = "Nombre del bucket. Si es vacio y create_bucket es true, se usa <project>-<id de la cuenta>"
  type        = string
  default     = ""
}

variable "force_destroy_bucket" {
  description = "Permite que terraform destroy borre el bucket aunque tenga objetos. Dejalo en false con datos reales"
  type        = bool
  default     = false
}

variable "raw_prefix" {
  description = "Carpeta del CSV crudo, con barra final"
  type        = string
  default     = "raw/train/"
}

variable "silver_prefix" {
  description = "Carpeta de salida de silver (Parquet particionado por fecha_dato), con barra final"
  type        = string
  default     = "silver/train/"
}

variable "rechazados_prefix" {
  description = "Carpeta de los registros apartados, con barra final"
  type        = string
  default     = "silver_rechazados/train/"
}

variable "calidad_prefix" {
  description = "Carpeta del reporte de calidad, con barra final"
  type        = string
  default     = "calidad/train/"
}

variable "scripts_prefix" {
  description = "Carpeta donde se sube el script de Glue, con barra final"
  type        = string
  default     = "scripts/"
}

# --- Glue -------------------------------------------------------------------

variable "job_name" {
  description = "Nombre del trabajo de Glue. Si es vacio, <project>-limpieza-train"
  type        = string
  default     = ""
}

variable "existing_glue_role_arn" {
  description = "ARN de un rol de Glue que ya existe. Si es vacio, se crea uno con permisos solo sobre las carpetas de este trabajo"
  type        = string
  default     = ""
}

variable "glue_version" {
  description = "Version de Glue. El script se probo con Spark 3.5 (Glue 5.0) y con Spark 4.1"
  type        = string
  default     = "5.0"
}

variable "worker_type" {
  description = "Tipo de worker. G.1X alcanza para los 2.3 GB del archivo"
  type        = string
  default     = "G.1X"
}

variable "number_of_workers" {
  description = "Workers del trabajo (minimo 2). La limpieza reparte los datos por cliente: con mas workers termina antes"
  type        = number
  default     = 10
}

variable "timeout_minutes" {
  description = "Tiempo maximo de una ejecucion"
  type        = number
  default     = 120
}

# --- Athena -----------------------------------------------------------------

variable "create_athena" {
  description = "Crea la base de datos del catalogo, el grupo de trabajo y las tablas de Athena"
  type        = bool
  default     = true
}

variable "database_name" {
  description = "Base de datos del catalogo de Glue. Si es vacio, el nombre del proyecto con guiones bajos"
  type        = string
  default     = ""
}

variable "partition_projection" {
  description = "true: la tabla silver encuentra sola las carpetas fecha_dato=YYYY-MM-DD, sin MSCK REPAIR TABLE. Solo sirve si todos los cortes caen el mismo dia del mes"
  type        = bool
  default     = true
}

variable "primer_corte" {
  description = "Primer fecha_dato de los datos, para la partition projection"
  type        = string
  default     = "2015-01-28"
}
