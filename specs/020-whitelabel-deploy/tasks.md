---
description: "Task list for feature 020 — White-Label Packaging & Deploy"
---

# Tasks: White-Label Packaging & Deploy

**Input**: Design documents from `/specs/020-whitelabel-deploy/`

**Prerequisites**: plan.md (required), spec.md (required for user stories). Depende del **bedrock 013**
(`tenant.slug`, `seed_client` onboarding-as-data) y de la **014** (imagen LiteLLM pinneada por digest,
`litellm/config.yaml`, volumen `litellm/extensions`). El **enforcement de licencias es la spec 021**
(referenciada, NO desarrollada aquí).

**Estado**: **greenfield / roadmap**. Hoy TODO es dev-mode y hay **cero IaC**: ninguna tarea de esta feature
está implementada. Todas arrancan en `[ ]`.

**Tests**: SÍ incluidos como **validación de artefactos** (no unit tests de producto): build reproducible de
imágenes prod (inspección de capas), `tofu validate/plan/apply` en sandbox EU, y **checks negativos**
(0 secretos default en prod, 0 mención del motor en marca blanca, 0 secretos en claro en state). Los tests
marcados ⚠️ se escriben ANTES del artefacto que validan y deben FALLAR primero.

**Organization**: Tareas agrupadas por user story para implementación y validación independientes.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Puede correr en paralelo (archivos distintos, sin dependencias)
- **[Story]**: US1..US6 (o SETUP/FOUND/POLISH)
- Rutas de archivo exactas incluidas

## Path Conventions

- Empaquetado + IaC: `deploy/` (docker/, branding/, clients/, terraform/, release/)
- Reusados sin reescribir: `backend/`, `frontend/`, `litellm/` (se buildean/empaquetan)
- Conservado sólo para dev local: `docker-compose.yml`
- Docs de la feature: `specs/020-whitelabel-deploy/`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Estructura del árbol `deploy/` y esqueleto de validación.

- [X] T001 [SETUP] Crear el árbol `deploy/` (`docker/`, `branding/`, `clients/`, `terraform/`, `release/`) con
      un `README.md` que explique el modelo de negocio (INSTALL + X licencias, distribuidor, Basa no opera
      servidores) y el mapa "un codebase, dos perfiles" (dev-compose vs prod-images).
- [X] T002 [P] [SETUP] Añadir `.gitignore` para secretos/artefactos por instalación (tfvars con valores,
      `*.tfstate`, tarballs, `clients/*/secrets*`) — nada de secretos en el repo.
- [X] T003 [SETUP] Preparar el esqueleto de validación: scripts/checks negativos vacíos (0 secretos default,
      0 mención del motor, 0 secretos en claro en state) y un `Makefile`/task-runner que orqueste build/plan.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Phase 0 research. TODO el diseño del módulo y las imágenes depende de estas decisiones.

**⚠️ CRITICAL**: Ninguna user story arranca hasta cerrar esta fase.

- [X] T004 [FOUND] Phase 0 research (`research.md`): fijar (a) **OpenTofu vs Terraform** (BSL) + **cloud de
      referencia** v1 (AWS: VPC/RDS/ElastiCache/Route53, con módulos por provider); (b) estrategia de **cómputo**
      (v1 VM+docker-compose por cloud-init desde imágenes de US1; **k3s + Helm + Zarf** = roadmap v2 — **ECS/
      Fargate descartado**: ECS Anywhere no corre air-gapped); (c) **store de secretos** (**SOPS+age** v1 /
      **OpenBao** v2, no secrets managers cloud) y modo **TLS** (**Caddy** v1 / **Traefik** v2); (d) layout de
      **remote state + workspaces por cliente**; (e) **residencia EU** por defecto. GCP/Azure = paridad roadmap
      v2, documentada. *(Bloquea US4.)*
- [X] T005 [FOUND] Definir el **contrato del perfil de cliente** (`contracts/`): variables de entrada del
      módulo (region, tenant_slug, dominio, fuente de imágenes registry|tarball) y **outputs** (URL, admin
      bootstrap rotado). Congela la interfaz que US3/US4 implementan. *(FR-014, FR-022, FR-024)*

