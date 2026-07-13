# Feature Specification: White-Label Packaging & Deploy

**Feature Branch**: `020-whitelabel-deploy`

**Created**: 2026-07-13

**Status**: Draft

**Input**: User description: "Empaquetar Basa Guardian para el modelo de negocio real: Basa cobra INSTALL + X
licencias y vende a un DISTRIBUIDOR (marca blanca) que garantiza training+soporte. Basa NO instala a cliente
final y NO tiene servidores: se entrega **OpenTofu** para que el cliente lo levante donde quiera. Requiere (1)
Dockerfiles de PRODUCCIÓN + imágenes/bundle, (2) branding pack como CONFIG (no fork), (3) perfil por cliente como
artefacto (env+seed+branding+config templado), (4) módulo OpenTofu portable (VPC/Postgres/Redis/secrets/TLS/región
EU), (5) secretos generados por instalación (sin defaults), (6) modo air-gapped/tarball on-prem sin egress. El
enforcement de licencias es otra spec (021) — se referencia, no se desarrolla acá."

---

## Contexto y honestidad SDD *(léelo antes que nada)*

Esta feature es **mayormente greenfield (roadmap)**. Hay que decirlo con todas las letras: **hoy TODO es
dev-mode y hay CERO Infrastructure-as-Code**. Nada de lo que esta spec propone (Dockerfiles de producción,
branding como config, perfil por cliente empaquetado, módulo OpenTofu, secretos por instalación, bundle
air-gapped) existe. Lo que existe es:

- **Dockerfiles de DESARROLLO.** `backend/Dockerfile` es single-stage sobre `python:3.12-slim`, corre
  `alembic upgrade head && uvicorn --reload` como **root**, mantiene `build-essential` en la imagen final y no
  tiene healthcheck. `frontend/Dockerfile` corre `npm run dev -- --host` (vite **dev server**, sin `build`,
  sin estáticos, sin Caddy/nginx) como root.
- **`docker-compose.yml` de desarrollo.** Bind-mounts del **código fuente** en caliente (`./backend:/app`,
  `./frontend:/app`, `./litellm/config.yaml`, `./litellm/extensions`), `pgdata` en un **volumen docker
  efímero**, **sin TLS**, y **secretos default hardcodeados** en el propio compose
  (`POSTGRES_PASSWORD=${POSTGRES_PASSWORD:-basasecurepass123}`,
  `LITELLM_MASTER_KEY=${LITELLM_MASTER_KEY:-basa_master_key_9999}`). La imagen de LiteLLM **sí** está pinneada
  por digest (herencia de la 014, Principio VI), pero el tag sigue siendo `main-latest`.
- **Cero IaC** (no hay `.tf`, ni Helm, ni manifiestos k8s, ni CloudFormation) y **cero CI/CD**.
- **Único deploy real documentado**: `llm-guardian/docs/DEPLOY_VPN.md` — `git clone` + `docker compose up` en
  una VM de la VPN (Elea), on-prem, a veces **sin egress** a proveedores externos.

El objetivo de la 020 es convertir eso en un **producto empaquetable de marca blanca** que **el DISTRIBUIDOR
levanta donde quiera con OpenTofu**, respetando el Principio VII (**Containerized & White-Label**, config+seed
**never fork**), el Principio IV (**Client Onboarding as Data**) y el Principio III (**Multi-Tenant by Design**,
`tenant.slug` → dominio/DNS por cliente). Esta spec es **explícita** sobre qué es **estado actual** vs qué es
**roadmap a construir**, y sobre qué **REUSA** del bedrock ya implementado:

- **REUSA (ya existe, no se rediseña):** el `seed_client(tenant, client_spec)` idempotente y el `tenant.slug`
  de la **013** (onboarding-as-data); la imagen LiteLLM pinneada por digest, el `config.yaml` y el volumen
  `litellm/extensions` de la **014**; los servicios y modelos del backend.
- **A CONSTRUIR (greenfield, esta spec):** Dockerfiles de producción + publicación/bundle de imágenes; el
  **branding pack** como config; el **perfil por cliente** como artefacto; el **módulo OpenTofu portable**; la
  **generación de secretos por instalación**; el **modo air-gapped**.

**Modelo de negocio (contexto central).** Basa cobra **INSTALL + X licencias** y vende a un **DISTRIBUIDOR** de
marca blanca que garantiza **training + soporte** al cliente final. **Basa NO instala al cliente final y NO
opera servidores**: entrega el **OpenTofu** (+ imágenes/bundle + perfil) para que el cliente lo levante en su
propia cuenta cloud / on-prem. Esto define el shape del entregable: **portable, parametrizable por cliente, sin
dependencia operativa de Basa**.

