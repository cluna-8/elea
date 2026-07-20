# Módulo OpenTofu portable (spec 020 US4). El dir se llama terraform/ por
# convención de ecosistema: OpenTofu (MPL 2.0) es drop-in sobre los mismos .tf —
# se ejecuta con `tofu`, no con terraform (BSL). Cloud de referencia v1: AWS.
terraform {
  required_version = ">= 1.8.0"
  required_providers {
    aws    = { source = "hashicorp/aws", version = "~> 5.0" }
    random = { source = "hashicorp/random", version = "~> 3.6" }
  }
  # Remote state POR CLIENTE (FR-023): bucket cifrado + workspaces. Se activa
  # por -backend-config en init (cada distribuidor trae su bucket); sin config,
  # state local (dev). key incluye el workspace automáticamente.
  backend "s3" {}
}

provider "aws" {
  region = var.region
}
