# Notas del tramo T-F (caché del proveedor, S13 y S17) para el HANDOFF a Sentinel (insumo de T085)

> Insumo, no el HANDOFF: lo que el tramo T-F escribió **genérico** (sin cadenas de Elea/Eleia) y tiene que volver a Sentinel
> (`cluna-8/sentinel`). Cierra sus T126/T131/T132 (S13) y suma S17 (caché de análisis, decisión del owner del 2026-10-06,
> research R34). Cambia comportamiento de la base de Sentinel en los puntos marcados «⚠ cambia». Fuera de este archivo: el porte de
> Sentinel F1 (`c974dc5`, `6ca0419`) entró por `cherry-pick -x` (T107) y no vuelve.

## Base (`litellm/extensions/`, `backend/src/api/`): costuras, todas retrocompatibles

Sin ninguna variable nueva definida y sin la señal de forzado, todo es igual que antes (batería T003 verde).

| Qué | Dónde | Notas |
|---|---|---|
| **S13** marcadores estables por conversación | `sentinel_guardian_policy.py`: `PlaceholderMap.for_conversation`, `new_placeholder_map`, `NONCE_KEY_ENV`; `sentinel_guardrail.py` (creación del mapa) | Con `MASKING_NONCE_KEY` (≥ 32 caracteres) y `sentinel_conversation_ref` en la metadata interna: sufijo `HMAC(k, "nonce"∣empresa∣llave∣ref)[:4]` e **índice por valor** `HMAC(HMAC(k, "idx"∣…), tipo∣valor∣probe)` (no depende del orden de aparición: un dato nuevo en el turno siguiente no mueve los marcadores viejos). Sin alguna de las dos, o si la derivación falla, aleatorio como siempre. La gramática `[TIPO_n_xxxx]` y la restauración (SSE, chunks OpenAI) no cambian. El informe lleva `nonce_scope = "conversation"` **solo cuando rige S13**: los informes de siempre no cambian. |
| Referencia de conversación: lo escribe solo la pasarela | `backend/src/api/gateway_plugins.py` (`run_pre_engine`) | Descarta `sentinel_conversation_ref` del cuerpo y de `metadata`/`litellm_metadata` **antes** de llamar a los enganches `pre_engine`; el enganche escribe el suyo. Nota de confianza: el motor solo lo recibe de la pasarela (único cliente suyo); no hay marca por tipo como en S14 porque el valor viaja por HTTP. |
| **S17** caché de análisis por segmento | `sentinel_guardian_policy.py`: `AnalysisCache`, `cached_analyze`, `analysis_cache_config`, `analysis_config_version`, `analysis_key`, `get_analysis_cache`, `reset_analysis_cache`, `analyze_segments`, `inspect_segments`; `sentinel_guardrail.py` (el analizador real pasa por la caché) | Guarda **solo** `(inicio, fin, tipo, puntaje)`; clave `SHA-256(versión∣idioma∣empresa∣texto)`; versión = hash de reconocedores + nombres/entidades propias + región + URL + `MASKING_ANALYSIS_CACHE_SALT`; LRU por entradas + TTL, en proceso; una falla del analizador no se cachea; el regex de `degrade` no entra; >1 000 detecciones no se cachea. Equivalencia con y sin caché probada. Variables: `MASKING_ANALYSIS_CACHE_{ENABLED,MAX_ENTRIES,TTL_S,SALT}`. ⚠ **cambia**: bajo forzado el análisis previo por tipo (BLOCK vs MASK) corre **por segmento** (los mismos que recorre el enmascarado) y no sobre el texto unido y recortado a `INSPECT_CAP`; AI-Act y secretos siguen mirando el texto unido (con su tope). |
| Exenciones opcionales de S14 (apagadas) | `sentinel_guardian_policy.py`: `S14_EXEMPT_POSITIONS_OPTIONAL`, `optional_exemptions`; `sentinel_guardrail.py` | `MASKING_EXEMPT_SYSTEM_PROMPT` y `MASKING_EXEMPT_TOOL_DEFINITIONS` (por defecto `false`): posiciones **opacas** (`system` y turnos `system`/`developer`; `tools`/`functions`). Solo las enciende la instalación; el informe lleva `exempt` (nombres) solo si hay alguna. Secretos y AI-Act siguen mirando todo. Trade-off en research R34: con la caché la exención solo ahorra el primer análisis de cada texto. |
| La fila del no-stream después de `map_response` | `backend/src/api/gateway.py` (camino no-stream de `/v1/messages`, suscripción/passthrough) | ⚠ **cambia** (autorizado por el coordinador): `_audit(...)` corre **después** de `map_response`/`map_error` y en un `try/finally`; si el enganche lanza, la fila sale igual con la decisión que haya y estado `upstream_error`. Sin plugins la fila es la de siempre (test). Permite que un plugin sume lo que lee de la respuesta (tokens de caché) a su `routing_decision`. |
| `.env.example` | `MASKING_NONCE_KEY`, `MASKING_ANALYSIS_CACHE_*`, `MASKING_EXEMPT_*` | **Comentadas** (opcionales, solo del motor y de la pasarela de la extensión): una variable real que solo lee el motor en Python haría fallar `docs/tools/drift_gate.py`. Cuando T081/T100 las pasen por el compose, T082 las descomenta y regenera la referencia (`docs/gen_config_reference.py` hoy no produce diff y el gate de deriva da PASS). |
| `MASKING_NONCE_KEY` protegida | `sentinel/engine/redirect_credentials.py` (`ENV_DENYLIST` y el fragmento `NONCE_KEY`), `deploy/release/gen_secrets.sh` (`rand_hex 32`), `deploy/release/checks/test_no_default_secrets.sh` | La clave no se puede referenciar como credencial de un modelo; el release la genera distinta por instalación; ningún artefacto versionado la trae con valor literal o `${…:-valor}`; el que activa la extensión (`GATEWAY_PLUGINS`) la tiene que declarar. `sentinel/extensions.env.example` la declara como `<generar>` y `sentinel/docker/compose.dev.yml` la pasa a backend y motor sin valor por defecto. **En el instalador la genera T100** (y tiene que pasarla al backend **y** al motor). |

