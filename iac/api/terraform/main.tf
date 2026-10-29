data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

locals {
  account_id    = data.aws_caller_identity.current.account_id
  region        = data.aws_region.current.name
  bucket_arn    = "arn:aws:s3:::${var.data_bucket_name}"
  athena_output = "s3://${var.data_bucket_name}/${var.athena_results_prefix}"
  image_uri     = "${aws_ecr_repository.api.repository_url}:${var.image_tag}"
}

# --- ECR --------------------------------------------------------------------

resource "aws_ecr_repository" "api" {
  name                 = var.ecr_repository_name
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }
}

# --- Instance role: what the running service may do (least privilege) -------

data "aws_iam_policy_document" "instance_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["tasks.apprunner.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "instance" {
  name               = "${var.project}-api-instance-role"
  assume_role_policy = data.aws_iam_policy_document.instance_assume.json
}

data "aws_iam_policy_document" "instance" {
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

  # Read catalog metadata for the silver database/tables.
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

  # Read the silver data.
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

resource "aws_iam_role_policy" "instance" {
  name   = "${var.project}-api-access"
  role   = aws_iam_role.instance.id
  policy = data.aws_iam_policy_document.instance.json
}

# --- Access role: lets App Runner pull the image from ECR -------------------

data "aws_iam_policy_document" "access_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["build.apprunner.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "access" {
  name               = "${var.project}-api-access-role"
  assume_role_policy = data.aws_iam_policy_document.access_assume.json
}

resource "aws_iam_role_policy_attachment" "access_ecr" {
  role       = aws_iam_role.access.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSAppRunnerServicePolicyForECRAccess"
}

# --- App Runner service -----------------------------------------------------

resource "aws_apprunner_service" "api" {
  service_name = var.service_name

  source_configuration {
    authentication_configuration {
      access_role_arn = aws_iam_role.access.arn
    }

    image_repository {
      image_identifier      = local.image_uri
      image_repository_type = "ECR"

      image_configuration {
        port = tostring(var.service_port)

        runtime_environment_variables = {
          ATHENA_DATABASE     = var.athena_database
          ATHENA_WORKGROUP    = var.athena_workgroup
          ATHENA_OUTPUT       = local.athena_output
          AWS_REGION          = var.region
          AUTH_ISSUER         = var.auth_issuer
          AUTH_AUDIENCE       = var.auth_audience
          AUTH_JWKS_URL       = var.auth_jwks_url
          AUTH_REQUIRED_SCOPE = var.auth_required_scope
          SERVICE_NAME        = var.service_name
          SERVICE_VERSION     = var.service_version
          SERVICE_ENVIRONMENT = var.service_environment
        }
      }
    }

    auto_deployments_enabled = false
  }

  instance_configuration {
    cpu               = var.cpu
    memory            = var.memory
    instance_role_arn = aws_iam_role.instance.arn
  }

  health_check_configuration {
    protocol = "HTTP"
    path     = "/health"
  }
}
