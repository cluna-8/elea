# Phase 1 Data Model — 044-hub-chat-panel-admin

Ninguna entidad se persiste en estas dos UIs (`client/`, `frontend/`) — toda persistencia vive en
el backend de la spec 043. Lo de acá son **modelos de vista**: la forma en que cada UI consume los
contratos y el estado efímero que mantiene mientras el usuario navega.

## Eleia Hub (`client/`)

### Sesión (ya existe, sin cambio de forma — `client/server.js:47`)
`{ token, user: {id, username, role, email} }`, indexada por cookie `elea_rag_sid`.

### Espacio visible (proyección del contrato 1)
```
{ id, engine_slug, display_name, role: "owner"|"member", status: "active"|"unassigned" }
```
Reemplaza la lista cruda de `GET /api/v1/workspaces` de AnythingLLM que el Hub consume hoy.

### Estado de subida en curso (efímero, vive en el cierre de la función del handler)
```
{ document_id, chunks_total, chunks_done, entities_summary: {TIPO: count} }
```
Se descarta al terminar la subida; no se persiste en ningún lado del lado del Hub.

### Presupuesto propio (proyección del contrato 2)
```
{ used_usd, max_usd, status: "ok"|"exceeded" }
```

## Eleia Guardian (`frontend/`)

### Fila de usuario en la tabla (extiende la forma actual de `UsersPage.tsx`)
```
{ id, username, email, role, group, account_type: "person"|"service", purpose?, is_active, deactivated_at? }
```
`purpose` solo presente cuando `account_type === "service"`.

### Fila de "modelo con consumo" (Dashboard/Costos, proyección del contrato 4)
```
{ model, requests, cost_usd, ... } // ya no incluye filas de surface/evidence
```

### Fila de "espacio sin asignar" (nueva vista, `WorkspacesUnassignedPage.tsx`)
```
{ id, engine_slug, display_name, status: "unassigned" }
```
Consumida vía `GET /workspaces?all=true&status=unassigned` (contrato 1, con permiso admin).

## Relación con las entidades de la 043

Ninguna de estas formas introduce campos que el backend no exponga ya en `data-model.md` de la 043
— son subconjuntos/proyecciones directas. Si `tasks.md` de la 044 encuentra que falta un campo, es
un defecto de contrato a reportar contra la 043, no algo a inventar del lado de la UI.
