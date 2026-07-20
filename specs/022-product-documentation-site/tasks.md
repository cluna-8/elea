---
description: "Task list for feature 022 — Product Documentation Site (Distribuidor & Operador)"
---

# Tasks: Product Documentation Site (Distribuidor & Operador)

**Input**: Design documents from `/specs/022-product-documentation-site/`

**Prerequisites**: plan.md (required), spec.md (required for user stories), research.md (framework decidido:
MkDocs+Material primario, Starlight+Pagefind plan B). **GREENFIELD**: no hay sitio previo; la **semilla** es el
corpus `basa-guardian/docs/*.md` (`whitelabel-deployment.md`, `integration-surfaces.md`,
`compliance-policies.md`) y el **OpenAPI** del backend FastAPI (para el API reference). Depende, en enganche de
deploy, del empaquetado de la **020** (compose v1 / k3s+Zarf v2).

**Tests**: SÍ incluidos. El **0 egress** (air-gap), el **white-label sin fork**, el **naming neutro**, la
**deriva del API reference** y la **búsqueda offline** llevan tests/checks; el contenido se valida como
documentación (cobertura de secciones + leyenda de estado). Los tests marcados ⚠️ se escriben ANTES de la
implementación y deben FALLAR primero.

**Organization**: Tareas agrupadas por user story para implementación y verificación independientes.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Puede correr en paralelo (archivos distintos, sin dependencias)
- **[Story]**: US1..US7 (o SETUP/FOUND/POLISH)
- Rutas de archivo exactas incluidas

## Path Conventions

- Sitio: `docs/` (raíz del repo) — `docs/mkdocs.yml`, `docs/Dockerfile`, `docs/nginx.conf`,
  `docs/requirements-docs.txt`, `docs/brand/`, `docs/docs/**` (contenido)
- Overlays de marca: `docs/mkdocs.<brand>.yml`
- Compose: `deploy/docker/compose.prod.yml` (servicio `docs` — el entregable) + `docker-compose.yml` (dev)
- Legacy a deprecar: `frontend/src/pages/DocsPage.tsx`
- Semilla: `basa-guardian/docs/*.md`
- Tests/checks: `deploy/release/checks/` (runner real del repo: `make -C deploy check`)

## Delta post-020/021 (speckit-analyze 2026-07-20 — los artefactos eran del 14-jul, pre-implementación de 020/021)

- **F1**: el compose entregable es `deploy/docker/compose.prod.yml` (020); el servicio `docs` vive AHÍ
  (perfil normal + selfhosted). El dev compose es opcional para preview local. T010 ajustada.
- **F2** (*Reuse over Reinvent*): el check de naming neutro del sitio comparte la **lista de nombres
  prohibidos** con `deploy/release/checks/test_no_engine_name.sh` (020) y se orquesta desde `make -C deploy
  check` — jamás dos listas que derivan. T022 ajustada; incluir "Meta" (constitución VII).
- **F3**: el brand-pack de docs NO es una segunda fuente de marca: el overlay `mkdocs.<brand>.yml` se
  **deriva del brand-pack de la 020** (`deploy/branding/brand*.json` + `deploy/clients/<slug>/branding.env`)
  en build. Una sola definición de marca por cliente. T023 ajustada.
- **F4**: `docs/` contiene internos NO publicables (`COORDINATION-019-e2e-hardening.md`, `retros/`):
  `docs_dir: docs` (relativo a `docs/`, o sea `docs/docs/`) los excluye por construcción, y el check
  anti-fuga (T031) los cubre además de `specs/0XX-*`.
- **F5**: el OpenAPI NO se obtiene importando `src.main` a la ligera (el import corre alembic + licensing →
  necesita DB): paso de export explícito (vía compose con la DB dev, o in-build si se verifica que el import
  sobrevive sin DB). El plugin de render debe pasar el test de 0 egress (assets bundled).
- **F6**: `mike` es git-branch-based: en el build multi-stage se usa un **repo git efímero** dentro del stage
  (mike deploy N versiones → copiar el árbol a nginx). Determinista y 0 egress.
