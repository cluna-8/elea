# Implementation Plan: LiteLLM Real Integration

**Branch**: `feature/002-litellm-sync` | **Date**: 2026-06-29 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/002-litellm-sync/spec.md`

## Summary

Sincronizar la gestión de usuarios, equipos, presupuestos y virtual keys de nuestra DB con la API de administración de LiteLLM. El backend FastAPI pasa de gestionar presupuestos localmente a delegar el enforcement financiero a LiteLLM, mientras mantiene su rol como capa de seguridad (PII masking, guardianes, audit logs).

## Technical Context

**Language/Version**: Python 3.12 (backend), TypeScript/React 18 (frontend)

**Primary Dependencies**: FastAPI, SQLAlchemy, httpx (para llamadas HTTP a LiteLLM), React + TailwindCSS

**Storage**: PostgreSQL (nuestra DB) + PostgreSQL de LiteLLM (compartida, misma instancia)

**Testing**: Manual via Swagger UI + curl para validar sincronización con LiteLLM

**Target Platform**: Docker Compose (desarrollo local) → producción en contenedores

**Performance Goals**: Overhead de sincronización < 200ms por operación CRUD

**Constraints**: LiteLLM OSS (sin features Enterprise). LiteLLM debe estar healthy antes de cualquier operación de sync.

**Scale/Scope**: Operaciones CRUD de gestión (no data path crítico). Volumen bajo.

## Constitution Check

| Principio | Estado | Notas |
|-----------|--------|-------|
| I. Privacy & PHI/PII Masking-First | ✅ | No afectado. El pipeline de masking no cambia. |
| II. Strict Compliance (GDPR & AI Act) | ✅ | No afectado. Las keys reales pasan igualmente por nuestras capas. |
| III. Budget & Resource Enforcement | ✅ **Mejora** | Pasamos de enforcement simulado a enforcement real via LiteLLM. |
| IV. Containerized & White-Label | ✅ **Refuerza** | Motor de IA completamente oculto. Naming en código: `AIEngineClient`, `engine_team_id`, `engine_user_id`, `engine_key_token`. Ninguna referencia a tecnología subyacente en API pública, DB fields, logs de app ni UI. |
| V. Explanatory Playground | ✅ | No afectado. |

## Project Structure

### Documentation (this feature)

```text
specs/002-litellm-sync/
├── spec.md              ✅ creado
├── plan.md              ✅ este archivo
├── tasks.md             (pendiente)
├── changelog.md         (se crea al final de cada sesión)
└── contracts/
    └── litellm-api.md   (endpoints de LiteLLM que consumimos)
```

### Source Code (cambios en el repositorio)

```text
backend/src/
├── services/
│   └── ai_engine_client.py        ← NUEVO: wrapper HTTP para la API de LiteLLM
├── models/
│   ├── user.py                  ← MODIFICAR: agregar engine_user_id, engine_team_id
│   └── budget.py                ← MODIFICAR: agregar litellm_key_token en APIKey
├── api/
│   ├── users.py                 ← MODIFICAR: sync con LiteLLM al crear user/group
│   ├── keys.py                  ← MODIFICAR: generar keys via LiteLLM, revocar via LiteLLM
│   └── budgets.py               ← MODIFICAR: leer spend real de LiteLLM
└── schemas/
    └── user.py                  ← MODIFICAR: agregar engine_team_id en responses

frontend/src/
├── pages/
│   └── UsersPage.tsx            ← MODIFICAR: mostrar spend real con barra de progreso
└── services/
    └── api.ts                   ← MODIFICAR: agregar endpoints de spend

litellm/
└── config.yaml                  ← MODIFICAR: habilitar store_model_in_db
```

## Architectural Decision: AIEngineClient como servicio de infraestructura

El cliente de LiteLLM es un servicio stateless que encapsula todas las llamadas HTTP a la API de gestión de LiteLLM. Usa `httpx.AsyncClient` para llamadas async. Toda la lógica de retry y error handling vive aquí.

```
FastAPI endpoint
    └── llama users.py / keys.py
            └── AIEngineClient (nuevo)
                    └── HTTP POST/GET/DELETE a litellm:4000
```

**Por qué no llamar directo desde los endpoints**: Centraliza el manejo de errores, el base URL, y el master key. Facilita mockear en tests futuros.

## Architectural Decision: Sincronización "best-effort con rollback"

Al crear un user/group/key:
1. Primero llamamos a LiteLLM
2. Si LiteLLM falla → retornamos 503, no guardamos en nuestra DB
3. Si LiteLLM ok → guardamos en nuestra DB con el ID devuelto
4. Si nuestra DB falla → intentamos revocar/borrar el recurso en LiteLLM

No usamos transacciones distribuidas (overkill para este scope). El rollback best-effort es suficiente para OSS.

## Architectural Decision: El cliente usa keys `sk-...` contra nuestro backend

Los clientes externos siempre apuntan a `http://basa-gateway:8081`. Nuestro backend recibe la key `sk-...`, la pasa tal cual a LiteLLM en la llamada a `/chat/completions`. LiteLLM valida la key, trackea el spend, y enforces el budget. Nuestro backend no necesita revalidar el presupuesto localmente.

```
Cliente → basa-backend (PII masking + guardianes) → litellm (valida sk-xxx, trackea spend) → LLM
```

## Fases de implementación

### Fase 1 — AIEngineClient + config (Foundational, sin UI)
Crear el servicio, actualizar `config.yaml`, agregar campos a modelos. Sin cambios visibles en UI.

### Fase 2 — Sync de Grupos/Teams (US1 parcial)
Al crear un grupo, también se crea en LiteLLM. Se guarda `engine_team_id`. Los grupos existentes sin `engine_team_id` son legacy — no se migran.

### Fase 3 — Keys reales via LiteLLM (US1 + US4)
Generación y revocación de keys usando la API real de LiteLLM. Las keys `basa_sk_...` locales se reemplazan por `sk-...` reales.

### Fase 4 — Sync de Usuarios individuales (US3)
Al crear un usuario, también se crea en LiteLLM. Se guarda `engine_user_id`.

### Fase 5 — Spend en tiempo real (US2)
Endpoints de spend + UI actualizada con barras de progreso.

### Fase 6 — Polish
Manejo de registros legacy, validación e2e.
