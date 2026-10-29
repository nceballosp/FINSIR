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
