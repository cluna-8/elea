# Spec 013 — Multi-Tenant Foundation & Client Model

**Feature Branch**: `013-multi-tenant-foundation`

**Created**: 2026-07-10

**Status**: Implementada — estado canónico en [`ROADMAP-guardian.md`](../ROADMAP-guardian.md) — **bedrock del producto** (precondición de 014–018). Ver [`ROADMAP-guardian.md`](../ROADMAP-guardian.md).

**Constitución**: v2.0.0 — Principios **III** (Multi-Tenant by Design), **IV** (Client Onboarding as Data), **VII** (Config+Seed, never fork); constraints **SC-3** (fail-closed identidad), **SC-4** (Tenant Isolation / RLS).

**Input**: "Multi-Tenant Foundation & Client Model — aislamiento por tenant (`tenant_id` + RLS), entidad `Tenant`, jerarquía Tenant→Group→Client→Connection, reconciliación de roles, onboarding-as-data, migración Alembic con default-tenant backfill (single-tenant sigue andando)."

---

## Contexto

> **Nota de honestidad SDD (Constitución, Principio III).** El esquema **HOY es single-tenant**:
> cero `tenant_id`, sin RLS, `users.role` es texto libre sin constraint (comentario legacy
> `admin, compliance_officer, clinician, developer`), y `entity_configs` de `SecurityPolicy` es un
> **singleton global**. Todo lo que esta spec introduce (`Tenant`, columnas `tenant_id`, políticas
> RLS, GUC de sesión, CHECK de `role`, unicidad compuesta) es **forward-looking: a construir**, no
> estado actual. Esta spec **no** declara como hecho nada de lo aspiracional.

El producto **ES la compliance y la gobernanza multi-tenant** (Constitución, cabecera). Sin aislamiento
por tenant y sin un modelo de "client" como dato, **nada del resto del roadmap encaja**: la 014 (firewall)
necesita resolver `tenant/client/tool` desde una virtual key; la 015 (policy scoping) necesita la columna
de tenant; la 017 (RBAC/SSO) necesita el eje de roles reconciliado. Por eso la 013 es el **bedrock**.

El requisito operativo duro: el **mismo código** debe seguir corriendo **single-tenant on-premise** (una
instalación = un tenant, apto para Ollama/vLLM local) además de **multi-tenant cloud** (SaaS). La migración
que introduce el aislamiento **no puede romper** los datos on-prem existentes: se resuelve con un **default
tenant** de UUID fijo al que se hace backfill de todo lo preexistente.

### Alcance de esta spec (qué SÍ / qué NO)

**SÍ (013):**
- Entidad `Tenant` (raíz de la jerarquía) + seed del **default tenant** determinista.
- `tenant_id` en las 8 entidades pedidas (`User`, `Group`, `APIKey`, `Budget`, `AuditLog`,
  `SecurityPolicy`, `Guardian`, `ComplianceProject`) con backfill + índices.
- Reconciliación del modelo de `role` a CHECK enum (`super_admin`/`tenant_admin`/`compliance_officer`/`client`)
  + `display_label` para los labels sectoriales legacy (`clinician`/`developer`).
- Modelo de **Client** = `User role='client'` + `client_type`; **Connection** = `APIKey` **extendida**
  (`tool_type`, `upstream_mode`, toggles por-key) — **reuse over reinvent**, no tabla nueva.
- Unicidad compuesta por tenant (`username`, `email`, `group.name`, `(user_id, tool_type)`).
- **RLS de Postgres** por `tenant_id` (ENABLE + FORCE) con GUC de sesión `app.current_tenant` y bypass
  `app.bypass_rls` para super_admin.
- Migración Alembic idempotente con backfill al default tenant.
- **Onboarding-as-data**: `seed_client(tenant, client_spec)` idempotente leído de config (productiviza el
  `seed_gateway_demo` hardcodeado del fork).

**NO (forward-looking a otras specs, marcado explícito):**
- La **cascada de `SecurityPolicy` / `entity_configs`** (`client > group > tenant > default`) es **spec 015**;
  013 solo añade `SecurityPolicy.tenant_id` como primer paso y NO resuelve `entity_configs` por capa.
  *(Distinto de la cascada de **defaults de contexto** —`legal_basis`/`risk_level`/`compliance_project_id`—
  que SÍ se implementa y testea en 013 reusando el patrón override existente; ver US4, FR-022, SC-007.)*