**Checkpoint**: Cloud de referencia + estrategia de cómputo/secrets/TLS + contrato del perfil fijados → las
user stories pueden empezar.

---

## Phase 3: User Story 1 - Imágenes de producción + publicación/bundle (Priority: P1) 🎯 MVP-blocker

**Goal**: Imágenes prod autocontenidas (backend multistage non-root sin `--reload`; frontend estático) y su
publicación pinneada / tarball. Base de todo el deploy.

**Independent Test**: Buildear las imágenes prod → verificar non-root, sin toolchain en la capa final, sin
`--reload`, frontend estático (no vite dev), código horneado, pinneadas por tag+digest o exportadas a tarball.

### Tests for User Story 1 ⚠️

- [X] T006 ⚠️ [P] [US1] Check de imagen en `deploy/release/checks/test_backend_image.sh`: la capa final NO
      contiene `build-essential`/toolchain, el proceso NO usa `--reload`, corre **non-root**, hay healthcheck.
      DEBE FALLAR primero. *(SC-001)*
- [X] T007 ⚠️ [P] [US1] Check de imagen en `deploy/release/checks/test_frontend_image.sh`: sirve **estáticos**
      (no hay proceso `npm run dev`/vite dev), corre non-root. DEBE FALLAR primero. *(SC-001)*

### Implementation for User Story 1

- [X] T008 [US1] Escribir `deploy/docker/backend.prod.Dockerfile`: **multistage** (build con toolchain → final
      slim sin `build-essential`), arranque `gunicorn`/`uvicorn workers` **sin `--reload`**, usuario **non-root**,
      healthcheck, base pinneada por digest; migraciones en un entrypoint prod. *(FR-001, FR-003)*
- [X] T009 [US1] Escribir `deploy/docker/frontend.prod.Dockerfile`: `vite build` → estáticos servidos por
      **nginx/caddy** (NO vite dev server), non-root, base pinneada. *(FR-002, FR-003)*
- [X] T010 [US1] Escribir `deploy/release/publish.sh`: build + push de las imágenes prod **pinneadas por
      tag+digest** a un registry (reusa la disciplina de pin de la 014). *(FR-004)*
- [X] T011 [US1] Garantizar TLS + storage durable + sin secretos default en el artefacto de orquestación de
      producción (delega los secretos a US5; delega TLS/storage al OpenTofu de US4). *(FR-005)*

**Checkpoint**: Imágenes prod verdes (checks negativos pasan) y publicables → US4 puede montar sobre ellas.

---

## Phase 4: User Story 2 - Branding pack como config, no fork (Priority: P1)

**Goal**: Branding (nombre/logo/colores/dominio/soporte) como config inyectable; el motor nunca se nombra.

**Independent Test**: Sustituir el branding default por el de un distribuidor ficticio (env/build) → UI y
metadata reflejan la marca **sin editar código**; `grep` de artefactos de marca blanca = 0 "litellm".

### Tests for User Story 2 ⚠️

- [X] T012 ⚠️ [P] [US2] Check negativo en `deploy/release/checks/test_no_engine_name.sh`: 0 coincidencias de
      "litellm"/"LiteLLM" expuestas al usuario en los artefactos de marca blanca (UI build + metadata). DEBE
      FALLAR si el motor se filtra. *(FR-007, SC-002)*

### Implementation for User Story 2

- [X] T013 [US2] Definir el **branding pack** (`deploy/branding/branding.default.env` Basa-neutro +
      `branding.example.env` distribuidor + `assets/` placeholder) con nombre/logo/colores/dominio/soporte.
      *(FR-006, FR-009)*
- [X] T014 [US2] Cablear el frontend (bundle marca-neutro) y el metadata del backend para consumir el branding
      pack como **config-as-data en runtime** (**env + assets montados**, una marca por instancia; NO build-time,
      NO rebuild), sin ediciones de código fuente; fallback al default si no hay pack del distribuidor.
      *(FR-006, FR-008, FR-009)*
