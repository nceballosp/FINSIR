"""Limpieza del archivo crudo train_ver2.csv: de la capa bronze (CSV) a la capa
silver (Parquet).

La limpieza no inventa ni rellena datos. Hace cuatro cosas:

  1. Arregla el formato: quita espacios, convierte '' y 'NA' en null, asigna
     tipos y deja el mismo codigo escrito de una sola forma (1.0 -> 1).
  2. Invalida los valores imposibles, que quedan en null y marcados: una edad
     fuera de 0 a 122 anos y una antiguedad negativa (el archivo usa -999999).
  3. Rescata un dato vacio solo con un dato real del mismo cliente en otro mes,
     y solo en las columnas que casi no cambian (ver RESCATABLES). Se rescata
     cuando el valor anterior y el siguiente del cliente son el mismo, o cuando
     el cliente tiene un unico valor en todos los meses. Si el cliente tuvo
     valores distintos y no hay certeza, el dato queda vacio.
  4. Aparta, sin borrarlos, los registros que no sirven: sin identificador, repetidos
     por (ncodpers, fecha_dato) o sin ningun dato del cliente. Quedan en la
     carpeta de rechazados con el motivo.

Cada fila de silver dice que se rescato (campos_rescatados) y que se invalido
(campos_invalidados). El trabajo escribe tambien un reporte de calidad.

Parametros del trabajo (Job parameters de Glue):
  --BUCKET       bucket de S3 (obligatorio)
  --RAW          carpeta del CSV crudo            (def. raw/train/)
  --SILVER       carpeta de salida en Parquet     (def. silver/train/)
  --RECHAZADOS   carpeta de los registros apartados (def. silver_rechazados/train/)
  --CALIDAD      carpeta del reporte de calidad   (def. calidad/train/)
"""
import argparse

from pyspark import StorageLevel
from pyspark.sql import SparkSession, Window, functions as F
from pyspark.sql.types import StringType, StructField, StructType

COLUMNAS = [
    "fecha_dato", "ncodpers", "ind_empleado", "pais_residencia", "sexo", "age",
    "fecha_alta", "ind_nuevo", "antiguedad", "indrel", "ult_fec_cli_1t",
    "indrel_1mes", "tiprel_1mes", "indresi", "indext", "conyuemp",
    "canal_entrada", "indfall", "tipodom", "cod_prov", "nomprov",
    "ind_actividad_cliente", "renta", "segmento",
    "ind_ahor_fin_ult1", "ind_aval_fin_ult1", "ind_cco_fin_ult1",
    "ind_cder_fin_ult1", "ind_cno_fin_ult1", "ind_ctju_fin_ult1",
    "ind_ctma_fin_ult1", "ind_ctop_fin_ult1", "ind_ctpp_fin_ult1",
    "ind_deco_fin_ult1", "ind_deme_fin_ult1", "ind_dela_fin_ult1",
    "ind_ecue_fin_ult1", "ind_fond_fin_ult1", "ind_hip_fin_ult1",
    "ind_plan_fin_ult1", "ind_pres_fin_ult1", "ind_reca_fin_ult1",
    "ind_tjcr_fin_ult1", "ind_valo_fin_ult1", "ind_viv_fin_ult1",
    "ind_nomina_ult1", "ind_nom_pens_ult1", "ind_recibo_ult1",
]
PRODUCTOS = [c for c in COLUMNAS if c.startswith("ind_") and c.endswith("ult1")]
COLUMNAS_FECHA = ["fecha_dato", "fecha_alta", "ult_fec_cli_1t"]
COLUMNAS_INT = [
    "age", "ind_nuevo", "antiguedad", "indrel", "tipodom", "cod_prov",
    "ind_actividad_cliente",
] + PRODUCTOS

# Columnas que casi no cambian de un mes a otro: un vacio se puede rescatar con
# el valor del mismo cliente. No estan las que son un estado del mes (tiprel_1mes,
# indrel_1mes, ind_actividad_cliente), ni las que estan vacias a proposito:
# ult_fec_cli_1t y conyuemp, donde el vacio significa que no aplica.
RESCATABLES = [
    "ind_empleado", "pais_residencia", "sexo", "fecha_alta", "indresi", "indext",
    "indfall", "canal_entrada", "cod_prov", "nomprov", "segmento", "tipodom",
]
EDAD_MINIMA, EDAD_MAXIMA = 0, 122  # 122 anos: la edad documentada mas alta
COLUMNAS_SILVER = COLUMNAS + ["campos_rescatados", "campos_invalidados"]


def leer_csv(spark, ruta):
    """Lee el CSV con el esquema explicito, todo como texto: evita una pasada
    extra de inferSchema sobre 2.3 GB y deja la limpieza en nuestras manos."""
    esquema = StructType([StructField(c, StringType()) for c in COLUMNAS])
    return spark.read.csv(ruta, header=True, schema=esquema, quote='"', escape='"')