- El **firewall base_url** que consume la identidad `tenant/client/tool` es **spec 014**.
- El **cierre del fallback admin** en runtime y **SSO** es **spec 017** (SC-3); 013 provee el eje de roles.
- La **des-singletonización fina** de `entity_configs` por grupo/cliente es 015; 013 solo añade `tenant_id`
  a `SecurityPolicy` como primer paso.
- El cableado de `SET LOCAL app.current_tenant` en `get_db` por request es un cambio de runtime que 013
  **especifica** y deja **listo para activar** (ver FR-024 y riesgos), coordinado con el deploy de la migración.

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Migración con default-tenant backfill (single-tenant sigue andando) (Priority: P1) 🎯 MVP

Como operador de un despliegue **on-premise single-tenant**, quiero que la migración que introduce el
aislamiento multi-tenant **no rompa mis datos ni mis flujos**: tras aplicarla, toda fila preexistente queda
asignada a un **default tenant** y el sistema sigue funcionando exactamente igual.

**Why this priority**: es la base de TODO. Sin un backfill que preserve el on-prem, activar `tenant_id NOT NULL`
+ RLS deja la instalación existente con filas huérfanas o con 0 resultados. Es el riesgo #1 del roadmap y el
único slice que, solo, ya entrega valor (aislamiento latente sin regresión). Es **idempotente**: re-ejecutar la
migración no duplica ni falla.

**Independent Test**: sobre una DB poblada single-tenant (usuarios, grupos, keys, budgets, audit logs, policies,
guardians, compliance projects), correr `alembic upgrade head`; verificar que existe **1** fila `tenants`
(`slug='default'`, UUID `00000000-0000-0000-0000-000000000001`), que **todas** las filas preexistentes tienen
`tenant_id` = ese UUID y `NOT NULL`, y que ninguna query de la app rompe. Correr `upgrade` una **segunda** vez
no falla ni duplica.

**Acceptance Scenarios**:

1. **Given** una DB single-tenant poblada, **When** se aplica la migración 010, **Then** se crea la tabla
   `tenants` con exactamente la fila default (UUID `…0001`, `slug='default'`, `deployment_mode='on_premise'`).
2. **Given** filas preexistentes en las 8 tablas, **When** corre el backfill, **Then** cada una tiene
   `tenant_id` = default y la columna queda `NOT NULL` con FK a `tenants.id`.
3. **Given** la migración ya aplicada, **When** se corre `alembic upgrade head` otra vez, **Then** no falla
   (idempotente: `IF NOT EXISTS` / `ON CONFLICT DO NOTHING` / `DROP … IF EXISTS`) y `tenants` sigue con 1 fila.
4. **Given** `audit_logs`/`api_keys`/`budgets` con `user_id` NULL o sin grupo, **When** corre el backfill
   relacional, **Then** esas filas huérfanas caen al default tenant explícitamente (el `SET NOT NULL` no falla).
5. **Given** la migración aplicada, **When** se ejecuta `alembic downgrade -1`, **Then** se revierten
   columnas/políticas/constraints sin dejar la DB inconsistente (reversible, aunque destructivo del scope).

---

### User Story 2 — Reconciliación del modelo de roles (super_admin/tenant_admin/compliance_officer/client) (Priority: P1)

Como arquitecto de seguridad, quiero que `users.role` deje de ser texto libre y pase a un **enum controlado**
(`super_admin`, `tenant_admin`, `compliance_officer`, `client`), con los labels sectoriales legacy
(`clinician`, `developer`) **degradados a `display_label`** (etiqueta de display configurable, no rol),
para tener un eje de acceso coherente por tenant (Constitución III, [D9]).

**Why this priority**: es la otra mitad del bedrock. El firewall (014) y el RBAC (017) resuelven identidad
sobre estos 4 roles; sin el enum + el backfill de valores legacy, cualquier CHECK futuro falla contra datos
sucios. Testeable de forma aislada sobre la tabla `users`.

**Independent Test**: tras la migración, `INSERT`/`UPDATE` de un `users.role` fuera del enum (p.ej. `'clinician'`
o `'hacker'`) viola el CHECK; los 4 roles válidos pasan. Verificar el mapeo: filas legacy `admin` →
`tenant_admin`; `clinician` → `role='client'` + `display_label='clinician'`; `developer` → `role='client'` +
`display_label='developer'`.

**Acceptance Scenarios**:

1. **Given** usuarios legacy con `role='admin'`, **When** corre el backfill de roles, **Then** quedan
   `role='tenant_admin'` (NO `super_admin`: el admin on-prem gestiona SOLO su instalación = su tenant).
