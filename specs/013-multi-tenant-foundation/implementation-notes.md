# Spec 013 — Notas de implementación

**Fecha**: 2026-07-10 · **Estado**: Implementada y verificada (suite 69 passed / 3 skips live
en Docker Compose contra Postgres 16; boot end-to-end con migración 001→010 + smoke de login
y endpoints gateados).

## Qué se entregó

- Migración [`010_multitenant_foundation.py`](../../backend/alembic/versions/010_multitenant_foundation.py):
  `tenants` + default tenant `…0001`, `tenant_id` NOT NULL + FK + índices en **13 tablas**,
  reconciliación de roles con CHECK, client model (`client_type` + Connection sobre `api_keys`),
  unicidad compuesta por tenant, RLS `ENABLE`+`FORCE` con policies. Idempotente (testeado
  re-ejecutando el **cuerpo** vía `stamp 009` → `upgrade head`) y reversible (roundtrip testeado).
- Modelos ORM sincronizados + [`Tenant`](../../backend/src/models/tenant.py) nuevo.
- Runtime GUC: ContextVars + listener `after_begin` en [`database.py`](../../backend/src/database.py)
  que inyecta `set_config('app.current_tenant', …, true)` **por transacción** (sobrevive commits
  intermedios). **Mecanismo listo pero no activado** (FR-024): lo cablea la identidad de 017/014.
- Cascada de defaults de contexto (US4) en [`context_resolution.py`](../../backend/src/services/context_resolution.py)
  + resolución de toggles por-key NULL=heredar.
- Onboarding-as-data (US6): [`onboarding.py`](../../backend/src/services/onboarding.py)
  (`seed_client` idempotente) + [`clients.example.yaml`](../../backend/config/clients.example.yaml).
- Tests nuevos: `test_migration_010`, `test_role_reconciliation`, `test_rls_isolation`,
  `test_client_model`, `test_context_resolution`, `test_seed_client`, `test_rbac_compat`
  (+ harness `migration_harness.py` con DBs descartables y rol NOSUPERUSER dueño).

## Decisiones tomadas (defaults revisables del §10 del handoff)

1. **FR-007 — 5 tablas de compliance INCLUIDAS** (`consent_records`, `dpa_registry`,
   `data_subject_requests`, `human_reviews`, `retention_policies`): reciben `tenant_id`+RLS
   como recomendaba el plan (sin ellas habría fugas cross-tenant, SC-4).
   `retention_policies.log_type` sigue UNIQUE global (pasarlo a `(tenant_id, log_type)` es 018).
2. **Ventana de deploy RLS (T041)**: además de la policy estricta `tenant_isolation` (FR-020)
   se crea **`tenant_isolation_bootstrap`**: permite la fila cuando el GUC no está seteado
   (las policies permisivas se OR-ean). Resultado: on-prem sigue funcionando sin GUC (cero
   regresión) y en cuanto una sesión setea el GUC el aislamiento es efectivo.
   **La 017 DEBE dropear la policy bootstrap** al cablear la identidad fail-closed por request.
3. **⚠️ Trampa superuser (T002)**: `sentinel_admin` del docker-compose es **SUPERUSER** de Postgres
   y los superusers bypasean RLS *siempre, incluso con FORCE*. FORCE cubre al *dueño* no-superuser.
   Los tests lo prueban con un rol NOSUPERUSER dueño (`rls_owner`) y documentan la trampa con un
   test explícito. **Acción pendiente (017)**: la app debe conectarse con un rol NOSUPERUSER en prod.
4. **Defaults Python-side** `tenant_id = DEFAULT_TENANT_ID` (y `tool_type='claude-code'`) en los
   modelos: los code paths heredados que no setean tenant siguen funcionando en on-prem; en cloud
   la identidad setea el valor explícito y el `WITH CHECK` de RLS rechaza cruces. No hay default
   server-side en DB (evita asignaciones silenciosas fuera del ORM).
5. **Shim RBAC transicional** ([`rbac.py`](../../backend/src/auth/rbac.py) `effective_roles`):
   los gates de la API siguen escritos con nombres legacy (`admin`, `developer`…); el shim expande
   `tenant_admin`/`super_admin`→`admin` y `client`+`display_label`∈{clinician,developer}→label,
   para que los usuarios migrados conserven exactamente sus permisos (SC-002). La matriz definitiva
   por tenant es 017. Los bordes de creación aceptan roles legacy vía `normalize_legacy_role`.
