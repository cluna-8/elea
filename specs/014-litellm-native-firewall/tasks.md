---
description: "Task list for feature 014 — LiteLLM-Native Firewall (base_url clients)"
---

# Tasks: LiteLLM-Native Firewall (base_url clients)

**Input**: Design documents from `/specs/014-litellm-native-firewall/`

**Prerequisites**: plan.md (required), spec.md (required for user stories). Depende del **bedrock 013**
(Tenant, `role="client"`, `client_type`, APIKey=Connection con `tenant_id`/`tool_type`/`upstream_mode`).

**Tests**: SÍ incluidos. Esta feature exige contract tests por Principio VI (firmas de hooks vs versión
pinneada) y su reversibilidad de masking lo pide la constitución (Dev Workflow — Tested & Verified). Los
tests marcados ⚠️ se escriben ANTES de la implementación y deben FALLAR primero.

**Organization**: Tareas agrupadas por user story para implementación y test independientes.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Puede correr en paralelo (archivos distintos, sin dependencias)
- **[Story]**: US1..US5 (o SETUP/FOUND/POLISH)
- Rutas de archivo exactas incluidas

## Path Conventions

- Extensiones del motor: `litellm/extensions/` (montadas en el contenedor LiteLLM)
- Backend: `backend/src/api/`, `backend/src/services/` (reusados), `backend/src/models/` (de la 013)
- Config: `litellm/config.yaml`, `docker-compose.yml`
- Tests: `tests/contract/`, `tests/integration/`, `tests/unit/`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Estructura del paquete de extensiones y montaje en el contenedor.

- [X] T001 [SETUP] Crear el paquete `litellm/extensions/` (con `__init__.py`) y su montaje como volumen
      en `docker-compose.yml` (mismo patrón que `./litellm/config.yaml:/app/config.yaml`).
- [ ] T002 [P] [SETUP] Configurar linting/formato para `litellm/extensions/` y `tests/` (reusar la
      config del repo).
- [ ] T003 [SETUP] Preparar el esqueleto de `tests/contract/`, `tests/integration/`, `tests/unit/` para
      esta feature.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Librería pura compartida + pin de versión. TODO lo demás depende de esto.

**⚠️ CRITICAL**: Ningún user story puede empezar hasta cerrar esta fase.

- [X] T004 [FOUND] Pinear la imagen LiteLLM en `docker-compose.yml`: `main-latest` → `vX.Y.Z-stable@sha256:…`
      (tag+digest). Documentar el proceso de bump (Principio VI). *(FR-026)*
- [X] T005 [FOUND] Phase 0 research (`research.md`): inspeccionar el **código** de la versión pinneada
      para confirmar (a) firmas reales de `async_pre_call_hook`/`async_post_call_success_hook`/
      `async_post_call_streaming_iterator_hook`/`user_api_key_auth`, (b) que los guardrails se ejecutan
      sobre `/v1/messages`, (c) forma de `ModelResponseStream` en la Messages API. Decidir la estrategia
      de unmask streaming (A objetos parseados, preferida; B rewrite SSE, fallback).
- [X] T006 ⚠️ [P] [FOUND] Unit tests de `basa_guardian_policy` en `tests/unit/test_policy.py`: mask
      reversible con nonce, colisión de placeholder con literal del usuario, carry-split (placeholder
      partido vs `[` suelto de código), round-trip text/thinking/tool_use. DEBEN FALLAR primero.
- [X] T007 [FOUND] Implementar `litellm/extensions/basa_guardian_policy.py` (librería PURA): portar
      `_redact_body` (mask_reversible con nonce por request), `_unmask`/`_unmask_deep` (unmask texto y
      objetos), `_safe_split`/`_PH_TYPE_RE`/`_PH_TAIL_RE` (carry-split), detect AI-Act / detect secrets
      (delegando en los servicios). Importable desde el motor Y el backend. *(FR-022)*

**Checkpoint**: Librería pura verde + imagen pinneada → los user stories pueden empezar.

---

## Phase 3: User Story 2 - Identidad (custom_auth, fail-closed) (Priority: P1) 🎯 MVP-blocker

