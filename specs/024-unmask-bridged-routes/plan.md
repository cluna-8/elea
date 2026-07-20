# Implementation Plan: Restauración de PII y atribución en respuestas byok (rutas bridged)

**Branch**: `024-unmask-bridged-routes` | **Date**: 2026-07-20 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/024-unmask-bridged-routes/spec.md`

## Summary

Cerrar el round-trip mask→unmask en el camino byok del motor para **rutas bridged**
(modelos no-Claude: local via Ollama y cloud puenteados) y devolver la **identidad** a los
eventos del monitor de ese camino. Tres defectos con root cause verificado (spike 019
batch 1 + lectura de código): (1) no-streaming: la respuesta llega como `dict` y el unmask
la ignora por leerla con `getattr`; (2) streaming: los chunks llegan como objetos parseados
y caen en el escape "se entrega tal cual"; (3) atribución: el audit logger busca la
identidad en un solo metadata-home y la ruta anthropic usa el otro. Todo se resuelve en
`litellm/extensions/` (Principio VI: cero parches al motor), con evidencia e2e contra el
motor vivo que hoy no existe (FR-007). Detalle de decisiones: [research.md](research.md).

## Technical Context

**Language/Version**: Python (extensiones del motor corren en el runtime del contenedor
del motor, 3.13; backend 3.11 — el código compartido ya es compatible con ambos)

**Primary Dependencies**: motor LiteLLM 1.92.0 pinneado por digest (hooks CustomGuardrail
+ CustomLogger — solo extensiones montadas, sin parches); lib de política compartida
`litellm/extensions/basa_guardian_policy.py` (carry-split, unmask_text/unmask_deep)

**Storage**: N/A (el mapping pii_tokens vive solo en el ciclo request/response; eventos
del monitor = Redis efímero + tabla audit metadata-only ya existentes — sin cambios de
esquema)

**Testing**: pytest en contenedor backend (suite del DoD via `docker compose run`);
unit sobre las extensiones (shapes fabricados de ambos tipos) + e2e contra motor vivo
con el modelo local del stack dev (`ollama-qwen3-4b`)

**Target Platform**: stack Docker del producto (dev y prod comparten las extensiones por
bind/copy — nada específico de plataforma)

**Project Type**: web-service existente (backend FastAPI + motor con extensiones) — sin
proyectos nuevos

**Performance Goals**: sin regresión perceptible de latencia de streaming (el rewrite por
chunk ya corre en passthrough; el adaptador bridged añade solo extracción de campos por
item)

**Constraints**: FR-003 (payload intacto fuera de los reemplazos), FR-005 (fail-safe:
shape desconocido → passthrough, jamás romper una respuesta), cero persistencia del
mapping

**Scale/Scope**: 2 archivos de extensión (`basa_guardrail.py`, `basa_audit_logger.py`) +
posible helper en la lib de política + tests unit/e2e + docs DoD; sin migraciones, sin
frontend

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principio | Veredicto | Nota |
|---|---|---|
| I. Privacy & Masking-First | ✅ refuerza | Cierra el round-trip del pilar; la protección de ida no se toca (SC-003) |
| II. Compliance FIRST | ✅ | Sin cambios de plano legal; auditoría gana identidad (mejor compliance) |
| III. Multi-Tenant | ✅ | La atribución tenant/client es exactamente lo que se restituye (FR-006) |
| IV. Onboarding as Data | ✅ n/a | Sin superficies nuevas; cero config nueva |
| V. Cost Governance | ✅ n/a | Sin cambios de costos |
| VI. LiteLLM-Native, No Patching | ✅ **gate clave** | Todo en `litellm/extensions/` montadas; el pipeline del motor no se toca |
| VII. White-Label | ✅ n/a | Sin strings de marca; naming neutro en docs (checks existentes) |
| VIII. Transparencia del pipeline | ✅ refuerza | Eventos del monitor completos para byok |

**Violaciones**: ninguna. **Re-check post-diseño**: sin cambios — el diseño de Phase 1 no
introduce proyectos, esquemas ni superficies nuevas.

## Project Structure

### Documentation (this feature)

```text
specs/024-unmask-bridged-routes/
├── plan.md              # Este archivo
├── research.md          # D1-D5: root causes verificados y decisiones
├── data-model.md        # Entidades existentes tocadas (mapping, evento) — sin esquema nuevo
├── quickstart.md        # Verificación viva del round-trip (comandos del spike)
├── contracts/
│   └── unmask-roundtrip.md   # Invariantes del contrato de restauración
└── tasks.md             # (/speckit-tasks — no lo crea este comando)
```

### Source Code (repository root)

```text
litellm/extensions/
├── basa_guardrail.py         # D1: _unmask_response_inplace acepta dict raíz
│                             # D2: iterator hook con adaptador de items parseados
├── basa_guardian_policy.py   # (solo si hace falta) helper carry-split a nivel campo
└── basa_audit_logger.py      # D3: identidad con doble metadata-home

backend/tests/
├── unit/test_unmask_shapes.py        # D1/D2 con shapes fabricados (dict + objeto + SSE)
└── e2e/test_engine_roundtrip_e2e.py  # FR-007: round-trip contra motor vivo + evento con identidad

docs/docs/integrations/               # DoD 022: G9 → resuelto, §3.5 y matriz promovidas
specs/019-integration-surfaces/       # FR-009: registro/matriz PARCIAL → FUNCIONA con evidencia
```

**Structure Decision**: no hay estructura nueva — el fix vive íntegro en las extensiones
existentes del motor (superficie compartida, CODEOWNERS de los tres; review de @cluna-8
pedida por frontera con seguridad) más tests en las carpetas convencionales del backend.

## Complexity Tracking

Sin violaciones constitucionales que justificar.
