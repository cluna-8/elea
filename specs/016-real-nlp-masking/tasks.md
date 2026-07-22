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
- [x] T003 [P] [SETUP] Agregar `NLP_ANALYZER_URL` (+ `BASA_ENTITY_REGION`) a `.env.example`.
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

- [x] T014 ⚠️ [P] [US1] Implementado como `test_t014_guardrail_masks_person_without_title_prefix` en
      `backend/tests/e2e/test_guardrail_behavior_e2e.py` (no en `tests/integration/` como decía el nombre
      original — necesita el motor real corriendo, vía `docker exec`): `BasaGuardrail().async_pre_call_hook()`
      con "Juan Pérez tiene turno el jueves" → placeholder presente, sin bloqueo. Corrido contra el stack
      real (`nlp-analyzer` + litellm). *(spec.md US1, acceptance scenarios 1-3)*

### Implementation for User Story 1

- [x] T015 [US1] En `litellm/extensions/basa_guardrail.py::async_pre_call_hook`: `policy.presidio_analyze`
      reemplaza a `policy.default_analyze` en el camino real cuando `NLP_ANALYZER_URL` está seteada;
      `default_analyze` queda como fallback de modo dev con warning explícito si no lo está. *(FR-001, FR-002)*
- [x] T016 [US1] `custom_names` viaja desde la identidad resuelta por `custom_auth.py` (T020/T021 de
      US2, implementadas junto con esto) hasta la llamada de `presidio_analyze` en `basa_guardrail.py`.
- [x] T017 [P] [US1] Validado de forma equivalente sin key real de Anthropic (no disponible en este
      entorno): T014 ejercita el mismo hook (`async_pre_call_hook`) contra el stack real, confirmando
      placeholder + no-bloqueo. Documentado en `implementation-notes.md`.

**Checkpoint**: US1 entregable y demostrable de forma independiente (nombres sin prefijo se enmascaran).

---

## Phase 4: User Story 2 - Enforcement real de `entity_configs` (Priority: P1) 🎯 MVP

**Goal**: La política activa (`MASK`/`BLOCK` por tipo de entidad) gobierna de verdad el tráfico del
firewall real.

**Independent Test**: configurar un tipo como `BLOCK`, enviar una request que lo contenga, verificar
rechazo con motivo auditable; configurar otro tipo como `MASK`, verificar que sigue el flujo normal.

### Tests for User Story 2 ⚠️

- [x] T018 ⚠️ [P] [US2] Implementado como `test_t018_custom_auth_resolves_entity_configs_from_real_db` en
      `backend/tests/e2e/test_guardrail_behavior_e2e.py` — `prisma_client` es un global de proceso que solo
      existe en el litellm ya corriendo (no se puede instanciar vía `docker exec python3 -c` en un
      subprocess nuevo), así que se verifica vía HTTP real (`gw.post("/v1/messages", ...)`) contra una
      `SecurityPolicy`/`APIKey` seedeada: `CREDIT_CARD: BLOCK` → 400 con el tipo nombrado.
- [x] T019 ⚠️ [P] [US2] Implementado como `test_t019_guardrail_blocks_entity_configured_as_block` en
      `backend/tests/e2e/test_guardrail_behavior_e2e.py`: entidad `BLOCK` rechazada, entidad `MASK` sigue
      normal (dos identidades fake vía `docker exec` sobre el hook real). *(spec.md US2, acceptance
      scenarios 1-4)*

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
      `NLP_ANALYZER_URL` está seteada al correrlo — falta el test dedicado en `tests/contract/`.
      *(contracts/presidio-analyzer-http.md)*
- [x] T025 ⚠️ [P] [US3] Implementado como `test_t025_guardrail_fails_closed_when_presidio_unavailable` en
      `backend/tests/e2e/test_guardrail_behavior_e2e.py`: monkeypatch de `basa_guardrail._PRESIDIO_URL` a
      un puerto cerrado → bloqueo con motivo `nlp_unavailable` confirmado end-to-end contra `BasaGuardrail`
      real. *(FR-004, SC-004)*

### Implementation for User Story 3

- [x] T026 [US3] En `litellm/extensions/basa_guardrail.py::async_pre_call_hook`: `NlpUnavailableError`
      (tanto en el preview de US2 como en el masking) se traduce al motivo de bloqueo `nlp_unavailable`
      por el mismo canal que AI-Act/secretos (helper `_nlp_unavailable_block`).
- [x] T027 [US3] **No requirió cambios** — mismo motivo que T023: `basa_audit_logger.py` ya generaliza
      cualquier `basa_compliance.status`, incluido `blocked_nlp_unavailable`. *(FR-011)*