**Goal**: Resolver identidad por User-Agent + virtual key contra `APIKey` (013), fail-closed. Va primero
porque los hooks de US1 consumen su metadata.

**Independent Test**: Request con UA de Claude Code + virtual key válida → `tool_type` + tenant/client
correctos; request sin key válida → rechazo (no admin).

### Tests for User Story 2 ⚠️

- [X] T008 ⚠️ [P] [US2] Contract test en `tests/contract/test_custom_auth_signature.py`: firma de
      `user_api_key_auth(request, api_key) -> UserAPIKeyAuth` vs versión pinneada. *(FR-027)*
- [X] T009 ⚠️ [P] [US2] Integration test en `tests/integration/test_identity.py`: UA→tool_type
      (claude→claude-code), virtual key→tenant/client/team, sin key→rechazo fail-closed, UA desconocido→
      `tool_type` desconocido sin crash.

### Implementation for User Story 2

- [X] T010 [US2] Implementar `litellm/extensions/custom_auth.py::user_api_key_auth`: portar
      `_detect_tool`/`_TOOL_UA` (UA→tool_type) y `_resolve_identity` (virtual key→tenant/client/team por
      `key_hash` directo contra `APIKey`/013); inyectar metadata `{tenant_id, client_id, tool_type}` en
      el `UserAPIKeyAuth`. *(FR-009, FR-010, FR-011, FR-013)*
- [X] T011 [US2] Hacer `user_api_key_auth` **fail-closed** en BYOK: sin virtual key válida → rechazo, NO
      `get_or_create_default_user` ni admin. *(FR-012, Constraint C3)*
- [X] T012 [US2] Registrar `custom_auth.user_api_key_auth` en `general_settings.custom_auth` de
      `litellm/config.yaml`. *(FR-023)*

**Checkpoint**: Identidad resuelta y fail-closed, verificada independiente.

---

## Phase 4: User Story 1 - Firewall nativo sobre `/v1/messages` (Priority: P1) 🎯 MVP

**Goal**: Política Basa como `CustomGuardrail` (pre/post/streaming) con block + mask reversible + unmask.

**⚠️ GATE — T005 ANTES de codear US1**: Ninguna tarea de implementación de US1 (T018–T021) arranca hasta
cerrar **T005** (Phase-0 research sobre la imagen pinneada). El research confirma la premisa (hooks +
stream normalizado sobre `/v1/messages` nativo) y fija la estrategia de unmask streaming: **Estrategia A**
(objetos `ModelResponseStream` parseados, preferida) o, si el research la invalida, **Estrategia B**
(rewrite SSE) como excepción acotada documentada (ver spec US1 y FR-007).

**Independent Test**: (Precondición: T005 cerrado.) Prompt AI-Act→400; prompt con PII→upstream ve
placeholders, caller ve valores reales (no-streaming y streaming).

### Tests for User Story 1 ⚠️

- [X] T013 ⚠️ [P] [US1] Contract test en `tests/contract/test_guardrail_signatures.py`: firmas de los
      tres hooks vs versión pinneada. *(FR-027)*
- [X] T014 ⚠️ [P] [US1] Contract test en `tests/contract/test_guardrail_on_v1_messages.py`: los
      guardrails se ejecutan sobre `/v1/messages` (no sólo `/chat/completions`). *(FR-028, SC-002)*
- [ ] T015 ⚠️ [P] [US1] Integration test en `tests/integration/test_pre_call_block.py`: AI-Act Art.5→400;
      secreto/API key→block; ambos antes de llegar al LLM.
- [ ] T016 ⚠️ [P] [US1] Integration test en `tests/integration/test_mask_unmask.py`: pre_call puebla
      `data["metadata"]["pii_tokens"]` y el upstream sólo ve placeholders; post_call_success des-enmascara
      (no-streaming).
- [ ] T017 ⚠️ [P] [US1] Integration test en `tests/integration/test_streaming_unmask.py`: unmask con
      placeholder partido entre chunks (carry) y stream truncado; 0 placeholders crudos, 0 texto perdido;
      round-trip text/thinking/tool_use. *(SC-004)*

### Implementation for User Story 1

