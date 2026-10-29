"""Pruebas de las reglas de limpieza, con Spark local.

    pip install pyspark pytest
    python -m pytest silver-clean/glue
"""
import importlib.util
import os
import sys
from datetime import date
from pathlib import Path

import pytest
from pyspark.sql import SparkSession
from pyspark.sql.types import StringType, StructField, StructType

# En Windows los trabajadores de Spark necesitan saber cual es el Python
os.environ.setdefault("PYSPARK_PYTHON", sys.executable)

ruta = Path(__file__).parent / "limpieza_train.py"
spec = importlib.util.spec_from_file_location("limpieza_train", ruta)
lt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lt)


@pytest.fixture(scope="module")
def spark():
    sesion = (
        SparkSession.builder.master("local[2]")
        .config("spark.sql.shuffle.partitions", "2")
        .config("spark.ui.enabled", "false")
        .getOrCreate()
    )
    # Lo mismo que hace main()
    sesion.conf.set("spark.sql.ansi.enabled", "false")
    yield sesion
    sesion.stop()


def crudo(spark, filas):
    """Las 48 columnas del CSV en texto; lo que no se indica queda vacio."""
    esquema = StructType([StructField(c, StringType()) for c in lt.COLUMNAS])
    return spark.createDataFrame(
        [tuple(f.get(c, "") for c in lt.COLUMNAS) for f in filas], esquema
    )


def cliente(**campos):
    base = {
        "fecha_dato": "2015-01-28", "ncodpers": "1", "ind_empleado": "N",
        "pais_residencia": "ES", "sexo": "H", "age": " 35", "fecha_alta": "2014-05-10",
        "ind_nuevo": " 0", "antiguedad": "     8", "indrel": " 1", "indrel_1mes": "1.0",
        "tiprel_1mes": "A", "indresi": "S", "indext": "N", "canal_entrada": "KHE",
        "indfall": "N", "tipodom": " 1", "cod_prov": "28", "nomprov": "MADRID",
        "ind_actividad_cliente": " 1", "renta": "100.5", "segmento": "02 - PARTICULARES",
    }
    return {**base, **campos}


def limpiar(spark, filas):
    """El mismo recorrido que main(), sin leer ni escribir."""
    tipado = lt.tipar(lt.normalizar_texto(crudo(spark, filas)))
    con_id = tipado.where(lt.tiene_identificador())
    return lt.rescatar_y_marcar(lt.invalidar_valores(con_id)).collect()


def por_mes(filas):
    return {(f["ncodpers"], f["fecha_dato"].month): f for f in filas}


def test_arregla_el_formato_sin_cambiar_el_contenido(spark):
    fila = limpiar(spark, [cliente(
        age="  40", ind_nuevo=" 0", antiguedad="NA", ind_nomina_ult1="NA",
        ind_cco_fin_ult1=" 1", ind_ahor_fin_ult1="0", ult_fec_cli_1t="2015-07-02",
        renta="122179.11000000002", indrel_1mes="3.0",
    )])[0]
    assert fila["age"] == 40 and fila["ind_nuevo"] == 0
    assert fila["fecha_dato"] == date(2015, 1, 28)
    assert fila["ult_fec_cli_1t"] == date(2015, 7, 2)
    assert fila["indrel_1mes"] == "3"          # '3.0' y '3' son lo mismo
    assert fila["renta"] == 122179.11000000002
    # lo que no tiene dato no se rellena: ni la antiguedad ni el producto
    assert fila["antiguedad"] is None
    assert fila["ind_nomina_ult1"] is None
    assert fila["ind_cco_fin_ult1"] == 1 and fila["ind_ahor_fin_ult1"] == 0
    assert fila["conyuemp"] is None


def test_invalida_edad_y_antiguedad_imposibles(spark):
    filas = por_mes(limpiar(spark, [
        cliente(ncodpers="1", fecha_dato="2015-01-28", age="164"),
        cliente(ncodpers="2", fecha_dato="2015-01-28", age="101"),     # una edad real
        cliente(ncodpers="3", fecha_dato="2015-01-28", antiguedad="-999999"),
        cliente(ncodpers="4", fecha_dato="2015-01-28", age="122"),
    ]))
    assert filas[(1, 1)]["age"] is None and filas[(1, 1)]["campos_invalidados"] == "age"
    assert filas[(2, 1)]["age"] == 101 and filas[(2, 1)]["campos_invalidados"] is None
    assert filas[(3, 1)]["antiguedad"] is None and filas[(3, 1)]["campos_invalidados"] == "antiguedad"
    assert filas[(4, 1)]["age"] == 122


def test_rescata_cuando_antes_y_despues_coinciden(spark):
    filas = por_mes(limpiar(spark, [
        cliente(fecha_dato="2015-01-28", segmento="03 - UNIVERSITARIO"),
        cliente(fecha_dato="2015-02-28", segmento=""),
        cliente(fecha_dato="2015-03-28", segmento="03 - UNIVERSITARIO"),
    ]))
    assert filas[(1, 2)]["segmento"] == "03 - UNIVERSITARIO"
    assert filas[(1, 2)]["campos_rescatados"] == "segmento"
    assert filas[(1, 1)]["campos_rescatados"] is None


