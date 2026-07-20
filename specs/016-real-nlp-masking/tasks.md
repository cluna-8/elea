---
description: "Task list for feature 016 — Real NLP Masking & Entity Detection Hardening"
---

# Tasks: Real NLP Masking & Entity Detection Hardening

**Input**: Design documents from `/specs/016-real-nlp-masking/`

**Prerequisites**: plan.md (required), spec.md (required), research.md, data-model.md, contracts/,
quickstart.md. Depende de **013** (identidad/APIKey) y **014** (BasaGuardrail, `basa_guardian_policy`,
`custom_auth` — esta feature extiende esos módulos, no los reescribe).

**Tests**: SÍ incluidos. La constitución exige tests para lógica no trivial (Dev Workflow — Tested &
Verified) y esta feature es security-critical (fail-closed, reversibilidad de masking). Los tests
marcados ⚠️ se escriben ANTES de la implementación y deben FALLAR primero.

**Organization**: Tareas agrupadas por user story para implementación y test independientes.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Puede correr en paralelo (archivos distintos, sin dependencias)
- **[Story]**: US1..US4 (o SETUP/FOUND/POLISH)
- Rutas de archivo exactas incluidas

## Path Conventions

- Extensiones del motor: `litellm/extensions/` (montadas en el contenedor LiteLLM)
- Imagen NLP nueva: `presidio-analyzer/`
- Backend (camino panel/playground): `backend/src/services/`
- Config: `docker-compose.yml`, `.env.example`
- Tests: `tests/contract/`, `tests/integration/`, `backend/tests/test_policy_unit.py` (unit puro, ya existente
  de la 014 — se extiende en vez de crear un archivo nuevo)

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Levantar el sidecar NLP y el cableado de configuración que todo lo demás necesita.

- [x] T001 [SETUP] Crear `presidio-analyzer/Dockerfile` (imagen propia: FastAPI fino sobre la librería
      `presidio-analyzer` + spaCy `es_core_news_md`, NO la imagen server oficial de Microsoft — más
      control sobre el contrato HTTP exacto, ver `presidio-analyzer/app.py`) y
      `presidio-analyzer/conf/es.yaml` (`NlpEngineConfig`). *(research.md §1-2)*
- [x] T002 [SETUP] Agregar el servicio `presidio-analyzer` a `docker-compose.yml`: build desde
      `presidio-analyzer/`, en `basa-network`, **sin** puerto publicado al host, healthcheck sobre su
      endpoint de salud. *(research.md §2)*
- [x] T003 [P] [SETUP] Agregar `PRESIDIO_ANALYZER_URL` (+ `BASA_ENTITY_REGION`) a `.env.example`.
      Pendiente: documentar en `README.md` (sección Quickstart/tabla de puertos, naming neutro
      Principio VII) — ver T034.
- [x] T004 [P] [SETUP] `backend/tests/test_policy_unit.py` ya existía (de la 014, `test_mask_is_reversible...`
      etc.) — se extendió con los tests de las funciones nuevas en vez de crear un archivo espejo nuevo.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Las funciones puras compartidas de las que dependen las 4 historias de usuario. Nada de
Fase 3+ puede empezar hasta cerrar esto.

**⚠️ CRITICAL**: Ningún user story puede empezar hasta cerrar esta fase.

- [x] T005 ⚠️ [P] [FOUND] Unit tests de `resolve_overlaps` en `backend/tests/test_policy_unit.py`:
      rangos solapados con distinta longitud/score, caso sin solapamiento (no-op), caso de contención
      total, **y caso de 3+ solapados en cadena** (agregado tras encontrar que la comparación par-a-par
      simple no lo garantiza — ver T006). *(contracts/policy-library-functions.md, data-model.md)*
- [x] T006 [FOUND] Implementar `resolve_overlaps(entities) -> entities` en
      `litellm/extensions/basa_guardian_policy.py`. **Corrección de diseño**: la primera versión
      (comparación par-a-par contra el último aceptado) no resolvía correctamente 3+ entidades solapadas
      en cadena; se reemplazó por clustering de intervalos (componentes conexas del grafo de
      solapamiento) — invariante de no-solapamiento garantizada en todos los casos. *(FR-009, research.md §5)*
