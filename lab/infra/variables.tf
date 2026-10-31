variable "project_id" { type = string }
variable "region" {
  type    = string
  default = "us-central1"
}
variable "function_name" {
  type    = string
  default = "orders-api"
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{0,23}$", var.function_name))
    error_message = "Usa 1-24 caracteres: minúsculas, números y guiones, empezando por letra."
  }
}
variable "runtime" {
  type    = string
  default = "python313"
}
variable "entry_point" {
  type    = string
  default = "handle"
}
variable "source_dir" {
  type    = string
  default = "../backend"
}
variable "failure_rate" {
  type    = number
  default = 0.02
  validation {
    condition     = var.failure_rate >= 0 && var.failure_rate <= 1
    error_message = "failure_rate debe estar entre 0 y 1."
  }
}
variable "extra_latency_ms" {
  type    = number
  default = 0
  validation {
    condition     = var.extra_latency_ms >= 0
    error_message = "extra_latency_ms debe ser >= 0."
  }
}
variable "extra_env" {
  type    = map(string)
  default = {}
}
variable "max_instances" {
  type    = number
  default = 10
}
variable "concurrency" {
  type    = number
  default = 1
}
variable "allow_unauthenticated" {
  type    = bool
  default = true
}
variable "log_retention_days" {
  type    = number
  default = 30
}
variable "student_members" {
  type    = list(string)
  default = []
}
