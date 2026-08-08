# Root OpenTofu del entorno de examen de La ITV — Hetzner Cloud (decisión 08-ago, swap
# desde AWS: la única cuenta AWS accesible hospeda prod legal de un cliente → blast radius).
# Root NUEVO y mínimo (research R4): NO reutiliza el root de clientes (ese provisiona
# RDS/ElastiCache y rompería la paridad con la sede — FR-011). Se ejecuta con `tofu`, no
# terraform. El apply queda BLOQUEADO hasta que exista el project guardian-itv + token
# (lo crea Cris, JF genera el token a Vaultwarden).
terraform {
  required_version = ">= 1.8.0"
  required_providers {
    hcloud = {
      source  = "hetznercloud/hcloud"
      version = "~> 1.49"
    }
  }
  # State local para el ciclo 1 (un solo operador). Si se comparte, mover a un backend
  # cifrado del propio project.
}

provider "hcloud" {
  # El token del project guardian-itv se pasa por env HCLOUD_TOKEN (Vaultwarden → shell),
  # NUNCA en un .tf ni en el repo. El token es POR PROJECT: no ve el project del VPS de prod.
  # (sin token declarado acá; el provider lo toma de HCLOUD_TOKEN)
}
