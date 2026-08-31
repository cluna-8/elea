# Data Model — Spec 035: Harness de carga

**Fase 1** · 2026-08-07 · Entidades derivadas de [spec.md](spec.md) (Key Entities) con
las decisiones de [research.md](research.md). Todo vive como archivos (YAML/JSON/md) —
el harness no tiene base de datos propia (FR-010: out-of-band, sin estado en el SUT).

## Gate (definición versionada — `harness/gates/gate-<N>.yaml`)

La identidad de un examen. Cambiarla = bump de `version` en PR (FR-006).

| Campo | Tipo | Regla |
|---|---|---|
| `gate` | int (125/250/500) | población canónica del tech tree |
| `version` | semver | citado por todo Run/Reporte; recalibrar tolerancia = bump |
| `duration` | fases con duración | 125: sostenido 30m · 250: + login_storm 10m · 500: sostenido 1h + pico ×2 + recuperación |
| `mix` | % por superficie | default hipótesis 60/25/10/5 (Assumptions de la spec) |
| `cadence` | rango s por superficie | ancla operativa de «sesión activa» (FR-001) |
| `pii_densities` | lista (0/1/5/20 por mil) | por escenario del guion |
| `stack_config_required` | mapa scope→estado | masking ON por default; precondición verificada pre-run (drift → aviso) |
| `population_ref` | ref a Población | `harness/src/seeder/populations/gate-<N>.yaml` |
| `slo` | los 4 SLO de oro | fijos (FR-007); no configurables por run |
| `repeatability_tolerance` | ±% en overhead p95 | vinculante (SC-005): ±10% ciclo 1 |
| `stream_duration` | rango s | duración programada de streams SSE del stub (condiciona maxVUs) |

## Población / Seed (`harness/src/seeder/populations/gate-<N>.yaml`)

Conjunto reproducible que el seeder aprovisiona vía API real (R5).

- `tenant`, `admin_bootstrap` (primer login), distribución por rol
  (client×client_type: chat_ui/desktop/base_url · tenant_admin · compliance_officer),
  keys por tool_type, budgets (default generoso + cohorte 402 ~2%).
- Reglas: users ANTES que keys (seat gate en ambos); pre-check de seats vía
  `GET /api/v1/health/license` con fail-fast; idempotente (la API rechaza duplicados →
  converge); modo `verify-only` entre runs.
- Estados: `absent → seeded → verified` (el estado va al Fingerprint).

## Corpus PII (`harness/corpus/templates/` + generador `harness/src/corpus/`)

- Plantillas es-ES por superficie (data versionada) + **generador determinista por
  semilla**: mismo (semilla, versión de corpus) → mismo corpus (US3 comparabilidad).
- Valores PII sintéticos que MATCHEAN los reconocedores reales del producto (DNI con
  letra válida, IBAN ES con checksum, +34 6XX, nombres detectables por NER es) —
  oráculo compartido con `sentinel_guardian_policy.py` (R6).
- Densidades configurables por escenario, incluida 0 (tráfico limpio).

## Canario

- Valor PII sintético **único por run** (nonce embebido, imposible de confundir con
  datos legítimos ni con residuos de runs anteriores — FR-004).
- Generado en runtime, JAMÁS commiteado. Set de un run ∩ set de otro = ∅ (test).
- Ciclo de vida: generado → sembrado en tráfico → (si aparece crudo en el stub) →
  `LeakEvidence {canario, request_id, superficie, timestamp, config_masking_vigente}` →
  SLO (c) FAIL.

## Run (`<run-id>/` — local scratch; oficiales → plataforma R3)

| Campo | Tipo | Regla |
|---|---|---|
| `run_id` | `<fecha>-g<gate>-<seq>` | único, humano-legible |
| `kind` | gate_oficial / diagnóstico / smoke / fault_injection | solo gate_oficial compite en comparaciones; fault_injection = SC-004 |
| `estado` | preparing → running → completed \| interrupted \| **invalid** | interrupted/invalid NUNCA comparables (US3-AS3); invalid con `invalid_reason` |
| `fingerprint` | Fingerprint | obligatorio antes de generar carga |
| `verdict` | Verdict | solo si completed |
| `evidence` | refs | k6 summary JSON, spool del stub, tarball de logs, export de métricas, headroom del instrumento |

Causas de `invalid` (de la spec): generador saturado (`dropped_iterations > 0`), stub
fuera de headroom (drift p99 >5 ms o CPU >60%), contador de auditoría que retrocede,
credencial insuficiente del evaluador, drift de `stack_config_required`, licencia
insuficiente detectada tarde, duración efectiva ≠ nominal sin causa.

## Fingerprint (`fingerprint.json` — lista mínima de FR-009)

`producto` (commit + digests de imágenes) · `masking_por_scope` · `config_nlp` ·
`workers_procesos` (backend/motor/nlp) · `limites_recursos` · `gate` (N + version) ·
`corpus` (versión + semilla) · `mix_y_cadencia_usadas` · `hardware` (instance_type,
AMI, región — outputs de OpenTofu) · `licencia` (lic_id, max_seats — propuesta R5) ·
`seed_estado` · `versiones_instrumento` (k6+xk6-sse, stub, harness commit) ·
`timestamp`. Comparador: dos fingerprints distintos → diferencia señalada, comparación
marcada ilegítima.

## Verdict (`verdict.json`)

Por cada SLO de oro (FR-007): `{slo, valor_medido, veredicto: PASS|FAIL, evidencia}`.
- (a) `audit_lost_events`: Δ == 0; nulo/ausente = FAIL; final < inicial = run invalid.
- (b) `reconciliación`: filas persistidas == eventos auditables del guion.
- (c) `canarios`: 0 crudos en el stub (evidencia por LeakEvidence si >0).
- (d) `bloqueos_durables`: 100% de los bloqueos provocados con fila durable.
Global: PASS ⟺ los 4 PASS y estado = completed. Por fase en gates 250/500 (tormenta /
sostenido / pico / recuperación).

## Reporte (`reporte.md` — comparable, US3)

Secciones fijas: veredicto global y por SLO → overhead por superficie y percentil
(p50/p95/p99/max, FR-008; TTFT y cortes solo coding) → métricas por fase → fingerprint
→ headroom del instrumento (evidencia de modelo abierto: tasa efectiva vs programada) →
refs a evidencia pesada. Dos reportes del mismo gate+version se comparan con un diff.

## Stub — configuración por run (API de control)

`{alias → {latency_ms, token_rate, error_rate, stream_duration_s}}` + `reset` +
`report` (canarios detectados, requests por alias, drift de pacing, CPU). Determinista
por semilla donde aplique (tasa de error reproducible).

## Relaciones

```text
Gate (versionado) ──1:N──> Run ──1:1──> Fingerprint
   │                        ├──1:1──> Verdict (si completed)
   │                        └──1:N──> Evidence (k6, spool, logs, métricas)
   └── population_ref ──> Población/Seed        Corpus ──genera──> Canarios (por run)
                                                 Stub ──detecta──> LeakEvidence ──> Verdict(c)
```