2. **Given** usuarios `role='clinician'`/`'developer'`, **When** corre el backfill, **Then** quedan
   `role='client'` con `display_label` conservando la etiqueta original.
3. **Given** el backfill de valores ya ejecutado, **When** se añade el CHECK `role IN (…)`, **Then** la
   creación del constraint no falla (el backfill corre **antes** del `ADD CONSTRAINT`).
4. **Given** el CHECK activo, **When** se intenta `UPDATE users SET role='clinician'`, **Then** viola el
   constraint (los labels sectoriales ya no son roles).
5. **Given** el eje reconciliado, **When** se siembra un `super_admin`, **Then** **no** se autogenera por
   migración: se siembra explícitamente aparte (solo cloud), para que el on-prem no exponga un rol cross-tenant.

---

### User Story 3 — Aislamiento por tenant con RLS de Postgres (Priority: P1)

Como DPO/compliance officer de un tenant cloud, quiero garantía a nivel de base de datos de que **ninguna query
cruza `tenant_id`** (SC-4), reforzada con **Row-Level Security** de Postgres, para que el aislamiento no dependa
solo del código de aplicación.

**Why this priority**: SC-4 es precondición de gobernanza SaaS. Es el control de aislamiento más fuerte y es la
razón de ser del multi-tenant. Testeable de forma aislada con dos tenants sembrados.

**Independent Test**: con `SET app.current_tenant = <tenantA>`, un `SELECT` sobre cada tabla tenant-scoped NO
devuelve filas de `tenantB`; un `INSERT` con `tenant_id` de otro tenant es rechazado por `WITH CHECK`. Con
`SET app.bypass_rls='on'` (super_admin) las queries ven todos los tenants.

**Acceptance Scenarios**:

1. **Given** filas de tenantA y tenantB, **When** `SET app.current_tenant=<A>` y `SELECT * FROM users`,
   **Then** solo aparecen filas de A.
2. **Given** `app.current_tenant=<A>`, **When** `INSERT … VALUES (tenant_id=<B>, …)`, **Then** el `WITH CHECK`
   de la policy lo rechaza.
3. **Given** la app conectada como **`basa_admin` (dueño de las tablas)**, **When** hay RLS `ENABLE` **+ FORCE**,
   **Then** la RLS **sí** aísla (sin `FORCE`, el dueño la bypasearía → falso sentido de seguridad, viola SC-4).
4. **Given** `app.bypass_rls='on'`, **When** un super_admin hace `SELECT`, **Then** ve filas de todos los tenants.
5. **Given** el GUC `app.current_tenant` **no seteado**, **When** la policy evalúa `current_setting(...,true)`,
   **Then** el cast a uuid **no explota** (patrón `NULLIF(current_setting('app.current_tenant',true),'')::uuid`).

---

### User Story 4 — Entidad Tenant y jerarquía Tenant→Group→Client→Connection (Priority: P2)

Como tenant-admin, quiero la **entidad `Tenant`** como raíz de la jerarquía con sus defaults (legal basis, risk
level, compliance project, security policy, compresión), y quiero que la **cascada de defaults de contexto**
(`legal_basis` / `risk_level` / `compliance_project_id`) con precedencia **Client(User) > Group > Tenant**
funcione y esté **testeada en 013**, reutilizando el patrón override ya existente
(`User.legal_basis` > `Group.default_legal_basis`), elevando `Tenant` como raíz.

> **Frontera 013↔015**: 013 implementa y testea la cascada de **defaults de contexto**
> (`legal_basis`/`risk_level`/`compliance_project_id`). La cascada de **`SecurityPolicy`/`entity_configs`**
> por capa es **spec 015**; 013 solo añade `SecurityPolicy.tenant_id`.

**Why this priority**: da la estructura jerárquica que la 015 (cascada de policy) y la 014 (firewall) consumen.
013 entrega la cascada de defaults de contexto funcionando; la cascada de `entity_configs`/policy vive en 015.
Es P2 porque el aislamiento (US1–US3) es el gate duro; la jerarquía de defaults es la capa de gobernanza sobre
ese aislamiento.

**Independent Test**: un client (User) **sin** override hereda `legal_basis`/`risk_level`/`compliance_project_id`
de su `Group`; sin default de grupo, hereda del `Tenant`; el override de `User` gana sobre ambos.

**Acceptance Scenarios**:

1. **Given** `Tenant.default_legal_basis='consent'` y `Group` sin default y `User` sin override, **When** se
   resuelve el **default de contexto** del client, **Then** el efectivo es `'consent'` (heredado del tenant).
