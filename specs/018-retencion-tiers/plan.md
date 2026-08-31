# Implementation Plan: Retención con dientes — purga programada + tiers de enforcement

**Branch**: `018-retencion-tiers` | **Date**: 2026-08-13 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/018-retencion-tiers/spec.md` — gate de producto SELLADO (JF, 13-ago): DSAR fuera (spec propia Guardian en C3; fix del 500 #193 como tarea suelta), tiers `estricto`/`estándar` sobre el registry 027.

## Summary

Darle dientes a la promesa RGPD Art. 5.1.e que hoy es solo configuración: un **purgador programado** (lotes acotados + ventana horaria, patrón scheduler de `licensing/reconcile.py`) que elimina filas de auditoría vencidas según un **clasificador único compartido** (sin tocar el esquema de `audit_logs`), excluye **permanentemente** la evidencia de licencias —por la FORMA de `guardian_events`, que es lo único que el inspeccionado no escribe: los eslabones de la hash-chain y también las filas legítimas pre-US5 que no la traen—, mata el único texto real durable (`human_reviews.response_text`) bajo el plazo de `prompt_content`, y deja rastro auditable en `purge_log` + una fila resumen de auditoría por corrida. Encima, un **tier de enforcement por instalación** (`estricto`|`estándar`) modelado como capa booleana del registry 027 (cero migración) que fija pisos de retención, postura de fallo de auditoría y consecuencias de capas con grado. Todo nace compatible con el mundo post-017: identidad batch por `tenant_context` y suite verificada con la policy bootstrap eliminada + rol NOSUPERUSER.

## Technical Context

**Language/Version**: Python 3.12 (backend FastAPI + SQLAlchemy 2 + Alembic; sin cambios de stack)

**Primary Dependencies**: FastAPI, SQLAlchemy, psycopg; scheduler = thread daemon con intervalo por env (patrón existente `licensing/reconcile.py::start_scheduler`, `:268-297` — sin dependencia nueva de cron/celery)

**Storage**: PostgreSQL con RLS FORCE (migración 010); **cero migraciones de esquema en esta spec** (FR-002: `audit_logs` intocada; tier = capa registry 027 sin migración; FR-010: UNIQUE global de `log_type` se queda)

**Testing**: pytest (suite backend existente); harness nuevo de "mundo post-017" (fixture que dropea `tenant_isolation_bootstrap` y conecta con rol NOSUPERUSER) para FR-006/SC-004; verificación de carga con el instrumento 035 de La ITV (SC-003, sin infra nueva)

**Target Platform**: Docker Compose — cloud y on-prem air-gap con el mismo código (la purga no requiere egress)

**Project Type**: web-service (backend); el plano motor (litellm/) **NO se toca** en esta spec — decisión explícita para evitar el impuesto del espejo triple

**Performance Goals**: SC-003 — bajo perfil de carga del gate 125 con purga concurrente, los 4 SLOs de oro del examen se mantienen verdes

**Constraints**: DELETE puro (sin particiones) sobre la tabla más caliente del producto → lotes acotados + pausa entre lotes + ventana horaria; edad calculada contra el reloj de la DB (edge case Reloj); idempotencia ante corrida interrumpida (US3-2)

**Scale/Scope**: instalación single-tenant en la práctica (Cámara ~125-500 usuarios ciclo 250/500); backlog inicial de purga potencialmente grande (instalaciones con meses de datos) — la primera corrida converge por lotes, no de un golpe

### Defaults operativos (FR-001 — operables sin redeploy, por env)

| Env | Default | Qué controla |
|---|---|---|
| `SENTINEL_PURGE_ENABLED` | `false` | interruptor maestro del purgador |
| `SENTINEL_PURGE_DRY_RUN` | `true` | simulacro: cuenta lo que caería y deja rastro, no borra |
| `SENTINEL_PURGE_INTERVAL_SECONDS` | `3600` | frecuencia de chequeo del scheduler (corre solo si está en ventana) |
| `SENTINEL_PURGE_WINDOW` | `02:00-05:00` | ventana horaria permitida (hora local de la instalación, `SENTINEL_PURGE_WINDOW_TZ` default `Europe/Madrid`) |
| `SENTINEL_PURGE_BATCH_SIZE` | `5000` | filas por lote de DELETE |
| `SENTINEL_PURGE_BATCH_PAUSE_MS` | `200` | pausa entre lotes (cede la tabla a los lectores calientes) |

*(enmienda aprobada por el manager 13-ago — arranque seguro; letra completa en Contrato 4.)* `SENTINEL_PURGE_ENABLED` pasa de `true` a **`false`** y entra `SENTINEL_PURGE_DRY_RUN=true`, la séptima perilla y la única fuera de la tabla sellada de este plan: se agrega ahora porque los nombres de este bloque todavía no están publicados en la doc del cliente, y hacerlo después de publicar ya sería cambiar el contrato de configuración de las instalaciones existentes. El porqué del `false`: un job de `DELETE` retroactivo no se enciende con un `docker pull`. El `.env` de la sede se escribe hoy y la imagen con purgador llega después; con `true` ahí, ese pull encendería solo un borrado sobre datos del cliente. Encender es un paso explícito del runbook, con reinicio del backend y con el conteo del simulacro ya firmado. La tensión con el Art. 5.1.e queda aceptada por escrito: una retención que todavía no purga se arregla con un `true`; una purga que se encendió sola y borró de más no se arregla con nada.

## Constitution Check

*Constitución 2.2.0 — evaluada pre-Phase 0 y re-evaluada post-diseño: PASS, sin violaciones que justificar.*

- **Principio II (compliance dos niveles, D3)**: esta spec convierte retención de «evidencia configurable» en **enforcement real** sin cambiar la postura de bloqueo en runtime de ningún request — la purga es un job, no un gate. Honestidad D3 preservada: nada se declara «enforced» hasta que SC-001/SC-004 pasen.
- **Security Constraint 1 + 6 (auditoría metadata-only)**: la purga borra metadata; `purge_log` y la fila resumen por corrida guardan **solo conteos/rangos/duración**, jamás contenido. FR-004 además REDUCE contenido real persistido (response_text muere a los 90 d) — movimiento a favor del principio.
- **Principio VI (LiteLLM-native, no patching)**: el plano motor no se toca. El tier `estricto` exige fail-closed de auditoría (FR-008b) **sin reescribir el env espejo**: el backend valida coherencia tier↔`SENTINEL_AUDIT_FAIL` y la incoherencia degrada el health + audita — el espejo triple queda intacto (sin rebundle).
- **Principio III (multi-tenant forward-looking)**: FR-006 es exactamente la parte C2 de esa deuda — los jobs batch nacen con el contrato de identidad del mundo post-017.
- **Workflow (tests que muerden)**: cada FR lleva test con criterio verificable; el harness post-017 es Foundational, no polish.

## Project Structure

### Documentation (this feature)

```text
specs/018-retencion-tiers/
├── spec.md
├── plan.md              # este archivo
├── research.md          # decisiones consolidadas del mapa as-is (workflow 6 agentes, 13-ago)
├── data-model.md        # entidades sin migración: clases, corrida de purga, capa tier
├── quickstart.md        # validación E2E (SC-001/002/004 + smoke del tier)
├── contracts/
│   └── clasificador-identidad-tier.md   # los 3 contratos internos de la spec
├── checklists/requirements.md
└── tasks.md             # /speckit-tasks
```

### Source Code (repository root)

```text
backend/
├── src/
│   ├── services/retention/
│   │   ├── __init__.py
│   │   ├── classifier.py        # FR-002: clasificador único (clase → predicado SQLAlchemy); exclusión de la cadena = PORTÓN POR FORMA de guardian_events, la columna `model` no participa (FR-003)
│   │   └── purger.py            # FR-001/004/005: lotes, ventana, response_text, escritura de purge_log + fila resumen. Lleva además el PISO del plazo (PLAZO_MINIMO_DIAS=1, :536): rechaza retention_days<1 en el punto de destrucción, abortando la clase y no la corrida — segunda red de FR-007, ver data-model.md
│   ├── services/retention_scheduler.py  # thread daemon, patrón reconcile.start_scheduler (reconcile.py:268-297, _loop en :285, Thread daemon en :294), wiring en main startup
│   ├── api/
│   │   ├── audit.py             # refactor: BLOQUEADO_LIKE/MODELO_LICENCIA/rejected% → consume classifier (FR-002). Excluye la cadena por el LITERAL pelado, no por el portón — asimetría deliberada, Contrato 1 regla 5
│   │   └── compliance.py        # FR-007: validación de rangos + pisos por tier en PUT /compliance/retention
│   ├── licensing/audit_events.py  # FR-006: emisor de la cadena pasa de SessionLocal pelado a tenant_context
│   └── database.py              # sin cambios de contrato; tenant_context(None, bypass=True) es el mecanismo (docstring ampliado)
├── tests/
│   ├── integration/test_retention_purge.py      # US1: SC-001, edge cases (caliente, reloj, huérfanos, cadena intercalada)
│   ├── integration/test_retention_tiers.py      # US2: pisos, SIEMPRE-evalúa, cambio auditado
│   ├── integration/test_purge_post017.py        # FR-006/SC-004: fixture bootstrap-dropeada + rol NOSUPERUSER
│   └── unit/test_retention_classifier.py        # tabla de clases vs seed 004, portón por forma medido contra Postgres, cobertura total de filas, y el TEST VERDUGO que llama al emisor real (Contrato 1 regla 2)
litellm/extensions/sentinel_governance.py            # SOLO alta de la clave de capa en el registry (código puro compartido, sin migración)
```

**Structure Decision**: paquete nuevo `backend/src/services/retention/` para clasificador+purgador (cohesión y testabilidad unitaria), scheduler como módulo hermano siguiendo el precedente de `reconcile`. El único toque fuera del backend es el alta de la clave `enforcement_tier_estricto` en el registry puro compartido (`sentinel_governance.py`) — cambio de código sin migración, que el resolutor del motor ignora con seguridad (capas desconocidas se ignoran por diseño 027) y solo el backend consume.

## Complexity Tracking

Sin violaciones de constitución que justificar. Riesgo señalado (no violación): el refactor de `audit.py` a consumir el clasificador debe ser conservador — la vitrina es superficie viva del cliente; el criterio es paridad exacta de resultados pre/post refactor (test de regresión con dataset sembrado).

*(dictamen del manager 14-ago.)* Ese riesgo ya se materializó una vez y por eso la paridad se lee al pie de la letra: excluir la cadena de la vitrina con «literal **más** `seq`» le mostraba al officer una licencia legítima pre-US5 en el balde «bloqueados», mezclada con intentos de fuga — `total=1` donde `main` da `0`. La vitrina vuelve al literal pelado (Contrato 1, regla 5) y la purga se queda con el portón por forma. **Que los dos criterios no coincidan es la decisión, no el descuido**: la purga es irreversible y no confía en una columna que escribe el inspeccionado; la vitrina es reversible y el literal ya es nuestro gracias a la Capa B.
