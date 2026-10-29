resource "aws_glue_job" "limpieza" {
  name              = local.job_name
  role_arn          = local.glue_role_arn
  glue_version      = var.glue_version
  worker_type       = var.worker_type
  number_of_workers = var.number_of_workers
  timeout           = var.timeout_minutes
  max_retries       = 0

  lifecycle {
    precondition {
      condition     = local.bucket_id != ""
      error_message = "Con create_bucket = false hay que indicar bucket_name."
    }
  }

  command {
    name            = "glueetl"
    python_version  = "3"
    script_location = "s3://${local.bucket_id}/${aws_s3_object.script.key}"
  }

  default_arguments = {
    "--BUCKET"              = local.bucket_id
    "--RAW"                 = var.raw_prefix
    "--SILVER"              = var.silver_prefix
    "--RECHAZADOS"          = var.rechazados_prefix
    "--CALIDAD"             = var.calidad_prefix
    "--job-language"        = "python"
    "--enable-metrics"      = "true"
    "--enable-job-insights" = "false"
    "--enable-spark-ui"     = "false"
    "--job-bookmark-option" = "job-bookmark-disable"
    "--TempDir"             = "s3://${local.bucket_id}/tmp/"
  }
}