2. **Given** `Group.default_legal_basis='contract'` y `User` sin override, **When** se resuelve, **Then** gana
   `'contract'` (el grupo es más específico que el tenant).
3. **Given** `User.legal_basis='legitimate_interest'`, **When** se resuelve, **Then** gana el override del user
   (el cliente es lo más específico). El mismo patrón aplica a `risk_level` y `compliance_project_id`.
4. **Given** `Tenant.default_compliance_project_id` apuntando a un `compliance_projects`, **When** se crea el
   tenant, **Then** la FK circular suave se maneja (FK NULLable, añadida tras poblar) sin bloquear el orden.

---

### User Story 5 — Client como dato: `client_type` + Connection por herramienta (Priority: P2)

Como operador de onboarding, quiero modelar un **client** como `User role='client'` + `client_type`
(`base_url`/`desktop`/`chat_ui`) y emitir una **Connection por herramienta** (`APIKey` extendida con `tool_type`,
`upstream_mode` y toggles por-key), reutilizando la herencia `User → APIKey` existente en vez de inventar una
tabla `connections` (Constitución IV, VII; **reuse over reinvent**).

**Why this priority**: materializa "Client Onboarding as Data" en el esquema. La gobernanza legal vive a nivel
**persona** (`User.compliance_project_id`/`legal_basis`); los toggles operativos viven a nivel **key**. P2 porque
depende de `tenant_id` (US1) y del enum de roles (US2).

**Independent Test**: crear `User role='client'` + `client_type='base_url'` persiste OK; el CHECK rechaza
`role` inválido y rechaza `client_type` no-NULL cuando `role != 'client'`. Emitir una `Connection` (`APIKey`)
`tool_type='claude-code'` + `upstream_mode='byok'`; resolver identidad por `key_hash` devuelve
client → group → compliance_project correctos.

**Acceptance Scenarios**:

1. **Given** `role='client'`, **When** se setea `client_type='base_url'`, **Then** persiste; con `role!='client'`
   y `client_type` no-NULL, el CHECK `(client_type IS NULL OR role='client')` lo rechaza.
2. **Given** un client, **When** se emiten dos `Connection` `tool_type='claude-code'` para él, **Then** el
   UNIQUE `(tenant_id, user_id, tool_type)` rechaza la segunda (≤1 Connection activa por herramienta).
3. **Given** `upstream_mode='subscription-passthrough'`, **When** se crea la Connection, **Then** exige
   `oauth_credential_ref` presente (referencia a secreto Fernet, **nunca** token en claro — SC-5); con `'byok'`
   usa `engine_key_token`.
4. **Given** un toggle por-key `redact_enabled=NULL`, **When** se resuelve, **Then** **hereda** del group/tenant;
   con `redact_enabled=False/True` hace **override** (semántica NULL=heredar, no False=off).
5. **Given** `api_keys.key_hash`, **When** se scopea el resto por tenant, **Then** `key_hash` permanece
   **UNIQUE global** (es material secreto: una colisión debe ser global).

---

### User Story 6 — Onboarding-as-data idempotente (`seed_client`) (Priority: P3)

Como operador, quiero sumar un cliente o un demo **sin tocar código**: una función `seed_client(tenant, spec)`
idempotente que lee un **YAML de config** y crea `User(role=client)+client_type` + N `Connection`s + `Budget(user)`
en una sola operación de datos, tenant-scoped y re-ejecutable sin duplicar (Constitución IV, VII).

**Why this priority**: es la promesa "sumar un cliente NUNCA toca código". `seed_gateway_demo` **NO existe en
este repo** (es código del fork externo *gatelite*); esta spec lo **porta/productiviza** como caso de
`seed_client` leído de config, reutilizando la lógica real de creación de keys/clients que aquí vive en
`backend/src/api/keys.py`. P3 porque necesita todo lo anterior (tenant, roles, client model) como cimiento.

**Independent Test**: `seed_client(tenant, spec_dict)` sobre un tenant crea el client + Connections + budget;
re-ejecutarlo con el mismo spec **no** duplica (clave `(tenant_id, user_id, tool_type)`), sin cambios de código.

**Acceptance Scenarios**:

1. **Given** un `client_spec` YAML (client_type, N tools con toggles, budget), **When** se corre `seed_client`,
   **Then** se crean 1 `User(role=client)`, N `Connection`s y 1 `Budget`, todos con el `tenant_id` del tenant.
2. **Given** un `seed_client` ya ejecutado, **When** se re-ejecuta con el mismo spec, **Then** es idempotente
   (no duplica; upsert por clave natural).