- [x] T007 ⚠️ [P] [FOUND] Unit tests de `resolve_entity_action` en `backend/tests/test_policy_unit.py`:
      tipo configurado `MASK`/`BLOCK`, tipo ausente → default `MASK`, valor inválido en config → default
      `MASK`.
- [x] T008 [FOUND] Implementar `resolve_entity_action(entity_type, entity_configs)` en
      `litellm/extensions/basa_guardian_policy.py`. *(FR-005, FR-008, research.md §6)*
- [x] T009 ⚠️ [P] [FOUND] Unit tests de `build_ad_hoc_recognizers` en `backend/tests/test_policy_unit.py`:
      región `eu` (default) → solo `PASSPORT` presente (NIF/NIE español son built-in de Presidio, no se
      reimplementan acá), región `latam_ar` → agrega `DNI`/`CUIL`, `custom_names` vacío → sin
      recognizer deny-list, con valores → recognizer deny-list correcto, región desconocida → vacío.
- [x] T010 [FOUND] Implementar `build_ad_hoc_recognizers(custom_names, region="eu")` en
      `litellm/extensions/basa_guardian_policy.py` (`STRUCTURED_ID_PATTERNS_BY_REGION`), reemplazando el
      diccionario `PII_PATTERNS` actual de ese archivo como única fuente de patrones estructurados **por
      región** — no un país fijo. **Corrección post-review**: el despliegue objetivo es Europa (España
      primero), no Argentina — región `eu` activa por default. *(FR-003, SC-006, research.md §3)*
- [x] T011 [FOUND] Definir `NlpUnavailableError` (excepción dedicada) en
      `litellm/extensions/basa_guardian_policy.py`.
- [x] T012 ⚠️ [P] [FOUND] Unit test de `presidio_analyze` en `backend/tests/test_policy_unit.py`
      con un cliente HTTP mockeado: éxito → `DetectedEntity[]` normalizada y pasada por
      `resolve_overlaps`; timeout/5xx/body inesperado → levanta `NlpUnavailableError` (NUNCA `[]`); texto
      vacío → cortocircuita sin llamar a la red. *(FR-004, contracts/presidio-analyzer-http.md)*
- [x] T013 [FOUND] Implementar `presidio_analyze(text, analyzer_url, custom_names, region="eu") ->
      DetectedEntity[]` (nuevo `AnalyzeFn`) en `litellm/extensions/basa_guardian_policy.py`: `httpx`
      async, timeout 2s, arma el body con `build_ad_hoc_recognizers` (+ `entities: null` para recibir
      todo lo que el Analyzer soporte, no una lista fija), normaliza la respuesta, aplica `resolve_overlaps`.

**Checkpoint**: librería pura verde (T005-T013) → los user stories pueden empezar.

---

## Phase 3: User Story 1 - Detección de PERSON sin prefijo (Priority: P1) 🎯 MVP

**Goal**: El firewall real detecta nombres de persona en texto conversacional natural usando NLP,
sin depender de un prefijo de título.

**Independent Test**: enviar un prompt con un nombre sin prefijo a través del firewall; verificar
placeholder en lo que ve el motor/LLM y el valor real restaurado en la respuesta final.

### Tests for User Story 1 ⚠️

- [ ] T014 ⚠️ [P] [US1] **Pendiente** — Integration test en `tests/integration/test_person_detection.py`:
      prompt "Juan Pérez tiene turno el jueves" a través de `BasaGuardrail.async_pre_call_hook` +
      `async_post_call_success_hook` contra el contenedor `presidio-analyzer` real → placeholder en el
      body saliente, nombre real restaurado en la respuesta. Necesita el stack real levantado (no se
      pudo correr en este entorno — ver quickstart.md paso 1). *(spec.md US1, acceptance scenarios 1-3)*

### Implementation for User Story 1

- [x] T015 [US1] En `litellm/extensions/basa_guardrail.py::async_pre_call_hook`: `policy.presidio_analyze`
      reemplaza a `policy.default_analyze` en el camino real cuando `PRESIDIO_ANALYZER_URL` está seteada;
      `default_analyze` queda como fallback de modo dev con warning explícito si no lo está. *(FR-001, FR-002)*
