# Reporte de run — 20260812-rampa-03

- **Gate**: 125 · versión 0.1.0-diagnostico
- **Tipo de run** (kind): diagnostico
- **Estado**: invalid
- **Veredicto global**: ⚠️ INVÁLIDO
- **Timestamp**: 2026-08-12T13:11:34.415307+00:00
- **Motivo de invalidez**: fallo inesperado del orquestador (CalledProcessError): Command '['/root/examen/sentinel-guardian/harness/bin/k6', 'run', '--env', 'GATE_CONFIG={"gate": 125, "version": "0.1.0-diagnostico", "base_url": "http://10.0.0.10", "stub_url": "http://10.0.0.20:8080", "pool_file": "pool.json", "corpus_file": "corpus.json", "summary_file": "summary.json", "densities_per_mille": [0, 1, 5, 20], "scenarios": [{"surface": "chat", "exec": "chat", "phase": "sustained", "executor": "constant-arrival-rate", "rate": 750, "timeUnit": "120s", "duration": "2m", "startTime": "0s", "preAllocatedVUs": 11, "maxVUs": 28, "gracefulStop": "75s"}, {"surface": "extension", "exec": "extension", "phase": "sustained", "executor": "constant-arrival-rate", "rate": 310, "timeUnit": "195s", "duration": "2m", "startTime": "0s", "preAllocatedVUs": 10, "maxVUs": 20, "gracefulStop": "75s"}, {"surface": "coding_sse", "exec": "coding", "phase": "sustained", "executor": "constant-arrival-rate", "rate": 130, "timeUnit": "210s", "duration": "2m", "startTime": "0s", "preAllocatedVUs": 34, "maxVUs": 89, "gracefulStop": "75s"}, {"surface": "admin", "exec": "admin", "phase": "sustained", "executor": "constant-arrival-rate", "rate": 60, "timeUnit": "390s", "duration": "2m", "startTime": "0s", "preAllocatedVUs": 10, "maxVUs": 20, "gracefulStop": "75s"}, {"surface": "chat", "exec": "chat", "phase": "burst", "executor": "constant-arrival-rate", "rate": 1875, "timeUnit": "120s", "duration": "2m", "startTime": "120s", "preAllocatedVUs": 26, "maxVUs": 69, "gracefulStop": "75s"}, {"surface": "extension", "exec": "extension", "phase": "burst", "executor": "constant-arrival-rate", "rate": 775, "timeUnit": "195s", "duration": "2m", "startTime": "120s", "preAllocatedVUs": 10, "maxVUs": 20, "gracefulStop": "75s"}, {"surface": "coding_sse", "exec": "coding", "phase": "burst", "executor": "constant-arrival-rate", "rate": 325, "timeUnit": "210s", "duration": "2m", "startTime": "120s", "preAllocatedVUs": 83, "maxVUs": 221, "gracefulStop": "75s"}, {"surface": "admin", "exec": "admin", "phase": "burst", "executor": "constant-arrival-rate", "rate": 150, "timeUnit": "390s", "duration": "2m", "startTime": "120s", "preAllocatedVUs": 10, "maxVUs": 20, "gracefulStop": "75s"}, {"surface": "chat", "exec": "chat", "phase": "peak", "executor": "constant-arrival-rate", "rate": 3750, "timeUnit": "120s", "duration": "2m", "startTime": "240s", "preAllocatedVUs": 52, "maxVUs": 138, "gracefulStop": "75s"}, {"surface": "extension", "exec": "extension", "phase": "peak", "executor": "constant-arrival-rate", "rate": 1550, "timeUnit": "195s", "duration": "2m", "startTime": "240s", "preAllocatedVUs": 10, "maxVUs": 20, "gracefulStop": "75s"}, {"surface": "coding_sse", "exec": "coding", "phase": "peak", "executor": "constant-arrival-rate", "rate": 650, "timeUnit": "210s", "duration": "2m", "startTime": "240s", "preAllocatedVUs": 166, "maxVUs": 441, "gracefulStop": "75s"}, {"surface": "admin", "exec": "admin", "phase": "peak", "executor": "constant-arrival-rate", "rate": 300, "timeUnit": "390s", "duration": "2m", "startTime": "240s", "preAllocatedVUs": 10, "maxVUs": 20, "gracefulStop": "75s"}, {"surface": "chat", "exec": "chat", "phase": "recovery", "executor": "constant-arrival-rate", "rate": 7500, "timeUnit": "120s", "duration": "2m", "startTime": "360s", "preAllocatedVUs": 104, "maxVUs": 276, "gracefulStop": "75s"}, {"surface": "extension", "exec": "extension", "phase": "recovery", "executor": "constant-arrival-rate", "rate": 3100, "timeUnit": "195s", "duration": "2m", "startTime": "360s", "preAllocatedVUs": 12, "maxVUs": 32, "gracefulStop": "75s"}, {"surface": "coding_sse", "exec": "coding", "phase": "recovery", "executor": "constant-arrival-rate", "rate": 1300, "timeUnit": "210s", "duration": "2m", "startTime": "360s", "preAllocatedVUs": 331, "maxVUs": 882, "gracefulStop": "75s"}, {"surface": "admin", "exec": "admin", "phase": "recovery", "executor": "constant-arrival-rate", "rate": 600, "timeUnit": "390s", "duration": "2m", "startTime": "360s", "preAllocatedVUs": 10, "maxVUs": 20, "gracefulStop": "75s"}, {"surface": "chat", "exec": "chat", "phase": "overload", "executor": "constant-arrival-rate", "rate": 15000, "timeUnit": "120s", "duration": "2m", "startTime": "480s", "preAllocatedVUs": 207, "maxVUs": 551, "gracefulStop": "75s"}, {"surface": "extension", "exec": "extension", "phase": "overload", "executor": "constant-arrival-rate", "rate": 6200, "timeUnit": "195s", "duration": "2m", "startTime": "480s", "preAllocatedVUs": 24, "maxVUs": 64, "gracefulStop": "75s"}, {"surface": "coding_sse", "exec": "coding", "phase": "overload", "executor": "constant-arrival-rate", "rate": 2600, "timeUnit": "210s", "duration": "2m", "startTime": "480s", "preAllocatedVUs": 662, "maxVUs": 1764, "gracefulStop": "75s"}, {"surface": "admin", "exec": "admin", "phase": "overload", "executor": "constant-arrival-rate", "rate": 1200, "timeUnit": "390s", "duration": "2m", "startTime": "480s", "preAllocatedVUs": 10, "maxVUs": 20, "gracefulStop": "75s"}], "model_chat": "itv-examen-local", "model_coding": "coding"}', '--env', 'POOL_FILE=/root/examen/sentinel-guardian/harness/runs/20260812-rampa-03/pool.json', '--env', 'CORPUS_FILE=/root/examen/sentinel-guardian/harness/runs/20260812-rampa-03/corpus.json', '--env', 'SUMMARY_FILE=/root/examen/sentinel-guardian/harness/runs/20260812-rampa-03/summary.json', '/root/examen/sentinel-guardian/harness/scenarios/gate.js']' returned non-zero exit status 99.
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
      "sentinel-docs:prod": "5a2b88562217",
      "sentinel/nlp-analyzer:examen-52e694b": "af145d5ef21a",
      "sentinel/frontend:examen-52e694b": "0b7957df5d43",
      "sentinel/backend:examen-52e694b": "31d77e223890",
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
    "version": "0.1.0-diagnostico",
    "kind": "diagnostico"
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
        "duration": "2m",
        "arrival_factor": 10.0
      },
      {
        "name": "burst",
        "duration": "2m",
        "arrival_factor": 25.0
      },
      {
        "name": "peak",
        "duration": "2m",
        "arrival_factor": 50.0
      },
      {
        "name": "recovery",
        "duration": "2m",
        "arrival_factor": 100.0
      },
      {
        "name": "overload",
        "duration": "2m",
        "arrival_factor": 200.0
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
    "harness_commit": "vu-fix-rampa3"
  },
  "timestamp": "2026-08-12T13:11:34.415307+00:00"
}
```

## Evidencia

- **k6_summary**: `/root/examen/sentinel-guardian/harness/runs/20260812-rampa-03/summary.json`
- **pool**: `/root/examen/sentinel-guardian/harness/runs/20260812-rampa-03/pool.json`
- **corpus**: `/root/examen/sentinel-guardian/harness/runs/20260812-rampa-03/corpus.json`
- **k6_config**: `/root/examen/sentinel-guardian/harness/runs/20260812-rampa-03/k6_config.json`
- **plataforma_r3**: `/srv/itv-runs/20260812-rampa-03/`