3. **Given** dos tenants distintos, **When** cada uno siembra un client con el **mismo** username, **Then** no
   colisionan (unicidad compuesta `(tenant_id, username)`).

---

### Edge Cases

- **GUC no seteado + FORCE RLS activo**: si `get_db` no inyecta `SET LOCAL app.current_tenant`, **todas** las
  queries devuelven 0 filas (o fallan por cast). La migración de esquema y el cambio de `get_db` deben
  desplegarse **coordinados**; considerar arrancar políticas permisivas hasta que el runtime inyecte el GUC
  (ver FR-024, riesgos).
- **Valor legacy fuera del enum** (`role` sucio no migrado): el CHECK de `role` falla si el UPDATE de backfill
  no cubrió todos los valores → el backfill DEBE ejecutarse y verificarse **antes** del `ADD CONSTRAINT`.
- **Duplicados que solo eran únicos globalmente**: al pasar `username`/`email`/`group.name` a UNIQUE compuesto,
  no hay conflicto en la migración; pero **login sin tenant** (que asumía username global) se rompe → el login
  debe resolver el tenant primero (SSO/slug) — forward-looking 017.
- **FK circular `tenants` ↔ `compliance_projects`/`security_policies`**: `Tenant.default_*` apunta a tablas que
  a su vez llevan `tenant_id`; crear `tenants` **sin** esas FKs y añadirlas tras poblar (o dejarlas NULLable).
- **Filas huérfanas en backfill relacional** (`audit_logs`/`consent_records` con `user_id` NULL): deben ir al
  default tenant explícitamente o el `SET NOT NULL` falla.
- **Degradar `developer` → `client`** cambia permisos efectivos (pierde gestión de keys/modelos en `rbac.py`):
  requiere ajuste de `rbac.py` + comunicación antes de prod (fuera del esquema puro; ver Assumptions).
- **`current_setting('app.current_tenant', true)::uuid` con GUC vacío** → `''::uuid` explota: usar `NULLIF`.
- **`entity_configs` singleton con múltiples `is_active=True` legacy** (bug heredado en `SecurityPolicy`): el
  scope fino es 015, pero cualquier dedupe que 013 toque debe colapsar antes de crear índices únicos.

---

## Requirements *(mandatory)*

### Functional Requirements

**Entidad Tenant y default backfill**

- **FR-001**: El sistema DEBE definir la entidad `Tenant` (tabla `tenants`) como raíz de la jerarquía, con:
  `id UUID PK`, `name`, `slug UNIQUE NOT NULL`, `is_active BOOLEAN DEFAULT TRUE`,
  `deployment_mode CHECK IN ('on_premise','cloud') DEFAULT 'on_premise'`, defaults de cascada
  (`default_legal_basis`, `default_risk_level`, `default_compliance_project_id` FK NULLable,
  `default_security_policy_id` FK NULLable), espejo de compresión (`compression_mode`,
  `compression_strategy`, `compression_threshold_tokens`, `compression_aggressiveness`,
  `compression_cache_enabled`), `created_at`, `updated_at`.
- **FR-002**: El sistema DEBE sembrar un **default tenant** con UUID fijo
  `00000000-0000-0000-0000-000000000001`, `slug='default'`, `deployment_mode='on_premise'`, de forma
  idempotente (`ON CONFLICT (id) DO NOTHING`). Este es el pivote que mantiene vivo el on-prem single-tenant.
- **FR-003**: El `slug` DEBE ser único y soportar el patrón config+seed nunca-fork (p.ej. `'elea'`, `'camara'`)
  para despliegues por cliente (Constitución VII).

**`tenant_id` en las 8 entidades + backfill**

- **FR-004**: El sistema DEBE añadir `tenant_id UUID FK→tenants.id NOT NULL` (tras backfill) a las 8 entidades:
  `users`, `groups`, `api_keys`, `budgets`, `audit_logs`, `security_policies`, `guardians`,
  `compliance_projects`, con índice `ix_<tabla>_tenant_id`.
- **FR-005**: El backfill de `tenant_id` DEBE preferir **relación** donde exista identidad
  (`audit_logs`/`consent_records` desde `user_id → users.tenant_id`; `api_keys`/`budgets` desde `user_id`/
  `group_id`) y **fallback al default tenant** para filas sin relación; ninguna fila puede quedar NULL antes
  del `SET NOT NULL`.
