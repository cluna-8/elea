# Basa Guardian — Guía de despliegue White-Label (runbook del distribuidor)

**Última actualización**: 2026-07-16 (§5.b postura de IP del artefacto — respuesta canónica)
**Audiencia**: el **modelo distribuidor** (partner que revende, instala, da training y soporte). NO es
una spec: es el runbook de **negocio + deploy** que usa el distribuidor para empaquetar, desplegar con
OpenTofu y licenciar Basa Guardian en la infraestructura del cliente final.
**Gobierna**: [`.specify/memory/constitution.md`](../.specify/memory/constitution.md) v2.0.0 — este
documento **materializa** los Principios **VII** (Containerized & White-Label: config+seed, never fork),
**III** (Multi-Tenant: el mismo código corre single-tenant on-prem y multi-tenant cloud), **IV** (Client
Onboarding as Data), **V** (Cost Governance) y **II** (Compliance / residencia EU). No inventa principios
nuevos.

> **Nota de honestidad SDD (léela antes que nada).** El proyecto distingue explícitamente lo
> **implementado hoy** de lo **forward-looking**. Este runbook hace lo mismo para el deploy: describe el
> **estado-objetivo** (cómo debe desplegarse en producción) y, en cada bloque, marca qué es real hoy y
> qué falta construir. No declara como hecho lo aspiracional — ese error hundió versiones previas del
> producto. **OpenTofu, imágenes de producción, secrets manager gestionado y el licenciamiento offline
> NO existen todavía en el repo**; son estado-objetivo. Lo que sí existe hoy es el stack Docker Compose
> dev/demo, el onboarding-as-data (seed por slug) y el bootstrap de admin. Ver la tabla de estado.

**Leyenda de estado** (se usa en todo el documento):

| Marca | Significado |
|---|---|
| 🟢 **HOY** | Implementado y verificable en el repo hoy |
| 🟡 **PARCIAL** | Existe la base, falta endurecerlo para producción |
| 🔵 **OBJETIVO** | Roadmap / estado-objetivo, no existe aún en el repo |

---

## 0. Estado actual vs objetivo (resumen ejecutivo)

| Pieza del deploy | Estado-actual (repo) | Estado-objetivo (producción cliente) | Estado |
|---|---|---|---|
| Orquestación | `docker-compose.yml` con 5 servicios (db, redis, litellm, backend, frontend) | Módulo OpenTofu + compose de producción (v1) / k3s+Helm+Zarf (v2) | 🟡 |
| Imágenes backend/frontend | Dev: `uvicorn --reload`, `npm run dev`, bind-mount del código fuente | Imágenes de producción multi-stage, sin reload, deps pinneadas, front servido estático | 🔵 |
| Imagen del motor | `ghcr.io/berriai/litellm` — **pinneada por tag+digest** en `basa-guardian`; `main-latest` (sin pin) en `gatelite`/`llm-guardian` | Pin por digest en todos los despliegues (Principio VI) | 🟡 |
| Base de datos / cache | Contenedores `postgres:16-alpine` / `redis:7-alpine` con volumen local | Postgres y Redis **gestionados** (RDS/Cloud SQL/Azure DB · ElastiCache/MemoryStore) | 🔵 |
| Secretos | `.env` en claro (con defaults inseguros en compose) | Secrets manager gestionado (AWS SM / GCP SM / Vault) **o SOPS/age** (cifrado sin servidor) para v1/air-gapped, inyectando env al arrancar | 🔵 |
| TLS + DNS | HTTP plano en puertos altos | TLS terminado — **Caddy (auto-TLS)** en v1, ALB/nginx en cloud — + DNS por cliente, región EU | 🔵 |
| Onboarding de cliente | `seed_clients_from_config(db, tenant_slug, path)` idempotente desde YAML | Igual, invocado por el flujo de instalación | 🟢 |
| Tenant por slug | Modelo `Tenant.slug` único; on-prem = 1 tenant (default `…0001`) | Igual; cloud = N tenants aislados por RLS | 🟢 / 🟡 (RLS es forward-looking) |
| Bootstrap de admin | Primer login `admin` crea `tenant_admin`; email `admin@basa.com.ar` | Igual + rotación de credencial obligatoria post-instalación | 🟡 (rotación sólo por SQL hoy) |
| Branding white-label | Naming neutro en código (`AIEngineClient`/`engine_*`, strip `litellm.*`) | Branding pack (nombre/logo/paleta) por cliente como **config-as-data en runtime** (sin recompilar) | 🟡 |
| Licenciamiento offline | Nada wireado (`cryptography==42.0.8` disponible, Ed25519 sin usar) | Licencia Ed25519 firmada, seat = Connection activa, sin phone-home | 🔵 (spec 021) |

