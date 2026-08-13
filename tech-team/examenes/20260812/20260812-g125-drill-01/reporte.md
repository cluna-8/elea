# Reporte de run — 20260812-g125-drill-01

- **Gate**: 125 · versión 1.0.0
- **Tipo de run** (kind): drill
- **Estado**: invalid
- **Veredicto global**: ⚠️ INVÁLIDO
- **Timestamp**: 2026-08-12T12:31:09.055330+00:00
- **Motivo de invalidez**: el drill no alcanzó saturación: la defensa C1 no llegó a ejercitarse (¿stub en modo sede-lenta? ¿SUT sobrado?)
  > Un run inválido/interrumpido conserva reporte PARCIAL y NO es comparable con otros (US3).

## Veredicto por SLO

| SLO | Medido | Veredicto | Detalle |
|---|---|---|---|
| `audit_lost_events_delta_zero` | 0 | ✅ PASS | inicial=0, final=0 |
| `reconciliation_rows` | 15 | ❌ FAIL | eventos_guion=1240, filas_persistidas=1255 — sobran 15 fila(s) frente a los eventos auditables |
| `zero_raw_canaries` | 0 | ✅ PASS | canarios_detectados=0, canary_set_size=64 |
| `blocked_rows_durable_100` | 1 | ✅ PASS | bloqueos_provocados=0, con_fila=0 — no se provocaron bloqueos en este run (100% trivial) |
| `saturated_503_rows_durable` | 1 | ✅ PASS | rechazos_guion=0, filas_rejected_saturated=0 — no hubo rechazos por saturación en este run (100% trivial) |
| `rejection_time_to_503_p95` | null | ✅ PASS | umbral_ms=6000, rechazos=0 — el producto no rechazó ninguna request: el criterio no aplica (PASS vacuo, no hay p95 que medir) |
| `admin_latency_budget_p95` | 76.4 | ✅ PASS | umbral_ms=199 |

## Overhead por superficie

Overhead = latencia medida − latencia programada del stub (FR-008). El examen mide el COSTE que el producto agrega sobre un proveedor de latencia conocida.

| Superficie | Programada (ms) | overhead p50 (ms) | overhead p95 (ms) | overhead p99 (ms) | overhead max (ms) |
|---|---|---|---|---|---|
| chat | 800 | -712 | -650 | -643 | -522 |
| extension | 0 | 47 | 87 | 100.7 | 162 |
| coding | 600 | 9.004e+04 | 9.006e+04 | 9.007e+04 | 9.009e+04 |
| admin | 0 | 48 | 76.4 | 181.7 | 213 |
| login | 0 | 0 | 0 | 0 | 0 |

### Coding (SSE) — TTFT y cortes · superficie `coding`

| Métrica | Programada (ms) | p50 (ms) | p95 (ms) | p99 (ms) | max (ms) |
|---|---|---|---|---|---|
| TTFT overhead | 600 | 30 | 55.1 | 65.5 | 85 |

- **Cortes de stream** (close/error a mitad): 0

## Por fase

### Fase `sustained` (dropped_iterations=0)

| Superficie | Programada (ms) | overhead p50 (ms) | overhead p95 (ms) | overhead p99 (ms) | overhead max (ms) |
|---|---|---|---|---|---|
| chat | 800 | -712 | -649 | -643.7 | -633 |
| extension | 0 | 45 | 87.5 | 97.3 | 103 |
| coding | 600 | 9.004e+04 | 9.006e+04 | 9.008e+04 | 9.009e+04 |
| admin | 0 | 47.5 | 144.6 | 199.3 | 213 |
| login | 0 | 0 | 0 | 0 | 0 |

### Coding (SSE) — TTFT y cortes · superficie `coding`

| Métrica | Programada (ms) | p50 (ms) | p95 (ms) | p99 (ms) | max (ms) |
|---|---|---|---|---|---|
| TTFT overhead | 600 | 33 | 56.4 | 76.42 | 85 |

- **Cortes de stream** (close/error a mitad): 0

### Fase `burst` (dropped_iterations=0)

| Superficie | Programada (ms) | overhead p50 (ms) | overhead p95 (ms) | overhead p99 (ms) | overhead max (ms) |
|---|---|---|---|---|---|
| chat | 800 | -712 | -650 | -641.1 | -522 |
| extension | 0 | 47 | 84.85 | 100.7 | 162 |
| coding | 600 | 9.004e+04 | 9.006e+04 | 9.007e+04 | 9.007e+04 |
| admin | 0 | 48 | 74.4 | 76.48 | 77 |
| login | 0 | 0 | 0 | 0 | 0 |

### Coding (SSE) — TTFT y cortes · superficie `coding`

| Métrica | Programada (ms) | p50 (ms) | p95 (ms) | p99 (ms) | max (ms) |
|---|---|---|---|---|---|
| TTFT overhead | 600 | 30 | 51.8 | 58.24 | 60 |

