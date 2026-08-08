# Contract — Wire del proveedor simulado (stub)

El stub DEBE hablar estos protocolos exactamente como los consumen el motor y el
backend (puntos de cableado en research.md R2; file:line verificados 07-ago).

## Wire OpenAI (consumidor: motor LiteLLM — todo el tráfico que sale del motor)

- `POST /v1/chat/completions` — JSON no-stream y SSE (`stream: true`):
  chunks `data: {...}` con `choices[].delta`, cierre `data: [DONE]`. El shape no-stream
  debe incluir `choices[0].message.content` y `usage.{prompt_tokens,completion_tokens}`
  (el plano chat del backend los lee, más el header `x-litellm-response-cost` que
  agrega el motor — no el stub).
- `POST /v1/embeddings` — respuesta con `data[].{index, embedding}` ordenable por
  index; vectores deterministas por hash del input (dimensión configurable; ver open
  question del auto-router en research.md).

## Wire Anthropic (consumidor: passthrough de suscripción del backend)

- `POST /v1/messages` — JSON no-stream y SSE con la secuencia de eventos Anthropic:
  `message_start → content_block_start → content_block_delta* → content_block_stop →
  message_delta (con usage) → message_stop`. Frames BIEN FORMADOS: el gateway parsea y
  reescribe los bloques SSE (rewrite de usage) — un frame malformado rompe la medición.
- `POST /v1/messages/count_tokens` — conteo aproximado (len/4) suficiente.
- `GET /v1/models` — lista mínima verosímil.

## Comportamiento programable (por alias, vía API de control)

- `latency_ms` (tiempo al primer byte/token), `token_rate` (ritmo de emisión),
  `stream_duration_s` (rango; condiciona maxVUs del scenario coding),
  `error_rate` (tasa determinista por semilla; errores con shape del wire
  correspondiente), degradación inyectable para escenarios de fallo.
- La latencia PROGRAMADA de cada request queda registrada — es la referencia del
  overhead (FR-008: overhead = medido − programado).

## Detección de canarios (el centinela — FR-003/FR-007c)

- Inspección INLINE de los bytes crudos de cada request (antes de parsear JSON) contra
  el set de canarios del run; hit → `LeakEvidence` inmediata (run continúa, SLO c FAIL).
- Spool comprimido (zstd-JSONL) de payloads crudos por run → barrido post-run
  independiente que verifica al detector (SC-004) + forense.
- Caso borde con test obligatorio: canario PARTIDO entre chunks SSE de un request
  entrante → igualmente detectado (buffer por request, no por chunk).

## API de control (consumidor: orquestador del harness)

- `POST /control/config` (config por alias del run) · `POST /control/reset` (limpia
  contadores y set de canarios) · `POST /control/canaries` (carga el set del run) ·
  `GET /control/report` (canarios detectados con evidencia, requests por alias,
  drift de pacing p50/p95/p99, CPU propia — el auto-headroom del instrumento).
- Umbrales de invalidez del run (drift p99 >5 ms, CPU >60%) evaluados por el
  orquestador leyendo este report.

## Reglas duras

- El stub corre en la instancia del GENERADOR, jamás en el SUT.
- Coste $0: el stub no llama a nadie (sin egress).
- Todo request que el SUT le mande y no matchee un endpoint contratado → 404 ruidoso y
  contado en el report (delata cableado incompleto — nunca silencio).