---

## 1. El modelo de negocio

El producto se distribuye bajo un modelo **install + N licencias**, no SaaS operado por Basa:

- **Marca blanca.** El distribuidor revende Basa Guardian bajo su propia marca (o co-marca). Ningún
  nombre de motor o proveedor (LiteLLM, Anthropic, OpenAI, Azure, Presidio…) aparece en la UI, la API
  pública, los errores ni los logs — el código ya usa naming neutro (`AIEngineClient`/`engine_*`, strip
  de prefijos `litellm.*` → "Basa Gateway"). Esto es **Principio VII** y es 🟢 en el core; el branding
  visual (nombre de producto, logo, paleta) se aplica por cliente. Ver §2 (branding pack).
- **El distribuidor da training + soporte de nivel 1/2.** Es el dueño de la relación con el cliente
  final: instala, capacita, resuelve incidencias, escala a Basa sólo bug de producto.
- **Basa NO instala al cliente final ni opera servidores.** Basa no tiene infraestructura de cliente,
  no ve datos del cliente, no hace phone-home. Basa entrega **artefactos** (imágenes/tarball, branding
  pack, perfil, módulo OpenTofu, licencia) y el distribuidor/cliente los despliega.
- **El cliente levanta el stack donde quiera, con OpenTofu.** El cliente final es dueño de su
  infraestructura (su VPC, su cuenta cloud o su datacenter on-prem/air-gapped). El **mismo código** corre
  **single-tenant on-premise** (un tenant por instalación, apto para modelos locales Ollama/vLLM) y
  **multi-tenant cloud** — Principio III. El despliegue por cliente es **configuración + seed, nunca un
  fork** (Principio VII: el propio Basa Guardian nació de un fork que no debe repetirse).
- **Licencias = seats.** El contrato fija N seats. Un **seat = una Connection activa** (una `APIKey`
  con `is_active=True` por herramienta/persona). El enforcement de seats es offline y firmado (§5).

**Frontera de responsabilidad (quién hace qué):**

| Actor | Responsabilidad |
|---|---|
| **Basa** | Construye el producto, publica imágenes/tarball + branding pack + módulo OpenTofu + licencia firmada. No instala, no opera, no ve datos. |
| **Distribuidor** | Empaqueta el perfil del cliente, corre el despliegue (o acompaña al cliente), da training y soporte, gestiona licencias/seats. |
| **Cliente final** | Es dueño de su infra (cuenta cloud / datacenter), aplica el OpenTofu, custodia sus secretos y sus datos. |

---

## 2. Qué se entrega (deliverables)

Por cada cliente/despliegue, el distribuidor arma un paquete con:

1. **Imágenes de producción o tarball air-gapped.**
   - **Cloud con egress** → imágenes de producción publicadas en un registry que el cliente pueda `pull`
     (backend, frontend, y el motor pinneado por digest). 🔵 Estado-objetivo: **hoy las imágenes de
     `backend`/`frontend` son dev** (`Dockerfile` con `uvicorn --reload` / `npm run dev` y bind-mount del
     código). Producción exige imágenes multi-stage, sin reload, dependencias pinneadas y el frontend
     compilado servido como estático.
   - **On-prem / air-gapped (sin egress)** → **tarball** con todas las imágenes (`docker save` de db,
     redis, litellm@digest, backend, frontend) + checksums, para `docker load` en la máquina destino.
     El motor **debe ir pinneado por digest** para que el tarball sea reproducible. 🔵

