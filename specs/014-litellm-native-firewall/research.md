# Research T005 (Phase 0) — LiteLLM 1.92.0: hooks sobre `/v1/messages` y estrategia de unmask streaming

**Fecha**: 2026-07-10 · **Método**: inspección del **código real** de la imagen pinneada
(`ghcr.io/berriai/litellm@sha256:80ea654c…` = litellm **1.92.0** + litellm_enterprise 0.1.45,
corriendo en el container `sentinel-litellm`), NO de la documentación. 5 investigadores paralelos,
~156 lecturas de código. Rutas relativas a `/app/.venv/lib/python3.13/site-packages/litellm/`.
Detalle completo por pregunta: journal del workflow `wf_8e57ead4-5b7`.

> ⚠️ Nota: el build del container muestra indicios de parches propios sobre 1.92.0 upstream
> (`ModifyResponseException`, flag `strip_anthropic_total_tokens`, comentarios "VERIA-44").
> El pin por **digest** (T004) es exactamente lo que nos protege: los hechos de abajo son del
> binario que corre, y un bump se valida con los contract tests, no con la doc.

## (a) Firmas reales de los 4 puntos de extensión — CONFIRMADAS

1. **`async_pre_call_hook(self, user_api_key_dict: UserAPIKeyAuth, cache: DualCache, data: dict, call_type: CallTypesLiteral) -> Optional[Union[Exception, str, dict]]`**
   (`integrations/custom_logger.py:357`). Retornos (procesados en `proxy/utils.py:904-919`):
   `dict` → **reemplaza `data` completo** (habilita el mask del input); `str` → rechazo 400;
   `Exception` → se relanza; `None` → sin cambios. `call_type` incluye **`"anthropic_messages"`**
   (`types/utils.py:293`). Gateado por `should_run_guardrail(data, pre_call)`.
2. **`async_post_call_success_hook(self, data: dict, user_api_key_dict: UserAPIKeyAuth, response: LLMResponseTypes)`**
   (`custom_logger.py:418`). Para `/v1/messages` llega **`AnthropicMessagesResponse`**; se puede
   mutar in-place o retornar una response nueva (`proxy/utils.py:2311-2313`). Solo no-streaming.
3. **`async_post_call_streaming_iterator_hook(self, user_api_key_dict, response, request_data) -> AsyncGenerator`**
   (`custom_logger.py:449`). Recibe el iterator del stream y re-yieldea chunks. **Detección por
   `__dict__` de la clase HOJA** (`proxy/utils.py:1652-1654`): el override debe estar en la clase
   registrada, NO heredado. El mode `post_call` gatea también el streaming (`proxy/utils.py:2530`).
4. **`user_api_key_auth(request: Request, api_key: str) -> UserAPIKeyAuth`** (custom auth).
   Registro: `general_settings.custom_auth: <modulo>.<funcion>`. **Gotcha crítico**: el módulo se
   resuelve como archivo **relativo al directorio del config.yaml** (`types_utils/utils.py:38-53`),
   NO por sys.path → `extensions/custom_auth.py` debe montarse al lado de `/app/config.yaml`
   (nuestro mount `./litellm/extensions:/app/extensions` cumple). La ruta `/v1/messages` usa la
   dependency de auth estándar → custom_auth corre ahí también; el `Request` de FastAPI llega
   completo (User-Agent accesible).
5. **`CustomLogger.async_log_success_event(kwargs, response_obj, start_time, end_time)`** — sin cambios.

**Gotchas de registro** (`proxy/guardrails/guardrail_registry.py:456-540`):
- Formato config: `guardrails: - guardrail_name: …` + `litellm_params: {guardrail: modulo.Clase, mode: [pre_call, post_call], default_on: true}`; `mode` es OBLIGATORIO; los params extra de
  `litellm_params` llegan como kwargs al `__init__` del guardrail.
- **NO definir `apply_guardrail`** en la clase: si está en el `__dict__`, litellm redirige todo al
  `unified_guardrail` y NO llama los hooks nativos (`proxy/utils.py:961-970`).
- `async_moderation_hook` corre **en paralelo** al LLM call (`common_request_processing.py:1390-1418`)
  → sirve solo para bloquear, jamás para enmascarar. Confirmada la premisa del plan.

