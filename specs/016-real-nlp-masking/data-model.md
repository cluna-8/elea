# Data Model — 016 Real NLP Masking & Entity Detection Hardening

No introduce tablas nuevas. Consume el schema existente (013/014) y precisa cómo cambian los
**contratos en memoria** que ya existían como `dict` sueltos.

## Entidades existentes reutilizadas (sin cambio de schema)

### SecurityPolicy (`backend/src/models/policy.py`)
- `entity_configs: JSONB` — **cambia de rol**: pasa de "informativo, editable pero sin efecto en tráfico
  real" a **fuente de verdad consultada por request** en el firewall (research §6).
- Sigue siendo la política **global activa única** (`is_active=True`); la cascada por scope es 015.
- **Default para tipos ausentes**: `MASK` (research §6) — se documenta acá porque es un comportamiento
  observable del dato, no solo del código.

### Guardian (`backend/src/models/guardian.py`), `guardian_type="pii_masking"`
- `config.custom_names: list[str]` — **cambia de rol**: pasa de alimentar solo el camino legacy
  (`guardian_service.py`) a construir la deny-list `ad_hoc_recognizers` que viaja en cada `/analyze`
  del firewall real (research §3). Sin cambio de shape.

### APIKey / Connection (013, `backend/src/models/budget.py`)
- `redact_enabled: bool | null` — sin cambios; sigue siendo el toggle on/off de masking a nivel
  Connection. Esta feature no lo reemplaza, opera dentro de él (si `redact_enabled=False`, no se llama
  ni al Analyzer ni se evalúa `entity_configs`, igual que hoy).

## Contratos en memoria nuevos/modificados (no-DB, viven en `sentinel_guardian_policy.py`)

### `DetectedEntity` (shape ya implícito, ahora formalizado)
```
{
  "start": int,          # offset en el texto analizado
  "end": int,             # offset exclusivo
  "entity_type": str,     # p.ej. "PERSON", "ES_NIF", "ES_NIE", "PASSPORT", "EMAIL_ADDRESS", "IBAN_CODE"
  "score": float,         # 0.0–1.0; ya no siempre 0.95 fijo — el Analyzer real devuelve confianza real
}
```
Fuente: respuesta de Presidio Analyzer (`/analyze`) normalizada al mismo shape que usaban los
detectores regex, para no romper `mask_text`/`PlaceholderMap` (research §1, "el Anonymizer no se usa").

### `EntityAction` (nuevo, resultado de resolver `entity_configs`)
```
entity_type: str -> "MASK" | "BLOCK"
```
Resuelto por una función pura (`resolve_entity_action(entity_type, entity_configs) -> Literal["MASK","BLOCK"]`)
con default `MASK` (ver arriba). Consumida por `SentinelGuardrail.async_pre_call_hook` antes de decidir si
una entidad corta la request o se enmascara.

### `AdHocRecognizerSet` (nuevo)
Estructura que viaja en el body de `/analyze` (formato definido por la API de Presidio, no propio):
patrones regex con nombre **solo para lo que Presidio no cubre ya con un reconocedor built-in propio del
idioma activo** (región `"eu"`: únicamente `PASSPORT`, con palabras de contexto — `ES_NIF`/`ES_NIE` son
built-in de Presidio, no se reimplementan) + deny-list de `custom_names`. Se construye en una única
función (`build_ad_hoc_recognizers(custom_names: list[str], region: str) -> list[dict]`), parametrizada
por región (`STRUCTURED_ID_PATTERNS_BY_REGION`: `"eu"` activa por default; `"latam_ar"` con DNI/CUIL
preparada para despliegues futuros en esa región).

### Relación con `PlaceholderMap` (sin cambios de shape, cambia el input)
`PlaceholderMap`/`mask_text`/`unmask_text` (ya existentes) siguen operando igual; lo único que cambia
es de dónde vienen las `DetectedEntity` que reciben (antes: regex local; ahora: Presidio Analyzer +
ad-hoc recognizers, pasadas por `resolve_overlaps()` primero).

## Nueva función pura: `resolve_overlaps`

```
resolve_overlaps(entities: list[DetectedEntity]) -> list[DetectedEntity]
```
Determinística, sin estado, sin I/O — vive junto a `mask_text` en `sentinel_guardian_policy.py` (research §5).
Invariante: la lista de salida nunca contiene dos entidades cuyos rangos `[start, end)` se solapen.

## Auditoría (sin cambio de schema, nuevo motivo registrable)

`AuditLog`/`sentinel_audit_logger.py` ya soportan `sentinel_compliance`/motivo de bloqueo (spec 014). Esta
feature agrega dos motivos nuevos al vocabulario existente (no requiere columna nueva, es texto/JSON
metadata-only):
- `blocked_entity_type` — bloqueo por `entity_configs[type] == "BLOCK"` (FR-006).
- `nlp_unavailable` — bloqueo por fail-closed del Analyzer (FR-004).

Ambos motivos son metadata (tipo, no valor) — cumplen Constraint C1 sin cambios adicionales.
