# Implementation Plan: Multi-Tenant Foundation & Client Model

**Branch**: `013-multi-tenant-foundation` | **Date**: 2026-07-10 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification desde `/specs/013-multi-tenant-foundation/spec.md`

## Summary

Convertir el esquema **hoy single-tenant** (cero `tenant_id`, sin RLS, `role` texto libre) en el **bedrock
multi-tenant** del producto, **sin romper el on-prem existente**. Se introduce la entidad `Tenant` (raíz de la
jerarquía Tenant→Group→Client→Connection), se añade `tenant_id` a las 8 entidades pedidas con backfill a un
**default tenant de UUID fijo**, se reconcilia `role` a un CHECK enum (`super_admin`/`tenant_admin`/
`compliance_officer`/`client`) degradando `clinician`/`developer` a `display_label`, se modela el **client** como
`User role='client'` + `client_type` y la **Connection** como `APIKey` **extendida** (reuse over reinvent), y se
activa **Row-Level Security** de Postgres (ENABLE + **FORCE**) con GUC de sesión `app.current_tenant` + bypass
`app.bypass_rls`. Todo via una **migración Alembic idempotente y reversible** (`010`), coordinada con un cambio de
runtime en `get_db` que inyecta el GUC por request.

**Enfoque de altura**: 013 entrega **esquema + aislamiento + default por tenant + onboarding-as-data**. La
**resolución en cascada efectiva** de policies (015), el **firewall** que consume la identidad (014), el
**cierre del fallback admin + SSO** (017) y la **des-singletonización fina** de `entity_configs` (015) son
forward-looking explícitos — 013 solo provee los slots y no los declara hechos.

## Technical Context

**Language/Version**: Python 3.11 (FastAPI backend heredado)

**Primary Dependencies**: SQLAlchemy + **Alembic** (migraciones), FastAPI, LiteLLM (motor white-label, no tocado
aquí), Pydantic. Fernet (cryptography) para el secreto OAuth de `subscription-passthrough`.

**Storage**: **PostgreSQL** (RLS es específico de Postgres — precondición dura del aislamiento). Redis existe
(cache de compresión) pero no participa de esta spec.

**Testing**: **pytest** (se hereda la suite 20/20); tests de migración up/down + tests de RLS con dos tenants +
tests de CHECK/unicidad + test de cascada de resolución.

**Target Platform**: Linux server en containers (Docker Compose es la base de verificación local, Constitución VII).

**Project Type**: web-service (backend FastAPI + frontend React/Vite; esta spec es **backend/schema-only**).

**Performance Goals**: la migración debe correr sobre DB poblada single-tenant sin downtime prohibitivo; los
índices `ix_<tabla>_tenant_id` (+ compuesto `(tenant_id, timestamp)` en `audit_logs`) mantienen los lookups del
dashboard eficientes bajo RLS.

**Constraints**: idempotencia (`IF NOT EXISTS`/`ON CONFLICT`/`DROP … IF EXISTS`) y reversibilidad
(`downgrade()`); **cero regresión** para on-prem single-tenant; **FORCE RLS** obligatorio (la app es dueña de las
tablas); GUC casteado con `NULLIF(...,'')::uuid` para no explotar cuando no está seteado.

**Scale/Scope**: 8 entidades pedidas + 1 nueva (`Tenant`) + (recomendado) 5 tablas de compliance; una migración
Alembic; cambios de modelos SQLAlchemy; un cambio de runtime en `get_db`; una función `seed_client`.

## Constitution Check

*GATE: debe pasar antes de implementar. Re-check tras el diseño.*