## (b) ¿Guardrails sobre `/v1/messages` nativo? — **SÍ** (FR-028 confirmada)

`proxy/anthropic_endpoints/endpoints.py:62-110`: `POST /v1/messages` entra por
`base_process_llm_request(route_type="anthropic_messages")` → **el MISMO pipeline común** que
`/chat/completions`: `pre_call_hook` → (during en paralelo) → llamada → `post_call_success_hook` /
`async_post_call_streaming_iterator_hook`. NO es passthrough a nivel proxy (el passthrough real es
`/anthropic/{endpoint:path}`, otra ruta que NO usamos).

## (c) Forma del stream en `/v1/messages` — decide la estrategia

En streaming, los chunks que atraviesan el hook son **frames SSE Anthropic crudos (`bytes`)**
(`common_request_processing.py:1574-1596` → `async_sse_data_generator` → itera el hook chain;
flag `_litellm_raw_sse_stream` en `proxy_server.py:6925`). **Nunca llega `ModelResponseStream`**
en esta ruta. Mutar/re-emitir bytes dentro del hook SÍ llega al cliente. Los deltas Anthropic
(`text_delta`/`thinking_delta`/`input_json_delta`) pasan sin normalización destructiva porque el
proxy no los re-parsea después del hook.

## Decisión: **Estrategia A′ — hook nativo + rewrite SSE de la policy compartida**

- La **Estrategia A pura** (objetos parseados `ModelResponseStream`) es **inviable** en
  `/v1/messages` 1.92.0: ese tipo no existe en esta ruta.
- La **Estrategia B pura** (reverse-proxy propio de bytes, como el demo) sigue **rechazada**:
  reintroduciría framing/transporte propio (viola Principio VI).
- **Resolución A′**: usamos el punto de extensión **nativo** (`async_post_call_streaming_iterator_hook`
  — sin parchear nada, el motor sigue siendo dueño del transporte HTTP/SSE, auth, usage, retries)
  y DENTRO del hook aplicamos `sentinel_guardian_policy.rewrite_sse_block` (carry-split + unmask sobre
  el frame SSE). El parsing SSE dentro del hook es acotado, puro y **compartido con el passthrough
  OAuth del backend** (US4), que necesita el nivel-bytes sí o sí — un solo motor de carry para las
  dos rutas (FR-029, paridad garantizada por librería única, ya implementada y testeada:
  `litellm/extensions/sentinel_guardian_policy.py`, 10/10 unit tests).
- Impacto en tasks.md: T020 se implementa con A′; el contract test T014 (guardrails sobre
  `/v1/messages`) queda confirmado por research y se blinda igualmente como test ejecutable.

## (d) Identidad — insumos confirmados para US2

- `UserAPIKeyAuth` (`proxy/_types.py:2423`) admite colgar identidad custom (metadata, user_id,
  team_id…) y **es el mismo objeto** que reciben los hooks del guardrail (`user_api_key_dict`).
- Excepción en custom_auth → 401 estándar del proxy (fail-closed disponible).
- El mapa UA→tool del demo (referencia E) se porta a `custom_auth` con la MISMA semántica de
  primer-match (orden observable: `claude` antes que `curl`, `curl` antes que `httpx`).

## (e) Comportamiento del demo a preservar (extracto operativo)

- Mask SOLO en turnos `role=="user"` (system/tools intactos); mismo valor → mismo placeholder;
  nonce de 4 hex por request; formato `[TYPE_idx_nonce]`.
- Carry-split: retener sufijo solo si matchea `\[[A-Z][A-Za-z0-9_]*$` y ≤48 chars; flush del carry
  como delta sintético ANTES de `content_block_stop`; `content_block_start` invalida carry stale;
  reescribe `text_delta`/`thinking_delta`/`input_json_delta`.
- Tabla UA→tool completa portada (claude/cursor/continue/aider/cline/roo/codex/gemini/windsurf/
  postman/curl/httpx/python-requests/node-fetch → "API directa"; sin match → "Desconocido").
- Los detalles finos (bugs de streaming resueltos en el demo) se formalizan como tests en 016.
