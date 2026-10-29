resource "aws_s3_bucket" "lake" {
  count = var.create_bucket ? 1 : 0

  bucket        = local.bucket_name
  force_destroy = var.force_destroy_bucket
}

resource "aws_s3_bucket_public_access_block" "lake" {
  count = var.create_bucket ? 1 : 0

  bucket                  = aws_s3_bucket.lake[0].id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "lake" {
  count = var.create_bucket ? 1 : 0

  bucket = aws_s3_bucket.lake[0].id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# El script de Glue. El CSV crudo no se sube con terraform: pesa 2.3 GB.
resource "aws_s3_object" "script" {
  bucket = local.bucket_id
  key    = local.script_key
  source = "${path.module}/../glue/limpieza_train.py"
  etag   = filemd5("${path.module}/../glue/limpieza_train.py")
}