- [x] T028 [P] [US3] `presidio_service.py::analyze_text_http` reescrito: ya no atrapa la excepción y
      devuelve `[]` (fail-open heredado) — ahora levanta `NlpUnavailableError`; acepta `custom_names`/`region`
      y construye `ad_hoc_recognizers` vía `policy.build_ad_hoc_recognizers`. *(research.md §7)*
- [x] T029 [US3] `guardian_service.py`: eliminado el catálogo `PATTERNS` propio de `presidio_service.py`
      (importa `basa_guardian_policy` vía el mismo sys.path trick que `gateway.py`); `get_or_create_default_guardians`
      migra el catálogo por defecto de Argentina (`DNI`/`CUIL`) a EU on-read (mismo patrón que la migración
      de `custom_names`); degradación a regex de dev ahora **visible** (trigger `DEGRADED` auditado), nunca
      silenciosa. *(FR-012, SC-006)*

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
- [x] T031 ⚠️ [P] [US4] Implementado como
      `test_stream_unmask_survives_overlap_resolution_with_different_length` en `backend/tests/test_policy_unit.py`:
      entidades solapadas (`ID` vs `ES_NIF`) enmascaradas vía `policy.mask_text`, texto partido en CADA
      posición posible, round-trip exacto confirmado en todas. Este test **expuso** que `mask_text` no
      llamaba `resolve_overlaps()` por sí mismo (confiaba en que el `analyze` inyectado ya lo hubiera
      hecho) — corregido: `mask_text` ahora resuelve solapamientos internamente (defensa en profundidad).

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
      si `NLP_ANALYZER_URL` está seteada al correrlo, conectividad real al Analyzer + fail-closed
      contra una URL inválida. *(quickstart.md paso 5)*
- [x] T034 [P] [POLISH] `README.md` actualizado: tabla de Quickstart con el servicio NLP (naming neutro,
      sin puerto al host) y `NLP_ANALYZER_URL`/`BASA_ENTITY_REGION`; conteo de tests de la suite actualizado.
- [x] T035 [POLISH] Suite completa corrida DENTRO del container real del backend
      (`docker compose run --rm --no-deps backend pytest tests/ -q`): **293 passed, 10 skipped**, 0
      regresiones sobre 013/014/019/021. *(quickstart.md paso 6)*
- [x] T036 [POLISH] `specs/016-real-nlp-masking/implementation-notes.md` escrito (mismo patrón que 013/014);
      `specs/ROADMAP-guardian.md` actualizado: 016 marcada "Lista para merge".

---

## Phase 8: User Story 5 - Catálogo de entidades custom con asistente de IA (Priority: P2)

**Goal**: Un compliance officer suma tipos de entidad nuevos (regex + contexto) sin deploy, con un
asistente de IA que redacta el borrador — pero activar algo siempre requiere revisión humana explícita.

**Independent Test**: crear una entidad custom con un patrón conocido y confirmar que el firewall real
la detecta; confirmar que un patrón catastrófico (IA o manual) nunca llega a persistirse.

**Nota de alcance**: esta historia se construyó fuera de la secuencia original (pedida por el usuario
después de cerrar US1-US4) — los tasks de abajo documentan lo ya hecho y lo pendiente encontrado en
review, para que quede trazable igual que el resto de la spec.

### Implementación (ya hecha)

- [x] T037 [US5] `backend/src/services/entity_catalog_service.py`: `validate_pattern_safety` (heurística
      estática de cuantificadores anidados + ejecución real en proceso `spawn` con timeout — no un hilo,
      el motor `re` no libera el GIL durante backtracking catastrófico; no el módulo `regex`, que tiene
      un motor de matching distinto al que corre en producción). *(FR-015, SC-007)*
- [x] T038 [US5] `draft_entity`: arma el borrador vía el mismo `AIEngineClient` que ya usa el backend;
      valida seguridad y corre `test_pattern` ANTES de devolver el borrador; nunca persiste nada. *(FR-014)*
- [x] T039 [US5] `create_custom_entity`/`list_custom_entities`/`delete_custom_entity` + endpoints
      `backend/src/api/guardians.py::/custom-entities/*` (draft sin persistir, create con revalidación
      SIEMPRE, list, delete). Auto-provisiona el Guardian `pii_masking` si no existe. *(FR-013)*
- [x] T040 [US5] Cableado hasta la detección real: `custom_auth.py` trae `custom_entities` (activas) del
      Guardian; `build_ad_hoc_recognizers`/`presidio_analyze` las suma a los `ad_hoc_recognizers`;
      `basa_guardrail.py` las pasa a través. Probado end-to-end contra el Presidio real (no mocks).