- [X] T018 [US1] Implementar `litellm/extensions/basa_guardrail.py::BasaGuardrail.async_pre_call_hook`:
      AI-Act Art.5→400 (`ComplianceService.evaluate_prompt`), secretos→block
      (`GuardianService.process_prompt`), mask PII reversible (`basa_guardian_policy` +
      `PresidioService`), mapa en `data["metadata"]["pii_tokens"]`. *(FR-001, FR-002, FR-003, FR-004, FR-005)*
- [X] T019 [US1] Implementar `async_post_call_success_hook`: unmask no-streaming leyendo
      `metadata.pii_tokens`. *(FR-006)*
- [X] T020 [US1] Implementar `async_post_call_streaming_iterator_hook` con la estrategia que fijó T005:
      **Estrategia A** (sobre `ModelResponseStream`, preferida) → unmask + carry-split de
      `basa_guardian_policy`, NO reimplementar framing SSE/decoder/usage; **o Estrategia B** (rewrite SSE)
      SÓLO si T005 demostró que el hook parseado no cubre `/v1/messages` (excepción acotada documentada).
      *(FR-007, FR-008)*
- [X] T021 [US1] Registrar `BasaGuardrail` en el bloque `guardrails:` de `litellm/config.yaml` con modes
      `pre_call`, `post_call`, `post_call_streaming`; conservar `model_list` + `router_settings.fallbacks`.
      *(FR-001, FR-023)*

**Checkpoint**: MVP demostrable — block + mask + unmask (no-streaming y streaming) sobre `/v1/messages`.

---

## Phase 5: User Story 3 - Audit metadata-only + monitor en vivo (Priority: P2)

**Goal**: `BasaAuditLogger` metadata-only con scrub de `pii_tokens` + feed en memoria para el monitor.

**Independent Test**: Request con PII → AuditLog con verdicto/tipos/timing y CERO texto/`pii_tokens`;
`/monitor` muestra before/after real.

### Tests for User Story 3 ⚠️

- [X] T022 ⚠️ [P] [US3] Contract test en `tests/contract/test_logger_signature.py`: firma de
      `async_log_success_event(kwargs, response_obj, start_time, end_time)` vs versión pinneada.
- [ ] T023 ⚠️ [P] [US3] Integration test (negativo) en `tests/integration/test_audit_scrub.py`: con
      `metadata.pii_tokens` poblado, el AuditLog persiste metadata pero NUNCA texto de prompt ni
      `pii_tokens`. *(SC-001, FR-015)*

### Implementation for User Story 3

- [X] T024 [US3] Implementar `litellm/extensions/basa_audit_logger.py::BasaAuditLogger.async_log_success_event`:
      metadata-only vía `AuditService.log_transaction`; **scrub** de `metadata.pii_tokens` + cualquier
      texto antes de persistir. *(FR-014, FR-015)*
- [X] T025 [US3] Alimentar un ring en memoria (acotado) desde el logger con el before/after real por capa
      (mask→compliance→routing→unmask). *(FR-016)*
- [X] T026 [US3] Implementar la vista de monitor en `backend/src/api/monitor.py` (portar `_MONITOR_HTML` +
      feed `/events`), consumiendo el ring; animación cosmética, datos reales, sin persistir PII. *(FR-017)*
- [X] T027 [US3] Registrar `BasaAuditLogger` en `litellm_settings.callbacks` de `litellm/config.yaml`.
      *(FR-023)*

**Checkpoint**: Auditoría verde (scrub verificado) + monitor demostrable.

---

## Phase 6: User Story 4 - Excepción: passthrough OAuth de suscripción (Priority: P2)

**Goal**: Adelgazar `gateway.py` a SÓLO el passthrough OAuth, reescrito sobre `basa_guardian_policy`;
GDPR-routing N/A.

**Independent Test**: Request OAuth `upstream_mode`=`subscription-passthrough` (013; "anthropic" en el
demo) → header verbatim a `api.anthropic.com`; block/mask con el MISMO resultado que la ruta motor.

### Tests for User Story 4 ⚠️