2. **Branding pack.** Nombre de producto, logo, favicon, paleta y datos de contacto de soporte del
   distribuidor. Se aplica como **config-as-data en runtime** (el frontend carga la config de branding al
   arrancar, no se hornea en la imagen), nunca tocando código (Principios IV y VII). 🟡 El código ya es
   marca-neutro; el mecanismo de branding-por-config-en-runtime es lo que falta formalizar. El frontend ya
   resuelve la URL de API sola desde `window.location.hostname` (ver `frontend/src/services/api.ts`), así
   que no requiere recompilar por dominio.

3. **Perfil por cliente (onboarding-as-data).** 🟢 Es el corazón del "config+seed, never fork":
   - **`tenant`**: nombre + `slug` único + `deployment_mode` (`on_premise` | `cloud`) + defaults de
     contexto legal (`default_legal_basis`, `default_risk_level`) y de compresión.
   - **`config/clients.yaml`**: lista de clients (personas/herramientas) con sus Connections (una virtual
     key por `tool_type`), Budget en USD y toggles por-key (`redact_enabled`, `compression_mode`,
     `allowed_models`, `allowed_tools`, `rpm_limit`, `tpm_limit`, `upstream_mode`). Schema documentado en
     [`backend/config/clients.example.yaml`](../backend/config/clients.example.yaml). Sumar un cliente o
     un demo = **editar el YAML y correr el seed**, nunca tocar código (Principios IV y VII).

4. **Módulo OpenTofu.** 🔵 Estado-objetivo: **no existe en el repo hoy** (no hay `.tf`). El objetivo es
   un módulo parametrizado por cliente (VPC, DB/Redis gestionados, cómputo, secrets, TLS+DNS, región) —
   ver §3 y §4. Se usa **OpenTofu, no Terraform**: como el distribuidor **entrega el IaC a terceros** y la
   licencia de Terraform es **BSL** (HashiCorp/IBM), OpenTofu (fork MPL, drop-in, mismo `.tf` y `tofu
   apply`) evita el riesgo de licenciamiento en la redistribución. Hasta que exista, el despliegue se hace
   con el `docker-compose.yml` actual sobre una VM provisionada a mano (como en
   `llm-guardian/docs/DEPLOY_VPN.md`).

5. **Licencia firmada (Ed25519).** 🔵 Estado-objetivo (spec 021). Archivo de licencia offline que habilita
   N seats. Ver §5.

---

## 3. Arquitectura de despliegue objetivo

🔵 Salvo el stack de contenedores en sí (🟢), toda esta topología es **estado-objetivo**: hoy el repo se
levanta como 5 contenedores en una sola máquina (dev/demo). El objetivo de producción es:

```
                         ┌────────────────────── VPC del cliente (región EU) ──────────────────────┐
   DNS por cliente        │                                                                          │
  client.basa.example ──► │  ┌─────────────┐   TLS terminado    ┌───────────── cómputo ───────────┐  │
        (TLS)             │  │ LB / ingress │ ─────────────────► │ frontend (estático)             │  │
                         │  │ (ALB/Caddy)  │                    │ backend  (FastAPI)              │  │
                         │  └─────────────┘                    │ litellm  (motor, @digest pin)   │  │
                         │         │                            └──────────────┬──────────────────┘  │
                         │         │  secretos inyectados                      │                      │
                         │  ┌──────┴───────┐                    ┌──────────────┴───────┐              │
                         │  │ Secrets Mgr  │                    │ Postgres gestionado  │              │
                         │  │ (SM/Vault)   │                    │ Redis gestionado     │              │
                         │  └──────────────┘                    └──────────────────────┘              │
                         └──────────────────────────────────────────────────────────────────────────┘
```

Componentes:

