# Data Model — 018 (cero migraciones: todo opera sobre esquema existente)

## Clase de retención (existente: `retention_policies`, seed 004:100-109)

| Campo | Estado | Notas |
|---|---|---|
| `log_type` (UNIQUE global) | sin cambios | FR-010: partición `(tenant_id, log_type)` diferida con nombre |
| `retention_days` | sin cambios | validación de rango pasa al backend (FR-007): mínimos por clase + pisos/topes por tier (tabla en research.md D7) |
| `purge_log` (JSONB) | **estrena escritores** | ver «Corrida de purga» |

Las 4 clases y su predicado sobre `audit_logs` viven en el **clasificador** (contrato 1 en `contracts/`), no en el esquema.

## Corrida de purga (sin tabla nueva)

Representación doble, ambas metadata-only:

1. **Entrada en `purge_log`** (JSONB de su clase, capado a las últimas 50 corridas):
   `{run_id, started_at, finished_at, cutoff, rows_deleted, batches, window, result: ok|partial|error}`
2. **Fila resumen en `audit_logs`** clase `config_audit` (mismos campos como metadata) — entra al canal de evidencia estándar del DPO y muere a los 730 d como cualquier config_audit.

Idempotencia: el predicado es «vencida al momento de la corrida» contra el reloj de la DB — una corrida interrumpida que se relanza no duplica el efecto (las borradas ya no están) y no salta filas (las vencidas siguen matcheando). El `purge_log` registra `result: partial` para la interrumpida.

## Tier de enforcement (existente: `governance_profiles`, migración 012)

- Capa nueva **solo en código**: `enforcement_tier_estricto`, decision `on`/`off` (CHECK existente respetado; `layer_key` sin FK/CHECK por diseño 027).
- `on` = tier `estricto` · `off`/ausente = `estándar` (default de fábrica).
- Cambio de tier = cambio de configuración auditado (SC-006), con valor anterior y nuevo.
- Consumidores: solo backend (validación FR-007, aserción `BASA_AUDIT_FAIL`, consecuencias con grado). El resolutor del motor la ignora (capa desconocida para él, comportamiento 027 verificado).

## Mutaciones sobre datos existentes

| Objeto | Operación | Regla |
|---|---|---|
| `audit_logs` filas vencidas de clases purgables | DELETE por lotes | jamás filas `model='license'` (FR-003, estructural en el clasificador) |
| `human_reviews.response_text` vencido (plazo `prompt_content`) | UPDATE → NULL | la fila de review persiste; `audit_log_id` huérfano lógico documentado |
| `licensing/audit_events.py` emisor | refactor de identidad | `SessionLocal` pelado → `tenant_context(bypass=True)` (FR-006) |

## Estados y transiciones

Fila de auditoría: `viva → vencida (edad > plazo de su clase, reloj DB) → purgada` — sin estado intermedio persistido; «vencida» es un predicado, no una columna. Excepción permanente: clase `license` no tiene transición a purgada.
