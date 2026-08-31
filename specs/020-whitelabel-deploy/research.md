# Research T004 (Phase 0) — Build-vs-buy del deploy de marca blanca (020 White-Label Packaging & Deploy)

**Fecha**: 2026-07-13 · **Método**: revisión de prior-art público (docs oficiales de las herramientas,
anuncios de licencia, FAQs de AWS, guías de air-gap) cruzada con el shape del negocio (Sentinel entrega IaC a un
**distribuidor tercero**; el cliente levanta la instalación en su cuenta cloud u **on-prem/air-gap**; **una
instancia por cliente**). Cada eje trae **veredicto v1/v2** y **fuentes**. Corrige la hipótesis vieja
(Terraform + ECS/EKS + secrets manager cloud + branding build-time) que no aguanta el requisito air-gap ni el
de entregar IaC bajo una licencia sin fricción legal.

> ⚠️ Nota de alcance: este research **fija decisiones de arquitectura de empaquetado/deploy** (US1–US6). Lo
> marcado "v2" es roadmap explícito, no código entregado en esta feature. El principio rector: **portable,
> sin dependencia operativa de Sentinel, apto air-gap, sin deuda legal para el distribuidor**.

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

---

# Addendum 2026-07-14 — Validación prior-art del eje distribución (sweep de mercado)

Sweep web (28 vendors verificados) disparado por la pregunta del fundador: *"¿distribuir por imágenes
Docker + clave paga es un modelo probado? ¿ya hay gente haciéndolo?"*. Resultado para esta spec:

- **El modelo comercial es mainstream**: **Replicated** (la categoría entera productizada: apps de ISVs
  como imágenes + air-gap bundles), **GitLab EE** (`gitlab/gitlab-ee` + license file offline), **Grafana
  Enterprise** (`grafana-enterprise` + `license.jwt`), **Directus**, **Harbor**, **Mattermost**, etc.
- **Tarball `docker save`/`load` VALIDADO como el estándar air-gap** (eje 4 sin cambios): **Harbor**
  (offline installer `.tgz` con todas las imágenes adentro, cero pulls), **GitLab** (flujo oficial
  offline: bajar imágenes en una máquina con red, empaquetar, transferir), **Replicated** (air-gap
  bundle = `.tar` con `images/` + `airgap.yaml`).
- **Registry privado con auth (GHCR / Docker Hub privado / Red Hat) es el default del mercado para
  clientes CONECTADOS — pero como gate de pago es DÉBIL**: tras el primer pull, un `docker save` lo
  convierte en un tarball que corre sin re-verificar nada. Controla la **distribución inicial**, no
  protege IP ni desbloquea features. El gate útil es el de **runtime** (la licencia firmada de la 021,
  que esta spec inyecta como config), no el de registry. Nuestro descarte del registry como enforcement
  queda **confirmado**, no contradicho.
- **Watch-item v2 (aditivo, NUNCA enforcement)**: para distribuidores conectados, un registry privado
  autenticado como **canal de entrega/actualización** cómodo (cf. Replicated Download Portal, Harbor
  online installer). El tarball sigue siendo el default air-gap; la licencia 021 sigue siendo el único
  mecanismo de pago. No se necesita para v1.
- Contra-ejemplo instructivo: **Metabase** valida su token ONLINE por default y trata el air-gap como un
  producto aparte negociado con ventas — esta spec arranca donde ellos hacen una excepción comercial
  (air-gap first-class, no add-on).

**Relación con la 021 (tier distribuidor)**: el addendum de la 021 fija la emisión **central por cupo**
(portal de Sentinel; `distributor_id`/`pool_id` en el `.lic`). Para esta spec hay **dos puntos de contacto**:
(1) el `.lic` sigue entrando como config del artefacto (secret/fichero montado), venga del canal que
venga — sin cambios; (2) **NUEVO** — el artefacto de deploy provisiona un **volumen/secret persistente**
para la **clave privada del deployment** (par Ed25519 generado en el **install**, que firma los exports
de true-up de la 021/FR-029; encaja con "secretos por instalación" D5). El registro de la clave pública
del deployment ocurre en el onboarding, fuera de la caja.

