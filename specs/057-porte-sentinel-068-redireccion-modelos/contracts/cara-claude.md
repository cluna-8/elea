# Contrato — Cara Claude en Eleia (`/api/v1/gw/v1/*`, redirección encendida)

**Base**: el contrato de la 068 rige tal cual (Sentinel
`specs/068-politica-redireccionamiento-modelos/contracts/cara-claude.md`, `6a70855`): rutas auxiliares
y autenticación (`Bearer` y `x-api-key`, `?beta=true`, `HEAD /api/hello` → 404), `GET /gw/v1/models`
(vista Anthropic, < 1 s, nunca redirige), `POST /gw/v1/messages` (pasos 1–6, orden de eventos
garantizado, `model` = id público, `usage` completo) y la tabla de errores. Con la redirección
apagada y sin postura, nada de esto aplica y la pasarela es la de hoy (FR-007).

Este documento fija **lo que Eleia agrega o precisa** (Sentinel no lo hizo: sus T139, T094, T093,
T090 y T091; en este documento los ids de tarea son **de Sentinel**), escrito genérico para volver por HANDOFF.

## 1. Campos del pedido hacia un destino traducido (T139, FR-035)

- Se reenvían solo los campos de primer nivel de esta lista permitida: `model`, `messages`, `system`,
  `max_tokens`, `stop_sequences`, `stream`, `temperature`, `top_p`, `top_k`, `tools`, `tool_choice`,
  `metadata`. El normalizador existente sigue adaptando `thinking`, `output_config`,
  `context_management`, `cache_control` (salvo T-F), los `system` intermedios y el recorte de
  `max_tokens` a la ventana del destino.
- Todo otro campo (p. ej. `safeguards`) se quita; sus **nombres** van a
  `extensions.redirect.dropped_fields`. Nunca se responde error por un campo desconocido.
- Hacia un destino **nativo** no se filtra.

## 2. Cabeceras beta y credenciales del cliente (T094 de Sentinel, FR-040, FR-042)

| Destino | `anthropic-beta` recibidas | Otras credenciales del cliente |
|---|---|---|
| Nativo | se reenvían las que están en la lista permitida (dato de la extensión, editable por super-admin); el resto se descarta | se ignoran (la credencial sale del destino) |
| Traducido | se descartan todas; `betas_dropped` = cantidad | se ignoran |

Con la política encendida, una credencial de **suscripción personal** hacia un destino de otro
proveedor ⇒ `401 authentication_error`, texto neutro.

## 3. `POST /gw/v1/messages/count_tokens` (T093 de Sentinel, FR-041)

| Destino del id pedido | Respuesta | `count_tokens_mode` |
|---|---|---|
| Cualquiera, con enmascarado forzado vigente (FR-041; R29 punto 2b) | `200 {"input_tokens": N}` estimado localmente o `404 not_found_error`; **nunca** se reenvía | `estimated` · `not_found` |
| Nativo, sin forzado | reenvío al destino | `forwarded` |
| Traducido | `200 {"input_tokens": N}` estimado localmente (`cl100k_base` horneado o `caracteres/4`, sin red; research R12) sobre el cuerpo ya normalizado | `estimated` |
| Traducido sin estimador disponible | `404 not_found_error` (la herramienta estima sola) | `not_found` |
| Id no publicado | igual que `POST /messages`: 404 «Modelo no disponible para tu organización.» | — |

## 4. Stream (T091 de Sentinel, FR-037, FR-038, FR-039)

- `event: ping` si el destino calla más de **15 s**.
- `message_start.message.model` = id público pedido; `usage` con los cuatro contadores (0 si el destino
  no informa).
- Error después de `message_start` ⇒ `event: error` con el cuerpo de error y cierre; nunca
  `message_stop` tras una falla.

## 5. Razonamiento (T090 de Sentinel, FR-036)

Los bloques `thinking` que produce un destino traducido salen con firma HMAC de la pasarela; al volver
en el turno siguiente, una firma válida se reconstruye como `reasoning_content` del destino si lo
necesita; una firma ajena o inválida descarta el bloque sin error. No se manda a un destino rastros de
razonamiento de otro destino.

## 6. Sondeo de arranque y parámetros de Azure (HANDOFF §2.2 pasos 7–8)

`max_tokens < 16` hacia OpenAI/Azure ⇒ se sube a 16; `max_tokens` ⇒ `max_completion_tokens` para
modelos que lo exigen por chat; ambos en `adjusted_params` (lo hace `sentinel/engine/redirect_guard.py`,
copiado; T-C solo lo prueba con Azure).

## 7. Errores agregados o precisados

| Situación | HTTP | `error.type` | Texto |
|---|---|---|---|
| Destino fuera de la región sin postura y `default_posture = reject_offregion` (R23) | 403 | `permission_error` | «Modelo no disponible para tu región.» |
| Destino sin jurisdicción de inferencia registrada, con cualquier postura, fila o relajación (FR-028, FR-031; QA A8) | 403 | `permission_error` | «Modelo no disponible para tu región.» |
| Respaldo en código: región del perfil sin resolver, o sin fila de región y destino fuera de `region_codes` (FR-031; R28) | 403 | `permission_error` | «Modelo no disponible para tu región.» |
| Enmascarado forzado (postura por defecto `masked_all`, respaldo en código o postura explícita) con informe de enmascarado incompleto, degradado, de alcance no completo o con contenido no analizable (FR-027; S14) | 400 | `invalid_request_error` | «El pedido no pudo protegerse para este destino y fue bloqueado. Probá en una conversación nueva.» (motivo interno `masking_required`; el guard copiado, `sentinel:sentinel/engine/redirect_guard.py:328-330`, más la verificación de S14; texto y código **tal cual** la cara copiada, `sentinel:sentinel/redirect/faces/claude.py:94-98`: 400 y no 403 porque Claude Desktop antepone «Failed to authenticate» a todo 403; QA M8) |
| Destino bloqueado por defecto sin habilitar (FR-029) | 404 | `not_found_error` | «Modelo no disponible para tu organización.» (no revela el motivo) |
| Despliegue de Azure inexistente detectado en el pedido | 400 | `invalid_request_error` | `capability_rejected: destino no disponible` (el detalle va al panel, no al cliente) |

Todos los textos son marca-neutra: no nombran componentes internos ni nombres de
`deploy/release/checks/prohibited_names.txt` (FR-050).

## 8. Configuración de las herramientas (referencia del quickstart)

- **Claude Desktop (3P)**: `inferenceProvider = gateway`, `inferenceGatewayBaseUrl =
  https://<dominio>/api/v1/gw`, llave virtual, `inferenceGatewayAuthScheme = bearer` (no `sso`, deprecado
  el 7-oct-2026), descubrimiento de modelos activado (HANDOFF §2.3).
- **Claude Code**: `ANTHROPIC_BASE_URL=https://<dominio>/api/v1/gw`, `ANTHROPIC_AUTH_TOKEN=<llave>`;
  opcional `ANTHROPIC_DEFAULT_{OPUS,SONNET,HAIKU}_MODEL` con los ids publicados. Los ids publicados
  tienen que ser ids que la versión instalada de Claude Code reconozca.