**Alcance honesto.** Esta spec cubre el **empaquetado y el deploy**. **NO** implementa el **enforcement de
licencias** (contar/expirar/validar las X licencias vendidas) — eso es la **spec 021 (license enforcement)**,
que esta spec sólo **referencia** dejando el hueco de entrada (placeholder de license key) sin cablearlo. **NO**
activa Presidio NLP real (esa es otra spec del roadmap). **NO** rediseña el schema multi-tenant (viene de 013)
ni el firewall (viene de 014). Depende del **bedrock 013** (`tenant.slug`, `seed_client`) y de la **014**
(imagen pinneada, `config.yaml`, extensiones).

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Dockerfiles de producción + imágenes/bundle publicables (Priority: P1)

El distribuidor no puede desplegar `uvicorn --reload` con bind-mounts de código y un vite dev server en un
cliente que paga. Esta story reemplaza los Dockerfiles de desarrollo por **imágenes de producción
autocontenidas**: backend **multistage** (compila deps en una etapa, imagen final slim **sin toolchain**,
`gunicorn`/`uvicorn workers` **sin `--reload`**, usuario **non-root**, healthcheck, base pinneada por digest);
frontend con `vite build` → **estáticos** servidos por **Caddy/nginx** (no vite dev), non-root. El código se
**hornea** en la imagen (sin bind-mounts de fuente). Las imágenes se **publican pinneadas** en un registry
(tag+digest, mismo patrón que la 014) **o** se exportan como **tarball** para air-gapped.

**Why this priority**: Sin imágenes de producción no hay producto que entregar; todo lo demás (OpenTofu,
perfil, branding) monta sobre estas imágenes. Materializa el Principio VII (containerized, reproducible).

**Independent Test**: Buildear las imágenes de producción y verificar: (a) el backend corre **sin `--reload`**,
como **non-root**, sin `build-essential` en la capa final, con healthcheck; (b) el frontend sirve **estáticos**
(no hay proceso vite dev), non-root; (c) ninguna imagen bind-montea código fuente; (d) ambas están pinneadas
por tag+digest o exportadas como tarball reproducible.

**Acceptance Scenarios**:

1. **Given** el `backend.prod.Dockerfile` multistage, **When** se buildea la imagen, **Then** la capa final
   no contiene `build-essential`/toolchain, el proceso arranca con workers de gunicorn/uvicorn **sin
   `--reload`**, corre como usuario non-root y expone un healthcheck.
2. **Given** el `frontend.prod.Dockerfile`, **When** se buildea, **Then** ejecuta `vite build` y sirve los
   estáticos vía Caddy/nginx (no `npm run dev`), como non-root.
3. **Given** las imágenes de producción, **When** se inspeccionan, **Then** el código fuente está **horneado**
   (no hay bind-mount de `./backend`/`./frontend` como en el compose de dev).
4. **Given** el pipeline de release, **When** se publica, **Then** las imágenes quedan pinneadas por tag+digest
   en el registry **o** exportadas como tarball (`docker save`) para el camino air-gapped (US6).

---

### User Story 2 - Branding pack como CONFIG, no fork (Priority: P1)

El distribuidor vende el producto con **su** marca: nombre, logo, colores, dominio, contacto de soporte. Esta
story hace que ese branding sea **config-as-data en runtime** — **env + assets montados** cuando la instancia
arranca, **no build-time** y **no theming multi-tenant dinámico** — **una marca por instancia** (hay **una
instancia por cliente**, no hace falta más). Es **configuración inyectable**, **no un fork del código**
(Principio VII: config+seed **never fork**). Un cambio de marca **no debe tocar una línea de código fuente**
**ni rebuildear la imagen**. Además, el motor upstream (**LiteLLM**) **nunca se nombra** en la UI ni en los
artefactos de marca blanca (mandato constitucional del Principio VII).

**Why this priority**: La marca blanca es el corazón del modelo de negocio (el distribuidor revende como
propio). Sin branding-as-config, cada distribuidor implicaría un fork — exactamente lo que la constitución
prohíbe. P1 porque define el entregable como producto revendible.

**Independent Test**: Tomar el branding pack por defecto (Basa-neutro), sustituirlo por el de un distribuidor
ficticio (nombre/logo/colores/dominio vía **env + assets montados**, sin rebuild) y verificar: (a) la UI y los
metadatos del backend reflejan la nueva marca **sin editar código ni rebuildear**; (b) un `grep` de los
artefactos de marca blanca **no** encuentra la cadena "litellm"/"LiteLLM" expuesta al usuario.

**Acceptance Scenarios**:

1. **Given** un branding pack (nombre, logo, colores, dominio, soporte), **When** se monta en runtime sobre el
   frontend (env + assets) y el metadata del backend, **Then** el producto muestra la marca del distribuidor
   **sin ningún cambio de código fuente ni rebuild de imagen**.
2. **Given** el producto de marca blanca corriendo, **When** se inspecciona la UI y las respuestas visibles,
   **Then** el motor upstream (LiteLLM) **no aparece nombrado** en ninguna parte.
3. **Given** ausencia de branding pack del distribuidor, **When** se despliega, **Then** cae al branding
   **por defecto** (Basa-neutro) como fallback documentado, sin romper.