---

# Addendum 2026-07-16 — Postura de IP del artefacto ("¿qué protección tiene la imagen instalada?")

Disparador: pregunta real de cliente en conversaciones on-premise (vía daily, reportada por Cristian):
*"cuando instalemos esto en un hospital, el equipo de IT del cliente va a tratar de ver el código y todo
lo demás — ¿qué protección tenemos para esa imagen / ese sistema compilado?"*. Es de las primeras
preguntas del ciclo de venta on-prem → merece decisión documentada y respuesta canónica (runbook §5).

## Verdad técnica (base de la decisión)

Código que corre en hardware del cliente **no es protegible criptográficamente**: una imagen Docker se
abre con `docker save` + untar; Python (aun compilado a bytecode `.pyc`) se descompila con tooling
público; la ofuscación (PyArmor) y la compilación (Nuitka/Cython) son **fricción de días, no seguridad**.
Cualquier promesa de "código protegido" on-prem es falsa y un pentest del propio hospital la desmonta —
mismo criterio de honestidad que la 021 aplicó al anti-tamper (el ancla es el contrato, no la cripto).

## Prior-art (cómo lo resuelve el mercado que ya validamos en el sweep 2026-07-14)

- **GitLab EE**: el código enterprise es **source-available público** — cualquiera lo lee; usarlo sin
  licencia es ilegal. Factura miles de millones así. La protección es licencia + contrato, no secreto.
- **Grafana Enterprise / Metabase EE / Directus**: binarios y JARs perfectamente inspeccionables y
  descompilables en el host del cliente; el gate es `license.jwt`/token + EULA.
- **Replicated** (distribuye apps de ISVs en air-gap, nuestro caso exacto): cero ofuscación como
  producto; su modelo es empaquetado + licencia + contrato.

**Estándar del mercado on-prem: el código se ve; el negocio se protege por licencia + contrato + stream
de valor.** Nadie serio vende ofuscación como protección.

## Decisión

1. **NO adoptamos ofuscación como estrategia de protección** (ni se promete al canal). La protección
   real del artefacto instalado tiene tres capas:
   - **Licencia (021)**: la imagen copiada **no trabaja** sin `.lic` firmada — gates fail-closed en
     arranque y creación de Connections; la licencia está atada a `tenant_id` (llevarla a otro sitio
     deja rastro en el true-up firmado + audit hash-chained en renovación).
   - **Contrato/EULA** (vía distribuidor): no-reverse-engineering, no-redistribución, derechos de
     auditoría, true-up anual. **El ancla — igual que en la 021.**
   - **Stream de valor**: librería de compliance viva (AI Act, recognizers por región), parches,
     certificación y soporte del vendor. Una copia del código es un producto de compliance **congelado y
     sin respaldo** — inasumible para un DPO en entorno regulado. Ahí vive el moat, no en el secreto.
2. **La inspeccionabilidad del comportamiento es argumento de venta, no debilidad**: el hospital va a
   auditar la imagen también para verificar que NO exfiltra (0 egress, air-gap, metadata-only audit).
   Transparencia de comportamiento = confianza (patrón GitLab).
3. **Pack de fricción (opcional, candidato a task cuando la 020 entre en plan/tasks — NUNCA vendido
   como seguridad)**: las imágenes de producción multi-stage (ya estado-objetivo de US1) además
   **excluyen fuentes no necesarias, `specs/`, docs internos y tests**; opcional: distribuir sólo
   bytecode (`.pyc`) y evaluar Nuitka/PyArmor **sólo** para el módulo de verificación de licencia.
   Etiquetado interno honesto: sube el costo de curiosear de 2 comandos a unos días.

**Relación con la 021**: esta postura es la extensión natural de su addendum ("el contrato es el ancla,
no la criptografía") aplicada al artefacto completo. **Runbook**: respuesta canónica para el canal en
`docs/whitelabel-deployment.md` §5 (qué decir — y qué NO prometer — cuando el cliente pregunta).
