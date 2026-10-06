# Handoff — alta y cambio de rol a roles de cumplimiento, sólo `super_admin` (Elea → Sentinel)

**Fecha**: 06-oct-2026. **Origen**: `cluna-8/elea`, rama `cluna-8/fix-alta-roles-cumplimiento`.
**Destino**: `cluna-8/sentinel` (base Guardian). **Evidencia del hallazgo**:
`specs/057-porte-sentinel-068-redireccion-modelos/qa-plan-v2.md` §N3 (rama
`origin/057-porte-sentinel-068-redireccion-modelos`).

Es código de base y genérico (ningún string de Elea/Eleia): la propiedad que se cierra es
previa y Sentinel la tiene igual, porque el endpoint y el modelo vienen de la base.

## 1. El defecto

`POST /users` exigía sólo `require_role("admin")` y `effective_roles` expande `tenant_admin` y
`super_admin` a `admin` (`backend/src/auth/rbac.py:23-36`). El administrador de empresa podía
entonces crear (o promover a) un `compliance_officer` —quien define el piso de residencia y la
ficha de modelos— o un `super_admin`: «el administrador no puede relajar» se cumplía por el rol
y no por la intención. Mismo hueco en `PUT`/`PATCH /users/{id}` (cambio de rol).

## 2. Qué se hizo

| Pieza | Dónde |
|---|---|
| Constante `ROLES_SOLO_SUPER_ADMIN = {compliance_officer, super_admin}` | `backend/src/models/user.py:15` |
| Guarda `exigir_super_admin_para_rol(actor, rol_nuevo)` → 403 con mensaje claro | `backend/src/auth/rbac.py:37-48` |
| Alta: `create_user` inyecta el actor (forma-2 de `require_role`) y lo pasa a `_validar_alta` | `backend/src/api/users.py:419`, `:312`, `:343` |
| Cambio de rol `PUT` / `PATCH` | `backend/src/api/users.py:550`, `:626` |
| Panel: la sesión guarda el rol canónico (`canonical_role`) y `canAssignComplianceRoles` | `frontend/src/services/auth.ts:16,38,48` |
| Panel: «Auditor» oculto en alta y edición salvo para `super_admin` | `frontend/src/pages/UsersPage.tsx:164,1658,1882` |
| Doc de roles | `docs/docs/administration/index.md` (sección «Quién asigna los roles de cumplimiento»), `docs/docs/install-deploy/index.md` (paso 7) |

Decisiones de diseño (las dejó cerradas el pedido; se anotan por si Sentinel las discute):

- La guarda mira `actor.role` real, **no** `effective_roles` (que no distingue `tenant_admin`
  de `super_admin`).
- Sólo se bloquea cuando el rol **cambia**: `PUT` re-manda el rol vigente (`UserBase.role` es
  requerido), y un `tenant_admin` sigue pudiendo editar el email o `is_active` de quien ya es
  auditor. «No se tocan datos».
- El 403 va después del 422 de rol inválido (`_validar_alta` documenta esa precedencia) y
  antes del gate de licencia y del bcrypt: un alta rechazada no gasta executor ni motor.
- El alta del primer admin (bootstrap, `login` → `_bootstrap_admin_si_sin_dueno`) **no pasa
  por este camino** y queda igual.
- Sin migración, sin cambio de contrato OpenAPI (`openapi.json` regenerado en local = el
  versionado) ni de `.env.example`.

## 3. Qué portar tal cual

1. Los tres archivos de backend de la tabla (el diff es chico y no toca nada de Elea).
2. `frontend/src/services/auth.ts` y los tres puntos de `UsersPage.tsx`, **si** Sentinel usa
   el mismo `authStorage.save` (colapsa `tenant_admin`/`super_admin` a `admin`: sin el rol
   canónico guardado el panel no puede distinguirlos). Confirmar que `UsersPage.tsx` no divergió.
