# Notas del tramo E2 (S14) para el HANDOFF a Sentinel (insumo de T085)

> Insumo, no el HANDOFF: lo que el tramo E2 (T096, T097, T105, T106) escribió **genérico** (sin cadenas de
> Elea/Eleia) y tiene que volver a Sentinel (`cluna-8/sentinel`); cierra su T074. T085 lo ordena en el
> formato de los HANDOFF de 053–055. Contrato de origen: `contracts/costuras-base.md` §S14; research R29.

## Base (`litellm/extensions/`, `backend/src/api/gateway.py`): una costura, retrocompatible

Sin la señal de forzado todo es igual que antes (`scope = "user"`; la batería T003 sigue verde en los dos venvs).

| Qué | Dónde | Notas |
|---|---|---|
| Señal con marca de procedencia por **tipo** | `sentinel_guardian_policy.py`: `ForcedMaskingSignal`, `mark_forced_masking`, `trusted_forced_masking`, `discard_untrusted_forced_masking` (clave `sentinel_forced_masking`) | La del cliente (dict plano) se descarta del cuerpo y de ambos `metadata`. |
| **Resolutor** del forzado | `register_forced_masking_resolver(fn)`, `resolve_forced_masking`, `clear_forced_masking_resolvers` | `fn(data, user_api_key_dict, call_type) -> bool`. El guard de la extensión corre **después** del guardrail base y no ve el grant, así que la extensión registra (al importarse en el motor) una función que verifica el token firmado; el guardrail base pone la marca. **Un resolutor que lanza cuenta como forzado** (falla cerrado). Decisión del coordinador (opción B). |
| Tabla de posiciones exentas como dato | `S14_EXEMPT_POSITIONS` (`opaque` / `structural` por formato; `…` = bloque de contenido, `@tipo`, `#schema`) | El test `test_g…` la compara con la del contrato: agregar una posición es un cambio de contrato con test. |
| Alcance completo | `mask_body(body, analyze, pmap, *, scope="user"\|"full", fmt="anthropic"\|"openai", tally=, skip_keys=)`, `extract_inspect_text(..., scope=)`, `detect_body_format` | Un solo recorrido (generadores) sirve para enmascarar e inspeccionar. Claves de objeto y escalares numéricos de los subárboles libres se analizan; booleanos y `null` no. Bajo forzado, `skip_keys` salta la metadata interna del motor y las copias de registro de la pasarela (`litellm_metadata`, `proxy_server_request`, `secret_fields`; en rutas OpenAI también `metadata`, que es el home interno y el motor no reenvía). |
| `unmask_deep` restaura **claves** | `sentinel_guardian_policy.py` | Una clave enmascarada que el modelo repite en su `tool_use` vuelve restaurada. |
| PDF en proceso hijo | `sentinel_pdf_extract.py` + `extract_pdf_text`, `pdf_config`, `reset_pdf_state` | `python -I <ruta>` (no `-m`: con `-I` el directorio de las extensiones no está en `sys.path`). `RLIMIT_AS` y `RLIMIT_CPU` = plazo + 5 s **antes** de importar `pypdf`; `pypdf.Configuration` con `MASKING_PDF_MAX_STREAM_BYTES`; entorno mínimo (sin credenciales); semáforo por proceso y bucle; plazo con kill de todo el grupo; caché por SHA-256 en memoria. |
| CUIT/CUIL sin guiones | `STRUCTURED_ID_PATTERNS_BY_REGION["latam_ar"]["CUIL"]` = `\b\d{2}-?\d{8}-?\d\b` | El paracaídas regex lo hereda (se toma con `[0]`). |
| Camino de suscripción | `backend/src/api/gateway.py`: `evaluate_request_policy(..., masking_scope=)` y su call-site | `governance_overrides["masking_scope"] = "full"` (solo ese valor) enmascara todo y **bloquea** lo no analizable: 400 con la forma de Anthropic y el texto del guard (`MASKING_REQUIRED_MESSAGE`), fila `blocked_residency` atribuida a la capa `pii_masking`. Sin el override la llamada es idéntica a la de siempre. |
| `.env.example` | `MASKING_PDF_*` (10), **comentadas** (opcionales, del motor) | Una variable real y solo leída por el motor en Python haría fallar `docs/tools/drift_gate.py` («declarada y ningún plano la consume»); cuando T081/T100 las pasen por el compose, T082 las descomenta y regenera la referencia. |

## Contrato del informe (`masking_report`, solo conteos y nombres de tipo)

`{completed, degraded, detected, masked, scope, unanalyzable, unanalyzable_kinds}` **siempre** (`scope` = `"user"` sin la señal),
más el campo opcional **`signed_thinking`** (entero) solo bajo forzado y solo si > 0:

- `signed_thinking`: cantidad de bloques `thinking` **con `signature`** cuyo texto cambió al enmascarar. **No suma a
  `unanalyzable` ni a `unanalyzable_kinds`** (hacia un traducido la extensión reconstruye la firma, R10). El guard (T061, E1) debe bloquear con
  `masking_required` solo si el destino es **nativo** y `signed_thinking > 0`.
- Bajo forzado, `detected` y `masked` son los del recorrido (por pedazo, no el preview unido): `detected == masked` solo si nada
  quedó sin reescribir; una detección en una posición estructural suma a `detected` y no a `masked`.
- Los tests existentes de S5b (`test_guardrail_masking_report.py`, `test_guardrail_redact_off_057.py`) se ajustaron a la forma nueva.

### Vocabulario de `unanalyzable_kinds` (cerrado; solo nombres)

`image`, `audio`, `document_url` (URL o `file_id`), `document` (otro tipo de documento), `unknown_block`, `redacted_thinking`,
`structural_entity`, `cache_control` (forma fuera del protocolo), `too_deep` (anidación > 100), y los de PDF:
`pdf_no_text`, `pdf_error` (corrupto, protegido o salida no cero), `pdf_resource_limit` (expansión, memoria, texto, páginas o bytes),
`pdf_timeout`, `pdf_request_limit` (tope por pedido o plazo total), `pdf_unavailable` (sin `pypdf`).
**`pdf_unavailable`, `cache_control`, `too_deep`, `unknown_block`, `document`, `document_url`, `audio` no están en `data-model.md` §5**
(que lista `image`, `pdf_no_text`, `pdf_timeout`, `pdf_resource_limit`, `pdf_error`, `structural_entity`, `redacted_thinking`, …): el coordinador
decide si se suman a la enmienda del contrato.

## Pendiente fuera de E2 (E1; acordado con el coordinador)

1. `sentinel/engine/redirect_guard.py`: registrar el resolutor del grant firmado (`policy.register_forced_masking_resolver`), `masking_ok` con
   `unanalyzable == 0` y `scope == "full"` (informe sin `scope` ⇒ bloqueo), `signed_thinking` hacia nativo (T061). **E2 no tocó ese archivo.**
2. `sentinel/redirect/plugin.py`: `governance_overrides["masking_scope"] = "full"` junto a `pii_masking`/`nlp_fail_mode` en `_subscription_posture`
   (hoy `:509`), y `masking_scope` / `unanalyzable_kinds` en `routing_decision.extensions.redirect` (data-model §5). **E2 no tocó ese archivo.**
3. `sentinel/tests/integration/test_residency_forced_masking_multiturno.py` (parte de T096 que depende del guard).

## Medición informativa de la demora (`sentinel/tests/perf/test_masking_pdf_overhead.py`; no fija presupuestos)

Con el detector regex de la base como piso del costo del recorrido (no mide el sidecar de entidades): PDF de 10 páginas ≈ 0,31 s y de 50 ≈ 0,39 s de mediana
(incluye el arranque del hijo con `pypdf`); un pedido típico de Claude Code de solo texto (60 herramientas, 24 turnos, 125 KB) ≈ 55 ms y **299 llamadas al
analizador / 93 000 caracteres**. A las 330 caracteres/s que declara `.env.example` para el analizador real, eso serían ~280 s: **riesgo de latencia/disponibilidad del
forzado completo sobre tráfico de Claude Code con el analizador real**, a confirmar en la corrida con Docker (T045/T083). El conductor ya memoriza por texto dentro del pedido y analiza
por adelantado hasta 8 cadenas a la vez (`_PREFETCH_CONCURRENCY`); si el analizador no paraleliza, la ayuda es nula.

## Riesgos y decisiones que quedan para el owner

- **Falsos positivos aceptados (fail-closed)**: con el analizador real, un id de `tool_use`, un nombre de herramienta o un `seed` que el NER/regex lea como entidad bloquea el pedido
  (`structural_entity`); T083 lo cuenta.
- `document` con `source.type = "text"` (texto plano en el cuerpo) se **enmascara como texto** aunque la tabla marque `source.data` como opaco (es texto, no base64): más estricto que el contrato.
- El texto de inspección bajo forzado (AI-Act, secretos, preview de tipos que bloquean) mantiene el tope `INSPECT_CAP` (16 000 caracteres) heredado; el enmascarado, en cambio, recorre todo.
- Verificación de Docker **sin hacer** (aviso pendiente al owner): `make -C deploy check` (incluye `check-docs`), la suite 🐳 del backend, `docs-refs` (no cambió la API; el generador de la configuración, stdlib, no produjo diff).
