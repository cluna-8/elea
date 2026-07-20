---
description: "Task list for feature 021 — Licensing & Seat Enforcement (offline, distributor model)"
---

# Tasks: Licensing & Seat Enforcement (offline, distributor model)

**Input**: Design documents from `/specs/021-licensing-seat-enforcement/`

**Prerequisites**: plan.md (required), spec.md (required for user stories). Depende del **bedrock 013**
(Tenant, `User role=client`, APIKey=Connection con `tenant_id`/`tool_type` + índice parcial
`uq_api_keys_tenant_user_tool`, AuditLog inmutable). **Complementa la 020** (deploy): el token de licencia
se inyecta como config del artefacto de la 020.

**Tests**: SÍ incluidos. El enforcement de licencias es **fail-closed** por diseño (Constraint C3
extendido) y su evidencia de tamper es un compromiso de compliance (Principio II); ambos exigen tests
negativos. Los tests marcados ⚠️ se escriben ANTES de la implementación y deben FALLAR primero.

**Organization**: Tareas agrupadas por user story para implementación y test independientes.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Puede correr en paralelo (archivos distintos, sin dependencias)
- **[Story]**: US1..US5 (o SETUP/FOUND/POLISH)
- Rutas de archivo exactas incluidas

## Path Conventions

- Núcleo de licenciamiento (backend-only): `backend/src/licensing/`
- Call-sites de creación: `backend/src/api/keys.py`, `backend/src/api/users.py`, `backend/src/api/health.py`
- Clave pública embebida: `backend/src/keys/basa_public_keys.pem`
- Modelos reusados de la 013: `backend/src/models/` (APIKey, User, Tenant, AuditLog)
- Inyección del token: artefacto de deploy de la **020**
- Tests: `tests/unit/`, `tests/integration/`, `tests/contract/`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Estructura del paquete de licenciamiento y su lugar en el backend.

- [X] T001 [SETUP] Crear el paquete `backend/src/licensing/` (con `__init__.py`) y el directorio
      `backend/src/keys/` para la clave pública embebida.
- [X] T002 [P] [SETUP] Añadir la dependencia de criptografía Ed25519 (p.ej. `cryptography`/`PyNaCl`) y
      configurar linting/formato para `backend/src/licensing/` y `tests/` (reusar la config del repo).
- [X] T003 [SETUP] Preparar el esqueleto de `tests/unit/`, `tests/integration/`, `tests/contract/` para
      esta feature.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Formato del token firmado + verificador Ed25519 OFFLINE. TODO lo demás depende de esto.

**⚠️ CRITICAL**: Ningún user story puede empezar hasta cerrar esta fase.

- [X] T004 [FOUND] Phase 0 research (`research.md` — GENERADO): veredicto **DIY Ed25519** (build-vs-buy;
      no hay SaaS/servidor reusable que respete air-gap + "cliente corre la caja"), lib de verificación
      (**PyNaCl/PyCA** o **PyJWT-EdDSA**), **formato `.lic`** (`{schema, license_id, tenant_id,
      distributor_id, pool_id, max_seats, not_before, expiry, grace_days, feature_flags, key_id}`
      + `issued_at` opcional ≈ `not_before` + firma detached; wire `lic_id`/`kid`), **definición de seat
      [D-021]** (default
      `COUNT(APIKey activas)` vs `COUNT(User role=client)`) y la estrategia **anti-rollback** (marca
      monotónica). **+ Addendum 2026-07-14**: prior-art validado (GitLab/Grafana/Directus/Replicated);
      tier DISTRIBUIDOR = firma central + cupo de emisión (NUNCA clave delegada); per-seat capturado en
      emisión + true-up; 3 ajustes de honestidad (cadena de hashes, expiry degrada, seat-gate
      best-effort). *(FR-001, FR-013, FR-023, FR-028–FR-030)*
- [X] T005 [FOUND] Generar el par de claves Ed25519 de prueba (offline), colocar SÓLO la pública en
      `backend/src/keys/basa_public_keys.pem` indexada por `key_id`; documentar que la privada NUNCA se
      despliega en la caja. *(FR-002, Constraint C5)*
