# Contrato — Costuras de base en Eleia (S1–S17)

Todas [BASE]: genéricas, sin marca, retrocompatibles. **Regla común**: sin extensión registrada y sin
la variable que la activa, el comportamiento es idéntico al actual y cada costura tiene su test
«sin extensión ⇒ idéntico» (FR-001, SC-002). Las de Sentinel se traen por `cherry-pick -x` (research
R1); S9, S11, S13, S14, S15, S16 y S17 son nuevas de Eleia y vuelven por `HANDOFF-elea-a-sentinel.md`.

| Costura | Activación | Contrato | Commit / origen | Test |
|---|---|---|---|---|
| **S1** routers de extensión | `PLUGIN_PACKAGES` (lista de paquetes con `router`) | `mount_plugin_routers(app)` después de todos los routers del core y de `gateway_openai`, antes de CORS; un paquete que no importa ⇒ error de arranque claro | `6161bf0` | `backend/tests/unit/test_plugin_routers.py` |
| **S2** enganches de pasarela | `GATEWAY_PLUGINS` | `pre_request` (puede responder), `pre_engine`, `wrap_stream`, `map_response` (no-stream exitoso), `models_filter` (siempre activo), `map_error`, `forward_headers_allowlist`, `post_mask`; identidad de la llave también en `models` y `count_tokens`; `ctx` llega a la auditoría | `e3a5297`, `faf94de`, `5a2d1aa`, `66dfa61`, `0669e03` | `backend/tests/unit/test_gateway_plugins.py` |
| **S2-OpenAI** | siempre montada; enganches con `GATEWAY_PLUGINS` | `POST /gw/v1/chat/completions` solo con llave del producto, `_openai_error`, 401 honesto sin llave virtual; mismos enganches S2 | `9c17500`, `efb2c94` | `backend/tests/contract/test_gateway_openai_route.py` |
| **S3** páginas del panel | `VITE_PLUGIN_PAGES_DIR` (alias `@plugin-pages`) en build | registro de páginas resuelto en build; `replaces: "<id>"` sustituye un ítem del menú base (ADAPT-026) | `f63144d`, `adb53d9`, `1d8a3b7` | `frontend/src/plugins/registry.test.ts` |
| **S4** migraciones extra | `ALEMBIC_EXTRA_VERSION_LOCATIONS` | sin variable: `upgrade head` y una cabeza; con variable: ubicaciones extra y `upgrade heads` en `main.py`, `Dockerfile`, `entrypoint/backend.sh` **y `Dockerfile.standalone`** (la imagen publicada, QA B1); con la variable, una migración fallida **aborta** el arranque (sin ella, se registra como hoy, `backend/src/main.py:40-43`) | `1021c8e` + T088 (Eleia) | `backend/tests/unit/test_alembic_extra_versions.py`, `backend/tests/unit/test_arranque_migraciones_falla.py`, `deploy/release/checks/test_standalone_heads.sh` |
| **S5b** informe de enmascarado | siempre | el guardrail deja `masking_report = {completed, degraded, detected, masked}` en la metadata interna; con S14 suma `scope`, `unanalyzable` y `unanalyzable_kinds` | `1a454ed` | `test_guardrail_masking_report.py` |
| **S6** entradas ocultas | `model_info.plugin_owner` | esas entradas no se listan, no se borran ni entran al catálogo del ruteo automático | `7a4f65c` | `backend/tests/unit/test_models_hidden_entries.py` |
| **S7** decisión de ruteo confiable | siempre | `routing_decision` del plano motor solo la escriben guardrails del motor (descarta la del cliente); espacio `extensions` acotado | `9c7bf08`, `8ceab22` | `backend/tests/unit/test_audit_routing_decision.py` |
| **S9** extensiones extra del motor | `EXTRA_ENGINE_EXTENSIONS` (rutas) | `populate_volumes.sh` y `bundle.sh` copian esos archivos al volumen de extensiones del motor junto a `litellm/extensions/*.py`; vacía ⇒ volumen y paquete idénticos | **nueva** (Sentinel T008 sin hacer) | `deploy/release/checks/test_extension_delivery.sh` |
| **S11** fragmentos de perfil | `PROFILE_FRAGMENTS` (rutas YAML) | `render_profile.sh` fusiona cada fragmento al `config.yaml` renderizado con `deploy/release/fragment_merge.py` (base, mismo contrato que el de la extensión): `model_list` y `guardrails` se agregan al final; un `model_name` o `guardrail_name` duplicado ⇒ el render falla; vacía ⇒ salida idéntica byte a byte | **nueva** (Sentinel T010 sin hacer) | idem |
| **S12** entorno extra | `EXTRA_ENV_FILE` | `env_file` opcional en `compose.prod.yml` para backend y motor | `933c513`, `891d4d0` | `deploy/release/checks/test_compose_extra_env_file.sh` |
| **Cifrado** (ADAPT-024) | `FERNET_SECRET_KEY` (+ `FERNET_PREVIOUS_KEYS`) | MultiFernet con rotación; `descifrar_estricto` falla en vez de devolver basura | `14edbc7` (2 archivos) | `backend/tests/unit/test_encryption_multifernet.py` |
| **S13** marcadores estables por conversación | `MASKING_NONCE_KEY` + metadata `sentinel_conversation_ref` | ver abajo | **nueva** (Sentinel T131 sin hacer) | `backend/tests/unit/test_masking_nonce_conversacion.py` |
| **S14** alcance completo del enmascarado forzado | metadata interna `sentinel_forced_masking` (solo la escribe la pasarela) o `governance_overrides.masking_scope = "full"` | ver abajo | **nueva** (Sentinel T074 sin hacer; QA B3) | `backend/tests/unit/test_masking_alcance_completo.py` |
| **S15** origen del canal interno | `INTERNAL_ALLOWED_CIDRS` (lista de CIDR o `auto`) | `_require_internal_secret` exige además que el par de transporte (no `X-Forwarded-For`) esté en la lista; `auto` = subredes de las interfaces del contenedor sin su puerta de enlace; vacía ⇒ sin chequeo (igual que hoy) | **dependencia**: la entrega el arreglo de separación de bases para toda instalación (QA A10); la 057 verifica las rutas de la extensión (T089) | del arreglo de bases; `sentinel/tests/unit/test_internal_rutas_extension_origen.py` (T089) |
| **S16** arranque de extensiones | `PLUGIN_PACKAGES` y un `on_startup()` opcional en el paquete | `run_plugin_startup()` de `backend/src/plugins.py`, llamado desde el `_lifespan` de `backend/src/main.py` antes del `yield`: corre el `on_startup()` de cada paquete en el orden de la variable, antes de servir; un fallo se registra y no tira el arranque; sin variable o sin `on_startup`, nada (QA v2 N1; research R33) | **nueva** (Eleia; Sentinel tiene el mismo `lifespan`) | `backend/tests/unit/test_plugin_startup.py` (contra `src.main:app` con su `lifespan` real) |
| **S17** caché de análisis por segmento | `MASKING_ANALYSIS_CACHE_*` (activa por defecto; `…_ENABLED=false` la apaga) | ver abajo | **nueva** (Eleia; research R34, decisión del owner 2026-10-06) | `backend/tests/unit/test_masking_analysis_cache.py` |

