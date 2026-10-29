resource "aws_glue_catalog_database" "this" {
  count = var.create_athena ? 1 : 0

  name = local.database_name
}

resource "aws_athena_workgroup" "this" {
  count = var.create_athena ? 1 : 0

  name          = var.project
  force_destroy = true

  configuration {
    enforce_workgroup_configuration = true

    result_configuration {
      output_location = "s3://${local.bucket_id}/athena-results/"
    }
  }
}

# Capa bronze: el CSV tal como llego, todo en texto
resource "aws_glue_catalog_table" "bronze_train" {
  count = var.create_athena ? 1 : 0

  name          = "bronze_train"
  database_name = aws_glue_catalog_database.this[0].name
  table_type    = "EXTERNAL_TABLE"

  parameters = {
    EXTERNAL                 = "TRUE"
    "skip.header.line.count" = "1"
  }

  storage_descriptor {
    location      = "s3://${local.bucket_id}/${var.raw_prefix}"
    input_format  = "org.apache.hadoop.mapred.TextInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat"

    ser_de_info {
      serialization_library = "org.apache.hadoop.hive.serde2.OpenCSVSerde"
      parameters = {
        separatorChar = ","
        quoteChar     = "\""
      }
    }

    dynamic "columns" {
      for_each = local.columnas_crudo
      content {
        name = columns.value
        type = "string"
      }
    }
  }
}

# Capa silver: Parquet particionado por fecha_dato
resource "aws_glue_catalog_table" "silver_train" {
  count = var.create_athena ? 1 : 0

  name          = "silver_train"
  database_name = aws_glue_catalog_database.this[0].name
  table_type    = "EXTERNAL_TABLE"

  parameters = merge(
    {
      EXTERNAL              = "TRUE"
      "parquet.compression" = "SNAPPY"
    },
    var.partition_projection ? {
      "projection.enabled"                  = "true"
      "projection.fecha_dato.type"          = "date"
      "projection.fecha_dato.format"        = "yyyy-MM-dd"
      "projection.fecha_dato.range"         = "${var.primer_corte},NOW"
      "projection.fecha_dato.interval"      = "1"
      "projection.fecha_dato.interval.unit" = "MONTHS"
      "storage.location.template"           = "s3://${local.bucket_id}/${var.silver_prefix}fecha_dato=$${fecha_dato}/"
    } : {}
  )

  partition_keys {
    name = "fecha_dato"
    type = "string"
  }

  storage_descriptor {
    location      = "s3://${local.bucket_id}/${var.silver_prefix}"
    input_format  = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat"

    ser_de_info {
      serialization_library = "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe"
    }

    dynamic "columns" {
      for_each = local.columnas_silver
      content {
        name = columns.value.name
        type = columns.value.type
      }
    }
  }
}

# Los registros apartados, con el motivo
resource "aws_glue_catalog_table" "rechazados_train" {
  count = var.create_athena ? 1 : 0

  name          = "rechazados_train"
  database_name = aws_glue_catalog_database.this[0].name
  table_type    = "EXTERNAL_TABLE"

  parameters = {
    EXTERNAL              = "TRUE"
    "parquet.compression" = "SNAPPY"
  }

  storage_descriptor {
    location      = "s3://${local.bucket_id}/${var.rechazados_prefix}"
    input_format  = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat"

    ser_de_info {
      serialization_library = "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe"
    }

    dynamic "columns" {
      for_each = local.columnas_rechazados
      content {
        name = columns.value.name
        type = columns.value.type
      }
    }
  }
}

# El reporte de calidad de la ultima ejecucion
resource "aws_glue_catalog_table" "calidad_train" {
  count = var.create_athena ? 1 : 0

  name          = "calidad_train"
  database_name = aws_glue_catalog_database.this[0].name
  table_type    = "EXTERNAL_TABLE"

  parameters = {
    EXTERNAL              = "TRUE"
    "parquet.compression" = "SNAPPY"
  }

  storage_descriptor {
    location      = "s3://${local.bucket_id}/${var.calidad_prefix}"
    input_format  = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat"

    ser_de_info {
      serialization_library = "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe"
    }

    dynamic "columns" {
      for_each = local.columnas_calidad
      content {
        name = columns.value.name
        type = columns.value.type
      }
    }
  }
}
