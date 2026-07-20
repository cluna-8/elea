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
- Tests: `tests/contract/`, `tests/integration/`, `backend/tests/unit/`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Levantar el sidecar NLP y el cableado de configuración que todo lo demás necesita.

- [ ] T001 [SETUP] Crear `presidio-analyzer/Dockerfile` (build propio sobre la imagen base de Presidio
      Analyzer, `--build-arg NLP_CONF_FILE=conf/es.yaml`) y `presidio-analyzer/conf/es.yaml`
      (`NlpEngineConfig` con spaCy `es_core_news_md`). *(research.md §1-2)*
- [ ] T002 [SETUP] Agregar el servicio `presidio-analyzer` a `docker-compose.yml`: build desde
      `presidio-analyzer/`, en `basa-network`, **sin** puerto publicado al host, healthcheck sobre su
      endpoint de salud. *(research.md §2)*
- [ ] T003 [P] [SETUP] Agregar `PRESIDIO_ANALYZER_URL` a `.env.example` con el default interno
      (`http://presidio-analyzer:3000` o el puerto real de la imagen) y documentarla en `README.md`
      (sección Quickstart/tabla de puertos, sin exponer nombre de terceros según Principio VII —
      referirse como "motor de detección NLP").
- [ ] T004 [P] [SETUP] Preparar `backend/tests/unit/test_basa_guardian_policy.py` (nuevo archivo, mirror
      del `litellm/extensions/basa_guardian_policy.py` para poder testear sin levantar el contenedor
      del motor — mismo patrón que ya usa `tests/unit/test_policy.py` de la 014).

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Las funciones puras compartidas de las que dependen las 4 historias de usuario. Nada de
Fase 3+ puede empezar hasta cerrar esto.

**⚠️ CRITICAL**: Ningún user story puede empezar hasta cerrar esta fase.

- [ ] T005 ⚠️ [P] [FOUND] Unit tests de `resolve_overlaps` en `backend/tests/unit/test_basa_guardian_policy.py`:
      rangos solapados con distinta longitud/score, caso sin solapamiento (no-op), caso de contención
      total. DEBEN FALLAR primero. *(contracts/policy-library-functions.md, data-model.md)*
- [ ] T006 [FOUND] Implementar `resolve_overlaps(entities) -> entities` en
      `litellm/extensions/basa_guardian_policy.py`: orden `(start, -length)`, descarta contenidas,
      empate por score, empate total estable por orden de entrada. *(FR-009, research.md §5)*
- [ ] T007 ⚠️ [P] [FOUND] Unit tests de `resolve_entity_action` en `backend/tests/unit/test_basa_guardian_policy.py`:
      tipo configurado `MASK`/`BLOCK`, tipo ausente → default `MASK`, valor inválido en config → default
      `MASK`. DEBEN FALLAR primero.
- [ ] T008 [FOUND] Implementar `resolve_entity_action(entity_type, entity_configs)` en
      `litellm/extensions/basa_guardian_policy.py`. *(FR-005, FR-008, research.md §6)*
- [ ] T009 ⚠️ [P] [FOUND] Unit tests de `build_ad_hoc_recognizers` en `backend/tests/unit/test_basa_guardian_policy.py`:
      DNI/CUIL siempre presentes, `custom_names` vacío → sin recognizer deny-list, `custom_names` con
      valores → recognizer deny-list correcto. DEBEN FALLAR primero.
- [ ] T010 [FOUND] Implementar `build_ad_hoc_recognizers(custom_names)` en
      `litellm/extensions/basa_guardian_policy.py`, reemplazando el diccionario `PII_PATTERNS` actual de
      ese archivo como única fuente de DNI/CUIL. *(FR-003, SC-006, research.md §3)*
- [ ] T011 [FOUND] Definir `NlpUnavailableError` (excepción dedicada) en
      `litellm/extensions/basa_guardian_policy.py`.
- [ ] T012 ⚠️ [P] [FOUND] Unit test de `presidio_analyze` en `backend/tests/unit/test_basa_guardian_policy.py`
      con un cliente HTTP mockeado: éxito → `DetectedEntity[]` normalizada y pasada por
      `resolve_overlaps`; timeout/5xx/body inesperado → levanta `NlpUnavailableError` (NUNCA `[]`).
      DEBE FALLAR primero. *(FR-004, contracts/presidio-analyzer-http.md)*
- [ ] T013 [FOUND] Implementar `presidio_analyze(text, analyzer_url, custom_names) -> DetectedEntity[]`
      (nuevo `AnalyzeFn`) en `litellm/extensions/basa_guardian_policy.py`: `httpx` async, timeout 2s,
      arma el body con `build_ad_hoc_recognizers`, normaliza la respuesta, aplica `resolve_overlaps`.

**Checkpoint**: librería pura verde (T005-T013) → los user stories pueden empezar.

---

## Phase 3: User Story 1 - Detección de PERSON sin prefijo (Priority: P1) 🎯 MVP

