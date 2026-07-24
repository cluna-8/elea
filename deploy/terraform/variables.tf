# Contrato del módulo (specs/020-whitelabel-deploy/contracts/client-profile.md).

variable "tenant_slug" {
  type        = string
  description = "Slug del cliente (013): nombra workspace, DNS y recursos."
}

variable "region" {
  type        = string
  default     = "eu-central-1"
  description = "Región AWS. Default EU (residencia GDPR, FR-021). El guard vive como precondition en main.tf (tofu 1.8 no cruza variables en validation)."
}

variable "allow_non_eu" {
  type        = bool
  default     = false
  description = "Override EXPLÍCITO para operar fuera de EU."
}

variable "product_domain" {
  type        = string
  description = "FQDN del producto (Caddy auto-HTTPS)."
}

variable "route53_zone_id" {
  type        = string
  description = "Zona DNS donde crear el registro del producto."
}

variable "backend_image" {
  type        = string
  description = "Imagen backend PINNEADA por digest (publish.sh)."
}

variable "frontend_image" {
  type        = string
  description = "Imagen frontend PINNEADA por digest (publish.sh)."
}

variable "litellm_image" {
  type        = string
  description = "Imagen LiteLLM pinneada (014)."
}

variable "nlp_analyzer_image" {
  type        = string
  description = "Imagen del analizador NLP pinneada por digest (016, publish.sh). Sin ella el motor degrada a detección por regex."
}

variable "image_source" {
  type        = string
  default     = "registry"
  description = "registry (pull) | tarball (air-gapped, US6 — FR-024)."
  validation {
    condition     = contains(["registry", "tarball"], var.image_source)
    error_message = "image_source debe ser 'registry' o 'tarball'."
  }
}

variable "profile_path" {
  type        = string
  description = "Ruta local al perfil RENDERIZADO del cliente (render_profile.sh)."
}

variable "instance_type" {
  type        = string
  default     = "t3.small"
  description = "Dimensionamiento de la VM v1."
}

variable "db_instance_class" {
  type    = string
  default = "db.t4g.micro"
}

variable "cache_node_type" {
  type    = string
  default = "cache.t4g.micro"
}
