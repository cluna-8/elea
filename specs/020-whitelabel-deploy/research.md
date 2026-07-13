# Research T004 (Phase 0) — Build-vs-buy del deploy de marca blanca (020 White-Label Packaging & Deploy)

**Fecha**: 2026-07-13 · **Método**: revisión de prior-art público (docs oficiales de las herramientas,
anuncios de licencia, FAQs de AWS, guías de air-gap) cruzada con el shape del negocio (Basa entrega IaC a un
**distribuidor tercero**; el cliente levanta la instalación en su cuenta cloud u **on-prem/air-gap**; **una
instancia por cliente**). Cada eje trae **veredicto v1/v2** y **fuentes**. Corrige la hipótesis vieja
(Terraform + ECS/EKS + secrets manager cloud + branding build-time) que no aguanta el requisito air-gap ni el
de entregar IaC bajo una licencia sin fricción legal.

> ⚠️ Nota de alcance: este research **fija decisiones de arquitectura de empaquetado/deploy** (US1–US6). Lo
> marcado "v2" es roadmap explícito, no código entregado en esta feature. El principio rector: **portable,
> sin dependencia operativa de Basa, apto air-gap, sin deuda legal para el distribuidor**.

## Resumen

- **IaC = OpenTofu, NO Terraform.** Terraform es **BSL** desde 2023 y HashiCorp es ahora **IBM**; entregar IaC
  bajo BSL a un **distribuidor** que la revende es deuda legal evitable. OpenTofu es el fork **MPL 2.0** bajo
  **CNCF**, **drop-in** sobre los mismos `.tf` → migración de coste ~cero, sin ceder terreno funcional.
- **Cómputo v1 = VM + docker compose (cloud-init); v2 = k3s + Helm + Zarf.** Se **descarta ECS/Fargate**: es
  AWS-only y **ECS Anywhere NO corre air-gapped** (exige conexión permanente al control plane de AWS
  in-region) → viola el requisito on-prem/air-gap de raíz.
- **Portabilidad real = módulos OpenTofu por provider (infra base) + k3s (v2).** k3s da el **mismo Kubernetes**
  en nube, on-prem y air-gap; ése es el valor, no un "multi-cloud mágico". k8s **solo por portabilidad** no se
  justifica para nube pura.
- **Air-gap v1 = tarball `docker save`/`load`; v2 = Zarf** (airgap-native para k8s, SBOM + firma cosign).
  **Replicated** se evalúa si el volumen de distribuidores crece.
- **App server v1 = uvicorn workers o gunicorn+UvicornWorker** (aburrido y probado); **granian** = optimización
  opcional.
- **Proxy/TLS v1 = Caddy** (auto-HTTPS, config mínima); **v2 = Traefik** (ingress default de k3s).
- **Branding = config-as-data en runtime** (env + assets montados), **una marca por instancia**. NO build-time,
  NO theming multi-tenant dinámico (hay una instancia por cliente: no hace falta).
- **Secretos v1 = SOPS + age; v2 = OpenBao.** Se **descartan los secrets managers cloud como base** (atan a una
  nube, no existen en air-gap). OpenBao es el fork **MPL** de Vault (Vault es BSL).

---

## Tabla de decisión por eje