4. **Given** un segundo distribuidor con otro pack, **When** se despliega su instalación, **Then** ambas marcas
   coexisten desde **el mismo código** parametrizado (dos configs, un solo codebase).

---

### User Story 3 - Perfil por cliente empaquetado (env + seed + branding + config templado) (Priority: P1)

Levantar un cliente nuevo debe ser **rellenar un artefacto**, no editar el producto. Esta story define el
**perfil de cliente** como un artefacto declarativo = **env** (endpoints, región, flags) + **seed**
(onboarding-as-data reusando `seed_client` de la 013) + **branding pack** (US2) + **`config.yaml` templado**
(model_list/proveedores/keys/región inyectados por cliente, no horneados). El perfil se ata al **`tenant.slug`**
de la 013 para el dominio/DNS y el nombre de workspace.

**Why this priority**: Es el pegamento entre el producto (US1/US2) y el deploy (US4). Sin un perfil como
artefacto, cada cliente implicaría tocar el `config.yaml` a mano o forkear — violando IV y VII. P1 porque hace
que "onboardear un cliente" sea un dato, no una release.

**Independent Test**: Definir el perfil de un cliente ficticio (env + seed + branding + `config.yaml.tmpl`) y
verificar que un cliente completo (tenant + clients + connections + branding) queda **descrito por el artefacto**
y se materializa vía `seed_client` **sin editar código** ni el `config.yaml` base.

**Acceptance Scenarios**:

1. **Given** un perfil de cliente (env + seed + branding + `config.yaml.tmpl`), **When** se aplica, **Then**
   el tenant, sus clients y connections se crean vía `seed_client` (013) de forma idempotente, sin código nuevo.
2. **Given** el `config.yaml` templado, **When** se renderiza para un cliente, **Then** `model_list`,
   proveedores, keys y **región** se inyectan **por cliente** (no horneados en la imagen).
3. **Given** el `tenant.slug` del cliente (013), **When** se despliega, **Then** el dominio/DNS y el nombre de
   workspace (US4) derivan de ese slug (Principio III).
4. **Given** un cambio en el perfil (p. ej. añadir un proveedor), **When** se re-aplica, **Then** el cambio se
   propaga sin editar el código del producto (config+seed, never fork).

---

### User Story 4 - Módulo OpenTofu portable (VPC / Postgres / Redis / secrets / TLS / región EU) (Priority: P1)

El entregable a Basa→distribuidor **es OpenTofu** (no Terraform: Terraform pasó a licencia **BSL** en 2023 y
HashiCorp es ahora IBM — entregar IaC bajo BSL a un **distribuidor tercero** es deuda legal evitable; OpenTofu
es el fork **MPL 2.0** bajo CNCF y es **drop-in** sobre los mismos `.tf`). Es un módulo **portable** que el
cliente aplica en su cuenta cloud u on-prem para levantar la instalación completa. Provisiona: **red** (VPC con
subredes pública/privada, security group con **sólo 443 in**, NAT para egress a proveedores LLM); **Postgres**
(gestionado tipo RDS/CloudSQL en nube, o contenedor con volumen durable on-prem/air-gap; swap de `POSTGRES_*` —
se abandona el Postgres efímero del compose); **Redis** (gestionado tipo ElastiCache/MemoryStore en nube, o
contenedor on-prem; swap de `REDIS_*`); **cómputo** (v1 realista = **VM + docker compose por cloud-init** desde
las imágenes de US1; v2 roadmap = **k3s + Helm + Zarf**); **secretos** (v1 = **SOPS + age**, sin servidor,
portable y apto air-gap; v2 = **OpenBao** si se pide store central) para todos los secretos; **TLS/ingress**
(v1 = **Caddy** auto-HTTPS; v2 = **Traefik**, el ingress default de k3s) + **DNS por cliente** (encaja con
`tenant.slug`); **región fijable a EU** (residencia GDPR). Expone **outputs** (URL, admin bootstrap rotado) y
soporta **remote state + workspaces por cliente** para las muchas instalaciones del distribuidor.

**Why this priority**: Es literalmente el producto que Basa vende (no instala; entrega el módulo OpenTofu). Sin
el módulo no hay negocio. P1.

**⚠️ Premisa condicionada (v1 vs v2 de cómputo)**: v1 apunta a **VM + docker compose por cloud-init** (realista,
rápido de entregar), con **módulos OpenTofu por provider** para la infra base y un cloud de referencia (AWS:
VPC/RDS/ElastiCache/Route53) sin atarse a servicios propietarios de orquestación. **k3s + Helm + Zarf** es el
**roadmap explícito v2** (da el **mismo Kubernetes** en nube, on-prem y air-gap — ése es el valor de
portabilidad real, no un "multi-cloud mágico"). Se **descarta ECS/Fargate**: es AWS-only y **ECS Anywhere NO
corre air-gapped** (exige conexión permanente al control plane de AWS in-region), lo que viola el requisito
on-prem/air-gap. No se promete multi-cloud en el MVP; k8s puro por portabilidad **no** se justifica para nube
pura.

