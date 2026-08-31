# Feature 006 — User Compliance Profiles

**Status**: Implementado ✅ (mergeado a master, 2026-06-29)
**Branch**: `feature/006-user-compliance-profiles`

## Objetivo

Vincular usuarios y grupos a proyectos de compliance, añadir base legal diferenciada por rol clínico, registrar consentimiento explícito, y añadir Redis para caché de respuestas y rate limiting real.

Sin esta feature, las políticas de compliance se aplican globalmente a todas las llamadas sin distinción de usuario — un médico y un administrativo reciben las mismas reglas aunque su base legal GDPR sea diferente.

---

## Requisitos funcionales

### FR-001 — Grupos de usuarios con perfil de compliance
- Un `UserGroup` tiene: nombre, descripción, base legal GDPR por defecto, nivel de riesgo AI Act, proyecto de compliance asignado
- Ejemplos: `Médicos` (Art. 9(2)(h), Alto Riesgo), `Enfermería` (Art. 9(2)(h), Alto Riesgo), `Administración` (Art. 6(1)(c), Limitado), `Investigación` (Art. 9(2)(j), Limitado)
- Un usuario pertenece a un grupo (o ninguno → usa configuración global)

### FR-002 — Asignación usuario ↔ proyecto de compliance
- Tabla de relación `user_compliance_assignments`: user_id, project_id, assigned_at, assigned_by
- El pipeline de chat determina qué proyecto aplicar según el grupo del usuario de la API key

### FR-003 — Registro de consentimiento
- Tabla `ConsentRecord`: user_id, consent_type (`ai_use`, `data_processing`, `special_category`), version, granted_at, revoked_at, ip_address
- El consentimiento Art. 9(2)(a) requiere registro aquí antes de procesar datos de salud
- Endpoint para revocar consentimiento → bloquea futuras llamadas del usuario

### FR-004 — Etiqueta de propósito por llamada
- El cliente puede enviar `X-Processing-Purpose` en la cabecera de la llamada al chat
- El audit log registra el propósito (`clinical_decision`, `administrative`, `research`, `training`)
- El Panel DPO muestra distribución de propósitos

### FR-005 — Exportación real de datos de sujeto (portabilidad Art. 20)
- `GET /compliance/dsr/{id}/export` genera JSON/CSV con todos los audit logs del sujeto
- Incluye: timestamps, modelos usados, propósito, coste, PII detectado (no contenido real)

### FR-006 — Redis: caché de respuestas
- Añadir contenedor Redis al docker-compose
- Configurar LiteLLM `cache: type: redis` en config.yaml
- TTL configurable por modelo (por defecto: 1 hora)
- El Panel de Analíticas muestra el hit rate de caché

### FR-007 — Redis: rate limiting por usuario
- Configurar LiteLLM `max_parallel_requests` y `tpm_limit` / `rpm_limit` por API key
- Añadir límites por defecto en la creación de API keys
- Respuesta HTTP 429 con `Retry-After` cuando se supera el límite

---

## Requisitos no funcionales

- NFR-001: La determinación del proyecto de compliance por usuario no debe añadir más de 5ms de latencia
- NFR-002: Redis no debe ser un punto único de fallo — el sistema debe funcionar sin Redis (sin caché)
- NFR-003: Los registros de consentimiento son inmutables — solo se añaden filas (revocación = nueva fila con revoked_at)

---

## Modelo de datos

### UserGroup (nuevo)
```
id UUID PK
name VARCHAR UNIQUE NOT NULL
description TEXT
default_legal_basis VARCHAR
default_risk_level VARCHAR
compliance_project_id UUID FK → compliance_projects
created_at TIMESTAMP
```

### ConsentRecord (nuevo)
```
id UUID PK
user_id UUID FK → users
consent_type VARCHAR  -- ai_use | data_processing | special_category
version VARCHAR       -- versión del texto de consentimiento
granted_at TIMESTAMP
revoked_at TIMESTAMP  -- NULL si vigente
ip_address VARCHAR
notes TEXT
```

### Cambios en tabla `users`
```
group_id UUID FK → user_groups (nullable)
```

### Cambios en tabla `api_keys`
```
rpm_limit INTEGER DEFAULT 60    -- peticiones por minuto
tpm_limit INTEGER DEFAULT 100000 -- tokens por minuto
```

### Cambios en tabla `audit_logs`
```
processing_purpose VARCHAR  -- clinical_decision | administrative | research | training
user_group_id UUID          -- grupo del usuario en el momento de la llamada
```

---

## API endpoints nuevos

```
GET    /api/v1/groups                     # listar grupos
POST   /api/v1/groups                     # crear grupo
PUT    /api/v1/groups/{id}                # editar grupo
DELETE /api/v1/groups/{id}                # eliminar grupo

GET    /api/v1/users/{id}/group           # ver grupo del usuario
PUT    /api/v1/users/{id}/group           # asignar grupo

GET    /api/v1/compliance/consent/{user_id}        # ver consentimientos
POST   /api/v1/compliance/consent                  # registrar consentimiento
DELETE /api/v1/compliance/consent/{id}             # revocar

GET    /api/v1/compliance/dsr/{id}/export          # exportar datos del sujeto
```

---

## Cambios en el pipeline de chat

```python
# Determinar proyecto de compliance según grupo del usuario
if api_key_obj and api_key_obj.user and api_key_obj.user.group:
    group_project = api_key_obj.user.group.compliance_project
    active_projects = [group_project] if group_project else active_projects_global

# Registrar propósito
processing_purpose = request.headers.get("X-Processing-Purpose", "unspecified")
```

---

## docker-compose.yml — Redis

```yaml
sentinel-redis:
  image: redis:7-alpine
  container_name: sentinel-redis
  ports:
    - "6379:6379"
  command: redis-server --maxmemory 256mb --maxmemory-policy allkeys-lru
  networks:
    - sentinel-network
```

## litellm/config.yaml — Redis cache + rate limiting

```yaml
cache:
  type: redis
  host: sentinel-redis
  port: 6379
  ttl: 3600
```

---

## Alembic migration: 005_user_compliance_profiles

- CREATE TABLE user_groups
- CREATE TABLE consent_records
- ALTER TABLE users ADD COLUMN group_id UUID FK
- ALTER TABLE api_keys ADD COLUMN rpm_limit INTEGER DEFAULT 60
- ALTER TABLE api_keys ADD COLUMN tpm_limit INTEGER DEFAULT 100000
- ALTER TABLE audit_logs ADD COLUMN processing_purpose VARCHAR
- ALTER TABLE audit_logs ADD COLUMN user_group_id UUID
- Seed 4 grupos por defecto: Médicos, Enfermería, Administración, Investigación

---

## Fases de implementación

### Fase 1 — Backend core (grupos + consentimiento)
- Modelos UserGroup, ConsentRecord
- Relación users.group_id
- API /groups + /compliance/consent
- Alembic 005

### Fase 2 — Pipeline + portabilidad
- chat.py: resolución de proyecto por grupo del usuario
- Cabecera X-Processing-Purpose → audit log
- GET /dsr/{id}/export

### Fase 3 — Redis
- docker-compose: contenedor sentinel-redis
- LiteLLM config.yaml: cache + rpm/tpm limits
- api_keys: campos rpm_limit, tpm_limit
- Respuesta 429 correcta

### Fase 4 — Frontend
- UsersPage: selector de grupo en modal de usuario
- Nueva pestaña "Grupos" en la página de usuarios
- CompliancePage → DSR: botón "Exportar datos"
- CompliancePage → nueva pestaña "Consentimientos"
- Panel DPO: distribución de propósitos de tratamiento
