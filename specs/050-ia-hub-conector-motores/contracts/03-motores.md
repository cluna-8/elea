# Contrato 3 — Enlaces Hub ↔ motores y motores ↔ Guardian

Regla general: cada motor es un contenedor sin puertos publicados, en una red interna con el Hub
y con `engine`. Su única salida a un modelo es `http://engine:4000/v1` con su propia llave `svc.*`
(nunca la maestra). Ningún motor tiene credenciales de proveedor ni de Guardian backend.

---

## 3.1 Motor de documentos (AnythingLLM 1.16.1) — sin cambios de contrato

**Hub → motor**: `http://anythingllm:3001/api/v1`, `Authorization: Bearer <ANYTHINGLLM_API_KEY>`.
Rutas usadas: `workspace/new`, `workspace/{slug}`, `workspace/{slug}/update`, `workspace/{slug}`
DELETE, `workspace/{slug}/thread/new`, `.../thread/{t}/update`, `.../thread/{t}` DELETE,
`.../thread/{t}/chat` `{message, mode:"chat"}` → `{textResponse, sources, metrics.model}`,
`.../thread/{t}/chats` (historial), `document/upload` (multipart `file`, texto plano extraído),
`workspace/{slug}/update-embeddings` `{adds:[..], deletes:[..]}`.

**Motor → Guardian engine**: `LLM_PROVIDER=generic-openai`,
`GENERIC_OPEN_AI_BASE_PATH=http://engine:4000/v1`, `GENERIC_OPEN_AI_API_KEY=<svc.anythingllm-provider>`,
`GENERIC_OPEN_AI_MODEL_PREF=<modelo real>`. Embeddings: embedder **local** del motor (no pasa por
Guardian; FR-051). Compose dev debe dejar de usar la llave maestra (FR-050).

**Qué guarda**: documentos crudos, embeddings, espacios, hilos y mensajes.

---

## 3.2 Motor tabular (nuevo, `tabular/`)

**Servicio**: `http://tabular:8090/v1`. Red `tabular-net` (Hub, engine). Volumen `tabular_data:/data`.

**Auth Hub → tabular**: `Authorization: Bearer <TABULAR_INTERNAL_TOKEN>` (obligatoria; 401 si falta) +
`X-Hub-User-Id: <uuid de la persona>` (obligatoria; se reenvía a Guardian como acting-user).

### `POST /v1/spaces`
**Request**: `{ "workspace_id": uuid }` → crea `/data/spaces/<workspace_id>/db.duckdb`.
**Response 201**: `{ "workspace_id" }`. `409` si ya existe (idempotente para el Hub).

### `POST /v1/spaces/{workspace_id}/files`
**Request**: multipart `file` (csv, xlsx; ≤ 50 MB). Cada hoja/archivo ⇒ tabla `f<N>_<nombre_normalizado>`.
**Response 201**: `{ "file_id", "name", "tables": [ { "name", "columns": [ { "name", "type" } ], "rows": int, "sample": [ {..} ] (5) } ] }`.
**Errores**: `413`, `415`, `422 { detail: "hoja vacía" }`.

### `GET /v1/spaces/{workspace_id}/files`
**Response 200**: `{ "files": [ { file_id, name, tables: [..], uploaded_at } ] }`.

### `DELETE /v1/spaces/{workspace_id}/files/{file_id}`
**Response 200**: `{ "status": "ok" }` (borra tablas y archivo).

### `POST /v1/spaces/{workspace_id}/query`
**Request**: `{ "question": string, "history": [ { "question", "answer" } ] (≤ 5) }`.

**Flujo interno**:
1. DDL completo del espacio + 5 filas de muestra por tabla + historial + pregunta → `POST engine/v1/chat/completions` (`model: TABULAR_MODEL`, `X-Guardian-Acting-User`). Prompt exige una sola sentencia `SELECT`/`WITH` en DuckDB, sin comentarios.
2. Validación: parseo con `sqlglot`; una sentencia; tipo `SELECT`/`WITH`; lista negra `read_csv|read_parquet|read_json|COPY|ATTACH|INSTALL|LOAD|PRAGMA|EXPORT|CREATE|INSERT|UPDATE|DELETE|DROP|ALTER`; `LIMIT 500` forzado si falta o es mayor.
3. Ejecución con conexión `read_only=True`, `SET memory_limit='1GB'`, `threads=2`, `interrupt()` a 20 s.
4. Filas (≤ 50) + pregunta → segunda llamada corta a Guardian → `answer`.

**Response 200**: `{ "sql": string, "columns": [..], "rows": [ {..} ] (≤ 500), "answer": string, "model_used": string }`.
**Errores**: `422 { code: "unsafe_sql", detail }` (no se ejecutó); `502 { code: "engine_error", status: 400|401|402 }` (reenvía el código de Guardian); `504 { code: "timeout" }`.

**tabular → Guardian engine**: `Authorization: Bearer <TABULAR_ENGINE_VIRTUAL_KEY>` (`svc.tabular`,
`can_act_on_behalf: true`), `X-Guardian-Acting-User`, `model: <TABULAR_MODEL>` (real). Nunca
`/v1/embeddings`.