**Independent Test**: Con credenciales de un cloud sandbox y un perfil de cliente (US3), correr
`tofu apply` en una **región EU** y verificar que se levanta una instalación funcional: VPC con 443-only,
Postgres gestionado wired por `POSTGRES_*`, Redis gestionado por `REDIS_*`, secretos cifrados en el store
portable (SOPS+age / OpenBao), TLS sirviendo HTTPS en el DNS del cliente, y outputs con la URL + un admin
bootstrap **rotado**.

**Acceptance Scenarios**:

1. **Given** el módulo OpenTofu y un perfil de cliente, **When** se hace `tofu apply` en región EU,
   **Then** se provisiona VPC (subredes pública/privada, SG **sólo 443 in**, NAT para egress a proveedores) +
   Postgres gestionado + Redis gestionado + cómputo, y el producto queda accesible por HTTPS.
2. **Given** el Postgres/Redis gestionados, **When** arranca el backend/motor, **Then** consumen esos endpoints
   vía swap de `POSTGRES_*`/`REDIS_*` (no el Postgres efímero ni el Redis in-container del compose de dev).
3. **Given** el store de secretos (**SOPS + age** v1 / **OpenBao** v2), **When** se despliega, **Then** todos
   los secretos (`POSTGRES_PASSWORD`, `LITELLM_MASTER_KEY`, `FERNET_SECRET_KEY`, `JWT_SECRET_KEY`, keys de
   proveedores, `oauth_credential_ref`) se inyectan cifrados desde ahí, **nunca** en `tfvars`/state en claro
   (Constraint C5, ver 014).
4. **Given** el TLS/ingress, **When** el cliente accede, **Then** hay HTTPS terminado (**Caddy** auto-HTTPS v1 /
   **Traefik** v2) sobre el DNS derivado del `tenant.slug`.
5. **Given** la variable de región, **When** se fija a EU, **Then** todos los recursos (cómputo, DB, cache,
   estado) quedan en la UE (residencia GDPR).
6. **Given** remote state + workspaces, **When** el distribuidor levanta un segundo cliente, **Then** usa un
   workspace/estado **aislado** desde el mismo módulo, sin colisión con el primero.

---

### User Story 5 - Secretos generados por instalación, sin defaults (Priority: P2)

Los secretos default hardcodeados del compose de dev (`basasecurepass123`, `basa_master_key_9999`) **no pueden
salir a producción**. Esta story los **retira del camino de producción** y hace que **cada instalación genere
sus propios secretos** (OpenTofu `random_password` cifrados con SOPS+age / OpenBao): `POSTGRES_PASSWORD`,
`LITELLM_MASTER_KEY`, `FERNET_SECRET_KEY`, `JWT_SECRET_KEY`, keys de proveedores, `oauth_credential_ref`. El
**admin bootstrap** se **genera y rota** por instalación, se expone **una sola vez** vía output y no se persiste
en claro.

**Why this priority**: Shippear defaults conocidos a N clientes es un agujero de seguridad de manual. P2 porque
el módulo (US4) puede existir con secretos manuales primero, pero no se considera entregable sin esto.

**Independent Test**: Levantar dos instalaciones distintas y verificar: (a) ningún artefacto de producción
contiene los defaults de dev; (b) cada instalación tiene secretos **únicos** generados; (c) el admin bootstrap
se emite rotado por output una sola vez y no queda en claro en el state ni en los logs.

**Acceptance Scenarios**:

1. **Given** los artefactos de producción, **When** se inspeccionan, **Then** **no** aparecen
   `basasecurepass123` ni `basa_master_key_9999` ni ningún secreto default (retirados del camino prod).
2. **Given** dos `tofu apply` en instalaciones distintas, **When** completan, **Then** cada una tiene
   `POSTGRES_PASSWORD`/`LITELLM_MASTER_KEY`/`FERNET_SECRET_KEY`/`JWT_SECRET_KEY` **únicos** y generados.
3. **Given** el admin bootstrap, **When** termina el apply, **Then** se emite **rotado** vía output una sola vez
   y no queda en claro en state/logs.

---

### User Story 6 - Air-gapped / tarball + on-prem sin egress (Priority: P3)

Algunos clientes (p. ej. la VM de VPN de Elea, on-prem) corren **sin egress** o en entornos air-gapped. Esta
story empaqueta el release **v1** como un **tarball** (`docker save`/`docker load` de las imágenes pinneadas +
config + seed) que se instala **sin acceso a registry en runtime**, y documenta el modo **on-prem sin egress**:
sólo se necesita egress a los proveedores LLM vía NAT — o **cero egress** si se usa un modelo local
(Ollama/vLLM, encaja con el single-tenant on-prem de la 013). Para el camino **k8s v2** el empaquetado
air-gap-native es **Zarf** (bundle con **SBOM + firma cosign**); **Replicated** se evalúa si el volumen de
distribuidores crece.

