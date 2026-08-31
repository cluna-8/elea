# Research — 024 Restauración de PII y atribución en respuestas byok

**Fecha**: 2026-07-20 · **Fuente primaria**: evidencia viva del spike 019 batch 1
(`specs/019-integration-surfaces/spikes-batch1.md`) + lectura del código actual.
No quedan NEEDS CLARIFICATION: los tres defectos tienen root cause verificado.

## D1 — Unmask no-streaming: la respuesta bridged es un `dict` plano

**Evidencia** (instrumentación temporal del hook durante el spike, luego revertida):
`async_post_call_success_hook` SÍ corre y el mapping `pii_tokens` SÍ está presente
(`tokens=True`); el problema es el *shape*: `resp_type=dict`. `_unmask_response_inplace`
lee `getattr(response, "content", None)` → en un dict devuelve `None` → cae a
`getattr(response, "choices", None)` → `None` → **no-op silencioso**.

**Decisión**: extender `_unmask_response_inplace` para aceptar **ambos** shapes por campo:
objeto con atributos (ruta passthrough actual, no se toca su comportamiento) y `dict`
plano (`response.get("content")` / `response.get("choices")`), reutilizando el patrón
get/setter por-bloque que la función ya tiene para los bloques internos (líneas 166-167,
que ya contemplan dict u objeto — la asimetría está solo en el nivel raíz).

**Alternativa rechazada**: normalizar la respuesta a un objeto antes del hook — tocaría
el pipeline del motor (viola Principio VI) y arriesga alterar el payload (FR-003).

## D2 — Unmask streaming: los chunks bridged son objetos parseados, no bytes SSE

**Evidencia**: `resp_type=async_generator` con `tokens=True`; los items no-bytes/str caen
en el escape del hook («objeto ya parseado → se entrega tal cual», sentinel_guardrail.py:126-128)
y salen sin reescribir. En el wire el cliente SÍ recibe SSE Anthropic válido → algo aguas
abajo del hook re-serializa los objetos: el hook es el último punto de extensión nuestro
antes de esa serialización.

**Decisión**: en el iterator hook, tratar los items no-bytes con un **adaptador por shape**:
extraer los campos de texto delta conocidos del evento (texto, razonamiento, fragmentos
JSON de tools), aplicarles el **mismo carry-split compartido** de la lib de política
(estado de carry por campo, exactamente como hoy se hace sobre los frames SSE) y re-emitir
el item mutado. Items de shape desconocido → passthrough intacto (fail-safe, FR-005).

**Primera task de implementación (evidencia antes que código)**: instrumentación temporal
en el stack dev para capturar el TIPO y estructura exacta de los items bridged (dict vs
clase del motor, nombres de campos delta) — el adaptador se escribe contra lo observado,
no contra lo supuesto. La lección del spike (veredicto de Codex refutado por la review) se
aplica acá como método.

**Alternativa rechazada**: des-registrar el iterator hook y re-enmascarar en el gateway
(`_byok_proxy`) — duplicaría política en el gateway (anti-diseño 019: router fino) y el
mapping vive en el motor (transportarlo al gateway = acoplamiento + superficie de fuga).

## D3 — Atribución nula: la identidad se busca en un solo metadata-home

**Evidencia** (código actual, `litellm/extensions/sentinel_audit_logger.py`): la identidad se
lee de `data["metadata"]["user_api_key_metadata"]` (línea 59); pero en la ruta anthropic
los campos proxy viven en `litellm_metadata` (research T005 de la 014 — el mismo motivo
por el que `_metadata_home()` existe en el guardrail). La ironía: la línea 65 del propio
logger YA itera ambos homes para `sentinel_masked_entities`, pero no para la identidad.

**Decisión**: buscar `user_api_key_metadata` con el mismo patrón de doble home que el
archivo ya usa tres líneas más abajo. Cambio mínimo, coherente con el código existente.

## D4 — Evidencia e2e que falta (FR-007)

**Hueco confirmado**: el contract test (`backend/tests/contract/test_route_parity.py`)
cubre el round-trip DEL GATEWAY (passthrough, upstream mockeado); los checks del motor
(`litellm/extensions/integration_checks.py`) invocan los hooks a mano con shapes
fabricados — nadie asserta el round-trip por el MOTOR VIVO. Por eso este defecto llegó a
la matriz sin detectarse.

**Decisión**: nuevo e2e en `backend/tests/e2e/` (convención del archivo vecino
`test_gateway_routing_e2e.py`: stack vivo requerido, sin simulación) que ejercite byok
streaming y no-streaming con PII contra el modelo local del stack dev y asserte:
(a) el valor original vuelve al cliente, (b) el evento del feed lleva identidad y conteo
de entidades. Corre en la suite completa del DoD (stack vivo); si el stack no está, falla
explícito o se salta con marca visible — NUNCA verde por simulación (patrón del vecino).

## APÉNDICE T002 — Shapes observados (2026-07-20): D2 REFUTADA y root cause real

La instrumentación de T002 (temporal, revertida) refutó la hipótesis de D2 y afinó D1:

1. **Streaming: los items SON bytes SSE** (`builtins.bytes`, eventos completos terminados
   en `\n\n`, framing normal). El hook SÍ está en el camino del cliente (verificado con un
   marcador SSE inyectado: 157 apariciones en el wire) y el mapping correcto SÍ llega
   (mismo `data_id` y mismos placeholders en pre_call y en el iterator hook).
2. **Root cause real del streaming**: `safe_split()` de la lib compartida solo retiene un
   sufijo que matchee `PH_TAIL_RE = \[[A-Z][A-Za-z0-9_]*$` — un **`[` pelado no matchea y
   se emite ya**. El bridge de Ollama emite deltas de 1-3 caracteres → el placeholder se
   parte SIEMPRE justo tras el `[` → el `[` se suelta, el resto nunca re-forma un inicio
   de placeholder, y el placeholder entero llega crudo al cliente. **El bug es latente
   también en passthrough** (misma lib): cualquier upstream que corte un delta exactamente
   en `[` lo dispara. Fix: permitir carry de `[` solo (`\[$`) — costo: retener UN delta
   cuando termina en `[`.
3. **D1 confirmada tal cual**: la respuesta no-streaming bridged es un `dict` plano
   shape-Anthropic (`content` con bloques thinking/text) → `getattr` → no-op.
4. **Hallazgo colateral — cache del motor incompatible con masking reversible**: el cache
   Redis (`litellm_settings.cache`) sirvió la MISMA respuesta (mismo id) para requests con
   mappings distintos: la key del cache se computa sobre el prompt SIN enmascarar, y el
   valor guarda la respuesta con los placeholders del request que la pobló → el unmask del
   request siguiente jamás matchea. Aun con el fix de safe_split, un cache hit devuelve
   placeholders ajenos (sin PII — los placeholders son opacos — pero rompe el round-trip).
   Se registra como issue aparte (tensión con cache/costes → módulo 023 de Falime); NO se
   resuelve en esta spec. Mitigación de la evidencia e2e: prompts únicos por corrida.

- Gateway passthrough: round-trip ya cubierto por contract tests — sin cambios.
- Detección de ida (patrones, Presidio): spec 016, módulo seguridad.
- Ruta `/v1/responses` del motor: sin política por diseño actual, no ofrecida; su
  gobernanza es la spec de superficies de compatibilidad (issue #28).
- Pipeline/streaming del motor: cero parches al motor (Principio VI) — todo en
  `litellm/extensions/` (montadas por bind, superficie compartida CODEOWNERS de los tres).
