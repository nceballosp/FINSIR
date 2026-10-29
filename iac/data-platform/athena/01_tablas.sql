-- Tablas de Athena sobre el CSV crudo y sobre la salida de la limpieza.
-- Es la alternativa a terraform/athena.tf: usalo si no creaste las tablas con
-- terraform.
-- Reemplaza YOUR_BUCKET por el nombre de tu bucket, y las carpetas si cambiaste
-- los prefijos del trabajo (raw/train/, silver/train/, silver_rechazados/train/
-- y calidad/train/).
-- En el editor de Athena, ejecuta UNA sentencia a la vez. Antes de la primera,
-- configura la carpeta de resultados: Settings, Manage, Location of query result.

-- Sentencia 1: la base de datos
CREATE DATABASE IF NOT EXISTS train_clean;

-- Sentencia 2: la capa bronze, el CSV tal como llego, todo en texto
CREATE EXTERNAL TABLE train_clean.bronze_train (
    fecha_dato             string,
    ncodpers               string,
    ind_empleado           string,
    pais_residencia        string,
    sexo                   string,
    age                    string,
    fecha_alta             string,
    ind_nuevo              string,
    antiguedad             string,
    indrel                 string,
    ult_fec_cli_1t         string,
    indrel_1mes            string,
    tiprel_1mes            string,
    indresi                string,
    indext                 string,
    conyuemp               string,
    canal_entrada          string,
    indfall                string,
    tipodom                string,
    cod_prov               string,
    nomprov                string,
    ind_actividad_cliente  string,
    renta                  string,
    segmento               string,
    ind_ahor_fin_ult1      string,
    ind_aval_fin_ult1      string,
    ind_cco_fin_ult1       string,
    ind_cder_fin_ult1      string,
    ind_cno_fin_ult1       string,
    ind_ctju_fin_ult1      string,
    ind_ctma_fin_ult1      string,
    ind_ctop_fin_ult1      string,
    ind_ctpp_fin_ult1      string,
    ind_deco_fin_ult1      string,
    ind_deme_fin_ult1      string,
    ind_dela_fin_ult1      string,
    ind_ecue_fin_ult1      string,
    ind_fond_fin_ult1      string,
    ind_hip_fin_ult1       string,
    ind_plan_fin_ult1      string,
    ind_pres_fin_ult1      string,
    ind_reca_fin_ult1      string,
    ind_tjcr_fin_ult1      string,
    ind_valo_fin_ult1      string,
    ind_viv_fin_ult1       string,
    ind_nomina_ult1        string,
    ind_nom_pens_ult1      string,
    ind_recibo_ult1        string
)
ROW FORMAT SERDE 'org.apache.hadoop.hive.serde2.OpenCSVSerde'
WITH SERDEPROPERTIES ('separatorChar' = ',', 'quoteChar' = '"')
LOCATION 's3://YOUR_BUCKET/raw/train/'
TBLPROPERTIES ('skip.header.line.count' = '1');

-- Sentencia 3: la capa silver, particionada por fecha_dato
CREATE EXTERNAL TABLE train_clean.silver_train (
    ncodpers               bigint,
    ind_empleado           string,
    pais_residencia        string,
    sexo                   string,
    age                    int,
    fecha_alta             date,
    ind_nuevo              int,
    antiguedad             int,
    indrel                 int,
    ult_fec_cli_1t         date,
    indrel_1mes            string,
    tiprel_1mes            string,
    indresi                string,
    indext                 string,
    conyuemp               string,
    canal_entrada          string,
    indfall                string,
    tipodom                int,
    cod_prov               int,
    nomprov                string,
    ind_actividad_cliente  int,
    renta                  double,
    segmento               string,
    ind_ahor_fin_ult1      int,
    ind_aval_fin_ult1      int,
    ind_cco_fin_ult1       int,
    ind_cder_fin_ult1      int,
    ind_cno_fin_ult1       int,
    ind_ctju_fin_ult1      int,
    ind_ctma_fin_ult1      int,
    ind_ctop_fin_ult1      int,
    ind_ctpp_fin_ult1      int,
    ind_deco_fin_ult1      int,
    ind_deme_fin_ult1      int,
    ind_dela_fin_ult1      int,
    ind_ecue_fin_ult1      int,
    ind_fond_fin_ult1      int,
    ind_hip_fin_ult1       int,
    ind_plan_fin_ult1      int,
    ind_pres_fin_ult1      int,
    ind_reca_fin_ult1      int,
    ind_tjcr_fin_ult1      int,
    ind_valo_fin_ult1      int,
    ind_viv_fin_ult1       int,
    ind_nomina_ult1        int,
    ind_nom_pens_ult1      int,
    ind_recibo_ult1        int,
    campos_rescatados      string,
    campos_invalidados     string
)
PARTITIONED BY (fecha_dato string)
STORED AS PARQUET
LOCATION 's3://YOUR_BUCKET/silver/train/';

-- Sentencia 4: registra las particiones que dejo el trabajo, una por mes.
-- Repitela cada vez que el trabajo escriba un mes nuevo.
MSCK REPAIR TABLE train_clean.silver_train;

-- Sentencia 5: los registros apartados, con el motivo
CREATE EXTERNAL TABLE train_clean.rechazados_train (
    fecha_dato             date,
    ncodpers               bigint,
    ind_empleado           string,
    pais_residencia        string,
    sexo                   string,
    age                    int,
    fecha_alta             date,
    ind_nuevo              int,
    antiguedad             int,
    indrel                 int,
    ult_fec_cli_1t         date,
    indrel_1mes            string,
    tiprel_1mes            string,
    indresi                string,
    indext                 string,
    conyuemp               string,
    canal_entrada          string,
    indfall                string,
    tipodom                int,
    cod_prov               int,
    nomprov                string,
    ind_actividad_cliente  int,
    renta                  double,
    segmento               string,
    ind_ahor_fin_ult1      int,
    ind_aval_fin_ult1      int,
    ind_cco_fin_ult1       int,
    ind_cder_fin_ult1      int,
    ind_cno_fin_ult1       int,
    ind_ctju_fin_ult1      int,
    ind_ctma_fin_ult1      int,
    ind_ctop_fin_ult1      int,
    ind_ctpp_fin_ult1      int,
    ind_deco_fin_ult1      int,
    ind_deme_fin_ult1      int,
    ind_dela_fin_ult1      int,
    ind_ecue_fin_ult1      int,
    ind_fond_fin_ult1      int,
    ind_hip_fin_ult1       int,
    ind_plan_fin_ult1      int,
    ind_pres_fin_ult1      int,
    ind_reca_fin_ult1      int,
    ind_tjcr_fin_ult1      int,
    ind_valo_fin_ult1      int,
    ind_viv_fin_ult1       int,
    ind_nomina_ult1        int,
    ind_nom_pens_ult1      int,
    ind_recibo_ult1        int,
    campos_rescatados      string,
    campos_invalidados     string,
    motivo                 string
)
STORED AS PARQUET
LOCATION 's3://YOUR_BUCKET/silver_rechazados/train/';

-- Sentencia 6: el reporte de calidad de la ultima ejecucion
CREATE EXTERNAL TABLE train_clean.calidad_train (
    metrica string,
    detalle string,
    filas   bigint
)
STORED AS PARQUET
LOCATION 's3://YOUR_BUCKET/calidad/train/';