- **Red**: VPC dedicada del cliente, subredes privadas para cómputo/datos, sólo el LB expuesto. Región
  **EU** por defecto (residencia de datos, Principio II). *Excepción acotada*: la ruta del firewall de
  coding tools (`base_url` clients) tiene **GDPR-routing = N/A** — no se fuerza endpoint EU en esa ruta,
  la garantía se traslada a masking/audit/allowlist (excepción ya ratificada del Principio II).
- **Datos gestionados**: **Postgres** (RDS / Cloud SQL / Azure DB) y **Redis** (ElastiCache / MemoryStore)
  gestionados en vez de los contenedores `postgres:16-alpine`/`redis:7-alpine` del compose. Backups y HA
  quedan del lado del proveedor gestionado.
- **Cómputo**:
  - **v1 (hoy portable)**: una VM (EC2/GCE/Azure VM) corriendo `docker compose` con el stack, con
    **Caddy** al frente (**auto-TLS**, sin ALB) y secretos con **SOPS/age** (cifrados en el
    artefacto/repo, **sin servidor** de secrets manager). Es el camino más corto y el que refleja el
    estado del repo. 🟡
  - **v2 (objetivo)**: **k3s + Helm + Zarf** con las imágenes de producción. **No ECS/EKS**: ECS Anywhere
    **no corre air-gapped** y el modelo de entrega es on-prem/air-gapped → k3s (Kubernetes liviano) + Helm
    (charts) + Zarf (empaquetado/registry air-gapped). 🔵
- **Secretos**: en cloud, un **secrets manager** (AWS Secrets Manager / GCP Secret Manager / HashiCorp
  Vault) provee `POSTGRES_PASSWORD`, `LITELLM_MASTER_KEY`, `FERNET_SECRET_KEY`, `JWT_SECRET_KEY` y las keys
  de proveedor, inyectadas como env al arrancar. En **v1 / air-gapped** (sin un secrets manager gestionado)
  la alternativa es **SOPS/age**: los secretos viajan **cifrados en el artefacto/repo** y se descifran al
  desplegar, **sin servidor**. En cualquier caso, **nunca** el `.env` en claro con los defaults inseguros
  del compose (`basasecurepass123`, `basa_master_key_9999`). Constraint C5 / Principio de encriptación:
  `FERNET_SECRET_KEY` cifra en reposo los secretos de servicio y el `oauth_credential_ref` de la ruta
  `subscription-passthrough` (ver `backend/src/services/encryption_service.py`). 🔵 (el secrets manager /
  SOPS es objetivo; Fernet en sí es 🟢).
- **TLS + DNS por cliente**: certificado + dominio propio del cliente terminando en el LB. 🔵

---

## 4. Flujo de instalación de punta a punta

Flujo **objetivo** (🔵 en su forma OpenTofu; los pasos de seed y bootstrap son 🟢 y se pueden correr hoy
a mano sobre el compose):

1. **`tofu apply`** con el `tfvars` del cliente (región EU, tamaños de DB/cómputo, dominio, `tenant`
   name+slug, `deployment_mode`). Provisiona VPC + Postgres/Redis gestionados + cómputo + secrets manager
   + TLS/DNS, y arranca el stack. 🔵
2. **Secretos generados, no hardcodeados.** OpenTofu / el secrets manager generan
   `POSTGRES_PASSWORD`, `LITELLM_MASTER_KEY`, `FERNET_SECRET_KEY`, `JWT_SECRET_KEY` (aleatorios, fuertes) y
   los inyectan como env. **Se descartan los defaults del compose.** 🔵
3. **Arranque + migraciones.** El backend corre `alembic upgrade head` al bootear (ver su `Dockerfile`),
   creando el esquema multi-tenant (013). El motor litellm corre sus migraciones de Prisma. ⚠️ En el
   **primer boot** el motor puede reportarse `unhealthy` por timeout aunque haya arrancado bien — ver §6.b.
