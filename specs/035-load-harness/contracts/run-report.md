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

### Filas OPCIONALES del rechazo de admisión (extensión C1, 2026-08-08)

Van SIEMPRE después de las 4 canónicas y en este orden. `global: PASS` exige que pasen
**todas** las filas presentes. Si ninguna aplica, el `verdict.json` es byte a byte el de
antes de C1 — los gates oficiales existentes no se mueven.

| Fila | Cuándo aparece | Medido |
|---|---|---|
| `saturated_503_rows_durable` | el run es `kind: drill` **o** el guion vio ≥1 rechazo | `filas / rechazos` (1.0 = paridad). Sin rechazos: `1.0` PASS vacuo. Con rechazos y sin conteo de filas: `null` ⇒ FAIL |
| `rejection_time_to_503_p95` | run `drill` **y** `rejection_p95_max_ms` fijado | p95 de `rejection_ms` (ms). **Sin rechazos**: `null` con veredicto PASS (vacuo — no hay p95 que medir; la regla del `null`⇒FAIL es exclusiva del SLO (a)). **Con rechazos y sin `rejection_ms.p95`**: `null` ⇒ **FAIL** (hubo 503 pero falta el cronómetro: no se puede afirmar el tiempo hasta el rechazo — espejo de la rama de admin) |
| `admin_latency_budget_p95` | run `drill` **y** `admin_p95_budget_ms` fijado (YAML o `--drill-admin-budget-ms`) | p95 de `surfaces.admin.latency_ms` (ms) |

**Un drill que no saturó es un examen INVÁLIDO, no un PASS.** Si el run es `kind: drill`
(y no `dry-run`), quedó `completed` y los rechazos del guion son `0`/ausentes, el verdict
sale `estado: invalid` + `global: INVALID` con
`invalid_reason: "el drill no alcanzó saturación: la defensa C1 no llegó a ejercitarse
(¿stub en modo sede-lenta? ¿SUT sobrado?)"`. Los criterios quedarían vacuos y el run
saldría PASS por no haber ejercitado nada — eso no es un aprobado, es un examen que no se
tomó. Las filas se conservan como evidencia. El **dry-run** del drill sigue `completed`
(datos sintéticos, ya marcado NO oficial), y un conteo de rechazos presente pero
**ilegible** (no entero) no invalida: lo reprueba la fila `saturated_503_rows_durable`.

Un criterio de drill **sin umbral** no produce fila: deja una entrada en `notas` que dice
cómo fijarlo (p. ej. derivar el presupuesto de admin del baseline del gate oficial del
mismo día). El insumo del guion es `k6_summary.saturated_rejections` + `rejection_ms`
(Trend `lat_rejection`, aparte de las latencias de servicio para no hundir los
percentiles del gate); el del producto es `reconciliation.filas_rejected_saturated` =
filas de `audit_logs` con el estado literal `rejected_saturated`.

## `fingerprint.json`

Lista mínima de FR-009 (data-model): producto (commit + digests), masking por scope,
config NLP, workers/procesos, límites de recursos, gate n+version+**kind**, **examen**
(programa del stub + fases), corpus versión+semilla, mix y cadencia usadas, hardware
(instance_type/AMI/región — outputs de OpenTofu), licencia (lic_id/max_seats), estado del
seed, versiones del instrumento (k6+xk6-sse, stub, harness commit), timestamp. El
comparador de runs diffea fingerprints ANTES que métricas y marca ilegítima cualquier
comparación con diff.

`gate.kind` y `examen` (extensión C1) son MATERIALES: el drill de saturación y el gate 125
oficial comparten número, versión, mezcla y cadencia, así que sin ellos sus fingerprints
solo diferían en el `timestamp` (no material) y el comparador declaraba «LEGÍTIMA» la
comparación de dos exámenes distintos. `examen` = `{stub: {latency_ms, token_rate_tps,
stream_duration_s, error_rate}, phases: [{name, duration, arrival_factor}…]}`.

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
