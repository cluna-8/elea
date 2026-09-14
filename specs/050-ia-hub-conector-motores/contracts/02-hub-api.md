# Contrato 2 — API interna de Eleia Hub (navegador ↔ `client/server.js`)

Todas las rutas exigen sesión del Hub (cookie) salvo `/api/auth/login` y `/api/branding`. Sin
sesión ⇒ 401. Los errores de motor se devuelven con copy neutro y `code` estable; el detalle va al
log del servidor (FR-016).

## Sin cambios (spec 040/044)

`POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/branding`, `GET /api/user/current`,
`GET /api/user/budget`, `GET /api/models`, `GET/POST /api/workspaces*` (documentos),
`POST /api/threads/*`, `GET /api/workspaces/{slug}/messages`, `POST /api/chat`.

## Cambia: `POST /api/workspaces/upload`

Igual firma. Internamente: `extract_text.py` → subida directa al motor de documentos →
reindexado. **Sin enmascarado** (FR-001/002). Respuesta sin los campos `entities`, `truncated`,
`documentId` de enmascarado.

## Nuevo: `GET /api/features`

**Response 200**: `{ "documents": bool, "tabular": bool, "presentations": bool, "presentations_admin_port": int|null, "docgen": bool }`
según `ANYTHINGLLM_URL`, `TABULAR_URL`, `PRESENTON_URL`, `PRESENTON_ADMIN_PORT`, `DOCGEN_URL` no vacías.

## Nuevo: proxy de administración de plantillas (segundo puerto, `PRESENTON_ADMIN_PORT`)

Todo lo que llega a ese puerto se reenvía a la pantalla de Presenton **solo si** la cookie de sesión
del Hub corresponde a un rol `tenant_admin`/`super_admin`; si no, página "Solo administradores"
(403) y Presenton no recibe nada. La cookie del Hub no viaja a Presenton.

## Renombrado: `/api/tabular/*` (antes `/api/exact-analysis/*`)

Antes de cada ruta con `{id}`: `GET /workspaces/{id}` en Guardian con el token de la persona;
403 ⇒ 403 `{ code: "no_access" }` sin tocar tabular (FR-011).

| Ruta | Request | Response 200 | Errores |
|---|---|---|---|
| `POST /api/tabular/workspaces` | `{ display_name }` | `{ id, display_name, kind: "exact_analysis" }` — crea en Guardian (`kind: exact_analysis`, FR-041) y luego `POST /v1/spaces` en tabular; si tabular falla, borra el registro en Guardian | `502 { code: "engine_unavailable" }` |
| `GET /api/tabular/workspaces` | — | `{ workspaces: [ { id, display_name, role } ] }` (filtra `kind = exact_analysis` de `GET /workspaces`) | — |
| `POST /api/tabular/workspaces/{id}/files` | multipart `file` (csv/xlsx, ≤ 50 MB) | `{ file_id, tables: [ { name, columns: [..], rows } ] }` | `413 { code: "file_too_large" }`, `415 { code: "unsupported_format" }` |
| `GET /api/tabular/workspaces/{id}/files` | — | `{ files: [ { file_id, name, tables: [..], uploaded_at } ] }` | — |
| `DELETE /api/tabular/workspaces/{id}/files/{file_id}` | — | `{ status: "ok" }` | — |
| `PUT /api/tabular/workspaces/{id}/dictionary` | `{ tables: { <alias>: { <columna>: descripción } } }` (vacío borra) | `{ updated: n }` | `403` sin membresía |
| `POST /api/tabular/workspaces/{id}/query` | `{ question, history?: [ { question, answer } ] (≤ 5) }` | `{ answer, sql, rows: [ {..} ] (≤ 500), columns: [..], model_used }` | `422 { code: "unsafe_sql" }`, `402 { code: "budget_exceeded" }`, `504 { code: "timeout" }` |

## Nuevo: `GET /api/presentations/templates`

**Response 200**: `{ "templates": [ { id, name, description, custom: bool } ] }` — plantillas modelo de
Presenton: las integradas (`general`, `executive`, `modern`, …) y las **propias del cliente**
(`custom: true`, creadas a partir de un PPTX corporativo; van primero). Pedido del dueño 13-sep.

## Nuevo: `POST /api/presentations/generate`

**Request**: `{ "content": string (≤ 20.000 chars), "title": string, "n_slides": 3..20, "export_as": "pptx" | "pdf", "template"?: string (id de plantilla; default `general`), "instructions"?: string, "thread_key"?: string }`

**Response 200**: `{ "artifact": { id, kind: "pptx" | "pdf", title, thread_key, created_at, size } }`

**Errores**: `502 { code: "engine_unavailable" }`, `504 { code: "timeout" }` (120 s), `422` si el archivo devuelto está vacío.

## Nuevo: `POST /api/documents/generate` (spec 049, inactivo hasta `DOCGEN_URL`)

**Request**: `{ "content", "template_id", "export_as": "docx" | "xlsx" | "pdf", "mode": "template" | "free", "thread_key"? }` → `{ artifact }`. `404 { code: "feature_disabled" }` mientras no haya motor.

## Nuevo: `POST /api/handoff`

**Request**: `{ "target": "presentation" | "document", "content": string, "tabular"?: { "workspace_id", "question" }, "options": { title, n_slides, export_as, template, instructions, thread_key } }`

Flujo: si `tabular` viene → verificar membresía → `POST /api/tabular/.../query` → si falla,
`502 { code: "tabular_failed" }` y no se genera nada → si no, `content = content + "\n\n" + answer + tabla markdown (≤ 50 filas)` → llamar al target.

**Response 200**: `{ "artifact": {...}, "tabular_used": bool }`

## Nuevo: artefactos

`GET /api/artifacts` → `{ artifacts: [ { id, kind, title, thread_key, created_at, size } ] }` (solo de la persona).
`GET /api/artifacts/{id}/download` → archivo con `Content-Disposition`; `403` si no es la dueña; `404` si no existe.
`DELETE /api/artifacts/{id}` → `{ status: "ok" }`; `403` si no es la dueña.

Almacenamiento: `/app/data/artifacts/<userId>/<uuid>.<ext>` + `/app/data/artifacts/<userId>/index.json`. Volumen `client_artifacts`.

## Variables de entorno del Hub

| Variable | Obligatoria | Uso |
|---|---|---|
| `ELEA_BACKEND_URL` | sí | Guardian backend |
| `ANYTHINGLLM_URL`, `ANYTHINGLLM_API_KEY` | no | motor de documentos |
| `TABULAR_URL`, `TABULAR_INTERNAL_TOKEN` | no | motor tabular |
| `PRESENTON_URL` | no | motor de presentaciones |
| `PRESENTON_ADMIN_PORT` | no | pantalla de plantillas de Presenton para admins (8097) |
| `ARTIFACTS_DIR` | no | archivos generados (`/app/data/artifacts`) |
| `DOCGEN_URL`, `DOCGEN_INTERNAL_TOKEN` | no | motor de documentos generados (049) |
| `HUB_BRAND_*` | no | marca |
| ~~`MASKING_VIRTUAL_KEY`~~ | eliminada | — |