- [x] T016 [US1] `custom_names` viaja desde la identidad resuelta por `custom_auth.py` (T020/T021 de
      US2, implementadas junto con esto) hasta la llamada de `presidio_analyze` en `basa_guardrail.py`.
- [ ] T017 [P] [US1] **Pendiente** — Ejecutar el paso 1 de `quickstart.md` (validación manual con `claude`
      real contra el gateway local) y documentar el resultado en `implementation-notes.md`.

**Checkpoint**: US1 entregable y demostrable de forma independiente (nombres sin prefijo se enmascaran).

---

## Phase 4: User Story 2 - Enforcement real de `entity_configs` (Priority: P1) 🎯 MVP

**Goal**: La política activa (`MASK`/`BLOCK` por tipo de entidad) gobierna de verdad el tráfico del
firewall real.

**Independent Test**: configurar un tipo como `BLOCK`, enviar una request que lo contenga, verificar
rechazo con motivo auditable; configurar otro tipo como `MASK`, verificar que sigue el flujo normal.

### Tests for User Story 2 ⚠️

- [ ] T018 ⚠️ [P] [US2] **Pendiente** — Contract test en `tests/contract/test_custom_auth_entity_configs.py`:
      la query de identidad de `custom_auth.py` devuelve `entity_configs` de la `SecurityPolicy` activa.
      Necesita el motor LiteLLM real (`prisma_client`) — no se pudo correr en este entorno.
- [ ] T019 ⚠️ [P] [US2] **Pendiente** — Integration test en `tests/integration/test_entity_enforcement.py`:
      entidad `BLOCK` → request rechazada antes del LLM con motivo `blocked_entity_type`; entidad `MASK` →
      sigue normal; tipo no configurado → default `MASK` (no ignorado, no bloqueado). *(spec.md US2,
      acceptance scenarios 1-4)*

### Implementation for User Story 2

- [x] T020 [US2] Extendida `_IDENTITY_SQL` en `litellm/extensions/custom_auth.py` con subqueries a
      `security_policies` (activa, por tenant) y `guardians` (pii_masking activo) trayendo `entity_configs`
      y `custom_names`. *(research.md §6)*
- [x] T021 [US2] `entity_configs`/`custom_names` viajan en el dict de identidad (`metadata.basa`, junto a
      `redact_enabled`) en `litellm/extensions/custom_auth.py`.
- [x] T022 [US2] En `litellm/extensions/basa_guardrail.py::async_pre_call_hook`: preview de entidades
      sobre el texto completo (un solo pase de detección) resuelto vía `resolve_entity_action` ANTES de
      tocar el body — si alguna es `BLOCK`, retorna motivo de bloqueo nombrando los tipos (sin valores),
      sin enmascarar nada primero; si no hay bloqueos, sigue el flujo `MASK` con `PlaceholderMap`.
      *(FR-005, FR-006, FR-007)*
- [x] T023 [US2] **No requirió cambios** — `litellm/extensions/basa_audit_logger.py:85` ya lee
      `basa_compliance.status` de forma genérica (`.get("status") or "passed"`); el nuevo motivo
      `blocked_entity_type` (seteado en `basa_guardrail.py`) aparece en el audit log sin tocar este
      archivo. La tarea, tal como estaba escrita, asumía que hacía falta una whitelist explícita — no es
      el caso. *(FR-011)*

**Checkpoint**: US1 + US2 = MVP entregable — detección real + enforcement real de la política.

---

## Phase 5: User Story 3 - NLP real con fail-closed (Priority: P2)

**Goal**: El motor NLP real es la fuente primaria de detección; su indisponibilidad rechaza la request
en vez de degradar silenciosamente.

**Independent Test**: con el Analyzer caído, verificar que el 100% de las requests afectadas se
rechazan explícitamente (ninguna procesa con detección degradada).

### Tests for User Story 3 ⚠️

