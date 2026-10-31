output "function_url" {
  value = google_cloudfunctions2_function.api.service_config[0].uri
}
output "log_analytics_view" {
  value = "`${var.project_id}.global._Default._Default`"
}
output "dashboards_console" {
  value = "https://console.cloud.google.com/monitoring/dashboards?project=${var.project_id}"
}
output "log_analytics_console" {
  value = "https://console.cloud.google.com/logs/analytics?project=${var.project_id}"
}
output "dashboard_id" {
  value = google_monitoring_dashboard.lab.id
}
