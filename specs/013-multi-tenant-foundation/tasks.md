---
description: "Task list — Spec 013 Multi-Tenant Foundation & Client Model"
---

# Tasks: Multi-Tenant Foundation & Client Model

**Input**: Design documents from `/specs/013-multi-tenant-foundation/`

**Prerequisites**: [plan.md](./plan.md) (required), [spec.md](./spec.md) (user stories)

**Tests**: SÍ incluidos — la Constitución (Workflow 3, Tested & Verified) exige tests para lógica no trivial;
la migración con backfill + RLS + los CHECK/unicidad son load-bearing y llevan tests de contrato.

**Organización**: tareas agrupadas por user story (US1–US6) para implementación/test independiente.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: puede correr en paralelo (distinto archivo, sin dependencias)
- **[Story]**: US1–US6 según spec.md
- Rutas exactas incluidas. Backend en `backend/`.

## Path Conventions

- Backend: `backend/src/`, migraciones `backend/alembic/versions/`, tests `backend/tests/`.

---

## Phase 1: Setup (Shared Infrastructure)

- [X] T001 Verificar baseline: `alembic current` está en `009`; DB Postgres single-tenant poblada disponible en Docker Compose para tests de migración (`backend/`).
- [X] T002 [P] Confirmar que la app se conecta como `basa_admin` (dueño de las tablas) y documentar el requisito de `FORCE ROW LEVEL SECURITY` en el header de la migración.
- [X] T003 [P] Crear archivo de config de ejemplo `backend/config/clients.example.yaml` (schema del `client_spec` para `seed_client`: client_type, tools[], toggles, budget).

---

## Phase 2: Foundational (Blocking Prerequisites)

**⚠️ CRITICAL**: ninguna user story puede empezar hasta completar esta fase — es el esquema base que todas consumen.

- [X] T004 [P] Crear modelo `Tenant` en `backend/src/models/tenant.py` (id UUID PK, name, slug UNIQUE, is_active, deployment_mode CHECK, defaults de cascada, compression_* espejo, timestamps). FK circulares `default_compliance_project_id`/`default_security_policy_id` NULLable. (FR-001)
- [X] T005 Registrar `Tenant` en el metadata/`Base` de SQLAlchemy y en los imports de modelos (`backend/src/models/__init__.py`).
- [X] T006 Crear el esqueleto de la migración `backend/alembic/versions/010_multitenant_foundation.py` (`revision='010'`, `down_revision='009'`, `upgrade`/`downgrade` idempotentes vacíos con el header de FORCE RLS).

**Checkpoint**: entidad `Tenant` definida y migración esqueleto lista — las user stories pueden empezar.

---

## Phase 3: User Story 1 — Migración con default-tenant backfill (Priority: P1) 🎯 MVP

**Goal**: aplicar la migración deja toda fila preexistente en un default tenant; el on-prem single-tenant sigue andando; idempotente y reversible.

**Independent Test**: `alembic upgrade head` sobre DB poblada → 1 fila `tenants` (`…0001`), todas las filas con `tenant_id` NOT NULL; re-`upgrade` no falla ni duplica; `downgrade -1` deja la DB consistente.

### Tests for User Story 1 ⚠️ (escribir primero, deben FALLAR)

- [X] T007 [P] [US1] Test up/down + idempotencia en `backend/tests/test_migration_010.py` (upgrade dos veces no falla; `tenants` tiene 1 fila; downgrade revierte sin inconsistencia). (SC-001, SC-009)
- [X] T008 [P] [US1] Test de backfill en `backend/tests/test_migration_010.py` (todas las filas de las 8 tablas → `tenant_id=…0001`, NOT NULL; filas huérfanas con `user_id` NULL caen al default). (SC-001, SC-002)

### Implementation for User Story 1

- [X] T009 [US1] Paso 1 migración: `CREATE TABLE IF NOT EXISTS tenants` (sin FK circulares) + `CREATE UNIQUE INDEX IF NOT EXISTS ix_tenants_slug`. (FR-001)
- [X] T010 [US1] Paso 2: `INSERT` default tenant `…0001`/`slug='default'`/`on_premise` con `ON CONFLICT (id) DO NOTHING`. (FR-002)
- [X] T011 [US1] Paso 3 por cada una de las 8 tablas: `ADD COLUMN IF NOT EXISTS tenant_id` → backfill (relacional para audit/keys/budgets, default para el resto) → `SET NOT NULL` → `ADD CONSTRAINT fk_<t>_tenant` (bloque DO $$ IF NOT EXISTS) → `CREATE INDEX ix_<t>_tenant_id` (+ `(tenant_id, timestamp)` en audit_logs). (FR-004, FR-005)
- [X] T012 [US1] Manejar FK circular: añadir `default_compliance_project_id`/`default_security_policy_id` FKs de `tenants` tras poblar `compliance_projects`/`security_policies`, o dejarlas NULLable. (edge case FK circular)
- [X] T013 [US1] `downgrade()`: revertir columnas/FKs/índices de tenant_id y `DROP TABLE IF EXISTS tenants`, dejando la DB consistente. (FR-023, SC-009)
- [X] T014 [US1] Añadir `tenant_id` a los modelos SQLAlchemy de las 8 entidades (`user.py`, `budget.py`, `policy.py`, `guardian.py`, `compliance.py`, `audit.py`) para que el ORM coincida con el esquema migrado.