- [ ] T028 ⚠️ [P] [US4] Integration test en `tests/integration/test_oauth_passthrough.py`: OAuth
      reenviado verbatim; práctica prohibida bloqueada; PII enmascarada/des-enmascarada vía
      `basa_guardian_policy`; GDPR-routing N/A (no fuerza endpoint EU). *(FR-018, FR-019, FR-020)*

### Implementation for User Story 4

- [X] T029 [US4] Escribir (NUEVO en este repo) `backend/src/api/gateway.py` con SÓLO el passthrough OAuth
      de suscripción (`upstream_mode`=`subscription-passthrough`), reenviando `Authorization`/OAuth
      verbatim a `api.anthropic.com`, e invocando `basa_guardian_policy` (block AI-Act/secretos +
      mask/unmask reversible, incl. carry-split streaming vía `rewrite_sse_block`); identidad **[D-014]**
      (NO fail-closed acá; `X-Basa-Key` = atribución opcional). *(FR-018, FR-019)* — 2026-07-10.
- [X] T030 [US4] El port NO recrea lo hand-rolled del demo: el `byok` migró a LiteLLM nativo (US1-3), y
      `_rewrite_sse_event`/`_redact_body`/`_detect_tool`/`_IN_RE`/`_OUT_RE` viven ahora en la librería
      compartida (`rewrite_sse_block`/`mask_body`/`detect_tool`; tokens de usage salen de
      `rewrite_sse_block`). Sólo el reenvío de headers (OAuth verbatim) es intrínseco al passthrough.
      *(FR-021, FR-030, SC-008)* — 2026-07-10.
- [X] T031 [US4] El OAuth de suscripción NUNCA vive en `config.yaml`: caso normal = lo pone el cliente
      (header, verbatim); caso gestionado = `oauth_credential_ref` Fernet descifrado en memoria
      (`encryption_service`). *(FR-025, Constraint C5, SC-007)* — 2026-07-10.

**Checkpoint**: `gateway.py` adelgazado; suscripción y BYOK con paridad de política.

---

## Phase 7: User Story 5 - Pin + contract tests como puerta (Priority: P3)

**Goal**: Blindar el port ante upgrades del motor.

**Independent Test**: Un bump incompatible del motor hace fallar la suite de contract tests.

### Tests / Implementation for User Story 5

- [X] T032 [US5] Consolidar la suite de contract tests (T008, T013, T014, T022) como **puerta de
      build/CI** contra la imagen pinneada; documentar el proceso "bump = correr contract tests, no
      reescribir". *(FR-027, FR-028, SC-006)*
- [X] T033 [US5] Contract test de **paridad de rutas** en `tests/contract/test_route_parity.py` (13 tests):
      nivel 1 (puro) — verdicto de bloqueo + tipos enmascarados del passthrough == librería compartida (lo
      que hace `BasaGuardrail`); nivel 2 (E2E con upstream mockeado) — block→400, mask sale al upstream y
      unmask vuelve al caller (no-streaming + streaming, incl. frame partido), OAuth reenviado verbatim,
      preview de la vitrina sin PII ni secretos. *(FR-029, SC-005)* — 2026-07-10.

**Checkpoint**: Todos los user stories independientes y blindados por contract tests.

---

## Phase N: Polish & Cross-Cutting Concerns

- [ ] T034 [P] [POLISH] Generar `data-model.md` (consume el schema de la 013, no crea propio) y
      `quickstart.md` (levantar contenedor → apuntar Claude Code a `/v1/messages` → ver `/monitor`).
- [ ] T035 [POLISH] Verificación end-to-end con Docker Compose (Principio VII); validar `quickstart.md`.
- [ ] T036 [P] [POLISH] Portar (o dejar enganchados para la 016) los tests de los 12 bugs del demo como
      contract tests del round-trip de deltas Anthropic.
- [ ] T037 [POLISH] Confirmar retiro final del código propio (FR-030) y actualizar
      `spec/plan/tasks/changelog` (Dev Workflow — Documentación viva).

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: sin dependencias.
- **Foundational (Phase 2)**: depende de Setup. BLOQUEA todos los user stories (la policy pura y el pin
  son prerequisito de ambos hogares).