## S17 — contrato (research R34)

- **Qué guarda**: por segmento de texto analizado, solo las detecciones `(inicio, fin, tipo de entidad, puntaje)`. Jamás el texto, el valor
  detectado ni un placeholder (los placeholders los genera cada pedido con el sufijo de S13).
- **Clave**: `SHA-256(versión de configuración | idioma | empresa | texto)`. La versión de configuración es un hash de la región, los nombres y
  entidades propias de la empresa, la URL del analizador y `MASKING_ANALYSIS_CACHE_SALT`: un cambio en cualquiera da otra clave (invalida). Entre
  empresas no se comparte.
- **Variables** (todas opcionales; valor inválido ⇒ el de por defecto): `MASKING_ANALYSIS_CACHE_ENABLED` (`true`), `MASKING_ANALYSIS_CACHE_MAX_ENTRIES`
  (`20000`; LRU), `MASKING_ANALYSIS_CACHE_TTL_S` (`3600`), `MASKING_ANALYSIS_CACHE_SALT` (vacía). En proceso: se pierde al reiniciar.
- **Garantías**: el enmascarado es idéntico con y sin caché; una falla del analizador no se cachea y sube igual (fail-closed, `nlp_fail_mode`); el
  regex de respaldo del modo `degrade` no entra; sin la caché (o apagada) el comportamiento es el de siempre. Bajo forzado, el análisis previo por tipo
  corre por segmento y por esta misma caché.
