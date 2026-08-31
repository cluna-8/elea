# harness/infra — entorno de examen (Hetzner Cloud, project `guardian-itv`)

Root OpenTofu mínimo del entorno de examen de La ITV. **Autorable ya; el `apply` está
BLOQUEADO** hasta que exista el project `guardian-itv` + token (lo crea Cris, JF genera
el token a Vaultwarden). Decisión de provider en el addendum de
[`research.md`](../../specs/035-load-harness/research.md) (swap AWS→Hetzner, 08-ago).

## Qué levanta

| Recurso | Qué es |
|---|---|
| `hcloud_server.sut` | **CCX33** (8 vCPU dedicadas / 32 GB): el stack de producción bajo prueba, `compose.prod.yml --profile selfhosted`. |
| `hcloud_server.gen` | **CCX23** (4 vCPU dedicadas / 16 GB): k6 + stub + puente de métricas. Separada para no competir por recursos con el SUT. |
| `hcloud_network.itv` | Red privada 10.0.0.0/16 (tráfico de carga + remote_write, sin cruzar internet). |
| `hcloud_firewall.sut_no_egress` | **DENY egress** en el SUT: el candado del SLO de canarios (el tráfico no puede salir hacia un proveedor real; el stub es el único destino posible). |

Las vCPU **dedicadas** de la línea CCX eliminan la varianza por vecinos ruidosos que la
tenancy compartida de AWS tenía — mejor para la repetibilidad (SC-005). Coste del par
~0,15 €/h → ~15-25 €/mes con stop/start.

## Flujo de uso (cuando exista el token)

```bash
export HCLOUD_TOKEN=…            # del project guardian-itv, vía Vaultwarden — NUNCA al repo
tofu init
tofu apply -var 'ssh_key_names=["itv-op"]' -var 'admin_ssh_cidrs=["A.B.C.D/32"]'

# ORDEN CRÍTICO: precargar imágenes ANTES de que el firewall corte el egress
./preload-images.sh "$(tofu output -raw sut_public_ip)" sentinel-backend:prod sentinel-litellm:pinned sentinel-nlp:piloto …

# los outputs alimentan el fingerprint del run
tofu output -json fingerprint_hardware
```

## Reglas

- **Nunca** el VPS de producción ni instalaciones de clientes (FR-011). Esto es un project
  aislado; su token no ve el project del VPS de prod.
- `admin_ssh_cidrs` restringido (nunca 0.0.0.0/0 en un gate oficial).
- Stop entre runs (EBS parado ~ centavos); reset `compose down -v && up` antes de cada gate
  oficial para matar drift.
- El apply lo coordina la sesión DevOps; esta carpeta es autoría de La ITV.