**Why this priority**: Es un modo de entrega para un subconjunto de clientes (el caso Elea real), pero el modelo
de negocio principal es cloud-con-OpenTofu. P3: importante y fundamentado, pero no bloquea el MVP.

**Independent Test**: Exportar el tarball, moverlo a un host **sin acceso a registry**, cargarlo
(`docker load`) y levantar el producto sin pulls; verificar que funciona con egress **sólo** a proveedores LLM
(o con un modelo local, cero egress externo).

**Acceptance Scenarios**:

1. **Given** el bundle de release, **When** se exporta, **Then** produce un tarball con las imágenes pinneadas
   + `config.yaml` + seed, autocontenido.
2. **Given** un host sin acceso a registry, **When** se carga el tarball y se levanta, **Then** el producto
   corre **sin pulls** en runtime.
3. **Given** el modo on-prem sin egress, **When** se documenta la red, **Then** el único egress requerido es a
   los proveedores LLM vía NAT — o **ninguno** con modelo local (Ollama/vLLM, 013).

---

### Edge Cases

- **Deriva dev↔prod (dos codebases de facto)**: si los Dockerfiles de producción divergen del código que corre
  en dev, se rompe "config+seed, never fork". El producto MUST ser **un solo codebase con dos perfiles de
  build** (dev-compose vs prod-images); el compose de dev se conserva **sólo** para desarrollo local.
- **Branding que se cuela al código**: si un distribuidor necesita editar fuente para su marca, se violó VII. El
  branding pack MUST cubrir nombre/logo/colores/dominio/soporte por config; cualquier caso no cubierto se
  documenta como gap, no se resuelve con fork.
- **Fuga del nombre del motor**: la UI podría filtrar "litellm" en un error, un header o un título (gotcha ya
  visto en el PoC de browser-DLP). Hay un check de que ningún artefacto de marca blanca expone el motor.
- **Secreto default que sobrevive a prod**: un `${VAR:-default}` olvidado en un artefacto de producción
  reintroduce el agujero. La US5 exige un check que falle si aparece cualquier default conocido en el camino
  prod.
- **State de OpenTofu con secretos en claro**: si un secreto entra al state (p. ej. `random_password` sin
  marcar sensitive o volcado a un output no protegido), queda en claro en el backend de state. MUST vivir en el
  store portable (SOPS+age / OpenBao) y marcarse sensitive; el state remoto MUST estar cifrado.
- **Región no-EU por descuido**: si la variable de región queda en un default us-*, se rompe la residencia GDPR.
  El default MUST ser EU y el apply MUST fallar/avisar si se fija fuera de EU sin override explícito.
- **`config.yaml` horneado en la imagen**: si el `config.yaml` se hornea, no se puede templar por cliente. MUST
  montarse/inyectarse por cliente (mismo patrón de volumen que la 014), no bakearse.
- **Cross-tenant en workspaces**: dos clientes del distribuidor compartiendo state/secretos por un workspace mal
  aislado filtra credenciales entre clientes. Cada cliente MUST tener workspace + secretos aislados (Principio
  III).
- **Air-gapped que igual necesita pull**: un `image: ...@sha256` que no está en el tarball fuerza un pull en un
  host sin egress y rompe el install. El tarball MUST contener **todas** las imágenes pinneadas del release.
- **Licencias fuera de scope pero cableadas a medias**: si esta spec empieza a contar/validar licencias, invade
  la 021. MUST dejar sólo el **hueco de entrada** (placeholder de license key) sin enforcement.

## Requirements *(mandatory)*

### Functional Requirements

**Imágenes de producción (US1)**
- **FR-001**: El sistema MUST proveer un `backend.prod.Dockerfile` **multistage**: etapa de build con
  toolchain, imagen final slim **sin** `build-essential`/compiladores, arranque con **uvicorn workers** o
  **gunicorn + UvicornWorker** (v1, aburrido y probado) **sin `--reload`**, usuario **non-root**, healthcheck y
  base pinneada por digest. (**granian** queda como optimización opcional, no requerida en v1.)
- **FR-002**: El sistema MUST proveer un `frontend.prod.Dockerfile` que ejecute `vite build` y sirva
  **estáticos** vía **Caddy** (o nginx) (NO vite dev server), como non-root, base pinneada. El bundle MUST ser
  **marca-neutro**: el branding NO se hornea por distribuidor, se inyecta en **runtime** (env + assets
  montados, ver US2).
- **FR-003**: Las imágenes de producción MUST hornear el código (self-contained); MUST NOT depender de
  bind-mounts de código fuente (a diferencia del `docker-compose.yml` de dev).
- **FR-004**: El release MUST publicar las imágenes pinneadas por **tag+digest** en un registry **o** exportarlas
  como **tarball** (`docker save`) para air-gapped (US6), reusando la disciplina de pin de la 014 (Principio VI).
