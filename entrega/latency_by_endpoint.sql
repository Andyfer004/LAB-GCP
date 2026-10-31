SELECT
  TIMESTAMP_TRUNC(timestamp, MINUTE) AS minute,
  JSON_VALUE(json_payload.endpoint) AS endpoint,
  COUNT(*) AS requests,
  AVG(SAFE_CAST(JSON_VALUE(json_payload.latency_ms) AS FLOAT64)) AS avg_latency_ms,
  APPROX_QUANTILES(SAFE_CAST(JSON_VALUE(json_payload.latency_ms) AS FLOAT64), 100)[OFFSET(95)] AS p95_latency_ms
FROM `YOUR_PROJECT_ID.global._Default._Default`
WHERE resource.type = 'cloud_run_revision'
  AND JSON_VALUE(resource.labels.service_name) = 'orders-api'
  AND JSON_VALUE(json_payload.message) = 'request_completed'
  AND STARTS_WITH(JSON_VALUE(json_payload.request_id), 'YOUR_RUN_ID-')
GROUP BY minute, endpoint
ORDER BY minute, endpoint;