| Principio / Constraint | Cómo lo cumple 013 |
|---|---|
| **III — Multi-Tenant by Design** (forward-looking) | Materializa el requisito: `tenant_id` en las 8 entidades + backfill + índices + **RLS**; jerarquía Tenant→Group→Client→Connection; `role` a CHECK enum; `clinician`/`developer`→`display_label`. Honesto: marcado "a construir", no hecho. |
| **IV — Client Onboarding as Data** | `User role='client'` + `client_type`; virtual key por herramienta (`APIKey`=Connection con `tool_type`); gobernanza a nivel persona, toggles a nivel key; `seed_client` sin tocar código. |
| **VII — Config+Seed, never fork** | `Tenant.slug` habilita despliegues por cliente (Elea, Cámara) como datos; `seed_client` productiviza `seed_gateway_demo`; "Connection" como naming neutro sobre `api_keys`. |
| **SC-3 — Fail-closed identidad** | El `tenant_id` de runtime viene de identidad válida (`get_db` inyecta el GUC), NUNCA default silencioso. El cierre del fallback admin completo es 017; 013 no introduce un default silencioso. |
| **SC-4 — Tenant Isolation / RLS** | RLS `ENABLE`+**FORCE** con policy `tenant_isolation`; test explícito de que sin FORCE fallaría. |
| **SC-5 — Fernet para secretos** | `oauth_credential_ref` es **referencia** a secreto Fernet, nunca token en claro. |
| **Workflow 2 — Reuse over Reinvent** | Connection **extiende** `APIKey`; no se crea tabla `connections` (rompería `audit_logs.api_key_id` + migraciones 003–012). |
| **Workflow 3 — Tested & Verified** | Migración up/down + RLS + CHECK + cascada llevan tests; verificación local Docker Compose. |

**Veredicto**: PASA. Una sola desviación potencial (incluir las 5 tablas de compliance no listadas) se documenta
en Complexity Tracking como decisión de alcance enmendable.

## Decisiones técnicas (reuse over reinvent, LiteLLM-native donde aplique)

1. **Connection = `APIKey` extendida (misma tabla `api_keys`), NO tabla nueva.** `APIKey` ya modela "virtual key
   por herramienta, identidad por `key_hash`, ligada a user+group" — es lo que `seed_gateway_demo` crea hoy.
   Renombrar rompería `audit_logs.api_key_id` y las relationships de Group/User sin ganancia. "Connection" queda
   como naming público/UI (white-label, VII). *(Alternativa `connections` rechazada, listada para trazabilidad.)*
2. **CHECK constraint sobre `role`, no ENUM nativo de Postgres.** `DROP/ADD CONSTRAINT` es idempotente sin
   `ALTER TYPE`; coherente con el estilo `op.execute` de 001–009.
3. **RLS con GUC de sesión, no roles Postgres por tenant.** Un solo rol de conexión; tenant inyectado por
   `SET LOCAL app.current_tenant`. **`FORCE ROW LEVEL SECURITY` obligatorio** (la app corre como `sentinel_admin`,
   dueño de las tablas, que bypasearía RLS por defecto).
4. **UUID fijo del default tenant (`…0001`).** Determinismo para seeds/backfill/tests e idempotencia
   (`ON CONFLICT DO NOTHING`).
5. **`admin → tenant_admin` en el backfill** (no `super_admin`): el admin on-prem gestiona SOLO su tenant;
   `super_admin` cross-tenant se siembra aparte, solo cloud.
6. **Gobernanza legal a nivel persona, toggles a nivel key** (IV literal): `compliance_project_id`/`legal_basis`
   no se duplican en la Connection; toggles por-key con semántica **NULL=heredar**.
7. **LiteLLM-native (VI)**: el motor **no se toca** en 013. `rpm_limit`/`tpm_limit` por-key siguen delegados a
   LiteLLM como backstop. La única excepción de proxy propio (OAuth `subscription-passthrough`) se **modela**
   aquí (`upstream_mode`/`oauth_credential_ref`) pero su implementación de forwarding es 014.
8. **`SecurityPolicy.tenant_id` como primer paso**, no el resolver: la cascada `client>group>tenant>default` es
   015; 013 solo añade la columna de aislamiento y el default por tenant.

## La migración Alembic (010) — backfill, RLS, orden

**Revisión**: `010_multitenant_foundation.py`, `revision='010'`, `down_revision='009'`. **Toda idempotente**
(`IF NOT EXISTS` / `ON CONFLICT DO NOTHING` / `DROP … IF EXISTS` antes de `CREATE POLICY`), estilo `op.execute`
de 001 y 009.