- **Exenciones opcionales de S14** (apagadas por defecto): `MASKING_EXEMPT_SYSTEM_PROMPT` y `MASKING_EXEMPT_TOOL_DEFINITIONS` suman posiciones
  opacas a la tabla de S14 (`S14_EXEMPT_POSITIONS_OPTIONAL`: `system` y turnos `system`/`developer`; `tools`); el informe del enmascarado lleva `exempt`
  (solo nombres) y el guard lo copia a la decisión (`masking_exempt`). Con ambas apagadas la tabla de S14 y su test de instantánea no cambian.

**No se portan**: S10 (descartada, R13 de Sentinel), S5a `76ab37a` (cara Codex, choca con `f8118e7`),
`9fe188f` (Eleia tiene `f8118e7`), `fd515ff` (modelo «auto», después).

**Pantalla de descubrimiento** (`GET /api/v1/gw`, `backend/src/api/gateway.py:2047-2069`): deja de
nombrar el motor interno (FR-004); describe los modos con texto neutro.

## S13 — contrato

- **Entrada**: clave `sentinel_conversation_ref` en la metadata interna del pedido al motor. Solo la
  escribe la pasarela (`pre_engine` de una extensión); el valor que mande el cliente en el cuerpo o en
  cabeceras se descarta antes de llamar a los enganches.
- **Configuración**: `MASKING_NONCE_KEY` (secreto del servidor, ≥ 32 bytes, distinto de los demás).
- **Comportamiento**: con las dos presentes, `PlaceholderMap` deriva el sufijo con
  `HMAC(MASKING_NONCE_KEY, "nonce" | tenant | llave | conversation_ref)` truncado a 4 caracteres hex (el ancho de
  hoy, `litellm/extensions/sentinel_guardian_policy.py:784`) y los índices por valor con la misma
  clave; el mismo valor en la misma conversación da el mismo marcador en todos los pedidos; otra
  conversación, otra llave u otra empresa dan otro sufijo. Sin alguna de las dos: aleatorio como hoy.
- **Garantías**: el marcador no es predecible sin la clave del servidor; no se comparte entre
  conversaciones ni personas; el destino sigue viendo solo marcadores; la restauración en la respuesta
  (incluido streaming y chunks OpenAI, `f8118e7`) no cambia; la auditoría registra
  `nonce_scope = conversation | request`, nunca el valor.
- **Índice por valor**: `HMAC(HMAC(MASKING_NONCE_KEY, "idx" | tenant | llave | conversation_ref), tipo | valor | probe)`, de modo que el
  marcador de un valor no depende del orden de aparición (un dato nuevo en el turno siguiente no mueve los viejos); los componentes van
  separados por NUL. Una clave de menos de 32 caracteres cuenta como ausente.
- **Quién escribe la referencia**: el enganche `pre_engine` de la extensión; la pasarela descarta la que mande el cliente (cuerpo,
  `metadata`, `litellm_metadata`) antes de llamar a los enganches (`backend/src/api/gateway_plugins.py`). El informe del guardrail lleva
  `nonce_scope = "conversation"` solo cuando rige S13 (los informes de siempre no cambian) y el guard lo copia a la decisión.
- **Fallo**: si la derivación falla, se usa el sufijo aleatorio (la caché pierde eficacia, la
  protección no).

## S14 — contrato (QA B3; research R29)