**Goal**: El firewall real detecta nombres de persona en texto conversacional natural usando NLP,
sin depender de un prefijo de título.

**Independent Test**: enviar un prompt con un nombre sin prefijo a través del firewall; verificar
placeholder en lo que ve el motor/LLM y el valor real restaurado en la respuesta final.

### Tests for User Story 1 ⚠️

- [ ] T014 ⚠️ [P] [US1] Integration test en `tests/integration/test_person_detection.py`: prompt
      "Juan Pérez tiene turno el jueves" a través de `BasaGuardrail.async_pre_call_hook` +
      `async_post_call_success_hook` (con Analyzer real o levantado en el entorno de test) → placeholder
      en el body saliente, nombre real restaurado en la respuesta. DEBE FALLAR primero (hoy no detecta
      sin prefijo). *(spec.md US1, acceptance scenarios 1-3)*

### Implementation for User Story 1

- [ ] T015 [US1] En `litellm/extensions/basa_guardrail.py::async_pre_call_hook`: reemplazar
      `policy.default_analyze` por `policy.presidio_analyze` (leyendo `PRESIDIO_ANALYZER_URL` de env) en
      el camino real; `default_analyze` queda como fallback documentado exclusivo de modo dev (activado
      solo si `PRESIDIO_ANALYZER_URL` no está seteada, con log explícito de "modo dev, no usar en prod").
      *(FR-001, FR-002)*
- [ ] T016 [US1] Pasar `custom_names` (desde la identidad resuelta, ver T019/T020 de US2 si ya están
      disponibles, o desde una consulta puntual a `Guardian.config` si US2 corre después) a
      `presidio_analyze` en la llamada de T015.
- [ ] T017 [P] [US1] Ejecutar el paso 1 de `quickstart.md` (validación manual con `claude` real contra
      el gateway local) y documentar el resultado en `specs/016-real-nlp-masking/implementation-notes.md`
      (nuevo archivo, mismo patrón que 013/014).

**Checkpoint**: US1 entregable y demostrable de forma independiente (nombres sin prefijo se enmascaran).

---

## Phase 4: User Story 2 - Enforcement real de `entity_configs` (Priority: P1) 🎯 MVP

**Goal**: La política activa (`MASK`/`BLOCK` por tipo de entidad) gobierna de verdad el tráfico del
firewall real.

**Independent Test**: configurar un tipo como `BLOCK`, enviar una request que lo contenga, verificar
rechazo con motivo auditable; configurar otro tipo como `MASK`, verificar que sigue el flujo normal.

### Tests for User Story 2 ⚠️

- [ ] T018 ⚠️ [P] [US2] Contract test en `tests/contract/test_custom_auth_entity_configs.py`: la query
      de identidad de `custom_auth.py` devuelve `entity_configs` de la `SecurityPolicy` activa. DEBE
      FALLAR primero.
- [ ] T019 ⚠️ [P] [US2] Integration test en `tests/integration/test_entity_enforcement.py`: entidad
      `BLOCK` → request rechazada antes del LLM con motivo `blocked_entity_type`; entidad `MASK` →
      sigue normal; tipo no configurado → default `MASK` (no ignorado, no bloqueado). DEBE FALLAR
      primero. *(spec.md US2, acceptance scenarios 1-4)*

### Implementation for User Story 2

- [ ] T020 [US2] Extender `_IDENTITY_SQL` en `litellm/extensions/custom_auth.py` con un JOIN/subquery a
      `security_policies` (activa) trayendo `entity_configs`. *(research.md §6)*
- [ ] T021 [US2] Poblar `entity_configs` en el dict de identidad que viaja a `metadata.basa` (mismo
      lugar donde ya vive `redact_enabled`) en `litellm/extensions/custom_auth.py`.
- [ ] T022 [US2] En `litellm/extensions/basa_guardrail.py::async_pre_call_hook`: para cada entidad
      detectada (post `resolve_overlaps`), resolver acción vía `resolve_entity_action`; si alguna es
      `BLOCK`, retornar motivo de bloqueo nombrando los tipos (sin valores); si no, enmascarar solo las
      `MASK` con el `PlaceholderMap` existente. *(FR-005, FR-006, FR-007)*
- [ ] T023 [US2] Agregar el motivo `blocked_entity_type` al vocabulario de auditoría en
      `litellm/extensions/basa_audit_logger.py` (metadata-only: tipos bloqueados, no valores). *(FR-011)*

**Checkpoint**: US1 + US2 = MVP entregable — detección real + enforcement real de la política.

---

## Phase 5: User Story 3 - NLP real con fail-closed (Priority: P2)

**Goal**: El motor NLP real es la fuente primaria de detección; su indisponibilidad rechaza la request
en vez de degradar silenciosamente.

**Independent Test**: con el Analyzer caído, verificar que el 100% de las requests afectadas se
rechazan explícitamente (ninguna procesa con detección degradada).

### Tests for User Story 3 ⚠️

