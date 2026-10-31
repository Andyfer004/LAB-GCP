locals {
  services = toset([
    "cloudfunctions.googleapis.com", "run.googleapis.com",
    "cloudbuild.googleapis.com", "artifactregistry.googleapis.com",
    "storage.googleapis.com", "logging.googleapis.com",
    "monitoring.googleapis.com", "iam.googleapis.com",
    "firestore.googleapis.com", "serviceusage.googleapis.com",
  ])
  student_roles = ["roles/monitoring.editor", "roles/logging.viewer",
    "roles/logging.configWriter", "roles/cloudfunctions.viewer",
  "roles/observability.analyticsUser"]
  student_grants = {
    for pair in setproduct(var.student_members, local.student_roles) :
    "${pair[0]}|${pair[1]}" => { member = pair[0], role = pair[1] }
  }
}
resource "google_project_service" "apis" {
  for_each           = local.services
  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}
# La activación de Analytics es permanente, como advierte el enunciado.
resource "google_logging_project_bucket_config" "default" {
  project          = var.project_id
  location         = "global"
  bucket_id        = "_Default"
  retention_days   = var.log_retention_days
  enable_analytics = true
  depends_on       = [google_project_service.apis]
}
resource "google_service_account" "runtime" {
  account_id   = "${var.function_name}-run"
  display_name = "Runtime ${var.function_name}"
  depends_on   = [google_project_service.apis]
}
resource "google_service_account" "build" {
  account_id   = "${var.function_name}-build"
  display_name = "Build ${var.function_name}"
  depends_on   = [google_project_service.apis]
}
resource "google_project_iam_member" "runtime_roles" {
  for_each = toset(["roles/logging.logWriter", "roles/monitoring.metricWriter", "roles/datastore.user"])
  project  = var.project_id
  role     = each.value
  member   = "serviceAccount:${google_service_account.runtime.email}"
}
resource "google_project_iam_member" "build_roles" {
  for_each = toset(["roles/cloudbuild.builds.builder", "roles/logging.logWriter"])
  project  = var.project_id
  role     = each.value
  member   = "serviceAccount:${google_service_account.build.email}"
}
resource "google_project_iam_member" "students" {
  for_each = local.student_grants
  project  = var.project_id
  role     = each.value.role
  member   = each.value.member
}
# Base nombrada y exclusiva del lab; no tocar una base (default) preexistente.
resource "google_firestore_database" "orders" {
  project                 = var.project_id
  name                    = "orders-lab"
  location_id             = var.region
  type                    = "FIRESTORE_NATIVE"
  delete_protection_state = "DELETE_PROTECTION_DISABLED"
  deletion_policy         = "DELETE"
  depends_on              = [google_project_service.apis]
}
resource "google_storage_bucket" "source" {
  name                        = "${var.project_id}-${var.function_name}-src"
  location                    = var.region
  uniform_bucket_level_access = true
  force_destroy               = true
  depends_on                  = [google_project_service.apis]
}
data "archive_file" "source" {
  type        = "zip"
  source_dir  = var.source_dir
  excludes    = ["__pycache__", ".venv", ".pytest_cache"]
  output_path = "${path.module}/.build/function-source.zip"
}
resource "google_storage_bucket_object" "source" {
  name   = "function-source-${data.archive_file.source.output_md5}.zip"
  bucket = google_storage_bucket.source.name
  source = data.archive_file.source.output_path
}
resource "google_cloudfunctions2_function" "api" {
  name     = var.function_name
  location = var.region
  build_config {
    runtime         = var.runtime
    entry_point     = var.entry_point
    service_account = google_service_account.build.id
    source {
      storage_source {
        bucket = google_storage_bucket.source.name
        object = google_storage_bucket_object.source.name
      }
    }
  }
  service_config {
    available_memory                 = "512Mi"
    available_cpu                    = "1"
    timeout_seconds                  = 60
    min_instance_count               = 0
    max_instance_count               = var.max_instances
    max_instance_request_concurrency = var.concurrency
    service_account_email            = google_service_account.runtime.email
    ingress_settings                 = "ALLOW_ALL"
    environment_variables = merge(var.extra_env, {
      FAILURE_RATE       = tostring(var.failure_rate)
      EXTRA_LATENCY_MS   = tostring(var.extra_latency_ms)
      FIRESTORE_DATABASE = google_firestore_database.orders.name
    })
  }
  depends_on = [google_project_iam_member.build_roles,
  google_project_iam_member.runtime_roles, google_logging_metric.requests]
}
resource "google_cloud_run_v2_service_iam_member" "public" {
  count    = var.allow_unauthenticated ? 1 : 0
  project  = var.project_id
  location = var.region
  name     = basename(google_cloudfunctions2_function.api.service_config[0].service)
  role     = "roles/run.invoker"
  member   = "allUsers"
}
