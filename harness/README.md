# harness/ — La ITV 🚗💨 · banco de pruebas de carga (spec 035)

Instrumento que administra **el examen de la Fase 0** de Basa Guardian: mide los gates
de carga **125 / 250 / 500** usuarios activos contra un stack de producción completo,
con veredicto automático por los cuatro SLO de oro (auditoría, PII, bloqueos durables).

> **Frontera del equipo (issue #95): este módulo MIDE, no parchea.** Todo cuello que el
> examen destape (pool, workers, backpressure, streams) se reporta como issue al equipo
> core de Guardian con la evidencia del run. El harness nunca contiene fixes de producto.

Spec, plan y decisiones: [`specs/035-load-harness/`](../specs/035-load-harness/). El
estado del examen no se declara — se demuestra con un número reproducible.

## Estructura

| Ruta | Qué hay |
|---|---|
| `gates/` | Definiciones **versionadas** de cada gate (`gate-125.yaml`…) — data, no código. Cambiar un gate = bump de `version` en PR. |
| `corpus/` | Dataset PII español etiquetado (artefacto compartido con el core, #107) + plantillas por superficie. Los canarios NO se commitean (runtime-only). |
| `scenarios/` | Guiones k6 por superficie (chat, extensión, coding-SSE, admin) + tormenta de login. |
| `src/basa_harness/stub/` | Proveedor simulado (doble wire OpenAI+Anthropic) + centinela de canarios. |
| `src/basa_harness/seeder/` | Aprovisionamiento reproducible de la población vía API real del producto. |
| `src/basa_harness/corpus/` | Generador determinista por semilla + validador del dataset. |
| `src/basa_harness/reporting/` | Cargador de gates, fingerprint, evaluador de SLO, comparador de runs. |
| `src/basa_harness/observe/` | Colector out-of-band (métricas + logs del producto por ventana de run). |
| `observability/` | Compose del centro (Prometheus+Grafana) y de la sonda (exporters). |
| `infra/` | Root OpenTofu del entorno de examen (Hetzner Cloud, project `guardian-itv`). |
| `tests/` | pytest **del instrumento** (unit + contract). Corre en CI sin stack. |
| `runs/` | Scratch local (gitignored). La evidencia persistida va a la plataforma de resultados. |

## Regla de tests (DevFlow del depto)

pytest prueba **el instrumento** con datos sintéticos (evaluador de SLO, detector de
canarios, generador de corpus, comparador) y corre en CI sin levantar el stack. La
prueba del *producto* son los **runs** (gates); la inyección de fallo del detector
(SC-004) se ejecuta como run, no como test unitario.

```bash
cd harness && pytest tests/ -q      # el instrumento se prueba a sí mismo
```

## Cómo correr un gate (referencia — construcción en curso)

El detalle end-to-end vive en
[`quickstart.md`](../specs/035-load-harness/quickstart.md). En una línea: un gate se
lanza con un comando, verifica las precondiciones del stack (fingerprint + config
exigida), genera carga con modelo de llegadas abierto, y produce
`verdict.json` + `fingerprint.json` + `reporte.md` sin análisis manual.

## Drill de saturación (C1)

Un **drill** no pregunta «¿aguanta 125?» sino «cuando NO aguanta, ¿se defiende bien?».
`gates/drill-saturacion-125.yaml` (`kind: drill`) corre en **modo sede-lenta**: el stub
gotea (`token_rate_tps: 5`) con streams largos (60-120 s) que ocupan el tope de
concurrencia al motor durante el sostenido, y **después** una ráfaga global (`burst`,
`arrival_factor: 3` — ×3 sobre TODAS las superficies, dominada por chat por la mezcla
60/25/10/5) encuentra la cola llena. Ahí el backend debe **rechazar rápido**, no colgarse.

Las fases son **secuenciales** (el orquestador escalona el `startTime` de los scenarios
k6): **15 min de examen** = 10 min de sostenido + 5 min de ráfaga. Si el burst arrancara a
la vez que el sostenido, caería sobre una cola fría y el drill no mediría nada.

**Contrato de wire** (sellado con el core — el harness lo mide, no lo define):

| Pieza | Valor |
|---|---|
| Identificación | header `X-Basa-Rejected: saturated` en **todo** 503 de saturación, en los dos caminos (`/api/v1/chat/completions` y `/api/v1/gw/v1/messages`). El header ES la llave: un 503 **sin** él no es rechazo de admisión (puede ser Caddy o un proxy de la sede) y no se cuenta. En chat el body agrega `code: "rejected_saturated"`; en `/gw` el error mantiene shape Anthropic. |
| Estado auditado | fila en `audit_logs` con el estado **literal** `rejected_saturated` (deliberadamente NO es un bloqueo de política). |
| Durabilidad | 1 fila durable por request rechazada, escrita **ANTES** de responder el 503 — incluido el camino del queue-timeout. |

```bash
# 1) baseline: el gate 125 oficial del MISMO día (mismo hardware, misma imagen)
python -m basa_harness.orchestrator --gate 125 --backend-url https://<sut>/

# 2) derivar el presupuesto de admin del baseline (p95 de admin + 50% de margen)
jq '.overhead.admin.medida_ms.p95 * 1.5' runs/<run-id-baseline>/verdict.json

# 3) el drill, con ese umbral (el YAML lo deja en null a propósito: no se hornea)
python -m basa_harness.orchestrator \
  --gate-file gates/drill-saturacion-125.yaml \
  --run-id 20260809-drill-sat-01 \
  --backend-url https://<sut>/ --drill-admin-budget-ms 33
```

El run sale marcado `kind: drill` (lo impone el YAML, no el flag) y el `verdict.json`
suma hasta tres filas **después** de los 4 SLO de oro, que siguen intactos y
obligatorios: `saturated_503_rows_durable` (espejo de los bloqueos durables — negar
servicio sin fila es tan grave como bloquear sin ella), `rejection_time_to_503_p95`
(umbral 6000 ms = queue-timeout de 5 s + 1 s de margen; caza el anti-patrón de los
timeouts de 150 s del incidente del 30-jul) y `admin_latency_budget_p95`. Detalle de las
filas en [`contracts/run-report.md`](../specs/035-load-harness/contracts/run-report.md).

> Los rechazos se cronometran en una Trend **aparte** (`lat_rejection`): un 503 rápido no
> es latencia de servicio y hundiría los percentiles del gate. Y un rechazo **no** cuenta
> como corte de stream en coding — nunca hubo stream que cortar (tampoco emite TTFT). Un
> run de gate oficial sin rechazos produce un verdict idéntico al de antes de C1.

> **Un drill que no llega a saturar es un examen INVÁLIDO, no un PASS**: si no hubo
> rechazos, la defensa nunca se ejercitó y el verdict sale `INVALID` con el motivo (¿stub
> en modo sede-lenta? ¿SUT sobrado?). El `--dry-run` queda afuera de esa regla.
> Sin `--run-id`, el id por defecto lleva el kind (`20260810-g125-drill-01`) para no
> chocar con el del gate oficial del mismo día; y un `run_dir` que ya tiene `verdict.json`
> **no se sobrescribe**: el harness aborta y pide otro `--run-id`.

## Entorno de examen

Hetzner Cloud, project dedicado `guardian-itv` (swap desde AWS aprobado el 08-ago —
ver el addendum de [`research.md`](../specs/035-load-harness/research.md)): SUT CCX33 +
generador CCX23 (vCPU dedicadas) + observabilidad en una CPX21 fija, firewall cloud con
egress bloqueado. **Nunca** se corre carga contra el VPS de producción ni contra
instalaciones de clientes.

El perfil de despliegue del examen vive en
[`deploy/clients/itv-examen/`](../deploy/clients/itv-examen/) (mismo mecanismo que
`camara-comercio`, pero 100% stub-backed y con egress bloqueado).

## Seeder + licencias del examen

El **seeder** (`src/basa_harness/seeder/`) aprovisiona la población del examen —
organización, usuarios por rol, llaves por herramienta, presupuestos — de forma
**reproducible e idempotente** vía la **API REST real** del producto (research R5). El
seed ES el primer mini-examen del plano admin.

Secuencia: bootstrap admin → **pre-check de seats** (`GET /health/license`, fail-fast si
la licencia no alcanza) → users → keys (users PRIMERO: el seat gate corre en ambos) →
budgets. Poblaciones declarativas en `src/basa_harness/seeder/populations/gate-<N>.yaml`
(distribución R5: 125 = 119 client + 4 admin + 2 compliance; 250 = 238+8+4; 500 = 475+17+8).

```bash
# seedear un despliegue (una vez); la semilla fija identidades/passwords deterministas
python -m basa_harness.seeder.seed --gate 125 --backend-url https://<sut>/ --seed 20260808

# entre runs: verificar sin crear nada (sale 1 si falta población)
python -m basa_harness.seeder.seed --gate 125 --backend-url https://<sut>/ --verify-only
```

> La **semilla** se fija una vez por despliegue: cambiarla cambia todas las passwords
> derivadas y exige DB fresca (`down -v`). Las credenciales (`--emit-credentials`) son
> material de RUN: van a `runs/` (gitignored), nunca al repo.

### Licencias in-house — ⚠️ PENDIENTE (T022, requiere la privada de JF)

Los gates necesitan DOS licencias: **300 seats** (125/250) y **500 seats** (500). Se
emiten con `backend/scripts/issue_license.py` reusando el kid horneado `basa-dev-2026b`,
cuya **clave privada NO está en el repo** (custodia de JF; `issue_license.py` está bajo
gate de Cristian en CODEOWNERS). El comando exacto — a correr cuando JF aporte la privada
— está documentado en
[`deploy/clients/itv-examen/README.md`](../deploy/clients/itv-examen/README.md). El
pre-check del seeder ya maneja el caso "licencia insuficiente/ausente" con mensaje
accionable, así que si la licencia no está instalada el seed aborta antes de crear nada.
