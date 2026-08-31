# Implementation Plan: Auditoría durable — bloqueos registrados, escritura ruidosa, UI honesta

**Branch**: `031-durable-audit` | **Date**: 2026-07-28 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/031-durable-audit/spec.md`

## Summary

Pagar la deuda central del producto («logueamos TODO» pero los bloqueos no dejan rastro
durable): (US1) los 3 planos registran bloqueos en `audit_logs` con la regla
**registrar→bloquear** — chat backend escribe la fila ANTES del raise en sus 3 puntos; el
guardrail del motor escribe vía el plano interno HTTP existente antes de rechazar; el
passthrough conserva su fila pero deja de pasar por tragadores. (US2) la escritura de
auditoría gana **reintento acotado + contador de pérdidas en Redis + banner en UI + campo
en health**, con política `audit_fail=open|closed` por instalación (default `open`;
`closed` = 503 honesto antes de llamar al proveedor, patrón fail-closed de licencias 021).
(US3) UI honesta: guardianes cloud como catálogo «próximamente/no instalado» (no toggles),
los reales declaran su plano; «Retención» declara que la purga llega con la 018; filtro
«bloqueados» de primera clase en Logs. **Sin migración de esquema**: `compliance_status`
(valor `blocked_by_policy` ya documentado en el modelo), `blocked_by_layer` (027) y la
atribución existente alcanzan. Fuera: purga (018), 5 guardianes cloud, dead-letter (FR-009).

## Technical Context

**Language/Version**: Python 3.11 (FastAPI backend + extensiones LiteLLM sin patching) +
TypeScript/React (frontend)

**Primary Dependencies**: SQLAlchemy (audit_logs existente), Redis (contador de pérdidas +
vitrina intacta), httpx (extensión motor → plano interno), extensiones LiteLLM ya montadas
(`litellm/extensions/sentinel_guardrail.py`, `sentinel_audit_logger.py`)

**Storage**: `audit_logs` existente (cero columnas nuevas — ver Constitution Check II);
Redis: `sentinel:audit:lost` (contador) + `sentinel:audit:last_fail` (timestamp) compartidos por
los productores (el motor ya escribe en Redis: es productor de la vitrina)

**Testing**: pytest (harness `build_app_client` + fake httpx namespace; suite 021
hash-chain como gate de no-regresión SC-003); verificación viva por plano (quickstart)

**Target Platform**: Docker on-prem (bundle piloto; `audit_fail` por env del perfil)

**Project Type**: Web application — estructura existente

**Performance Goals**: overhead de auditoría ≤ ~50 ms por request en camino feliz (reuso
de la sesión DB existente); reintento acotado que no convierte una caída de DB en un DoS
interno (edge case de la spec: presupuesto fijo, sin cola infinita)

**Constraints**: registrar→bloquear en los 3 planos; jamás `print` (logging real); el
motor no tiene driver de Postgres (plano interno HTTP, restricción conocida de la imagen);
hash-chain 021 intacta (los eslabones `model='license'` y su verificación posicional de
`guardian_events`); vitrina efímera NO cambia; metadata-only (jamás texto del prompt)

**Scale/Scope**: piloto single-tenant; 3 planos de escritura, ~6 ficheros backend, 2
extensiones motor, 3 páginas frontend

## Constitution Check

| Principio | Veredicto | Nota |
|---|---|---|
| I. Masking-First | ✅ PASS | Las filas de bloqueo llevan conteos/tipos de entidades, jamás valores ni texto del prompt (metadata-only, igual que hoy). |
| II. Compliance FIRST | ✅ PASS | ESTA spec es el principio II hecho código: la evidencia auditada deja de tener el agujero de los bloqueos. Sin esquema paralelo: valores en columnas existentes. |
| III. Multi-Tenant (forward) | ✅ PASS | Filas con tenant_id existente; `audit_fail` es config de instalación (per-tenant cuando toque). |
| IV. White-Label | ✅ PASS | `audit_fail` viaja en el perfil/env del cliente, no en imagen. |
| V. Cost Governance | ✅ PASS | `closed` rechaza ANTES de llamar al proveedor: no se gasta dinero en tráfico inauditable (FR-005). |
| VI. LiteLLM-Native | ✅ PASS | Todo en extensiones montadas (guardrail/logger); el evento del motor viaja por el plano interno HTTP existente. Cero parches al motor. |
| VII. Onboarding as Data | ✅ PASS | Default `open` en el perfil del piloto (seed), `closed` como dato de perfil. |
| VIII. Transparencia | ✅ PASS | US3 entera: la UI declara estado real (guardianes, retención, pérdidas de auditoría visibles). |

**Violaciones**: ninguna.

## Project Structure

### Documentation (this feature)

```text
specs/031-durable-audit/
├── plan.md              # Este fichero
├── research.md          # Fase 0 — decisiones D1-D8 con evidencia file:line
├── quickstart.md        # Fase 1 — verificación por plano + caída de DB en vivo
├── contracts/
│   └── audit-durable.md # Fase 1 — payload interno extendido, health, env, estados UI
└── tasks.md             # Fase 2 (/speckit-tasks)
```

(Sin data-model.md: cero entidades nuevas — la spec lo asume y el modelo lo confirma:
`compliance_status` String con `blocked_by_policy` documentado en audit.py:27,
`blocked_by_layer` de la 027 en audit.py:45.)

### Source Code (repository root)

```text
backend/src/
├── services/audit_service.py       # Núcleo US2: retry acotado + contador Redis + logging
│                                   #   real + modo closed; reusar log_transaction para
│                                   #   filas de bloqueo (tokens 0, coste 0, status bloqueado)
├── api/chat.py                     # US1: fila durable ANTES del raise en los 3 puntos
│                                   #   (~598 AI-Act, ~728 guardián, ~839 residencia)
├── api/gateway.py                  # US1: el _audit del passthrough deja de tragar (US2);
│                                   #   camino closed en passthrough y byok
├── api/internal.py                 # US1: payload de bloqueo en el endpoint interno de
│                                   #   audit (retrocompatible) + probe para closed
├── api/health.py                   # US2: bloque audit {mode, lost_events, last_failure}
└── api/audit.py                    # FR-006: filtro estado=bloqueado de primera clase

litellm/extensions/
├── sentinel_guardrail.py               # US1: registrar→bloquear (POST interno con identidad
│                                   #   de la Connection) en sus puntos de bloqueo
└── sentinel_audit_logger.py            # US2: prints→logging, retry acotado, contador Redis

frontend/src/pages/
├── AuditPage.tsx                   # US1/US2: filtro «Bloqueados» + badge rojo + banner
│                                   #   «N eventos no registrados desde HH:MM»
├── página de guardianes (nombre real a confirmar en tasks)  # US3: catálogo honesto
└── pestaña Retención (CompliancePage) # US3: estado real de la purga

deploy/
├── clients/camara-comercio/…      # audit_fail=open explícito en el perfil (seed)
└── docker/compose.prod.yml        # env SENTINEL_AUDIT_FAIL cableada al backend y al motor
```

**Structure Decision**: cero módulos nuevos de backend — la spec endurece caminos
existentes en su sitio. El único "componente" nuevo es el contador de pérdidas: un par de
claves Redis con helpers en `audit_service.py`; las extensiones del motor reimplementan el
incremento en su proceso (no comparten código con el backend — restricción de imagen
conocida).

## Complexity Tracking

Sin violaciones constitucionales que justificar.
