# Implementation Plan: Auto-router semántico + rediseño «Modelos & Ollama»

**Branch**: `030-semantic-auto-router` | **Date**: 2026-07-28 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/030-semantic-auto-router/spec.md`

## Summary

Portar el auto-router semántico de llm-guardian (spec 015 de aquel repo: embeddings de
utterances por ruta + coseno + umbral + best-of, ~140 líneas) al plano de chat de
basa-guardian, con tres cambios de fondo: **embeddings 100% locales** vía el motor
(`router-embeddings` → `ollama/qwen3-embedding:0.6b`, validado 8/9 en el benchmark del
28-jul), **config caliente editable por admin** (`auto_router.json` en el volumen
`litellm_config`, switch global on/off + timeout + default_model), y **rutas con modelo
destino desacoplado del nombre** (resuelve «¿N modelos de Ollama, a cuál va?»). El panel
vive embebido en «Modelos & Ollama». La decisión de ruteo es transparente de punta a punta:
Debugger Técnico (`pipeline_metadata.layer_llm.auto_router`), vitrina «Conexiones en vivo»
(nuevo evento de éxito del plano chat) y auditoría durable (columna JSONB nueva
`routing_decision`, metadata-only). Además, US3: todo modelo cloud nace con fallback al
modelo local (write en el alta + seed), sin fallback local→cloud jamás.

## Technical Context

**Language/Version**: Python 3.11 (FastAPI backend) + TypeScript/React 18 (Vite frontend)

**Primary Dependencies**: FastAPI, httpx, Redis (cache de vectores + vitrina), SQLAlchemy +
Alembic (auditoría), LiteLLM (motor, sin patching — Principio VI), Ollama (embeddings y
modelo local)

**Storage**: `auto_router.json` en volumen `litellm_config` (config caliente, RW backend —
patrón nuevo pero volumen ya montado y chowneado, ver research R3); PostgreSQL para
auditoría (migración 013, columna `routing_decision` JSONB nullable); Redis para cache de
embeddings (`autoroute:emb:*`, TTL 7d, versión de cache v3)

**Testing**: pytest (unit + integration con mock de httpx a nivel de namespace del módulo,
patrón `test_chat_attribution.py`; smoke vivo estilo `test_chat_smoke.py` auto-skip);
benchmark reproducible `bench_embeddings.py` contra el stack levantado (SC-001)

**Target Platform**: Docker on-prem (bundle white-label amd64; dev arm64 en Mac)

**Project Type**: Web application (backend FastAPI + frontend React) — estructura existente

**Performance Goals**: ruteo p50 ≤ 1,5 s en frío razonable / ≤ 400 ms con cache caliente
(SC-002); switch OFF = cero llamadas de embeddings (SC-003)

**Constraints**: el texto de la consulta JAMÁS sale del host para decidir el ruteo (FR-003);
degradación siempre funcional y siempre registrada (FR-004); sin restart del motor para
ediciones de rutas (config caliente del backend, no del motor); la auditoría es
metadata-only (jamás texto del prompt en `routing_decision`); no romper el contrato C1 de
`applied_layers` ni el `guardian_events` congelado por la hash-chain 021

**Scale/Scope**: piloto Cámara (300 seats, single-tenant on-prem); 3 rutas seed, catálogo
de ~3-5 modelos; un evento de ruteo por consulta de chat

## Constitution Check

*GATE: evaluado contra la constitución v2.0.0 antes de Fase 0; re-evaluado tras el diseño.*

| Principio | Veredicto | Nota |
|---|---|---|
| I. Masking-First | ✅ PASS | El ruteo lee el texto crudo SOLO para embeberlo localmente (FR-003); ocurre antes y aparte del pipeline de protección sin cortocircuitarlo (FR-010): el masking hacia el modelo destino aplica idéntico. |
| II. Compliance FIRST | ✅ PASS | `routing_decision` es metadata-only (ruta, score, flags — cero texto). Residencia: embeddings locales refuerzan el default EU/on-host. |
| III. Multi-Tenant (forward) | ✅ PASS | Config única por instalación (single-tenant hoy); el JSON es per-volumen = per-cliente. Multi-tenant heredará config por tenant (asunción de spec, sin bloquear v1). |
| IV. White-Label | ✅ PASS | Seed por config + template (`auto_router.json` al volumen vía populate_volumes.sh), nunca fork. |
| V. Cost Governance honesto | ✅ PASS | FR-009: el coste se calcula sobre el modelo que CONTESTÓ (fix de la asimetría request.model vs routed_model en coste, ver research R7). |
| VI. LiteLLM-Native | ✅ PASS | Cero patching del motor: embeddings vía `/v1/embeddings` estándar; fallbacks vía `router_settings.fallbacks` nativo (ya existe el PUT). El router del motor nativo se descartó en llm-guardian (su config loader exige key OpenAI viva) — replicamos el servicio propio. |
| VII. Client Onboarding as Data | ✅ PASS | Rutas/modelos del piloto = datos de seed del perfil, editables por UI. |
| VIII. Transparencia | ✅ PASS | Decisión visible en Debugger + vitrina + auditoría; degradación SIEMPRE registrada (FR-004). |

**Violaciones**: ninguna. Sin entradas en Complexity Tracking.

## Project Structure

### Documentation (this feature)

```text
specs/030-semantic-auto-router/
├── plan.md              # Este fichero
├── research.md          # Fase 0 — decisiones R1-R9 con evidencia
├── data-model.md        # Fase 1 — schema auto_router.json + columna audit
├── quickstart.md        # Fase 1 — cómo levantar/verificar (incl. benchmark SC-001)
├── contracts/           # Fase 1 — router-config API + chat auto + evento monitor
├── bench_embeddings.py  # Benchmark reproducible (ya en el repo, se adapta al stack)
└── tasks.md             # Fase 2 (/speckit-tasks — NO lo crea /speckit-plan)
```

### Source Code (repository root)

```text
backend/
├── src/
│   ├── services/
│   │   ├── auto_router_service.py        # NUEVO — port adaptado (config caliente, switch,
│   │   │                                 #   timeout, target_model desacoplado, sin ascii-fold,
│   │   │                                 #   cache v3, flag degraded, cero-embeds si OFF)
│   │   └── ai_engine_client.py           # +método embeddings() (patrón test_guardrail:303)
│   ├── api/
│   │   ├── router_config.py              # NUEVO — GET/PUT /chat/router-config (admin-only)
│   │   ├── chat.py                       # model=="auto" → decisión; layer_llm.auto_router;
│   │   │                                 #   publicación de ÉXITO a vitrina; coste por modelo
│   │   │                                 #   efectivo; GET /models añade pseudo-modelo «auto»;
│   │   │                                 #   alta de modelo cloud → fallback default a local
│   │   ├── gateway.py                    # _publish_monitor: campo opcional routing;
│   │   │                                 #   /gw model=="auto" → default local (edge case)
│   │   └── monitor.py                    # label/render del campo routing en la vitrina
│   ├── models/audit.py                   # +columna routing_decision (JSONB nullable)
│   └── services/audit_service.py         # +param routing_decision en log_transaction
├── alembic/versions/013_auto_router_decision.py   # NUEVO — migración
└── tests/
    ├── unit/test_auto_router_service.py           # NUEVO
    └── integration/test_chat_auto_router.py       # NUEVO (patrón test_chat_attribution)