- [ ] T024 ⚠️ [P] [US3] **Pendiente** — Contract test en `tests/contract/test_presidio_analyzer_contract.py`
      contra el contenedor real `presidio-analyzer`: health check, `ES_NIF` built-in responde para
      `supported_language="es"`, recognizer `PASSPORT` ad-hoc, recognizer deny-list de `custom_names`,
      shape de respuesta. Cubierto parcialmente por los checks nuevos en `contract_checks.py` (T033) si
      `PRESIDIO_ANALYZER_URL` está seteada al correrlo — falta el test dedicado en `tests/contract/`.
      *(contracts/presidio-analyzer-http.md)*
- [ ] T025 ⚠️ [P] [US3] **Pendiente** — Integration test en `tests/integration/test_nlp_failclosed.py`:
      apuntar `PRESIDIO_ANALYZER_URL` a un endpoint caído/inexistente → la request se rechaza con motivo
      `nlp_unavailable`. El comportamiento de `presidio_analyze` ya está cubierto por unit tests mockeados
      (T012); falta el integration test end-to-end contra `BasaGuardrail` real. *(FR-004, SC-004)*

### Implementation for User Story 3

- [x] T026 [US3] En `litellm/extensions/basa_guardrail.py::async_pre_call_hook`: `NlpUnavailableError`
      (tanto en el preview de US2 como en el masking) se traduce al motivo de bloqueo `nlp_unavailable`
      por el mismo canal que AI-Act/secretos (helper `_nlp_unavailable_block`).
- [x] T027 [US3] **No requirió cambios** — mismo motivo que T023: `basa_audit_logger.py` ya generaliza
      cualquier `basa_compliance.status`, incluido `blocked_nlp_unavailable`. *(FR-011)*
- [ ] T028 [P] [US3] **Pendiente** — En `backend/src/services/presidio_service.py::analyze_text_http`:
      dejar de atrapar la excepción y devolver `[]` (fail-open heredado) — debe **propagar** y aceptar
      un parámetro `ad_hoc_recognizers` en el payload. Fuera del alcance de esta sesión (foco: camino de
      firewall real, no el panel/playground legacy). *(research.md §7)*
- [ ] T029 [US3] **Pendiente** — En `backend/src/services/guardian_service.py`: eliminar el catálogo
      `PATTERNS` propio; construir `ad_hoc_recognizers` reusando `build_ad_hoc_recognizers` (thin wrapper
      Python si el módulo no es directamente importable entre backend y motor). *(FR-012, SC-006)*

**Checkpoint**: motor NLP real es la fuente primaria en ambos caminos (firewall + panel); indisponibilidad
nunca se traduce en detección degradada silenciosa.

---

## Phase 6: User Story 4 - Integridad ante coincidencias solapadas (Priority: P2)

**Goal**: El texto enmascarado nunca se corrompe cuando dos detecciones se solapan.

**Independent Test**: texto sintético con rangos solapados intencionales → salida válida, un solo
placeholder por rango disputado, reversible.

### Tests for User Story 4 ⚠️

- [x] T030 ⚠️ [P] [US4] Regression test en `backend/tests/test_policy_unit.py` sobre `resolve_overlaps`
      directamente: dos entidades solapadas de tipos distintos (score/largo distinto) → un único
      resultado válido; **y el caso de 3+ entidades solapadas en cadena** que motivó la corrección de
      diseño de T006. *(spec.md US4, acceptance scenarios 1-2)*
      **Pendiente**: un test yendo end-to-end por `mask_text`/`mask_body` (no solo `resolve_overlaps`
      aislada) con un `AnalyzeFn` que devuelva entidades solapadas de verdad.
- [ ] T031 ⚠️ [P] [US4] **Pendiente** — Extender `backend/tests/test_policy_unit.py` (carry-split, ya
      existente de la 014): confirmar que el carry-split sigue siendo válido cuando el placeholder
      resultante viene de una entidad que ganó una resolución de solapamiento (largo de placeholder
      distinto al de antes).

### Implementation for User Story 4

- [x] T032 [US4] **Ubicación real distinta a la planeada**: en vez de cablear `resolve_overlaps()` dentro
      de `mask_text`/`mask_body`, se llama dentro de las funciones `AnalyzeFn` (`default_analyze` y
      `presidio_analyze`) antes de devolver sus entidades — `mask_text`/`mask_body` reciben entidades ya
      deduplicadas sin necesidad de conocer `resolve_overlaps`. Efecto equivalente, menos acoplamiento
      (cualquier `AnalyzeFn` nuevo es responsable de sus propios solapamientos). *(FR-009, FR-010)*