## Extensión `sentinel/`

- **Alineación E1↔E2 del forzado (T108)**: el guard lee `masking_report.signed_thinking` (era el provisional `signed_thinking_detections`) y **registra el
  resolutor de forzado al importarse** y al instanciarse (`register_forced_masking_resolver`, en las dos copias del módulo de política que pueden convivir
  en el motor: `extensions.sentinel_guardian_policy` y el plano). Sin esto todo pedido forzado se bloqueaba con `masking_required`.
- **Referencia y afinidad** (`sentinel/redirect/session_ids.py`, `plugin.pre_engine`): `conv = HMAC(k, "conv"∣empresa∣sesión)` y
  `affinity = HMAC(k, "affinity"∣empresa∣sesión∣agente)`; sesión = `x-claude-code-session-id` o `…_session_<id>` del `user_id` de `metadata`; sin clave o
  sin sesión, nada. La afinidad va **firmada** en la autorización (`Grant.affinity`) y solo si el destino declara `session_affinity` (OpenRouter la tiene
  por defecto; `FEATURES` del catálogo la suma). El guard la manda como `session_id` en el cuerpo de OpenRouter y como `x-session-id` en los demás; el que manda
  el cliente se descarta.
- **Marcas de caché** (`faces/claude.py`): ya se conservaban cuando el destino declara `cache_control`; ahora la marca de un bloque reemplazado por una nota
  (imagen o PDF sin soporte) pasa a la nota.
- **Precio de caché** (`redirect_credentials.py`): `cache_read_per_mtok` / `cache_write_per_mtok` opcionales en el precio; `cost_params` fija
  `cache_read_input_token_cost` y `cache_creation_input_token_cost` (los nombres que honra `completion_cost`: test con la versión instalada); `price_per_mtok` es
  la **única** conversión (guard por catálogo, chat de la consola y destino firmado); `price_cache_missing` en la decisión cuando se cobra a precio de entrada;
  el cliente no puede fijar ningún costo.