- **FR-005**: El artefacto de orquestación de producción MUST terminar **TLS**, usar almacenamiento **durable**
  para `pgdata` (no el volumen efímero del compose de dev) y MUST NOT shippear secretos default (delega en US5).

**Branding pack como config (US2)**
- **FR-006**: El branding del producto (nombre, logo, colores, dominio, contacto de soporte) MUST inyectarse
  como **config-as-data en runtime** (**env + assets montados**), **una marca por instancia**; MUST NOT
  requerir build-time baking, theming multi-tenant dinámico, ni fork del código (Principio VII).
- **FR-007**: El motor upstream (**LiteLLM**) MUST NOT aparecer nombrado en la UI ni en ningún artefacto de
  marca blanca (mandato del Principio VII).
- **FR-008**: Un único **branding pack** MUST parametrizar en **runtime** el frontend (env + assets montados) y
  el metadata del backend; cambiar de marca MUST requerir **cero** ediciones de código fuente **y cero
  rebuild** de imagen.
- **FR-009**: MUST existir un branding **por defecto** (Basa-neutro) como fallback; el pack del distribuidor lo
  sobreescribe.

**Perfil por cliente (US3)**
- **FR-010**: Cada instalación de cliente MUST ser describible como un **perfil-artefacto** = env + seed
  (onboarding-as-data 013) + branding pack (US2) + `config.yaml` templado.
- **FR-011**: El `config.yaml` MUST ser **templado** (no horneado): `model_list`, proveedores, keys y **región**
  se inyectan por cliente en deploy (mismo patrón de montaje que la 014).
- **FR-012**: El seed del perfil MUST reusar `seed_client` (013), idempotente (Principio IV); MUST NOT introducir
  un mecanismo de onboarding paralelo.
- **FR-013**: Levantar un cliente nuevo MUST NOT requerir cambios de código — sólo un **perfil-artefacto** nuevo
  + un workspace de OpenTofu (US4).
- **FR-014**: El perfil MUST atarse al **`tenant.slug`** (013) para derivar dominio/DNS y nombre de workspace
  (Principio III).

**Módulo OpenTofu portable (US4)**
- **FR-015**: El módulo MUST provisionar **red**: VPC con subredes pública/privada, security group con **sólo
  443 in**, y NAT para el egress a proveedores LLM.
- **FR-016**: El módulo MUST provisionar **Postgres gestionado** (RDS/CloudSQL) y cablearlo por swap de
  `POSTGRES_*`; MUST NOT usar el Postgres efímero in-container del compose de dev en producción.
- **FR-017**: El módulo MUST provisionar **Redis gestionado** (ElastiCache/MemoryStore) y cablearlo por swap de
  `REDIS_*`.
- **FR-018**: El módulo MUST desplegar el **cómputo**: v1 = **VM + docker compose por cloud-init** desde las
  imágenes de US1; **k3s + Helm + Zarf** queda como **roadmap v2** explícito. **ECS/Fargate MUST NOT** usarse
  (AWS-only y **ECS Anywhere no corre air-gapped**: exige conexión permanente al control plane de AWS
  in-region, lo que rompe el requisito on-prem/air-gap).
- **FR-019**: Todos los secretos (`POSTGRES_PASSWORD`, `LITELLM_MASTER_KEY`, `FERNET_SECRET_KEY`,
  `JWT_SECRET_KEY`, keys de proveedores, `oauth_credential_ref`) MUST vivir cifrados en un **store portable**
  (v1 = **SOPS + age**, sin servidor y apto air-gap; v2 = **OpenBao** —fork MPL de Vault, NO Vault por su BSL—
  si se pide store central) e inyectarse en runtime; MUST NOT aparecer en `tfvars`/state/logs en claro
  (Constraint C5, ver 014). Los secrets managers cloud (Secrets Manager/SSM) MUST NOT ser la base: atan a una
  nube y no existen en air-gap.
- **FR-020**: El módulo MUST configurar **TLS/ingress** (v1 = **Caddy** auto-HTTPS; v2 = **Traefik**, ingress
  default de k3s) + **DNS por cliente** derivado del `tenant.slug`.
- **FR-021**: El módulo MUST permitir **fijar la región a EU** (residencia GDPR); el default MUST ser EU.
- **FR-022**: El módulo MUST exponer **outputs**: al menos la **URL** del producto y un **admin bootstrap
  rotado** (emitido una vez, no persistido en claro).
- **FR-023**: El módulo MUST soportar **remote state + workspaces por cliente** para las muchas instalaciones del
  distribuidor, con estado y secretos **aislados** por cliente (Principio III).
- **FR-024**: El módulo MUST permitir elegir, por variable, entre **pull-secret de registry** o **tarball
  air-gapped** (US6) como fuente de imágenes.

