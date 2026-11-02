data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

locals {
  account_id    = data.aws_caller_identity.current.account_id
  region        = data.aws_region.current.name
  bucket_arn    = "arn:aws:s3:::${var.data_bucket_name}"
  athena_output = "s3://${var.data_bucket_name}/${var.athena_results_prefix}"
  image_uri     = "${local.account_id}.dkr.ecr.${local.region}.amazonaws.com/${var.ecr_repository_name}:${var.image_tag}"
  name_prefix   = "${var.project}-api"
}

# --- CloudWatch logs --------------------------------------------------------

resource "aws_cloudwatch_log_group" "api" {
  name              = "/ecs/${local.name_prefix}"
  retention_in_days = var.log_retention_days
}

# --- IAM: shared trust for ECS tasks ----------------------------------------

data "aws_iam_policy_document" "task_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

# --- IAM: execution role (ECR pull + log write) -----------------------------

resource "aws_iam_role" "execution" {
  name               = "${local.name_prefix}-exec-role"
  assume_role_policy = data.aws_iam_policy_document.task_assume.json
}

resource "aws_iam_role_policy_attachment" "execution" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# --- IAM: task role (app permissions, least privilege) ----------------------

resource "aws_iam_role" "task" {
  name               = "${local.name_prefix}-task-role"
  assume_role_policy = data.aws_iam_policy_document.task_assume.json
}

data "aws_iam_policy_document" "task" {
  # Run and read Athena queries.
  statement {
    sid = "AthenaQuery"
    actions = [
      "athena:StartQueryExecution",
      "athena:GetQueryExecution",
      "athena:GetQueryResults",
    ]
    resources = [
      "arn:aws:athena:${local.region}:${local.account_id}:workgroup/${var.athena_workgroup}",
    ]
  }

  # Read catalog metadata for the gold database/tables.
  statement {
    sid = "GlueCatalog"
    actions = [
      "glue:GetTable",
      "glue:GetTables",
      "glue:GetDatabase",
      "glue:GetDatabases",
      "glue:GetPartitions",
    ]
    resources = [
      "arn:aws:glue:${local.region}:${local.account_id}:catalog",
      "arn:aws:glue:${local.region}:${local.account_id}:database/${var.athena_database}",
      "arn:aws:glue:${local.region}:${local.account_id}:table/${var.athena_database}/*",
    ]
  }

  # List the data bucket (needed by Athena).
  statement {
    sid       = "BucketList"
    actions   = ["s3:ListBucket", "s3:GetBucketLocation"]
    resources = [local.bucket_arn]
  }

  # Read the gold data.
  statement {
    sid       = "ReadData"
    actions   = ["s3:GetObject"]
    resources = ["${local.bucket_arn}/*"]
  }

  # Read/write the Athena results prefix only.
  statement {
    sid       = "AthenaResults"
    actions   = ["s3:GetObject", "s3:PutObject"]
    resources = ["${local.bucket_arn}/${var.athena_results_prefix}*"]
  }
}

resource "aws_iam_role_policy" "task" {
  name   = "${local.name_prefix}-access"
  role   = aws_iam_role.task.id
  policy = data.aws_iam_policy_document.task.json
}

# --- Security group ---------------------------------------------------------

resource "aws_security_group" "service" {
  name        = "${local.name_prefix}-sg"
  description = "FINSIR API Fargate task: public 8080 (demo-grade), all egress"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description = "Public API access (demo-grade exposure)"
    from_port   = var.service_port
    to_port     = var.service_port
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# --- ECS cluster ------------------------------------------------------------

resource "aws_ecs_cluster" "api" {
  name = "${local.name_prefix}-cluster"
}

# --- ECS task definition ----------------------------------------------------

resource "aws_ecs_task_definition" "api" {
  family                   = local.name_prefix
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.cpu
  memory                   = var.memory
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  container_definitions = jsonencode([
    {
      name      = "finsir-api"
      image     = local.image_uri
      essential = true
      portMappings = [{
        containerPort = var.service_port
        protocol      = "tcp"
      }]
      environment = [
        { name = "ATHENA_DATABASE", value = var.athena_database },
        { name = "ATHENA_WORKGROUP", value = var.athena_workgroup },
        { name = "ATHENA_OUTPUT", value = local.athena_output },
        { name = "ATHENA_TABLE", value = var.athena_table },
        { name = "AWS_REGION", value = local.region },
        { name = "IS_AUTH_DEV_MODE", value = "true" },
        { name = "AUTH_DEV_SECRET", value = var.auth_dev_secret },
        { name = "AUTH_REQUIRED_SCOPE", value = var.auth_required_scope },
        { name = "SERVICE_NAME", value = var.service_name },
        { name = "SERVICE_VERSION", value = var.service_version },
        { name = "SERVICE_ENVIRONMENT", value = var.service_environment },
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.api.name
          "awslogs-region"        = local.region
          "awslogs-stream-prefix" = "finsir-api"
        }
      }
    }
  ])
}

# --- ECS service ------------------------------------------------------------

resource "aws_ecs_service" "api" {
  name            = local.name_prefix
  cluster         = aws_ecs_cluster.api.id
  task_definition = aws_ecs_task_definition.api.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = data.aws_subnets.default.ids
    security_groups  = [aws_security_group.service.id]
    assign_public_ip = true
  }

  # Ensure the execution role's ECR-pull and log-write permissions exist
  # before the first task starts.
  depends_on = [aws_iam_role_policy_attachment.execution]
}
