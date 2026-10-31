-- Ejecutar en Log Analytics / Observability Analytics. Elegir la hora del run.
-- Inicio incluye run_id; sustituir YOUR_RUN_ID por el valor de run.json.
SELECT
  TIMESTAMP_TRUNC(timestamp, MINUTE) AS minute,
  JSON_VALUE(json_payload.category) AS category,
  COUNT(*) AS requests,
  COUNTIF(JSON_VALUE(json_payload.outcome) = 'client_error') AS client_errors,
  COUNTIF(JSON_VALUE(json_payload.outcome) = 'server_error') AS server_errors,
  100.0 * SAFE_DIVIDE(
    COUNTIF(JSON_VALUE(json_payload.outcome) != 'success'), COUNT(*)
  ) AS error_pct
FROM `YOUR_PROJECT_ID.global._Default._Default`
WHERE resource.type = 'cloud_run_revision'
  AND JSON_VALUE(resource.labels.service_name) = 'orders-api'
  AND JSON_VALUE(json_payload.message) = 'request_completed'
  AND STARTS_WITH(JSON_VALUE(json_payload.request_id), 'YOUR_RUN_ID-')
GROUP BY minute, category
ORDER BY minute, category;
