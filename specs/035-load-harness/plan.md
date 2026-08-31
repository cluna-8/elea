# Implementation Plan: Harness de carga — «El examen existe» (gates 125/250/500)

**Branch**: `035-load-harness` | **Date**: 2026-08-07 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/035-load-harness/spec.md`

## Summary

Construir el instrumento que administra el examen de Fase 0: un harness de carga que
simula N sesiones de usuario ACTIVAS sobre las 4 superficies del producto contra un
stack de producción completo en un entorno cloud dedicado, con proveedor simulado
centinela (canarios PII), seeder reproducible, veredicto automático por los 4 SLO de
oro, reportes comparables con fingerprint, y observabilidad en vivo self-hosted.
Enfoque técnico (sellado en [research.md](research.md), 6 decisiones con verificación
empírica del 07-ago): k6 v1.8.0+xk6-sse pineado como generador (modelo abierto por
executor `constant-arrival-rate`), stub Python asyncio de doble wire (OpenAI+Anthropic)
con detección inline de canarios, topología de observabilidad «centro persistente +
sonda efímera» (Prometheus/Grafana OSS), par de cajas de vCPU dedicadas Hetzner CCX
con OpenTofu y stop/start (provider hcloud, decisión 08-ago), seeding vía API REST real
del producto, licencias de test emitidas in-house, módulo raíz `harness/` con gates
versionados como data.

## Technical Context

**Language/Version**: Python 3.12 (stub, seeder, generador de corpus, evaluador SLO,
reporting — el stack de la casa) + JavaScript para guiones k6 + YAML para definiciones
de gates y poblaciones (config-as-data).

**Primary Dependencies**: k6 v1.8.0 + xk6-sse v0.1.12 (binario versionado, build
reproducible vía xk6; NUNCA k6 v2.x — incompatible con xk6-sse hoy) · FastAPI/uvicorn
(stub, 1 proceso) · Prometheus OSS (centro + agent-mode en sonda) + Grafana OSS +
node_exporter/cadvisor/postgres_exporter · OpenTofu (root mínimo nuevo, patrón
modules/network) · candidatos corpus: Faker es_ES + python-stdnum (verificar al
implementar).

**Storage**: reportes/veredictos/fingerprints como archivos versionables
(`harness/runs/` local gitignored; oficiales → plataforma R3); evidencia pesada en
`/srv/itv-runs/<id>/` del servidor persistente (Caddy read-only + auth); series de
métricas en Prometheus central (retención larga). El harness NO escribe en la base del
producto (out-of-band).

**Testing**: pytest (`harness/tests/` unit + contract, espejo de backend/tests; corre
en CI sin stack — job `harness-tests`). Frontera: pytest prueba el instrumento; los
runs prueban el producto; SC-004 (inyección de fallo) se ejecuta como run.

**Target Platform**: Linux x86_64 — SUT en Hetzner Cloud CCX33 (8 vCPU dedicadas /
32 GB, project `guardian-itv`, `compose.prod.yml --profile selfhosted`, medido a través
de Caddy); generador+stub en CCX23 separada, misma red privada; centro de observabilidad
en una CPX21 fija del mismo project (decisión 08-ago aprobada por JF — supersede el
diseño AWS de R4; detalle en el Addendum de research.md).

**Project Type**: módulo de tooling del monorepo (`harness/`) — no es código de
producto; nada de él entra en artefactos que se venden.

**Performance Goals**: sostener la carga del gate 500 (~3.5 llegadas/s, ~150 requests
en vuelo pico) con headroom sobrado y auto-medido del instrumento: stub con lateness de
pacing p99 <5 ms y CPU <60% (triggers de run inválido); generador con
`dropped_iterations == 0` como threshold duro.

**Constraints**: gates a coste de API $0 (solo stub; FR-012) · el instrumento jamás
corre dentro del SUT ni lo instrumenta (FR-010) · PROHIBIDO cargar el VPS de prod o
instalaciones de clientes (FR-011) · egress del SUT bloqueado por Security Group
(candado del SLO de canarios) · veredicto SLO computado de k6 JSON + health del
producto + detector del stub, NUNCA de la caja de observabilidad · corpus 100%
sintético (constitución: no raw PII) · presupuesto explícito y techo duro en todo run
contra proveedor real.

**Scale/Scope**: gates de 125/250/500 usuarios activos (hasta 500 users + ~500 keys +
budgets seedeados en ≤10 min); runs de 30 min a ~3.5 h; ciclo 1 ≈ 25-30 runs;
histórico comparable entre ciclos (ago→sept).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.* —
**Evaluado 07-ago (pre-research y re-verificado post-research): PASS sin violaciones.**

- **I. Masking-First**: el harness no toca el pipeline de masking; lo EXAMINA. La
  definición de gate fija el estado de masking exigido al stack (default: ON en todos
  los scopes) — coherente con D8 (masking-off legítimo pero jamás silencioso). SC-004
  usa masking-off solo en el stack de examen, declarado en fingerprint. ✅
- **II. Compliance/GDPR**: SLO de oro = la promesa de auditoría bajo carga; corpus 100%
  sintético; el spool del stub solo contiene material sintético (no viola
  metadata-only, que aplica a la auditoría del producto). ✅
- **III. Multi-tenant**: el seeder puebla un tenant vía API real; no cruza tenants. ✅
- **IV. Client-as-Data**: el seeder usa exactamente el onboarding-as-data del producto
  (users + client_type + keys por tool_type) — cero código de producto tocado. ✅
- **V. Cost Governance**: budgets del seed generosos por default + cohorte 402 dedicada
  — examina el enforcement sin contaminar el gate. ✅
- **VI. LiteLLM-Native, No Patching**: el stub se cablea por `api_base` del model_list
  y `SENTINEL_GW_ANTHROPIC_BASE` — puntos de extensión de configuración, cero parches al
  motor. ✅
- **VII. White-Label/config+seed**: el entorno de examen es un perfil de cliente más
  (`deploy/clients/itv-examen/`) — la misma maquinaria que se vende; harness = módulo
  interno que no entra en artefactos publicados. ✅
- **VIII. Transparencia**: el reporte por SLO con evidencia es la versión
  de-instrumento del principio; fingerprint = observabilidad de qué se examinó. ✅
- **Security & Compliance Constraints**: no raw PII (sintético) ✅ · NLP real activo en
  el stack examinado (FR-011) ✅ · sin credenciales en claro (secrets del examen por
  overlay/env; provider keys VACÍAS a propósito) ✅.
- **Development Workflow**: SDD completo (spec verificada → este plan → tasks) ✅ ·
  Reuse over Reinvent: regex del producto como oráculo del corpus, patrón
  modules/network de tofu, mecanismo de perfiles de cliente ✅ · tests nuevos con el
  código (harness/tests/) ✅.

## Project Structure

### Documentation (this feature)

```text
specs/035-load-harness/
├── spec.md              # Verificada 07-ago (workflow adversarial wf_5044412a)
├── checklists/requirements.md
├── plan.md              # Este archivo
├── research.md          # Fase 0 SELLADA 07-ago (workflow wf_601e144b, 6 decisiones)
├── data-model.md        # Fase 1 — pendiente
├── quickstart.md        # Fase 1 — pendiente
├── contracts/           # Fase 1 — pendiente (wire del stub, esquema verdict/fingerprint, gate YAML)
└── tasks.md             # Fase 2 (/speckit-tasks — no lo crea /speckit-plan)
```

### Source Code (repository root)

```text
harness/                       # módulo nuevo del monorepo (dueño en CODEOWNERS + ADR 0002)
├── README.md                  # doc canónica del módulo (única doc interna obligatoria)
├── gates/                     # gate-125.yaml · gate-250.yaml · gate-500.yaml (versionados, FR-006)
├── corpus/templates/          # plantillas es-ES por superficie (canarios: runtime-only)
├── scenarios/                 # k6: chat.js · extension.js · coding-sse.js · admin.js + común
├── src/
│   ├── stub/                  # proveedor simulado doble-wire + detector de canarios + API de control
│   ├── seeder/                # cliente API REST + populations/*.yaml + pre-check de seats
│   ├── corpus/                # generador determinista por semilla (oráculo: regex del producto)
│   ├── reporting/             # evaluador SLO + fingerprint + comparador de runs
│   └── observe/               # colector out-of-band (logs por ventana, export métricas)
├── observability/             # compose del centro (Prometheus+Grafana) + sonda (exporters+agent)
├── infra/                     # root OpenTofu mínimo (par c6i, VPC, SGs con egress bloqueado)
├── tests/                     # pytest del instrumento (unit/ + contract/)
└── runs/                      # scratch local (.gitignore)

deploy/clients/itv-examen/     # perfil de cliente del examen (config.yaml.tmpl → stub, overlay env)
.github/CODEOWNERS             # + sección La ITV: harness/ @DrZuzzjen
docs/adr/0002-harness-modulo-monorepo.md
```

**Structure Decision**: módulo raíz `harness/` del monorepo (regla estructural del
CONTRIBUTING, propuesta literal del #95, precedente de layout backend/ con src+tests
espejo y config-as-data). El entorno de examen se materializa como perfil de cliente
(`deploy/clients/itv-examen/`) usando la maquinaria de deploy existente — costura con
territorio Factory (deploy/ es de @FalimeJ en CODEOWNERS): el PR que lo cree pide su
review por el CODEOWNERS vigente.

## Complexity Tracking

Sin violaciones de constitución que justificar. Única deuda consciente: el binario k6
pineado a la línea 1.x con extensión de mantenimiento incierto — mitigada con pin +
build reproducible versionado + plan B documentado (vendorear xk6-sse, Apache-2.0), y
registrada como open question en research.md.
