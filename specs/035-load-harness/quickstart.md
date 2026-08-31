# Quickstart — Validación end-to-end del harness (spec 035)

Guía de validación: escenarios ejecutables que prueban que el instrumento funciona,
en orden de construcción. Referencias: [contracts/](contracts/) y
[data-model.md](data-model.md); implementación en `tasks.md` (fase 2).

## Prerrequisitos

1. **Infra**: `tofu apply` en el root ITV (par c6i en eu-central-1; outputs → fingerprint).
   Verificar ANTES: cuota de vCPU de la cuenta ≥12 en la región.
2. **Licencias ITV**: emitidas in-house con `backend/scripts/issue_license.py`
   (kid `sentinel-dev-2026b`; una de 300 y una de 500 seats; requiere la clave privada —
   custodia a confirmar con JF). Montadas como `client.lic` +
   `SENTINEL_ALLOW_DEV_LICENSE=true`. JAMÁS `issue_dev_license.py` sobre stack vivo.
3. **SUT**: `compose.prod.yml --profile selfhosted` con el perfil
   `deploy/clients/itv-examen/` (model_list → stub, `SENTINEL_GW_ANTHROPIC_BASE` → stub,
   provider keys vacías) + Security Group sin egress.
4. **Observabilidad**: centro (Prometheus+Grafana) arriba en el servidor persistente;
   sonda (exporters + agent) en el override del SUT.
5. **Binario k6** v1.8.0+xk6-sse construido (x86_64) y versionado.

## Escenario 0 — El instrumento se prueba a sí mismo (pytest, sin stack)

```bash
cd harness && pytest tests/ -q
```
**Esperado**: verde. Cubre evaluador SLO (nulo→FAIL, contador retrocede→invalid),
detector de canarios (incl. canario partido entre chunks SSE), generador de corpus
(determinismo, unicidad por run, matchea reconocedores del producto), comparador de
fingerprints, pre-check del seeder, contracts del stub in-process.

## Escenario 1 — Smoke del cableado (¿el 100% del tráfico pasa por el stub?)

Una request por superficie (chat JWT, extensión key, coding byok SSE, passthrough) →
`GET /control/report` del stub.
**Esperado**: 4 requests contadas por alias correcto, 0 endpoints 404, frames SSE bien
formados end-to-end (LiteLLM pinneado traduce `/v1/messages`→`openai/` — la open
question de R2 se cierra acá ANTES de dar por buena la matriz).

## Escenario 2 — Seed del gate 125 con pre-check

```bash
harness seed --population populations/gate-125.yaml   # (comando ilustrativo)
```
**Esperado**: pre-check de seats vía `/api/v1/health/license` OK; 125 users + keys +
budgets en <5 min; re-ejecución converge (idempotente); `verify-only` pasa; con
licencia insuficiente a propósito → falla ANTES de tocar nada, mensaje accionable.

## Escenario 3 — Gate 125 completo con UN comando (US1, SC-006)

```bash
harness gate run 125    # ≤30 min de preparación desde entorno provisto
```
**Esperado**: fingerprint verificado (precondiciones `stack_config_required`), 30 min
de carga sostenida con las 4 superficies, tablero vivo en Grafana, y al cierre:
`verdict.json` + `fingerprint.json` + `reporte.md` con veredicto por SLO SIN análisis
manual, `dropped_iterations == 0`, headroom del stub dentro de umbrales, coste API $0.

## Escenario 4 — La prueba del detector (SC-004, run `fault_injection`)

Mismo gate con override `masking: off` (queda en fingerprint, jamás compite como
oficial). **Esperado**: canarios detectados > 0, SLO (c) FAIL con LeakEvidence; el
barrido post-run del spool coincide con el detector inline. Después, run sano → 0.
**Sin este escenario en verde, ningún «0 fugas» de un gate cuenta como evidencia.**

## Escenario 5 — Repetibilidad y comparación (US3, SC-005)

Dos runs consecutivos del gate 125 sin tocar nada → comparador: fingerprints idénticos,
veredictos iguales, overhead p95 dentro de ±10%. Luego cambiar una config del stack
(p. ej. WEB_CONCURRENCY) y repetir → el comparador delata el diff de fingerprint y
marca la comparación ilegítima.

## Escenario 6 — Gate 250 con tormenta (US2)

**Esperado**: 250 logins concentrados en 10 min + fase sostenida; reporte separa fases;
SLOs evaluados en ambas.

## Escenario 7 — Run interrumpido (edge case)

Matar el runner a mitad de un run. **Esperado**: reporte parcial `interrupted`, marcado
no comparable; nada que parezca un examen completo.

## Escenario 8 — Smoke con proveedor real (US5, SC-009 — previo al gate 500)

Población pequeña, presupuesto techo declarado (OpenRouter + camino Ollama).
**Esperado**: gasto ≤ presupuesto (corte automático al alcanzarlo), reporte de
contraste stub-vs-real con divergencias señaladas.

## DoD del ciclo 1 contra esta guía

Escenarios 0-5 en verde + gate 125 y gate 250 **medidos** (pasen o no) con reportes
comparables publicados en la plataforma = SC-001 cumplido. Escenario 8 y gate 500:
ciclo 3 (SC-008: la definición del gate 500 valida en seco ya en ciclo 1).
