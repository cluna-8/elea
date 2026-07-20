# Infraestructura

Arquitectura de despliegue objetivo de la plataforma: red, datos, cómputo, secretos y
TLS/DNS, tanto en cloud como on-prem/air-gapped. Complementa la
[guía de instalación](index.md).

**Leyenda de estado**:

| Marca | Significado |
|---|---|
| 🟢 **HOY** | Implementado y verificable en la versión actual del producto |
| 🟡 **PARCIAL** | Existe la base, falta endurecerlo para producción |
| 🔵 **OBJETIVO** | Roadmap / estado-objetivo, no existe aún |

!!! note "Estado"
    🔵 Salvo el stack de contenedores en sí (🟢), toda esta topología es
    **estado-objetivo**: hoy el producto se levanta como 5 contenedores en una sola máquina
    (dev/demo). El objetivo de producción es el siguiente.

```text
                        ┌───────────────────── VPC del cliente (región EU) ─────────────────────┐
   DNS por cliente      │                                                                        │
 cliente.marca.example ►│  ┌──────────────┐   TLS terminado    ┌─────────── cómputo ──────────┐  │
        (TLS)           │  │ LB / ingress │ ─────────────────► │ frontend (estático)          │  │
                        │  │ (ALB/Caddy)  │                    │ backend  (FastAPI)           │  │
                        │  └──────────────┘                    │ motor    (@digest pin)       │  │
                        │         │                            └──────────────┬───────────────┘  │
                        │         │  secretos inyectados                      │                  │
                        │  ┌──────┴───────┐                    ┌──────────────┴───────┐          │
                        │  │ Secrets Mgr  │                    │ Postgres gestionado  │          │
                        │  │ (SM/Vault)   │                    │ Redis gestionado     │          │
                        │  └──────────────┘                    └──────────────────────┘          │
                        └────────────────────────────────────────────────────────────────────────┘
```

## Componentes

### Red

VPC dedicada del cliente, subredes privadas para cómputo/datos, sólo el LB expuesto. Región
**EU** por defecto (residencia de datos). 🔵

*Excepción acotada*: la ruta del firewall de coding tools (clients de tipo `base_url`) tiene
**GDPR-routing = N/A** — no se fuerza endpoint EU en esa ruta; la garantía se traslada a
masking/audit/allowlist (excepción documentada del principio de residencia EU).

### Datos gestionados (cloud)

**Postgres** (RDS / Cloud SQL / Azure DB) y **Redis** (ElastiCache / MemoryStore) gestionados
en vez de los contenedores `postgres:16-alpine`/`redis:7-alpine` del compose. Backups y HA
quedan del lado del proveedor gestionado. 🔵

### Cómputo

- **v1 (hoy portable)**: una VM (EC2/GCE/Azure VM) corriendo `docker compose` con el stack,
  con **Caddy** al frente (**auto-TLS**, sin ALB) y secretos con **SOPS/age** (cifrados en el
  artefacto, **sin servidor** de secrets manager). Es el camino más corto y el que refleja el
  estado actual del producto. 🟡
- **v2 (objetivo)**: **k3s + Helm + Zarf** con las imágenes de producción. **No ECS/EKS**:
  ECS Anywhere **no corre air-gapped** y el modelo de entrega es on-prem/air-gapped → k3s
  (Kubernetes liviano) + Helm (charts) + Zarf (empaquetado/registry air-gapped). 🔵

### Secretos por instalación

Cada instalación genera **sus propios secretos** (aleatorios, fuertes); jamás se comparten
entre clientes ni se versionan en claro.

- En **cloud**, un **secrets manager** (AWS Secrets Manager / GCP Secret Manager / HashiCorp
  Vault) provee `POSTGRES_PASSWORD`, la clave maestra del motor, `FERNET_SECRET_KEY`,
  `JWT_SECRET_KEY` y las keys de proveedor LLM, inyectadas como variables de entorno al
  arrancar. 🔵
- En **v1 / air-gapped** (sin un secrets manager gestionado) la alternativa es **SOPS/age**:
  los secretos viajan **cifrados en el artefacto** y se descifran al desplegar, **sin
  servidor**. 🔵
- En cualquier caso, **nunca** el `.env` en claro con los defaults inseguros del compose de
  desarrollo: rotá **todos** los valores por defecto antes de exponer la instalación.
- Cifrado en reposo 🟢: `FERNET_SECRET_KEY` cifra en reposo los secretos de servicio y la
  referencia de credencial OAuth (`oauth_credential_ref`) de la ruta
  `subscription-passthrough`.

### TLS + DNS por cliente

Certificado + dominio propio del cliente terminando en el LB. 🔵

## On-prem / air-gapped

El mismo código corre single-tenant en el datacenter del cliente, sin depender de servicios
cloud:

- **Artefacto**: tarball con todas las imágenes pinneadas por digest (incluido el sitio de
  documentación, `basa-docs:<brand>-<version>`) + checksums, que se mueve al host destino
  (USB/SFTP) y se carga con `docker load`. 🔵
- **Storage durable**: sin servicios gestionados, Postgres y Redis corren en contenedor con
  **volumen durable** en el host; los backups pasan a ser responsabilidad del operador.
- **Egress**: el único egress necesario es hacia los proveedores LLM (vía NAT/proxy). Con
  **modelos locales** (Ollama/vLLM en la lista de modelos del perfil) el egress es **cero**.
- **Licencia**: la verificación de licencia es **100% offline** — jamás llama a casa. Ver
  [Licenciamiento](licensing.md).
- **Camino v2**: paquete **Zarf** (bundle con SBOM + firma cosign). 🔵

!!! tip "Gotcha relacionado"
    En redes sin egress, `git clone` y `docker pull` fallan y los proveedores LLM remotos no
    son alcanzables — ver los
    [gotchas de instalación](index.md#gotcha-egress).
