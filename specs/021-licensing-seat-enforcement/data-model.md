# Data Model — 021 Licensing & Seat Enforcement

**Principio**: la 021 NO crea schema de dominio — consume la 013 tal cual. Lo único
propio es una fila de estado runtime (migración `011`).

## Entidades consumidas (013, sin cambios)

| Entidad | Rol en la 021 |
|---|---|
| `Tenant` | Unidad de aislamiento: entitlement, conteo y reconciliación son POR tenant (FR-017). |
| `APIKey` | **El seat** ([D-021], FR-013/014): `COUNT(activas y no expiradas)` por tenant — `seat_counter.count_active_seats` es LA única query (la usan gate y reconciliación). |
| `User` | Call-site de creación (users.py) gateado igual que keys.py. |
| `AuditLog` | Canal de evidencia: cada transición de licencia es una fila `model='license'`, metadata-only, con la entrada encadenada en `guardian_events[0]` (FR-022/024/028). |

## Estado propio: `license_runtime_state` (migración 011)

Fila **singleton** (`id=1`, CheckConstraint) por deployment:

| Columna | Semántica |
|---|---|
| `genesis_license_id` | Ancla de la génesis de la cadena — se fija en el PRIMER evento y **se registra en el onboarding**; el primer true-up se verifica contra ella (FR-028). |
| `hash_head` | Hash del último evento encadenado. Avanza en la MISMA tx que el evento, bajo `SELECT … FOR UPDATE` (serializa requests + scheduler + N workers). |
| `event_counter` | `seq` del último evento (contador monotónico de la cadena). |
| `monotonic_ts` | Marca anti-rollback (FR-023): último ts de licencia visto; un tick con `now < marca` → `license_clock_rollback_suspected` + creación degradada. Sobrevive reinicios. |

## Esquema de la entrada encadenada (`guardian_events[0]`)

```json
{"event_type": "license_*", "license_id": "...", "seats_used": 3, "max_seats": 5,
 "reason": "...", "ts": "ISO-8601", "prev_hash": "<sha256 hex>", "seq": 42}
```

- `hash(entrada) = sha256(json canónico de la entrada completa)` — mismo esquema
  canónico que la firma del token (`token.canonical_payload_bytes`).
- Génesis: `prev_hash` del seq 1 = `sha256("sentinel-genesis:<license_id>")`.
- Vector de regresión fijo en `tests/contract/test_license_wire_formats.py`.

## Estado en memoria (no persistido)

- `entitlement._state` — `LicenseState{status, reason, token, checked_at}`; singleton,
  refrescado por el tick (histéresis `READ_FAILURE_TOLERANCE=3` ante I/O fallido).
- `reconcile._registry` — `{tenant_id: TenantSeatStatus{status, seats_used, max_seats,
  checked_at}}`; swap atómico por corrida, publicación incremental por tenant.
- `reconcile._clock_rollback` — episodio de rollback vigente (la marca que lo
  sostiene SÍ persiste).

## Límite documentado (FR-028, contrato T039)

El truncado de COLA / wipe total de la cadena **no es detectable localmente** (quien
controla el runtime controla la DB). Lo detecta la **continuidad entre true-up
exports** (head-ancestro + contador no-decreciente, `trueup_export.verify_export`);
el ancla final es contractual (true-up en renovación + audit-rights del EULA).
