output "product_url" {
  value       = "https://${var.product_domain}"
  description = "URL del producto (FR-022)."
}

output "admin_bootstrap" {
  value       = module.secrets.admin_bootstrap
  sensitive   = true # emitido UNA vez: tofu output -raw admin_bootstrap (FR-027)
  description = "Credencial admin inicial, generada y rotable por instalación."
}

output "postgres_endpoint" {
  value = module.database.endpoint
}

output "redis_endpoint" {
  value = module.cache.endpoint
}
