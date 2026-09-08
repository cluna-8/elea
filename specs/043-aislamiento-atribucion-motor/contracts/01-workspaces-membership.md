# Contrato 1 — Espacios de trabajo, membresías e hilos con verificación de acceso

**Consumido por**: spec 044, US1 (P1).

## Endpoints (backend Guardian, prefijo `/workspaces`, auth JWT de sesión)

### `GET /workspaces`
Lista los espacios donde el usuario autenticado es `owner` o `member`. Admins con permiso explícito
pueden pasar `?all=true&status=unassigned` para ver los espacios sin dueño (FR-006/FR-010 de 044).

Respuesta (200):
```json
{
  "workspaces": [
    {"id": "uuid", "engine_slug": "contabilidad", "display_name": "Contabilidad",
     "role": "owner", "status": "active"}
  ]
}
```
Sin sesión → 401. Nunca 200 con datos de espacios ajenos.

### `GET /workspaces/{id}`
200 si el usuario tiene membresía (cualquier rol) o es admin; 403 "sin acceso" en caso contrario
(NUNCA 404 que confirme existencia a quien no tiene acceso — mensaje uniforme).

### `POST /workspaces`
Crea el workspace en el backend (y dispara la creación real en AnythingLLM vía el flujo ya
existente en `client/server.js` — la orquestación exacta la decide la 044); el creador queda como
`owner`.

### `GET /workspaces/{id}/members` · `POST /workspaces/{id}/members` · `DELETE /workspaces/{id}/members/{user_id}`
Solo `owner` del workspace o admin. `POST` agrega por `username`; `DELETE` quita (nunca al último
`owner` sin transferir antes — usar `PATCH .../transfer-owner`).

### `PATCH /workspaces/{id}/transfer-owner`
Body `{"new_owner_user_id": "uuid"}`. Solo `owner` actual o admin. El nuevo dueño debe ya ser
`member`.

### Hilos: `GET /workspaces/{id}/threads` · `POST /workspaces/{id}/threads` · `DELETE /workspaces/{id}/threads/{thread_id}`
Devuelven/operan **solo** los hilos cuyo `owner_user_id` es el usuario autenticado. `POST` sin
`engine_thread_slug` crea/usa el hilo principal del usuario en ese workspace.

## Garantía de verificación en el sistema (FR-004)

Todo endpoint de este contrato, y todo endpoint de documentos/ajustes/chat que reciba un
`workspace_id`/`slug`, MUST resolver la pertenencia contra `workspace_memberships` en el backend
antes de proxyar a AnythingLLM — nunca delegar la verificación al cliente que llama.

## Casos de error uniformes

| Caso | Código | Cuerpo |
|---|---|---|
| Sin sesión | 401 | `{"detail": "iniciá sesión"}` |
| Sin membresía | 403 | `{"detail": "sin acceso a este espacio"}` |
| Workspace inexistente Y sin membresía | 403 (igual que arriba, no 404) | idem |
| Intento de quitar al último owner sin transferir | 409 | `{"detail": "transferí la propiedad antes de salir"}` |

## Backfill (FR-006)

Instalaciones existentes: todo `engine_slug` que AnythingLLM ya tenga y el backend no conozca se
importa como `Workspace(status='unassigned', owner_user_id=NULL)` en un paso de sincronización
(idempotente, se puede correr más de una vez) — no se pierde ningún espacio, documento ni hilo
existente en AnythingLLM.