**Secretos por instalación (US5)**
- **FR-025**: Ningún artefacto del camino de producción MUST contener secretos default (retirar
  `basasecurepass123`, `basa_master_key_9999` y cualquier `${VAR:-default}` de secreto del camino prod).
- **FR-026**: Cada instalación MUST **generar sus propios secretos** en provisión (OpenTofu `random_password` /
  cifrados con SOPS+age / OpenBao), únicos por instalación.
- **FR-027**: El **admin bootstrap** MUST generarse y **rotarse** por instalación, emitirse una sola vez vía
  output y MUST NOT persistirse en claro (state/logs).

**Air-gapped / on-prem (US6)**
- **FR-028**: El release MUST ser empaquetable para air-gap: **v1** = **tarball** (`docker save`/`docker load`
  de las imágenes pinneadas + `config.yaml` + seed), autocontenido; **v2 (k8s)** = bundle **Zarf**
  (SBOM + firma cosign, airgap-native).
- **FR-029**: El modo **on-prem sin egress** MUST documentar las expectativas de red: egress **sólo** a
  proveedores LLM vía NAT, o **cero** egress con modelo local (Ollama/vLLM, 013).
- **FR-030**: El install air-gapped MUST NOT requerir acceso a registry en runtime (imágenes cargadas desde el
  tarball).

**Transversal (un codebase, dos perfiles; hueco de licencias)**
- **FR-031**: El compose de **desarrollo** actual MUST conservarse **sólo** para desarrollo local; los artefactos
  de producción son **aditivos**, no un fork (config+seed, never fork — un codebase, dos perfiles de build).
- **FR-032**: El **enforcement de licencias** MUST quedar **fuera de scope**: esta spec sólo MUST exponer el
  **hueco de entrada** (p. ej. env/placeholder de license key) que la **spec 021 (license enforcement)**
  consumirá; MUST NOT contar/validar/expirar licencias aquí.

### Key Entities *(include if feature involves data)*

- **Imagen backend de producción** — *NUEVO*. Multistage, gunicorn/uvicorn workers sin `--reload`, non-root,
  healthcheck, base pinneada. Reemplaza `backend/Dockerfile` (dev, `--reload`, root) en el camino prod.
- **Imagen frontend de producción** — *NUEVO*. `vite build` → estáticos por Caddy/nginx, non-root. Reemplaza
  `frontend/Dockerfile` (dev, vite dev server) en el camino prod.
- **Release bundle** — *NUEVO*. Imágenes pinneadas en registry (tag+digest) **o** tarball `docker save`
  (air-gapped). Hereda la disciplina de pin de la 014.
- **Branding pack** — *NUEVO, config-as-data en runtime*. Nombre/logo/colores/dominio/soporte inyectados por
  **env + assets montados en runtime** (NO build-time, NO theming multi-tenant dinámico): **una marca por
  instancia**. NO fork. Default Basa-neutro + override por distribuidor.
- **Perfil de cliente** — *NUEVO, artefacto*. env + seed (`seed_client` 013) + branding pack + `config.yaml`
  templado, atado a `tenant.slug`.
- **Módulo OpenTofu (raíz + submódulos)** — *NUEVO*. `network` (VPC/SG/NAT), `database` (Postgres),
  `cache` (Redis), `compute` (VM+cloud-init v1 / **k3s+Helm+Zarf** v2), `secrets` (**SOPS+age** v1 / **OpenBao**
  v2), `ingress` (**Caddy** v1 / **Traefik** v2 + DNS por `tenant.slug`). Módulos por provider; región EU
  fijable.
- **Set de secretos por instalación** — *NUEVO*. `POSTGRES_PASSWORD`, `LITELLM_MASTER_KEY`, `FERNET_SECRET_KEY`,
  `JWT_SECRET_KEY`, keys de proveedores, `oauth_credential_ref`, admin bootstrap rotado. Generados por install,
  cifrados con **SOPS + age** (v1) / **OpenBao** (v2), nunca default ni en claro.
- **Remote state + workspace (por cliente)** — *NUEVO*. Estado remoto cifrado + un workspace por cliente para las
  N instalaciones del distribuidor; aislamiento por cliente (III).
- **`tenant.slug` / `seed_client` (013)** — *REUSA*. Slug para dominio/DNS/workspace; `seed_client` idempotente
  para el onboarding-as-data del perfil. No se rediseñan.
- **Imagen LiteLLM pinneada + `config.yaml` + `litellm/extensions` (014)** — *REUSA*. El release las incluye; el
  `config.yaml` se templa por cliente (no se hornea).
- **`docker-compose.yml` (dev)** — *CONSERVADO sólo para dev*. No sale al camino prod; los artefactos prod son
  aditivos.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001 (imágenes de producción reales)**: Las imágenes de producción tienen **0** `--reload`, **0**
  bind-mounts de código fuente, corren **non-root**, el frontend sirve **estáticos** (no hay proceso vite dev),
  y la capa final del backend **no** contiene `build-essential`; verificable inspeccionando imagen/Dockerfile.
