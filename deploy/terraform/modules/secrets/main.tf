# Secretos POR INSTALACIÓN (spec 020 US5, FR-019/FR-026): cada tofu apply
# genera los suyos — cero defaults compartidos entre clientes. Viven en el
# state (por eso el remote state va CIFRADO y los outputs sensitive); el .lic
# y las keys de proveedor viajan aparte, cifrados con SOPS+age en el perfil.

resource "random_password" "postgres" {
  length  = 32
  special = false
}

resource "random_password" "litellm_master" {
  length  = 40
  special = false
}

resource "random_password" "jwt" {
  length  = 48
  special = false
}

resource "random_password" "admin_bootstrap" {
  length  = 24
  special = false
  # Rotación (FR-027): tofu apply -replace=module.secrets.random_password.admin_bootstrap
}

# Fernet exige 32 bytes url-safe base64: se derivan de un password aleatorio.
resource "random_password" "fernet_seed" {
  length  = 32
  special = false
}

output "postgres_password" {
  value     = random_password.postgres.result
  sensitive = true
}

output "litellm_master_key" {
  value     = "sk-${random_password.litellm_master.result}"
  sensitive = true
}

output "jwt_secret_key" {
  value     = random_password.jwt.result
  sensitive = true
}

output "fernet_secret_key" {
  value     = base64encode(random_password.fernet_seed.result)
  sensitive = true
}

output "admin_bootstrap" {
  value     = random_password.admin_bootstrap.result
  sensitive = true
}