| Eje | Descartado (y por qué) | v1 (MVP) | v2 (roadmap) |
|---|---|---|---|
| **IaC** | **Terraform** — BSL 2023 + HashiCorp = IBM; deuda legal al entregar a distribuidor | **OpenTofu** (MPL 2.0, CNCF, drop-in `.tf`) | OpenTofu (mismo) |
| **Cómputo** | **ECS/Fargate** — AWS-only; **ECS Anywhere no corre air-gapped** | **VM + docker compose** (cloud-init) | **k3s + Helm + Zarf** |
| **Portabilidad** | "multi-cloud mágico" en HCL; k8s por moda | **módulos OpenTofu por provider** | **k3s** = mismo k8s nube/on-prem/air-gap |
| **Air-gap** | pull de registry en runtime | **tarball** `docker save`/`load` | **Zarf** (SBOM + cosign); Replicated si escala |
| **App server** | uvicorn `--reload` (dev) | **uvicorn workers** / **gunicorn+UvicornWorker** | granian (opcional) |
| **Proxy/TLS** | ALB+ACM (AWS-only), vite dev | **Caddy** (auto-HTTPS) | **Traefik** (default k3s) |
| **Branding** | build-time baking; theming multi-tenant dinámico | **config-as-data runtime** (env + assets), 1 marca/instancia | igual |
| **Secretos** | secrets managers cloud como base; **Vault** (BSL) | **SOPS + age** (sin server, air-gap) | **OpenBao** (fork MPL de Vault) |

---

## (1) IaC — Terraform vs OpenTofu → **OpenTofu**

Terraform pasó de MPL a **BSL 1.1** en agosto 2023; en 2024 HashiCorp fue **adquirida por IBM**. Para un
producto que **entrega los `.tf` a un distribuidor tercero** (que a su vez los aplica en cuentas de clientes
finales), la BSL introduce una zona gris de "uso competitivo/producción de terceros" que es **deuda legal
evitable**. **OpenTofu** es el fork dirigido por la comunidad, licencia **MPL 2.0**, aceptado en la **CNCF**, y
**drop-in**: consume los mismos `.tf`/HCL, mismos providers, mismo state → el coste de adopción es ~cero y no se
pierde funcionalidad. El directorio del módulo se conserva como `deploy/terraform/` (los archivos siguen siendo
`.tf`; OpenTofu los lee sin cambios).

**Veredicto v1/v2**: **OpenTofu** en ambas. Se documenta el porqué (BSL) para que ningún PR "vuelva a Terraform
por costumbre".

**Fuentes**:
- https://opentofu.org/manifesto/
- https://spacelift.io/blog/terraform-license-change
- https://www.cncf.io/projects/opentofu/

## (2) Cómputo — ECS/Fargate vs VM+compose vs k3s → **VM+compose (v1), k3s+Helm+Zarf (v2)**

**ECS/Fargate se descarta**: además de ser **AWS-only** (rompe portabilidad y ata al distribuidor a una nube),
**ECS Anywhere NO funciona air-gapped**: el agente **exige conexión saliente permanente** al control plane de
**Amazon ECS in-region** para registrar y operar las instancias externas. En un cliente on-prem sin egress
(caso Elea) eso **rompe el install de raíz**. La ruta realista y entregable ya es **VM + docker compose por
cloud-init** desde las imágenes de US1 (v1). Para el salto a orquestación, **k3s** (Kubernetes ligero,
single-binary, apto air-gap) + **Helm** (packaging) es el v2: mismo runtime en nube, on-prem y air-gap.

**Veredicto v1/v2**: **v1 = VM + docker compose (cloud-init)**; **v2 = k3s + Helm** (+ Zarf para air-gap, ver
eje 4). **ECS/Fargate = NO** (air-gap-incompatible).

**Fuentes**:
- https://aws.amazon.com/ecs/anywhere/faqs/
- https://oneuptime.com/blog
- https://docs.k3s.io/installation/airgap

## (3) Portabilidad — ¿multi-cloud o mismo-k8s? → **módulos por provider + k3s (no "multi-cloud mágico")**

La portabilidad **no** se compra escribiendo HCL "genérico" que corra en AWS/GCP/Azure sin tocar nada — eso es
un mito que infla el alcance. Se compra de dos formas concretas: (a) **módulos OpenTofu por provider** para la
infra base (red/DB/cache/DNS), abstraídos por recurso, con un cloud de referencia (AWS) en v1; y (b) **k3s**
como capa de cómputo v2, que entrega el **mismo Kubernetes** en cualquier sustrato (nube, on-prem, air-gap). El
valor real es ese "mismo k8s en todos lados", no un multi-cloud simultáneo. Corolario: **adoptar k8s solo por
portabilidad NO se justifica para un cliente de nube pura** — ahí VM+compose alcanza.

