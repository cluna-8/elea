# Reporte de run — 20260812-g125-01

- **Gate**: 125 · versión 1.0.0
- **Tipo de run** (kind): gate_oficial
- **Estado**: invalid
- **Veredicto global**: ⚠️ INVÁLIDO
- **Timestamp**: 2026-08-12T11:23:43.770231+00:00
- **Motivo de invalidez**: fallo inesperado del orquestador (ReconcileError): el producto registró 60 fila(s) de bloqueo en la ventana pero el guion contó 0 bloqueos provocados (k6 no incrementa `observed_blocks` en ninguna superficie). Con 0 provocados el SLO (d) sale PASS vacuo: sería un aprobado regalado sobre un run donde el bloqueo SÍ ocurrió. Revisá esas filas a mano (GET /api/v1/audit-logs?estado=bloqueados) antes de certificar.
  > Un run inválido/interrumpido conserva reporte PARCIAL y NO es comparable con otros (US3).
- **Nota**: reporte PARCIAL: el run no llegó a completarse; NO comparable

## Veredicto por SLO

| SLO | Medido | Veredicto | Detalle |
|---|---|---|---|

## Overhead por superficie

Overhead = latencia medida − latencia programada del stub (FR-008). El examen mide el COSTE que el producto agrega sobre un proveedor de latencia conocida.

_Sin datos de overhead (¿run en seco o k6 no corrió?)._

## Por fase

_Fase única (sin desglose)._

## Instrumento (modelo abierto + headroom del stub)

- **Instrumento válido**: NO
- **dropped_iterations**: None (evidencia de modelo abierto: si > 0, k6 no sostuvo la tasa ⇒ run inválido)
- **Drift de pacing del stub p99**: None ms (umbral 5 ms)
- **CPU del stub**: None % (umbral 60%)
- **Tráfico no auditable**: None (punto ciego del detector de canarios si > 0)

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
    "kind": "gate_oficial"
  },
  "examen": {
    "stub": {
      "latency_ms": {
        "chat": 800,
        "coding_first_token": 600
      },
      "token_rate_tps": 40,
      "stream_duration_s": [
        10,
        60
      ],
      "error_rate": 0.0
    },
    "phases": [
      {
        "name": "sustained",
        "duration": "30m",
        "arrival_factor": 1.0
      }
    ]
  },
  "corpus": {
    "version": "1.1.0",
    "seed": null,
    "n_canaries": 0,
    "densities_per_mille": []
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
    "harness_commit": "05ac55f934379cf796805cc9d77bec75013cf720"
  },
  "timestamp": "2026-08-12T11:23:43.770231+00:00"
}
```

## Evidencia

- **k6_summary**: `/root/examen/basa-guardian/harness/runs/20260812-g125-01/summary.json`
- **pool**: `/root/examen/basa-guardian/harness/runs/20260812-g125-01/pool.json`
- **corpus**: `/root/examen/basa-guardian/harness/runs/20260812-g125-01/corpus.json`
- **k6_config**: `/root/examen/basa-guardian/harness/runs/20260812-g125-01/k6_config.json`
- **plataforma_r3**: `/srv/itv-runs/20260812-g125-01/`