- **FR-006**: `api_keys.key_hash` DEBE permanecer **UNIQUE global** (material secreto); NO se scopea por tenant.
- **FR-007** *(forward-looking, decidir alcance)*: Las tablas de compliance por-tenant no listadas en las 8
  (`consent_records`, `dpa_registry`, `data_subject_requests`, `human_reviews`, `retention_policies`) DEBERÍAN
  recibir `tenant_id` para completitud de RLS; sin él serían fugas de aislamiento cross-tenant. Marcado como
  candidato de alcance de 013 (ver Assumptions / Complexity).

**Reconciliación de roles**

- **FR-008**: El sistema DEBE añadir `users.display_label VARCHAR NULL` para absorber los labels sectoriales
  (`clinician`/`developer`) como etiqueta de display configurable (Constitución III, [D9]).
- **FR-009**: El sistema DEBE hacer backfill de roles legacy **antes** de aplicar el CHECK: `admin → tenant_admin`;
  `clinician → role='client'` + `display_label='clinician'`; `developer → role='client'` +
  `display_label='developer'`.
- **FR-010**: El sistema DEBE aplicar `CHECK (role IN ('super_admin','tenant_admin','compliance_officer','client'))`
  sobre `users.role` (via `DROP CONSTRAINT IF EXISTS` + `ADD CONSTRAINT`, no `ALTER TYPE`).
- **FR-011**: El `super_admin` (cross-tenant, Basa/cloud) NO DEBE autogenerarse por migración; se siembra
  explícitamente aparte (solo cloud) para no exponer un rol cross-tenant en on-prem.

**Client model & Connection**

- **FR-012**: El sistema DEBE modelar el **client** como `User role='client'` + `client_type VARCHAR NULL`
  `CHECK IN ('base_url','desktop','chat_ui')`, con CHECK `(client_type IS NULL OR role='client')`.
- **FR-013**: El sistema DEBE extender `api_keys` (= **Connection**, misma tabla, NO tabla nueva) con:
  `tool_type NOT NULL CHECK IN ('claude-code','copilot','cursor','claude-desktop','chatgpt','chat-ui')`
  (backfill de keys demo a `'claude-code'`), `upstream_mode NOT NULL DEFAULT 'byok'
  CHECK IN ('subscription-passthrough','byok')`, `oauth_credential_ref NULL` (referencia a secreto Fernet,
  solo para `subscription-passthrough`), y toggles por-key NULLable (`redact_enabled`, `compression_mode`,
  `allowed_models`, `allowed_tools`).
- **FR-014**: Los toggles por-key DEBEN tener semántica **NULL = heredar** del group/tenant y valor = override;
  NUNCA confundir "no seteado" con "apagado".
- **FR-015**: `oauth_credential_ref` DEBE ser una **referencia** a un secreto Fernet/gestor de secretos, NUNCA
  el token OAuth en claro (SC-5).
- **FR-016**: La gobernanza legal (`compliance_project_id`/`legal_basis`) DEBE vivir a nivel **persona** (`User`)
  y NO duplicarse en la Connection (se reutiliza el del User).

**Unicidad compuesta**

- **FR-017**: El sistema DEBE cambiar la unicidad global de `users.username`, `users.email` y `groups.name` a
  UNIQUE **compuesta** `(tenant_id, x)`, permitiendo que dos tenants tengan el mismo username/email/grupo.
- **FR-018**: El sistema DEBE aplicar UNIQUE `(tenant_id, user_id, tool_type)` sobre `api_keys` (≤1 Connection
  por herramienta por client).

**RLS**

- **FR-019**: Por cada tabla tenant-scoped el sistema DEBE `ENABLE ROW LEVEL SECURITY` **y `FORCE ROW LEVEL
  SECURITY`** (crítico: la app se conecta como `basa_admin`, dueño de las tablas, que bypasearía RLS sin FORCE).
- **FR-020**: Por cada tabla tenant-scoped el sistema DEBE crear una policy `tenant_isolation` con
  `USING (tenant_id = NULLIF(current_setting('app.current_tenant', true),'')::uuid
   OR current_setting('app.bypass_rls', true) = 'on')` y el mismo predicado en `WITH CHECK`
  (via `DROP POLICY IF EXISTS` antes de `CREATE POLICY`).
- **FR-021**: El bypass `app.bypass_rls='on'` DEBE permitir a super_admin ver/operar cross-tenant; sin él, la
  sesión queda aislada al `app.current_tenant`.

**Resolución de contexto (esquema, no resolver)**