> **Nota de numeración de revisión**: las specs **010 y 011 no produjeron migraciones Alembic** — la última
> revisión real en `backend/alembic/versions/` es `009`, por eso esta migración toma `revision='010'`. Si 010/011
> (u otra spec en vuelo) llegan a emitir una migración, **no deben reclamar la revisión `010`** (colisión de
> `down_revision`): usar un slug/revision-id no colisionable y encadenar `down_revision` correctamente. Verificar
> con `alembic heads` antes de crear el archivo para evitar múltiples heads.

**`upgrade()` — orden obligatorio (el orden importa: CHECK e índices únicos fallan si el backfill no corrió antes):**

1. **`CREATE TABLE IF NOT EXISTS tenants`** — SIN las FK circulares `default_compliance_project_id`/
   `default_security_policy_id` en la creación (se añaden con `ALTER … ADD CONSTRAINT` tras poblar, o se dejan
   NULLable). `CREATE UNIQUE INDEX IF NOT EXISTS ix_tenants_slug`.
2. **`INSERT` default tenant** — `VALUES ('00000000-…-0001','Default Tenant','default','on_premise')
   ON CONFLICT (id) DO NOTHING`. Pivote del on-prem.
3. **Por cada tabla** (`users`, `groups`, `api_keys`, `budgets`, `audit_logs`, `security_policies`, `guardians`,
   `compliance_projects` [+ tablas de compliance si entran en alcance]):
   a) `ALTER TABLE … ADD COLUMN IF NOT EXISTS tenant_id UUID`;
   b) **backfill**: `UPDATE … SET tenant_id='…0001' WHERE tenant_id IS NULL` — para `audit_logs`/`api_keys`/
      `budgets`/`consent_records` **preferir backfill relacional** (`user_id → users.tenant_id`) con fallback al
      default;
   c) `ALTER … ALTER COLUMN tenant_id SET NOT NULL`;
   d) `ADD CONSTRAINT fk_<t>_tenant FOREIGN KEY(tenant_id) REFERENCES tenants(id)` (guardado en bloque
      `DO $$ … IF NOT EXISTS`);
   e) `CREATE INDEX IF NOT EXISTS ix_<t>_tenant_id` (+ `(tenant_id, timestamp)` en `audit_logs`).
4. **Reconciliación de roles** (ANTES del CHECK): `ADD COLUMN IF NOT EXISTS display_label`;
   `UPDATE users SET display_label='clinician', role='client' WHERE role='clinician'`; idem `'developer'`;
   `UPDATE users SET role='tenant_admin' WHERE role='admin'`; luego `DROP CONSTRAINT IF EXISTS ck_users_role`;
   `ADD CONSTRAINT ck_users_role CHECK (role IN ('super_admin','tenant_admin','compliance_officer','client'))`.
5. **Client model**: `ADD COLUMN IF NOT EXISTS client_type` + CHECK `(client_type IN ('base_url','desktop',
   'chat_ui'))` + CHECK `(client_type IS NULL OR role='client')`; extender `api_keys` con `tool_type`
   (backfill `'claude-code'` → NOT NULL), `upstream_mode` (DEFAULT `'byok'`), `oauth_credential_ref`, toggles
   NULLable.
6. **Desglobalizar unicidad**: `DROP` del UNIQUE global de `users.username`/`users.email`/`groups.name`;
   `CREATE UNIQUE INDEX` `(tenant_id, username)`, `(tenant_id, email)`, `(tenant_id, name)`;
   `CREATE UNIQUE INDEX` `(tenant_id, user_id, tool_type)` en `api_keys`. `api_keys.key_hash` **se deja global**.
   > **Nota de nombres de constraint**: los `unique=True` inline de SQLAlchemy generan **nombres auto** con el
   > patrón `<tabla>_<columna>_key` → `users_username_key`, `users_email_key`, `groups_name_key`. El `DROP` DEBE
   > usar **esos nombres exactos** (`ALTER TABLE … DROP CONSTRAINT IF EXISTS users_username_key`, etc.) o
   > `DROP INDEX IF EXISTS` sobre el índice implícito, para ser **idempotente** — no asumir un nombre custom que
   > no existe. Verificar los nombres reales con `\d users` antes de escribir el `DROP`.
