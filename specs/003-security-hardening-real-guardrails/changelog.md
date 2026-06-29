# Changelog: Feature 003 — Security Hardening Real Guardrails

**Branch**: `feature/003-security-hardening` | **Date**: 2026-06-29

## Nuevas dependencias

- `alembic==1.13.3` — migrations versionadas de schema PostgreSQL
- `cryptography==42.0.8` — encriptación Fernet para API keys de servicios de guardrails

## Alembic migrations (`backend/alembic/`)

- **`alembic.ini`** — configuración de Alembic (URL sobreescrita en env.py)
- **`alembic/env.py`** — construye DATABASE_URL desde las mismas variables que usa `database.py`
- **`alembic/versions/001_initial_schema.py`** — baseline con `CREATE TABLE IF NOT EXISTS` para todos los modelos actuales
- **`alembic/versions/002_guardian_engine_fields.py`** — agrega `engine_guardrail_name`, `fail_mode`, `apply_on`, `service_api_key_encrypted` a `guardians`; seed automático de `engine_guardrail_name` para los 5 tipos externos
- **`alembic/versions/003_audit_guardian_events.py`** — agrega columna `guardian_events JSONB` a `audit_logs`

## Backend — modelos

- **`backend/src/models/guardian.py`** — nuevos campos: `engine_guardrail_name`, `fail_mode`, `apply_on`, `service_api_key_encrypted`
- **`backend/src/models/audit.py`** — nuevo campo: `guardian_events JSONB`

## Backend — servicios

- **`backend/src/services/encryption_service.py`** — NUEVO: `encrypt()` / `decrypt()` con Fernet. Opera en no-op si `FERNET_SECRET_KEY` no está configurado
- **`backend/src/services/ai_engine_client.py`** — nuevas funciones: `get_active_guardrail_names(db)`, `test_guardrail(name, text)`
- **`backend/src/services/guardian_service.py`**:
  - Eliminadas las simulaciones de keyword/regex para guardrails externos (Lakera, OpenAI Mod, Azure, Bedrock, LlamaGuard)
  - Reemplazado por delegación al motor de IA vía campo `guardrails` en cada request
  - Seed actualizado: nombres y `engine_guardrail_name` sin referencias a proveedores en la UI
- **`backend/src/services/audit_service.py`** — acepta parámetro `guardian_events` y lo persiste en el log

## Backend — API

- **`backend/src/api/chat.py`**:
  - Importa `Guardian` y `ai_engine_client`
  - Antes de cada llamada al motor: obtiene guardrails activos con `engine_guardrail_name` y los incluye en `"guardrails": [...]` del request body
  - Respuestas 400 del motor se capturan y retornan como mensaje genérico (white-label: sin nombre de proveedor)
  - `guardian_events` capturados de la respuesta del motor y pasados al audit log
- **`backend/src/api/guardians.py`**:
  - Schemas actualizados con `fail_mode`, `apply_on`, `service_api_key` (entrada) / `has_service_key` (salida)
  - `engine_guardrail_name` NUNCA se expone en respuestas de la API
  - Nuevo endpoint: `POST /guardians/{id}/test` — ejecuta test real contra el motor
  - Encriptación automática de `service_api_key` al persistir

## Infrastructure

- **`backend/Dockerfile`** — CMD actualizado: `alembic upgrade head && uvicorn ...`
- **`docker-compose.yml`** — nuevo env var `FERNET_SECRET_KEY` para el servicio backend

## Frontend

- **`frontend/src/services/api.ts`** — nuevo método `testGuardian(id, text)`
- **`frontend/src/pages/SecurityPage.tsx`**:
  - Eliminado el badge "Nube / Simulación"
  - Badge dinámico: Local / Activo (con key) / Activo / Inactivo según estado real
  - Descripciones de guardianes desde tabla estática (sin nombres de proveedores)
  - Nuevos controles `fail_mode` y `apply_on` para guardianes del motor
  - Panel de prueba collapsable para guardianes del motor: textarea + botón "Ejecutar test" + resultado visual

## White-label compliance

- `engine_guardrail_name` nunca expuesto en respuestas API
- Errores 400 del motor muestran mensaje genérico de política de seguridad
- Descripciones en UI no mencionan nombres de proveedores de guardrails
- Nombres de guardianes en la UI describen la función, no el proveedor
