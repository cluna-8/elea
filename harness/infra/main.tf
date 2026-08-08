# Topología del examen: SUT (stack de producción) + generador (k6+stub), en una red
# privada, con el SUT SIN egress a internet (el candado del SLO de canarios: el tráfico
# no puede salir hacia un proveedor real). Las imágenes del stack se precargan por
# docker save/load ANTES de cerrar el firewall (research R4, opción b — sin registry).

resource "hcloud_network" "itv" {
  name     = "guardian-itv-net"
  ip_range = var.private_net_cidr
}

resource "hcloud_network_subnet" "itv" {
  network_id   = hcloud_network.itv.id
  type         = "cloud"
  network_zone = "eu-central"
  ip_range     = cidrsubnet(var.private_net_cidr, 8, 0) # 10.0.0.0/24
}

# ── SUT: sistema bajo prueba. Egress a internet BLOQUEADO. ──────────────────────────
resource "hcloud_server" "sut" {
  name        = "guardian-itv-sut"
  server_type = var.sut_server_type
  image       = var.image
  location    = var.location
  ssh_keys    = var.ssh_key_names
  labels      = { team = "itv", role = "sut" }

  # Sin public IPv4/IPv6 de salida usable: el SUT vive en la red privada. (Hetzner asigna
  # IP pública por default; el firewall de abajo corta el egress igual — cinturón y tiradores.)
  public_net {
    ipv4_enabled = true # necesaria para el bootstrap/precarga; el firewall corta la salida después
    ipv6_enabled = false
  }
}

resource "hcloud_server_network" "sut" {
  server_id  = hcloud_server.sut.id
  network_id = hcloud_network.itv.id
  ip         = "10.0.0.10"
}

# ── Generador: k6 + stub + puente de métricas hacia el centro. ──────────────────────
resource "hcloud_server" "gen" {
  name        = "guardian-itv-gen"
  server_type = var.gen_server_type
  image       = var.image
  location    = var.location
  ssh_keys    = var.ssh_key_names
  labels      = { team = "itv", role = "generador" }

  public_net {
    ipv4_enabled = true
    ipv6_enabled = false
  }
}

resource "hcloud_server_network" "gen" {
  server_id  = hcloud_server.gen.id
  network_id = hcloud_network.itv.id
  ip         = "10.0.0.20"
}

# ── Firewall del SUT: DENY egress. Sólo entra tráfico de carga desde el generador (red
#    privada) y SSH del operador. NADA sale hacia internet → el stub es el único destino
#    posible de los proveedores de IA (candado físico del SLO de canarios, R2). ─────────
resource "hcloud_firewall" "sut_no_egress" {
  name = "guardian-itv-sut-no-egress"

  # ENTRADA: SSH del operador + tráfico de carga desde la red privada.
  rule {
    direction  = "in"
    protocol   = "tcp"
    port       = "22"
    source_ips = var.admin_ssh_cidrs
  }
  rule {
    direction  = "in"
    protocol   = "tcp"
    port       = "any"
    source_ips = [var.private_net_cidr] # el generador y la sonda, por red privada
  }

  # SALIDA: SOLO dentro de la red privada (remote_write de la sonda al centro). Cualquier
  # destino fuera de la red privada NO tiene regla → Hetzner lo BLOQUEA (deny by default en
  # cuanto existe al menos una regla out). Esto es el egress-block que pide la spec.
  rule {
    direction       = "out"
    protocol        = "tcp"
    port            = "any"
    destination_ips = [var.private_net_cidr]
  }
  rule {
    direction       = "out"
    protocol        = "udp"
    port            = "any"
    destination_ips = [var.private_net_cidr]
  }
}

resource "hcloud_firewall_attachment" "sut" {
  firewall_id = hcloud_firewall.sut_no_egress.id
  server_ids  = [hcloud_server.sut.id]
}