- **FR-022**: 013 DEBE implementar y testear la **cascada de defaults de contexto** —`legal_basis`,
  `risk_level`, `compliance_project_id`— con precedencia `Client(User) > Group > Tenant`, en un servicio de
  resolución que reutiliza el patrón override ya existente (`User.legal_basis` > `Group.default_legal_basis`)
  elevando `Tenant` como raíz. El esquema provee los slots por capa (defaults en `Tenant`, `Group.default_*`
  existentes, override en `User`). La cascada de **`SecurityPolicy` / `entity_configs`** por capa NO es 013:
  es **spec 015** (013 solo añade `SecurityPolicy.tenant_id` como primer paso).

**Migración & runtime**

- **FR-023**: La migración Alembic (`010_multitenant_foundation`, `down_revision='009'`) DEBE ser **idempotente**
  (`IF NOT EXISTS` / `ON CONFLICT DO NOTHING` / `DROP … IF EXISTS`) y **reversible** (`downgrade()` revierte
  políticas, RLS, constraints, columnas y la tabla `tenants`).
- **FR-024** *(runtime, especificado-pero-NO-activado en 013)*: Para que la RLS aplique en runtime,
  `src/database.py::get_db` DEBE setear `SET LOCAL app.current_tenant='<uuid>'` por request desde la identidad
  resuelta; NUNCA un default silencioso (SC-3, fail-closed). 013 **especifica** este cambio pero **no lo activa**:
  la **fuente de identidad fail-closed** (cierre del fallback admin + SSO) llega en **spec 017**. Regla de
  activación: **activar RLS (FORCE) solo tras cablear el GUC** con esa identidad, **o** con **políticas
  permisivas coordinadas** durante la ventana de deploy — nunca forzar RLS en runtime antes, para no dejar la app
  devolviendo 0 filas.

**Onboarding-as-data**

- **FR-025**: El sistema DEBE proveer `seed_client(tenant, client_spec)` idempotente que lee config (YAML) y crea
  `User(role=client)+client_type` + N Connections + `Budget(user)` en una sola operación tenant-scoped, sin tocar
  código para sumar un cliente o demo (Constitución IV). **Nota de artefacto**: `seed_gateway_demo` **no existe
  en este repo** (es código del fork externo *gatelite* a **portar**); la lógica real de creación de keys/clients
  aquí es `backend/src/api/keys.py`, que `seed_client` DEBE **reutilizar** en vez de reimplementar.

### Key Entities *(include if feature involves data)*

- **Tenant** *(nuevo, a construir)*: empresa compradora; raíz de la jerarquía. Defaults de cascada
  (legal basis, risk level, compliance project, security policy, compresión) + `slug` para config+seed.
  Default tenant de UUID fijo `…0001` para backfill on-prem.
- **User** *(modificar)*: persona sujeto de la gobernanza. `+tenant_id`, `+display_label`, `+client_type`;
  `role` gana CHECK enum; unicidad `(tenant_id, username)`/`(tenant_id, email)`. El **client** es
  `User role='client'`.
- **Group** *(modificar)*: capa media de la cascada. `+tenant_id`; `name` a UNIQUE `(tenant_id, name)`.
- **APIKey (= Connection)** *(modificar, reuse over reinvent)*: virtual key por herramienta identificada por
  `key_hash`. `+tenant_id`, `+tool_type`, `+upstream_mode`, `+oauth_credential_ref`, toggles por-key; UNIQUE
  `(tenant_id, user_id, tool_type)`; `key_hash` sigue global. "Connection" es naming público/UI (white-label).
- **Budget** *(modificar)*: gate 402 persona→grupo. `+tenant_id`; sin cambios de enforcement.
- **AuditLog** *(modificar)*: metadata-only. `+tenant_id` (denormalizado, backfill desde `user_id`), índice
  `(tenant_id, timestamp)` para dashboard; `user_group_id` ya denormalizado.
- **SecurityPolicy** *(modificar)*: `+tenant_id` como **primer paso** hacia des-singletonizar `entity_configs`
  (el scope fino por grupo/cliente es 015).
- **Guardian** *(modificar)*: `+tenant_id`; sin otros cambios.
- **ComplianceProject** *(modificar)*: `+tenant_id`; ojo FK circular suave con `Tenant.default_compliance_project_id`.
- **Connection (tabla nueva independiente)** *(DESCARTADA)*: no se crea `connections`; violaría reuse-over-reinvent
  y rompería `audit_logs.api_key_id` + migraciones 003–012. Documentado para trazabilidad.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Tras `alembic upgrade head` sobre una DB single-tenant poblada, **100%** de las filas de las 8
  tablas tienen `tenant_id = …0001` y `NOT NULL`; `tenants` tiene exactamente **1** fila; correr `upgrade`
  dos veces no falla ni duplica (idempotencia verificada).
