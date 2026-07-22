# Implementation Plan: Governance configurable y enforcement honesto del firewall

**Branch**: `027-governance-configurable-enforcement` | **Date**: 2026-07-22 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/027-governance-configurable-enforcement/spec.md`

## Summary

El catálogo de guardianes que la UI muestra como activos no se corresponde con lo que corre: 6 de 9
capas no se ejecutan en ningún plano, la "delegación al motor" se fabrica leyendo solo la DB, y no
existe forma de configurar qué capas aplican por modo de conexión ni por superficie. Esta feature
construye el **marco de gobernanza honesto**: (1) un catálogo de capas **en código** con un piso
no-negociable estructuralmente inapagable; (2) una entidad `GovernanceProfile` (fila-por-decisión,
`NULL=heredar`) que configura las capas opcionales por modo y superficie, por tenant; (3) un
**resolutor puro único** en la librería compartida `basa_guardian_policy`, consumido por los tres
puntos de aplicación (gateway passthrough, guardrail del motor, chat UI); (4) un **estado real
calculado** — declarativo + sonda `GET /guardrails/list` + evidencia por pedido — con default
inseguro (`no_disponible`) y nunca persistido; (5) **atribución por pedido** en campos nuevos
(`applied_layers` + `blocked_by_layer`), dejando `guardian_events` congelado como legado; y (6) una
página Admin nueva "Gobernanza" con autosave-con-rollback (no el botón global que causa el bug
conocido de toggles). Las decisiones y su evidencia `archivo:línea` están en
[research.md](./research.md) (D1-D8).

## Technical Context

**Language/Version**: Python 3.11 (backend FastAPI + extensiones LiteLLM), TypeScript/React 18 (frontend Vite)

**Primary Dependencies**: FastAPI + SQLAlchemy + Alembic (backend); LiteLLM 1.92.0 **pineado por
digest** (motor, extensiones vía puntos documentados: custom_auth, custom guardrail, custom logger);
React/Vite sin router (SPA con `useState<Page>`); librería pura compartida
`litellm/extensions/basa_guardian_policy.py` (importada por ambos planos)

**Storage**: PostgreSQL — base del backend (`basa_gateway`): tabla nueva `governance_profiles` +
2 columnas nuevas en `audit_logs` (`applied_layers` JSONB, `blocked_by_layer` VARCHAR indexable),
migración Alembic. La base del motor (`basa_engine` en prod) NO recibe esquema nuevo. Redis solo
para el feed de monitor existente.

**Testing**: pytest (suite heredada, 226 passing en main) + tests de contrato contra la versión
pineada del motor (patrón `tests/contract/test_route_parity.py` de la 014, que esta feature
**modifica**: la paridad pasa a verificarse sobre el resolutor de perfil). Verificación local con
Docker Compose antes de mergear.

**Target Platform**: Linux server (Docker Compose dev + perfil prod selfhosted/cloud de la 020)

**Project Type**: Web application (backend + frontend + extensiones del motor)

**Performance Goals**: resolución de perfil sin I/O nuevo en el camino caliente — se resuelve donde
ya hay sesión de DB (`_resolve_attribution` en gateway; SQL de identidad + cache 60s en custom_auth).
Sonda al motor cacheada (TTL ~30 s) — nunca una llamada autenticada por pageview.

**Constraints**:
- C1 — auditoría metadata-only: `applied_layers` lleva solo códigos/contadores, jamás texto/PII.
- White-label (Principio VII): la sonda `/guardrails/list` se consume en el backend; su payload
  crudo (nombres de proveedor) jamás llega a la UI.
- Fail-closed en estado: motor inalcanzable → `no_disponible`, jamás `aplicándose`.
- El piso vive en código: ninguna representación en DB puede apagarlo (SC-004 estructural).
- Cache de identidad del motor (60 s): al escribir gobernanza se invalida la entrada por key, o
  SC-006 es falso durante ese minuto.

**Scale/Scope**: 1 tabla nueva + 2 columnas; 1 registry en código (10 capas: 4 piso + 6
gobernables); 1 resolutor puro + 3 call-sites; 1 endpoint de estado + CRUD de perfil; 1 página
Admin nueva; 2 productores de evento de monitor extendidos + emisores en punto de bloqueo en los
3 planos (el del chat es nuevo). Sin proveedores nuevos, sin implementar capas (módulo de
seguridad).

## Constitution Check

*GATE: contra la Constitución 2.0.0 (2026-07-10). Estado: **PASA** con 2 notas.*

| Principio | Veredicto | Nota |
|---|---|---|
| I. Masking-First | ✅ con decisión D8 | El piso se define como **detectar/evaluar/registrar** siempre; el **transformar** (enmascarar) queda gobernado absorbiendo `redact_enabled` (FR-014 de la 013) como decisión de la capa `pii_masking`. Sin D8, FR-002 literal derogaría un requisito entregado de otra spec. **Confirmada por el owner (2026-07-22); spec enmendada.** El principio no se viola: el orden masking-antes-de-compresión y el mapa reversible no se tocan. |
| II. Compliance FIRST | ✅ | La feature ES este principio: honestidad de enforcement (dos niveles, real vs declarado) llevada a runtime. La atribución de bloqueo en el plano motor queda declarada como dependiente de la 018 (corte explícito en research D6) — no se promete lo que el sistema no sostiene, exactamente la disciplina que la constitución exige. |
| III. Multi-Tenant by Design | ✅ | `governance_profiles` nace con `tenant_id` + UNIQUE por tenant + default `DEFAULT_TENANT_ID`, siguiendo el patrón `ComplianceProject`. No se reimplementa la cascada 015 (enum de scope cerrado; punto de enganche documentado). |
| IV. Client Onboarding as Data | ✅ | Los ejes de alcance se anclan a datos existentes de la Connection (`upstream_mode`, `tool_type` con CHECK); configurar gobernanza jamás requiere tocar código ni archivos (FR-012/SC-006). |
| V. Cost Governance | ✅ N/A | No se toca presupuesto ni compresión. La sonda evita el `test_guardrail` facturable (research D4). |
| VI. LiteLLM-Native, No Patching | ✅ | Todo por puntos de extensión documentados: `GET /guardrails/list` (API pública del proxy), header `x-litellm-applied-guardrails` (mecanismo nativo de evidencia), custom_auth/guardrail/logger ya existentes. Contrato cubierto por test contra la imagen pineada (la sonda no está versionada — riesgo mitigado por el pin + test de contrato obligatorio). |
| VII. White-Label | ✅ | `engine_guardrail_name=None` se mantiene en la API pública; el estado se expone, el nombre de proveedor no. Payload de la sonda nunca reenviado crudo. |
| VIII. Pipeline Transparency | ✅ | `applied_layers` es la materialización durable de este principio (hoy `pipeline_metadata` es solo de respuesta y solo del chat). `pipeline_metadata` pasa a derivarse de `applied_layers` en vez de armarse a mano. |
| SC-3 (fail-closed auth) | ✅ | Sin cambios al modelo de identidad; el estado de capa adopta el mismo default inseguro. |
| SC-1/SC-6 (no raw PII) | ✅ | C1 arriba; además se documenta NO copiar el patrón del `detail` con nombre propio (fuga existente, research D6). |

**Nota 1 (única decisión que tocó la letra de la spec)**: D8, **confirmada por el owner el
2026-07-22**. FR-002 y la Assumption del piso quedaron enmendados en la spec en consecuencia.

**Nota 2**: el prerrequisito P1 (identidad del motor rota en perfil prod) es un bug de producto
independiente de esta feature; se trackea aparte y **no** entra en tasks.md.

## Project Structure

### Documentation (this feature)

```text
specs/027-governance-configurable-enforcement/
├── spec.md              # Especificación (committeada)
├── plan.md              # Este archivo
├── research.md          # Fase 0 — decisiones D1-D8 + prerrequisitos P1-P5
├── data-model.md        # Fase 1 — governance_profiles, registry, columnas de audit
├── quickstart.md        # Fase 1 — cómo probar los dos modos y el estado honesto
├── contracts/           # Fase 1 — API de gobernanza + esquema applied_layers
├── checklists/
│   └── requirements.md  # 16/16 PASS (pre-plan)
└── tasks.md             # Fase 2 — /speckit-tasks (NO la genera /speckit-plan)
```

### Source Code (repository root)

```text
backend/
├── src/
│   ├── models/
│   │   ├── governance.py            # NUEVO: GovernanceProfile
│   │   └── audit.py                 # +applied_layers, +blocked_by_layer
│   ├── services/
│   │   ├── governance_catalog.py    # NUEVO: registry GOVERNANCE_LAYERS (D1)
│   │   ├── governance_resolution.py # NUEVO: resolución por tenant (usa el resolutor puro)
│   │   ├── governance_status.py     # NUEVO: estado real calculado (D4: A+B+C)
│   │   ├── guardian_service.py      # −trigger DELEGATED fabricado; seed neutralizado (P2)
│   │   └── ai_engine_client.py      # +sonda /guardrails/list cacheada
│   ├── api/
│   │   ├── governance.py            # NUEVO: router admin-only (estado + CRUD perfil)
│   │   ├── gateway.py               # evaluate_request_policy(body, profile); applied_layers
│   │   ├── chat.py                  # call-site del resolutor; persistencia applied_layers
│   │   ├── inspect.py               # gw_inspect pasa por el Profile (P4)
│   │   └── analytics.py             # agregado sobre applied_layers (deja de mentir)
├── alembic/versions/                # migración 012 (head real: 011) — governance_profiles + columnas audit
├── tests/
│   ├── contract/                    # paridad sobre el resolutor; SC-001 vs /guardrails/list
│   ├── integration/                 # perfil por modo/superficie e2e; piso inviolable
│   └── unit/                        # resolutor puro; función de estado; mapeo de modo (D5)