- **SC-002 (marca blanca sin fork)**: Cambiar de marca (nombre/logo/colores/dominio) se hace con **0** ediciones
  de código fuente, y un `grep` de los artefactos de marca blanca devuelve **0** coincidencias de
  "litellm"/"LiteLLM" expuestas al usuario.
- **SC-003 (cliente como dato)**: Un cliente nuevo se levanta desde un **perfil-artefacto** (env + seed +
  branding + `config.yaml` templado) con **0** ediciones de código y **0** ediciones del `config.yaml` base.
- **SC-004 (tofu apply levanta todo, en EU)**: `tofu apply` en una **región EU** deja una instalación
  funcional accesible por **HTTPS**, con VPC (443-only) + Postgres gestionado + Redis gestionado + secretos
  cifrados (SOPS+age / OpenBao) + TLS (Caddy) + DNS por `tenant.slug`.
- **SC-005 (secretos por instalación, sin defaults)**: **0** secretos default en artefactos de producción; cada
  instalación tiene secretos **únicos** generados; el admin bootstrap se emite **rotado** una sola vez y **no**
  queda en claro en state/logs.
- **SC-006 (air-gapped funciona)**: Un install air-gapped completa con **0** pulls de registry en runtime; el
  único egress es a proveedores LLM (o **ninguno** con modelo local).
- **SC-007 (N instalaciones aisladas)**: El distribuidor levanta **N** instalaciones desde **un** módulo vía
  workspaces, con state y secretos **aislados** por cliente (sin fuga cross-tenant).
- **SC-008 (un codebase, dos perfiles)**: El compose de **dev** sigue funcionando sin cambios para desarrollo
  local; los artefactos de producción son **aditivos** (config+seed, never fork), verificable corriendo ambos
  perfiles desde el mismo código.

## Assumptions

- **Depende del bedrock 013 y de la 014**: `tenant.slug` y `seed_client` (013, onboarding-as-data) ya existen y
  se **reusan**; la imagen LiteLLM pinneada por digest, el `config.yaml` y el volumen `litellm/extensions`
  (014) ya existen y se **empaquetan** (el `config.yaml` se templa por cliente, no se rediseña). Esta spec NO
  los diseña.
- **Modelo de negocio (fuente de las decisiones de shape)**: Basa cobra **INSTALL + X licencias** y vende a un
  **DISTRIBUIDOR** de marca blanca que garantiza training+soporte; **Basa NO instala al cliente final y NO opera
  servidores**; entrega **OpenTofu** (+ imágenes/bundle + perfil) para que el cliente lo levante donde quiera.
  Esto justifica que el entregable sea **portable, parametrizable y sin dependencia operativa de Basa**.
- **Enforcement de licencias = spec 021 (license enforcement)**: contar/validar/expirar las X licencias vendidas
  es **otra spec**; esta sólo deja el **hueco de entrada** (placeholder de license key) sin cablearlo (FR-032).
- **Reconciliación de numeración con el roadmap (bookkeeping SDD)**: `ROADMAP-guardian.md` **reserva** los
  slots `015`–`018` para otras features (SecurityPolicy, Real NLP Masking/Presidio, Auth hardening/RBAC/SSO,
  Compliance). Para no colisionar con ellos, esta spec ocupa el slot **020** ("White-Label Packaging &
  Deploy"), la de **license enforcement** es la **021** y la de **integration surfaces** la **019**. Los slots
  reservados `015`–`018` quedan intactos con sus features; no se toca el roadmap en esta spec.
- **v1 realista de cómputo y cloud de referencia**: v1 = **VM + docker compose por cloud-init** sobre **un cloud
  de referencia** (AWS: VPC/RDS/ElastiCache/Route53), con **módulos OpenTofu por provider** para la infra base
  y TLS por **Caddy** (auto-HTTPS) — sin atarse a servicios de orquestación propietarios. **k3s + Helm + Zarf**
  es el **roadmap v2** explícito y da el **mismo Kubernetes** en nube, on-prem y air-gap (esa es la portabilidad
  real). **ECS/Fargate se descarta**: es AWS-only y **ECS Anywhere no corre air-gapped** (exige conexión
  permanente al control plane de AWS in-region), lo que viola on-prem/air-gap. No se promete multi-cloud en el
  MVP; k8s puro por portabilidad **no** se justifica para nube pura.
- **Región EU por defecto**: la residencia GDPR se satisface fijando la región a EU por defecto; el distribuidor
  puede overridear conscientemente (con aviso).
- **Un codebase, dos perfiles**: el `docker-compose.yml` de dev se conserva para desarrollo local; producción es
  aditiva (Dockerfiles prod + OpenTofu), no un fork del código (Principio VII).
- **Los servicios existentes no cambian**: backend/servicios/modelos se **empaquetan** tal cual; esta spec es de
  **empaquetado y deploy**, no de lógica de producto.
