# Contract — Corpus PII español compartido (dataset etiquetado)

**Versión del contrato**: 1.0.0-draft (a review del core en #107) · **Consumidores**:
(1) harness ITV — mezclas de tráfico de los gates; (2) runner de precision/recall del
core (#107) contra la imagen real de sentinel-nlp. Los **canarios de carga NO viven aquí**
(runtime-only por run, capa aparte — FR-004).

## Formato de archivo

JSONL, UTF-8 **sin BOM**, texto normalizado **NFC**, una doc por línea:

```json
{
  "id": "piloto-63-iban-01",
  "text": "Le paso el IBAN ES91 2100 0418 4502 0005 1332 para la factura FAC-2026-001587",
  "entities": [
    {"entity_type": "IBAN_CODE", "start": 16, "end": 45, "value": "ES91 2100 0418 4502 0005 1332"}
  ],
  "forbidden": [
    {"entity_type": "PHONE_NUMBER", "start": 62, "end": 77}
  ],
  "source": "regression-63",
  "difficulty": "medium",
  "lang": "es",
  "region": "eu"
}
```

## Reglas normativas

1. **`entity_type`** (clave adoptada del core — la que emite el detector, cero mapeo):
   enum CERRADO del **baseline** (config default eu, SIN custom) = `PERSON`,
   `EMAIL_ADDRESS`, `PHONE_NUMBER`, `IBAN_CODE`, `CREDIT_CARD`, `ES_NIF`, `ES_NIE`,
   `PASSPORT`, `LOCATION`, `DATE_TIME`. **Tipo desconocido = ERROR de validación**, no
   advertencia. *Aclaración 08-ago (verificado en el código, señalado al core en #107)*:
   los `SENTINEL_*` que mencionó el core son `SENTINEL_CUSTOM_NAMES` / `SENTINEL_CUSTOM_<tipo>`
   (`sentinel_guardian_policy.py:259,268`) — entidades **custom por instalación**
   (`custom_names`/`custom_entities`), que el baseline excluye por definición (regla 6).
   No van en el dataset baseline; si se cubren deny-lists custom, es la sección opcional
   aparte y ESE enum se amplía con los `SENTINEL_CUSTOM_*` correspondientes.
2. **Spans**: offsets de **caracteres Unicode (codepoints)** sobre el `text` NFC, end
   **exclusivo** `[start, end)`, **ajustados** (sin espacios ni puntuación colgantes —
   el scoring exact-span no debe regalar slack). Jamás bytes.
   **Scoring dual (decidido con el core, 08-ago — vive en el runner #107, NO en el
   dataset)**: los tipos **estructurados** (ES_NIF, ES_NIE, IBAN_CODE, CREDIT_CARD,
   PASSPORT, PHONE_NUMBER) tienen frontera canónica + checksum → **match EXACTO de
   span**. Los tipos **NER** (PERSON, LOCATION, DATE_TIME) tienen frontera difusa y sus
   spans están etiquetados a **granularidad de autor** → el consumidor DEBE puntuarlos
   con **type-match + solape de span (IoU ≥ 0.5)**, no exact-span (exigir exact-span
   mediría ruido de tokenización, no detección). Los labels NER se quedan honestos como
   verdad-terreno: **jamás se calibran contra el modelo** (sería circular — el recall
   dejaría de significar nada). La tolerancia de frontera NER vive en el scorer.
3. **`value` obligatorio en `entities`** y checksum del validador:
   `value == text[start:end]` (post-NFC) o el corpus está roto. En `forbidden` el
   `value` es opcional (mismo checksum si está presente).
4. **Negativos, dos clases obligatorias en el dataset**:
   - `forbidden`: hard negatives por tipo — spans que NO deben detectarse como ese
     `entity_type` (ej. canónico: `FAC-2026-*` con forbidden `PHONE_NUMBER` = la
     regresión literal del #63);
   - **docs limpios**: registros con `entities: []` y sin PII alguna (tasa de falsos
     positivos global).
5. **`source`**: `generated` | `regression-63` | `handmade` · **`difficulty`**:
   `easy` | `medium` | `hard` · `lang`: `es` · `region`: `eu`. (Top-level, según el
   mensaje del core del 08-ago que supersede el `meta{}` del sketch del #107 — si el
   runner prefiere `meta{}`, es un cambio mecánico: decidir en la review.)
6. **Baseline reproducible**: el corpus asume **config DEFAULT región `eu`**, SIN
   `custom_names` ni `custom_entities` de instalación, y SIN umbrales de score
   (el runner mide con la config real del producto). Deny-lists de cliente: sección
   aparte y opcional, jamás en el baseline.
7. **Versionado**: `harness/corpus/dataset-v<semver>.jsonl` + `manifest.json`
   (`version`, `sha256` del contenido, `generator_version`, `seed`, conteos por
   `entity_type`/`source`/`difficulty`). El reporte del runner del core y el
   fingerprint de los runs ITV citan `version + sha256 + seed` — un número de
   precision/recall sin corpus pinneado no es comparable.
8. **Validador** (`harness/src/sentinel_harness/corpus/validate.py`, corre en pytest y en el
   job `harness-tests`): enum de tipos, spans dentro de rango y sin duplicados exactos,
   checksum de `value`, normalización NFC verificada, docs limpios presentes,
   regresiones del #63 presentes. El dataset no se versiona sin validador en verde.
9. **Prohibido en el corpus**: datos reales de cualquier persona o cliente (100%
   sintético o casos del piloto ya anonimizados en #63) y patrones regex hostiles
   (#106 — ese camino se examina solo deliberadamente, fuera de gates).