def normalizar_texto(df):
    """Quita los espacios y convierte '' y 'NA' en null."""
    columnas = []
    for c in df.columns:
        valor = F.trim(F.col(c))
        columnas.append(F.when((valor == "") | (valor == "NA"), None).otherwise(valor).alias(c))
    return df.select(columnas)


def conversion(c):
    """Como se convierte cada columna de texto a su tipo."""
    if c in COLUMNAS_FECHA:
        return F.to_date(F.col(c), "yyyy-MM-dd")
    if c == "ncodpers":
        return F.col(c).cast("long")
    if c == "renta":
        return F.col(c).cast("double")
    if c == "indrel_1mes":
        # '1.0' y '1' son el mismo tipo de cliente
        return F.regexp_replace(c, r"\.0$", "")
    if c in COLUMNAS_INT:
        return F.col(c).cast("int")
    return F.col(c)


COLUMNAS_CON_CONVERSION = COLUMNAS_FECHA + COLUMNAS_INT + ["ncodpers", "renta"]


def tipar(df):
    return df.select([conversion(c).alias(c) for c in COLUMNAS])


def tiene_identificador():
    return F.col("ncodpers").isNotNull() & F.col("fecha_dato").isNotNull()


def etiquetas(pares):
    """Une con comas los nombres cuya condicion se cumple; null si ninguno."""
    texto = F.concat_ws(",", *[F.when(condicion, F.lit(nombre)) for nombre, condicion in pares])
    return F.when(F.length(texto) > 0, texto)


def invalidar_valores(df):
    """Deja en null los valores imposibles y lo anota en campos_invalidados."""
    edad_imposible = F.col("age").isNotNull() & ~F.col("age").between(EDAD_MINIMA, EDAD_MAXIMA)
    antiguedad_imposible = F.coalesce(F.col("antiguedad") < 0, F.lit(False))
    return (
        df.withColumn(
            "campos_invalidados",
            etiquetas([("age", edad_imposible), ("antiguedad", antiguedad_imposible)]),
        )
        .withColumn("age", F.when(~edad_imposible, F.col("age")))
        .withColumn("antiguedad", F.when(~antiguedad_imposible, F.col("antiguedad")))
    )


def rescatar_y_marcar(df):
    """Rescata los vacios de RESCATABLES con el dato real del mismo cliente,
    anota que se rescato y agrega el motivo por el que se aparta cada fila.

    Un vacio se rescata si el valor conocido mas reciente y el siguiente valor
    conocido del cliente son iguales, o si el cliente tiene un unico valor en
    todos sus meses. Si hay dudas, queda vacio."""
    completitud = sum((F.col(c).isNotNull().cast("int") for c in COLUMNAS), F.lit(0))
    df = df.withColumn("_completitud", completitud)
    orden = Window.partitionBy("ncodpers").orderBy("fecha_dato", F.col("_completitud").desc())
    anteriores = orden.rowsBetween(Window.unboundedPreceding, Window.currentRow)
    posteriores = orden.rowsBetween(Window.currentRow, Window.unboundedFollowing)
    cliente = Window.partitionBy("ncodpers")

    # Con varios registros en el mismo mes, el mas completo va primero y el resto
    # es repetido
    repetido = F.coalesce(F.lag("fecha_dato").over(orden) == F.col("fecha_dato"), F.lit(False))

    rescatado = {}
    for c in RESCATABLES:
        anterior = F.last(c, ignorenulls=True).over(anteriores)
        siguiente = F.first(c, ignorenulls=True).over(posteriores)
        distintos = F.size(F.collect_set(c).over(cliente))
        valor = (
            F.when(anterior == siguiente, anterior)
            .when(anterior.isNull() & (distintos == 1), siguiente)
            .when(siguiente.isNull() & (distintos == 1), anterior)
        )
        rescatado[c] = F.coalesce(F.col(c), valor)

    df = df.withColumn("_repetido", repetido)
    pares = [(c, F.col(c).isNull() & rescatado[c].isNotNull()) for c in RESCATABLES]
    df = df.withColumn("campos_rescatados", etiquetas(pares))
    df = df.select(
        [rescatado[c].alias(c) if c in rescatado else F.col(c) for c in df.columns]
    )
    return df.withColumn(
        "motivo",
        F.when(F.col("_repetido"), "repetido_fecha_dato_ncodpers")
        .when(F.col("fecha_alta").isNull(), "sin_datos_del_cliente"),
    ).drop("_completitud", "_repetido")


def con_columnas_de_control(df, motivo):
    return (
        df.withColumn("campos_rescatados", F.lit(None).cast("string"))
        .withColumn("campos_invalidados", F.lit(None).cast("string"))
        .withColumn("motivo", F.lit(motivo))
    )


