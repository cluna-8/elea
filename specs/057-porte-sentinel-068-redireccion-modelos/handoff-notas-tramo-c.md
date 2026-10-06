# Notas del tramo T-C para el HANDOFF a Sentinel (insumo de T085)

> Insumo, no el HANDOFF: lo que el tramo T-C escribió **genérico** (sin cadenas de Elea/Eleia) y tiene que
> volver a Sentinel (`cluna-8/sentinel`). T085 lo ordena en el formato de los HANDOFF de 053–055. Los ids de
> tarea «de Sentinel» son los de su 068/069.

## Base (`backend/`): una costura, retrocompatible

| Qué | Dónde | Por qué | Prueba |
|---|---|---|---|
| `GatewayContext.body` (opcional, `None`) y lectura del cuerpo de `count_tokens` en `_plain_passthrough`, **solo con plugins y en POST**; `ctx.model` saneado con `sanear_modelo_declarado` | `backend/src/api/gateway_plugins.py`, `backend/src/api/gateway.py` | La costura S2 ya dejaba responder `count_tokens` desde `pre_request`, pero el plugin no veía ni el modelo ni el cuerpo (Sentinel `main` igual): sin esto T093 de Sentinel no se puede hacer | `backend/tests/unit/test_gateway_plugins.py` (7 nuevos), batería T003 (`test_gw_no_regresion_057.py`) sin cambios |

`contracts/costuras-base.md` (fila S2) debería sumar «cuerpo de `count_tokens`» cuando se enmiende.

## Extensión (`sentinel/`): todo genérico

- **T139 de Sentinel** — lista permitida de campos de primer nivel hacia traducidos (`FIELD_ALLOWLIST`,
  `dropped_field_names` en `faces/claude.py`; `dropped_fields` en la decisión, acotado a 128 caracteres).
- **T094 de Sentinel** — `redirect/betas.py` (default acotado + `REDIRECT_BETA_ALLOWLIST`; en blanco = default,
  `none` = ninguna), `_apply_betas` en `pre_engine` (decide con el destino final) y `_subscription_foreign`
  (FR-042, 401 neutro). La edición desde el panel quedó fuera (decisión del coordinador).
- **T093 de Sentinel** — `redirect/token_estimate.py` (`cl100k_base` solo con vocabulario en disco y hash
  verificado; si no, `caracteres/4`; nunca red) y `_count_tokens` en el plugin (traducido o forzado ⇒ estimado
  o 404; nativo sin forzado ⇒ reenvío con el id `rdx-*`). El conteo escribe su propia fila (la pasarela no
  audita las respuestas tempranas de `count_tokens`) con `count_tokens_mode`.
- **T091 de Sentinel** — `stream.py`: `usage` con los cuatro contadores en `message_start` (y `message_delta` sin
  ceros que pisen al inicio: el SDK acumula), falla del destino o `event: error` ajeno ⇒ `event: error` neutro y
  cierre sin `message_stop`. Cambia un test heredado: la falla a mitad del stream ya no propaga en la cara Claude
  (sigue propagando en la genérica).
- **T090 de Sentinel** — `redirect/thinking.py`: firma HMAC atada al **destino** y al texto (clave derivada de la
  de la autorización con otro dominio), `ThinkingSigner` en el stream, firma en el no-stream, reconstrucción en el
  turno siguiente solo para el destino que lo exige (`provider_options.reasoning_replay` o proveedor `deepseek`) y
  descarte sin rastros del resto. La firma atada al destino es una precisión sobre D7 de la 068 (ahí era «sobre el
  texto»): así el razonamiento de un destino nunca llega a otro.
- **US1 esc. 4 / FR-015 / FR-018** — un id `claude-*` no publicado cae a la regla por tier inferido de su nombre
  (`infer_tier`), solo con política `on` y llave del producto; sin regla ⇒ 404 neutro. Los ids de la base y la
  suscripción personal siguen su camino. Sentinel lo tenía en el data-model (`family_tier`: «para ids no
  publicados que caen por tier») pero no en el plugin.
- **FR-035** — herramientas del servidor del proveedor original (`web_search*`, `web_fetch*`, `code_execution*`)
  hacia un traducido ⇒ 400 `capability_rejected: …`, nunca ignoradas.
- **Defecto latente corregido** — `_select_by_capability` reasignaba `plan.decision` tras una sustitución por
  capacidad y la auditoría de la pasarela dejaba de ver `omitted`, `dropped_fields`, etc. (ahora actualiza en el
  lugar).

## Tests que viajan

`sentinel/tests/fixtures/harness_corpus/claude/**` y `corpus_claude.py` (corpus sintético), `gw_harness.py`
(pasarela real + motor falso), `unit/test_face_claude_{campos_desconocidos,betas,razonamiento,corpus}.py`,
`contract/test_face_claude_{count_tokens,contract}.py`, `integration/test_face_claude_stream.py`,
`unit/test_guard_azure_parametros.py` y `perf/test_redirect_overhead.py`.

## Pendiente que no es de este tramo (para el gate y T-E)

- Validar en vivo (T045): que el motor entregue el bloque `thinking` reconstruido como `reasoning_content` al
  destino que lo exige, la lista real de betas de Claude Code y el 404 de `?beta=true` con Azure.
- La API de administración (`sentinel/redirect/api/admin.py`, T-E) no valida que un id publicado en la cara Claude
  empiece con `claude`: Claude Code descarta del lado del cliente lo que no reconoce (`unrecognized_model`), así que
  un id como `gpt-5.4-mini` publicado ahí no lo usará esa herramienta. Conviene un 422 con texto claro.
- `count_tokens` en el camino de postura sin redirección (US2) y el alcance completo del forzado (S14): T062.
- `REDIRECT_BETA_ALLOWLIST` está documentada en `sentinel/README.md`; si T-G la quiere en el sitio de producto,
  hay que declararla donde la base la consuma (el gate de deriva rechaza una variable que solo lee la extensión).