- **F7 (naming, resolución de una contradicción interna del spec)**: FR-013 a la letra ("no mencionar
  Anthropic/OpenAI…") choca con US2/FR-005, que EXIGE la matriz de integraciones (Claude Code, ChatGPT,
  Copilot, Cursor son la superficie documentada) y con el BYOK del operador (que configura claves de SU
  proveedor). Resolución alineada a la constitución VII (el principio es no exponer el MOTOR): prohibido
  absoluto en el HTML publicado = internals del pipeline (`litellm`/`berriai`/`presidio` + crédito del
  tema); nombres de herramientas/proveedores permitidos SOLO como superficies de integración o BYOK del
  usuario. En prosa la marca es neutra ("el producto"/"el gateway"); los identificadores wire (`x-basa-*`,
  `BASA_*`, `/gw/*`) se conservan literales.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Esqueleto del sitio MkDocs + Material y del árbol de contenido.

- [X] T001 [SETUP] Crear `docs/mkdocs.yml` (config base marca-neutra): tema Material, nav/IA de las 9 secciones,
      plugins declarados (`search`/`offline`, `privacy`, `mike`, i18n, render OpenAPI). Crear el árbol vacío
      `docs/docs/**` (overview, install-deploy, white-label, administration, integrations, api-reference,
      compliance, operations, release-notes).
- [X] T002 [P] [SETUP] Crear `docs/requirements-docs.txt` con MkDocs + Material + plugins **pinneados**
      (`mkdocs-material`, `mike`, `mkdocs-static-i18n`, plugin OpenAPI, plugin `privacy`); documentar el build
      local (`mkdocs serve` / `mkdocs build --strict`).
- [X] T003 [SETUP] Preparar el esqueleto de checks en `docs/tests/` (0 egress, naming neutro, white-label,
      deriva API) y engancharlos al runner CI del repo.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Fijar la IA (content-map) + el build `--strict` con `privacy`/`offline` (base del air-gap). TODO
lo demás depende de tener el esqueleto que construye 0-egress y la IA acordada.

**⚠️ CRITICAL**: Ningún user story cierra hasta que el build `--strict` pase y la IA esté fijada.

- [X] T004 [FOUND] Generar `content-map.md`: IA detallada (las 9 secciones + roadmap clínico), **mapeo
      semilla→página** (`whitelabel-deployment.md`→Install/Deploy+Branding, `integration-surfaces.md`→
      Integraciones, `compliance-policies.md`→Compliance) y el **estado por página** (🟢/🟡/🔵). Bloquea US2.
- [X] T005 [FOUND] Configurar el build **air-gap-first** en `docs/mkdocs.yml`: plugin **`privacy`** (embebe
      assets remotos), plugin **`offline`** y `strict: true`. Verificar que `mkdocs build --strict` pasa con el
      árbol de contenido inicial. *(alimenta US1/US4)*

**Checkpoint**: IA fijada + build `--strict` 0-egress verde → los user stories pueden avanzar.

---

## Phase 3: User Story 1 - Contenedor propio, estático y air-gapped (Priority: P1) 🎯 MVP

**Goal**: Empaquetar el sitio como imagen multi-stage → nginx, con **0 egress** en runtime, y enchufarlo al
docker-compose (v1) + documentar el enganche Zarf (v2, 020).

**Independent Test**: Construir la imagen, arrancarla con la **red saliente bloqueada**, navegar + buscar;
verificar 0 requests externos y que el servicio levanta en el compose detrás del proxy.

### Tests for User Story 1 ⚠️

- [X] T006 ⚠️ [P] [US1] Test de **0 egress** en `docs/tests/test_airgap_zero_egress.*`: arrancar la imagen con
      la red saliente bloqueada, navegar todas las secciones + ejecutar búsqueda, y afirmar **0** requests a
      hosts externos. *(FR-002, SC-001)*
- [X] T007 ⚠️ [P] [US1] Test de build `--strict` en CI: `mkdocs build --strict` **falla** ante un link interno
      roto o un asset externo no embebido (fixture negativo que debe romper el build). *(FR-003, SC-001)*

### Implementation for User Story 1

- [X] T008 [US1] Crear `docs/Dockerfile` **multi-stage**: stage build (Python + MkDocs Material →
      `mkdocs build --strict`) → stage runtime (**nginx** sirviendo `site/` estático, sin toolchain). *(FR-001)*