def metricas_de_lectura(texto):
    """Una pasada sobre el CSV: filas leidas, filas sin identificador y valores
    que no se pudieron convertir a su tipo."""
    sin_identificador = ~(conversion("ncodpers").isNotNull() & conversion("fecha_dato").isNotNull())
    agregados = [
        F.count(F.lit(1)).alias("filas_leidas"),
        F.sum(F.when(sin_identificador, 1).otherwise(0)).alias("sin_identificador"),
    ]
    for c in COLUMNAS_CON_CONVERSION:
        fallo = F.col(c).isNotNull() & conversion(c).isNull()
        agregados.append(F.sum(F.when(fallo, 1).otherwise(0)).alias(f"fallo_{c}"))
    return texto.agg(*agregados).first().asDict()


def reporte_de_calidad(spark, lectura, resultado):
    """Una fila por metrica: (metrica, detalle, filas)."""
    filas = [("filas_leidas", "", lectura["filas_leidas"])]
    for c in COLUMNAS_CON_CONVERSION:
        if lectura[f"fallo_{c}"]:
            filas.append(("conversion_fallida", c, lectura[f"fallo_{c}"]))
    if lectura["sin_identificador"]:
        filas.append(("rechazadas", "sin_identificador", lectura["sin_identificador"]))
    for r in resultado.groupBy("motivo").count().where(F.col("motivo").isNotNull()).collect():
        filas.append(("rechazadas", r["motivo"], r["count"]))

    silver = resultado.where(F.col("motivo").isNull())
    contar = [F.count(F.lit(1)).alias("_total")]
    for c in RESCATABLES:
        contar.append(
            F.sum(F.when(F.array_contains(F.split("campos_rescatados", ","), c), 1).otherwise(0)).alias(f"resc_{c}")
        )
    for c in ["age", "antiguedad"]:
        contar.append(
            F.sum(F.when(F.array_contains(F.split("campos_invalidados", ","), c), 1).otherwise(0)).alias(f"inv_{c}")
        )
    for c in COLUMNAS:
        contar.append(F.sum(F.col(c).isNull().cast("long")).alias(f"nulo_{c}"))
    total = silver.agg(*contar).first().asDict()
    filas.append(("filas_en_silver", "", total["_total"]))
    for c in RESCATABLES:
        filas.append(("campo_rescatado", c, total[f"resc_{c}"]))
    for c in ["age", "antiguedad"]:
        filas.append(("campo_invalidado", c, total[f"inv_{c}"]))
    for c in COLUMNAS:
        filas.append(("nulos_en_silver", c, total[f"nulo_{c}"]))
    return spark.createDataFrame(filas, "metrica string, detalle string, filas long")


def main():
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--BUCKET", required=True)
    parser.add_argument("--RAW", default="raw/train/")
    parser.add_argument("--SILVER", default="silver/train/")
    parser.add_argument("--RECHAZADOS", default="silver_rechazados/train/")
    parser.add_argument("--CALIDAD", default="calidad/train/")
    # Glue agrega sus propios argumentos (--JOB_NAME, --JOB_RUN_ID, ...)
    args, _ = parser.parse_known_args()
    base = f"s3://{args.BUCKET}/"

    spark = SparkSession.builder.appName("limpieza-train").getOrCreate()
    # Spark 4 viene con ANSI activo: un cast invalido seria un error y aqui debe
    # ser un null, que se cuenta en el reporte
    spark.conf.set("spark.sql.ansi.enabled", "false")

    texto = normalizar_texto(leer_csv(spark, base + args.RAW))
    lectura = metricas_de_lectura(texto)

    tipado = tipar(texto)
    sin_id = con_columnas_de_control(tipado.where(~tiene_identificador()), "sin_identificador")
    resultado = rescatar_y_marcar(
        invalidar_valores(tipado.where(tiene_identificador()))
    ).persist(StorageLevel.MEMORY_AND_DISK)

    silver = resultado.where(F.col("motivo").isNull()).select(COLUMNAS_SILVER)
    (
        silver.repartition("fecha_dato")
        .sortWithinPartitions("ncodpers")
        .write.mode("overwrite")
        .partitionBy("fecha_dato")
        .parquet(base + args.SILVER)
    )

    rechazados = resultado.where(F.col("motivo").isNotNull()).select(COLUMNAS_SILVER + ["motivo"])
    (
        rechazados.unionByName(sin_id.select(COLUMNAS_SILVER + ["motivo"]))
        .coalesce(1)
        .write.mode("overwrite")
        .parquet(base + args.RECHAZADOS)
    )

    reporte = reporte_de_calidad(spark, lectura, resultado)
    reporte.coalesce(1).write.mode("overwrite").parquet(base + args.CALIDAD)
    for r in reporte.where(F.col("metrica") != "nulos_en_silver").orderBy("metrica", "detalle").collect():
        print(f"[limpieza] {r['metrica']:<20} {r['detalle']:<34} {r['filas']}")

    resultado.unpersist()
    spark.stop()


if __name__ == "__main__":
    main()