- [X] T006 ⚠️ [P] [FOUND] Unit tests en `tests/unit/test_license_verifier.py`: firma **válida** → parse OK;
      firma **alterada** (un byte) → rechazo; **mismatch** de `tenant_id` → rechazo; token **ausente/
      corrupto** → rechazo; **rotación** (token firmado con clave A, verificado contra el set {A,B} por
      `key_id`) → OK. DEBEN FALLAR primero. *(FR-003, FR-005, FR-006, FR-007)*
- [X] T007 [FOUND] Implementar `backend/src/licensing/token.py` (parse + esquema del `LicenseToken`) y
      `backend/src/licensing/verifier.py` (verificación Ed25519 **offline** contra `BasaPublicKeySet` por
      `key_id`, sin ninguna llamada de red). *(FR-001, FR-003, FR-004, FR-007)*

**Checkpoint**: Verificador offline verde + clave pública embebida → los user stories pueden empezar.

---

## Phase 3: User Story 1 - Artefacto firmado + verificación offline al arranque (Priority: P1) 🎯 MVP-blocker

**Goal**: Cargar el token (inyectado por la 020), verificar offline al arranque, computar entitlement en
memoria; fail-closed + audit si inválido/ausente/mismatch.

**Independent Test**: Arrancar con token válido → entitlement cargado; con firma alterada / sin token /
tenant cruzado → modo degradado fail-closed + audit; todo **sin egress**.

### Tests for User Story 1 ⚠️

- [X] T008 ⚠️ [P] [US1] Integration test en `tests/integration/test_startup_verify.py`: arranque con token
      válido → entitlement `{tenant_id, max_seats, expiry}` consultable; token alterado/ausente/mismatch →
      estado degradado fail-closed + evento de audit; token **válido pero vencido dentro de grace** →
      arranca con estado `grace` (NO `invalid`): proceso vivo, tráfico existente OK, sólo creación
      bloqueada; token válido pero vencido **MÁS ALLÁ de grace** → arranca en `expired` + degradado
      read-only-para-creación (proceso vivo, 0 exits) — expiry degrada, nunca mata, también en el boot
      path. *(SC-002, SC-013)*
- [X] T009 ⚠️ [P] [US1] Integration test **offline** en `tests/integration/test_offline_verify.py`: con
      egress de red bloqueado, la verificación de un token válido se completa con **0 llamadas salientes**
      y el sistema opera normal. *(SC-001, FR-004)*

### Implementation for User Story 1

- [X] T010 [US1] Implementar `backend/src/licensing/entitlement.py`: cargar el token desde env/secret/
      fichero montado (020), verificar (Phase 2), y mantener el **entitlement en memoria** + cómputo
      inicial de estado. *(FR-003, FR-026)*
- [X] T011 [US1] Hookear la verificación en el **arranque** del backend; si el token es
      ausente/corrupto/firma inválida/`tenant_id` mismatch → **modo degradado fail-closed** (no crea seats)
      + exponer estado `invalid`/`mismatch`. *(FR-005, FR-006)*
- [X] T012 [US1] Emitir el evento de audit de carga de licencia (OK / inválido / mismatch / ausente) vía la
      infraestructura de audit inmutable existente (metadata-only, sin token crudo). *(FR-022, FR-024)*

**Checkpoint**: Entitlement cargado y verificado offline; fail-closed al arranque verificado independiente.

---

## Phase 4: User Story 2 - Gate de seats en la creación de Connection/Client (Priority: P1) 🎯 MVP

**Goal**: Rechazar la creación del asiento N+1 en `POST keys.py`/`users.py` (402/403 antes de provisionar),
fail-closed, coexistiendo con el 409 de duplicados.

**Independent Test**: `max_seats=3` + 3 activas → 4º `POST` = 402/403 sin provisioning; revocar una →
`POST` OK.

### Tests for User Story 2 ⚠️

- [X] T013 ⚠️ [P] [US2] Unit test en `tests/unit/test_seat_counter.py`: `COUNT(activas)` cuenta sólo
      Connections activas (excluye revocadas/soft-deleted/expiradas), por tenant, aislado. *(FR-013, FR-014)*