3. Los tests: `backend/tests/unit/test_roles_cumplimiento_solo_super_admin.py` (puro, sin
   Postgres), `backend/tests/integration/test_alta_roles_cumplimiento.py` (Postgres),
   `frontend/tests/contract/UsersPage.roles-cumplimiento.test.tsx`,
   `frontend/tests/unit/auth.canonical-role.test.ts`.

## 4. Tests existentes que hubo que ajustar (el mismo ajuste va en Sentinel)

Creaban o ascendían a `compliance_officer` con la sesión del `tenant_admin` del bootstrap, que
ahora recibe 403. Pasaron a una sesión `super_admin` (`headers_for_role(..., Rol.SUPER_ADMIN)`):
`tests/integration/test_auth_events.py`, `test_rol_auditor.py`, `test_seat_gate_users.py`,
`test_users_lifecycle_043.py`; y `tests/contract/test_auth_credenciales.py` (`_payload` pasó de
`compliance_officer` a `lectura`: sigue siendo un rol sin seat). En `test_users_lifecycle_043.py`
la sesión es **de función**, no de módulo, porque los tests de «último admin» dan de baja a
todos los admins menos uno y dejarían inactivo (401) a un super_admin compartido.

## 5. Qué verificar antes de portar / consecuencias a conocer

- **El primer `super_admin` ahora lo provee un comando** (ver §6). Antes de este cambio no
  existía camino alguno (`backend/src/models/user.py:97-98`: «se siembra aparte, solo cloud»),
  y con la guarda una instalación single-tenant sin `super_admin` no podía dar de alta un
  Auditor. El comando es genérico: en cloud, donde el `super_admin` se siembra aparte, no
  hace falta correrlo (si ya hay uno, no hace nada).
- **Herramientas que dan de alta auditores con la sesión admin**: el sembrador del arnés
  (`harness/src/sentinel_harness/seeder/seed.py`, poblaciones `gate-*.yaml` con
  `roles.compliance_officer`) pasó a usar una sesión `super_admin` (§6). Cualquier otro
  script o instalador que haga `POST /users` con `role=compliance_officer` desde la sesión del
  admin de bootstrap recibirá 403: revisarlos al portar.
- **Quedan fuera de este fix** (mismo patrón, otra superficie; sin tocar): (a) un `tenant_admin`
  puede resetear la contraseña de un `super_admin`/`compliance_officer` existente
  (`POST /users/{id}/password`, `backend/src/api/users.py:746`) y así tomar la cuenta;
  (b) puede cambiarles el rol a uno que no está protegido (degradarlos) o desactivarlos;
  (c) el alta JIT por SSO asigna roles por su propio camino (`tests/integration/test_sso_jit.py`).
  Si la intención es que el `tenant_admin` no controle a quien cumple, vale cerrarlos.
- `docs/docs/install-deploy/index.md` paso 7 decía que `compliance_officer` prueba que hubo un
  dueño; el código (`ROLES_QUE_PRUEBAN_DUENO`, `users.py:43`) no lo cuenta desde 017/US1. Se
  corrigió la frase.

## 6. Primer `super_admin`: comando del operador (Elea → Sentinel)

`python -m src.cli crear-super-admin --usuario <u> --email <e>`, dentro del contenedor del
backend. Código de base, genérico (ningún string de Elea/Eleia).

| Pieza | Dónde |
|---|---|
| Comando + `crear_super_admin(db, usuario, email)` (idempotente) | `backend/src/cli.py` (archivo nuevo) |
| Evento `AUTH_BOOTSTRAP_SUPER_ADMIN = "auth_bootstrap_super_admin"` | `backend/src/services/auth_events.py:21` |
| Comentario del modelo (`super_admin` ya no es «se siembra aparte, solo cloud») | `backend/src/models/user.py:97-98` |
| Doc: «Cómo se provee el primer super admin» | `docs/docs/administration/index.md` (`#primer-super-admin`), `docs/docs/install-deploy/index.md` (paso 7) |
| Sembrador del arnés con sesión `super_admin` | `harness/src/sentinel_harness/seeder/{client,seed,population}.py`, `RUNBOOK-examen.md` §5 |