- **Entrada**: metadata interna `sentinel_forced_masking = {"scope": "full"}` en el pedido al motor, escrita
  solo por la pasarela (`pre_engine` de una extensión; la que mande el cliente en cuerpo o cabeceras se
  descarta antes de los enganches), o `governance_overrides["masking_scope"] = "full"` en el camino de
  suscripción. Sin la señal, el guardrail se comporta como hoy (`scope = "user"`).
- **Con la señal**: enmascarado encendido y `nlp_fail_mode = block` aunque la empresa diga otra cosa; ningún
  tipo de entidad del perfil queda exento. Alcance: `system` (texto y bloques; en OpenAI, turnos
  `system`/`developer`), todos los turnos `user` y `assistant` (`text`, valores de texto de `tool_use.input`,
  `tool_result`, `thinking`; en OpenAI, `content` y `tool_calls[].function.arguments`), descripciones de
  herramientas; y, como regla general fail-closed, **todo valor de texto** del cuerpo a cualquier profundidad
  (`metadata`, `stop_sequences`, `enum`/`default`/`examples` de `input_schema`, `user`/`name` de OpenAI,
  campos desconocidos) salvo la lista cerrada de campos estructurales de research R29 (`model`, `role`, `type`,
  ids, nombres de herramienta, `media_type`, `cache_control`, `signature`, `stream`, parámetros numéricos), que
  se exime **por posición, nunca por nombre de clave** (ver «Posiciones exentas»).
- **Posiciones exentas** (QA v2 N8; research R29), lista cerrada por formato; `*` = cualquier índice. Fuera de
  estas rutas no hay exención, aunque la clave se llame `id`, `name`, `type` o `role`. `…` = un bloque de contenido a cualquier profundidad de `messages[*].content[*]` o `system[*]`, incluidos los bloques anidados en `tool_result.content[*]` (las mismas posiciones de bloque: `type`, `source.type`, `source.media_type`, `source.data`, `cache_control`); en la tabla de datos del guardrail cada ruta se escribe completa.

  | Clase | Anthropic Messages | OpenAI chat |
  |---|---|---|
  | **Opaca** (ni se analiza ni se reescribe) | `model` (el camino redirigido lo reemplaza por el del destino; analizarlo daría falsos positivos con los ids fechados: `-20250929` cumple el patrón de DNI de `latam_ar`, `litellm/extensions/sentinel_guardian_policy.py:142`); `messages[*].content[*].signature` (`thinking`); `…source.data` (base64: camino de PDF o no analizable); `system[*].cache_control`, `messages[*].content[*].cache_control`, `tools[*].cache_control` con forma validada (`type`, `ttl` del protocolo; otra forma ⇒ no analizable) | `model`; `…file.file_data`, `…image_url.url` con `data:` (camino de PDF o no analizable) |
  | **Estructural** (se analiza, no se reescribe; detección ⇒ no analizable `structural_entity` ⇒ bloqueo) | `stream`, `max_tokens`, `temperature`, `top_p`, `top_k`, `thinking.type`, `thinking.budget_tokens`, `tool_choice.type`, `tool_choice.name`, `tool_choice.disable_parallel_tool_use`; `messages[*].role`; `messages[*].content[*].type`, `.id` y `.name` de `tool_use`, `.tool_use_id` y `.is_error` de `tool_result`, `.source.type`, `.source.media_type`; `system[*].type`; `tools[*].name`, `tools[*].type`; en `tools[*].input_schema` (JSON Schema, a cualquier profundidad): las palabras clave del esquema, `type`, `format`, `$ref`, las claves de `properties` y `required[*]` | `stream`, `stream_options.*`, `max_tokens`, `max_completion_tokens`, `temperature`, `top_p`, `n`, `seed`, `presence_penalty`, `frequency_penalty`, `logprobs`, `top_logprobs`, `parallel_tool_calls`, `response_format.type`, `response_format.json_schema.name`, `tool_choice` (cadena) y `tool_choice.type`, `tool_choice.function.name`; `messages[*].role`, `messages[*].tool_call_id`, `messages[*].tool_calls[*].id`, `.type`, `.function.name`; `messages[*].content[*].type`; `tools[*].type`, `tools[*].function.name`, `tools[*].function.strict`; en `tools[*].function.parameters` y `response_format.json_schema.schema`: lo mismo que en `input_schema` |
  | **Libre** (se analiza y se enmascara todo, **claves de objeto incluidas**; los números se analizan como su texto decimal y, si hay detección, se reemplazan por el marcador como cadena; booleanos y `null` no se analizan) | todo lo demás; en particular `tool_use.input`, `metadata`, `stop_sequences`, `description`/`title`/`enum`/`const`/`default`/`examples`/`pattern` del esquema, el texto de `tool_result` y los campos desconocidos | todo lo demás; en particular `tool_calls[*].function.arguments` (parseados; si no son JSON válido, se analizan y enmascaran como texto), `user`, `messages[*].name`, `file.filename`, `metadata` y los campos desconocidos |

  La tabla vive en el guardrail como dato; un test la compara con esta tabla: agregar o quitar una posición es un
  cambio de contrato con test.
