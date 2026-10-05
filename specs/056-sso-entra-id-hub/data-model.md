# Data Model — Spec 056

**Sin cambios de esquema ni migraciones.** Las entidades persistentes ya existen (spec 017):
`sso_providers` (`017_sso_providers.py`, modelo `backend/src/models/sso_provider.py`) y `users`
(`backend/src/models/user.py`). Esta spec agrega **estado en memoria del Hub** y **campos en
respuestas** existentes. Todo lo de abajo es base de [contracts/](contracts/).

## Entidades existentes que se usan (sin cambios)

| Entidad | Campos relevantes | Reglas que no cambian |
|---|---|---|
| **Proveedor SSO del tenant** (`sso_providers`) | `tenant_id`, `provider_type` (`entra`), `config` (`tenant_id`, `client_id` del directorio; en claro), `client_secret_encrypted` (Fernet), `enabled` | Uno por tenant. El secreto entra y no sale (`backend/src/sso/admin_api.py:87-101`). No se puede habilitar sin secreto (`:175-180`). |
| **Usuario** (`users`) | `email` (clave de cruce, única por tenant), `role`, `is_active`, `password_hash`, `must_change_password` | JIT de la 017 intacto (FR-007, `backend/src/sso/jit.py`): nunca cambia rol, grupo ni tenant y nunca reactiva una baja. Los nacidos por SSO tienen `password_hash = "!sso-no-password"` (`jit.py:48`). |
| **Licencia** | `feature_flags` con `sso` | Sin `sso` → `/auth/sso/*` responde 403 (`api.py:66-79`). |

## Estado nuevo en memoria del Hub (`client/server.js`)

### Flujo SSO pendiente (`pendingSso: Map<sid, FlujoPendiente>`)

| Campo | Tipo | Origen | Regla |
|---|---|---|---|
| clave `sid` | string (48 hex) | cookie `elea_rag_sid` del navegador (`client/server.js:76`, `:88-97`) | Ata el flujo al navegador que lo inició (research D1, requisito 1). |
| `stateCookie` | string (JWT firmado por el backend) | valor de `sentinel_sso_state` en el `Set-Cookie` de `GET {backend}/auth/sso/login` | Se reenvía **tal cual** al callback del backend en la cabecera `Cookie`. El Hub no lo decodifica ni lo valida (no tiene el secreto: FR-003). Nunca se loguea. |
| `state` | string | parámetro `state` del `Location` que devolvió el backend | Se compara con el `state` del query del callback con `crypto.timingSafeEqual` antes de canjear (D1, requisito 2). |
| `venceEn` | número (epoch ms) | `Date.now() + 10 min` (mismo TTL que el JWT de estado, `backend/src/sso/api.py:59`) | Un pendiente vencido se trata como inexistente y se borra. |

**Transiciones**

```text
(sin pendiente) --GET /sso/login, backend 302--> PENDIENTE
PENDIENTE --GET /sso/callback (mismo sid)--> CONSUMIDO (se borra SIEMPRE, salga bien o mal)
PENDIENTE --vence (10 min) o barrido--> (se borra)
PENDIENTE --nuevo GET /sso/login del mismo sid--> PENDIENTE (reemplaza al anterior)
```

**Límites**: tope de 5 000 entradas (constante en `client/sso.js`). Al superarlo se barren primero los
vencidos y, si sigue lleno, el más viejo. Un reinicio del Hub vacía el `Map`: el callback no
encuentra pendiente y responde `sso_reintentar` (caso borde de la spec).

### Sesión del Hub (`sessions: Map<sid, Sesion>`, existente en `client/server.js:75`)

| Campo | Cambio |
|---|---|
| `token` | Sin cambio: el JWT de Guardian, solo del lado del servidor. En el camino SSO llega en el cuerpo de la respuesta del callback del backend (`backend/src/sso/api.py:324-336`). |
| `user` | Sin cambio de forma: `{id, username, role, display_label, email}` del callback. No trae `must_change_password` (research H11), así que el modal obligatorio no se abre (FR-008). |
| `auth_method` | **Nuevo**, `'password'` \| `'sso'`. Ausente en sesiones creadas por `POST /api/auth/login` (= `'password'`, sin cambiar ese camino: FR-005). `'sso'` solo lo pone `GET /sso/callback`. Lo expone `GET /api/user/current` como `user.auth_method`. |

**Rotación de `sid`** (research D1, requisito 4): al emitir una sesión SSO el Hub genera un `sid`
nuevo, guarda la sesión bajo ese `sid`, borra cualquier sesión del `sid` viejo y responde con
`Set-Cookie: elea_rag_sid=<nuevo>; HttpOnly; Path=/; SameSite=Lax` (mismos atributos que hoy,
`client/server.js:93`).

## Campos nuevos en respuestas existentes

| Respuesta | Campo | Tipo | Regla |
|---|---|---|---|
| `GET /api/v1/auth/sso/available` (backend, base) | `return_origin` | string \| null | Esquema + host + puerto de `SENTINEL_SSO_REDIRECT_URI` (p. ej. `https://eleia.ejemplo.local`), `null` si la variable falta o no es una URL absoluta. Sin ruta ni query. Ver [guardian-sso-api.md](contracts/guardian-sso-api.md). |
| `GET /api/auth/sso/available` (Hub, nuevo) | `{enabled, return_origin}` | bool, string \| null | Proxy fail-closed del de arriba. No expone `provider_type`. |
| `GET /api/user/current` (Hub) | `user.auth_method` | `'password'` \| `'sso'` | Ver Sesión del Hub. |

## Eventos de auditoría (canal existente, metadata-only)

| Evento | Cuándo | Campos | Cambio |
|---|---|---|---|
| `auth_sso_login` | Ingreso aceptado | `target_user_id`, `new_role` (solo alta JIT), `tenant_id` | Sin cambio (`api.py:361-364`). |
| `auth_sso_denied` | Identidad rechazada (firma, sin email, JIT) | `tenant_id` | Sin cambio (`api.py:302`, `:313`, `:379`). |
| `auth_sso_denied` | **Nuevo**: `state` ausente, inválido o ajeno, `code` ausente, proveedor cambiado entre login y callback | `tenant_id` | Research D6. Sin `state`, `code`, email ni token. Con tope por proceso (~30/min); el excedente solo deja un warning con el conteo. |
| `auth_sso_config_changed` | `PUT /auth/sso/config` | `actor_user_id`, `tenant_id` | Sin cambio (`admin_api.py:191-192`). El formulario del panel lo dispara por la misma API. |
