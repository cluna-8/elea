# Contract — Verdict, Fingerprint y Reporte de run

Los tres artefactos que produce todo run (data-model: Run/Verdict/Fingerprint/Reporte).
Formatos estables: son la superficie de comparación entre runs (US3) y lo que consumen
humanos, sesiones agénticas y el futuro panel de rendimiento.

## `verdict.json` (veredicto automático, SC-002)

```json
{
  "run_id": "20260812-g125-01",
  "gate": {"n": 125, "version": "1.0.0"},
  "estado": "completed",
  "global": "FAIL",
  "slos": [
    {"slo": "audit_lost_events_delta_zero", "medido": 0,     "veredicto": "PASS",
     "detalle": {"inicial": 3, "final": 3, "fuente": "GET /api/v1/health (audit.lost_events, credencial compliance)"}},
    {"slo": "reconciliation_rows",          "medido": -12,   "veredicto": "FAIL",
     "detalle": {"eventos_guion": 2250, "filas_persistidas": 2238}},
    {"slo": "zero_raw_canaries",            "medido": 0,     "veredicto": "PASS"},
    {"slo": "blocked_rows_durable_100",     "medido": 1.0,   "veredicto": "PASS",
     "detalle": {"bloqueos_provocados": 40, "con_fila": 40}}
  ],
  "por_fase": {"sustained": {"...": "..."}},
  "instrumento": {"dropped_iterations": 0, "stub_drift_p99_ms": 1.2, "stub_cpu_pct": 24,
                   "valido": true}
}
```

Reglas: `medido: null` en el SLO (a) ⇒ FAIL (nunca se interpreta como 0) · contador
final < inicial ⇒ `estado: invalid` (no hay verdict) · `global: PASS` ⟺ 4 PASS +
`estado: completed` + `instrumento.valido: true`.

## `fingerprint.json`

Lista mínima de FR-009 (data-model): producto (commit + digests), masking por scope,
config NLP, workers/procesos, límites de recursos, gate n+version, corpus
versión+semilla, mix y cadencia usadas, hardware (instance_type/AMI/región — outputs de
OpenTofu), licencia (lic_id/max_seats), estado del seed, versiones del instrumento
(k6+xk6-sse, stub, harness commit), timestamp. El comparador de runs diffea
fingerprints ANTES que métricas y marca ilegítima cualquier comparación con diff.

## `reporte.md` (humano, comparable con diff)

Orden fijo de secciones:
1. **Veredicto** global + tabla por SLO (valores del verdict.json).
2. **Overhead por superficie** — p50/p95/p99/max (FR-008; overhead = medido − latencia
   programada del stub); TTFT y cortes de stream SOLO en coding.
3. **Por fase** (250/500): tormenta vs sostenido; pico y recuperación.
4. **Instrumento**: evidencia de modelo abierto (tasa efectiva vs programada,
   dropped_iterations), headroom del stub y del runner.
5. **Fingerprint** (inline).
6. **Evidencia**: refs a k6 summary JSON, spool del stub, tarball de logs del producto,
   export de la ventana de métricas — en la plataforma R3 (`/srv/itv-runs/<id>/`).

## Ubicación y ciclo de vida

- Local: `harness/runs/<run-id>/` (scratch, gitignored).
- Oficiales: los tres artefactos livianos + evidencia pesada → plataforma R3; series
  del run consultables por rango temporal en el Prometheus central.
- Un run `interrupted`/`invalid` conserva reporte parcial marcado — jamás un directorio
  a medias que parezca examen completo (edge case de la spec).