- [X] T014 ⚠️ [P] [US2] Integration test en `tests/integration/test_seat_gate_keys.py`: con `max_seats=N` y
      N activas, `POST` de Connection N+1 → 402/403 `license_seat_limit_exceeded`, **sin** llamar a
      `ai_engine_client.generate_key`, con audit; revocar una → `POST` OK. *(SC-003)*
- [X] T015 ⚠️ [P] [US2] Integration test en `tests/integration/test_seat_gate_users.py`: mismo gate en
      `POST` de Client (`role=client`) contra `max_seats`. *(FR-009)*
- [X] T016 ⚠️ [P] [US2] Integration test en `tests/integration/test_gate_coexist.py`: el 402/403 (licencia)
      y el 409 (`uq_api_keys_tenant_user_tool`, duplicado) son guardas independientes — un caso dispara sólo
      409, otro sólo 402/403, un tercero podría disparar ambos. *(SC-004, FR-011)*
- [X] T017 ⚠️ [P] [US2] Integration test en `tests/integration/test_seats_not_usage.py`: un seat
      rate-limited a 0 rpm (007) **igual** cuenta para `max_seats` (seats ≠ uso). *(SC-008, FR-012)*

### Implementation for User Story 2

- [X] T018 [US2] Implementar `backend/src/licensing/seat_counter.py`: definición única de seat ([D-021],
      default `COUNT(APIKey activas)` por tenant), consistente con el índice parcial existente. *(FR-013, FR-014)*
- [X] T019 [US2] Añadir el gate en `backend/src/api/keys.py` (`POST`): contar seats y rechazar con 402/403
      `license_seat_limit_exceeded` **antes** de `ai_engine_client.generate_key` si excede `max_seats`;
      **fail-closed** si el entitlement no está cargado/es inválido. *(FR-008, FR-010)*
- [X] T020 [US2] Añadir el mismo gate en `backend/src/api/users.py` (`POST` de Client `role=client`).
      *(FR-009, FR-010)*
- [X] T021 [US2] Emitir el evento de audit `license_seat_limit_exceeded` en cada rechazo del gate
      (metadata-only, con `seats_used`/`max_seats`). *(FR-022, FR-024)*

**Checkpoint**: MVP demostrable — no se puede crear el asiento N+1; el gate coexiste con el 409 y no
confunde seats con uso.

---

## Phase 5: User Story 3 - Contador / reconciliación de seats por tenant (Priority: P2)

**Goal**: Reconciliación periódica local que detecta drift (`over_seat`) y dispara degradado + audit.

**Independent Test**: Inyectar seats por DB directa por encima de `max_seats` → reconciliación marca
`over_seat` + audit; corregir → vuelve a `ok`.

### Tests for User Story 3 ⚠️

- [X] T022 ⚠️ [P] [US3] Integration test en `tests/integration/test_reconcile.py`: drift inyectado por DB
      directa (`COUNT(activas) > max_seats`) → reconciliación marca `over_seat`, dispara degradado, emite
      audit con `seats_used` vs `max_seats`; al corregir → `ok`. *(SC-005)*
- [X] T023 ⚠️ [P] [US3] Integration test en `tests/integration/test_reconcile_isolation.py`: con múltiples
      tenants, el `over_seat` de uno NO afecta el estado de otro. *(SC-009, FR-017)*

### Implementation for User Story 3

- [X] T024 [US3] Implementar `backend/src/licensing/reconcile.py`: job periódico **local** que compara
      `COUNT(activas)` vs `max_seats` por tenant (misma definición que US2) y publica
      `{ok|over_seat|expired}` por tenant, aislado. *(FR-015, FR-016, FR-017)*
- [X] T025 [US3] Enganchar la reconciliación al scheduler existente del backend (sin phone-home) y conectar
      su salida al cómputo de estado (US4) + audit (US5). *(FR-015, FR-016)*

**Checkpoint**: Reconciliación verde (drift detectado, aislado por tenant).

---

