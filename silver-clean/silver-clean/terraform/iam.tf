data "aws_iam_policy_document" "glue_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["glue.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "glue" {
  count = var.existing_glue_role_arn == "" ? 1 : 0

  name               = "${var.project}-glue-role"
  assume_role_policy = data.aws_iam_policy_document.glue_assume.json
}

resource "aws_iam_role_policy_attachment" "glue_service" {
  count = var.existing_glue_role_arn == "" ? 1 : 0

  role       = aws_iam_role.glue[0].name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSGlueServiceRole"
}

# Solo lo que el trabajo necesita: leer el crudo y el script, y escribir sus tres salidas
data "aws_iam_policy_document" "glue_bucket" {
  statement {
    actions   = ["s3:ListBucket", "s3:GetBucketLocation"]
    resources = [local.bucket_arn]
  }

  statement {
    actions = ["s3:GetObject"]
    resources = [
      "${local.bucket_arn}/${var.raw_prefix}*",
      "${local.bucket_arn}/${var.scripts_prefix}*",
    ]
  }

  statement {
    actions = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
    resources = [
      "${local.bucket_arn}/${var.silver_prefix}*",
      "${local.bucket_arn}/${var.rechazados_prefix}*",
      "${local.bucket_arn}/${var.calidad_prefix}*",
      "${local.bucket_arn}/tmp/*",
    ]
  }
}

resource "aws_iam_role_policy" "glue_bucket" {
  count = var.existing_glue_role_arn == "" ? 1 : 0

  name   = "${var.project}-acceso-al-bucket"
  role   = aws_iam_role.glue[0].id
  policy = data.aws_iam_policy_document.glue_bucket.json
}