frontend/src/
├── pages/ModelsPage.tsx                  # Sección nueva «Ruteo inteligente» (switch, default,
│   │                                     #   timeout, editor de rutas, estado embeddings,
│   │                                     #   señal de ruta rota; filtra pseudo-modelo auto)
├── pages/PlaygroundPage.tsx              # «Auto» en dropdown (viene de GET /models); badge
│   │                                     #   modelo real + degradado en la respuesta
├── pages/UserPortal.tsx                  # ídem dropdown (ya filtra is_configured)
└── services/api.ts                       # getRouterConfig / putRouterConfig

litellm/
├── auto_router.json                      # NUEVO — seed dev 3 rutas (código/redacción/trivial)
└── config.yaml                           # +router-embeddings → ollama/qwen3-embedding:0.6b

deploy/
├── clients/camara-comercio/config.yaml.tmpl   # +router-embeddings +router_settings base
├── clients/camara-comercio/auto_router.json   # NUEVO — seed piloto (default=local)
├── release/populate_volumes.sh                # copia auto_router.json al volumen
└── release/INSTALL-CAMARA.md                  # +ollama pull qwen3-embedding:0.6b (preflight)
```

**Structure Decision**: se conserva la estructura web-app existente (backend/ + frontend/).
Piezas nuevas mínimas: 1 servicio, 1 router API, 1 migración, 1 sección de UI. El resto son
extensiones quirúrgicas de ficheros existentes en los puntos exactos mapeados en research.md
(§R2 tabla de inserción).

## Complexity Tracking

Sin violaciones constitucionales que justificar.