- **Cortes de stream** (close/error a mitad): 0

## Instrumento (modelo abierto + headroom del stub)

- **Instrumento válido**: sí
- **dropped_iterations**: 0 (evidencia de modelo abierto: si > 0, k6 no sostuvo la tasa ⇒ run inválido)
- **Drift de pacing del stub p99**: 2.038 ms (umbral 5 ms)
- **CPU del stub**: 0.86 % (umbral 60%)
- **Tráfico no auditable**: 0 (punto ciego del detector de canarios si > 0)

## Fingerprint

Dos runs solo se comparan si comparten fingerprint (el comparador diffea esto ANTES que las métricas).

```json
{
  "producto": {
    "commit": "52e694b",
    "digests": {
      "basa-docs:prod": "5a2b88562217",
      "basa/nlp-analyzer:examen-52e694b": "af145d5ef21a",
      "basa/frontend:examen-52e694b": "0b7957df5d43",
      "basa/backend:examen-52e694b": "31d77e223890",
      "postgres:16": "95206741a5b2",
      "redis:7-alpine": "e7723ff73d96",
      "ghcr.io/berriai/litellm:<none>": "80ea654c506d",
      "caddy:2-alpine": "5f5c8640aae0"
    }
  },
  "masking_por_scope": {
    "default": true
  },
  "config_nlp": {
    "nlp_analyzer": "real",
    "nlp_analyzer_url": "configured",
    "nlp_fail_mode": "block"
  },
  "workers_procesos": {},
  "limites_recursos": {},
  "gate": {
    "n": 125,
    "version": "1.0.0",
    "kind": "drill"
  },
  "examen": {
    "stub": {
      "latency_ms": {
        "chat": 800,
        "coding_first_token": 600
      },
      "token_rate_tps": 5,
      "stream_duration_s": [
        60,
        120
      ],
      "error_rate": 0.0
    },
    "phases": [
      {
        "name": "sustained",
        "duration": "10m",
        "arrival_factor": 1.0
      },
      {
        "name": "burst",
        "duration": "5m",
        "arrival_factor": 3.0
      }
    ]
  },
  "corpus": {
    "version": "1.1.0",
    "seed": 356243790,
    "n_canaries": 64,
    "densities_per_mille": [
      0,
      1,
      5,
      20
    ]
  },
  "mix_y_cadencia_usadas": {
    "mix": {
      "chat": 60,
      "extension": 25,
      "coding_sse": 10,
      "admin": 5
    },
    "cadence_s": {
      "chat": [
        60,
        180
      ],
      "extension": [
        90,
        300
      ],
      "coding_sse": [
        120,
        300
      ],
      "admin": [
        180,
        600
      ]
    },
    "surface_populations": {
      "chat": 75,
      "extension": 31,
      "coding_sse": 13,
      "admin": 6
    },
    "arrival_rates": {
      "chat": {
        "executor": "constant-arrival-rate",
        "rate": 75,
        "time_unit_s": 120.0
      },
      "extension": {
        "executor": "constant-arrival-rate",
        "rate": 31,
        "time_unit_s": 195.0
      },
      "coding_sse": {
        "executor": "constant-arrival-rate",
        "rate": 13,
        "time_unit_s": 210.0
      },
      "admin": {
        "executor": "constant-arrival-rate",
        "rate": 6,
        "time_unit_s": 390.0
      }
    }
  },
  "hardware": {
    "datacenter": null,
    "gen_server_type": "cpx42",
    "location": "hel1",
    "provider": "hetzner",
    "sut_server_type": "ccx33"
  },
  "licencia": {
    "lic_id": "lic_itv_examen_130",
    "kid": "itv-examen-2026",
    "max_seats": 130,
    "seats_used": 119
  },
  "seed_estado": "unknown",
  "versiones_instrumento": {
    "k6": "v1.8.0",
    "xk6_sse": "v0.1.12",
    "stub": "0.1.0",
    "harness_commit": "a076008-wire-fix"
  },
  "timestamp": "2026-08-12T12:31:09.055330+00:00"
}
```

## Evidencia

- **k6_summary**: `/root/examen/basa-guardian/harness/runs/20260812-g125-drill-01/summary.json`
- **pool**: `/root/examen/basa-guardian/harness/runs/20260812-g125-drill-01/pool.json`
- **corpus**: `/root/examen/basa-guardian/harness/runs/20260812-g125-drill-01/corpus.json`
- **k6_config**: `/root/examen/basa-guardian/harness/runs/20260812-g125-drill-01/k6_config.json`
- **reconciliacion**: `/root/examen/basa-guardian/harness/runs/20260812-g125-drill-01/reconciliation.json`
- **plataforma_r3**: `/srv/itv-runs/20260812-g125-drill-01/`