6. **Bootstrap admin** (`users.py` login / `chat.py` fallback) crea ahora `role='tenant_admin'`
   (canónico); el **fallback a admin sin key sigue existiendo** y se cierra en 017 (SC-3),
   como manda la spec. Fix colateral heredado: el email de bootstrap `admin@sentinel.local` rompía
   el `EmailStr` del response (`.local` es TLD reservado) → `admin@sentinel.com.ar`.
7. **Coexistencia con gatelite (infra)**: containers renombrados `sentinel-*` y puertos host
   desplazados (db 5433, motor 4010, backend 8091, frontend 8090) para no pisar el demo del
   lunes que corre en paralelo; `REDIS_HOST` ahora usa el nombre de servicio compose (`redis`).
8. **`seed_client` no registra la key en el motor**: el seeding funciona offline; la
   sincronización con el motor queda en el flujo online (`/keys`) o en la 014.

## Review adversarial (workflow multi-agente, 2026-07-10)

31 hallazgos reportados por 5 dimensiones de review → verificación adversarial → **19
confirmados, 12 refutados**. Todos los confirmados aplicados; los estructurales:

- **[crítico] Migración explotaba con N keys legacy por user** (repro en vivo): todas
  backfillean a `'claude-code'` y el UNIQUE colisionaba. Fix: **dedupe** (queda activa
  la más reciente por `(tenant,user,tool)`; las demás `is_active=FALSE` — solo
  bookkeeping local, el motor no se toca) + **índice único PARCIAL** `WHERE is_active`
  (coincide con el "≤1 Connection **activa**" de la spec; re-emitir tras revocar es válido).
- **[major] El downgrade no revertía los roles** y dropeaba `display_label` (la única
  fuente): rollback dejaba lockout admin con el código pre-013. Fix: reversión
  determinista (`tenant_admin→admin`, `client→display_label`) antes del DROP.
- **[major] La tabla `tenants` no tenía RLS**: una sesión scopeada veía nombres/slugs
  de todos los tenants. Fix: ENABLE+FORCE+policies sobre `tenants` (scope por `id`).
- **[major] `PUT /users/{id}` y `POST /keys` no hablaban el esquema nuevo**: update
  con rol legacy → 500 por CHECK; keys sin `tool_type` → segunda key = 500 por índice.
  Fix: normalización también en update; `tool_type` en el schema de creación de keys +
  pre-check **409** legible (la restricción ≤1 activa/tool es semántica de la spec).
- **[major] Frontend**: gates de `auth.ts` con vocabulario legacy → shim espejo
  (`toLegacyRole`) aplicado al guardar la sesión; login devuelve `display_label`.
- **[major] SC-002 sin cobertura automatizada** → `test_app_regression_smoke.py`:
  app FastAPI real (TestClient) sobre la DB migrada: login bootstrap, gates del shim,
  creación/update con roles legacy, listado de keys.
- Menores aplicados: tests de predicado real de policies (no solo nombres), bypass vía
  ContextVar testeado, test de key_hash autosuficiente, unicidad email/group.name
  cross-tenant testeada, helper compartido `key_material` (FR-025 reuse), FKs de
  `Tenant.default_*` con `use_alter` + mismos nombres que la 010, `include_object` en
  `env.py` (LiteLLM comparte la DB — autogenerate no debe tocar sus tablas), ORM
  `Index(unique=True)` alineado 1:1 con la migración.
- Bug heredado adicional: `EmailStr` rechaza TLDs reservados (`.local`, `.test`) → el
  bootstrap `admin@sentinel.local` rompía el listado de usuarios; corregido.
- Refutados (decisiones ratificadas): policy bootstrap permisiva (ventana FR-024),
  defaults Python-side, `retention_policies.log_type` global (018), GUC `bypass_rls`
  como diseño de la spec (el hardening de roles DB es 017), residuos del harness en
  cluster de dev (aceptado), login global por username (017).

## Riesgos abiertos / forward-looking (sin cambios vs plan)

- Activación real de RLS en runtime = GUC cableado por identidad + rol NOSUPERUSER + drop de la
  policy bootstrap → **spec 017** (y 014 para la identidad por virtual key del firewall).
- Login multi-tenant (resolver tenant por slug/SSO antes del lookup de username) → 017.
- Refactor fino de permisos `developer→client` y matriz por tenant → 017.
- Cascada de `SecurityPolicy`/`entity_configs` por capa → 015.