litellm/
└── extensions/
    ├── basa_guardian_policy.py      # +resolve_profile / apply_layers (resolutor puro, D3)
    ├── basa_guardrail.py            # consume Profile; evidencia applied-guardrails
    ├── custom_auth.py               # +perfil resuelto en metadata.basa; invalidación de cache
    └── basa_audit_logger.py         # +applied_layers/blocked_by_layer en fila y monitor

frontend/
└── src/
    ├── App.tsx                      # Page union + nav item (roles LEGACY ["admin"]) + render
    ├── pages/
    │   ├── GovernancePage.tsx       # NUEVO: estado honesto + config por modo/superficie (D7)
    │   ├── SecurityPage.tsx         # badges leen status calculado, no is_active
    │   └── DashboardPage.tsx        # contador "activos" lee status calculado
    └── services/
        └── api.ts                   # bloque Governance (jsonHeaders + handleExpiredSession)
```

**Structure Decision**: aplicación web existente (backend + frontend + extensiones del motor). No se
crean proyectos nuevos. La única pieza compartida entre planos vive donde ya vive la que existe:
`litellm/extensions/basa_guardian_policy.py`, importada hoy por `gateway.py:76` y
`basa_guardrail.py:40` — así "la misma decisión" es literal, no una convención (patrón de paridad
de la 014).

## Complexity Tracking

> Sin violaciones constitucionales que justificar. Dos decisiones que podrían parecer complejidad
> extra, con su porqué:

| Decisión | Por qué es necesaria | Alternativa más simple rechazada porque |
|-----------|------------|-------------------------------------|
| Registry de capas en código + tabla de decisiones (dos piezas, no una) | El piso solo es inapagable si no está en DB (SC-004 estructural); las decisiones solo son por-tenant si no están en código | Todo-en-DB: el seed destructivo (`guardian_service.py:33-36`) borra la tabla entera y el piso pasa a ser borrable con un UPDATE |
| Estado con 3 fuentes (declarativo + sonda + evidencia) | LiteLLM ignora en silencio nombres de guardrail desconocidos: ninguna fuente sola distingue "corre" de "no-op silencioso" | Solo la sonda: no cubre las capas backend-local ni "requiere credencial"; solo evidencia: capa sin tráfico reciente reportaría falso negativo |