7. **RLS** — por cada tabla tenant-scoped:
   `ALTER TABLE … ENABLE ROW LEVEL SECURITY; ALTER TABLE … FORCE ROW LEVEL SECURITY;`
   `DROP POLICY IF EXISTS tenant_isolation ON <t>;`
   `CREATE POLICY tenant_isolation ON <t> USING (tenant_id = NULLIF(current_setting('app.current_tenant',
   true),'')::uuid OR current_setting('app.bypass_rls', true)='on') WITH CHECK (mismo predicado);`

**`downgrade()`** (reversible, destructivo del scope — documentado): `DROP POLICY IF EXISTS` + `DISABLE RLS` por
tabla; `DROP CONSTRAINT ck_users_role`; restaurar UNIQUE globales; `DROP COLUMN IF EXISTS tenant_id` (y las
columnas nuevas) por tabla; `DROP TABLE IF EXISTS tenants`.

**Nota `env.py` / runtime**: `alembic/env.py` corre como el dueño (`sentinel_admin`) — por eso hace falta **FORCE
RLS**. Para que la app aplique RLS **en runtime**, `src/database.py::get_db` debe setear
`SET LOCAL app.current_tenant='<uuid>'` por request (o usar un rol NOSUPERUSER separado). Este cambio de `get_db`
es de runtime y se **coordina** con el deploy de la migración: hasta que el GUC se cablee, arrancar políticas
permisivas o activarlas tras el cableado, para no dejar la app devolviendo 0 filas.

## Orden de implementación

1. **Modelos SQLAlchemy** (`Tenant`, columnas nuevas en `User`/`Group`/`APIKey`/`Budget`/`AuditLog`/
   `SecurityPolicy`/`Guardian`/`ComplianceProject`) — sin lógica, solo esquema.
2. **Migración 010** con el orden de arriba (backfill → constraints → RLS).
3. **Runtime `get_db`** (inyección del GUC) + mecanismo de bypass para super_admin.
4. **`seed_client`** (onboarding-as-data) leyendo YAML.
5. **Tests**: migración up/down, backfill, CHECK de rol, unicidad compuesta, RLS + FORCE + bypass, cascada,
   idempotencia de `seed_client`.
6. **Verificación local** con Docker Compose (Postgres real, RLS efectiva).

## Riesgos

| Riesgo | Mitigación |
|---|---|
| **`FORCE RLS` omitido**: la app (dueña de las tablas) bypasea RLS → falso sentido de seguridad (viola SC-4). | Test explícito conectado como `sentinel_admin` que prueba que sin FORCE fallaría; FORCE en la migración por cada tabla. |
| **GUC no seteado + FORCE activo** → todas las queries devuelven 0 filas / fallan por cast → caída total. | Coordinar deploy migración ↔ cambio `get_db`; arrancar políticas permisivas o activarlas tras cablear el GUC. |
| **`current_setting(...)::uuid` con GUC vacío explota** (`''::uuid`). | `NULLIF(current_setting('app.current_tenant',true),'')::uuid` en la policy. |
| **Filas huérfanas en backfill** (`user_id` NULL en audit/keys/budgets) → `SET NOT NULL` falla. | Fallback explícito al default tenant en el `UPDATE`. |
| **CHECK de `role` falla por valor legacy sucio** no migrado. | El `UPDATE` de backfill de roles corre y se verifica ANTES del `ADD CONSTRAINT`, misma migración. |
| **FK circular `tenants`↔`compliance_projects`/`security_policies`**. | Crear `tenants` sin esas FKs; añadirlas tras poblar, o dejarlas NULLable. |
| **`developer→client` cambia permisos efectivos** (pierde gestión keys/modelos). | Refactor de `rbac.py` + tests + comunicación (forward-looking, coordinado con 017) antes de prod. |
| **`username`/`email` a UNIQUE compuesto rompe login sin tenant**. | Login debe resolver el tenant primero (slug/SSO) — forward-looking 017. |
| **Múltiples `is_active=True` legacy en `SecurityPolicy`** si 013 toca dedupe. | Dedupe previo antes de cualquier índice único (el scope fino es 015). |
| **Downgrade destructivo del scope**. | Documentado; solo para test/rollback; `downgrade()` deja la DB consistente. |

