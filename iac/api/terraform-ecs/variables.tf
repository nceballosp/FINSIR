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
  description = "Service name reported in logs (SERVICE_NAME env value)"
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
  description = "Tag of the image Fargate pulls from ECR"
  type        = string
  default     = "latest"
}

# --- Data platform references -----------------------------------------------

variable "data_bucket_name" {
  description = "Name of the data-platform S3 bucket (data lake). Empty = derive it as <project>-<account-id>, matching the data platform's default."
  type        = string
  default     = ""
}

variable "athena_database" {
  description = "Glue catalog database with the gold tables"
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

variable "athena_table" {
  description = "Gold table the API reads (ATHENA_TABLE env value)"
  type        = string
  default     = "gold_train"
}

# --- Fargate sizing ---------------------------------------------------------

variable "service_port" {
  description = "Port the container listens on"
  type        = number
  default     = 8080
}

variable "cpu" {
  description = "Fargate vCPU units (e.g. 1024 = 1 vCPU)"
  type        = string
  default     = "1024"

  # shortcut: per-variable validation only, cross-combo caught at apply; tighten to a combined check if the root is bumped to Terraform >= 1.9
  validation {
    condition     = contains(["256", "512", "1024", "2048", "4096"], var.cpu)
    error_message = "cpu must be a valid Fargate vCPU unit: 256, 512, 1024, 2048, or 4096."
  }
}

variable "memory" {
  description = "Fargate memory in MB"
  type        = string
  default     = "2048"

  validation {
    condition     = contains(["512", "1024", "2048", "3072", "4096", "5120", "6144", "7168", "8192"], var.memory)
    error_message = "memory must be a valid Fargate memory value: 512, 1024, 2048, 3072, 4096, 5120, 6144, 7168, or 8192."
  }
}

# --- Auth configuration (dev-mode HS256; secret injected via env) -----------

variable "auth_dev_secret" {
  description = "HS256 signing secret for dev-mode auth (never committed)"
  type        = string
  sensitive   = true

  validation {
    condition     = length(var.auth_dev_secret) >= 16
    error_message = "auth_dev_secret must be at least 16 characters."
  }
}

variable "auth_required_scope" {
  description = "Scope required to call the data endpoints"
  type        = string
  default     = "gold:read"
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
  default     = "dev"
}

variable "log_retention_days" {
  description = "CloudWatch log group retention in days"
  type        = number
  default     = 14
}
