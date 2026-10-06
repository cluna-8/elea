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

- **No existe un camino que cree al primer `super_admin`**: `backend/src/models/user.py:97-98`
  («NO se autogenera… se siembra aparte, solo cloud») y ningún script/instalador lo hace.
  Con este cambio, en una instalación single-tenant sin un `super_admin` sembrado **nadie puede
  dar de alta un Auditor** por API ni por panel (hasta ahora lo hacía el `tenant_admin`). Es
  lo que pidió el fix, pero Sentinel debería decidir si agrega un alta guiada del primer
  `super_admin` (comando del operador o variable de bootstrap) antes de publicar el cambio.
- **Herramientas que dan de alta auditores con la sesión admin**: el sembrador del arnés
  (`harness/src/sentinel_harness/seeder/seed.py:292`, poblaciones `gate-*.yaml` con
  `roles.compliance_officer`) llama `POST /users` con la sesión del admin de bootstrap: pasará a
  recibir 403 para esos usuarios. Pendiente decidir si el arnés usa una sesión `super_admin`.
- **Quedan fuera de este fix** (mismo patrón, otra superficie; sin tocar): (a) un `tenant_admin`
  puede resetear la contraseña de un `super_admin`/`compliance_officer` existente
  (`POST /users/{id}/password`, `backend/src/api/users.py:746`) y así tomar la cuenta;
  (b) puede cambiarles el rol a uno que no está protegido (degradarlos) o desactivarlos;
  (c) el alta JIT por SSO asigna roles por su propio camino (`tests/integration/test_sso_jit.py`).
  Si la intención es que el `tenant_admin` no controle a quien cumple, vale cerrarlos.
- `docs/docs/install-deploy/index.md` paso 7 decía que `compliance_officer` prueba que hubo un
  dueño; el código (`ROLES_QUE_PRUEBAN_DUENO`, `users.py:43`) no lo cuenta desde 017/US1. Se
  corrigió la frase.

## 6. Cómo verificar después de portar

```bash
cd backend
python -m pytest tests/unit/test_roles_cumplimiento_solo_super_admin.py tests/test_rbac_compat.py -q
# con Postgres (CI):
python -m pytest tests/integration/test_alta_roles_cumplimiento.py tests/integration/test_auth_events.py \
  tests/integration/test_rol_auditor.py tests/integration/test_seat_gate_users.py \
  tests/integration/test_users_lifecycle_043.py tests/contract/test_auth_credenciales.py -q
cd ../frontend && npm test && npx tsc --noEmit
```