## Project Structure

### Documentation (this feature)

```text
specs/013-multi-tenant-foundation/
├── spec.md      # Qué y por qué (user stories, FR, SC)
├── plan.md      # Este archivo (enfoque, migración, RLS, riesgos)
└── tasks.md     # Tareas accionables por user story
```

### Source Code (repository root)

```text
backend/
├── src/
│   ├── models/
│   │   ├── tenant.py            # NUEVO: entidad Tenant
│   │   ├── user.py             # MODIFICAR: User/Group — tenant_id, display_label, client_type, role CHECK
│   │   ├── budget.py           # MODIFICAR: Budget.tenant_id; APIKey (=Connection, tabla api_keys) extendida — vive AQUÍ, no en user.py
│   │   ├── policy.py           # MODIFICAR: SecurityPolicy.tenant_id
│   │   ├── guardian.py         # MODIFICAR: tenant_id
│   │   ├── compliance.py       # MODIFICAR: ComplianceProject.tenant_id (+ compliance siblings si en alcance)
│   │   └── audit.py            # MODIFICAR: AuditLog.tenant_id
│   ├── auth/
│   │   └── rbac.py             # MODIFICAR (forward-looking coordinado): mapeo de permisos client/tenant_admin
│   ├── database.py             # MODIFICAR: get_db inyecta SET LOCAL app.current_tenant (runtime, coordinado)
│   └── services/
│       └── onboarding.py       # NUEVO: seed_client(tenant, client_spec) idempotente
├── alembic/
│   └── versions/
│       └── 010_multitenant_foundation.py   # NUEVO: migración con backfill + RLS
└── tests/
    ├── test_migration_010.py   # up/down, backfill, idempotencia
    ├── test_rls_isolation.py    # RLS + FORCE + bypass, dos tenants
    ├── test_role_reconciliation.py  # CHECK enum + backfill de roles
    ├── test_client_model.py     # client_type, Connection, toggles NULL=heredar
    └── test_seed_client.py      # onboarding-as-data idempotente
```

**Structure Decision**: web-service backend. Esta spec es **backend/schema-only**: modelos SQLAlchemy +
migración Alembic + un cambio de runtime en `get_db` + servicio `seed_client`. No hay cambios de frontend en 013
(la UI de gestión de tenants/clients es forward-looking). El motor LiteLLM no se toca (VI).

## Complexity Tracking

> Solo desviaciones que justificar.

| Desviación | Por qué se necesita | Alternativa más simple rechazada porque |
|---|---|---|
| Incluir `tenant_id` + RLS en 5 tablas de compliance **no listadas** en las 8 pedidas (`consent_records`, `dpa_registry`, `data_subject_requests`, `human_reviews`, `retention_policies`) | Son datos por-tenant (consentimientos ligados a user, DPA/DSR/retención por empresa); sin `tenant_id`+RLS serían **fugas de aislamiento cross-tenant** (viola SC-4). | Limitarse a las 8 pedidas dejaría agujeros de RLS conocidos; se marca como **decisión de alcance enmendable de una línea** (FR-007) — si el reviewer prefiere diferirlas, se difieren sin cambiar el resto del diseño. |
| Extender `api_keys` con 8+ columnas (Connection) en la misma migración de fundación | Es el modelo de "client como dato" (IV) y evita una 2ª migración de esquema que bloquearía 014. | Diferir el client model a otra spec obligaría a 014 a traer su propia migración = el bloqueo que 013 debe evitar. |
| Cambio de runtime en `get_db` acoplado a una migración de esquema | La RLS con FORCE es inútil (o rompe todo) sin el GUC inyectado por request. | Hacer solo el esquema dejaría la app devolviendo 0 filas o con RLS inefectiva; se **coordina** el deploy en vez de separarlo. |
