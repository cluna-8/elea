# Los outputs alimentan el FINGERPRINT del run (FR-009): el hardware examinado queda
# registrado, así una comparación entre runs es legítima o se detecta que no lo es.
output "sut_server_type" {
  description = "Tipo de caja del SUT (va al fingerprint)."
  value       = hcloud_server.sut.server_type
}

output "gen_server_type" {
  value = hcloud_server.gen.server_type
}

output "datacenter" {
  description = "Datacenter (va al fingerprint)."
  value       = hcloud_server.sut.datacenter
}

output "sut_private_ip" {
  value = "10.0.0.10"
}

output "gen_private_ip" {
  value = "10.0.0.20"
}

output "sut_public_ip" {
  description = "Sólo para bootstrap/precarga de imágenes; el egress queda bloqueado por el firewall."
  value       = hcloud_server.sut.ipv4_address
}

output "gen_public_ip" {
  description = "Generador (k6 + stub): por acá entra el operador a lanzar el examen y a recoger artefactos. El firewall de egress es del SUT, no del generador."
  value       = hcloud_server.gen.ipv4_address
}

output "fingerprint_hardware" {
  description = "Bloque hardware listo para inyectar en el fingerprint del run."
  value = {
    provider        = "hetzner"
    sut_server_type = hcloud_server.sut.server_type
    gen_server_type = hcloud_server.gen.server_type
    datacenter      = hcloud_server.sut.datacenter
    location        = var.location
  }
}
