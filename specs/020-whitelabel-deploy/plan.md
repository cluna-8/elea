# Implementation Plan: White-Label Packaging & Deploy

**Branch**: `020-whitelabel-deploy` | **Date**: 2026-07-13 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/020-whitelabel-deploy/spec.md`

## Summary

Convertir el estado actual (todo **dev-mode**, **cero IaC**) en un **producto de marca blanca que el
DISTRIBUIDOR levanta donde quiera con OpenTofu**. El modelo de negocio manda el shape: Basa **cobra INSTALL + X
licencias y NO instala ni opera servidores** — entrega imágenes/bundle + un **módulo OpenTofu portable** + un
**perfil por cliente**. La arquitectura se estructura en **cuatro artefactos** encadenados:

1. **Imágenes de producción** (US1): backend multistage (gunicorn/uvicorn workers, non-root, sin `--reload`) +
   frontend `vite build` → estáticos por Caddy/nginx; publicadas pinneadas (tag+digest) **o** como tarball
   air-gapped. Reemplazan los Dockerfiles de desarrollo en el camino prod (el compose de dev se conserva sólo
   para local).
2. **Branding pack como config** (US2): nombre/logo/colores/dominio como **config-as-data en runtime** (env +
   assets montados, **una marca por instancia**, no build-time); **never fork**; el motor (LiteLLM) **nunca se
   nombra** (Principio VII).
3. **Perfil por cliente** (US3): env + `seed_client` (013) + branding pack + `config.yaml` **templado**, atado al
   `tenant.slug` (013) para dominio/DNS/workspace (Principios IV y III).
4. **Módulo OpenTofu portable** (US4): VPC (443-only + NAT) + Postgres gestionado + Redis gestionado + cómputo
   (v1 VM+cloud-init; v2 **k3s+Helm+Zarf**) + secretos (**SOPS+age** v1 / **OpenBao** v2) + TLS/ingress
   (**Caddy** v1 / **Traefik** v2) + DNS + **región EU** + remote state/**workspaces por cliente**. Con
   **secretos generados por instalación** (US5) y **camino air-gapped/tarball** (US6).

El enfoque técnico central: **empaquetar y desplegar reusando el bedrock** (013 slug/seed, 014 imagen
pinneada/config/extensiones) **sin forkear el código** (Principio VII). Se entrega **OpenTofu** (MPL 2.0, CNCF),
**no Terraform** (BSL desde 2023 + HashiCorp es ahora IBM: entregar IaC BSL a un distribuidor tercero es deuda
legal evitable; OpenTofu es drop-in sobre los mismos `.tf`). El **enforcement de licencias** queda para la
**spec 021**; aquí sólo se deja el hueco de entrada. **v1 = un cloud de referencia (AWS) con VM+docker-compose**;
**k3s+Helm+Zarf** es el roadmap v2 (mismo Kubernetes en nube/on-prem/air-gap). **ECS/Fargate se descarta**:
**ECS Anywhere no corre air-gapped** (conexión permanente al control plane de AWS in-region).

## Technical Context

**Language/Version**: Sin lenguaje de producto nuevo. Empaquetado: **Dockerfiles multistage** (Python 3.12
backend, Node 20 frontend build → estáticos). IaC: **OpenTofu** (HCL, **MPL 2.0 / CNCF** — no Terraform por su
**BSL**) + **cloud-init** para el cómputo v1. App server: **uvicorn workers** o **gunicorn + UvicornWorker**
(granian opcional). Reusa el código Python/FastAPI del backend y el frontend Vite tal cual (se **buildean**, no
se reescriben).

**Primary Dependencies**: OpenTofu (HCL) con **módulos por provider** (cloud de referencia AWS:
VPC/RDS/ElastiCache/Route53 — sin atarse a servicios de orquestación propietarios); Docker (multistage build,
`docker save` para tarball; **Zarf** para air-gap k8s en v2); **Caddy** (estáticos + TLS auto-HTTPS v1; Traefik
en k3s v2); **SOPS + age** para secretos (OpenBao en v2); las imágenes/artefactos de la **014** (LiteLLM
pinneada, `config.yaml`, `litellm/extensions`) y de la **013** (`seed_client`, `tenant.slug`).

**Storage**: **Postgres gestionado** (RDS/CloudSQL) vía swap de `POSTGRES_*` (abandona el `pgdata` efímero del
compose de dev; on-prem/air-gap usa Postgres en contenedor con volumen durable). **Redis gestionado**
(ElastiCache/MemoryStore) vía `REDIS_*`. **Secretos** cifrados con **SOPS + age** (v1, sin servidor y apto
air-gap) / **OpenBao** (v2, fork MPL de Vault) — **no** secrets managers cloud como base (atan a una nube, no
existen en air-gap). **Remote state** cifrado con workspace por cliente.

**Testing**: validación de artefactos — build reproducible de las imágenes prod (inspección de capas: non-root,
sin toolchain, sin `--reload`, frontend estático); `tofu validate`/`plan`/`apply` en cloud sandbox
(región EU); checks negativos (0 secretos default en camino prod, 0 mención del motor en artefactos de marca
blanca, 0 secretos en claro en state/outputs); prueba air-gapped (`docker load` sin registry).

**Target Platform**: Linux server en containers, desplegado por OpenTofu en cuenta cloud del cliente (v1: VM +
docker compose por cloud-init) o on-prem/air-gapped (tarball). Principio VII (Containerized & White-Label).

**Project Type**: infraestructura + empaquetado (deploy artifacts), no lógica de producto. El código de producto
(backend/frontend) se **reusa y buildea**; el trabajo es Dockerfiles prod + branding config + perfil + OpenTofu.

**Performance Goals**: sin objetivo de throughput nuevo; la meta es un `tofu apply` reproducible que deja
una instalación funcional por HTTPS. La única exigencia de runtime es que las imágenes prod no degraden vs dev.

**Constraints**: secretos **fuera de config en claro** y **generados por instalación** (Constraint C5 de la 014
+ US5); **región EU** por defecto (residencia GDPR, adyacente al Principio II); **never fork** (config+seed,
Principio VII); **aislamiento por cliente** en state/secretos (Principio III); **el motor nunca se nombra** en
marca blanca (VII).

**Scale/Scope**: 4 familias de artefactos nuevos (imágenes prod, branding pack, perfil de cliente, módulo
OpenTofu) + retirada de secretos default del camino prod + camino air-gapped. **N instalaciones** por el
distribuidor vía workspaces. Sin schema nuevo (todo viene de 013/014). Licencias = 021 (fuera de scope).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principio / Constraint | Cómo lo cumple esta feature | Veredicto |
|---|---|---|
| **VII. Containerized & White-Label (config+seed, never fork)** | Imágenes prod multistage reproducibles; branding pack como config (nombre/logo/colores/dominio por env/build); perfil por cliente = env+seed+branding+config templado; el motor (LiteLLM) nunca se nombra; un codebase con dos perfiles de build (dev-compose / prod-images). | PASS by-design / a construir |
| **IV. Client Onboarding as Data** | El cliente es un **artefacto** (perfil) que materializa `seed_client` (013) idempotente; levantar un cliente = rellenar un perfil + un workspace, no editar código. | PASS by-design / a construir |
| **III. Multi-Tenant by Design** | `tenant.slug` (013) deriva dominio/DNS y nombre de workspace; remote state + workspaces por cliente con secretos aislados; sin fuga cross-tenant. | PASS by-design / a construir |
| **I. Privacy & Masking-First (adyacente)** | TLS terminado en ingress (Caddy); secretos cifrados con SOPS+age/OpenBao, nunca en claro; residencia EU por defecto. No cambia la lógica de masking (viene de 014). | PASS by-design (empaquetado) |
| **II. Compliance FIRST (adyacente)** | Región **EU fijable por defecto** (residencia GDPR); el empaquetado no relaja el enforcement de 014, lo transporta intacto. | PASS by-design (residencia) |
| **Constraint C5 — Credenciales fuera de config** | Retira los defaults del compose de dev del camino prod; secretos **generados por instalación** y cifrados con SOPS+age/OpenBao; admin bootstrap rotado; nada en `tfvars`/state/logs en claro. | PASS by-design / a construir |
| **Dev Workflow — Reuse over Reinvent** | Reusa `seed_client`/`tenant.slug` (013) y la imagen pinneada/`config.yaml`/extensiones (014); el branding y el perfil son config, no código; OpenTofu empaqueta, no reescribe. | PASS by-design |
| **V. Cost Governance (no aplica directo)** | El empaquetado no introduce gobernanza de coste nueva (vive en el motor/013); N/A salvo por dimensionar recursos cloud razonables. | N/A (fuera de scope) |
| **VIII. Pipeline Transparency (no aplica directo)** | El monitor/transparencia son de la 014; esta spec no los toca, sólo los empaqueta. | N/A (fuera de scope) |

**Sin violaciones de principio a justificar** (ver Complexity Tracking): esta feature **honra** VII/IV/III por
diseño; no hay excepción constitucional que registrar. La única tensión (licencias) se resuelve **sacándolas de
scope** (spec 021), no violando un principio.

## Mapeo estado actual → objetivo (dev-mode → producto empaquetado + IaC)

Traducción fiel de lo que existe hoy (dev) a los artefactos objetivo (prod/IaC). Columna "Dueño" =
REUSA (bedrock 013/014) vs NUEVO (esta spec).

| Estado actual (dev-mode, hoy) | Objetivo (020) | Dueño |
|---|---|---|
| `backend/Dockerfile` single-stage, `uvicorn --reload`, root, `build-essential` en la imagen | `deploy/docker/backend.prod.Dockerfile` multistage, gunicorn/uvicorn workers, non-root, healthcheck, sin toolchain | NUEVO |
| `frontend/Dockerfile` `npm run dev` (vite dev server, sin build) | `deploy/docker/frontend.prod.Dockerfile`: `vite build` → estáticos por Caddy/nginx, non-root | NUEVO |
| `docker-compose.yml` con bind-mounts de código (`./backend:/app`, `./frontend:/app`) | imágenes prod self-contained (código horneado); compose de dev conservado sólo para local | NUEVO (+ conserva dev) |
| `pgdata` en volumen docker efímero | Postgres gestionado (RDS/CloudSQL) por swap `POSTGRES_*` | NUEVO (OpenTofu `database`) |
| Redis in-container (`redis:7-alpine`) | Redis gestionado (ElastiCache/MemoryStore) por swap `REDIS_*` | NUEVO (OpenTofu `cache`) |
| Secretos default en compose (`basasecurepass123`, `basa_master_key_9999`) | secretos **generados por instalación** y cifrados con SOPS+age (v1) / OpenBao (v2); admin bootstrap rotado | NUEVO (US5) |
| Sin TLS | TLS/ingress (Caddy auto-HTTPS v1 / Traefik v2) + DNS por `tenant.slug` | NUEVO (OpenTofu `ingress`) |
| Imagen LiteLLM pinneada por digest (014) | reusada tal cual en el release (registry o tarball) | REUSA (014) |
| `litellm/config.yaml` montado como volumen (014) | **templado por cliente** (model_list/proveedores/keys/región), montado, no horneado | REUSA (014) + templado NUEVO |
| `seed_gateway_demo` → `seed_client` idempotente (013) | seed del **perfil de cliente** (onboarding-as-data) | REUSA (013) |
| `tenant.slug` (013) | deriva dominio/DNS + nombre de workspace | REUSA (013) |
| Branding hardcodeado en el frontend | branding pack como **config-as-data en runtime** (env + assets montados, una marca por instancia), default Basa-neutro + override distribuidor | NUEVO (US2) |
| Deploy manual `git clone` + `docker compose up` (DEPLOY_VPN.md) | módulo OpenTofu portable (v1) + camino air-gapped/tarball (on-prem sin egress) | NUEVO (US4/US6) |
| — (no existe) | hueco de entrada de license key (sin enforcement) | NUEVO placeholder → **spec 021** |

## Project Structure

### Documentation (this feature)

```text
specs/020-whitelabel-deploy/
├── plan.md              # This file
├── spec.md              # Feature spec (user stories, FR, SC)
├── tasks.md             # Task list (por user story)
├── research.md          # Phase 0: OpenTofu vs Terraform (BSL), VM+cloud-init v1 vs k3s+Helm+Zarf v2, SOPS/age vs OpenBao, Caddy/TLS
├── quickstart.md        # Phase 1 (a generar): rellenar un perfil → tofu apply (EU) → HTTPS → validar
└── contracts/           # Phase 1 (a generar): variables/outputs del módulo + contrato del perfil de cliente
```

### Source Code (repository root)

```text
deploy/                                    # NUEVO — artefactos de empaquetado + IaC
├── docker/
│   ├── backend.prod.Dockerfile            # NUEVO: multistage, gunicorn/uvicorn workers, non-root, healthcheck
│   ├── frontend.prod.Dockerfile           # NUEVO: vite build -> estáticos por Caddy/nginx, non-root
│   └── entrypoint/                         # NUEVO: entrypoints prod (migraciones + arranque sin --reload)
├── branding/                              # NUEVO — branding pack como CONFIG (never fork)
│   ├── branding.default.env               # Basa-neutro (fallback)
│   ├── branding.example.env               # ejemplo de distribuidor
│   └── assets/                             # logos/colores placeholder (montados en runtime, no baked)
├── clients/                               # NUEVO — perfiles por cliente (artefactos; secretos NO aquí)
│   └── <client-slug>/
│       ├── client.env                     # endpoints, región, flags
│       ├── branding.env                   # override de marca del distribuidor
│       ├── seed.yaml                      # onboarding-as-data -> seed_client (013)
│       └── config.yaml.tmpl               # litellm config TEMPLADO (model_list/proveedores/keys/región)
├── terraform/                             # NUEVO — módulo OpenTofu portable (`.tf` drop-in; dir sin renombrar)
│   ├── modules/
│   │   ├── network/                        # VPC, subredes pub/priv, SG (443-only), NAT
│   │   ├── database/                       # Postgres gestionado (RDS/CloudSQL) -> POSTGRES_*
│   │   ├── cache/                          # Redis gestionado (ElastiCache/MemoryStore) -> REDIS_*
│   │   ├── compute/                        # v1: VM + docker compose (cloud-init); v2 (roadmap): k3s + Helm + Zarf
│   │   ├── secrets/                        # SOPS + age (v1) / OpenBao (v2) + random_password (US5)
│   │   └── ingress/                        # TLS: Caddy auto-HTTPS (v1) / Traefik (v2) + DNS por tenant.slug
│   ├── envs/
│   │   └── <client>/                       # workspace + tfvars por cliente (remote state aislado)
│   └── README.md                           # bump/región EU/workspaces
└── release/                               # NUEVO — publicación de imágenes / tarball air-gapped
    ├── publish.sh                          # push pinneado a registry (tag+digest)
    └── bundle.sh                           # docker save -> tarball (US6)

