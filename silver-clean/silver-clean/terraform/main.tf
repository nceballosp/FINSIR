data "aws_caller_identity" "current" {}

locals {
  account_id = data.aws_caller_identity.current.account_id

  bucket_name = var.bucket_name != "" ? var.bucket_name : "${var.project}-${local.account_id}"
  bucket_id   = var.create_bucket ? aws_s3_bucket.lake[0].id : var.bucket_name
  bucket_arn  = "arn:aws:s3:::${local.bucket_id}"

  job_name      = var.job_name != "" ? var.job_name : "${var.project}-limpieza-train"
  database_name = var.database_name != "" ? var.database_name : replace(var.project, "-", "_")
  glue_role_arn = var.existing_glue_role_arn != "" ? var.existing_glue_role_arn : aws_iam_role.glue[0].arn

  script_key = "${var.scripts_prefix}limpieza_train.py"

  # Las columnas del CSV crudo, todas en texto (capa bronze)
  columnas_crudo = [
    "fecha_dato",
    "ncodpers",
    "ind_empleado",
    "pais_residencia",
    "sexo",
    "age",
    "fecha_alta",
    "ind_nuevo",
    "antiguedad",
    "indrel",
    "ult_fec_cli_1t",
    "indrel_1mes",
    "tiprel_1mes",
    "indresi",
    "indext",
    "conyuemp",
    "canal_entrada",
    "indfall",
    "tipodom",
    "cod_prov",
    "nomprov",
    "ind_actividad_cliente",
    "renta",
    "segmento",
    "ind_ahor_fin_ult1",
    "ind_aval_fin_ult1",
    "ind_cco_fin_ult1",
    "ind_cder_fin_ult1",
    "ind_cno_fin_ult1",
    "ind_ctju_fin_ult1",
    "ind_ctma_fin_ult1",
    "ind_ctop_fin_ult1",
    "ind_ctpp_fin_ult1",
    "ind_deco_fin_ult1",
    "ind_deme_fin_ult1",
    "ind_dela_fin_ult1",
    "ind_ecue_fin_ult1",
    "ind_fond_fin_ult1",
    "ind_hip_fin_ult1",
    "ind_plan_fin_ult1",
    "ind_pres_fin_ult1",
    "ind_reca_fin_ult1",
    "ind_tjcr_fin_ult1",
    "ind_valo_fin_ult1",
    "ind_viv_fin_ult1",
    "ind_nomina_ult1",
    "ind_nom_pens_ult1",
    "ind_recibo_ult1",
  ]

  # Las columnas de silver, sin la de particion (fecha_dato)
  columnas_silver = [
    { name = "ncodpers", type = "bigint" },
    { name = "ind_empleado", type = "string" },
    { name = "pais_residencia", type = "string" },
    { name = "sexo", type = "string" },
    { name = "age", type = "int" },
    { name = "fecha_alta", type = "date" },
    { name = "ind_nuevo", type = "int" },
    { name = "antiguedad", type = "int" },
    { name = "indrel", type = "int" },
    { name = "ult_fec_cli_1t", type = "date" },
    { name = "indrel_1mes", type = "string" },
    { name = "tiprel_1mes", type = "string" },
    { name = "indresi", type = "string" },
    { name = "indext", type = "string" },
    { name = "conyuemp", type = "string" },
    { name = "canal_entrada", type = "string" },
    { name = "indfall", type = "string" },
    { name = "tipodom", type = "int" },
    { name = "cod_prov", type = "int" },
    { name = "nomprov", type = "string" },
    { name = "ind_actividad_cliente", type = "int" },
    { name = "renta", type = "double" },
    { name = "segmento", type = "string" },
    { name = "ind_ahor_fin_ult1", type = "int" },
    { name = "ind_aval_fin_ult1", type = "int" },
    { name = "ind_cco_fin_ult1", type = "int" },
    { name = "ind_cder_fin_ult1", type = "int" },
    { name = "ind_cno_fin_ult1", type = "int" },
    { name = "ind_ctju_fin_ult1", type = "int" },
    { name = "ind_ctma_fin_ult1", type = "int" },
    { name = "ind_ctop_fin_ult1", type = "int" },
    { name = "ind_ctpp_fin_ult1", type = "int" },
    { name = "ind_deco_fin_ult1", type = "int" },
    { name = "ind_deme_fin_ult1", type = "int" },
    { name = "ind_dela_fin_ult1", type = "int" },
    { name = "ind_ecue_fin_ult1", type = "int" },
    { name = "ind_fond_fin_ult1", type = "int" },
    { name = "ind_hip_fin_ult1", type = "int" },
    { name = "ind_plan_fin_ult1", type = "int" },
    { name = "ind_pres_fin_ult1", type = "int" },
    { name = "ind_reca_fin_ult1", type = "int" },
    { name = "ind_tjcr_fin_ult1", type = "int" },
    { name = "ind_valo_fin_ult1", type = "int" },
    { name = "ind_viv_fin_ult1", type = "int" },
    { name = "ind_nomina_ult1", type = "int" },
    { name = "ind_nom_pens_ult1", type = "int" },
    { name = "ind_recibo_ult1", type = "int" },
    { name = "campos_rescatados", type = "string" },
    { name = "campos_invalidados", type = "string" },
  ]

  # Los rechazados llevan fecha_dato como una columna mas, y el motivo
  columnas_rechazados = concat(
    [{ name = "fecha_dato", type = "date" }],
    local.columnas_silver,
    [{ name = "motivo", type = "string" }],
  )

  columnas_calidad = [
    { name = "metrica", type = "string" },
    { name = "detalle", type = "string" },
    { name = "filas", type = "bigint" },
  ]
}
