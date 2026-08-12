# Contract — Definición versionada de gate (`harness/gates/gate-<N>.yaml`)

Esquema del data-model (entidad Gate) como contrato ejecutable: el orquestador consume
este YAML y un gate se corre con UN comando (SC-006). Ejemplo normativo del gate 125:

```yaml
gate: 125
version: 1.0.0            # bump en PR ante CUALQUIER cambio, incluida la tolerancia
description: Paridad sede (~125 beta testers Cámara)
phases:
  - name: sustained
    duration: 30m
population_ref: populations/gate-125.yaml
mix:                      # hipótesis documentada (Assumptions) hasta validar con datos reales
  chat: 60                # request/response JSON (sin streaming — verificado)
  extension: 25
  coding_sse: 10          # única superficie SSE (TTFT + cortes)
  admin: 5
cadence_s:                # ancla operativa de «sesión activa» (FR-001)
  chat: [60, 180]
  extension: [90, 300]
  coding_sse: [120, 300]
  admin: [180, 600]
pii_densities_per_mille: [0, 1, 5, 20]
stack_config_required:    # precondición verificada ANTES del run (drift → aviso, run no oficial)
  masking:
    default: on           # D8: masking-off es legítimo pero el gate oficial lo fija ON
  nlp_analyzer: real      # FR-011: jamás regex-only
  nlp_analyzer_url: configured   # post-PR #97: /gw llama al sidecar en cada request
  nlp_fail_mode: block           # default de fábrica (#97); el gate lo fija explícito
  producto_incluye: ["PR #97"]   # gates oficiales solo contra imagen post-paridad NLP
  auto_router: "off"      # pendiente open question R2 (vectores fake vs cache del router)
stub:
  latency_ms: {chat: 800, coding_first_token: 600}
  token_rate_tps: 40
  stream_duration_s: [10, 60]
  error_rate: 0.0
slo:                      # fijos — se listan por trazabilidad, no son configurables
  - audit_lost_events_delta_zero
  - reconciliation_rows
  - zero_raw_canaries
  - blocked_rows_durable_100
repeatability_tolerance_pct: 10   # SC-005, vinculante; recalibrar = bump de version
budget_api_usd: 0                 # FR-012: gate oficial solo contra stub
```

Deltas de los otros gates:
- **gate-250**: fase previa `login_storm` (`duration: 10m`, toda la población entra en
  la ventana; métricas separadas por fase) + `sustained 30m`. SLOs idénticos en ambas
  fases (la tormenta no relaja nada).
- **gate-500**: fases `sustained 1h` → `peak ×2` → `recovery` (verificación de vuelta a
  niveles normales sin intervención); sección opcional `knee_search` (informativa,
  fuera del pass/fail, explícitamente diferible).

## Extensión C1 — campos opcionales `kind` y `drill` (2026-08-08)

**Aditivos**: una definición sin ellos es exactamente el gate de siempre (`kind` ausente
= `gate_oficial`), y los 4 SLO de oro de `slo:` siguen siendo obligatorios en toda
definición — un drill **no** los reemplaza ni los relaja.

```yaml
kind: drill               # opcional; {gate_oficial (default), drill}. Un valor
                          # desconocido es error de validación, no se ignora.
drill:                    # opcional; única clave válida: `criteria`
  criteria:               # claves desconocidas → error (un typo se leería como «sin
                          # umbral» y el drill pasaría por no medir nada)
    rejection_p95_max_ms: 6000   # número > 0, o null = umbral sin fijar
    admin_p95_budget_ms: null    # null: se deriva del baseline medido del mismo día
```

- `kind: drill` marca un examen **dirigido** (`harness/gates/drill-saturacion-125.yaml`:
  el drill de saturación del nodo C1, modo «sede lenta»). El YAML MANDA sobre `--kind`:
  un drill no puede correrse por accidente como gate oficial.
- `drill.criteria` son criterios **propios del drill**, no SLO de oro. Un criterio con
  umbral fijado es vinculante para el veredicto del drill; con `null` (o ausente) no
  produce fila — deja una nota que dice cómo fijarlo. Nunca se inventa un número.
- `admin_p95_budget_ms` se deriva del baseline MEDIDO del gate oficial del mismo día
  (mismo hardware, misma imagen) y se pasa por `--drill-admin-budget-ms`; por eso vive
  como `null` en el YAML.

**Cross-check `kind` ↔ `drill` (bidireccional, error de validación).** Los dos campos son
opcionales por separado pero NO independientes; las dos incoherencias son silenciosas y
caras:

| Definición | Resultado | Por qué |
|---|---|---|
| bloque `drill` sin `kind: drill` (ausente o explícito `gate_oficial`) | **error**: «bloque 'drill' en una definición gate_oficial: o falta 'kind: drill' o sobra el bloque» | el evaluador solo mira `drill.criteria` en un run drill: los criterios no se evaluarían y el examen parecería medir sin medir |
| `kind: drill` sin bloque `drill` con `criteria` | **error**: «'kind: drill' sin bloque 'drill' con 'criteria'…» | un drill sin criterios propios «pasa» por no medir nada |

Los VALORES de `criteria` pueden ser `null` (umbral sin fijar, legítimo); la **clave** no.
Un umbral fijado debe ser un número **finito** > 0: `.inf` volvería el criterio decorativo
(nada lo supera) y `.nan` lo haría aleatorio — ambos son error de validación.

Reglas del contrato:
1. Todo Run cita `gate + version`; reportes de versiones distintas no se comparan como
   equivalentes (el comparador lo señala).
2. `stack_config_required` es la precondición del fingerprint: si el stack no la
   cumple, el orquestador avisa y el run no puede marcarse `gate_oficial`.
3. Un run `fault_injection` (SC-004) usa el MISMO gate con override explícito de
   `masking.default: off` — el override queda en el fingerprint y el run jamás compite
   en comparaciones oficiales.
4. Precondición post-#97: el bloque `nlp` del health (probe cacheado 10 s, gateado por
   rol) debe reportar sano antes de un run oficial, y el `nlp_fail_mode` vigente queda
   registrado en el fingerprint (un gate corrido en `degrade` no es el mismo examen que
   uno en `block`).