**Veredicto v1/v2**: **v1** = módulos OpenTofu por provider (AWS de referencia); **v2** = k3s como sustrato
portable. GCP/Azure = paridad roadmap, no promesa MVP.

**Fuentes**:
- https://docs.k3s.io/
- https://opentofu.org/docs/language/modules/

## (4) Air-gap — tarball vs Zarf → **tarball (v1), Zarf (v2)**

**v1** empaqueta el release como **tarball** (`docker save` de todas las imágenes pinneadas + `config.yaml` +
seed) que se instala con `docker load` **sin acceso a registry en runtime** — suficiente para VM+compose
on-prem. Para el mundo **k8s v2**, el estándar airgap-native es **Zarf**: crea bundles declarativos con
**SBOM** y **firma cosign**, incluye un registry interno y despliega charts/imagenes sin egress. **Replicated**
(entrega/licenciamiento de apps k8s a terceros) es la opción "buy" a **evaluar si el volumen de distribuidores
crece** y el soporte de N instalaciones se vuelve carga operativa.

**Veredicto v1/v2**: **v1 = tarball `docker save`/`load`**; **v2 = Zarf** (SBOM+cosign). Replicated =
watch-item, no MVP.

**Fuentes**:
- https://docs.docker.com/reference/cli/docker/image/save/
- https://zarf.dev/
- https://www.replicated.com/

## (5) App server — uvicorn/gunicorn vs granian → **uvicorn workers / gunicorn+UvicornWorker (v1)**

El backend es FastAPI/ASGI. La opción **aburrida y probada** es correr **uvicorn con workers** o **gunicorn con
`UvicornWorker`** (proceso maestro + N workers, sin `--reload`, non-root). **granian** (server ASGI/RSGI en
Rust) es una **optimización opcional** de throughput/memoria, no un requisito v1: se deja como palanca si el
perfil de carga lo pide.

**Veredicto v1/v2**: **v1 = uvicorn workers o gunicorn+UvicornWorker**; **granian = opcional**.

**Fuentes**:
- https://www.uvicorn.org/deployment/
- https://github.com/emmett-framework/granian

## (6) Proxy/TLS — Caddy vs Traefik vs ALB+ACM → **Caddy (v1), Traefik (v2)**

