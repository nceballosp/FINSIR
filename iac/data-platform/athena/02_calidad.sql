-- Verificacion de la limpieza. Elige la base de datos (train_clean con 01_tablas.sql,
-- o la que creo terraform) y ejecuta UNA sentencia a la vez.
-- Los valores esperados son los del archivo train_ver2.csv completo (13647309
-- filas); con otro archivo cambian.

-- Sentencia 1: el reporte de la ultima ejecucion, sin el detalle de los nulos.
-- Expected: filas_leidas 13647309, filas_en_silver 13620624 y 26685 rechazadas
-- por sin_datos_del_cliente.
SELECT metrica, detalle, filas
FROM calidad_train
WHERE metrica <> 'nulos_en_silver'
ORDER BY metrica, detalle;

-- Sentencia 2: el crudo. Los numeros del reporte deben cerrar: leidas = en silver
-- + rechazadas.
-- Expected: 13647309 filas en el crudo.
SELECT count(*) AS filas_crudo, count(DISTINCT fecha_dato) AS meses
FROM bronze_train;

-- Sentencia 3: las filas de silver por mes
-- Expected: 618784 en 2015-01-28, 630293 en 2015-06-28, 829817 en 2015-07-28 y
-- 931453 en 2016-05-28. Hasta junio de 2015 hay menos que en el crudo porque los
-- registros sin datos del cliente se apartaron.
SELECT fecha_dato, count(*) AS filas
FROM silver_train
GROUP BY fecha_dato
ORDER BY fecha_dato;

-- Sentencia 4: lo que sigue vacio en silver, columna por columna. Nada se rellena:
-- un vacio es un dato que no existe.
-- Expected: renta 2767690, ult_fec_cli_1t 13595831 y conyuemp 13618816 (el vacio
-- significa que no aplica), cod_prov y nomprov 65194, segmento 41296,
-- canal_entrada 33900, indrel_1mes y tiprel_1mes 123096, sexo 70, ind_nomina_ult1
-- e ind_nom_pens_ult1 633, age 1071, antiguedad 1087.
SELECT count(*) AS filas,
       count_if(age IS NULL) AS age,
       count_if(antiguedad IS NULL) AS antiguedad,
       count_if(renta IS NULL) AS renta,
       count_if(sexo IS NULL) AS sexo,
       count_if(segmento IS NULL) AS segmento,
       count_if(canal_entrada IS NULL) AS canal_entrada,
       count_if(cod_prov IS NULL) AS cod_prov,
       count_if(indrel_1mes IS NULL) AS indrel_1mes,
       count_if(tiprel_1mes IS NULL) AS tiprel_1mes,
       count_if(ind_nomina_ult1 IS NULL) AS ind_nomina_ult1
FROM silver_train;

-- Sentencia 5: que se rescato con datos del mismo cliente. Cada fila de silver lo
-- dice en campos_rescatados.
-- Expected: canal_entrada 125541, segmento 121387, cod_prov 1712 y 1049 filas
-- que recuperaron la fecha de alta y el resto de datos fijos del cliente.
SELECT campo, count(*) AS filas
FROM silver_train
CROSS JOIN UNNEST(split(campos_rescatados, ',')) AS t(campo)
WHERE campos_rescatados IS NOT NULL
GROUP BY campo
ORDER BY filas DESC;

-- Sentencia 6: que valores imposibles se dejaron en null, y en cuantas filas.
-- Expected: age 22 y antiguedad 38.
SELECT campo, count(*) AS filas
FROM silver_train
CROSS JOIN UNNEST(split(campos_invalidados, ',')) AS t(campo)
WHERE campos_invalidados IS NOT NULL
GROUP BY campo;

-- Sentencia 7: los registros apartados, por motivo.
-- Expected: sin_datos_del_cliente 26685, de 7031 clientes que solo traen los
-- productos y nunca un dato propio.
SELECT motivo, count(*) AS filas, count(DISTINCT ncodpers) AS clientes
FROM rechazados_train
GROUP BY motivo;

-- Sentencia 8: un cliente con todo su historial, como lo pediria la API.
-- Sin el filtro de fecha_dato Athena lee todas las carpetas; con uno, solo las
-- de esos meses.
-- Expected: 17 filas. El cliente 62130 tiene el canal de entrada rescatado en 5
-- de ellas.
SELECT fecha_dato, age, sexo, segmento, canal_entrada, cod_prov, renta,
       ind_cco_fin_ult1, ind_recibo_ult1, campos_rescatados
FROM silver_train
WHERE ncodpers = 62130
ORDER BY fecha_dato;

-- Sentencia 9: nadie tiene dos registros en el mismo mes.
-- Expected: 0 filas.
SELECT ncodpers, fecha_dato, count(*) AS registros
FROM silver_train
GROUP BY ncodpers, fecha_dato
HAVING count(*) > 1
LIMIT 10;

-- Sentencia 10: las filas con pocos datos propios. Son registros que solo traian
-- los productos y a los que se les devolvieron los datos fijos del cliente; la
-- edad, la actividad y la renta de ese mes no existen.
-- Expected: 1049 filas.
SELECT count(*) AS filas
FROM silver_train
WHERE campos_rescatados LIKE '%fecha_alta%';
