variable "region" {
  description = "AWS region where the API is deployed"
  type        = string
  default     = "us-east-1"
}

variable "project" {
  description = "Resource name prefix"
  type        = string
  default     = "finsir"
}

variable "tags" {
  description = "Additional tags applied to every resource"
  type        = map(string)
  default     = {}
}

variable "service_name" {
  description = "App Runner service name"
  type        = string
  default     = "finsir-service"
}

# --- Container image --------------------------------------------------------

variable "ecr_repository_name" {
  description = "Name of the ECR repository holding the API image"
  type        = string
  default     = "finsir-api"
}

variable "image_tag" {
  description = "Tag of the image App Runner pulls from ECR"
  type        = string
  default     = "latest"
}

# --- Data platform references (no account-specific hardcoding) --------------

variable "data_bucket_name" {
  description = "Name of the data-platform S3 bucket (data lake)"
  type        = string
}

variable "athena_database" {
  description = "Glue catalog database with the silver tables"
  type        = string
  default     = "finsir"
}

variable "athena_workgroup" {
  description = "Athena workgroup used to run queries"
  type        = string
  default     = "finsir"
}

variable "athena_results_prefix" {
  description = "S3 key prefix (with trailing slash) where Athena writes results"
  type        = string
  default     = "athena-results/"
}

# --- App Runner sizing ------------------------------------------------------

variable "service_port" {
  description = "Port the container listens on"
  type        = number
  default     = 8080
}

variable "cpu" {
  description = "App Runner vCPU units (e.g. 1024 = 1 vCPU)"
  type        = string
  default     = "1024"
}

variable "memory" {
  description = "App Runner memory in MB"
  type        = string
  default     = "2048"
}

# --- Auth configuration (secrets injected via env, never hardcoded) ---------

variable "auth_issuer" {
  description = "Expected JWT issuer (iss claim)"
  type        = string
  default     = ""
}

variable "auth_audience" {
  description = "Expected JWT audience (aud claim)"
  type        = string
  default     = ""
}

variable "auth_jwks_url" {
  description = "JWKS endpoint for RS256 verification in production"
  type        = string
  default     = ""
}

variable "auth_required_scope" {
  description = "Scope required to call the data endpoints"
  type        = string
  default     = ""
}

# --- Service metadata -------------------------------------------------------

variable "service_version" {
  description = "Service version reported in logs"
  type        = string
  default     = "0.1.0"
}

variable "service_environment" {
  description = "Deployment environment reported in logs (local|dev|uat|prod)"
  type        = string
  default     = "prod"
}