- [X] T009 [US1] Crear `docs/nginx.conf`: sirve estáticos; **sin ACME/auto-HTTPS** (TLS lo termina el proxy del
      deploy; air-gap sin egress a Let's Encrypt). *(FR-023)*
- [X] T010 [US1] Añadir el servicio **`docs`** a `deploy/docker/compose.prod.yml` (imagen
      `basa-docs:<brand>-<version>`, perfiles normal+selfhosted) detrás del proxy/TLS del deploy, sin exponer
      egress nuevo (Principio VII); opcional: servicio de preview en el compose dev. *(FR-004, SC-002 — delta F1)*
- [X] T011 [US1] Documentar el enganche **k3s+Helm+Zarf v2** (020): la imagen del sitio entra en el bundle Zarf
      (SBOM + firma) igual que el resto de imágenes pinneadas. *(FR-004)*

**Checkpoint**: Imagen air-gapped 0-egress, servicio `docs` en el compose, enganche Zarf documentado.

---

## Phase 4: User Story 2 - Contenido de Distribuidor + Operador sembrado (Priority: P1)

**Goal**: Publicar las 9 secciones con contenido real, sembradas del corpus existente, conservando la leyenda
de estado; retirar/redirigir `DocsPage.tsx`.

**Independent Test**: Las 9 secciones existen con contenido real; las 3 piezas del corpus están migradas a sus
secciones sin perder 🟢/🟡/🔵; la doc de producto ya no vive en el frontend.

### Tests for User Story 2 ⚠️

- [X] T012 ⚠️ [P] [US2] Check de cobertura de secciones en `docs/tests/test_sections_present.*`: el sitio
      construido publica las 9 secciones (overview, install-deploy, white-label, administration, integrations,
      api-reference, compliance, operations, release-notes) con contenido no-placeholder. *(FR-005, SC-003)*
- [X] T013 ⚠️ [P] [US2] Check de conservación de la **leyenda de estado**: las páginas migradas del corpus
      preservan las marcas 🟢 HOY / 🟡 PARCIAL / 🔵 OBJETIVO. *(FR-006, SC-003)*

### Implementation for User Story 2

- [X] T014 [P] [US2] Migrar `basa-guardian/docs/whitelabel-deployment.md` → `docs/docs/install-deploy/**` +
      `docs/docs/white-label/**` (deploy: OpenTofu/secretos/estado; branding pack). *(FR-006, relación 020)*
- [X] T015 [P] [US2] Migrar `basa-guardian/docs/integration-surfaces.md` → `docs/docs/integrations/**`
      (superficies base_url/browser/mcp + matriz + gotchas). *(FR-006, relación 019)*
- [X] T016 [P] [US2] Migrar `basa-guardian/docs/compliance-policies.md` → `docs/docs/compliance/**`
      (GDPR/AI-Act, DPA, DSR, retención, panel DPO). *(FR-006, relación 005/008, Principio II)*
- [X] T017 [US2] Redactar **Overview & arquitectura** (`docs/docs/overview/**`): qué es el producto, stack en
      containers, pipeline (masking→…→unmask) — marca-neutro. *(FR-005)*
- [X] T018 [US2] Redactar **Administración** (`docs/docs/administration/**`): multi-tenant, RBAC (super/tenant-
      admin, compliance_officer, client), guardrails, budgets, SSO, licencias/seats. *(FR-007, relación 013/021)*
- [X] T019 [US2] Redactar **Operaciones & troubleshooting** (`docs/docs/operations/**`): runbook operativo +
      gotchas verificados (de `integration-surfaces.md`). *(FR-005)*
- [X] T020 [US2] Deprecar `frontend/src/pages/DocsPage.tsx`: redirección/enlace al sitio o retiro; la doc de
      producto deja de vivir en el bundle del frontend. *(FR-009, SC-003)*

**Checkpoint**: Sitio con contenido real de distribuidor+operador; corpus migrado; doc fuera del frontend.

---

## Phase 5: User Story 3 - White-label por config, sin fork (Priority: P1)

**Goal**: Branding por tokens de config (overlay `INHERIT`/`envsubst`), contenido marca-neutro, imagen trazable
por marca, 0 mención de motor/proveedor.

**Independent Test**: Construir con 2 marcas cambiando **sólo** tokens de branding; 0 líneas de contenido/tema
difieren; cada build produce `basa-docs:<brand>-<version>`; 0 menciones de motor en el HTML.

### Tests for User Story 3 ⚠️

- [X] T021 ⚠️ [P] [US3] Test de white-label en `docs/tests/test_whitelabel_no_fork.*`: construir marca A y
      marca B; afirmar que difieren **sólo** en tokens (site_name/logo/favicon/palette/extra.css) y **0** líneas
      de contenido/tema cambian. *(FR-010, FR-011, SC-004)*
- [X] T022 ⚠️ [P] [US3] Check de **naming neutro** en `deploy/release/checks/test_docs_neutral_naming.sh`:
      grep de nombres prohibidos sobre el HTML publicado → **falla** si aparece. La lista se comparte con
      `test_no_engine_name.sh` (020) e incluye Meta (constitución VII). *(FR-013, SC-004 — delta F2)*

### Implementation for User Story 3

- [X] T023 [US3] Definir el **brand-pack**: tokens `site_name`, `logo`, `favicon`, `palette`, `extra.css` en
      `docs/mkdocs.<brand>.yml` (overlay **`INHERIT`** sobre `docs/mkdocs.yml`), **derivado del brand-pack de
      la 020** (`deploy/branding/brand*.json` + `clients/<slug>/branding.env`) — una sola fuente de marca por
      cliente; assets por defecto marca-neutros en `docs/brand/`. *(FR-010, FR-011 — delta F3)*
- [X] T024 [US3] Parametrizar el tag de imagen **por marca** en el build: `basa-docs:<brand>-<version>` (una
      marca por instancia, config-as-data). *(FR-012)*
- [X] T025 [US3] Verificar que el contenido markdown se mantiene **marca-neutro** por defecto (sin nombres de
      producto hardcodeados en el corpus migrado). *(FR-011, FR-013)*

**Checkpoint**: 2 marcas desde config, imagen por marca, naming neutro verificado (never fork).

---

## Phase 6: User Story 4 - Búsqueda offline, nunca SaaS (Priority: P2)

**Goal**: Búsqueda contra índice local (lunr `offline`), sin buscador SaaS, funcionando con la red bloqueada.

**Independent Test**: Con la red bloqueada, buscar y obtener resultados sin egress; 0 integraciones SaaS en
config/HTML.

### Tests for User Story 4 ⚠️

- [X] T026 ⚠️ [P] [US4] Test de búsqueda offline en `docs/tests/test_search_offline.*`: con la red saliente
      bloqueada, la búsqueda resuelve contra el índice **local** (0 requests externos). *(FR-014, SC-005)*
- [X] T027 ⚠️ [P] [US4] Check anti-SaaS: **0** claves/endpoints de Algolia u otro buscador SaaS en config ni en
      el HTML publicado. *(FR-015, SC-005)*

### Implementation for User Story 4

- [X] T028 [US4] Activar la búsqueda **lunr built-in** de Material con el plugin `offline` (índice precomputado,
      embebido en la imagen; funciona sin backend de búsqueda). *(FR-014)*
- [X] T029 [US4] Documentar la opción **Pagefind** para el plan B (Starlight) como equivalente offline; dejar
      Algolia DocSearch **prohibido** por escrito. *(FR-014, FR-015)*

**Checkpoint**: Búsqueda offline verificada, sin SaaS, sin egress.

---

## Phase 7: User Story 5 - API reference single-source desde el OpenAPI (Priority: P2)

**Goal**: API reference auto-generado del OpenAPI de FastAPI + config reference de `.env.example`; sin derivar
las specs de Spec Kit.

**Independent Test**: Cambiar un endpoint/campo en el backend → reconstruir → el API reference publicado refleja
el cambio sin edición manual; 0 páginas auto-derivadas de `specs/0XX-*`.

### Tests for User Story 5 ⚠️

- [X] T030 ⚠️ [P] [US5] Test de **deriva** en `docs/tests/test_apiref_single_source.*`: alterar el OpenAPI
      (fixture) → reconstruir → el API reference publicado refleja el cambio (0 edición manual). *(FR-016, SC-006)*
- [X] T031 ⚠️ [P] [US5] Check anti-fuga: **0** páginas del sitio auto-derivadas de `specs/0XX-*/` (Spec Kit).
      *(FR-018, SC-006)*

### Implementation for User Story 5

- [X] T032 [US5] Generar el **API reference** en el build desde el **OpenAPI** del backend FastAPI (plugin de
      render OpenAPI, p.ej. `mkdocs-swagger-ui-tag`) → `docs/docs/api-reference/**`. *(FR-016)*
- [X] T033 [US5] Generar el **config/env reference** desde `.env.example` (una fuente de verdad para las
      variables). *(FR-017)*
- [X] T034 [US5] Documentar la regla: el contenido de producto es corpus **curado separado**; **NO** se
      auto-derivan las specs de Spec Kit (audiencias distintas + fuga de contexto interno). *(FR-018)*

**Checkpoint**: API/config reference single-source, sin deriva, sin fuga de las specs.

---

## Phase 8: User Story 6 - Versionado (mike) + i18n ES/EN (Priority: P2)

**Goal**: Versionado por release con `mike` + i18n ES/EN con `mkdocs-static-i18n`, con fallback explícito.

**Independent Test**: Publicar ≥2 versiones con `mike`; selector cambia entre ellas. Cambiar ES↔EN; página sin
traducción EN degrada con fallback, no 404.

### Tests for User Story 6 ⚠️

- [ ] T035 ⚠️ [P] [US6] Test de versionado en `docs/tests/test_versioning_i18n.*`: con ≥2 versiones publicadas
      por `mike`, el selector sirve cada versión; con i18n activo, el selector ES/EN sirve la variante correcta y
      una página sin EN degrada con **fallback explícito** (no 404). *(FR-019, FR-020, SC-007)*

### Implementation for User Story 6

- [ ] T036 [US6] Configurar **`mike`** (versión fijada) para publicar `1.x`/`latest`/`dev` con selector de
      versión. *(FR-019)*
- [ ] T037 [US6] Configurar **`mkdocs-static-i18n`** (ES primario, EN segundo) con selector de idioma y
      **fallback explícito** al idioma primario para páginas sin traducción. *(FR-020)*
- [ ] T038 [US6] Cablear **Release notes** (`docs/docs/release-notes/**`) al flujo de `mike` (una entrada por
      versión). *(FR-005, FR-019)*

**Checkpoint**: Selector de versión + selector de idioma funcionando, con fallback.

---

## Phase 9: User Story 7 - Docset end-user (clínico) como roadmap (Priority: P3)

**Goal**: Documentar el segundo docset (clínico) como roadmap aditivo; NO entregarlo.

**Independent Test**: La arquitectura contempla un segundo nav-tree (clínico) y lo marca NO implementado/roadmap;
0 contenido clínico en v1.

### Tests / Implementation for User Story 7

- [ ] T039 [US7] Documentar en `content-map.md` el docset **end-user (clínico)** como **roadmap P3**: reusa
      contenedor + white-label + i18n con audiencia/tono propios (segundo nav-tree); marcarlo **NO
      implementado** y **no** publicar contenido clínico en v1. *(FR-021, SC-008)*

**Checkpoint**: Docset clínico documentado como roadmap; ninguna promesa de hecho.

---

## Phase N: Polish & Cross-Cutting Concerns

- [ ] T040 [P] [POLISH] Generar `quickstart.md`: build local (`mkdocs serve`), `mkdocs build --strict`, test de
      0 egress, construir + publicar una marca, cambiar versión/idioma.
- [ ] T041 [POLISH] Verificación end-to-end (Principio VII): build `--strict` → imagen `basa-docs:<brand>-…` →
      **0 egress** con red bloqueada → **2 marcas** desde config → selectores de versión/idioma → naming neutro.
      *(SC-001..SC-007)*
- [ ] T042 [P] [POLISH] Confirmar **decisión de framework** documentada (`research.md`): MkDocs primario /
      Starlight+Pagefind plan B con disparador de migración; contra de Material en modo mantenimiento. *(FR-022, SC-008)*
- [ ] T043 [POLISH] Documentar las limitaciones conocidas (Material en modo mantenimiento; `mike` no
      first-party; API reference hereda huecos de un OpenAPI incompleto) y actualizar `spec/plan/tasks/content-map`
      (Dev Workflow — Documentación viva).

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: sin dependencias (más allá del corpus `docs/*.md` como semilla).
- **Foundational (Phase 2)**: depende de Setup. Fija la IA (content-map) y el build `--strict` 0-egress;
  bloquea US1/US2/US4.
- **US1 (Phase 3)**: depende de Foundational. Empaquetado air-gapped. MVP.
- **US2 (Phase 4)**: depende de Foundational (IA) + US1 (imagen donde sirve el contenido).
- **US3 (Phase 5)**: depende de US1 (imagen por marca) + US2 (contenido marca-neutro).
- **US4 (Phase 6)**: depende de Foundational (build offline) + US1 (imagen).
- **US5 (Phase 7)**: depende de Setup (esqueleto) + del OpenAPI del backend. Independiente de US2/US3.
- **US6 (Phase 8)**: depende de US2 (contenido a versionar/traducir).
- **US7 (Phase 9)**: documentación/roadmap; depende de la IA (US2).
- **Polish (Phase N)**: depende de los user stories deseados.

### User Story Dependencies

- **US1 (P1)**: tras Foundational. Contenedor air-gapped (MVP de empaquetado).
- **US2 (P1)**: tras Foundational + US1. Contenido (valor).
- **US3 (P1)**: tras US1 + US2. White-label sin fork.
- **US4 (P2)**: tras Foundational + US1. Búsqueda offline.
- **US5 (P2)**: tras Setup + OpenAPI. API reference single-source (independiente).
- **US6 (P2)**: tras US2. Versionado + i18n.
- **US7 (P3)**: tras US2. Roadmap.

### Within Each User Story

- Tests (⚠️) escritos y FALLANDO antes de implementar.
- El build `--strict` 0-egress (Foundational) antes de empaquetar la imagen (US1).
- El contenido migrado (US2) antes del versionado/i18n (US6) y del white-label de contenido (US3).

### Parallel Opportunities

- Setup: T002 [P].
- Tests de cada story marcados [P] corren en paralelo (archivos distintos).
- Migración del corpus (T014/T015/T016) [P]: tres archivos distintos a tres secciones distintas.
- US5 (API reference) puede desarrollarse en paralelo a US2/US3 (otra fuente: el OpenAPI, no el corpus).

---

## Parallel Example: User Story 2 (migración del corpus)

```bash
# Migraciones de US2 juntas (archivos/fuentes distintos):
Task: "Migrar whitelabel-deployment.md → docs/docs/install-deploy/** + white-label/** en T014"
Task: "Migrar integration-surfaces.md → docs/docs/integrations/** en T015"
Task: "Migrar compliance-policies.md → docs/docs/compliance/** en T016"
```

---

## Implementation Strategy

### MVP First (US1 + US2 + US3)

1. Phase 1 Setup → Phase 2 Foundational (IA fijada + build `--strict` 0-egress verde).
2. Phase 3 US1 (contenedor air-gapped) → imagen 0-egress en el compose.
3. Phase 4 US2 (contenido sembrado) → las 9 secciones con contenido real; doc fuera del frontend.
4. Phase 5 US3 (white-label por config) → imagen por marca, naming neutro.
5. **STOP & VALIDATE**: el sitio funciona **offline** (0 egress), publica el docset de distribuidor+operador,
   y se white-labelea con sólo cambiar tokens (never fork).

### Incremental Delivery

1. Foundational → IA + build 0-egress.
2. US1 + US2 + US3 → **MVP**: sitio air-gapped, contenido, white-label.
3. US4 → búsqueda offline.
4. US5 → API reference single-source.
5. US6 → versionado + i18n.
6. US7 → docset clínico (roadmap).

### Parallel Team Strategy

Tras Foundational: Dev A → US1 (empaquetado air-gapped) + US3 (white-label); Dev B → US2 (migración + redacción
del contenido); Dev C → US5 (API reference desde OpenAPI, fuente independiente). US4/US6 los cierra quien
termine su rama primero. US7 lo documenta quien cierra la IA.

---

## Notes

- [P] = archivos distintos, sin dependencias.
- [Story] mapea cada tarea a su user story para trazabilidad.
- Verificar que los tests ⚠️ fallan antes de implementar (0 egress, white-label, naming, deriva API, búsqueda).
- **Semilla del contenido**: `basa-guardian/docs/whitelabel-deployment.md`, `.../integration-surfaces.md`,
  `.../compliance-policies.md`; el **API reference** sale del **OpenAPI** del backend FastAPI (no a mano).
- **Honestidad SDD**: GREENFIELD; el docset end-user (clínico) y el plan B (Starlight+Pagefind) son **roadmap
  documentado**, no entregables de v1. El framework decidido es **MkDocs + Material** (air-gap de primera clase
  + cero toolchain nueva), con el contra de estar en **modo mantenimiento** declarado.
- **Never fork**: el white-label es config-as-data (overlay `INHERIT`/`envsubst`); el contenido markdown es
  marca-neutro; una imagen por marca (`basa-docs:<brand>-<version>`).
- **Prohibiciones load-bearing**: 0 buscador SaaS (Algolia), 0 derivación de las specs de Spec Kit, 0 ACME en
  air-gap (nginx/`auto_https off`).