- **Vocabulario cerrado y tipos semánticos** (enmienda de N8 por decisión del owner, 2026-10-06; research R35). Con el analizador real el
  NER marca como nombre, lugar o URL cadenas del protocolo y de las herramientas, y toda detección en una posición estructural bloquea; por eso,
  **solo bajo la señal y solo en las posiciones estructurales de la tabla**:
  1. **Vocabulario cerrado** (el valor dentro del conjunto no se analiza; fuera del conjunto se analiza como antes):

     | Posición | Anthropic Messages | OpenAI chat |
     |---|---|---|
     | `messages[*].role` | `user`, `assistant` | `system`, `developer`, `user`, `assistant`, `tool`, `function` |
     | `type` de bloque (`…type`) | `text`, `image`, `document`, `tool_use`, `server_tool_use`, `tool_result`, `thinking`, `redacted_thinking`, `search_result`, `web_search_tool_result`, `web_search_result` | `text`, `refusal`, `image_url`, `input_audio`, `file` |
     | `…source.type` / `…source.media_type` | `base64`, `url`, `text`, `file`, `content` / patrón `tipo/subtipo` MIME | — |
     | `thinking.type` | `enabled`, `disabled`, `adaptive` | — |
     | `tool_choice.type` | `auto`, `any`, `tool`, `none` | `function`, `allowed_tools`, `custom` (y `tool_choice` cadena: `none`, `auto`, `required`) |
     | `tools[*].type` | `custom` o `nombre_AAAAMMDD` (herramientas del servidor) | `function`, `custom` |
     | `messages[*].tool_calls[*].type`, `response_format.type` | — | `function` / `text`, `json_object`, `json_schema` |
     | en `input_schema`, `parameters`, `json_schema.schema` | palabras clave del JSON Schema, `type` de JSON (`object`, `array`, `string`, `number`, `integer`, `boolean`, `null`) y `format` estándar | ídem |

  2. **Identificadores de vocabulario abierto** (se ignoran **solo** los tipos `PERSON`, `LOCATION`, `ORGANIZATION`, `NRP`, `URL` y
     `DATE_TIME`; cualquier otro tipo —DNI, CUIT, CBU, email, teléfono, tarjeta, IBAN, propios de la empresa, desconocidos— sigue siendo
     `structural_entity`): Anthropic: `tools[*].name`, `tool_choice.name`, `id` y `name` de `tool_use`, `tool_use_id` de `tool_result`; OpenAI:
     `tools[*].function.name`, `tool_choice.function.name`, `messages[*].tool_call_id`, `messages[*].tool_calls[*].id` y `.function.name`,
     `response_format.json_schema.name`; en los dos, las claves de `properties` (y demás mapas de nombres), `required[*]` y `$ref`/`$id`/`$anchor`.
     El descarte va **antes** de resolver solapes (una detección semántica larga no puede tapar a un patrón que va adentro).
     **Escalares numéricos** de las posiciones estructurales (`temperature`, `top_p`, `top_k`, `max_tokens`, `thinking.budget_tokens`, y los números de
     las palabras clave del esquema: `minLength`, `maxLength`, `minimum`, `maximum`, `minItems`, `maxItems`…; OpenAI: los equivalentes, `n`, `seed`…): su
     valor es de vocabulario abierto, así que rige la misma regla (enmienda de R35 por R36, 2026-10-06): se ignoran los tipos semánticos y bloquea un patrón
     (un DNI como `minLength` sigue siendo `structural_entity`). Se analizan como su texto decimal, igual que en un subárbol libre.
     **Campo `is_error` de `tool_result`** (R36): es un nombre de campo del protocolo (su valor es booleano). Sin la posición en la tabla se trataba como campo
     desconocido y su CLAVE se analizaba estricta: el NER real la marca LOCATION y bloqueaba todo turno 2 con una herramienta usada. Está en la tabla como
     estructural (la clave no se analiza; un valor que no sea booleano —un DNI— se analiza estricto y bloquea). Los campos desconocidos siguen estrictos.
  3. **Sin cambios**: texto de mensajes, `tool_result`, `thinking`, `system`, `tool_use.input`, descripciones y todo subárbol libre (se enmascaran
     también los tipos semánticos); una palabra clave de esquema fuera del vocabulario y los campos desconocidos se analizan estrictos; la clase
     de cada posición (estructural: no se reescribe) y el resto de S14.

  Las tablas viven en el guardrail como dato (`S14_CLOSED_VOCABULARY`, `S14_OPEN_IDENTIFIERS`, `STRUCTURAL_IGNORED_ENTITY_TYPES`) y un test las
  compara con esta sección (`backend/tests/unit/test_masking_vocabulario_estructural.py`): agregar o quitar un valor, una posición o un tipo es un
  cambio de contrato con test.
