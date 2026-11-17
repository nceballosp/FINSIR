output "training_role_arn" {
  description = "ARN del rol IAM que da acceso SSM y S3 a la EC2."
  value       = aws_iam_role.training_ec2.arn
}

output "training_instance_id" {
  description = "ID de la instancia EC2, vacio si create_instance=false."
  value       = try(aws_instance.training[0].id, "")
}

output "training_instance_public_ip" {
  description = "IP publica para salida a internet; la instancia no acepta conexiones entrantes."
  value       = try(aws_instance.training[0].public_ip, "")
}

output "training_s3_read_prefix" {
  value = "s3://${local.bucket_name}/${trim(var.gold_prefix, "/")}/"
}

output "training_s3_model_prefix" {
  value = "s3://${local.bucket_name}/${trim(var.model_prefix, "/")}/"
}

output "bucket_name" {
  description = "Bucket que Terraform usa para leer Gold y guardar el modelo."
  value       = local.bucket_name
}

output "training_state_machine_arn" {
  description = "ARN de la Step Function que ejecuta el entrenamiento en la EC2."
  value       = try(aws_sfn_state_machine.training[0].arn, "")
}

output "start_training_command" {
  description = "Comando para iniciar manualmente el entrenamiento desde AWS CLI."
  value = var.create_instance ? join(" ", [
    "aws stepfunctions start-execution",
    "--state-machine-arn ${aws_sfn_state_machine.training[0].arn}",
    "--input '{}'",
    "--region ${var.region}",
  ]) : ""
}
