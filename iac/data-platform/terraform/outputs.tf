output "bucket" {
  description = "Bucket de los datos"
  value       = local.bucket_id
}

output "job_name" {
  description = "Trabajo de Glue de la limpieza"
  value       = aws_glue_job.limpieza.name
}

output "glue_role_arn" {
  description = "Rol que usa el trabajo de Glue"
  value       = local.glue_role_arn
}

output "subir_el_csv" {
  description = "Comando para subir el CSV crudo (2.3 GB)"
  value       = "aws s3 cp train_ver2.csv s3://${local.bucket_id}/${var.raw_prefix}train_ver2.csv"
}

output "ejecutar_la_limpieza" {
  description = "Comando para iniciar la limpieza"
  value       = "aws glue start-job-run --job-name ${aws_glue_job.limpieza.name} --region ${var.region}"
}

output "gold_job_name" {
  description = "Glue job that builds gold_train"
  value       = aws_glue_job.gold_train.name
}

output "run_gold_train" {
  description = "Command to build gold_train (after the cleaning job succeeds)"
  value       = "aws glue start-job-run --job-name ${aws_glue_job.gold_train.name} --region ${var.region}"
}

output "gold_train_path" {
  description = "Where gold_train is written"
  value       = "s3://${local.bucket_id}/${var.gold_prefix}"
}

output "conversion_job_name" {
  description = "Glue job that builds gold_segment_conversion"
  value       = aws_glue_job.gold_segment_conversion.name
}

output "run_gold_segment_conversion" {
  description = "Command to build gold_segment_conversion (after the cleaning job succeeds)"
  value       = "aws glue start-job-run --job-name ${aws_glue_job.gold_segment_conversion.name} --region ${var.region}"
}

output "gold_segment_conversion_path" {
  description = "Where gold_segment_conversion is written"
  value       = "s3://${local.bucket_id}/${var.conversion_prefix}"
}

output "gold_analytics_tables" {
  description = "Tablas gold analiticas en Athena (vacio si create_athena es false)"
  value       = var.create_athena ? sort([for t in values(local.analytics_tables) : t.table_name]) : []
}

output "gold_analytics_jobs" {
  description = "Job de Glue de cada tabla gold analitica (tabla -> job)"
  value       = { for k, t in local.analytics_tables : t.table_name => aws_glue_job.gold_analytics[k].name }
}

output "gold_analytics_paths" {
  description = "Donde se escribe cada tabla gold analitica (tabla -> ruta S3)"
  value       = { for k, t in local.analytics_tables : t.table_name => "s3://${local.bucket_id}/${t.prefix}" }
}

output "gold_jobs_input" {
  description = "Input JSON de la Step Functions con todos los jobs gold (lo usa deploy.ps1)"
  value       = jsonencode({ gold_jobs = local.gold_job_names })
}

output "ruta_silver" {
  description = "Donde queda la capa silver"
  value       = "s3://${local.bucket_id}/${var.silver_prefix}"
}

output "ruta_rechazados" {
  description = "Donde quedan los registros apartados"
  value       = "s3://${local.bucket_id}/${var.rechazados_prefix}"
}

output "ruta_calidad" {
  description = "Donde queda el reporte de calidad"
  value       = "s3://${local.bucket_id}/${var.calidad_prefix}"
}

output "athena_database" {
  description = "Base de datos de Athena (vacio si create_athena es false)"
  value       = var.create_athena ? aws_glue_catalog_database.this[0].name : ""
}

output "athena_workgroup" {
  description = "Grupo de trabajo de Athena (vacio si create_athena es false)"
  value       = var.create_athena ? aws_athena_workgroup.this[0].name : ""
}

output "state_machine_arn" {
  description = "Step Functions que orquesta el batch (vacio si create_orchestration es false)"
  value       = var.create_orchestration ? aws_sfn_state_machine.batch[0].arn : ""
}

output "run_batch" {
  description = "Comando para correr la orquestacion a mano (limpieza -> jobs gold en paralelo)"
  value = var.create_orchestration ? join(" ", [
    "aws stepfunctions start-execution",
    "--state-machine-arn ${aws_sfn_state_machine.batch[0].arn}",
    "--input '${jsonencode({ gold_jobs = local.gold_job_names })}'",
    "--region ${var.region}",
  ]) : ""
}