- **PDF**: `document` con PDF en base64 (OpenAI: parte `file` con PDF) ⇒ texto con `pypdf`, enmascarado,
  reemplazado por un bloque de texto. Topes `MASKING_PDF_MAX_PAGES` (200) y `MASKING_PDF_MAX_BYTES` (20 MB).
  **Fuera del bucle de eventos** (QA v2 N4; research R29 3b): un proceso hijo por PDF con `RLIMIT_AS` =
  `MASKING_PDF_MAX_MEMORY_MB` (512), plazo `MASKING_PDF_TIMEOUT_S` (20 s, al vencer se mata), concurrencia
  `MASKING_PDF_MAX_CONCURRENCY` (2), límites de descompresión de `pypdf.Configuration` bajados a
  `MASKING_PDF_MAX_STREAM_BYTES` (25 MB), corte en `MASKING_PDF_MAX_TEXT_CHARS` (2 000 000), por pedido a lo sumo `MASKING_PDF_MAX_PER_REQUEST` (5) PDF y plazo total `MASKING_PDF_REQUEST_DEADLINE_S` (30 s, incluye la espera), y caché en memoria por SHA-256 (`MASKING_PDF_CACHE_ENTRIES`, 32; texto o veredicto de falla, nunca persistido ni registrado); hijo: `python -I -m` de `litellm/extensions/sentinel_pdf_extract.py`, `RLIMIT_CPU` = plazo + 5 s. Nombres de tipo: tope de expansión, de memoria o de texto ⇒ `pdf_resource_limit`; plazo vencido ⇒ `pdf_timeout`; salida no cero o PDF corrupto ⇒ `pdf_error`; tope por pedido o plazo total ⇒ `pdf_request_limit`; todas opcionales,
  con esos valores por defecto.
- **No analizable** (cuenta en `unanalyzable`, con su nombre de tipo en `unanalyzable_kinds`): PDF sin texto,
  protegido, corrupto, sobre los topes, con plazo vencido, memoria agotada o expansión excesiva (`pdf_timeout`,
  `pdf_resource_limit`, `pdf_error`, `pdf_request_limit`) o sin `pypdf` instalado; una detección en una posición estructural
  (`structural_entity`); `document` por URL; `image`; audio; tipos
  desconocidos; `redacted_thinking`; `thinking` firmado con detecciones hacia un destino nativo.