- [ ] T024 ⚠️ [P] [US3] Contract test en `tests/contract/test_presidio_analyzer_contract.py` contra el
      contenedor real `presidio-analyzer`: health check, recognizer DNI ad-hoc, recognizer deny-list
      de `custom_names`, shape de respuesta. DEBE FALLAR primero (servicio aún no existe en el compose
      hasta T001-T002; si esas tareas ya cerraron, este test valida el contrato real). *(contracts/presidio-analyzer-http.md)*
- [ ] T025 ⚠️ [P] [US3] Integration test en `tests/integration/test_nlp_failclosed.py`: apuntar
      `PRESIDIO_ANALYZER_URL` a un endpoint caído/inexistente → la request se rechaza con motivo
      `nlp_unavailable`, no se procesa con regex de respaldo. DEBE FALLAR primero. *(FR-004, SC-004)*

### Implementation for User Story 3

- [ ] T026 [US3] En `litellm/extensions/basa_guardrail.py::async_pre_call_hook`: atrapar
      `NlpUnavailableError` de `presidio_analyze` (T013/T015) y retornar el motivo de bloqueo
      `nlp_unavailable` por el mismo canal que AI-Act/secretos.
- [ ] T027 [US3] Agregar el motivo `nlp_unavailable` al vocabulario de auditoría en
      `litellm/extensions/basa_audit_logger.py`. *(FR-011)*
- [ ] T028 [P] [US3] En `backend/src/services/presidio_service.py::analyze_text_http`: dejar de atrapar
      la excepción y devolver `[]` (fail-open heredado) — debe **propagar** (o levantar
      `NlpUnavailableError` si se homologa con la librería del motor) y aceptar un parámetro
      `ad_hoc_recognizers` en el payload. *(research.md §7, contraste explícito documentado en
      contracts/presidio-analyzer-http.md)*
- [ ] T029 [US3] En `backend/src/services/guardian_service.py`: eliminar el catálogo `PATTERNS` propio
      y las listas duplicadas; construir `ad_hoc_recognizers` reusando la misma función que T010 (via
      un thin wrapper Python si el módulo no es directamente importable entre backend y motor — documentar
      la decisión de empaquetado en `implementation-notes.md`). *(FR-012, SC-006)*

**Checkpoint**: motor NLP real es la fuente primaria en ambos caminos (firewall + panel); indisponibilidad
nunca se traduce en detección degradada silenciosa.

---

## Phase 6: User Story 4 - Integridad ante coincidencias solapadas (Priority: P2)

**Goal**: El texto enmascarado nunca se corrompe cuando dos detecciones se solapan.

**Independent Test**: texto sintético con rangos solapados intencionales → salida válida, un solo
placeholder por rango disputado, reversible.

### Tests for User Story 4 ⚠️

- [ ] T030 ⚠️ [P] [US4] Regression test en `backend/tests/unit/test_basa_guardian_policy.py`: texto con
      una coincidencia tipo teléfono que se solapa con una tipo DNI → `mask_text` produce un único
      placeholder válido para el rango disputado y el mapa permite reconstruir el original exacto. DEBE
      FALLAR primero (el bug de corrupción es real hoy sin `resolve_overlaps` en el camino de reemplazo).
      *(spec.md US4, acceptance scenarios 1-2)*
- [ ] T031 ⚠️ [P] [US4] Extender `tests/unit/test_policy.py` (carry-split, ya existente de la 014):
      confirmar que el carry-split sigue siendo válido cuando el placeholder resultante viene de una
      entidad que ganó una resolución de solapamiento (largo de placeholder distinto al de antes).

### Implementation for User Story 4

- [ ] T032 [US4] Cablear `resolve_overlaps()` (T006) dentro de `mask_text`/`mask_body` en
      `litellm/extensions/basa_guardian_policy.py`, ANTES del loop de reemplazo por offsets. *(FR-009, FR-010)*

**Checkpoint**: las 4 historias completas — detección real, enforcement real, fail-closed, e integridad
del texto enmascarado.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Verificación de contrato ampliada, documentación y cierre de la feature.

- [ ] T033 [P] [POLISH] Extender `litellm/extensions/contract_checks.py` con checks de
      `resolve_overlaps`/`resolve_entity_action`/`build_ad_hoc_recognizers`/`presidio_analyze` (existencia
      y comportamiento fail-closed) y de conectividad al Analyzer real. *(quickstart.md paso 5)*
- [ ] T034 [P] [POLISH] Actualizar `README.md` (tabla de compatibilidad de proveedores / arquitectura del
      repo) para reflejar el nuevo servicio NLP, con naming neutro (Principio VII).
- [ ] T035 [POLISH] Correr la suite completa (`docker compose run --rm --no-deps backend pytest tests/ -q`)
      y confirmar 0 regresiones sobre lo heredado de 013/014. *(quickstart.md paso 6)*
- [ ] T036 [POLISH] Escribir `specs/016-real-nlp-masking/implementation-notes.md` (mismo patrón que
      013/014) y actualizar `specs/ROADMAP-guardian.md`: marcar 016 como Implementada.

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