4. **Seed del tenant por slug.** Se crea el `Tenant` (name + `slug` + `deployment_mode=on_premise` para
   instalaciones single-tenant; el default determinista es `…0001`, ver `backend/src/models/tenant.py`).
   El slug es la clave del despliegue por cliente (Principio VII). 🟢
5. **Seed de clients + branding.**
   - `seed_clients_from_config(db, tenant_slug="<slug>", path="config/clients.yaml")` siembra, de forma
     **idempotente**, cada persona/herramienta: `User role="client"` + N Connections (una `APIKey` por
     `tool_type`) + Budget, todo tenant-scoped. Devuelve las **keys en claro SÓLO de las Connections recién
     creadas** — se entregan una vez al cliente y no se pueden recuperar después (sólo queda el hash). 🟢
   - Se aplica el **branding pack** (config del frontend). 🟡
6. **Bootstrap de admin + rotación.** El primer login como `admin` crea un `tenant_admin` con la password
   que se envía en ese primer login (ver `backend/src/api/users.py`; el email es `admin@basa.com.ar` — el
   `.local` reservado rompía la validación, ver §6.c). **Rotar la credencial inmediatamente**: hoy **no hay
   endpoint de cambio de password**, así que la rotación es por SQL (§6.f); el endpoint es roadmap (spec
   017). 🟡
7. **Instalación de la licencia.** Se coloca el archivo de licencia Ed25519 que habilita los N seats
   contratados. 🔵 (spec 021).
8. **Smoke test post-deploy** (adaptado del checklist de `DEPLOY_VPN.md`):
   - `docker ps` → 5 contenedores `Up`/`healthy` (o los tasks equivalentes en v2).
   - `curl` a `/health/readiness` del motor → 200; a un endpoint del backend → 200.
   - Login como `admin` desde el navegador en la **URL/dominio real** (no `localhost`).
   - Apuntar `ANTHROPIC_BASE_URL` de un Claude Code a la ruta `/v1/messages` del motor con una virtual key
     sembrada → verificar bloqueo/masking; abrir `/monitor` y ver el before/after real.

---

## 5. Licenciamiento offline (resumen — ver spec 021)

🔵 **Estado-objetivo. Nada de esto está wireado hoy** (la primitiva `cryptography==42.0.8` está en el
backend, con soporte Ed25519, pero sin usar). Se resume acá para training/soporte y se especifica en
detalle en la **spec 021**.

> Nota de honestidad: el ROADMAP lista la spec **017 como "Auth hardening & Multi-Tenant RBAC + SSO"**
> (auth, no licenciamiento). El licenciamiento offline por seats se separó a su **propia spec, la 021**
> (licensing & seat enforcement), dentro del mismo tramo de endurecimiento de auth/gobernanza. Trátese como
> roadmap, no como capacidad entregable hoy.

Modelo:

- **Seat = Connection activa.** Un seat consumido = una `APIKey` con `is_active=True` para el tenant. El
  conteo de seats se deriva del propio esquema (013), no de un servicio externo.
- **Licencia Ed25519 firmada.** Basa firma con su clave privada un artefacto de licencia (tenant/slug,
  N seats, fecha de expiración, features habilitadas). El despliegue verifica la firma con la **clave
  pública** embebida — no puede falsificarse sin la privada de Basa.
- **Sin phone-home.** La verificación es **100% offline**: apta para on-prem y air-gapped. No hay llamada
  de vuelta a Basa, no se filtran datos de uso del cliente. Coherente con "Basa no opera servidores del
  cliente" (§1).
- **Enforcement blando/duro (a definir en 021).** El comportamiento al exceder seats o expirar la licencia
  (avisar vs bloquear altas de Connection) se especifica en 021.

### 5.b Postura de IP del artefacto — respuesta canónica a "¿qué protección tiene la imagen instalada?"

