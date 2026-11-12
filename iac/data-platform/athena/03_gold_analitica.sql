-- Consultas de ejemplo sobre las tablas gold analiticas (las crea Terraform en
-- la base de datos finsir, workgroup finsir). Sirven para revisar los datos en
-- el editor de Athena y como punto de partida de los endpoints de la API.
-- Ejecuta UNA sentencia a la vez.
--
-- Todas las tablas estan particionadas por fecha_dato (string 'YYYY-MM-DD',
-- de '2015-01-28' a '2016-05-28'). Filtra siempre por fecha_dato: Athena lee
-- solo esa carpeta y la consulta cuesta casi nada.
-- En la API, los valores entre <> son parametros: validalos antes de pegarlos
-- en el SQL (fecha con ^\d{4}-\d{2}-\d{2}$, producto contra la lista de 24,
-- dimension contra la lista de 7), como ya hace el repositorio de gold_train.

-- 0) Meses disponibles (para llenar un selector de mes en el dashboard)
SELECT DISTINCT fecha_dato
FROM gold_product_monthly_kpis
ORDER BY fecha_dato;

-- 1) gold_product_monthly_kpis: KPIs de un mes, del producto mas adquirido al menos
SELECT product, product_name, holders, penetration_rate, adds, add_rate,
       drops, drop_rate, net_adds, popularity_rank
FROM gold_product_monthly_kpis
WHERE fecha_dato = '2016-04-28'            -- <fecha_dato>
ORDER BY popularity_rank;

-- 1b) Serie de tiempo de un producto (tendencia y estacionalidad)
SELECT fecha_dato, holders, penetration_rate, adds, drops, net_adds
FROM gold_product_monthly_kpis
WHERE product = 'ind_recibo_ult1'          -- <product>
ORDER BY fecha_dato;

-- 2) gold_customer_profile: perfil por segmento en un mes (suma los grupos)
SELECT segmento,
       sum(clients)                                         AS clients,
       sum(active_clients) * 1.0 / sum(clients)             AS active_rate,
       sum(avg_n_products * clients) / sum(clients)         AS avg_n_products,
       sum(avg_renta * renta_known) / nullif(sum(renta_known), 0) AS avg_renta
FROM gold_customer_profile
WHERE fecha_dato = '2016-05-28'            -- <fecha_dato>
GROUP BY segmento
ORDER BY clients DESC;

-- 2b) Piramide de edad por sexo (filtrable por segmento)
SELECT age_band, sexo, sum(clients) AS clients
FROM gold_customer_profile
WHERE fecha_dato = '2016-05-28'            -- <fecha_dato>
  AND segmento = '02 - PARTICULARES'       -- <segmento> (opcional)
GROUP BY age_band, sexo
ORDER BY age_band, sexo;

-- 3) gold_product_penetration: mapa de calor producto x rango de edad
SELECT dimension_value, product_name, penetration_rate, clients, holders
FROM gold_product_penetration
WHERE fecha_dato = '2016-05-28'            -- <fecha_dato>
  AND dimension = 'age_band'               -- <dimension>: segmento, age_band, income_band,
                                           --   tenure_band, sexo, provincia, actividad
ORDER BY dimension_value, product;

-- 4) gold_product_affinity: matriz de correlacion (phi) para un mes
SELECT product_a_name, product_b_name, phi, lift, confidence
FROM gold_product_affinity
WHERE fecha_dato = '2016-05-28'            -- <fecha_dato>
ORDER BY product_a, product_b;

-- 4b) Venta cruzada: que productos acompanan mas a la cuenta de nomina
SELECT product_b_name, confidence, lift, holders_both
FROM gold_product_affinity
WHERE fecha_dato = '2016-05-28'            -- <fecha_dato>
  AND product_a = 'ind_cno_fin_ult1'       -- <product>
ORDER BY lift DESC
LIMIT 10;

