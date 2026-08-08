variable "location" {
  description = "Datacenter Hetzner (queda en el fingerprint del run)."
  type        = string
  default     = "fsn1" # Falkenstein, Alemania (UE)
}

variable "sut_server_type" {
  description = "Caja del sistema bajo prueba. CCX = vCPU DEDICADAS (mejor para SC-005 que la tenancy compartida de AWS)."
  type        = string
  default     = "ccx33" # 8 vCPU dedicadas / 32 GB
}

variable "gen_server_type" {
  description = "Caja del generador k6 + stub (separada del SUT: el instrumento no compite por recursos)."
  type        = string
  default     = "ccx23" # 4 vCPU dedicadas / 16 GB
}

variable "image" {
  description = "Imagen base de las cajas."
  type        = string
  default     = "ubuntu-24.04"
}

variable "ssh_key_names" {
  description = "Nombres de las SSH keys ya cargadas en el project guardian-itv."
  type        = list(string)
  default     = []
}

variable "private_net_cidr" {
  description = "Red privada del examen (el tráfico de carga y el remote_write viajan por acá, sin internet)."
  type        = string
  default     = "10.0.0.0/16"
}

variable "admin_ssh_cidrs" {
  description = "CIDRs que pueden entrar por SSH al SUT (el operador del examen). Restringir; nunca 0.0.0.0/0 en un gate oficial."
  type        = list(string)
  default     = []
}