- **Tokens de caché en la auditoría** (`plugin.map_response` y `wrap_stream` con `stream.wrap_sse(usage_sink=…)`): `cache_read_tokens` / `cache_write_tokens` en
  `routing_decision.extensions.redirect` (Claude, chat OpenAI/OpenRouter y Responses). `nonce_scope` (`conversation` | `request`) y `session_affinity` también.
  `costs.compare` suma por destino lecturas, escrituras, entrada total y `cache_hit_rate` (el formato Anthropic suma la caché a la entrada; el de OpenAI ya la incluye).
- **Panel** (`sentinel/frontend/redirect/DestinationsTab.tsx`): casillas «Marcas de caché» y «Afinidad de sesión» (fusionan con el perfil que ya tiene el destino), precio
  de lectura y escritura de caché y aprovechamiento a demanda (botón; no suma una llamada a los costos al abrir la pestaña).
- **Caché de respuestas del motor** (T071): el `namespace` y el salto de caché con mapa de enmascarado ya cubrían FR-048; el test lo fija con la caché real de `litellm`.

## ⚠ Limitaciones y pendientes

1. **Tokens de caché de las filas del camino byok** (Claude Code con la llave de la pasarela): las escribe el logger de auditoría del motor con la decisión que el guard fijó
   **antes** de la respuesta; el logger no se tocó (decisión A del coordinador). Esas filas **no** llevan `cache_read_tokens`/`cache_write_tokens`; las del camino de
   suscripción (no-stream y stream) sí. Seguimiento posible: que el logger sume `usage.cache_*` a la decisión de confianza (cambio de base chico, a decidir con Sentinel).
2. **Sin verificar en vivo** (🐳/Azure, T066 y T078): el efecto real de la afinidad (`session_id`/`x-session-id`) y de las marcas de caché sobre los aciertos del proveedor; que el
   motor fijado honre `cache_read_input_token_cost` por pedido en `litellm_params` (verificado con `completion_cost` de la versión instalada, no con el motor en vivo); SC-011 y SC-012.
3. **El identificador original de la sesión nunca llega al motor ni al destino**: la pasarela lo lee de sus cabeceras de entrada y reenvía solo lo derivado.
4. **Cifra real de la demora**: la medición local (`sentinel/tests/perf/test_masking_cache_turno2.py`) usa el analizador simulado; con el real, la tomará la corrida con Docker (T045/T083).
5. Docker **sin correr** (aviso pendiente al owner): `make -C deploy check` (incluye `check-docs`), `docs-refs`, la suite 🐳 del backend, T066, T078.

## Insumo para la documentación (T079/T080/T081/T082)

La página `docs/docs/integrations/redireccionamiento.md` **no existe todavía en Eleia** (la crea T079): el hunk del porte F1 sobre ella no se trajo y T079 tiene que incorporar su
contenido: el puente chat+herramientas+razonamiento → Responses hacia OpenAI/Azure (conserva el `reasoning_effort` del cliente, incluido `none`) y `context_length`/`max_output` en
`/gw/v1/models` genérico. Estado honesto para la leyenda:

- 🟢 (código y test local): marcadores estables por conversación (S13); caché de análisis (S17) y su medición (turno 2: 8 llamadas / 2 460 caracteres frente a 299 / 93 487 del
  turno 1 en frío; 97 % menos); exenciones opcionales apagadas; precio de lectura y escritura de caché y `price_cache_missing`; marcas de caché conservadas.
- 🟡 (falta la verificación con un destino real): afinidad de sesión por proveedor; costo con tokens de caché en el motor en vivo; aprovechamiento ≥ 60 % desde el 2.º paso (SC-011).
- 🔵 (no está cableado): tokens de caché en las filas byok (ver arriba).
- Texto de producto: «seudonimización reversible»; con el forzado vigente el análisis es de **alcance completo** y la caché solo evita repetir el análisis del mismo texto; las dos exenciones
  existen, están **apagadas** y encenderlas es una decisión explícita de la instalación (queda registrada en la auditoría con el nombre de lo exento).
- Variables nuevas (T082): `MASKING_NONCE_KEY`, `MASKING_ANALYSIS_CACHE_{ENABLED,MAX_ENTRIES,TTL_S,SALT}`, `MASKING_EXEMPT_{SYSTEM_PROMPT,TOOL_DEFINITIONS}` — hoy comentadas en `.env.example`.
