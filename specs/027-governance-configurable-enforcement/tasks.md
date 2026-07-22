# Tasks: Governance configurable y enforcement honesto del firewall

**Input**: Design documents from `/specs/027-governance-configurable-enforcement/`

**Prerequisites**: plan.md, spec.md, research.md (D1-D8, P1-P5), data-model.md, contracts/ (3), quickstart.md

**Tests**: INCLUIDOS — la constitución los exige para lógica no trivial (Development Workflow §3), y SC-001/SC-004 son literalmente tests de contrato.

> **⚠️ Orden respecto a la 016 (PR #21)**: decisión registrada — **la 016 mergea primero**.
> Las tareas marcadas 🔀 tocan archivos que el PR #21 reescribe (`guardian_service.py`,
> `basa_guardrail.py`, `custom_auth.py`, `guardians.py`): no arrancarlas hasta rebasear sobre
> main post-merge de la 016. Todo lo demás puede avanzar ya.
>
> **⚠️ P1 (motor sin identidad en perfil prod)** se trackea aparte (issue #40) y NO está acá.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: paralelizable (archivos distintos, sin dependencias)
- **[US1]** estado honesto (P1, MVP) · **[US2]** configuración por modo/superficie (P2)

---

## Phase 1: Setup

*(No hay proyecto nuevo que inicializar: la feature vive en backend/frontend/litellm existentes.)*

- [ ] T001 Crear rama de trabajo desde `027-governance-configurable-enforcement` actualizada; verificar suite verde de partida (`docker compose run --rm --no-deps backend pytest tests/ -q`)

---

## Phase 2: Foundational (Blocking Prerequisites)

**⚠️ Ninguna user story arranca sin esto.**

- [ ] T002 🔀 **Neutralizar el seed destructivo de guardianes** (prerrequisito P2 del research, PRIMERA tarea por orden explícito de data-model §5): en `backend/src/services/guardian_service.py:33-36`, reemplazar el `db.query(Guardian).delete()` cuando `len < 9` por reconciliación aditiva (crear solo las filas faltantes por `guardian_type`, jamás borrar). Test de regresión: editar un guardián + recargar → la edición sobrevive.
- [ ] T003 [P] Registry `GOVERNANCE_LAYERS` en `backend/src/services/governance_catalog.py` — dataclass frozen + catálogo inicial completo de data-model §2.1-§2.3 (10 capas: 4 piso + 6 gobernables, `planes` frozenset, `requires_service=None` inicial, `default_decision`). Unit tests: inmutabilidad, piso completo, claves estables.
- [ ] T004 [P] Espejo del registry consumible por el resolutor en `litellm/extensions/basa_guardian_policy.py` (import o copia verificada) + **contract test de sincronía** registry↔espejo en `backend/tests/contract/`.
- [ ] T005 [P] Modelo `GovernanceProfile` en `backend/src/models/governance.py` (esquema exacto data-model §1.1: UNIQUE, 3 CHECKs nombrados, centinela `'*'`, `updated_by NOT NULL`).
- [ ] T006 Migración Alembic `backend/alembic/versions/012_governance_profiles_audit_attribution.py` (`down_revision='011'`): tabla + `audit_logs.applied_layers` JSONB + `blocked_by_layer` VARCHAR + índice parcial. **Cero seed** (data-model §5). Test: upgrade+downgrade limpios.
- [ ] T007 **Resolutor puro** `resolve_profile` + `apply_layers` en `litellm/extensions/basa_guardian_policy.py` (contrato resolutor-perfil completo: firma tri-estado con `surface_trusted` y `connection_overrides`, precedencia Connection > superficie confiable > modo > tenant > producto, piso irrepresentable como apagado, relajar-exige-confiable, `PolicyResult` con `applied_layers`/`blocked_by_layer`). Unit tests exhaustivos: propiedad `∀config: piso ⊆ Profile`, tri-estado del override, surface off confiable vs UA, tokens canónicos.
- [ ] T008 [P] Función de mapeo de modo (ruteo efectivo → `subscription|gateway-models`) en la librería compartida, con tests (ruta no mapeada ⇒ `gateway-models`, jamás `upstream_mode` crudo).
- [ ] T009 Resolución por tenant en `backend/src/services/governance_resolution.py`: lee filas de `governance_profiles` + arma `config` para el resolutor (patrón `_first_not_none` de context_resolution). Tests con tenant sin filas (SC-007: postura default de producto).

**Checkpoint**: registry + tabla + resolutor puro testeados en aislamiento.

---

## Phase 3: User Story 1 — El Admin ve el estado REAL de cada capa (P1) 🎯 MVP

**Goal**: vista de gobernanza que jamás reporta activa una capa que no corre (FR-001, SC-001/SC-002).

**Independent Test**: quickstart SC-001/SC-002 — las 3+1 capas reales `aplicandose`, las de proveedor `no_disponible`/`requiere_credencial`, resumen por modo en una vista; `docker stop basa-litellm` → `no_disponible`, jamás activa.

### Tests primero

- [ ] T010 [P] [US1] Contract test SC-001 en `backend/tests/contract/test_governance_status_contract.py`: ∀ capa con `estado_efectivo=aplicandose ∧ 'engine' ∈ planes` ⇒ su nombre ∈ `GET /guardrails/list` de la imagen pineada (D4 punto 6).
- [ ] T011 [P] [US1] Integration test estado honesto en `backend/tests/integration/test_governance_status.py`: motor inalcanzable → `no_disponible` con motivo del catálogo cerrado; capa `off` + sin credencial → `no_disponible` (no `requiere_credencial`, regla §4.1#1); `requires_service` sin confirmar → jamás `aplicandose` (regla 2b).

### Implementación

- [ ] T012 [US1] Sonda `GET /guardrails/list` cacheada (~30 s) en `backend/src/services/ai_engine_client.py` — consumida SOLO en backend, payload jamás reenviado (white-label).
- [ ] T013 [US1] Función de estado en `backend/src/services/governance_status.py` (reglas §4.1 completas, incluida 2b `requires_service`; default `no_disponible` fail-closed; catálogo cerrado de motivos — garantía (f): jamás texto de excepción del motor).
- [ ] T014 [US1] Router `backend/src/api/governance.py` admin-only (espejo guardians.py:17) con `GET /status?mode=&surface=[&tenant_id]` (shape del contrato: `planes` lista, `origen`, `decision_resuelta`⊥`estado_efectivo`; `tenant_id` solo single-tenant, 403 multi-tenant — garantía (g)) + resumen por modo (FR-010/SC-002). Montarlo en main.py.
- [ ] T015 🔀 [US1] **Borrar el trigger DELEGATED fabricado** (`guardian_service.py:334-347`) — la mentira con nombre y línea. Ajustar tests que lo esperaban.
- [ ] T016 🔀 [US1] `GET /guardians` computa y devuelve `status`/`reason`/`planes` desde governance_status (manteniendo `engine_guardrail_name=None`); `PUT /guardians/{id}` que activa capa no confirmada responde el estado recalculado, nunca 200-verde (D4 punto 4).
- [ ] T017 [P] [US1] Frontend: `GovernancePage.tsx` (vista estado honesto + resumen por modo, FR-013 copy que distingue "no la aplicamos" de "desprotegido") + las 3 ediciones sincronizadas de `App.tsx` (union `Page`, nav item `roles: ["admin"]` LEGACY, render) + bloque `// --- Governance ---` en `services/api.ts` (jsonHeaders + `handleExpiredSession` en TODAS — no repetir api.ts:253-267). Distinguir 403 de fallo de red — no repetir el `catch { // silent }`.
- [ ] T018 [P] [US1] `SecurityPage.tsx` (badges :183/:199/:204/:215) y `DashboardPage.tsx` (:71 contador) dejan de leer `is_active`: consumen `status` calculado. `is_active` se renderiza como "deseado" donde aplique.
- [ ] T019 🔀 [US1] Evidencia por pedido: `basa_guardrail.py` adopta `add_guardrail_to_applied_guardrails_header`; `chat.py`/`gateway.py` leen `x-litellm-applied-guardrails` como fuente C del estado.

**Checkpoint / STOP & VALIDATE**: quickstart SC-001 + SC-002 + motor caído, en vivo. **US1 es demo-able por sí sola.**

---

## Phase 4: User Story 2 — Configurar por modo de conexión y superficie (P2)

**Goal**: capas opcionales configurables por alcance con piso inviolable; atribución por pedido en los 3 planos (FR-002..FR-009, SC-003..SC-006).

**Independent Test**: quickstart SC-003 (capas difieren por modo, verificado por status), SC-004 (422 piso + intento registrado), SC-005 (bloqueo atribuible en el monitor), SC-006 (cambio desde UI aplica al instante).

### Tests primero

- [ ] T020 [P] [US2] Contract test del CRUD en `backend/tests/contract/test_governance_profile_contract.py`: 422 piso + evento `governance_floor_violation`; 422 enum (`scope_value` canónicos, centinela `'*'`); DELETE idempotente 204; respuesta PUT = verdad recalculada.
- [ ] T021 [P] [US2] **Re-anclar la paridad**: `tests/contract/test_route_parity.py` pasa a assertar que cada call-site produce lo de `resolve_profile`+`apply_layers` (verdicto + entidades + `applied_layers`) — contrato resolutor #12.
- [ ] T022 [P] [US2] Integration por alcance en `backend/tests/integration/test_governance_enforcement.py`: capa on solo para `gateway-models` → suscripción la lleva `delegated`/`skipped` jamás `applied` (exhaustividad); surface off confiable aplica, UA-derivada no; `X-Basa-Redact` fuerza ON pero jamás OFF; tri-estado (Connection sin toggle NO tapa la cascada); redact-off ⇒ `pii_detection: applied+count` + `pii_masking: skipped`.

### Implementación

- [ ] T023 [US2] CRUD del perfil en `backend/src/api/governance.py`: `GET/PUT /profile`, `DELETE /profile/{scope_type}/{scope_value}/{layer_key}` (contrato completo: validación piso en API + registro del intento, invalidación del cache de identidad ANTES de responder — garantía (e)).
- [ ] T024 🔀 [US2] `custom_auth.py`: perfil resuelto del tenant en `metadata['basa']` (vía SQL de identidad + cache), **fin del colapso NULL→True** (:149 — tri-estado crudo, contrato resolutor #2), mecanismo de invalidación por key (60 s → invalidable), y regla explícita para la master key (piso + perfil default, riesgo del research).
- [ ] T025 🔀 [US2] `basa_guardrail.py`: el hook consume el `Profile` (reemplaza el bloque fijo :82-99), escribe `home['basa_governance']` con `applied_layers`/`blocked_by_layer`, y **emite el evento de monitor en el punto de bloqueo** (contrato evento §12, best-effort, preview display-masked §10).
- [ ] T026 [US2] `gateway.py`: resolver perfil en :477-479 (donde ya están ident/tool/mode), `evaluate_request_policy(body, profile)`, `applied_layers` reemplaza el `guardian_events` PROXY hardcodeado (:285-286), `_resolve_redact` pasa a **solo restrictivo** (header OFF se ignora con telemetría) + actualizar discovery :666, y `_publish_monitor` lleva los campos nuevos.
- [ ] T027 [US2] `chat.py`: call-site del resolutor (reemplaza la lista de guardrails de :353-354), persistencia de `applied_layers`/`blocked_by_layer` vía `AuditService.log_transaction` (columnas nuevas en `audit_service.py`), **evento de monitor en el punto de bloqueo antes del raise** (contrato §13), y `pipeline_metadata` derivado de `applied_layers` (Principio VIII).
- [ ] T028 [US2] `inspect.py`: `gw_inspect` bajo el Profile (fix P4 — corre piso completo) con respuesta de bloqueo `ok:false` + `blocked`/`blocked_by_layer`/`motivo` (contrato: fail-closed para extensiones viejas).
- [ ] T029 [US2] `basa_audit_logger.py`: `applied_layers`/`blocked_by_layer` en `_INSERT_AUDIT_SQL` y en el evento del monitor (mismo esquema que gateway — contrato §8).
- [ ] T030 [P] [US2] `GovernancePage.tsx`: sección de configuración con **autosave optimista + rollback por control** (patrón D7: estado desde la respuesta del server, err.detail en el catch, strip por fila; texto en onBlur/debounce ≥800 ms). Prohibido el botón global.
- [ ] T031 [P] [US2] `analytics.py`: el agregado de guardianes migra de `guardian_events` (clave que nadie escribe, :94) a `applied_layers` — el dashboard deja de contar licencias como activaciones.
- [ ] T032 [P] [US2] `monitor.py`: render de los campos nuevos en la vitrina **escapando TODO por `escapeHtml`** — y de paso los campos existentes que hoy van crudos a innerHTML (:81-87, XSS confirmado en el mapeo del firewall).

**Checkpoint**: quickstart SC-003..SC-006 en vivo.

---

## Phase 5: Polish & Cross-Cutting

- [ ] T033 [P] **Sitio de docs de producto (OBLIGATORIO, DoD)**: páginas de `docs/docs/**` que la feature toca (la sección de gobernanza es NUEVA: qué es el piso, qué se configura, el estado honesto y sus 5 estados, la regla de superficie confiable) — curado marca-neutro, template de docs/README.md, leyenda 🟢/🟡/🔵 honesta — y `make -C deploy check-docs` verde.
- [ ] T034 [P] Correr `quickstart.md` completo contra el stack dev y anotar desvíos (es el gate de la feature).
- [ ] T035 [P] Test negativo white-label sobre `/governance/*`: ninguna respuesta contiene nombres de proveedor ni fragmentos de traceback (garantía (f)).
- [ ] T036 Decidir y documentar P3 (auditoría histórica con `DELEGATED` fabricados: marcar como no confiable vs purgar) — coordinar con Cristian, es frontera con su módulo.
- [ ] T037 Sync final spec/plan/checklist + `speckit-analyze` de consistencia spec↔plan↔tasks antes del PR.

---

## Dependencies & Execution Order

- **Setup (T001)** → **Foundational (T002-T009)** → US1 y US2 pueden ir en paralelo, pero el orden recomendado es **US1 primero** (MVP demo-able, y US2 reusa el endpoint de status para la respuesta del PUT).
- T002 (seed) **antes** que cualquier cosa que toque el catálogo (D1, riesgo).
- T007 (resolutor) bloquea T019/T021/T024-T028.
- Tareas 🔀 (T002, T015, T016, T019, T024, T025): **después del merge de la 016** + rebase.
- T023 depende de T013/T014 (la respuesta del PUT recalcula estado).
- T032 puede adelantarse en cualquier momento (es un fix de seguridad independiente).

## Implementation Strategy

**MVP = Foundational + US1** (STOP & VALIDATE tras T019): entrega el valor de confianza —
"lo que la UI muestra es lo que corre" — sin ninguna capacidad de configuración nueva, tal
como la spec lo declara. US2 encima, story completa. Con `/srdev-claude` (worktrees): las
tareas [P] de cada fase en paralelo; las 🔀 en un branch que rebasea sobre main post-016.
