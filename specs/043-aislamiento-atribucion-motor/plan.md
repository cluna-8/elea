# Implementation Plan: Aislamiento por usuario, atribución de gasto y enmascarado determinista (motor + backend + instalador)

**Branch**: `043-aislamiento-atribucion-motor` | **Date**: 2026-09-08 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/043-aislamiento-atribucion-motor/spec.md`. Diagnóstico con evidencia file:line en [diagnostico.md](./diagnostico.md).

## Summary

Cerrar tres bugs reportados por el cliente Elea, confirmados en código: (1) el Hub Chat no aísla
espacios de trabajo/hilos por usuario y ~10 endpoints de historial no exigen sesión; (2) el
enmascarado de PII usa un nonce aleatorio por request HTTP, y como el cliente trocea documentos en
varias llamadas, el mismo valor recibe placeholders distintos dentro del mismo documento; (3) el
gasto del camino RAG queda atribuido a dos cuentas de servicio del instalador (`svc.anythingllm-
provider`, `svc.rag-masking`) en vez de al usuario final, y la columna `audit_logs.model` mezcla
modelos reales con superficies (`chat-ui`) y marcas de evidencia (`license`).

Enfoque técnico: nueva capa de pertenencia (Workspace↔User) en el backend Guardian como fuente de
verdad de aislamiento (no delegado al motor de documentos, que corre single-user y cuya API admin
varía entre versiones); un mecanismo de identidad "en nombre de" validado en el backend para que
las llaves de servicio propaguen el usuario final a la auditoría y al presupuesto; y determinismo
del placeholder por documento vía el parámetro `nonce` que `PlaceholderMap` ya acepta, sin tocar
la Constitución I (mapa reversible no persistido salvo opt-in ya existente). Todo dentro de
LiteLLM-native (Principio VI): se reutilizan los hooks de auth/guardrail existentes, no se
reimplementa routing ni protocolo.

## Technical Context

**Language/Version**: Python 3.12 (backend Guardian, extensiones del motor LiteLLM); Bash (instalador `elea-installer`).

**Primary Dependencies**: FastAPI 0.111, SQLAlchemy 2.0, Alembic 1.13, Pydantic 2.13, `python-jose` (JWT), `redis` 5.0 (cliente), LiteLLM (motor, versión fijada por el compose — pendiente pinear per FR-007).

**Storage**: PostgreSQL 16 (tabla de verdad para usuarios, workspaces, membresías, auditoría — vía Alembic); Redis 7 (bóveda de PII existente, sesiones si aplica).

**Testing**: Pytest (`backend/tests/{unit,contract,integration,e2e}`), suite de contrato existente para hooks de LiteLLM (`test_policy_unit.py` y equivalentes) — se extiende, no se reemplaza.

**Target Platform**: Linux server, Docker Compose (`db`, `redis`, `engine`, `backend`, `anythingllm` vía `elea-installer`).

**Project Type**: Web service multi-contenedor (backend + motor + storage), consumido por dos clientes (`frontend/`, `client/`) que son la spec 044, fuera de este plan.

**Performance Goals**: sin objetivo de latencia nuevo explícito; el enmascarado ya tiene un piso conocido (~330 car/s por CPU, timeout 15s por chunk — no se degrada). La verificación de pertenencia agrega como máximo una consulta indexada por request.

**Constraints**: enmascarado sigue siendo módulo puro sin I/O en el camino caliente (Principio de diseño ya declarado en `sentinel_guardian_policy.py`) — el determinismo por documento se logra derivando el nonce del `document_id` recibido, sin consultar Redis en `placeholder_for`. Sin streaming de presupuesto (Principio V, no se promete). Cambios en LiteLLM solo vía sus puntos de extensión documentados (Principio VI).

**Scale/Scope**: 1 instalación por cliente (single-tenant on-premise, hoy); ~3 espacios de trabajo y un puñado de usuarios en el piloto de Elea; diseño debe soportar backfill de instalaciones existentes sin downtime (ya se hizo en la 042).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Constitución v2.2.0 (`.specify/memory/constitution.md`). Evaluación contra los 8 principios:

| Principio | Aplica | Evaluación |
|---|---|---|
| I. Privacy & PII/PHI Masking-First | Sí | El determinismo por documento **no** persiste el mapa fuera de lo que la bóveda opt-in (042) ya hace; el nonce deriva de un `document_id` efímero, no del valor. No toca reglas (a)-(d). **PASA**. |
| II. Compliance & Governance FIRST | Parcial | La auditoría "en nombre de" es evidencia adicional (quién autenticó vs. en nombre de quién), no un gate nuevo de compliance. **PASA, sin cambio de nivel**. |
| III. Multi-Tenant by Design | Sí (indirecto) | Workspace/Membership llevan `tenant_id` desde el diseño inicial, coherente con el objetivo forward-looking; no se declara RLS como hecho si no se implementa acá — se documenta como no incluido en este alcance salvo que ya exista en el esquema actual. **Verificar en Phase 0**. |
| IV. Client Onboarding as Data | Sí | `Connection`/`APIKey` con `tool_type` ya existe; las llaves de servicio ganan un `tool_type="servicio"` propio (FR-014) sin tocar el modelo de onboarding. **PASA**. |
| V. Cost Governance & Optimization | Sí | El enforcement 402 debe cerrar el "fallback a admin por defecto" en el camino RAG (mandato explícito de la SC de este principio) — es justamente FR-012. Orden masking→compresión no cambia. **PASA, resuelve deuda declarada**. |
| VI. LiteLLM-Native, No Patching | Sí | El `nonce` de `PlaceholderMap` ya es parámetro del constructor (sin tocar firma); la identidad "en nombre de" se propaga vía el hook de auth existente (`custom_auth.py`), no vía parcheo del router. **PASA**. |
| VII. Containerized & White-Label | Sí | FR-050 a FR-054 son directamente este principio: cerrar la sanitización que falta, sin excepción nueva. **PASA, resuelve deuda declarada**. |
| VIII. Pipeline Transparency | Parcial | La superficie separada del modelo en auditoría (FR-032) mejora `pipeline_metadata`; no se rediseña el Playground. **PASA, sin regresión**. |

**Constraints de seguridad (checklist obligatorio)**:
1. No Raw PII/PHI Storage — sin cambios; el `document_id` no es PII. **OK**.
2. NLP real en prod — sin cambios de postura; FR-025 documenta la mitigación existente (deny-list), no reemplaza Presidio. **OK**.
3. Cerrar el fallback de auth — **este plan lo ejecuta** (FR-012, gate 402 real en el camino RAG). **OK, avanza la deuda**.
4. Tenant Isolation — Workspace/Membership llevan `tenant_id` y se scopean igual que el resto del esquema (`audit.py`, `budget.py`); RLS activo sigue siendo forward-looking global del proyecto, no se declara resuelto acá. **OK, consistente con lo existente**.
5. Encryption — sin cambios; ninguna credencial nueva en claro. **OK**.
6. Auditoría metadata-only — el "usuario final" es un `user_id` (metadato), no contenido. **OK**.

**Resultado del gate**: PASA sin excepciones. No se requiere Complexity Tracking.

## Project Structure

### Documentation (this feature)

```text
specs/043-aislamiento-atribucion-motor/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md         # Phase 1 output
├── quickstart.md         # Phase 1 output
├── contracts/            # Phase 1 output — los 6 contratos que consume la spec 044
│   ├── 01-workspaces-membership.md
│   ├── 02-attribution-on-behalf-of.md
│   ├── 03-masking-document-id.md
│   ├── 04-users-service-accounts-audit-model.md
│   ├── 05-users-lifecycle.md
│   └── 06-branding-neutral.md
├── diagnostico.md         # Ya existía — evidencia file:line del diagnóstico (08-sep)
└── tasks.md               # Phase 2 output (/speckit-tasks — NO se crea acá)
```

### Source Code (repository root)

```text
backend/
├── src/
│   ├── models/
│   │   ├── user.py              # + account_type (persona|servicio), estado de baja
│   │   ├── workspace.py         # NUEVO: Workspace, WorkspaceMembership
│   │   └── audit.py             # + acted_for_user_id, surface (separado de model), event_type
│   ├── api/
│   │   ├── workspaces.py        # NUEVO: CRUD de espacios + membresías, verificación de acceso
│   │   ├── users.py             # + PATCH parcial, DELETE (baja), filtro is_service
│   │   ├── inspect.py           # + document_id en el body, propagación "en nombre de"
│   │   ├── gateway.py           # + acted_for_user_id en _audit(); separar model/surface
│   │   └── costs.py, analytics.py  # excluir surface/evidence de "modelos"
│   ├── licensing/audit_events.py   # sin cambio de semántica, solo relectura por surface/event_type
│   ├── services/
│   │   ├── guardian_service.py     # renombrar seed "(Presidio)" → neutro
│   │   └── workspace_service.py    # NUEVO: lógica de pertenencia, backfill de instalaciones existentes
│   └── schemas/
│       ├── user.py               # PATCH parcial (todos los campos opcionales)
│       └── workspace.py          # NUEVO
├── alembic/versions/
│   └── 018_workspaces_service_accounts_audit_surface.py  # NUEVA migración
└── tests/
    ├── unit/, contract/, integration/, e2e/   # extendidas, no reemplazadas