-- 5) gold_product_transitions: enlaces del Sankey de un mes (los mas grandes)
SELECT from_product_name, to_product_name, clients, share
FROM gold_product_transitions
WHERE fecha_dato = '2016-04-28'            -- <fecha_dato>
ORDER BY clients DESC
LIMIT 40;                                   -- <limit>: un Sankey legible usa 20-50 enlaces

-- 6) gold_baseline_popularity: MAP@7 del modelo base por mes
--    (fecha_dato = mes del ranking, label_fecha_dato = mes evaluado)
SELECT fecha_dato, label_fecha_dato, top_7_products, clients_evaluated,
       clients_with_adds, map_at_7, map_at_7_buyers, hit_rate_at_7_buyers
FROM gold_baseline_popularity
ORDER BY fecha_dato;

-- 6b) Recomendacion base para un cliente (fallback mientras no exista el modelo):
--     el ranking del ultimo mes menos lo que el cliente ya tiene, primeros 7.
WITH ranking AS (
  SELECT split(popularity_ranking, ',') AS products
  FROM gold_baseline_popularity
  WHERE fecha_dato = '2016-05-28'          -- <fecha_dato>: ultimo mes
),
client AS (
  SELECT *
  FROM gold_train
  WHERE fecha_dato = '2016-05-28'          -- <fecha_dato>
    AND ncodpers = 1375586                 -- <ncodpers>
)
SELECT slice(
         filter(r.products, p -> NOT contains(
           filter(ARRAY[
             IF(c.ind_ahor_fin_ult1 = 1, 'ind_ahor_fin_ult1'), IF(c.ind_aval_fin_ult1 = 1, 'ind_aval_fin_ult1'),
             IF(c.ind_cco_fin_ult1 = 1, 'ind_cco_fin_ult1'),   IF(c.ind_cder_fin_ult1 = 1, 'ind_cder_fin_ult1'),
             IF(c.ind_cno_fin_ult1 = 1, 'ind_cno_fin_ult1'),   IF(c.ind_ctju_fin_ult1 = 1, 'ind_ctju_fin_ult1'),
             IF(c.ind_ctma_fin_ult1 = 1, 'ind_ctma_fin_ult1'), IF(c.ind_ctop_fin_ult1 = 1, 'ind_ctop_fin_ult1'),
             IF(c.ind_ctpp_fin_ult1 = 1, 'ind_ctpp_fin_ult1'), IF(c.ind_deco_fin_ult1 = 1, 'ind_deco_fin_ult1'),
             IF(c.ind_deme_fin_ult1 = 1, 'ind_deme_fin_ult1'), IF(c.ind_dela_fin_ult1 = 1, 'ind_dela_fin_ult1'),
             IF(c.ind_ecue_fin_ult1 = 1, 'ind_ecue_fin_ult1'), IF(c.ind_fond_fin_ult1 = 1, 'ind_fond_fin_ult1'),
             IF(c.ind_hip_fin_ult1 = 1, 'ind_hip_fin_ult1'),   IF(c.ind_plan_fin_ult1 = 1, 'ind_plan_fin_ult1'),
             IF(c.ind_pres_fin_ult1 = 1, 'ind_pres_fin_ult1'), IF(c.ind_reca_fin_ult1 = 1, 'ind_reca_fin_ult1'),
             IF(c.ind_tjcr_fin_ult1 = 1, 'ind_tjcr_fin_ult1'), IF(c.ind_valo_fin_ult1 = 1, 'ind_valo_fin_ult1'),
             IF(c.ind_viv_fin_ult1 = 1, 'ind_viv_fin_ult1'),   IF(c.ind_nomina_ult1 = 1, 'ind_nomina_ult1'),
             IF(c.ind_nom_pens_ult1 = 1, 'ind_nom_pens_ult1'), IF(c.ind_recibo_ult1 = 1, 'ind_recibo_ult1')
           ], x -> x IS NOT NULL), p)),
         1, 7) AS recommended_products
FROM ranking r CROSS JOIN client c;
