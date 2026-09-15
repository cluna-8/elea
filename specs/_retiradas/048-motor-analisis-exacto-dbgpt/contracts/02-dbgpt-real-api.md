# Contrato 2: backend → DB-GPT — descubierto en vivo (T074, 10-sep-2026)

Confirmado contra una instancia real (`eosphorosai/dbgpt-openai:v0.8.2`, config
`dbgpt-proxy-openai.toml`, `LLM_MODEL_NAME=azure-gpt-4o-mini` vía el motor de Eleia) — el
OpenAPI real del proceso (`GET /openapi.json`) más una prueba end-to-end real: subir un CSV,
preguntar, y confirmar la respuesta correcta con el SQL ejecutado auditado.

**Autenticación**: DB-GPT soporta `Authorization: Bearer <DBGPT_API_KEY>` si `system.api_keys`
en el TOML no está vacío. **Hoy está vacío por default** (`api_keys = []`) — sin auth propia, la
única defensa es el aislamiento de red (FR-002). Hardening pendiente (ver "Hallazgos" abajo):
fijar `system.api_keys` y que el backend mande ese Bearer — defensa en profundidad, no reemplaza
el aislamiento de red.

## Paso 1 — Subir el archivo

```
POST /api/v1/resource/file/upload?chat_mode=chat_excel&conv_uid=<uuid>
Content-Type: multipart/form-data

doc_files: <el archivo>
```

**Response 200**:
```json
{
  "success": true,
  "data": {
    "is_oss": true,
    "file_path": "dbgpt-fs://distributed/dbgpt_app_file/<id>?user_name=<user>&conv_uid=<uuid>",
    "file_name": "prueba.csv",
    "file_learning": true,
    "bucket": "dbgpt_app_file"
  }
}
```

`conv_uid` lo genera el CALLER (backend de Eleia) — un `uuid4` por conversación de análisis
exacto, no lo asigna DB-GPT.

## Paso 2 — Preguntar

```
POST /api/v1/chat/completions
Content-Type: application/json

{
  "model_name": "<uno de litellm/config.yaml>",
  "chat_mode": "chat_excel",
  "conv_uid": "<el mismo uuid del paso 1>",
  "select_param": "<el objeto `data` COMPLETO del paso 1, serializado a JSON string>",
  "user_input": "<la pregunta en lenguaje natural>"
}
```

**Hallazgo real (no documentado en ningún lado, causó un 500 hasta encontrarlo)**:
`select_param` NO es el `file_path` pelado — es el objeto `data` entero de la respuesta del
upload, vuelto a stringificar. `chat_data.excel_analyze.chat.py::_resolve_path` hace
`json.loads(select_param)`; pasar solo el `file_path` revienta con
`JSONDecodeError: Expecting value`.

**IMPORTANTE — `/api/v2/chat/completions` NO soporta `chat_mode="chat_excel"`** (confirmado:
devuelve 400 `invalid_chat_mode`, la lista soportada es
`chat_normal, chat_app, chat_flow, chat_knowledge, chat_data, chat_dashboard`). El camino real
para Excel/CSV es **`/api/v1/chat/completions`** con `ConversationVo` (`select_param`, no
`chat_param` de v2).

**Response 200**: streaming SSE (`text/event-stream`-like, aunque sin el content-type explícito
verificado), líneas `data: {...}` — igual que OpenAI streaming. Cada línea es el contenido
ACUMULADO hasta ese punto (no incremental por default — `incremental` default `false` en
`ConversationVo`), forma:

```json
{"id": "chatcmpl-...", "model": "azure-gpt-4o-mini", "choices": [{"index": 0, "message": {"role": "assistant", "content": "..."}}], "usage": {}}
```

La ÚLTIMA línea trae el contenido final completo, con el SQL ejecutado embebido en un tag
`<chart-view content="{...}">` (HTML-escaped JSON adentro del atributo `content`):

```
<chart-view content="{&quot;type&quot;: &quot;response_table&quot;, &quot;sql&quot;: &quot; SELECT ... &quot;, &quot;data&quot;: [...]}">
```

**Esto resuelve R3 (validación de SQL solo-lectura)**: el backend puede extraer el atributo
`content` del tag `<chart-view>` (regex o parser HTML simple), HTML-unescape, `json.loads()`, y
validar `sql` con `sqlglot` — auditable de verdad, no una promesa vacía.

Verificado en vivo: la consulta real ejecutada fue
`SELECT departamento AS Departamento, SUM(ventas) AS Total_Ventas FROM data_analysis_table WHERE departamento = 'Marketing' GROUP BY departamento;`
— `SELECT` puro, contra una tabla `data_analysis_table` que DB-GPT arma internamente a partir
del CSV subido (no aparece en `GET /api/v2/serve/datasources` — es efímera, scopeada a la
conversación, no un datasource persistente del catálogo).

## Hallazgos de seguridad adicionales (más allá de los ya documentados en research.md)

1. **El header `user-id`** (visto en `/api/v1/resource/file/upload` y `/api/v1/chat/completions`)
   es exactamente el vector del **GHSA de path-traversal** referenciado en la investigación
   original (`packages/dbgpt-app/.../python_upload_api.py`, un endpoint DISTINTO a
   `resource/file/upload` pero mismo patrón de confiar en ese header sin validar). **El backend
   de Eleia NUNCA debe pasar un valor de `user-id` controlado por el usuario final sin
   sanitizar** — usar un identificador propio generado server-side (p. ej. el `user.id` UUID de
   Eleia), nunca un string libre.
2. `system.api_keys` vacío por default (sin auth de DB-GPT) — mitigado hoy por el aislamiento de
   red (FR-002), pero vale la pena fijarlo como hardening adicional (tarea nueva, ver abajo).

## Cambios a `tasks.md` que este descubrimiento deja claros

- T081 (header de atribución): el nombre real a mandar es **`user-id`** — pero sanitizado
  (UUID propio de Eleia, nunca el username/email crudo) — no el patrón `X-Guardian-Acting-User`
  literal, DB-GPT no lo lee.
- T077/T080: el servicio debe generar `conv_uid` (uuid4) por conversación de análisis exacto Y
  usar `/api/v1/chat/completions` (v1, `ConversationVo`), no v2.
- T092 (validación `sqlglot`): parsear el tag `<chart-view>` de la respuesta final (no
  incremental) para extraer `sql` antes de auditar/validar.
- **Nueva tarea de hardening** (agregar a Polish): fijar `system.api_keys` en el TOML montado y
  que el backend mande ese Bearer — defensa adicional más allá del aislamiento de red.