litellm/extensions/
├── sentinel_guardian_policy.py   # PlaceholderMap: derivar nonce de document_id (ya acepta el parámetro)
├── sentinel_guardrail.py         # sanitización de errores también en el plano /gw
└── custom_auth.py                 # aceptar y validar identidad "en nombre de" desde llaves de servicio

elea-installer/
├── install.sh                     # tool_type de llaves de servicio ≠ "chat-ui"; pin de versión del motor de documentos; comando propio de logs
├── create-tester.sh               # sin cambio de contrato, valida contra el nuevo modelo de usuario
└── docker-compose.yml             # pin de imagen, variables nuevas si aplica
```

**Structure Decision**: Web service existente (backend + motor + storage) extendido en el lugar —
no se crean proyectos nuevos. El único módulo nuevo es `workspace_service.py` +
`models/workspace.py` + `api/workspaces.py` (una capa de pertenencia, patrón ya usado por
`budget.py`/`guardian.py`). Las extensiones de LiteLLM se tocan solo en sus puntos de extensión ya
declarados (Principio VI) — `sentinel_guardian_policy.py` para el nonce, `custom_auth.py` para la
identidad "en nombre de", `sentinel_guardrail.py` para sanitización. `frontend/` y `client/` NO se
tocan en este plan (son la spec 044, que consume los contratos generados en Phase 1).

## Complexity Tracking

*Sin violaciones — tabla omitida.*

## Constitution Check — post-diseño (re-evaluación tras Phase 1)

Con `data-model.md` y `contracts/` completos, se repasa el gate:

- **I. Masking-First**: confirmado en `research.md` R4 — `document_id` es efímero, no persiste
  valor↔documento, la bóveda de la 042 no cambia de forma. **PASA**.
- **III. Multi-Tenant**: `Workspace`/`WorkspaceMembership`/`WorkspaceThread` llevan `tenant_id`
  desde el modelo (`data-model.md`), consistente con el resto del esquema. No se declara RLS activo
  como resultado de esta spec — sigue siendo forward-looking global, sin regresión. **PASA**.
- **V. Cost Governance**: el contrato 2 cierra explícitamente el fallback-a-admin (constraint de
  seguridad #3) con 402 pre-request sobre `acted_for_user_id`. **PASA, avanza deuda declarada**.
- **VI. LiteLLM-Native**: ningún contrato toca routing, protocolo ni streaming del motor; el
  `nonce`/HMAC de R4 y la cabecera `X-Guardian-Acting-User` de R2 se leen en los hooks de auth y
  guardrail ya existentes. **PASA**.
- **VII. White-Label**: contrato 6 cierra la sanitización faltante en el plano `/gw` y renombra el
  campo público, con compatibilidad hacia atrás. **PASA**.

**Resultado**: PASA sin excepciones nuevas. Listo para `/speckit-tasks`.