## Phase 6: User Story 4 - Expiry + grace period + modo degradado (Priority: P2)

**Goal**: Ciclo de vida `active→grace→expired` con reloj local; grace bloquea creación; expired →
read-only-para-creación (toggle a bloqueo total).

**Independent Test**: `expiry` pasado dentro de grace → estado `grace`, creación bloqueada, tráfico OK;
más allá del grace → `expired`, modo degradado.

### Tests for User Story 4 ⚠️

- [X] T026 ⚠️ [P] [US4] Integration test en `tests/integration/test_lifecycle.py` con reloj inyectado:
      `active` (creación OK) → `grace` (creación bloqueada, tráfico existente OK, audit) → `expired`
      (degradado read-only-para-creación); verificar el toggle a bloqueo total. *(SC-006)*

### Implementation for User Story 4

- [X] T027 [US4] Extender `entitlement.py` para computar `{active|grace|expired}` desde `expiry`/
      `grace_days` con el **reloj local** (offline). *(FR-018, FR-021)*
- [X] T028 [US4] Implementar el **modo degradado**: en `grace`/`expired`/`over_seat`, bloquear la creación
      de seats (default **read-only para creación**; toggle configurable a bloqueo total); el tráfico
      existente sigue. *(FR-019, FR-020)*
- [X] T029 [US4] Conectar el estado de licencia al gate (US2) para que `grace`/`expired`/`over_seat`
      bloqueen la creación fail-closed, y emitir audit por transición. *(FR-019, FR-020, FR-022)*

**Checkpoint**: Ciclo de vida y aterrizaje suave demostrables con reloj local.

---

## Phase 7: User Story 5 - Evidencia de tamper: audit hash-chained + true-up firmado (Priority: P3)

**Goal**: Cada transición de licencia (incl. rollback de reloj) → AuditLog inmutable metadata-only
**encadenado por hash**; export de **true-up firmado** con la deployment key; consolidar el endpoint de
health.

**Independent Test**: Provocar cada transición (inválido, seat-limit, over-seat, grace, expired, reloj
atrasado) → cada una deja un `AuditLog` append-only metadata-only, no borrable por la ruta normal;
borrar/editar un evento por DB directa → la verificación de la cadena lo detecta; el export de true-up
valida contra la deployment key y un byte alterado invalida la firma.

### Tests for User Story 5 ⚠️

- [ ] T030 ⚠️ [P] [US5] Integration test (negativo) en `tests/integration/test_audit_tamper.py`: cada
      transición deja `{event_type, license_id, tenant_id, seats_used, max_seats, ts, prev_hash}`; **cero**
      token crudo/claves; los eventos NO se pueden borrar/editar por la ruta normal (inmutabilidad).
      *(SC-007, FR-024, FR-025, FR-028)*
- [ ] T031 ⚠️ [P] [US5] Integration test en `tests/integration/test_clock_rollback.py`: un `now` anterior a
      la marca monotónica → evento `license_clock_rollback_suspected` + degradado. *(FR-023)*
- [ ] T039 ⚠️ [P] [US5] Integration test en `tests/integration/test_hash_chain.py`: cadena íntegra →
      verificación OK; borrar un evento **intermedio** por DB directa → eslabón roto detectado y
      reportado; editar un campo de un evento → ídem; génesis anclada al `license_id`; el **hash-head y
      el contador monotónico** se persisten y avanzan con cada evento. Documentar en el test (como
      comentario-contrato) que el truncado de cola/total NO es detectable localmente — su detección es
      la continuidad entre exports (T040). *(SC-011, FR-028)*
- [ ] T040 ⚠️ [P] [US5] Integration test en `tests/integration/test_trueup_export.py`: el export firmado
      valida contra la pública del deployment; refleja lo que la caja registró (`seats_used`/historial) +
      **hash-head + contador**; alterar un byte → firma inválida; dos exports sucesivos → el verificador
      (lado Basa, mismo módulo) acepta continuidad head-ancestro/contador-no-decreciente y **rechaza** un
      export post-truncado (contador retrocede o head no-ancestro); el **PRIMER export** se verifica
      contra la **génesis registrada en el onboarding** (FR-028); la generación corre **sin egress**;
      metadata-only (0 PII, 0 token crudo). *(SC-012, FR-028, FR-029)*

