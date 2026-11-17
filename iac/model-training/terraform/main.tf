data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}

data "aws_vpc" "default" {
  count   = var.create_instance && var.subnet_id == "" ? 1 : 0
  default = true
}

data "aws_subnets" "default" {
  count = var.create_instance && var.subnet_id == "" ? 1 : 0

  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default[0].id]
  }
}

data "aws_subnet" "selected" {
  count = var.create_instance ? 1 : 0
  id    = local.selected_subnet
}

data "aws_ssm_parameter" "al2023_ami" {
  count = var.create_instance ? 1 : 0
  name  = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64"
}

locals {
  bucket_name     = var.bucket_name != "" ? var.bucket_name : "finsir-${data.aws_caller_identity.current.account_id}"
  bucket_arn      = "arn:aws:s3:::${local.bucket_name}"
  gold_prefix     = trim(var.gold_prefix, "/")
  model_prefix    = trim(var.model_prefix, "/")
  selected_subnet = var.subnet_id != "" ? var.subnet_id : try(tolist(data.aws_subnets.default[0].ids)[0], null)
}

resource "aws_iam_role" "training_ec2" {
  name = "finsir-model-training-ec2"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "ssm_core" {
  role       = aws_iam_role.training_ec2.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_role_policy" "training_s3" {
  name = "finsir-model-training-s3"
  role = aws_iam_role.training_ec2.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "ListGoldTrainingPrefix"
        Effect   = "Allow"
        Action   = ["s3:ListBucket"]
        Resource = local.bucket_arn
        Condition = {
          StringLike = {
            "s3:prefix" = ["${local.gold_prefix}", "${local.gold_prefix}/*"]
          }
        }
      },
      {
        Sid      = "ReadGoldTrainingObjects"
        Effect   = "Allow"
        Action   = ["s3:GetObject"]
        Resource = "${local.bucket_arn}/${local.gold_prefix}/*"
      },
      {
        Sid    = "WriteModelArtifacts"
        Effect = "Allow"
        Action = [
          "s3:AbortMultipartUpload",
          "s3:ListMultipartUploadParts",
          "s3:PutObject"
        ]
        Resource = "${local.bucket_arn}/${local.model_prefix}/*"
      },
      {
        Sid      = "ListModelMultipartUploads"
        Effect   = "Allow"
        Action   = ["s3:ListBucketMultipartUploads"]
        Resource = local.bucket_arn
        Condition = {
          StringLike = {
            "s3:prefix" = ["${local.model_prefix}", "${local.model_prefix}/*"]
          }
        }
      },
      {
        Sid      = "ReadBucketRegion"
        Effect   = "Allow"
        Action   = ["s3:GetBucketLocation"]
        Resource = local.bucket_arn
      }
    ]
  })
}

resource "aws_iam_instance_profile" "training" {
  name = "finsir-model-training-ec2"
  role = aws_iam_role.training_ec2.name
}

resource "aws_security_group" "training" {
  count       = var.create_instance ? 1 : 0
  name        = "finsir-model-training-ec2"
  description = "Sin puertos entrantes; administracion mediante Systems Manager."
  vpc_id      = data.aws_subnet.selected[0].vpc_id

  egress {
    description = "HTTP para el repositorio predeterminado de extensiones DuckDB."
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    description = "HTTPS para SSM, S3, GitHub y descarga segura de paquetes."
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "finsir-model-training-ec2" }
}

resource "aws_instance" "training" {
  count                       = var.create_instance ? 1 : 0
  ami                         = data.aws_ssm_parameter.al2023_ami[0].value
  instance_type               = var.instance_type
  subnet_id                   = local.selected_subnet
  associate_public_ip_address = true
  vpc_security_group_ids      = [aws_security_group.training[0].id]
  iam_instance_profile        = aws_iam_instance_profile.training.name

  root_block_device {
    volume_type           = "gp3"
    volume_size           = var.root_volume_size_gib
    encrypted             = true
    delete_on_termination = true
  }

  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
  }

  user_data = <<-USERDATA
    #!/bin/bash
    set -euo pipefail
    dnf install -y python3.12 python3.12-pip git libgomp
    python3.12 -m pip install --upgrade pip
    mkdir -p /opt/finsir-model-training /mnt/finsir-duckdb-tmp
    chmod 0777 /opt/finsir-model-training
    chmod 1777 /mnt/finsir-duckdb-tmp
    shutdown -h now
  USERDATA

  tags = { Name = "finsir-model-training" }
}