Comportamiento (decidido acá; Sentinel puede discutirlo):

- **Idempotente**: si ya existe un `super_admin` (de cualquier cuenta), sale `0` sin crear nada y
  lo avisa por stderr; usuario/email ocupados → rechaza (salida `1`) sin promover a nadie;
  email que no cumple `EmailStr` → rechaza (el response de `GET /users` lo exige).
- **Contraseña**: `secrets.token_urlsafe(24)` (192 bits, 32 caracteres, entra en los 72 bytes de
  bcrypt), impresa **una sola vez** por stdout; stderr y logs no la llevan; en la base queda el
  hash bcrypt. `must_change_password=True` (spec 055).
- **Auditoría**: una fila `model='auth'` (`emit_auth_event`, metadata-only: id del target y
  `new_role`) en la **misma transacción** que el insert. Evento propio y no `auth_bootstrap_admin`
  para no confundirlos al auditar. Tenant: `DEFAULT_TENANT_ID` (una instancia por cliente).
- **«Sólo si se lo invoca»**: ni el arranque, ni migraciones, ni endpoints lo llaman (lo
  verifica un test).
- **Carrera**: dos invocaciones simultáneas con usernames distintos podrían crear dos
  `super_admin` (el chequeo «no hay ninguno» no es atómico); con el mismo username/email gana la
  restricción UNIQUE y la otra se rechaza. Es un comando de operador, no un endpoint; si Sentinel
  quiere cerrarlo, un `pg_advisory_xact_lock` al inicio de `crear_super_admin` alcanza.
- **Orden respecto del bootstrap de `admin`**: `ROLES_QUE_PRUEBAN_DUENO` incluye `super_admin`
  (`api/users.py:43`), así que crearlo **antes** del primer login de `admin` impide que ese login
  cree el `tenant_admin`; el `super_admin` lo da de alta por `POST /users`. Documentado.

**Arnés** (`harness/`): el seeder toma `SEED_SUPER_ADMIN_USERNAME`/`SEED_SUPER_ADMIN_PASSWORD` del
**entorno** (no argv: quedaría en `ps`/historial). Los `compliance_officer` se crean con esa
sesión (`SeedClient.create_user(..., como_super_admin=True)`, `BackendClient.login_super_admin`);
el resto de los roles, con la del admin. Sin las variables, `seed` aborta **antes de crear
nada** (`--verify-only` no las necesita). Si el `super_admin` ya existía y `admin` no, el
seeder crea `admin` con esa sesión. Sentinel conserva el arnés propio: portar el enfoque.

Tests: `backend/tests/unit/test_cli_crear_super_admin.py` (puro, sin Postgres),
`backend/tests/integration/test_cli_crear_super_admin.py` (Postgres; **no se pudo correr en la
máquina de desarrollo, sin Docker/Postgres**: correrlo en CI antes de dar por bueno el porte),
`harness/tests/unit/test_seeder.py`.

## 7. Cómo verificar después de portar

```bash
cd backend
python -m pytest tests/unit/test_roles_cumplimiento_solo_super_admin.py \
  tests/unit/test_cli_crear_super_admin.py tests/test_rbac_compat.py -q
# con Postgres (CI):
python -m pytest tests/integration/test_alta_roles_cumplimiento.py \
  tests/integration/test_cli_crear_super_admin.py tests/integration/test_auth_events.py \
  tests/integration/test_rol_auditor.py tests/integration/test_seat_gate_users.py \
  tests/integration/test_users_lifecycle_043.py tests/contract/test_auth_credenciales.py -q
cd ../frontend && npm test && npx tsc --noEmit
```