**Checkpoint**: las 4 historias completas — detección real, enforcement real, fail-closed, e integridad
del texto enmascarado.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Verificación de contrato ampliada, documentación y cierre de la feature.

- [x] T033 [P] [POLISH] Extendido `litellm/extensions/contract_checks.py` con checks de
      `resolve_overlaps`/`resolve_entity_action`/`build_ad_hoc_recognizers` (región `eu` sin DNI/CUIL) y,
      si `PRESIDIO_ANALYZER_URL` está seteada al correrlo, conectividad real al Analyzer + fail-closed
      contra una URL inválida. *(quickstart.md paso 5)*
- [ ] T034 [P] [POLISH] **Pendiente** — Actualizar `README.md` (tabla de compatibilidad de proveedores /
      arquitectura del repo) para reflejar el nuevo servicio NLP, con naming neutro (Principio VII), y
      documentar `PRESIDIO_ANALYZER_URL`/`BASA_ENTITY_REGION` en la sección Quickstart.
- [ ] T035 [POLISH] **Pendiente** — Correr la suite completa contra el stack real
      (`docker compose run --rm --no-deps backend pytest tests/ -q`) y confirmar 0 regresiones sobre lo
      heredado de 013/014/019/021. Localmente solo se corrió `backend/tests/test_policy_unit.py` (27/27
      verde, sin Docker) — falta la suite completa contra Postgres real. *(quickstart.md paso 6)*
- [ ] T036 [POLISH] **Pendiente** — Escribir `specs/016-real-nlp-masking/implementation-notes.md` (mismo
      patrón que 013/014) y actualizar `specs/ROADMAP-guardian.md`: marcar 016 como Implementada (hoy
      dice "Roadmap").

---

## Dependencies & Execution Order

- **Setup (T001-T004)** → bloquea todo lo demás (el Analyzer tiene que existir para poder testear contra
  algo real, aunque los unit tests puros de Foundational no lo necesitan levantado).
- **Foundational (T005-T013)** → bloquea Fases 3-6. Es la librería pura compartida.
- **US1 (T014-T017)** y **US2 (T018-T023)** son P1, **independientes entre sí** una vez cerrada
  Foundational — pueden desarrollarse en paralelo por personas distintas, aunque T016 tiene una
  dependencia blanda con T021 (de dónde sale `custom_names`/`entity_configs` en la identidad).
- **US3 (T024-T029)** depende de Foundational y de que US1 ya haya cableado `presidio_analyze` como
  ruta real (T015) — technically puede empezar en paralelo si se mockea esa integración, pero el
  contract test T024 necesita el servicio de Setup arriba.
- **US4 (T030-T032)** depende solo de Foundational (T006 `resolve_overlaps`) — es independiente de
  US1/US2/US3, puede hacerse en cualquier momento después del checkpoint de Foundational.
- **Polish (T033-T036)** al final, depende de todas las historias.

## Parallel Execution Examples

Tras cerrar Foundational (T005-T013), con 3 personas del equipo de seguridad/guardianes:
```
Persona A: T014-T017 (US1 — detección)
Persona B: T018-T023 (US2 — enforcement)
Persona C: T030-T032 (US4 — integridad) en paralelo, sin dependencias cruzadas con A/B
```
US3 (T024-T029) conviene arrancarlo después de que A cierre T015 (para no mockear dos veces el mismo
cableado de `presidio_analyze`).

Dentro de Foundational, los tests marcados `[P]` (T005, T007, T009, T012) pueden escribirse en
paralelo por ser archivos/funciones independientes, todos ANTES de sus implementaciones correspondientes.

## Implementation Strategy

**MVP = US1 + US2** (ambas P1): con eso el firewall real ya detecta nombres sin prefijo Y respeta
`MASK`/`BLOCK` configurado — es la primera versión que un compliance officer puede confiar como "hace lo
que dice que hace". US3 (fail-closed real) y US4 (integridad ante solapamientos) son endurecimientos que
pueden entregarse incrementalmente después sin romper el MVP.