**Checkpoint**: US1 funcional — el on-prem migra sin regresión, idempotente y reversible. **MVP.**

---

## Phase 4: User Story 2 — Reconciliación del modelo de roles (Priority: P1)

**Goal**: `role` pasa a CHECK enum; `clinician`/`developer` degradados a `display_label`; backfill de valores legacy antes del CHECK.

**Independent Test**: INSERT/UPDATE de `role` fuera del enum viola el CHECK; los 4 válidos pasan; mapeo `admin→tenant_admin`, `clinician`/`developer→client`+label verificado.

### Tests for User Story 2 ⚠️

- [X] T015 [P] [US2] Test de CHECK + backfill de roles en `backend/tests/test_role_reconciliation.py` (rechaza `'clinician'`/`'hacker'`; acepta los 4; verifica el mapeo y `display_label` conservado; `super_admin` NO autogenerado). (SC-005)

### Implementation for User Story 2

- [X] T016 [US2] Paso 4 migración: `ADD COLUMN IF NOT EXISTS display_label`; backfill `admin→tenant_admin`, `clinician→client`+label, `developer→client`+label. (FR-008, FR-009)
- [X] T017 [US2] `DROP CONSTRAINT IF EXISTS ck_users_role` + `ADD CONSTRAINT ck_users_role CHECK (role IN (...))` — DESPUÉS del backfill de valores. (FR-010)
- [X] T018 [US2] Actualizar el modelo `User` en `backend/src/models/user.py`: `display_label` + documentar el enum de `role` (los 4 valores) sin autogenerar `super_admin`. (FR-011)

**Checkpoint**: US1 + US2 — esquema de tenant + eje de roles reconciliado, ambos testeables.

---

## Phase 5: User Story 3 — Aislamiento por tenant con RLS (Priority: P1)

**Goal**: RLS `ENABLE`+`FORCE` por tabla tenant-scoped con policy `tenant_isolation` (GUC + bypass); ninguna query cruza tenant.

**Independent Test**: `SET app.current_tenant=<A>` → 0 filas de B; INSERT con tenant ajeno rechazado; `app.bypass_rls='on'` ve todo; GUC vacío no explota.

### Tests for User Story 3 ⚠️

- [X] T019 [P] [US3] Test de aislamiento RLS en `backend/tests/test_rls_isolation.py` con dos tenants: SELECT aislado, INSERT cross-tenant rechazado por WITH CHECK, bypass super_admin, GUC vacío no explota (NULLIF). (SC-003)
- [X] T020 [P] [US3] Test de FORCE efectivo en `backend/tests/test_rls_isolation.py` conectado como `basa_admin` (dueño): la RLS sí aísla; documentar que sin FORCE fallaría. (SC-004)

### Implementation for User Story 3

- [X] T021 [US3] Paso 7 migración: por cada tabla tenant-scoped `ENABLE ROW LEVEL SECURITY` + `FORCE ROW LEVEL SECURITY`. (FR-019)
- [X] T022 [US3] `DROP POLICY IF EXISTS tenant_isolation` + `CREATE POLICY tenant_isolation` con `USING`/`WITH CHECK` = `tenant_id = NULLIF(current_setting('app.current_tenant',true),'')::uuid OR current_setting('app.bypass_rls',true)='on'`. (FR-020, FR-021)
- [X] T023 [US3] `downgrade()`: `DROP POLICY IF EXISTS` + `DISABLE ROW LEVEL SECURITY` por tabla. (FR-023)
- [X] T024 [US3] Runtime: modificar `backend/src/database.py::get_db` para `SET LOCAL app.current_tenant='<uuid>'` por request desde la identidad resuelta (fail-closed, NUNCA default silencioso) + mecanismo `app.bypass_rls` para super_admin. Coordinado con el deploy (políticas permisivas hasta cablear el GUC). (FR-024, SC-3)

**Checkpoint**: US1+US2+US3 — aislamiento duro activo. Los 3 P1 completan el core del bedrock.

---

## Phase 6: User Story 4 — Entidad Tenant y jerarquía / cascada (Priority: P2)

**Goal**: `Tenant` como raíz con defaults; cascada de resolución Client(User) > Group > Tenant funciona reutilizando el patrón override existente.

