output "cluster_name" {
  description = "ECS cluster name"
  value       = aws_ecs_cluster.api.name
}

output "service_name" {
  description = "ECS service name"
  value       = aws_ecs_service.api.name
}

output "task_definition_arn" {
  description = "ECS task definition ARN"
  value       = aws_ecs_task_definition.api.arn
}

output "task_role_arn" {
  description = "Task role ARN (app permissions)"
  value       = aws_iam_role.task.arn
}

output "execution_role_arn" {
  description = "Execution role ARN (ECR pull + logs)"
  value       = aws_iam_role.execution.arn
}

output "security_group_id" {
  description = "Security group ID for the Fargate task"
  value       = aws_security_group.service.id
}

output "log_group_name" {
  description = "CloudWatch log group for container logs"
  value       = aws_cloudwatch_log_group.api.name
}

output "image_uri" {
  description = "ECR image URI deployed to the task"
  value       = local.image_uri
}

output "public_ip_hint" {
  description = "How to find the task's public IP"
  value       = "No stable endpoint (no ALB). See README section 'Find the public IP' to resolve the current task IP; it changes on every redeploy."
}