docker-compose.yml                         # CONSERVADO sólo para dev local (no sale a prod)
backend/ , frontend/ , litellm/            # REUSADOS: se buildean/empaquetan, NO se reescriben
```

**Structure Decision**: todo lo nuevo vive bajo `deploy/` para dejar claro que es **empaquetado + IaC**, no
lógica de producto (que se reusa de `backend/`, `frontend/`, `litellm/`). El código propio se divide por
**tipo de artefacto**: (a) `deploy/docker/` para las imágenes prod; (b) `deploy/branding/` para el branding-como-
config; (c) `deploy/clients/<slug>/` para el perfil por cliente (onboarding-as-data 013); (d) `deploy/terraform/`
para el módulo **OpenTofu** portable con submódulos por recurso (se conserva el nombre de dir: OpenTofu es
drop-in sobre los mismos `.tf`); (e) `deploy/release/` para publicar/empaquetar. No se crea
schema nuevo (013) ni lógica de firewall nueva (014): esta spec **empaqueta y despliega** lo existente.

## Orden de implementación

1. **Phase 0 research.** Fijar **OpenTofu vs Terraform** (BSL), el **cloud de referencia** (v1 AWS), la
   estrategia de cómputo (VM+cloud-init v1 vs **k3s+Helm+Zarf** v2; descarte de ECS Anywhere por air-gap), el
   store de secretos (**SOPS+age** vs **OpenBao**) y el modo TLS (**Caddy** vs Traefik). Documentar la
   residencia EU y el layout de remote state/workspaces. Bloquea el diseño del módulo.
2. **US1 imágenes de producción (P1).** `backend.prod.Dockerfile` (multistage, non-root, sin `--reload`) +
   `frontend.prod.Dockerfile` (vite build → estáticos). Publicación pinneada + esqueleto del tarball. Base de
   todo el resto (OpenTofu monta sobre estas imágenes).
3. **US2 branding pack (P1).** Branding como **config-as-data en runtime** (env + assets montados, una marca por
   instancia; no build-time), default Basa-neutro + override; check de que el motor no se nombra. Independiente
   de OpenTofu.
4. **US3 perfil por cliente (P1).** Estructura del perfil-artefacto (env + seed `seed_client` 013 + branding +
   `config.yaml.tmpl`), atado a `tenant.slug`. Pegamento entre producto (US1/US2) y deploy (US4).
5. **US4 módulo OpenTofu (P1).** Submódulos `network`/`database`/`cache`/`compute`/`secrets`/`ingress`;
   región EU; remote state + workspaces por cliente; outputs (URL + admin bootstrap). Consume perfil (US3) e
   imágenes (US1).
6. **US5 secretos por instalación (P2).** Retirar defaults del camino prod; `random_password` cifrados con
   SOPS+age (v1) / OpenBao (v2); admin bootstrap rotado. Se integra en el submódulo `secrets` de US4.
7. **US6 air-gapped/tarball (P3).** `bundle.sh` (`docker save`) + variable de fuente de imágenes (registry vs
   tarball) + doc on-prem sin egress. Cierra el caso Elea.
8. **Cierre.** Validación end-to-end: `tofu apply` en EU deja HTTPS funcional; checks negativos (secretos,
   motor, region); prueba air-gapped; `quickstart.md`.

## Riesgos

| Riesgo | Impacto | Mitigación |
|---|---|---|
| **Deriva dev↔prod (dos codebases de facto)**: los Dockerfiles prod divergen del código que corre en dev. | Alto — se rompe "never fork" (VII) y se mantiene doble. | Un solo codebase con **dos perfiles de build**; el compose de dev sólo para local; CI que buildea ambas rutas del mismo árbol. |
| **Secreto default sobrevive al camino prod** (`${VAR:-default}` olvidado). | Alto — agujero de seguridad replicado a N clientes. | Check negativo (US5) que **falla** si aparece cualquier default conocido en artefactos prod; retirada explícita del compose de dev en prod. |
| **Secretos en claro en el state/outputs de OpenTofu**. | Alto — credenciales expuestas en el backend de state. | Secretos cifrados con SOPS+age/OpenBao; `random_password` + outputs marcados `sensitive`; remote state **cifrado**; admin bootstrap emitido una vez, no persistido. |
| **`config.yaml` u otros datos horneados en la imagen** (no templables por cliente). | Medio — no se puede parametrizar por cliente sin rebuild. | `config.yaml` **templado** y montado (patrón de volumen 014); branding por env + assets montados en runtime, no baked. |
| **Región no-EU por default/descuido**. | Alto — rompe residencia GDPR (II). | Default **EU**; el apply avisa/falla si se fija fuera de EU sin override explícito. |
| **Multi-cloud / air-gap prometido de más**: HCL AWS no porta 1:1 a GCP/Azure; y ECS Anywhere **no** corre air-gapped (conexión permanente al control plane de AWS). | Medio — alcance infla, o se elige un cómputo que rompe on-prem. | v1 = **un cloud de referencia (AWS)** con **módulos OpenTofu por provider**; **ECS/Fargate descartado**; portabilidad real = **k3s+Helm+Zarf** v2 (mismo k8s en nube/on-prem/air-gap), documentado en spec y research. |
| **Cross-tenant en workspaces** (state/secretos compartidos entre clientes del distribuidor). | Alto — fuga de credenciales entre clientes. | Workspace + state + secretos **aislados** por cliente (III); naming derivado de `tenant.slug`; test de aislamiento. |
| **Air-gapped que igual pide pull** (imagen no incluida en el tarball). | Medio — install roto en host sin egress. | `bundle.sh` incluye **todas** las imágenes pinneadas del release; verificación `docker load` sin registry. |
| **Fuga del nombre del motor** en UI/errores/headers (gotcha del PoC browser-DLP). | Medio — rompe la marca blanca (VII). | Check de que ningún artefacto de marca blanca expone "litellm"/"LiteLLM" al usuario. |
| **Scope creep de licencias** (empezar a contar/validar licencias aquí). | Medio — invade la 021 y retrasa el MVP. | Sólo **hueco de entrada** (placeholder license key) sin enforcement; el enforcement es **spec 021**. |

## Complexity Tracking

> Sin violaciones de principio que justificar.

Esta feature **no introduce ninguna excepción constitucional**: honra VII (config+seed, never fork), IV
(client-as-data) y III (multi-tenant/aislamiento por cliente) **por diseño**. La única tensión potencial —
enforcement de licencias — se resuelve **excluyéndola de scope** (spec 021), no violando un principio. Por tanto
la tabla de complejidad queda **vacía a propósito**: cualquier PR que quiera hornear branding en el código
(fork), shippear un secreto default a prod, o contar licencias aquí **debe** justificarse como violación en esta
sección antes de mergear.
