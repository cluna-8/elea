# Contract: Presidio Analyzer HTTP (interfaz externa consumida)

Interfaz que este feature **consume** (no expone). Se pinnea con un contract test análogo a
`litellm/extensions/contract_checks.py` — corre contra el servicio real levantado, no contra la doc.

## Request — `POST {PRESIDIO_ANALYZER_URL}/analyze`

```json
{
  "text": "string, texto del turno user (hasta INSPECT_CAP=16000 chars)",
  "language": "es",
  "ad_hoc_recognizers": [
    {
      "name": "BASA_DNI",
      "supported_language": "es",
      "patterns": [{"name": "dni_pattern", "regex": "...", "score": 0.85}],
      "supported_entity": "DNI"
    },
    {
      "name": "BASA_CUSTOM_NAMES",
      "supported_language": "es",
      "deny_list": ["Pedro", "Cristian", "..."],
      "supported_entity": "PERSON"
    }
  ],
  "entities": null
}
```
- `entities: null` → Presidio devuelve todos los tipos que sus recognizers (built-in + ad-hoc) soportan;
  el filtrado por tipo relevante para la política se hace **después**, en `resolve_entity_action`, no acá
  (evita que el filtro server-side esconda entidades que la policy pueda necesitar más adelante).
- Timeout de cliente: **2s** (research §4). Excede esto o cualquier error de red/HTTP ⇒ tratado como
  "Analyzer no disponible".

## Response — 200 OK

```json
[
  {"start": 0, "end": 10, "entity_type": "PERSON", "score": 0.85}
]
```
Normalizado 1:1 al shape `DetectedEntity` de `data-model.md` — no requiere transformación adicional
antes de pasar a `resolve_overlaps`/`mask_text`.

## Fallas — contrato de fail-closed (FR-004, cambia el comportamiento heredado)

| Condición | Comportamiento REQUERIDO |
|---|---|
| Timeout (>2s) | `async_pre_call_hook` retorna motivo de bloqueo `nlp_unavailable` (NO devuelve `[]`) |
| HTTP 5xx / conexión rechazada | Igual — bloqueo `nlp_unavailable` |
| HTTP 200 con body inesperado (no es una lista) | Igual — tratar como falla, no como "sin entidades" |

**Contraste explícito con el código heredado a reemplazar**: `PresidioService.analyze_text_http`
(`backend/src/services/presidio_service.py`) hoy captura la excepción y hace `return []` — eso es
fail-**open** (una falla de red hoy se traduce en "no se detectó nada", la request sigue sin protección).
Este contrato lo prohíbe explícitamente para el camino del firewall real.

## Verificación (contract test, análogo a `contract_checks.py`)

Correr contra el contenedor `presidio-analyzer` real (no mockeado):
1. Health check del servicio disponible.
2. Un request con un DNI conocido vía `ad_hoc_recognizers` → confirma que el recognizer custom se
   aplica (no solo los built-in).
3. Un nombre en la `deny_list` de `custom_names` → confirma detección determinística sin depender del
   modelo NER (piso de cobertura garantizado incluso si el NER falla un caso borde).
4. Simular indisponibilidad (URL inválida / puerto cerrado) → confirma que el caller produce el motivo
   de bloqueo `nlp_unavailable`, no una lista vacía silenciosa.
