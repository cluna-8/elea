# Tasks: Harness de carga — «El examen existe» (gates 125/250/500)

**Input**: Design documents from `/specs/035-load-harness/` (plan.md, research.md,
data-model.md, contracts/, quickstart.md — todos sellados 07/08-ago)

**Tests**: OBLIGATORIOS por DevFlow del depto («código nuevo = tests nuevos en el mismo
PR») — cada módulo lleva su pytest en `harness/tests/`.

**Contexto de secuenciación (08-ago)**: el lado cloud está **bloqueado hasta que
exista el project Hetzner `guardian-itv` + token** (Cris crea, JF genera; ~lunes 11).
⚠️ Provider swap 08-ago aprobado por JF: **Hetzner Cloud, NO AWS** (CCX33 SUT + CCX23
generador + CPX21 observabilidad; ver Addendum de research.md). TODO lo demás es
construible y testeable en local (compose dev del repo). Las tareas bloqueadas llevan
**[BLOQ-DEVOPS]**. El **corpus es el entregable compartido con el core (#107)** — va
primero en Foundational, no al final.

**Ramas/PRs**: construcción en ramas cortas colgadas de `035-load-harness` (o de main
tras su merge), PR<400 líneas, codex-gate en cada PR con código. Un PR por fase o
módulo coherente.

## Format: `[ID] [P?] [Story] Description`

---

## Phase 1: Setup (scaffold del módulo)

- [ ] T001 Crear estructura `harness/` según plan.md (README.md con frontera «mide, no
      parchea» + gates/ + corpus/templates/ + scenarios/ + src/{stub,seeder,corpus,
      reporting,observe}/ + observability/ + infra/ + tests/ + runs/ en .gitignore) +
      `harness/pyproject.toml` (Python 3.12, deps: fastapi, uvicorn, httpx, pyyaml,
      zstandard; dev: pytest)
- [ ] T002 [P] `.github/CODEOWNERS`: sección La ITV (`harness/ @DrZuzzjen`) — mismo PR
      que T001 (regla CONTRIBUTING)
- [ ] T003 [P] `docs/adr/0002-harness-modulo-monorepo.md` (template 0000; registra
      módulo + decisiones R1/R4/R6; pendiente OK de JF sobre ADR — si dice no, se cae)
- [ ] T004 [P] Job `harness-tests` en `.github/workflows/ci.yml` (pytest sin stack;
      confirmar con JF antes de tocar el workflow recién mergeado de #93)

**Checkpoint**: PR de scaffold abierto (solo estructura + docs — codex-gate exento si
no hay lógica).

---

## Phase 2: Foundational (bloquea todas las stories)

### 2a — Corpus compartido (#107) — PRIORIDAD: el core espera este artefacto

- [x] T005 `specs/035-load-harness/contracts/corpus-format.md`: esquema del dataset
      etiquetado — HECHO 08-ago incorporando los requisitos del runner del core
      (entity_type con enum cerrado del producto, spans codepoints NFC end-exclusivo,
      value como checksum obligatorio, forbidden + docs limpios, baseline config
      default eu, versionado semver+sha256+seed); publicado en #107 para review
- [ ] T006 [P] `harness/src/corpus/generator.py`: generador determinista por semilla —
      valores que MATCHEAN los reconocedores reales (DNI/NIE con checksum, IBAN ES
      válido, +34 6XX, nombres es detectables por NER); densidades configurables por
      escenario (incl. 0); evaluar Faker es_ES + python-stdnum (open question R6) y
      pinnear o descartar con nota
- [ ] T007 [P] `harness/corpus/regressions-63.jsonl`: los casos reales del piloto (#63)
      etiquetados a mano como regresiones (IBAN troceado, FAC-2026-*/PROP-2026-*,
      nombres/direcciones/fechas en claro) — SIN patrones hostiles del #106
- [ ] T008 `harness/src/corpus/canaries.py`: canarios runtime-only únicos por run
      (nonces; dos runs → conjuntos disjuntos)
- [ ] T009 Tests corpus en `harness/tests/unit/test_corpus.py`: determinismo por
      semilla, densidades, unicidad de canarios, TODOS los valores generados matchean
      el oráculo (regex del producto importadas/replicadas de `basa_guardian_policy`),
      regressions-63 parsea contra el esquema
- [ ] T010 Dataset etiquetado v1 generado y commiteado (`harness/corpus/dataset-v1.jsonl`
      versionado) + aviso en #107 al core: artefacto listo para su gate de calidad

### 2b — Definiciones de gate y fingerprint

- [ ] T011 [P] `harness/gates/gate-125.yaml` + `gate-250.yaml` + `gate-500.yaml` según
      contracts/gate-definition.md (version 1.0.0; `nlp_fail_mode: block`;
      `producto_incluye: ["PR #97"]`; tolerancia ±10%)
- [ ] T012 [P] `harness/src/reporting/gate_loader.py`: parser+validador de definiciones
      (la «validación en seco» de SC-008 sale de acá)
- [ ] T013 [P] `harness/src/reporting/fingerprint.py`: captura y comparación
      (lista mínima FR-009 incl. nlp_fail_mode y licencia; diff → comparación ilegítima)
- [ ] T014 Tests en `harness/tests/unit/test_gates_fingerprint.py`: los 3 YAML validan,
      dry-run del 500 pasa (SC-008 local), fingerprints distintos → delatados

**Checkpoint**: corpus v1 entregado al core (#107) + gates versionados validando.

---

## Phase 3: User Story 1 — Gate 125 con veredicto automático (P1) 🎯 MVP

**Goal**: `harness gate run 125` end-to-end contra stack local (dev) primero,
AWS después. **Independent Test**: quickstart escenarios 1-3.

### Stub (contracts/stub-wire.md)

- [ ] T015 [US1] `harness/src/stub/server.py`: FastAPI 1 proceso, wire OpenAI
      (/v1/chat/completions JSON+SSE, /v1/embeddings determinista por hash) + wire
      Anthropic (/v1/messages JSON+SSE con secuencia de eventos completa,
      count_tokens, /v1/models); latencia/token-rate/error-rate programables por alias;
      404 ruidoso y contado para todo lo no contratado
- [ ] T016 [US1] `harness/src/stub/canary_sentinel.py`: escaneo inline sobre bytes
      crudos + LeakEvidence + spool zstd-JSONL por run + buffer por request (canario
      partido entre chunks SSE → detectado)
- [ ] T017 [US1] `harness/src/stub/control.py`: API de control (config/reset/canaries/
      report con drift de pacing p50/p95/p99 + CPU propia — el auto-headroom)
- [ ] T018 [US1] Tests stub en `harness/tests/contract/test_stub_wire.py` (in-process:
      frames SSE bien formados en ambos wires, pacing, canario partido, spool==inline)

### Cableado y seeder

- [ ] T019 [P] [US1] `deploy/clients/itv-examen/`: config.yaml.tmpl (model_list 100%
      `openai/<alias>` → stub, fallbacks stub-backed) + overlay env
      (`BASA_GW_ANTHROPIC_BASE`→stub, provider keys vacías, `BASA_ALLOW_DEV_LICENSE=true`)
      — OJO: toca `deploy/` (CODEOWNERS Falime) → su review en el PR
- [ ] T020 [P] [US1] `harness/src/seeder/`: cliente API (bootstrap admin → pre-check
      seats vía /api/v1/health/license fail-fast → users → keys → budgets), poblaciones
      `populations/gate-{125,250,500}.yaml` (distribución R5), idempotente + verify-only
- [ ] T021 [US1] Tests seeder en `harness/tests/unit/test_seeder.py` (pre-check con
      población>seats → falla ANTES; orden users→keys; distribución suma exacta)
- [ ] T022 [US1] Emitir licencias ITV (300 y 500 seats) con
      `backend/scripts/issue_license.py` — **requiere la privada basa-dev-2026b (JF)**;
      guardarlas FUERA del repo; documentar comando exacto en harness/README

### Escenarios k6 y orquestador

- [ ] T023 [P] [US1] `harness/Dockerfile.k6` + build pineado k6 v1.8.0 + xk6-sse
      v0.1.12 **en x86_64** (re-verificar el build de R1 en la arch real)
- [ ] T024 [P] [US1] `harness/scenarios/`: chat.js (JSON, sin streaming), extension.js
      (X-Basa-Key), coding-sse.js (sse.open, TTFT+cortes), admin.js (paneles JWT) +
      common.js (SharedArray de identidades, tags por superficie/fase, thresholds
      dropped_iterations==0)
- [ ] T025 [US1] `harness/src/reporting/evaluator.py`: evaluador SLO (lee k6 summary +
      /api/v1/health con credencial compliance + report del stub + reconciliación
      audit_logs) → verdict.json según contracts/run-report.md (nulo=FAIL, contador
      retrocede=invalid, bloque nlp sano como precondición)
- [ ] T026 [US1] `harness/src/reporting/report.py`: reporte.md comparable (overhead
      p50/p95/p99/max por superficie, secciones fijas del contrato)
- [ ] T027 [US1] Orquestador `harness/run_gate.py` (o CLI del módulo): UN comando =
      verificar precondiciones/fingerprint → configurar stub → k6 → recolectar →
      evaluar → reporte; run interrumpido → parcial marcado invalid (quickstart esc. 7)
- [ ] T028 [US1] Tests evaluador/reporte en `harness/tests/unit/test_evaluator.py` con
      fixtures sintéticos (todos los casos del data-model: FAIL por nulo, invalid por
      retroceso, PASS limpio, headroom violado)
- [ ] T029 [US1] **Ensayo local completo**: gate 125 REDUCIDO (población 10, 3 min)
      contra docker-compose dev del repo + stub — valida cableado end-to-end
      (quickstart esc. 1-3 en miniatura) SIN esperar AWS; cierra la open question R2
      (LiteLLM pinneado traduce /v1/messages→openai/ con SSE)
- [ ] T030 [US1] `harness/infra/`: root OpenTofu provider **hcloud** (project
      guardian-itv: SUT ccx33 + generador ccx23 + red privada 10.x + hcloud_firewall
      con deny de EGRESS en el SUT; outputs server_type/datacenter→fingerprint) +
      script de precarga de imágenes (`docker save` en la caja de carga → `load` en el
      SUT ANTES de cerrar el firewall — sin registry, decisión opción (b)) — AUTORABLE
      YA; el apply es [BLOQ-DEVOPS] (espera project+token en Vaultwarden)
- [ ] T031 [US1] [BLOQ-DEVOPS] **Gate 125 OFICIAL en la caja de examen Hetzner**
      (imagen con #97 mergeado) → reporte publicado + primer par de repetibilidad
      (SC-005)

**Checkpoint**: MVP — el examen existe y corre en local; oficial pendiente de AWS.

---

## Phase 4: User Story 3 — Runs comparables (P2, adelantada: no depende de AWS)

- [ ] T032 [P] [US3] `harness/src/reporting/compare.py`: comparador de runs
      (fingerprint diff PRIMERO, tolerancia ±10% p95, interrupted/invalid → no
      comparable)
- [ ] T033 [US3] Tests comparador en `harness/tests/unit/test_compare.py` (fixtures:
      pares idénticos/distintos/inválidos)
- [ ] T034 [US3] [BLOQ-DEVOPS] Par de repetibilidad real del gate 125 + run con config
      cambiada (WEB_CONCURRENCY) → el comparador delata el diff (quickstart esc. 5)

## Phase 5: User Story 2 — Gate 250 con tormenta de login (P2)

- [ ] T035 [P] [US2] `harness/scenarios/login_storm.js` (250 logins/10 min +
      startTime escalonado) + fases separadas por tag en evaluador/reporte
- [ ] T036 [US2] Tests de separación de fases en `harness/tests/unit/test_evaluator.py`
- [ ] T037 [US2] [BLOQ-DEVOPS] **Gate 250 OFICIAL en la caja Hetzner** → reporte
      publicado

## Phase 6: Observabilidad (FR-010/FR-013 — transversal, autorable ya)

- [ ] T038 [P] `harness/observability/centro/`: compose Prometheus (receiver on,
      retención larga) + Grafana OSS + dashboard vivo provisionado como código
- [ ] T039 [P] `harness/observability/sonda/`: compose override del SUT (node_exporter,
      cadvisor, postgres_exporter, prometheus agent-mode remote_write, rotación de logs)
- [ ] T040 `harness/src/observe/collect.py`: colector por run (docker logs
      --since/--until → tarball + export ventana de métricas + rsync a /srv/itv-runs/)
- [ ] T041 [BLOQ-DEVOPS] Deploy del centro en la **CPX21 fija del project guardian-itv**
      (red privada con las cajas de examen — remote_write local; ticket a devops con el
      compose de T038; UI Grafana pública con auth: definir con devops en la semana) +
      k6 remote-write end-to-end

## Phase 7: User Stories 4 y 5 (P3 — definición ya, ejecución ciclo 3)

- [ ] T042 [P] [US4] Dry-run del gate-500.yaml en verde (SC-008 — ya cubierto por
      T012/T014; verificar contra la licencia de 500 emitida en T022)
- [ ] T043 [P] [US5] Definición del smoke US5 (`harness/gates/smoke-real.yaml`):
      presupuesto techo, aliases OpenRouter + Ollama, contraste stub-vs-real —
      ejecución en ciclo 3 (SC-009, previo al gate 500)

## Phase 8: Polish & DoD

- [ ] T044 [P] SC-004 ejecutable: modo fault_injection en el orquestador (override
      masking off + kind marcado) — ensayo local primero, oficial en AWS
- [ ] T045 [P] Docs (regla de las 3 superficies, R6): harness/README completo (runbook
      del examen + comandos de licencia + frontera) + línea en «Arquitectura del repo»
      del README raíz; docs/ producto y docs-cliente NO aplican (economía interna,
      FR-007 de la 025); TechTree se actualiza cuando haya números MEDIDOS
- [ ] T046 Issue(s) al core con evidencia del primer run que falle un SLO (SC-007,
      label team:itv) — el harness produce trabajo accionable
- [ ] T047 Quickstart validation: escenarios 0-5 en verde documentados con outputs

---

## Dependencies & Execution Order

- **Fase 1 → 2 → resto**; dentro de fase, los [P] van en paralelo.
- **Local-first por el bloqueo devops**: T001-T030 + T032-T033 + T035-T036 + T038-T040
  + T042-T045 NO necesitan cloud (T030 se AUTORA ya; solo su apply espera). Los
  [BLOQ-DEVOPS] (apply de T030, T031, T034, T037, T041) entran cuando exista el project
  Hetzner `guardian-itv` + token en Vaultwarden (~lunes 11).
- **Corpus (2a) primero**: es el entregable compartido del #107 — T005 (esquema a
  review del core) es el primer commit de la fase 2.
- **Gate oficial 125 (T031) requiere**: #97 mergeado en la imagen + licencia ITV
  (T022, bloqueada por la privada de JF) + cajas Hetzner arriba con imágenes
  precargadas.
- Orquestación agéntica (DevFlow): Fable orquesta y verifica; agentes Opus codean una
  tarea acotada por brief. Review adversarial en T016/T025 (área de riesgo:
  masking/PII y auditoría — son el corazón del veredicto).

## Implementation Strategy

**Semana 1 (11-15 ago)**: Fases 1-2 + stub + seeder + escenarios + ensayo local T029
(el examen corre en miniatura el miércoles). En cuanto devops entregue: tofu apply +
gate 125 oficial.
**Semana 2 (18-21 ago)**: gate 250 + pares de repetibilidad + SC-004 + reportes
publicados = **DoD del ciclo (SC-001)**. Colchón: el corte mínimo de observabilidad
(R3) si el centro se demora.