**Independent Test**: client sin override hereda de Group; sin default de grupo hereda de Tenant; override de User gana.

### Tests for User Story 4 ⚠️

- [X] T025 [P] [US4] Test de cascada en `backend/tests/test_context_resolution.py` (3 casos: hereda de tenant, hereda de group, override de user, para legal_basis/risk_level/compliance_project). (SC-007)

### Implementation for User Story 4

- [X] T026 [US4] Poblar los defaults de cascada en `Tenant` (legal_basis, risk_level, compliance_project_id, security_policy_id, compression_*) en el modelo `backend/src/models/tenant.py`. (FR-001)
- [X] T027 [US4] Servicio de resolución de la **cascada de defaults de contexto** (`legal_basis`, `risk_level`, `compliance_project_id`) que aplica precedencia `User > Group > Tenant` reutilizando el patrón `User.legal_basis > Group.default_*`, elevando `Tenant` como raíz. La resolución vive en servicio, no en DB. **Alcance 013**: SOLO estos 3 defaults de contexto; la cascada de `SecurityPolicy`/`entity_configs` es spec 015. (FR-022, SC-007)

**Checkpoint**: la jerarquía de defaults sobre el aislamiento funciona.

---

## Phase 7: User Story 5 — Client como dato: `client_type` + Connection (Priority: P2)

**Goal**: client = `User role='client'`+`client_type`; Connection = `APIKey` extendida (`tool_type`, `upstream_mode`, toggles); reuse over reinvent.

**Independent Test**: crear client persiste; CHECK rechaza role inválido / client_type sin role='client'; Connection resuelve identidad por key_hash; UNIQUE (tenant,user,tool) rechaza duplicado; toggles NULL=heredar.

### Tests for User Story 5 ⚠️

- [X] T028 [P] [US5] Test de client model en `backend/tests/test_client_model.py`: CHECK `client_type`/`role`; UNIQUE `(tenant_id,user_id,tool_type)`; `key_hash` sigue global; `subscription-passthrough` exige `oauth_credential_ref`. (SC-006)
- [X] T029 [P] [US5] Test de toggles por-key en `backend/tests/test_client_model.py`: `redact_enabled=NULL` hereda, `True/False` override; idem `compression_mode`/`allowed_models`. (FR-014)

### Implementation for User Story 5

- [X] T030 [US5] Paso 5 migración: `ADD COLUMN client_type` + CHECK `(base_url|desktop|chat_ui)` + CHECK `(client_type IS NULL OR role='client')`. (FR-012)
- [X] T031 [US5] Extender `api_keys` en la migración: `tool_type` (backfill `'claude-code'`→NOT NULL, CHECK 6 valores), `upstream_mode` (DEFAULT `'byok'`, CHECK), `oauth_credential_ref` NULL, toggles NULLable (`redact_enabled`, `compression_mode`, `allowed_models`, `allowed_tools`). (FR-013)
- [X] T032 [US5] Paso 6 migración: unicidad compuesta — `DROP` UNIQUE global de `users.username`/`users.email`/`groups.name` usando los **nombres auto-generados exactos** (`users_username_key`, `users_email_key`, `groups_name_key`) con `DROP CONSTRAINT IF EXISTS` o `DROP INDEX IF EXISTS` (idempotente; verificar con `\d` antes); `CREATE UNIQUE INDEX (tenant_id, …)`; `CREATE UNIQUE INDEX (tenant_id, user_id, tool_type)`; dejar `api_keys.key_hash` global. (FR-006, FR-017, FR-018)
- [X] T033 [US5] Actualizar modelos: `User.client_type` en `backend/src/models/user.py`; `APIKey` (=Connection, tabla `api_keys`) con `tool_type`/`upstream_mode`/`oauth_credential_ref`/toggles + relationship/constraints en `backend/src/models/budget.py` (el modelo `APIKey` vive AHÍ, no en `user.py`); documentar "Connection" como naming público. (FR-013, FR-016)
- [X] T034 [US5] Verificar que `oauth_credential_ref` guarda una **referencia** a secreto Fernet, nunca el token en claro (SC-5); documentar en el modelo. (FR-015)

**Checkpoint**: el client como dato y la Connection por herramienta existen a nivel esquema.

---

## Phase 8: User Story 6 — Onboarding-as-data idempotente (Priority: P3)

**Goal**: `seed_client(tenant, spec)` crea client + Connections + budget desde YAML, idempotente, sin tocar código.

**Independent Test**: `seed_client` crea User(role=client)+Connections+Budget tenant-scoped; re-ejecutar no duplica; dos tenants con mismo username no colisionan.

### Tests for User Story 6 ⚠️

- [X] T035 [P] [US6] Test de idempotencia en `backend/tests/test_seed_client.py`: doble ejecución = 0 duplicados (clave `(tenant_id,user_id,tool_type)`); unicidad compuesta permite mismo username en 2 tenants. (SC-008)