Pregunta recurrente del ciclo de venta on-prem (hospitales incluidos): *"el equipo de IT del cliente va a
abrir la imagen y mirar el código — ¿qué protección tienen?"*. Respuesta oficial de producto (decisión
documentada en [research 020, addendum 2026-07-16](../specs/020-whitelabel-deploy/research.md); usarla
tal cual en training y preventa — es postura, aplica hoy):

**Lo que se responde (tres capas):**

1. **La imagen copiada no trabaja.** El producto exige una licencia firmada (Ed25519, offline) atada al
   tenant: sin ella no arranca ni crea Connections (fail-closed, spec 021 🔵); moverla a otro sitio deja
   rastro verificable en la renovación (true-up firmado + auditoría hash-chained).
2. **El contrato es el ancla.** EULA vía distribuidor con no-reverse-engineering, no-redistribución y
   derechos de auditoría — el mismo modelo con el que operan GitLab EE (cuyo código enterprise es
   literalmente público), Grafana Enterprise o Metabase EE. El estándar on-prem del mercado es ese: el
   código se puede ver; usarlo sin licencia es incumplimiento contractual.
3. **El valor está en el stream, no en el código congelado.** Librería de compliance viva (AI Act,
   recognizers por región), parches, certificación y soporte del vendor. Una copia es un producto de
   compliance congelado, sin licencia ni respaldo — exactamente lo que un DPO de entorno regulado no
   puede firmar.

**El giro a favor**: que el hospital inspeccione la imagen es *bueno para la venta* — va a verificar que
el sistema **no exfiltra nada** (0 egress en air-gap, auditoría metadata-only, sin phone-home). La
transparencia de comportamiento es argumento de confianza; ofrecerla proactivamente (SBOM en v2 vía Zarf).

**Lo que NO se promete jamás**: código "protegido", "encriptado" u ofuscado como mecanismo de seguridad.
Técnicamente no existe en hardware del cliente (una imagen se abre con dos comandos; Python se
descompila) y prometerlo nos deja mal parados ante el primer pentest del propio cliente. Si el canal
pide "algo más", existe un pack de **fricción** opcional (imágenes sin fuentes/specs/tests, bytecode)
documentado en el research — se ofrece como prolijidad del artefacto, nunca como protección.

Todos verificados en despliegues reales (bitácora en
[`llm-guardian/docs/DEPLOY_VPN.md`](../../llm-guardian/docs/DEPLOY_VPN.md)) o en el código actual.

### a) On-prem sin egress: clonar/pull falla
En redes sin salida a Internet, `git clone` de GitHub devuelve **403** y `docker pull` no resuelve. Para
código, usar un **espejo** accesible desde esa red (Azure DevOps u otro). Para imágenes, entregar el
**tarball air-gapped** (`docker save`/`docker load`, §2). Recordar además que **el acceso a los
proveedores de LLM también requiere egress** salvo que se usen **modelos locales** (Ollama/vLLM) — en
air-gapped puro, el `model_list` debe apuntar sólo a modelos locales.

### b) `litellm` reportado `unhealthy` en el primer boot (no es un fallo)
En el primer arranque el motor tarda varios minutos (migraciones de Prisma/DB) y el timeout de espera del
healthcheck de `docker compose` puede agotarse **aunque el contenedor haya arrancado bien**. Verificar con
`docker logs <litellm>` (si dice "Application startup complete" y `/health/readiness` responde 200, está
sano). **Solución**: correr `docker compose up -d` **de nuevo** — como db/redis/litellm ya quedan
corriendo, la segunda pasada sólo levanta backend/frontend y es rápida.

### c) Bootstrap de admin con email `.local` rompe la pestaña de Usuarios
El bootstrap de admin usa un email hardcodeado. Con `admin@basa.local` (o cualquier TLD reservado
`.local`/`.test`/`.example`/`.invalid`), una versión reciente de `email-validator` (dependencia de
Pydantic) lo rechaza como inválido y devuelve **500** en cualquier respuesta que incluya la lista de
usuarios — rompía toda la pestaña "Usuarios & Presupuestos". **Corregido en código**
(`backend/src/api/users.py` usa `admin@basa.com.ar`). Para un deploy que **ya** tiene un admin con el email
viejo, corregir a mano en la base:
```bash
docker exec <db-container> psql -U <user> -d <db> \
  -c "UPDATE users SET email='admin@basa.com.ar' WHERE username='admin';"
```

