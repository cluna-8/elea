# Contrato 1 — API de Guardian que consume Eleia Hub (existente, verificada 12-sep-2026)

Todo bajo `http://backend:8000/api/v1`. Salvo login, cada llamada lleva
`Authorization: Bearer <jwt de la persona>`. 401 en cualquier ruta ⇒ el Hub cierra sesión.
Fuentes: `backend/src/api/users.py`, `chat.py`, `workspaces.py`, `keys.py`, `auth/session.py`.

## `POST /users/login`

**Request**: `{ "username": string, "password": string }`

**Response 200**: `{ "access_token": string, "token_type": "bearer", "user": { "id": uuid, "username": string, "role": string, "display_label": string, "email": string } }`

**Token**: JWT HS256, **24 h**, claims `sub`, `role`, `username`, `tenant`, `exp`. Sin refresh.

**Errores**: `401` "Credenciales incorrectas." (usuario inexistente, inactivo o clave mala).

**Nota SSO**: este es el único punto que cambia cuando Guardian tenga SSO. El Hub no guarda claves.

## Identidad

**No existe `GET /users/me`.** El Hub toma identidad del `user` del login. `tenant` solo está en
el JWT. `account_type` (`person`|`service`) se deriva del prefijo `svc.` del usuario.

## `GET /users/me/budget`

**Response 200**: `{ "used_usd": number, "max_usd": number | null, "status": "ok" | "exceeded" }`.
Sin presupuesto configurado ⇒ `{0.0, null, "ok"}`. Personal primero, grupo como respaldo.
**Nunca devuelve 402.**

## `GET /chat/models`

**Response 200**: **array** `[ { "model_name": string, "provider": string, "model_id": string, "api_base"?: string, "is_configured": bool, "is_eu_compliant": bool } ]`.
`auto` va **primero** cuando el router semántico está activo. Ante error de config devuelve `[]`.

## `POST /chat/completions` (chat directo, sin espacio)

**Auth**: JWT de la persona (o llave `sk-*`, no usada por el Hub). Rol `lectura` ⇒ 403.

**Request**: `{ "message": string, "model": string }` (+ overrides opcionales de política). **Un turno, sin historial, sin streaming.**

**Response 200**: `{ "response": string, "pipeline_metadata": { "layer_llm": { "model_used": string, "latency_ms", "prompt_tokens", "completion_tokens", "cost_usd" }, "layer_masking": { "entities_detected", ... }, "layer_compliance": {...}, "governance": {...}, "auto_router"?: {...} } }`.
`model_used` es el modelo que realmente respondió. `auto_router` solo aparece si se pidió `auto`.

**Errores**: `401`; `402` "Presupuesto mensual agotado…"; `403` rol; `429` con `Retry-After`; `503` auditoría en modo cerrado.

## Espacios — `/workspaces`

Reglas comunes: sin sesión ⇒ 401. Sin acceso ⇒ **siempre 403** "sin acceso a este espacio" (nunca
404), con fila de auditoría. Admin = rol `super_admin` | `tenant_admin`.

| Método y ruta | Request | Response 200 | Autorización |
|---|---|---|---|
| `GET /workspaces` | — | `{ "workspaces": [ { id, engine_slug, display_name, role, status, kind } ] }` | miembro (solo los suyos) |
| `GET /workspaces?status_filter=unassigned` | — | `{ "workspaces": [ { id, engine_slug, display_name, status } ] }` (sin `kind`) | admin |
| `POST /workspaces` | `{ display_name, engine_slug? }` — **hoy no acepta `kind`** (FR-041 lo agrega) | `{ id, engine_slug, display_name, role: "owner", status }` | cualquier persona |
| `GET /workspaces/{id}` | — | `{ id, engine_slug, display_name, role, status }` (FR-041 agrega `kind`) | miembro o admin |
| `GET /workspaces/{id}/members` | — | `{ "members": [ { user_id, username, role } ] }` | miembro o admin |
| `POST /workspaces/{id}/members` | `{ username }` | `{ user_id, role }` | dueño o admin; `409` si el usuario no existe |
| `DELETE /workspaces/{id}/members/{user_id}` | — | `{ "status": "ok" }` | dueño o admin; `409` si es el dueño |
| `PATCH /workspaces/{id}/transfer-owner` | `{ new_owner_user_id }` | `{ id, owner_user_id }` | dueño o admin; `409` si no es miembro |
| `GET /workspaces/{id}/threads` | — | `{ "threads": [ { id, workspace_id, engine_thread_slug, principal_engine_thread_slug, created_at } ] }` (solo los del que llama) | miembro |
| `POST /workspaces/{id}/threads` | `{ engine_thread_slug?: string, principal_engine_thread_slug?: string }` (get-or-create) | igual que el elemento de la lista | miembro |
| `DELETE /workspaces/{id}/threads/{thread_id}` | — | `{ "status": "ok" }` | dueño del hilo |

`kind` ∈ `rag` | `exact_analysis`. Cuando un dueño es dado de baja, sus espacios pasan a
`status: "unassigned"`.

## Cuentas y llaves de servicio (usa el instalador, no el Hub)

**`POST /users`** (admin): `{ username: "svc.<nombre>", email, role: "client", password }`.
El prefijo `svc.` es lo que lo hace cuenta de servicio. **No hay campo `tool_type` en el usuario.**

**`POST /keys`** (admin): `{ name, user_id, tool_type: "servicio", can_act_on_behalf: true|false, models?: [..], max_budget?, budget_duration?: "30d", rpm_limit?, tpm_limit? }`
→ `{ id, name, key_preview, plain_key, user_id, ... }`. **`plain_key` se devuelve una sola vez.**
`409` si ya hay una llave activa para ese `tool_type` y usuario.

Cuentas existentes: `svc.anythingllm-provider`, `svc.rag-masking`. Nuevas: `svc.tabular`
(`can_act_on_behalf: true`), `svc.presenton` (`false`), `svc.docgen` (`true`, spec 049).

## `POST /gw/inspect` — deja de usarse

Endpoint de enmascarado por trozos (`X-Sentinel-Key`, body `{text, tool, document_id}`). El Hub
lo elimina (FR-001). Queda en Guardian sin cambios.

## Comportamiento del engine (`http://engine:4000/v1`) para los motores

- `Authorization: Bearer <llave svc.*>`. Nunca la llave maestra (FR-050).
- `model` debe ser un nombre real del catálogo. **`auto` no existe acá** (400).
- Cabecera opcional `X-Guardian-Acting-User: <uuid>`: honrada si la llave tiene
  `can_act_on_behalf` y el usuario es del tenant; si no, se ignora sin bloquear.
- Respuestas: `200` cuerpo OpenAI estándar (texto ya desenmascarado); `400` bloqueo de política
  (AI Act, secreto, entidad bloqueada, NLP caído en modo bloqueo) con motivo en `detail`;
  `401` llave inválida; `402` presupuesto de la cuenta `svc.*` agotado.
- Sin cabeceras propias en la respuesta. Conteos de enmascarado y costo solo en `audit_logs`.
- `/v1/embeddings`: pasa auth y presupuesto, **no** pasa el guardrail. Prohibido para texto del
  cliente (FR-051).