### Implementation for User Story 5

- [ ] T032 [US5] Implementar `backend/src/licensing/audit_events.py`: emitir cada transición de licencia al
      **AuditLog inmutable existente**, metadata-only, **encadenada por hash** (cada evento incluye el hash
      del anterior; génesis = `license_id`) + verificador de cadena; NO inventar canal nuevo. *(FR-022,
      FR-024, FR-025, FR-028)*
- [ ] T033 [US5] Implementar la **marca monotónica** (último ts de licencia/audit visto); si `now` < marca
      → `license_clock_rollback_suspected` + tratar como degradado (anti-rollback best-effort). *(FR-023)*
- [ ] T034 [US5] Implementar/extender `backend/src/api/health.py`: exponer `{status, seats_used, max_seats,
      expiry}` metadata-only (sin token ni claves) para operación/soporte. *(FR-027)*
- [ ] T041 [US5] Implementar `backend/src/licensing/deployment_key.py` (par Ed25519 generado en el install;
      privada en volumen/secret, nunca en config en claro ni en el repo) y
      `backend/src/licensing/trueup_export.py` (export firmado `{tenant_id, distributor_id, pool_id,
      seats_used, max_seats, historial, hash-head, rango}`, generación local/offline). *(FR-029)*

**Checkpoint**: Todas las transiciones dejan evidencia hash-chained; true-up firmado generable offline;
health de licencia expuesto.

---

## Phase N: Polish & Cross-Cutting Concerns

- [ ] T035 [P] [POLISH] Generar `data-model.md` (consume 013: APIKey/User/Tenant/AuditLog; define el
      pequeño estado de licencia + marca monotónica) y `quickstart.md` (emitir token de prueba offline →
      inyectar en 020 → arrancar sin egress → ver `/health`).
- [ ] T036 [POLISH] Verificación end-to-end con Docker Compose **sin egress** (Principio VII); validar que
      el **mismo binario/imagen** opera con distintos tokens cambiando sólo la config inyectada (020).
      *(SC-010)*
- [ ] T037 [P] [POLISH] Contract test del **formato del token**, del **esquema del evento de audit de
      licencia** (incl. `prev_hash`, FR-028) y del **formato wire del TrueUpExport** (artefacto
      cross-party que Basa verifica — FR-029) en `tests/contract/`; documentar el proceso de **rotación
      de claves** por `key_id`.
- [ ] T038 [POLISH] Documentar la integración con la **020** (dónde/cómo se inyecta el token) y actualizar
      `spec/plan/tasks/changelog` (Dev Workflow — Documentación viva).

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: sin dependencias.
- **Foundational (Phase 2)**: depende de Setup. BLOQUEA todos los user stories (el verificador y el formato
  del token son prerequisito de US1–US5).
- **US1 (Phase 3)**: depende de Foundational. Va **primero** (US2 necesita el entitlement cargado).
- **US2 (Phase 4)**: depende de Foundational + US1 (consume el entitlement para contar contra `max_seats`).
- **US3 (Phase 5)**: depende de Foundational + US2 (reusa la definición de seat); alimenta US4/US5.
- **US4 (Phase 6)**: depende de US1 (entitlement) y se integra con US2 (gate) y US3 (over_seat).
- **US5 (Phase 7)**: depende de US1–US4 existiendo (registra sus transiciones); reusa el audit inmutable.
- **Polish (Phase N)**: depende de los user stories deseados.

### User Story Dependencies

- **US1 (P1)**: tras Foundational. Sin dependencias de otros stories.
- **US2 (P1)**: tras US1 (necesita el entitlement/`max_seats`).
- **US3 (P2)**: tras US2 (misma definición de seat).
- **US4 (P2)**: tras US1; integra con US2/US3.
- **US5 (P3)**: tras US1–US4.

### Within Each User Story

- Tests (⚠️) escritos y FALLANDO antes de implementar.
- Verificador/formato del token antes del entitlement; entitlement antes del gate; gate antes de la
  reconciliación; estado antes del degradado.

