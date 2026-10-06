# Contrato — Costuras de base en Eleia (S1–S15)

Todas [BASE]: genéricas, sin marca, retrocompatibles. **Regla común**: sin extensión registrada y sin
la variable que la activa, el comportamiento es idéntico al actual y cada costura tiene su test
«sin extensión ⇒ idéntico» (FR-001, SC-002). Las de Sentinel se traen por `cherry-pick -x` (research
R1); S9, S11, S13, S14 y S15 son nuevas de Eleia y vuelven por `HANDOFF-elea-a-sentinel.md`.

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
  ids, nombres de herramienta, `media_type`, `cache_control`, `signature`, `stream`, claves de objeto).
- **PDF**: `document` con PDF en base64 (OpenAI: parte `file` con PDF) ⇒ texto con `pypdf`, enmascarado,
  reemplazado por un bloque de texto. Topes `MASKING_PDF_MAX_PAGES` (200) y `MASKING_PDF_MAX_BYTES` (20 MB).
- **No analizable** (cuenta en `unanalyzable`, con su nombre de tipo en `unanalyzable_kinds`): PDF sin texto,
  protegido, corrupto, sobre los topes o sin `pypdf` instalado; `document` por URL; `image`; audio; tipos
  desconocidos; `redacted_thinking`; `thinking` firmado con detecciones hacia un destino nativo.
- **Informe**: `masking_report = {completed, degraded, detected, masked, scope, unanalyzable, unanalyzable_kinds}`
  (`unanalyzable_kinds`: solo nombres de tipo). El guard de la
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