### Implementation for User Story 6

- [X] T036 [US6] Implementar `seed_client(tenant, client_spec)` en `backend/src/services/onboarding.py`: upsert `User(role=client)+client_type` + N Connections + `Budget(user)`, tenant-scoped, leyendo el YAML de T003. **Reutilizar** la lógica de creación de keys/clients ya existente en `backend/src/api/keys.py` (reuse over reinvent). (FR-025)
- [X] T037 [US6] **Portar** `seed_gateway_demo` desde el fork externo *gatelite* (NO existe en este repo) como caso de `seed_client` leído de config — o construirlo sobre `backend/src/api/keys.py` — (config+seed, nunca fork — VII). (FR-025)

**Checkpoint**: sumar un client/demo = 0 líneas de código.

---

## Phase N: Polish & Cross-Cutting Concerns

- [X] T038 [P] Documentar en `specs/013-multi-tenant-foundation/` la decisión de alcance de las 5 tablas de compliance no listadas (`consent_records`, `dpa_registry`, `data_subject_requests`, `human_reviews`, `retention_policies`): incluir `tenant_id`+RLS o diferir (FR-007). Si se incluyen, extender T011/T021/T022 a esas tablas.
- [X] T039 Verificación local con Docker Compose (Postgres real): correr la suite completa + `alembic upgrade`/`downgrade` roundtrip sobre DB poblada. (Constitución Workflow 3)
- [X] T040 [P] Actualizar `spec/plan/tasks/changelog` sincronizados (documentación viva, Workflow 4); marcar en ROADMAP-guardian que 013 desbloquea 014/015/017.
- [X] T041 Nota de coordinación de deploy: documentar el orden migración ↔ `get_db` (GUC) y la ventana de políticas permisivas para evitar 0-filas (riesgo runtime).

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: sin dependencias.
- **Foundational (Phase 2)**: depende de Setup — **BLOQUEA todas las user stories** (define `Tenant` + esqueleto de migración).
- **US1 (Phase 3)**: base de todo; los pasos de migración de US2/US3/US5 se añaden **sobre** la misma migración 010, por lo que se implementan en orden (US1 → US2 → US3 → US5) dentro del archivo de migración aunque sus tests sean independientes.
- **US4 (Phase 6)**: depende de `Tenant` (Phase 2) y del backfill (US1); independiente de US3.
- **US5 (Phase 7)**: depende de `tenant_id` (US1) y del enum de roles (US2).
- **US6 (Phase 8)**: depende de US1 + US2 + US5 (necesita client model completo).
- **Polish (Phase N)**: tras las user stories deseadas.

### Within Each User Story

- Tests primero (deben FALLAR) → migración/modelo → verificación.
- Modelos antes de servicios; servicios antes de runtime.

### Parallel Opportunities

- Setup: T002, T003 en paralelo.
- Foundational: T004 [P] con la preparación de T003.
- Tests marcados [P] dentro de cada story corren en paralelo (distinto archivo de test).
- **Ojo**: los pasos de la **migración 010** (T009–T013, T016–T017, T021–T023, T030–T032) tocan el **mismo archivo** → NO son paralelos entre sí; se secuencian en el orden del plan.

---

## Implementation Strategy

### MVP First (US1)

1. Setup + Foundational (Tenant + esqueleto migración).
2. US1: migración con backfill + downgrade → **STOP & VALIDATE** (on-prem migra sin regresión, idempotente).
3. Deploy/demo del bedrock latente.

### Incremental Delivery

1. US1 (backfill) → US2 (roles) → US3 (RLS) = los 3 P1 = aislamiento duro completo.
2. US4 (cascada) + US5 (client model) = P2, gobernanza sobre el aislamiento.
3. US6 (seed_client) = P3, onboarding sin código.
4. Cada story añade valor sin romper las previas.

### Coordinación crítica de deploy

- La migración 010 (esquema + FORCE RLS) y el cambio de `get_db` (GUC `app.current_tenant`) se despliegan
  **coordinados**: activar políticas permisivas o cablear el GUC **antes** de forzar RLS en runtime, para no
  dejar la app devolviendo 0 filas (riesgo #2 del plan).

## Notes

- [P] = distinto archivo, sin dependencias. Los pasos de la migración única 010 NO son [P] entre sí.
- [Story] mapea cada tarea a su user story para trazabilidad.
- Verificar que los tests fallan antes de implementar.
- Commit tras cada tarea o grupo lógico; verificación local Docker Compose antes de mergear.
- Forward-looking marcado explícito: resolver de policy (015), firewall (014), fallback admin+SSO (017),
  refactor de permisos `developer`→`client` en `rbac.py` (017) — NO se declaran hechos en 013.