- **SC-002**: **0** queries de la app rompen tras la migración en modo single-tenant (regresión cero para on-prem).
- **SC-003** *(SC-4 constitucional)*: con `app.current_tenant=<A>`, **0** filas de otro tenant aparecen en un
  `SELECT` sobre cualquier tabla tenant-scoped, y **0** `INSERT` con `tenant_id` ajeno pasan el `WITH CHECK`.
- **SC-004**: conectado como el usuario dueño de las tablas (`basa_admin`), la RLS **sigue aislando** (prueba
  explícita de que sin `FORCE` fallaría) — el aislamiento no es un falso positivo.
- **SC-005**: el CHECK de `role` **rechaza el 100%** de valores fuera del enum y **acepta** los 4 válidos; el
  mapeo de backfill (`admin→tenant_admin`, `clinician`/`developer→client`+label) se cumple en **100%** de filas
  legacy.
- **SC-006**: dos tenants pueden tener el **mismo** `username`/`email`/`group.name` sin conflicto; dentro de un
  mismo tenant siguen siendo únicos; `api_keys.key_hash` sigue global.
- **SC-007**: la cascada de **defaults de contexto** (`legal_basis`/`risk_level`/`compliance_project_id`) da el
  valor efectivo correcto en los 3 casos (hereda de tenant, hereda de group, override de user) — verificado por
  test en 013. (La cascada de `SecurityPolicy`/`entity_configs` es 015, fuera de este SC.)
- **SC-008**: `seed_client(tenant, spec)` es idempotente: re-ejecutar con el mismo spec produce **0** filas
  duplicadas; sumar un client/demo requiere **0** líneas de código.
- **SC-009**: `alembic downgrade -1` deja la DB en estado consistente (sin columnas/políticas/constraints
  huérfanas) en entornos de test.

## Assumptions

- **Reuse over reinvent (Constitución, Workflow 2)**: "Connection" **extiende** `api_keys`, no crea tabla nueva;
  renombrar `api_keys→connections` rompería `audit_logs.api_key_id` y migraciones 003–012 sin beneficio.
- **CHECK constraint sobre `role`, no ENUM nativo**: más fácil de ampliar idempotentemente (`DROP/ADD CONSTRAINT`)
  sin `ALTER TYPE`, coherente con el estilo `op.execute` idempotente de las migraciones 001–009.
- **`admin → tenant_admin` (no super_admin)**: en on-prem el admin gestiona SOLO su instalación (=su tenant);
  `super_admin` cross-tenant se siembra explícitamente aparte, solo cloud.
- **RLS con GUC de sesión** (`app.current_tenant` + `app.bypass_rls`) en vez de roles Postgres por tenant: un
  solo rol de conexión, tenant inyectado por `SET LOCAL` en el request; `FORCE ROW LEVEL SECURITY` es
  **obligatorio** porque la app es dueña de las tablas.
- **UUID fijo del default tenant** (`…0001`): permite que seeds, backfill y tests referencien el pivote de forma
  determinista y que re-ejecutar la migración sea idempotente.
- **`get_db` inyecta el GUC** (o se crea un rol de app NOSUPERUSER separado) como cambio de **runtime coordinado**
  con el deploy; fuera de la migración pura de esquema. Sin este cableado + FORCE RLS, la app devolvería 0 filas.
- **`client_type` (base_url/desktop/chat_ui)** es forward-looking del onboarding; el `client_type` describe CÓMO
  consume la persona, distinto de `tool_type` (la herramienta concreta) que vive en la Connection.
- **Reasignación de permisos de `developer`**: degradar `developer→client` cambia permisos efectivos
  (pierde `create_key`/`revoke_key`/model-mgmt en `rbac.py`); ese refactor de `src/auth/rbac.py` + sus tests es
  **forward-looking** (coordinado con 017), no parte del esquema de esta spec — se asume comunicado antes de prod.
- **Alcance de tablas de compliance no listadas** (`consent_records`, `dpa_registry`, `data_subject_requests`,
  `human_reviews`, `retention_policies`): se asume **recomendado incluirlas** en 013 para no dejar fugas de RLS;
  decisión de alcance enmendable de una línea (ver FR-007 y Complexity en plan.md).
- **Postgres** es la DB de destino (RLS es específico de Postgres); on-prem y cloud comparten el motor.
- **Dependencia**: la 013 **no depende** de otras specs; 014/015/017 **dependen** de ella (bedrock).