**ALB+ACM se descarta como base** por ser AWS-only (rompe portabilidad/on-prem). **Caddy** da **HTTPS
automático** (ACME/Let's Encrypt) con configuración mínima y sirve los estáticos del frontend + termina TLS en
pocas líneas → ideal para VM+compose v1. En el mundo k8s v2, **Traefik** ya es el **ingress por defecto de
k3s**, así que se adopta ahí sin fricción.

**Veredicto v1/v2**: **v1 = Caddy** (auto-HTTPS); **v2 = Traefik** (viene con k3s).

**Fuentes**:
- https://caddyserver.com/docs/automatic-https
- https://docs.k3s.io/networking/networking-services

## (7) Branding — build-time vs runtime → **config-as-data en runtime, 1 marca por instancia**

El modelo es **una instancia por cliente**: no hay multi-tenant de marca dentro de una misma instancia, así que
**no se necesita** theming dinámico ni build-time baking (que forzaría un **rebuild por distribuidor** — coste
y deriva). El branding (nombre, logo, colores, dominio, soporte) se inyecta como **config-as-data en runtime**:
**variables de entorno** + **assets montados** (logo/colores) que el frontend (bundle **marca-neutro**) y el
metadata del backend leen al arrancar. Cambiar de marca = cambiar env + assets y **reiniciar**, **sin tocar
código ni reconstruir imagen**.

**Veredicto v1/v2**: **runtime config-as-data** en ambas; una marca por instancia; sin build-time, sin theming
multi-tenant.

**Fuentes**:
- https://12factor.net/config

## (8) Secretos — secrets manager cloud vs SOPS+age vs OpenBao → **SOPS+age (v1), OpenBao (v2)**

Los **secrets managers cloud** (AWS Secrets Manager/SSM, etc.) **no sirven como base**: **atan a una nube** y
**no existen en air-gap**. **SOPS + age** cifra los secretos **at-rest** (en el repo/artefacto del perfil) sin
ningún servidor: es **portable, simple y apto air-gap** — encaja con "entregamos artefactos, no operamos
infra". Si un distribuidor pide un **store central** (rotación, políticas), el v2 es **OpenBao**: el fork
**MPL** de Vault gobernado por la Linux Foundation (**Vault es BSL** → mismo problema legal que Terraform, se
evita). Los `random_password` de OpenTofu se generan por instalación, se marcan `sensitive` y se cifran con
SOPS/age; nada en `tfvars`/state/logs en claro (Constraint C5).

**Veredicto v1/v2**: **v1 = SOPS + age**; **v2 = OpenBao** (si piden store central). Secrets managers cloud =
NO como base.

**Fuentes**:
- https://github.com/getsops/sops
- https://github.com/FiloSottile/age
- https://openbao.org/

---

## Recomendación integrada (v1 entregable / v2 roadmap)

- **v1 (MVP entregable-a-distribuidor)**: **OpenTofu** (módulos por provider, AWS de referencia) provisiona VPC
  (443-only + NAT) + Postgres/Redis (gestionados en nube o en contenedor durable on-prem) + **cómputo VM +
  docker compose (cloud-init)** desde imágenes prod pinneadas; **Caddy** termina TLS (auto-HTTPS) sobre el DNS
  derivado del `tenant.slug`; **backend con uvicorn workers/gunicorn+UvicornWorker**; **branding config-as-data
  en runtime** (env + assets, marca-neutro por defecto); **secretos con SOPS+age**, generados por instalación;
  **air-gap por tarball** (`docker save`/`load`). Región **EU** por defecto.
- **v2 (roadmap explícito)**: **k3s + Helm** como sustrato portable (mismo k8s nube/on-prem/air-gap),
  **Traefik** de ingress, **Zarf** para air-gap (SBOM+cosign), **OpenBao** si se pide store central de
  secretos; **granian** como optimización opcional del app server; **Replicated** a evaluar si el volumen de
  distribuidores exige una plataforma de entrega/licenciamiento k8s.

## Riesgos y mitigaciones

| Riesgo | Impacto | Mitigación |
|---|---|---|
| **Volver a Terraform "por costumbre"** en un PR. | Reintroduce deuda legal BSL en el entregable. | Decisión documentada (este research); OpenTofu es drop-in → sin excusa técnica. |
| **Elegir ECS/Fargate por familiaridad AWS.** | Rompe air-gap (ECS Anywhere exige control plane in-region). | v1 VM+compose; v2 k3s; ECS marcado **NO** en spec/FR-018. |
| **Overselling multi-cloud** (HCL "genérico"). | Alcance infla y no se entrega. | Módulos por provider + k3s como portabilidad real; GCP/Azure = paridad roadmap. |
| **Secreto en air-gap sin store cloud.** | Un secrets manager cloud dejaría al cliente on-prem sin secretos. | SOPS+age (sin server, at-rest) como base; OpenBao (v2) para central. |
| **Vault (BSL) como "el estándar".** | Repite el problema legal de Terraform. | OpenBao (fork MPL) como única vía de store central. |
| **Branding build-time.** | Rebuild por distribuidor + deriva de imagen. | Config-as-data runtime (env + assets), bundle marca-neutro, 1 marca/instancia. |
| **Tarball incompleto en air-gap.** | Un `@sha256` ausente fuerza pull y rompe el install. | El bundle incluye **todas** las imágenes pinneadas; check `docker load` sin registry (US6). |
