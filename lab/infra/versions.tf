terraform {
  required_version = ">= 1.5, < 2.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 6.0, < 8.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = ">= 2.4, < 3.0"
    }
  }
}
provider "google" {
  project = var.project_id
  region  = var.region
}