- [X] T015 [US2] Asegurar que ningún artefacto de marca blanca nombra el motor (títulos, headers, errores,
      about); cerrar el gotcha de fuga de nombre del PoC browser-DLP. *(FR-007)*

**Checkpoint**: Marca blanca conmutable por config, sin fork y sin filtrar el motor.

---

## Phase 5: User Story 3 - Perfil por cliente empaquetado (Priority: P1)

**Goal**: Perfil-artefacto = env + seed (`seed_client` 013) + branding pack + `config.yaml` templado, atado a
`tenant.slug`.

**Independent Test**: Definir el perfil de un cliente ficticio → un cliente completo (tenant+clients+connections
+branding) queda descrito por el artefacto y se materializa vía `seed_client` sin editar código.

### Tests for User Story 3 ⚠️

- [X] T016 ⚠️ [P] [US3] Check en `deploy/release/checks/test_profile_renders.sh`: el `config.yaml.tmpl` renderiza
      con el env del perfil (model_list/proveedores/keys/región inyectados) y NO queda nada horneado; el seed es
      idempotente. DEBE FALLAR primero. *(FR-011, FR-012, SC-003)*

### Implementation for User Story 3

- [X] T017 [US3] Definir la estructura del perfil en `deploy/clients/<client-slug>/` (`client.env`,
      `branding.env`, `seed.yaml`, `config.yaml.tmpl`) y documentar su contrato (del research T005). *(FR-010)*
- [X] T018 [US3] Cablear el `seed.yaml` a **`seed_client`** (013) — onboarding-as-data idempotente, sin
      mecanismo paralelo. *(FR-012)*
