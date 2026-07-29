terraform {
  required_version = ">= 1.7"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
  # Configure GCS backend before first apply.
  # backend "gcs" {
  #   bucket = "molli-tfstate"
  #   prefix = "env/dev"
  # }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

variable "project_id" {
  type        = string
  description = "GCP project ID (molli-dev or molli-prod)"
}

variable "region" {
  type    = string
  default = "us-central1"
}

variable "environment" {
  type        = string
  description = "dev or prod"
}

# Resources already provisioned manually (not yet captured as Terraform
# resources below):
# - APIs enabled (run, aiplatform, secretmanager, firestore, scheduler, cloudbuild, artifactregistry)
# - Service accounts (chat-service runtime, sync-job runtime, ci-deploy)
# - Secret Manager secrets (empty versions; values created manually)
# - Artifact Registry repo
# - Firestore database
# - Workload Identity Federation for GitHub Actions
# - Vertex AI Vector Search index + endpoint
# - Cloud Scheduler job
# - Cloud Run service + job