### d) La consola web parte secretos/URLs de más de ~80 caracteres
Al pegar en una consola web (sin GUI) una URL o secreto de más de ~80 caracteres, la consola inserta un
**salto de línea real** en medio del texto, rompiendo la autenticación con un error confuso ("Malformed
input to a URL function" / "Authentication failed"). **Solución**: partir cualquier secreto/URL larga en
variables de shell cortas (≤25-30 chars cada una) en líneas separadas, y concatenarlas al usarlas:
```bash
P1="mitad1delaclave"
P2="mitad2delaclave"
echo "${P1}${P2}" | wc -c   # verificar longitud antes de usarla
```

### e) "Sin usuario" en el desglose de costos — no es un bug
El gasto se atribuye a una persona sólo cuando ésta tiene una **llave personal** en el motor, creada
automáticamente recién al asignarle un perfil de presupuesto (`_ensure_personal_key`). Las consultas
hechas **antes** de asignar presupuesto viajan con la llave maestra compartida y aparecen como "Sin
usuario". No es retroactivo. Explicarlo en training para no confundirlo con un fallo de atribución.

### f) No hay endpoint para cambiar la password de un usuario ya creado
Ni en UI ni en API se puede rotar la password de un usuario existente (sólo se define al crearlo). Hasta
que llegue el endpoint (spec 017), la rotación del admin post-instalación es por SQL:
```bash
docker exec <db-container> psql -U <user> -d <db> \
  -c "UPDATE users SET password_hash='<sha256-del-nuevo-valor>' WHERE username='admin';"
```
Este hueco es más relevante cuanta más gente tenga acceso a la red donde corre el stack — cerrarlo bien es
precisamente la spec 017 (auth hardening).

---

## 7. Mantenimiento: bump del motor (Principio VI)

La imagen del motor se **fija por tag+digest** (hoy 🟢 sólo en `basa-guardian`:
`ghcr.io/berriai/litellm:main-latest@sha256:80ea654…`; los repos demo aún usan `main-latest` sin pin).
Para actualizar el motor:

1. Cambiar el **digest** en el `docker-compose.yml` / módulo OpenTofu.
2. Correr la **suite de contract tests** (`tests/contract/`): firmas de los tres hooks del guardrail +
   `user_api_key_auth` + ejecución sobre `/v1/messages`.
3. Si pasa → commitear. Si falla → **no reescribir los hooks a ciegas**: investigar el cambio de firma del
   motor. **Actualizar el motor = correr tests, no reescribir** (Principio VI, No Patching).

---

## Referencias

- Constitución v2.0.0 — Principios VII, III, IV, V, II · Constraints C5 (secretos fuera de config) y C3
  (fail-closed): [`.specify/memory/constitution.md`](../.specify/memory/constitution.md)
- Onboarding-as-data: [`backend/src/services/onboarding.py`](../backend/src/services/onboarding.py) ·
  schema [`backend/config/clients.example.yaml`](../backend/config/clients.example.yaml)
- Modelo de tenant / slug: [`backend/src/models/tenant.py`](../backend/src/models/tenant.py)
- Firewall LiteLLM-native (ruta `/v1/messages`, passthrough OAuth): [`specs/014-litellm-native-firewall/`](../specs/014-litellm-native-firewall/)
- Bitácora de deploy real (gotchas): [`llm-guardian/docs/DEPLOY_VPN.md`](../../llm-guardian/docs/DEPLOY_VPN.md)
- Roadmap del core (specs 015–018; auth hardening/RBAC+SSO en 017): [`specs/ROADMAP-guardian.md`](../specs/ROADMAP-guardian.md). Licenciamiento/seats: **spec 021** (spec propia).
</content>
</invoke>