- [X] T019 [US3] Templar `config.yaml.tmpl`: inyectar `model_list`/proveedores/keys/**región** por cliente en
      deploy (montado como volumen, patrón 014; NO horneado). *(FR-011)*
- [X] T020 [US3] Derivar dominio/DNS y nombre de workspace del **`tenant.slug`** (013); levantar un cliente NO
      requiere cambios de código, sólo un perfil + workspace. *(FR-013, FR-014)*

**Checkpoint**: Un cliente = un artefacto; onboarding como dato, sin fork.

---

## Phase 6: User Story 4 - Módulo OpenTofu portable (Priority: P1) 🎯 MVP

**Goal**: Módulo portable (VPC/Postgres/Redis/cómputo/secrets/TLS/DNS/región EU) + remote state/workspaces por
cliente + outputs. Consume perfil (US3) e imágenes (US1).

**⚠️ GATE — T004 ANTES de codear US4**: Ninguna tarea de US4 arranca hasta cerrar **T004** (OpenTofu vs
Terraform, cloud de referencia, cómputo v1 vs v2, store de secretos, TLS, layout de state). v1 = un cloud de
referencia (AWS) con VM+cloud-init; **k3s+Helm+Zarf** (v2) y GCP/Azure son roadmap explícito; **ECS/Fargate
descartado** (ECS Anywhere no corre air-gapped).

**Independent Test**: (Precondición: T004 cerrado.) `tofu apply` en región EU con un perfil → VPC (443-only)
+ Postgres/Redis gestionados + secretos cifrados (SOPS+age / OpenBao) + TLS/HTTPS (Caddy) en el DNS del
`tenant.slug` + outputs con URL + admin bootstrap rotado.

### Tests for User Story 4 ⚠️

- [X] T021 ⚠️ [P] [US4] `tofu validate` + `plan` en `deploy/terraform/` contra un perfil de ejemplo; el
      plan MUST mostrar SG **443-only**, DB/Redis gestionados, secretos cifrados (SOPS+age/OpenBao), TLS (Caddy),
      región EU. DEBE FALLAR si falta alguno. *(FR-015..FR-021)*
- [X] T022 ⚠️ [P] [US4] Check de aislamiento en `deploy/release/checks/test_workspace_isolation.sh`: dos
      workspaces (dos clientes) → state y secretos **aislados**, sin colisión. DEBE FALLAR primero. *(SC-007)*

### Implementation for User Story 4

- [X] T023 [P] [US4] Submódulo `deploy/terraform/modules/network/`: VPC, subredes pública/privada, security
      group **sólo 443 in**, NAT para egress a proveedores LLM. *(FR-015)*
- [X] T024 [P] [US4] Submódulo `deploy/terraform/modules/database/`: Postgres gestionado (RDS/CloudSQL) +
      output de `POSTGRES_*` (swap del efímero de dev). *(FR-016)*
- [X] T025 [P] [US4] Submódulo `deploy/terraform/modules/cache/`: Redis gestionado (ElastiCache/MemoryStore) +
      output de `REDIS_*`. *(FR-017)*
- [X] T026 [US4] Submódulo `deploy/terraform/modules/compute/`: v1 = VM + docker compose por **cloud-init** desde
      las imágenes de US1; dejar el hook (comentado/roadmap) para **k3s + Helm + Zarf** (v2). **NO** ECS/Fargate
      (ECS Anywhere no corre air-gapped). *(FR-018)*
- [X] T027 [US4] Submódulo `deploy/terraform/modules/ingress/`: TLS (**Caddy** auto-HTTPS v1 / **Traefik** v2) +
      **DNS por cliente** derivado del `tenant.slug`. *(FR-020)*
- [X] T028 [US4] Módulo raíz + `deploy/terraform/envs/<client>/`: región **EU** fijable (default EU), **remote
      state + workspaces por cliente**, y **outputs** (URL + admin bootstrap rotado). *(FR-021, FR-022, FR-023)*
- [X] T029 [US4] Variable de **fuente de imágenes**: `registry` (pull-secret) vs `tarball` air-gapped (engancha
      con US6). *(FR-024)*

**Checkpoint**: `tofu apply` en EU deja una instalación funcional por HTTPS, aislada por cliente.

---

## Phase 7: User Story 5 - Secretos generados por instalación, sin defaults (Priority: P2)

**Goal**: Retirar defaults del camino prod; generar secretos únicos por instalación; admin bootstrap rotado.

**Independent Test**: Dos instalaciones → 0 defaults en artefactos prod, secretos únicos por install, admin
bootstrap rotado emitido una vez, nada en claro en state/logs.

### Tests for User Story 5 ⚠️

- [X] T030 ⚠️ [P] [US5] Check negativo en `deploy/release/checks/test_no_default_secrets.sh`: 0 coincidencias de
      `basasecurepass123`/`basa_master_key_9999`/`${VAR:-<secreto>}` en artefactos del **camino prod**. DEBE
      FALLAR si sobrevive un default. *(FR-025, SC-005)*
- [X] T031 ⚠️ [P] [US5] Check en `deploy/release/checks/test_secrets_not_in_state.sh`: ningún secreto ni el admin
      bootstrap aparece en claro en `tfstate`/outputs no-sensitive/logs. DEBE FALLAR primero. *(SC-005)*

### Implementation for User Story 5

- [X] T032 [US5] En el submódulo `secrets/`: generar por instalación `POSTGRES_PASSWORD`, `LITELLM_MASTER_KEY`,
      `FERNET_SECRET_KEY`, `JWT_SECRET_KEY`, keys de proveedores y `oauth_credential_ref` vía `random_password`
      cifrados con **SOPS + age** (v1) / **OpenBao** (v2), no secrets managers cloud; marcar `sensitive`.
      *(FR-019, FR-026, Constraint C5)*
- [X] T033 [US5] Retirar del camino prod todo secreto default heredado del compose de dev (los artefactos prod
      NO cargan `${VAR:-basasecurepass123}` ni `${VAR:-basa_master_key_9999}`). *(FR-025)*
- [X] T034 [US5] Generar y **rotar** el **admin bootstrap** por instalación; emitirlo una sola vez vía output
      protegido; NO persistirlo en claro. *(FR-027)*

**Checkpoint**: Sin defaults en prod; cada instalación con secretos únicos y admin bootstrap rotado.

---

## Phase 8: User Story 6 - Air-gapped / tarball + on-prem sin egress (Priority: P3)

**Goal**: Release empaquetable como tarball (`docker save`) instalable sin registry; doc on-prem sin egress.

**Independent Test**: Exportar tarball → mover a host sin registry → `docker load` + levantar sin pulls; funciona
con egress sólo a proveedores LLM (o cero con modelo local).

### Tests for User Story 6 ⚠️

- [X] T035 ⚠️ [P] [US6] Check en `deploy/release/checks/test_airgapped_bundle.sh`: el tarball contiene **todas**
      las imágenes pinneadas del release; `docker load` + arranque **sin** acceso a registry. DEBE FALLAR si
      falta una imagen. *(FR-028, FR-030, SC-006)*

### Implementation for User Story 6

- [X] T036 [US6] Escribir `deploy/release/bundle.sh`: `docker save` de las imágenes pinneadas (backend, frontend,
      LiteLLM 014) + `config.yaml` + seed → tarball autocontenido (v1). Para el camino **k8s v2**, el bundle
      air-gap-native es **Zarf** (SBOM + firma cosign); evaluar Replicated si crece el volumen de distribuidores.
      *(FR-028)*
- [X] T037 [US6] Cablear la variable de fuente de imágenes (US4 T029) al camino **tarball**: install sin pulls en
      runtime. *(FR-024, FR-030)*
- [X] T038 [US6] Documentar el modo **on-prem sin egress**: egress sólo a proveedores LLM vía NAT, o cero con
      modelo local (Ollama/vLLM, 013); cubre el caso Elea/DEPLOY_VPN. *(FR-029)*

**Checkpoint**: Install air-gapped sin registry en runtime; on-prem sin egress documentado.

---

## Phase N: Polish & Cross-Cutting Concerns

- [X] T039 [P] [POLISH] Generar `quickstart.md`: rellenar un perfil → `tofu apply` en EU → HTTPS →
      validar (checks negativos). Y `data`/diagramas si aplica.
- [ ] T040 [POLISH] Verificación end-to-end en cloud sandbox (región EU): un cliente completo por HTTPS +
      corrida de TODOS los checks negativos (secretos, motor, region, state). Principio VII.
- [X] T041 [P] [POLISH] Confirmar "un codebase, dos perfiles": el `docker-compose.yml` de dev sigue funcionando
      para local sin cambios; los artefactos prod son aditivos (never fork). *(SC-008, FR-031)*
- [X] T042 [POLISH] Dejar el **hueco de entrada de license key** (env/placeholder) SIN enforcement y
      documentarlo como interfaz para la **spec 021 (license enforcement)**. Segundo punto de contacto
      (addendum 2026-07-14): provisionar además el **volumen/secret persistente para la clave privada
      del deployment** (par Ed25519 generado en el install, firma los exports de true-up de 021/FR-029;
      encaja con "secretos por instalación" D5) — también SIN lógica acá, sólo el hueco. *(FR-032)*

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: sin dependencias.
- **Foundational (Phase 2)**: depende de Setup. BLOQUEA todos los user stories (fija cloud de referencia,
  cómputo, secrets, TLS, state y el contrato del perfil).
- **US1 (Phase 3)**: depende de Foundational. Base de todo (OpenTofu monta sobre estas imágenes).
- **US2 (Phase 4)**: depende de Foundational; independiente de OpenTofu (config de branding).
- **US3 (Phase 5)**: depende de Foundational + US2 (el perfil incluye el branding pack) + reusa `seed_client`/
  `tenant.slug` (013).
- **US4 (Phase 6)**: depende de Foundational + US1 (imágenes) + US3 (perfil). **Gate duro**: no arranca hasta
  cerrar **T004** (research), que fija cómputo v1/v2, secrets y TLS.
- **US5 (Phase 7)**: depende de US4 (se integra en el submódulo `secrets/`).
- **US6 (Phase 8)**: depende de US1 (imágenes pinneadas) + US4 (variable de fuente de imágenes).
- **Polish (Phase N)**: depende de los user stories deseados.

### User Story Dependencies

- **US1 (P1)**: tras Foundational. Sin dependencias de otros stories.
- **US2 (P1)**: tras Foundational. Independiente.
- **US3 (P1)**: tras Foundational + US2; reusa 013.
- **US4 (P1)**: tras Foundational + US1 + US3.
- **US5 (P2)**: tras US4.
- **US6 (P3)**: tras US1 + US4.

### Within Each User Story

- Tests/checks (⚠️) escritos y FALLANDO antes del artefacto que validan.
- Imágenes antes que el OpenTofu que las despliega.
- Branding antes que el perfil que lo incluye.
- Perfil antes que el módulo que lo consume.

### Parallel Opportunities

- Setup: T002 [P].
- US1: T006/T007 [P] (checks de imagen); US4: submódulos T023/T024/T025 [P] (recursos independientes).
- Checks negativos de cada story marcados [P] corren en paralelo (archivos distintos).
- US2 puede desarrollarse en paralelo a US1 una vez cerrada Foundational (branding config vs imágenes).

---

## Parallel Example: User Story 4

```bash
# Submódulos de recursos independientes (distintos directorios):
Task: "Submódulo network (VPC/SG 443-only/NAT) en deploy/terraform/modules/network/"
Task: "Submódulo database (Postgres gestionado -> POSTGRES_*) en deploy/terraform/modules/database/"
Task: "Submódulo cache (Redis gestionado -> REDIS_*) en deploy/terraform/modules/cache/"
# Checks de US4 juntos (distintos archivos):
Task: "tofu validate/plan (443-only, DB/Redis gestionados, TLS, EU) en tests de US4"
Task: "Aislamiento de workspaces (dos clientes) en deploy/release/checks/test_workspace_isolation.sh"
```

---

## Implementation Strategy

### MVP First (US1 + US3 + US4)

1. Phase 1 Setup → Phase 2 Foundational (research: cloud de referencia + cómputo + secrets + TLS + contrato de
   perfil).
2. Phase 3 US1 (imágenes de producción).
3. Phase 5 US3 (perfil por cliente) — con US2 branding integrado.
4. Phase 6 US4 (módulo OpenTofu).
5. **STOP & VALIDATE**: `tofu apply` en región EU deja una instalación funcional por HTTPS desde un perfil
   + imágenes prod. Producto entregable-a-distribuidor listo (sin licencias, sin air-gapped todavía).

### Incremental Delivery

1. Foundational → decisiones de cloud/cómputo/secrets/TLS congeladas.
2. US1 → imágenes de producción publicables.
3. US2 → marca blanca por config (revendible sin fork).
4. US3 → cliente como artefacto (onboarding-as-data).
5. US4 → **MVP**: OpenTofu portable levanta una instalación en EU.
6. US5 → secretos por instalación (endurecimiento de seguridad).
7. US6 → air-gapped/tarball (caso on-prem sin egress, Elea).

### Parallel Team Strategy

Tras Foundational: Dev A → US1 (imágenes prod); Dev B → US2+US3 (branding + perfil); Dev C → US4 submódulos
OpenTofu. US5 lo integra quien cierra `secrets/`; US6 lo cierra quien consolida el release/bundle.

---

## Notes

- [P] = archivos/directorios distintos, sin dependencias.
- [Story] mapea cada tarea a su user story para trazabilidad.
- Verificar que los checks ⚠️ fallan antes de crear el artefacto que validan.
- Commit tras cada tarea o grupo lógico; validación en cloud sandbox (región EU) antes de mergear.
- **Reuse vs nuevo**: se **reusan** `seed_client`/`tenant.slug` (013) y la imagen pinneada/`config.yaml`/
  extensiones (014); lo **nuevo** es empaquetado (Dockerfiles prod), branding-config, perfil-artefacto y el
  módulo OpenTofu. El código de producto NO se reescribe: se buildea/empaqueta.
- **Never fork**: un codebase, dos perfiles de build (dev-compose / prod-images). Cualquier branding horneado en
  código, secreto default en prod, o conteo de licencias aquí es una violación a justificar (ver plan.md →
  Complexity Tracking).
- **Fuera de scope**: el **enforcement de licencias** es la **spec 021**; aquí sólo el hueco de entrada.
