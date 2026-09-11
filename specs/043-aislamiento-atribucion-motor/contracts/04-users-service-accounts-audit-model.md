# Contrato 4 — Tipo de cuenta en usuarios; modelo/superficie separados en costos

**Consumido por**: spec 044, US2, US4 (P2).

## `GET /users`

Nuevo query param `include_service` (bool, default `false`). Sin él, excluye
`account_type='service'`. Respuesta gana el campo `account_type` por usuario:
```json
{"users": [{"id": "uuid", "username": "ana.gomez", "account_type": "person", ...}]}
```

Cuando `include_service=true`, cada cuenta de servicio incluye además `purpose` (string legible,
p. ej. "Protección de documentos antes de indexarlos") para que la 044 lo muestre en su sección
plegada de solo lectura (FR-022 de 044).

## Conteos y asientos de licencia

`GET /users/count` (o el mecanismo existente que alimente "Usuarios activos" y el gate de seat
enforcement de la spec 021) MUST excluir `account_type='service'` y usuarios con `deactivated_at
IS NOT NULL`.

## `GET /costs/top-models` y `GET /analytics/summary` (o sus equivalentes actuales)

MUST filtrar `event_type='traffic' AND model IS NOT NULL` (ver `data-model.md` R5) — dejan de
devolver `license` y `chat-ui`/superficies. Forma de respuesta sin cambios (lista de
`{model, requests, cost_usd, ...}`), solo cambia el contenido.

## `GET /costs/by-user` (o equivalente)

Nuevo o extendido para agrupar por `COALESCE(acted_for_user_id, user_id)` — así el consumo hecho
por una llave de servicio "en nombre de" alguien aparece bajo esa persona, no bajo la cuenta de
servicio (contrato 2).