### Parallel Opportunities

- Setup: T002 [P].
- Foundational: T006 [P] (unit tests) mientras se prepara T007.
- Tests de cada story marcados [P] corren en paralelo (archivos distintos).
- US3 (reconciliación) puede desarrollarse en paralelo a US4 (ciclo de vida) una vez cerradas US1+US2
  (comparten la definición de seat pero tocan archivos distintos).

---

## Parallel Example: User Story 2

```bash
# Tests de US2 juntos (distintos archivos):
Task: "Unit seat_counter en tests/unit/test_seat_counter.py"
Task: "Integration gate en keys en tests/integration/test_seat_gate_keys.py"
Task: "Integration gate en users en tests/integration/test_seat_gate_users.py"
Task: "Integration coexistencia 402/403 vs 409 en tests/integration/test_gate_coexist.py"
Task: "Integration seats != uso en tests/integration/test_seats_not_usage.py"
```

---

## Implementation Strategy

### MVP First (US1 + US2)

1. Phase 1 Setup → Phase 2 Foundational (formato del token + verificador offline).
2. Phase 3 US1 (verificación al arranque, fail-closed, offline).
3. Phase 4 US2 (gate de seats en creación: no se puede crear el asiento N+1).
4. **STOP & VALIDATE**: arrancar sin egress con token válido; intentar crear más allá de `max_seats` →
   402/403 sin provisioning; revocar → OK. Enforcement offline básico listo.

### Incremental Delivery

1. Foundational → base lista (token + verificador).
2. US1 + US2 → **MVP** (licencia verificada offline + gate de seats fail-closed).
3. US3 → reconciliación (red de seguridad contra drift/backup/DB directa).
4. US4 → expiry + grace + modo degradado (ciclo de vida y aterrizaje suave).
5. US5 → evidencia de tamper en audit inmutable (valor anti-tamper del modelo distribuidor).

### Parallel Team Strategy

Tras Foundational: Dev A → US1+US2 (verificación + gate); Dev B → US3 (reconciliación) una vez fijada la
definición de seat; Dev C → US4 (ciclo de vida). US5 lo cierra quien consolida el audit + health.

---

## Notes

- [P] = archivos distintos, sin dependencias.
- [Story] mapea cada tarea a su user story para trazabilidad.
- Verificar que los tests ⚠️ fallan antes de implementar.
- Commit tras cada tarea o grupo lógico; verificación local con Docker Compose (**sin egress**) antes de
  mergear.
- **Reuse vs propio**: se reusan `APIKey`/`User`/`Tenant`/`AuditLog` (013), el pre-check/índice de seat, el
  call-site de creación y el scheduler; sólo el verificador + entitlement + gate + reconciliación + eventos
  de licencia son código propio.
- **Fail-closed siempre**: "sin token" NUNCA significa "ilimitado"; revisar todos los early-returns del
  gate (FR-006/FR-010).
- **Seats ≠ uso**: `max_seats` cuenta asientos; `rpm_limit`/`tpm_limit`/`max_budget` (007) son gobernanza
  de uso, ortogonal (FR-012).
- **Offline por diseño**: 0 phone-home; verificación y reconciliación 100% locales (modelo distribuidor,
  cajas sin egress).
- **Numeración**: T039–T041 se añadieron con el addendum 2026-07-14 (cadena de hashes + true-up firmado,
  FR-028/FR-029) y viven en la Phase 7 (US5) aunque su ID sea posterior a los T035–T038 de Polish.
- **El gate es fricción, el contrato es el ancla**: el seat-gate y la cadena de hashes hacen el tamper
  **detectable**, no imposible (el cliente controla el runtime). El enforcement real = true-up en la
  renovación sobre el TrueUpExport firmado + audit-rights del EULA (research addendum).
- **Emisión central**: la caja sólo valida su hoja `.lic`; el techo del pool del distribuidor
  (`sum(hojas) ≤ max_total_seats`) se valida en el portal de emisión de Basa (FR-030), fuera de scope acá.
