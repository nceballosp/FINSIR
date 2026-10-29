output "service_url" {
  description = "Public HTTPS URL of the App Runner service"
  value       = "https://${aws_apprunner_service.api.service_url}"
}

output "ecr_repository_url" {
  description = "ECR repository URL to push the API image to"
  value       = aws_ecr_repository.api.repository_url
}

output "instance_role_arn" {
  description = "IAM role the running service assumes (least privilege)"
  value       = aws_iam_role.instance.arn
}
