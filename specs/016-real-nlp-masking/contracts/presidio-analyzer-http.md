# Contract: Presidio Analyzer HTTP (interfaz externa consumida)

Interfaz que este feature **consume** (no expone). Se pinnea con un contract test análogo a
`litellm/extensions/contract_checks.py` — corre contra el servicio real levantado, no contra la doc.

## Request — `POST {NLP_ANALYZER_URL}/analyze`

```json
{
  "text": "string, texto del turno user (hasta INSPECT_CAP=16000 chars)",
  "language": "es",
  "ad_hoc_recognizers": [
    {
      "name": "SENTINEL_PASSPORT",
      "supported_language": "es",
      "patterns": [{"name": "passport_pattern", "regex": "...", "score": 0.4}],
      "supported_entity": "PASSPORT",
      "context": ["pasaporte", "passport", "reisepass", "passeport"]
    },
    {
      "name": "SENTINEL_CUSTOM_NAMES",
      "supported_language": "es",
      "deny_list": ["Pedro", "Cristian", "..."],
      "supported_entity": "PERSON"
    }
  ],
  "entities": null
}
```
- Región `"eu"` (default, `SENTINEL_ENTITY_REGION`): el único `ad_hoc_recognizer` estructurado es `PASSPORT`
  — `ES_NIF`/`ES_NIE` (DNI/NIE españoles) son reconocedores **built-in** de Presidio con validación de
  checksum para `supported_language="es"`, NO se reimplementan como ad-hoc. Región `"latam_ar"` (no
  activa por default) agrega `DNI`/`CUIL` ad-hoc, análogos al ejemplo de `PASSPORT` arriba.
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
2. Un NIF español conocido (sin `ad_hoc_recognizers`) → confirma que el built-in `ES_NIF` de Presidio
   responde para `supported_language="es"` (valida la elección de research §1, no algo nuestro).
3. Un pasaporte simulado vía `ad_hoc_recognizers` (`PASSPORT`) → confirma que el recognizer custom se
   aplica.
4. Un nombre en la `deny_list` de `custom_names` → confirma detección determinística sin depender del
   modelo NER (piso de cobertura garantizado incluso si el NER falla un caso borde).
5. Simular indisponibilidad (URL inválida / puerto cerrado) → confirma que el caller produce el motivo
   de bloqueo `nlp_unavailable`, no una lista vacía silenciosa.
