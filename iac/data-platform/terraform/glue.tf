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

# Gold training table, built from silver. Run it after the cleaning job.
resource "aws_glue_job" "gold_train" {
  name              = local.gold_job_name
  role_arn          = local.glue_role_arn
  glue_version      = var.glue_version
  worker_type       = var.worker_type
  number_of_workers = var.number_of_workers
  timeout           = var.timeout_minutes
  max_retries       = 0

  command {
    name            = "glueetl"
    python_version  = "3"
    script_location = "s3://${local.bucket_id}/${aws_s3_object.gold_script.key}"
  }

  default_arguments = {
    "--BUCKET"              = local.bucket_id
    "--SILVER"              = var.silver_prefix
    "--GOLD"                = var.gold_prefix
    "--job-language"        = "python"
    "--enable-metrics"      = "true"
    "--enable-job-insights" = "false"
    "--enable-spark-ui"     = "false"
    "--job-bookmark-option" = "job-bookmark-disable"
    "--TempDir"             = "s3://${local.bucket_id}/tmp/"
  }
}

# Analytical gold tables (dashboard + popularity baseline), one job per table,
# all running glue/gold_analytics.py with a different --TABLE. Run after cleaning.
resource "aws_glue_job" "gold_analytics" {
  for_each = local.analytics_tables

  name              = each.value.job_name
  description       = each.value.description
  role_arn          = local.glue_role_arn
  glue_version      = var.glue_version
  worker_type       = var.worker_type
  number_of_workers = var.analytics_number_of_workers
  timeout           = var.timeout_minutes
  max_retries       = 0

  command {
    name            = "glueetl"
    python_version  = "3"
    script_location = "s3://${local.bucket_id}/${aws_s3_object.analytics_script.key}"
  }

  default_arguments = {
    "--BUCKET"              = local.bucket_id
    "--TABLE"               = each.key
    "--SILVER"              = var.silver_prefix
    "--GOLD"                = each.value.prefix
    "--job-language"        = "python"
    "--enable-metrics"      = "true"
    "--enable-job-insights" = "false"
    "--enable-spark-ui"     = "false"
    "--job-bookmark-option" = "job-bookmark-disable"
    "--TempDir"             = "s3://${local.bucket_id}/tmp/"
  }
}

# Gold segment conversion table, built from silver. Run it after cleaning.
resource "aws_glue_job" "gold_segment_conversion" {
  name              = local.conversion_job_name
  role_arn          = local.glue_role_arn
  glue_version      = var.glue_version
  worker_type       = var.worker_type
  number_of_workers = var.number_of_workers
  timeout           = var.timeout_minutes
  max_retries       = 0

  command {
    name            = "glueetl"
    python_version  = "3"
    script_location = "s3://${local.bucket_id}/${aws_s3_object.conversion_script.key}"
  }

  default_arguments = {
    "--BUCKET"              = local.bucket_id
    "--SILVER"              = var.silver_prefix
    "--GOLD"                = var.conversion_prefix
    "--job-language"        = "python"
    "--enable-metrics"      = "true"
    "--enable-job-insights" = "false"
    "--enable-spark-ui"     = "false"
    "--job-bookmark-option" = "job-bookmark-disable"
    "--TempDir"             = "s3://${local.bucket_id}/tmp/"
  }
}