- [x] T041 [US5] Fix de precisión encontrado probando en vivo: Presidio compila patrones con
      `re.IGNORECASE` por default — el propio patrón de `PASSPORT` matcheaba la palabra "pasaporte".
      `global_regex_flags` case-sensitive en `presidio-analyzer/app.py` para recognizers con patrones.

### Tests (ya hechos)

- [x] T042 [P] [US5] Unit tests de `validate_pattern_safety`/`test_pattern`/`build_ad_hoc_recognizers`
      con `custom_entities` en `backend/tests/unit/test_entity_catalog_service.py` +
      `backend/tests/test_policy_unit.py` (45 tests). Incluye regresión de los 2 findings de review
      (draft_entity 500 por score/content sin validar; `test_pattern` sin timeout).

### Hallazgos de review — cerrados

- [x] T043 [P] [US5] Sanitización de `entity_type` en `create_custom_entity`:
      `_validate_entity_type` (`^[A-Z][A-Z0-9_]*$`, largo acotado) — `InvalidEntityTypeError` → 422.
      Verificado contra Postgres real (`tests/contract/test_entity_catalog_contract.py`) y con curl
      contra el backend vivo. *(FR-017)*
- [x] T044 [P] [US5] Unicidad de `entity_type` entre entidades custom **activas**: se rechaza la
      creación de una duplicada (no se confía en que Presidio dedupe `ad_hoc_recognizers` por nombre —
      no verificado, más simple y determinístico rechazar explícito). `DuplicateEntityTypeError` → 409.
      Entidades `inactive`/`status` distinto de `active` no cuentan para la unicidad. *(FR-016, SC-008)*
- [x] T045 [US5] Locking real en `create_custom_entity`/`delete_custom_entity`: `_pii_guardian(...,
      for_update=True)` usa `SELECT ... FOR UPDATE` de Postgres — serializa escrituras concurrentes en
      vez de dejarlas pisarse (lost update). Verificado con 8 hilos reales creando entidades distintas
      en paralelo contra Postgres real: 8/8 persistidas, cero perdidas.
- [x] T046 [P] [US5] Contract test end-to-end (`tests/contract/test_entity_catalog_contract.py`) contra
      Postgres real (no un Guardian fake): sanitización, unicidad, y concurrencia con hilos reales.
      Complementa los tests unitarios con fake session (rápidos, sin DB) de
      `test_entity_catalog_service.py`, que no pueden probar `with_for_update()` de verdad.

**Checkpoint**: US5 completa — funcional, probada en vivo, y los 3 hallazgos de la review cerrados con
test de contrato contra Postgres real (no solo curl manual).

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
- **US5 (T037-T046)** depende de Foundational (reusa `presidio_analyze`/`build_ad_hoc_recognizers`) pero
  es independiente de US1-US4 en su implementación — se hizo después, a pedido explícito del usuario.
  **Completa** (T037-T046, incluidos los 3 hallazgos de review).

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
pueden entregarse incrementalmente después sin romper el MVP. US5 (catálogo custom + IA) es una extensión
de alcance posterior al MVP — **completa**, incluidos los 3 hallazgos de integridad de la review.

## Próximos pasos inmediatos (en orden sugerido)

1. ~~T043-T045 (US5, hallazgos de review)~~ — **cerrado**.
2. ~~T014, T017, T018, T019, T025~~ — **cerrado** (`backend/tests/e2e/test_guardrail_behavior_e2e.py`).
   **T024** (contract test dedicado en `tests/contract/test_presidio_analyzer_contract.py`) sigue
   **pendiente** — cubierto solo parcialmente por `contract_checks.py` (T033).
3. ~~T028, T029~~ — **cerrado** (`presidio_service.py`/`guardian_service.py` reescritos, fail-open
   eliminado, catálogo EU migrado on-read).
4. ~~T031, T034, T035, T036~~ — **cerrado** (carry-split extendido, README, suite completa dentro del
   container real: 293 passed/10 skipped, `implementation-notes.md` + `ROADMAP-guardian.md`).
5. **Pendiente aún**: T024 (contract test dedicado, ver punto 2); commitear y pushear todo lo de esta
   sesión (rename `NLP_ANALYZER_URL`/`nlp-analyzer`, fixes de tests, docs regeneradas, notas); decidir
   con el usuario rebase vs merge sobre `main` antes del push (la rama ya tiene 2 merges pusheados —
   un rebase reescribiría historia ya publicada).