- **US2 (Phase 3)**: depende de Foundational. Va **antes** de US1 (los hooks consumen su metadata).
- **US1 (Phase 4)**: depende de Foundational + US2 (metadata de identidad). **Gate duro**: la
  implementación (T018–T021) NO arranca hasta cerrar **T005** (research), que además fija la estrategia de
  unmask streaming (A preferida / B excepción acotada).
- **US3 (Phase 5)**: depende de Foundational; se integra con US1 (lee `pii_tokens` para scrubbear) y US2
  (identidad en la auditoría).
- **US4 (Phase 6)**: depende de Foundational (importa `basa_guardian_policy`); independiente del motor.
- **US5 (Phase 7)**: depende de US1–US4 existiendo (cubre sus firmas y la paridad).
- **Polish (Phase N)**: depende de los user stories deseados.

### User Story Dependencies

- **US2 (P1)**: tras Foundational. Sin dependencias de otros stories.
- **US1 (P1)**: tras Foundational + US2 (metadata de identidad para los hooks).
- **US3 (P2)**: tras Foundational; integra con US1/US2 pero testeable independiente.
- **US4 (P2)**: tras Foundational; comparte `basa_guardian_policy` con US1 pero corre en otro hogar.
- **US5 (P3)**: tras US1–US4.

### Within Each User Story

- Tests (⚠️) escritos y FALLANDO antes de implementar.
- Policy pura antes que los hooks; hooks antes que el registro en config.
- Identidad antes que los hooks que la consumen.

### Parallel Opportunities

- Setup: T002 [P].
- Foundational: T006 [P] (unit tests) mientras se prepara T007.
- Tests de cada story marcados [P] corren en paralelo (archivos distintos).
- US4 puede desarrollarse en paralelo a US1/US3 una vez cerrada Foundational (otro hogar, misma policy).

---

## Parallel Example: User Story 1

```bash
# Tests de US1 juntos (distintos archivos):
Task: "Contract test firmas de los 3 hooks en tests/contract/test_guardrail_signatures.py"
Task: "Contract test guardrails sobre /v1/messages en tests/contract/test_guardrail_on_v1_messages.py"
Task: "Integration pre_call block en tests/integration/test_pre_call_block.py"
Task: "Integration mask/unmask en tests/integration/test_mask_unmask.py"
Task: "Integration streaming unmask en tests/integration/test_streaming_unmask.py"
```

---

## Implementation Strategy

### MVP First (US2 + US1)

1. Phase 1 Setup → Phase 2 Foundational (policy pura + pin).
2. Phase 3 US2 (identidad fail-closed).
3. Phase 4 US1 (firewall nativo: block + mask + unmask).
4. **STOP & VALIDATE**: prompt AI-Act→400; PII enmascarada al upstream y des-enmascarada al caller,
   streaming incluido. Demo BYOK lista.

### Incremental Delivery

1. Foundational → base lista.
2. US2 + US1 → **MVP** (firewall nativo BYOK, demo por `/v1/messages`).
3. US3 → audit metadata-only + monitor (vitrina de demo).
4. US4 → suscripción OAuth (la "firewall on top of your subscription story").
5. US5 → blindaje por contract tests (sostenibilidad ante upgrades).

### Parallel Team Strategy

Tras Foundational: Dev A → US2+US1 (motor); Dev B → US4 (backend passthrough, misma policy); Dev C → US3
(audit+monitor). US5 lo cierra quien consolida CI.

---

## Notes

- [P] = archivos distintos, sin dependencias.
- [Story] mapea cada tarea a su user story para trazabilidad.
- Verificar que los tests ⚠️ fallan antes de implementar.
- Commit tras cada tarea o grupo lógico; verificación local con Docker Compose antes de mergear.
- **Reuso vs propio**: sólo `basa_guardian_policy` + los 3 wrappers de extensión + el passthrough OAuth
  son código propio; framing SSE/decoder/usage/routing/fallbacks/cost-ceiling son del motor (Principio VI).
- **Excepción única**: el passthrough OAuth de suscripción es el único proxy propio permitido; importa la
  policy compartida, no la reimplementa.
