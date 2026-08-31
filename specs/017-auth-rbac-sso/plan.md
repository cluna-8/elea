# Implementation Plan: Identidad con dientes — matriz RBAC definitiva, SSO Entra y RLS despierta

**Branch**: `017-auth-rbac-sso` | **Date**: 2026-08-13 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/017-auth-rbac-sso/spec.md` — gate de producto SELLADO (JF, 13-ago): (1) auditor read-only con única excepción resolver reviews, sin probar dueño; (2) rol `lectura` de consulta pura (no chatea, no seat, no dueño); (3) SSO gateado por `feature_flags` de la licencia firmada (primer consumidor del mecanismo 021).

## Summary

Cuatro capítulos sobre el recorte sellado: (A) la **matriz RBAC definitiva** operando SOBRE el shim `effective_roles` (los 15 routers no se renombran), con auditor read-only, rol `lectura` nuevo, actor propagado a las mutaciones (#72) y un harness de matriz rol×endpoint como red; (B) **SSO como contrato de proveedor** con Entra (OIDC auth code vía authlib) como primer módulo — config por tenant con secret Fernet, callback que emite el MISMO JWT, JIT mínimo por email, password como fallback permanente, todo detrás del flag de licencia `sso`; (C) **RLS partida**: tenant claim en el JWT + GUC por request en toda la API de gestión + harness del mundo post-flip (compartido con la 018), con el DROP real como migración env-gated para el release siguiente; (D) **hardening cerrado de 4**: lockout de login, auth events auditados, `expires_at` unificado en los 3 planos, `engine_key_token` cifrado.

## Technical Context

**Language/Version**: Python 3.12 (backend FastAPI + SQLAlchemy 2 + Alembic) · TypeScript/React (frontend: espejo de roles + superficie SSO) · plano motor Python (litellm/extensions — SOLO custom_auth.py para expires_at, ⚠️ merge-order #137)

**Primary Dependencies**: **authlib** (nueva, única dependencia agregada — ver research D2) para OIDC auth code + discovery; Fernet vía servicio de cifrado existente; Redis existente para lockout

**Storage**: PostgreSQL. Migraciones de esta spec: (1) tabla `sso_providers` (config por tenant, patrón GovernanceProfile/012, bajo RLS); (2) CHECK `ck_users_role` ampliado con `lectura`; (3) data-migration re-cifrado de `engine_key_token` + drop de su índice; (4) **migración env-gated APAGADA** del drop de `tenant_isolation_bootstrap` + flip NOSUPERUSER (FR-014 — se entrega lista, no activa)

**Testing**: pytest; harness de matriz rol×endpoint (Foundational); fixture «mundo post-flip» **compartida con la 018** (bootstrap dropeada + NOSUPERUSER); E2E SSO contra el tenant Entra de prueba de DevOps (llega antes del 24-ago; hasta entonces, tests contra IdP falso local — respuesta OIDC simulada)

**Target Platform**: Docker Compose cloud + on-prem. Air-gap: SSO requiere alcanzar el IdP → en sede sin salida queda apagado y el login local es el camino (FR-009); authlib viaja en la imagen, cero egress en reposo

**Project Type**: web-service + frontend + un toque quirúrgico al plano motor

**Performance Goals**: sin cambios de SLO; el GUC por request agrega un SET local por transacción (mismo costo ya pagado por el gateway en :901)

**Constraints**: cero regresión para la Cámara (SC-007); tokens viejos sin tenant claim válidos ≤24 h con tenant default; `custom_auth.py` NO se toca hasta sellar merge-order con #137 (precondición de tasks)

**Scale/Scope**: 15 routers gateados + chat JWT; 5 roles canónicos; 1 proveedor SSO (Entra); las ~5 ediciones acopladas del rol nuevo van como UN paquete

### Defaults operativos (por env, revisables en tasks)

| Env | Default | Qué controla |
|---|---|---|
| `SENTINEL_LOGIN_MAX_ATTEMPTS` | `5` | intentos fallidos antes del lockout |
| `SENTINEL_LOGIN_LOCKOUT_SECONDS` | `900` | duración del lockout |
| `SENTINEL_RLS_STRICT` | `false` | FR-014: la migración del drop+flip solo corre con esto en `true` (release siguiente, con Factory) |

## Constitution Check

*Constitución 2.2.0 — PASS pre-Phase 0 y post-diseño; sin violaciones que justificar.*

- **Security Constraint 3 (fail-closed en identidad)**: todo lo nuevo es fail-closed — lockout, flag `sso` ausente = apagado, config SSO rota degrada SOLO el camino SSO con el login local intacto (FR-009 es fallback declarado, no fail-open silencioso).
- **Security Constraint 4 (tenant isolation / RLS activo)**: el capítulo C es exactamente la parte C2 de esa constraint; el flip final queda entregado y PROBADO (FR-013) aunque apagado — honestidad D7 (forward-looking no se declara hecho).
- **Security Constraint 5 (Fernet para secretos en reposo)**: client_secret del IdP y `engine_key_token` pasan a Fernet — FR-018 cierra una violación VIGENTE de esta constraint (sk-sentinel entera en claro e indexada).
- **Principio III / D9 (RBAC reconciliado)**: la matriz implementa D9 tal cual (super_admin/tenant_admin/compliance_officer/client + `lectura` nuevo; labels sectoriales siguen como display). El shim se consagra como capa de traducción — el rename cosmético queda fuera (blast radius).
- **Principio VI (LiteLLM-native)**: el único toque al motor es `custom_auth.py` (expires_at) — punto de extensión ya nuestro, con test de contrato; nada del motor se parchea.
- **Principio II**: los auth events son evidencia (nivel 2), clase `security_events` del clasificador 018 — sin cambiar posturas de bloqueo en runtime.
- **Constraint 6 (metadata-only)**: los auth events registran actor/resultado/timestamps, jamás passwords ni tokens.

## Project Structure

### Documentation (this feature)

```text
specs/017-auth-rbac-sso/
├── spec.md · plan.md · research.md · data-model.md · quickstart.md
├── contracts/
│   ├── matriz-roles.md          # LA matriz canónica rol×superficie (fuente única, consumida por código y harness)
│   └── proveedor-sso.md         # contrato de proveedor + costura licencia/perfil
├── checklists/requirements.md
└── tasks.md
```

### Source Code (repository root)

```text
backend/
├── src/
│   ├── auth/
│   │   ├── rbac.py              # recableado effective_roles sobre la matriz; PERMISSIONS/ROLE_HIERARCHY borrados; actor inyectado (FR-004)
│   │   ├── matrix.py            # NUEVA fuente única de la matriz (espejo 1:1 de contracts/matriz-roles.md)
│   │   ├── session.py           # tenant claim (FR-011); tolerancia ≤24h token viejo
│   │   └── lockout.py           # FR-015 (Redis, respuesta uniforme)
│   ├── sso/
│   │   ├── registry.py          # contrato de proveedor (FR-006), registry-style 027
│   │   ├── entra.py             # proveedor v1 (authlib, OIDC auth code + discovery)
│   │   └── api.py               # /auth/sso/{login,callback}; gate feature_enabled('sso') (FR-010); JIT (FR-008)
│   ├── services/auth_events.py  # FR-016: emisor de auth events → clase security_events (clasificador 018)
│   ├── api/users.py             # bootstrap sin compliance_officer (FR-002); lockout+audit en login; ROLES_QUE_PRUEBAN_DUENO
│   ├── api/chat.py              # camino JWT del dual-auth gatea rol (lectura NO chatea) + expires_at Playground (FR-017)
│   ├── database.py / deps       # GUC por request desde la identidad (FR-012)
│   └── services/ai_engine_client.py + api/keys.py  # FR-018: engine_key_token Fernet + docstring corregido
├── alembic/versions/            # 013_sso_providers · 014_role_lectura · 015_encrypt_engine_key · 016_rls_strict (env-gated, APAGADA)
├── tests/
│   ├── integration/test_role_matrix.py      # FR-005: harness rol×endpoint (Foundational)
│   ├── integration/test_sso_entra.py        # US2 (IdP falso local + E2E real cuando llegue el tenant)
│   ├── integration/test_rls_post_flip.py    # FR-013 (fixture compartida con 018)
│   └── integration/test_hardening.py        # US4: lockout, auth events, expires_at×3, dump sin claro
frontend/src/                                # espejo de roles (toLegacyRole/nav) + botón SSO condicionado al flag
litellm/extensions/custom_auth.py            # ⚠️ SOLO expires_at (FR-017) — tras sellar merge-order con #137
```

**Structure Decision**: paquete `backend/src/sso/` nuevo y separado de `auth/` — el contrato de proveedor es extensible (Google C3, futuros SCIM/MFA anotados) y no debe enredarse con la sesión local que es el fallback permanente. La matriz vive en `auth/matrix.py` como fuente única que consumen tanto `effective_roles` como el harness — un solo lugar que cambiar, un test que muerde si el código y el contrato divergen.

## Complexity Tracking

Sin violaciones. Riesgos gestionados (no de constitución): merge-order #137/#147 (precondición de tasks, no de spec); dependencia externa del tenant Entra (mitigada con IdP falso local para no bloquear la construcción); las ~5 ediciones acopladas del rol `lectura` empaquetadas en una sola tarea con checklist propio.