def test_no_rescata_si_el_valor_cambio(spark):
    filas = por_mes(limpiar(spark, [
        cliente(fecha_dato="2015-01-28", segmento="03 - UNIVERSITARIO"),
        cliente(fecha_dato="2015-02-28", segmento=""),
        cliente(fecha_dato="2015-03-28", segmento="02 - PARTICULARES"),
    ]))
    # no se sabe si fue universitario o particular en febrero
    assert filas[(1, 2)]["segmento"] is None
    assert filas[(1, 2)]["campos_rescatados"] is None


def test_rescata_al_principio_o_al_final_si_hay_un_unico_valor(spark):
    filas = por_mes(limpiar(spark, [
        cliente(ncodpers="1", fecha_dato="2015-01-28", canal_entrada=""),
        cliente(ncodpers="1", fecha_dato="2015-02-28", canal_entrada="KHE"),
        cliente(ncodpers="1", fecha_dato="2015-03-28", canal_entrada=""),
        # con dos valores distintos, el vacio del final no se puede rescatar
        cliente(ncodpers="2", fecha_dato="2015-01-28", canal_entrada="KHE"),
        cliente(ncodpers="2", fecha_dato="2015-02-28", canal_entrada="KAT"),
        cliente(ncodpers="2", fecha_dato="2015-03-28", canal_entrada=""),
    ]))
    assert filas[(1, 1)]["canal_entrada"] == "KHE" and filas[(1, 3)]["canal_entrada"] == "KHE"
    assert filas[(2, 3)]["canal_entrada"] is None


def test_no_rescata_estados_del_mes_ni_los_vacios_a_proposito(spark):
    filas = por_mes(limpiar(spark, [
        cliente(fecha_dato="2015-01-28", tiprel_1mes="A", conyuemp="N", renta="50"),
        cliente(fecha_dato="2015-02-28", tiprel_1mes="", conyuemp="", renta=""),
        cliente(fecha_dato="2015-03-28", tiprel_1mes="A", conyuemp="N", renta="50"),
    ]))
    assert filas[(1, 2)]["tiprel_1mes"] is None
    assert filas[(1, 2)]["conyuemp"] is None
    assert filas[(1, 2)]["renta"] is None       # la renta nunca se rellena


def test_aparta_los_registros_sin_datos_del_cliente_y_los_repetidos(spark):
    filas = limpiar(spark, [
        # un cliente con todos sus datos, una vez completo y una vez repetido y vacio
        cliente(ncodpers="1", fecha_dato="2015-01-28"),
        cliente(ncodpers="1", fecha_dato="2015-01-28", sexo="", fecha_alta="", age="", segmento=""),
        # un cliente que solo trae productos
        {"fecha_dato": "2015-01-28", "ncodpers": "2", "ind_cco_fin_ult1": "1"},
    ])
    motivos = sorted((f["ncodpers"], f["motivo"] or "") for f in filas)
    assert motivos == [(1, ""), (1, "repetido_fecha_dato_ncodpers"), (2, "sin_datos_del_cliente")]
    # el que se queda es el registro completo
    assert [f for f in filas if f["ncodpers"] == 1 and f["motivo"] is None][0]["sexo"] == "H"


def test_un_registro_sin_datos_se_rescata_con_los_del_mismo_cliente(spark):
    filas = por_mes(limpiar(spark, [
        cliente(ncodpers="1", fecha_dato="2015-01-28"),
        {"fecha_dato": "2015-02-28", "ncodpers": "1", "ind_cco_fin_ult1": "1"},
        cliente(ncodpers="1", fecha_dato="2015-03-28"),
    ]))
    rescatada = filas[(1, 2)]
    assert rescatada["motivo"] is None
    assert rescatada["fecha_alta"] == date(2014, 5, 10) and rescatada["sexo"] == "H"
    assert rescatada["ind_cco_fin_ult1"] == 1
    # lo que cambia mes a mes no se inventa
    assert rescatada["age"] is None and rescatada["renta"] is None
    assert "fecha_alta" in rescatada["campos_rescatados"].split(",")


def test_sin_identificador_no_entra_en_la_ventana(spark):
    tipado = lt.tipar(lt.normalizar_texto(crudo(spark, [
        cliente(ncodpers="", fecha_dato="2015-01-28"),
        cliente(ncodpers="5", fecha_dato="no es una fecha"),
        cliente(ncodpers="6"),
    ])))
    assert tipado.where(~lt.tiene_identificador()).count() == 2
    lectura = lt.metricas_de_lectura(lt.normalizar_texto(crudo(spark, [
        cliente(ncodpers="", fecha_dato="2015-01-28"),
        cliente(ncodpers="6", age="treinta"),
    ])))
    assert lectura["sin_identificador"] == 1
    assert lectura["fallo_age"] == 1
