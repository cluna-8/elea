# Implementation Plan: Motor de análisis exacto de datos (DB-GPT) para Eleia Hub

**Branch**: `044-hub-chat-panel-admin` (spec 048 se desarrolla sobre la misma rama que 043/044,
mismo criterio ya usado para 043-047 en este repo) | **Date**: 2026-09-10 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/048-motor-analisis-exacto-dbgpt/spec.md`

## Summary

Desplegar DB-GPT como contenedor Docker aislado de red (solo alcanzable desde `backend/`),
configurado para resolver TODAS sus llamadas de modelo contra el motor interno de Eleia
(LiteLLM) vía su soporte nativo de proveedor `proxy/openai` (`OPENAI_API_BASE`/`OPENAI_API_KEY`),
con una llave de servicio nueva (`svc.dbgpt-excel`, `can_act_on_behalf=true`) que atribuye cada
pregunta a la persona real. El backend expone un endpoint propio (`/api/v1/exact-analysis/...`)
que verifica pertenencia de espacio (reusa `Workspace`/`WorkspaceMembership` de la 043),
enforcement de presupuesto (402) ANTES de reenviar, y valida que el SQL que DB-GPT ejecuta sea
de solo lectura — el backend actúa de proxy de autenticación/atribución entre `client/` y DB-GPT,
que nunca es alcanzable directamente desde fuera.

## Technical Context

**Language/Version**: Python 3.12 (backend, mismo runtime que el resto de `backend/`)

**Primary Dependencies**: FastAPI (ya en uso), `httpx` (proxy hacia DB-GPT, ya en uso en el
backend para otras integraciones), `sqlglot` (validar que el SQL que DB-GPT ejecuta sea
solo-lectura — nueva dependencia, MIT, sin binarios nativos)

**Storage**: PostgreSQL (mismo esquema — nuevas filas de `Workspace` tipo "análisis exacto" o
tabla dedicada, decisión abajo en Project Structure/data-model); DB-GPT persiste su propio estado
(SQLite + Chroma por default) en un volumen Docker dedicado, nunca compartido con el esquema de
Eleia

**Testing**: pytest (backend, mismo patrón que el resto de `backend/tests/`) — dobles HTTP reales
del motor DB-GPT (mismo criterio que `client/tests/mock-servers.js`, pero en Python) para no
depender de una instancia real en CI

**Target Platform**: Linux server, Docker Compose (dev) / `elea-installer` (producción)

**Project Type**: web-service (extensión del backend existente + un contenedor nuevo)

**Performance Goals**: sin objetivo numérico propio — hereda el mismo criterio de latencia
"aceptable para chat interactivo" del resto del producto; DB-GPT + un modelo Azure real son el
cuello de botella, no el proxy del backend

**Constraints**: **el contenedor DB-GPT MUST NOT tener ningún puerto publicado hacia el host ni
hacia ninguna red fuera de la interna del backend** (FR-002, mitiga CVE-2026-80104) — esta es la
restricción no negociable de todo el diseño, todo lo demás se subordina a ella

**Scale/Scope**: una instancia de DB-GPT por despliegue (no multi-tenant a nivel de contenedor —
el aislamiento entre personas/tenants lo hace el backend antes de reenviar, igual que ya hace con
AnythingLLM)

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principio | Chequeo | Resultado |
|---|---|---|
| I. Privacy & PII/PHI Masking-First | ¿El enmascarado ocurre ANTES de que el dato llegue al motor, con mapa reversible? | ✅ Reusa el pipeline de enmascarado ya existente (mismo que protege la subida a AnythingLLM) — se enmascara al cargar la planilla, antes de que DB-GPT la indexe. Ningún dato crudo cruza hacia DB-GPT. |
| II. Compliance & Governance | ¿Auditoría metadata-only, sin persistir contenido? | ✅ El SQL ejecutado se audita (evidencia auditable, spec 048 Key Entities), nunca el contenido de las filas. |
| V. Cost Governance | ¿Presupuesto 402 pre-request, atribución por persona? | ✅ Es el requisito central de esta spec (FR-004/FR-005/FR-008) — el backend hace el chequeo 402 ANTES de reenviar a DB-GPT, y toda llamada de modelo de DB-GPT lleva el header "en nombre de" hacia el motor interno. |
| VI. LiteLLM-Native, No Patching | ¿Se reutiliza el motor existente en vez de reimplementar? | ✅ DB-GPT NO trae su propio motor de modelos — se configura como cliente del motor LiteLLM ya existente (`provider=proxy/openai` apuntando al engine interno), cero motor de inferencia nuevo. |
| VII. Containerized & White-Label | ¿Naming neutro, sin exponer "DB-GPT" al usuario? | ✅ FR-009 lo exige explícitamente; el contenedor se llama `exact-analysis-engine` en compose, nunca "dbgpt" en ningún string visible al usuario. |
| Seguridad — Fail-closed en identidad | ¿Ninguna request sin key/token válido cae a un fallback admin? | ✅ El backend exige sesión JWT válida antes de aceptar cualquier pedido de análisis exacto — mismo `require_role`/`get_current_user` que el resto de la API. |
| Seguridad — Tenant Isolation | ¿RLS/tenant_id en las tablas nuevas? | ✅ Reusa `Workspace`/`WorkspaceMembership` (ya RLS-forzado desde la migración 018) — no se crea ninguna tabla nueva sin ese mismo tratamiento. |

**Sin violaciones que requieran justificación en Complexity Tracking.**

## Project Structure

### Documentation (this feature)

```text
specs/048-motor-analisis-exacto-dbgpt/
├── plan.md              # This file
├── research.md           # Phase 0 output
├── data-model.md          # Phase 1 output
├── quickstart.md           # Phase 1 output
├── contracts/              # Phase 1 output
└── tasks.md                # Phase 2 output (/speckit-tasks, no esta spec)
```

### Source Code (repository root)

```text
backend/
├── src/
│   ├── api/
│   │   └── exact_analysis.py       # NUEVO — endpoints /api/v1/exact-analysis/*
│   ├── services/
│   │   └── exact_analysis_service.py  # NUEVO — proxy hacia DB-GPT, validación SQL, atribución
│   └── models/
│       └── workspace.py            # EXTENDER — Workspace.kind ("rag" | "exact_analysis")
├── tests/
│   ├── contract/
│   │   └── test_exact_analysis_sql_readonly.py   # NUEVO
│   └── integration/
│       └── test_exact_analysis_aislamiento.py    # NUEVO
└── scripts/
    └── bootstrap_dbgpt_service_key.py  # NUEVO — mismo patrón que la llave de AnythingLLM

docker-compose.yml            # EXTENDER — servicio `exact-analysis-engine` (imagen DB-GPT), SIN
                               # puertos publicados, en una red Docker dedicada que solo `backend`
                               # también integra
elea-installer/docker-compose.yml   # EXTENDER — mismo servicio para producción

client/
└── server.js                # EXTENDER (spec 046, fuera de esta spec — punto de integración
                              # que esta spec deja como interfaz clara: POST /api/v1/exact-
                              # analysis/query)
```

**Structure Decision**: extensión del backend existente (`backend/src/api/`,
`backend/src/services/`) — no un servicio Python nuevo separado, porque el requisito central
(FR-002: DB-GPT nunca alcanzable salvo desde el backend) ya obliga a que el backend sea el único
punto de red intermedio; agregar un tercer servicio solo para el proxy sumaría un salto de red sin
ganancia. `Workspace` de la 043 se extiende con un `kind` en vez de crear una entidad paralela —
reusa RLS, membresías y el patrón "sin asignar" ya construidos, evitando duplicar ese trabajo
(Reuse over Reinvent, Development Workflow #2).

## Complexity Tracking

*Sin violaciones — tabla omitida.*
