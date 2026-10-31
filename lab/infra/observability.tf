locals {
  log_filter = "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${var.function_name}\" AND jsonPayload.message=\"request_completed\""
  run_filter = "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${var.function_name}\""
}
resource "google_logging_metric" "requests" {
  name        = "orders_lab_requests"
  description = "Solicitudes finalizadas por resultado y categoría"
  filter      = local.log_filter
  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
    unit        = "1"
    labels {
      key        = "outcome"
      value_type = "STRING"
    }
    labels {
      key        = "category"
      value_type = "STRING"
    }
  }
  label_extractors = {
    outcome  = "EXTRACT(jsonPayload.outcome)"
    category = "EXTRACT(jsonPayload.category)"
  }
  depends_on = [google_project_service.apis]
}
resource "google_monitoring_dashboard" "lab" {
  dashboard_json = jsonencode({
    displayName = "Laboratorio - API observable"
    gridLayout = {
      columns = "2"
      widgets = [
        {
          title = "Tráfico nativo (solicitudes/s)"
          xyChart = {
            dataSets = [{
              plotType = "LINE"
              timeSeriesQuery = { timeSeriesFilter = {
                filter = "metric.type=\"run.googleapis.com/request_count\" AND ${local.run_filter}"
                aggregation = {
                  alignmentPeriod    = "60s", perSeriesAligner = "ALIGN_RATE"
                  crossSeriesReducer = "REDUCE_SUM", groupByFields = ["metric.label.response_code_class"]
                }
              } }
            }]
          }
        },
        {
          title = "Latencia p95 nativa (ms)"
          xyChart = {
            dataSets = [{
              plotType = "LINE"
              timeSeriesQuery = { timeSeriesFilter = {
                filter = "metric.type=\"run.googleapis.com/request_latencies\" AND ${local.run_filter}"
                aggregation = {
                  alignmentPeriod    = "60s", perSeriesAligner = "ALIGN_DELTA"
                  crossSeriesReducer = "REDUCE_PERCENTILE_95"
                }
              } }
            }]
          }
        },
        {
          title = "Resultados de negocio desde logs (solicitudes/s)"
          xyChart = {
            dataSets = [{
              plotType = "STACKED_AREA"
              timeSeriesQuery = { timeSeriesFilter = {
                filter = "metric.type=\"logging.googleapis.com/user/${google_logging_metric.requests.name}\" AND ${local.run_filter}"
                aggregation = {
                  alignmentPeriod    = "60s", perSeriesAligner = "ALIGN_RATE"
                  crossSeriesReducer = "REDUCE_SUM", groupByFields = ["metric.label.outcome", "metric.label.category"]
                }
              } }
            }]
          }
        },
        {
          title = "Logs de solicitudes"
          logsPanel = {
            filter        = local.log_filter
            resourceNames = ["projects/${var.project_id}"]
          }
        },
        {
          title = "Preguntas del laboratorio"
          text = {
            format  = "MARKDOWN"
            content = "¿Cuándo sube el tráfico y la latencia p95? ¿Qué proporción corresponde a 4xx y 5xx? ¿Aumentan los errores de electronics entre los minutos 35 y 45? Agrega las dos gráficas SQL de observability/ al mismo dashboard, desde Log Analytics / Observability Analytics."
          }
        }
      ]
    }
  })
  depends_on = [google_project_service.apis]
}