**Variables**: `TABULAR_INTERNAL_TOKEN`, `TABULAR_ENGINE_URL=http://engine:4000/v1`,
`TABULAR_ENGINE_VIRTUAL_KEY`, `TABULAR_MODEL` (default `azure-gpt-5.4-mini`: con planillas reales de Elea el 12-sep resolvió 5/5 preguntas de cruce; `azure-gpt-4o-mini` falló los JOIN e inventó conteos al redactar), `TABULAR_MAX_FILE_MB=50`, `TABULAR_QUERY_TIMEOUT_S=20`.

**Qué guarda**: archivos crudos y `.duckdb` por espacio. No guarda conversación (el Hub manda historial corto).

---

## 3.3 Motor de presentaciones (Presenton)

**Servicio**: `http://presenton:80` (la imagen escucha en el 80; el 5001 de la doc es el mapeo de host del ejemplo). Red `presentations-net` (Hub, engine). Volumen `presenton_data:/app_data`. Sin `ports:`.

**Compose (env)**: `LLM=custom`, `CUSTOM_LLM_URL=http://engine:4000/v1`,
`CUSTOM_LLM_API_KEY=${PRESENTON_ENGINE_VIRTUAL_KEY}` (`svc.presenton`), `CUSTOM_MODEL=<modelo real>`,
`DISABLE_IMAGE_GENERATION=true`, `CAN_CHANGE_KEYS=false`, `DISABLE_AUTH=true` (Presenton 0.9.x trae login propio; se desactiva porque solo el Hub llega por red interna y la identidad la pone el Hub contra Guardian). Imagen fijada por digest (`sha256:f0c6a235…`, v0.9.7-beta).

**Hub → Presenton**: sin credencial (red interna). Verificar en `plan.md` la firma exacta de la
versión fijada; la documentada hoy es:

### `POST /api/v1/ppt/presentation/generate`
**Request**: `{ "content": string, "n_slides": int, "language"?: "Spanish", "template"?: string, "export_as": "pptx" | "pdf", "instructions"?: string }`
**Response 200**: `{ "presentation_id", "path", "edit_path" }`. El Hub descarga `path`, valida tamaño > 0 y tipo, y lo copia a su volumen de artefactos.

**Presenton → Guardian engine**: llave `svc.presenton`, **sin** `X-Guardian-Acting-User` (Presenton no permite cabeceras extra). Gasto atribuido a `svc.presenton`. Sin embeddings.

**Qué guarda**: sus presentaciones internas (efímeras para nosotros). La fuente de verdad es la copia en el Hub.

**Plantillas modelo** (pedido del dueño 13-sep): `GET /api/v1/ppt/template/all` devuelve las integradas
(`is_default: true`: general, executive, modern, editorial, standard, swift, momentum, dynamic) y las
propias (`is_default: false`). El Hub las lista y manda `template: <id>` al generar. Crear una plantilla
propia a partir del PPTX corporativo del cliente usa el flujo de Presenton (`/template/init` →
`/template/fonts-upload-and-slides-preview` → `/template/async`, con un modelo con visión vía
Guardian); **queda para el hito 6/plan** exponerlo como acción de admin desde el Hub, porque la UI de
Presenton no es accesible (FR-032).

**Restricciones**: UI de Presenton no accesible por personas (FR-032).

---

## 3.4 Motor de documentos generados (docgen, spec 049) — contrato reservado

**Servicio**: `http://docgen:8091/v1`. Red `docgen-net`. Mismo esquema de auth que tabular
(`Authorization: Bearer <DOCGEN_INTERNAL_TOKEN>` + `X-Hub-User-Id`).

### `GET /v1/templates` → `{ templates: [ { id, name, kind: docx|xlsx, fields: [..] } ] }`
### `POST /v1/documents`
**Request**: `{ "template_id"?, "content", "instructions"?, "export_as": docx|xlsx|pdf, "mode": "template" | "free" }`
**Response 200**: archivo binario (`Content-Type` según formato) + cabecera `X-Docgen-Mode`.
**Errores**: `422` plantilla incompatible; `403 { code: "free_mode_not_allowed" }` si el rol no tiene modo libre (spec 047); `504`.

**docgen → Guardian engine**: llave `svc.docgen` (`can_act_on_behalf: true`), `X-Guardian-Acting-User`. Modo plantilla: ≤ 2 llamadas. Modo libre: sandbox sin red; solo el modelo sale por Guardian.

Detalle completo en la [spec 049](../../049-motor-generacion-documentos/spec.md).

---

## 3.5 Instalador — llaves de servicio

`elea-installer/install.sh` `create_service_key()` ya crea `svc.anythingllm-provider` y
`svc.rag-masking` con `POST /users` + `POST /keys`. Agregar:

| Cuenta | `tool_type` | `can_act_on_behalf` | Variable en `.env` | Motor |
|---|---|---|---|---|
| `svc.tabular` | `servicio` | `true` | `TABULAR_ENGINE_VIRTUAL_KEY` | tabular |
| `svc.presenton` | `servicio` | `false` | `PRESENTON_ENGINE_VIRTUAL_KEY` | Presenton |
| `svc.docgen` | `servicio` | `true` | `DOCGEN_ENGINE_VIRTUAL_KEY` | docgen (049) |

Retirar `svc.dbgpt-excel` y `DBGPT_ENGINE_VIRTUAL_KEY`. Cada motor con su llave: sin llave, el
motor arranca pero recibe 401 del engine; el Hub sigue funcionando y muestra copy neutro.
