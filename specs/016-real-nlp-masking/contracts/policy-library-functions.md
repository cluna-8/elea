# Contract: funciones nuevas/modificadas en `sentinel_guardian_policy.py` (librería PURA)

Interfaz interna compartida por el guardrail del motor y el backend (mismo hogar dual que el resto de
la librería — spec 014). Sin DB, sin I/O directo (el I/O del Analyzer lo hace el `AnalyzeFn` inyectado,
no esta librería).

## `resolve_overlaps(entities: list[DetectedEntity]) -> list[DetectedEntity]`

- **Pre**: `entities` puede contener rangos `[start, end)` solapados entre sí, en cualquier orden.
- **Post**: la lista resultante no contiene solapamientos; para cada **cluster transitivo** de rangos
  solapados en la entrada (A solapa B, B solapa C ⇒ los tres van al mismo cluster aunque A y C no se
  toquen directamente — clustering por barrido/merge de intervalos, no comparación par-a-par), sobrevive
  exactamente una entidad — la de mayor `(end - start)`; empate → mayor `score`; empate total → la que
  apareció primero en `entities` (estable).
- **Invariante**: `len(resultado) <= len(entities)`; ninguna entidad en el resultado tiene un rango que
  se solape con otra del resultado — **garantizado incluso con 3+ entidades solapadas en cadena**.
- Pura, determinística, sin excepciones esperadas (entrada ya validada por el caller).

## `resolve_entity_action(entity_type: str, entity_configs: dict) -> Literal["MASK", "BLOCK"]`

- **Pre**: `entity_configs` es el JSONB de `SecurityPolicy.entity_configs` (o `{}` si no hay política).
- **Post**: `entity_configs[entity_type]` si existe y es `"MASK"` o `"BLOCK"`; si no, `"MASK"` (default,
  ver `data-model.md`). Cualquier otro valor no reconocido en `entity_configs` también cae al default
  (nunca propaga un valor no válido hacia el caller).
- Pura, sin excepciones.

## `build_ad_hoc_recognizers(custom_names: list[str], region: str = "eu") -> list[dict]`

- **Pre**: `custom_names` viene de `Guardian.config.custom_names` (puede ser lista vacía); `region`
  selecciona el set de `STRUCTURED_ID_PATTERNS_BY_REGION` (default `"eu"`).
- **Post**: devuelve la lista de `ad_hoc_recognizers` en el formato que espera `/analyze` de Presidio
  (`contracts/presidio-analyzer-http.md`), incluyendo SIEMPRE los recognizers estructurados de la región
  activa (región `"eu"`: solo `PASSPORT` — `ES_NIF`/`ES_NIE` son built-in de Presidio, no se
  reimplementan; región `"latam_ar"`: `DNI`, `CUIL`, `PASSPORT`) — no dependen de `custom_names` — más
  un recognizer `deny_list` con `custom_names` solo si la lista no está vacía.
- Es la **única** función que conoce la forma de estos patrones por región — reemplaza los dos
  diccionarios `PII_PATTERNS` duplicados hoy (research §3).

## `presidio_analyze(text: str, analyzer_url: str, custom_names: list[str], region: str = "eu") -> list[DetectedEntity]` (nuevo `AnalyzeFn`)

- Implementación concreta del tipo `AnalyzeFn` ya definido en la librería (`Callable[[str], Awaitable[list]]`),
  pensada para inyectarse en `mask_body`/`mask_text` en lugar de `default_analyze` (que queda como
  fallback documentado solo para dev/demo sin Presidio levantado — nunca en el camino fail-closed real).
- **Post en éxito**: lista de `DetectedEntity` normalizada, ya pasada por `resolve_overlaps`.
- **Post en falla** (timeout/error, `contracts/presidio-analyzer-http.md`): **levanta una excepción**
  dedicada (p.ej. `NlpUnavailableError`) — NO devuelve `[]`. El caller (`SentinelGuardrail.async_pre_call_hook`)
  atrapa esa excepción puntual y la traduce al motivo de bloqueo `nlp_unavailable`; cualquier otra
  excepción no capturada sigue propagando (no se ensancha el `except` para tragarse bugs no relacionados).

## Cambio de comportamiento en `async_pre_call_hook` (`litellm/extensions/sentinel_guardrail.py`)

Contrato del hook (firma) **no cambia** (sigue pinneado por `contract_checks.py` contra la versión de
LiteLLM). Lo que cambia es el cuerpo:
1. Resuelve `entity_configs` desde la identidad (ya presente en `metadata.sentinel`, research §6).
2. Llama a `presidio_analyze` (o `default_analyze` si no hay `NLP_ANALYZER_URL` configurada — modo
  dev explícito, documentado, nunca el default de producción).
3. Ante `NlpUnavailableError` → retorna el motivo de bloqueo (mismo contrato `str` → 400/503 que ya usan
  AI-Act/secretos).
4. Preview: corre `presidio_analyze`/`default_analyze` sobre el texto completo del request y resuelve
   la acción de cada entidad vía `resolve_entity_action`. Si alguna es `BLOCK` → retorna motivo de
   bloqueo (nombra los tipos, nunca el valor) — **antes** de tocar el body, para no enmascarar
   parcialmente una request que se termina rechazando.
5. Sin bloqueos: procede a `mask_body`/`mask_text` (que vuelve a invocar el mismo `AnalyzeFn` por
   segmento) para enmascarar las entidades restantes (`MASK`) con `PlaceholderMap` como hoy.