- **Excepción: binarios que devuelve una herramienta** (enmienda 2026-10-07; research R39; FR-027). Una `image`, un audio o un
  documento no analizable (PDF ilegible, `document` por URL, `file` sin datos) que está **dentro de un `tool_result`** (Anthropic; en
  OpenAI, el contenido de un mensaje de rol `tool`/`function`) **no** es no analizable: el recorrido lo cambia, en el lugar, por un
  bloque de texto con una nota neutra («imagen/documento/audio omitido por la política de protección de datos: no se envía al
  modelo»; pide no insistir con capturas), conserva la marca de caché válida del bloque y lo cuenta aparte. El binario **nunca** sale
  hacia el destino. Vale en cualquier profundidad dentro del `tool_result` (`source.type = "content"` incluido). **No cambia**: un PDF
  con texto devuelto por una herramienta sigue como texto enmascarado; lo que **adjunta la persona** en su mensaje (imagen, audio,
  documento sueltos en un turno `user`) sigue siendo no analizable y bloquea; los no binarios (`redacted_thinking`, tipos
  desconocidos, `structural_entity`, `cache_control` inválido, `too_deep`) siguen bloqueando también dentro de un `tool_result`. Sin la
  señal de forzado, el cuerpo no se toca. Texto de las notas, `litellm/extensions/sentinel_guardian_policy.py:1460-1473`; la decisión,
  `_w_unanalyzable` (`:1476`) y las rutas de `tool_result` (`_w_container`, `:1633-1638`).
- **Informe**: `masking_report = {completed, degraded, detected, masked, scope, unanalyzable, unanalyzable_kinds}`
  (`unanalyzable_kinds`: solo nombres de tipo). **Campos opcionales** (solo cuando hubo reemplazos; sin ellos el informe es el de
  siempre): `unanalyzable_replaced` (entero ≥ 1) y `unanalyzable_replaced_kinds` (nombres de tipo, `[a-z0-9_]{1,32}`), de
  `litellm/extensions/sentinel_guardrail.py:740-744`; **no suman a `unanalyzable`** (el binario ya no sale) y el guard los copia
  a la decisión del pedido (`sentinel/engine/redirect_guard.py:258-271`, `:658-663`), de donde sale la auditoría
  (`unanalyzable_replaced`, solo conteo y tipos; jamás contenido). El camino de suscripción solo lo registra en el log
  (`backend/src/api/gateway.py:543-546`). El guard de la
  extensión exige, cuando el forzado rige, `completed ∧ ¬degraded ∧ detected = masked ∧ unanalyzable = 0 ∧
  scope = "full"`; si no, `masking_required` con el error de cada cara (cara Claude 400
  `invalid_request_error`, cara genérica 403; contracts/cara-claude.md §7, cara-generica.md). Un informe sin
  `scope` no pasa.
- **Restauración**: sin cambios (respuesta, streaming y chunks OpenAI, `f8118e7`).

## S15 — contrato (QA A10; research R31) — dependencia, no la implementa la 057

- `INTERNAL_ALLOWED_CIDRS` vacía: igual que hoy (solo el secreto). Con valor: el pedido a `/api/v1/internal/*`
  pasa solo si el secreto coincide **y** el par de transporte está en la lista; si no, el mismo 404 que hoy
  (`backend/src/api/internal.py:120-127`). Nunca se usa `X-Forwarded-For` para esta decisión.
- `auto`: subredes de las interfaces del contenedor (sin loopback) menos la dirección de la puerta de enlace
  de cada una (por donde entra lo publicado desde el host).
- Aplica a toda ruta que use `_require_internal_secret`, incluidas las de la extensión (`/model-catalog`,
  `/model-access`, `/model-credential`). Además, la extensión responde 404 en `/model-credential` salvo
  `CATALOG_DIRECT_ENABLED` (T090).
