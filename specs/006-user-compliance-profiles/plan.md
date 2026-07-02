# Plan — Feature 006: User Compliance Profiles

> As-built: documenta lo que se implementó (no un plan futuro).

## Archivos creados

| Archivo | Descripción |
|---------|-------------|
| `backend/src/models/consent.py` | Modelo `ConsentRecord` (tipo, versión, fecha, revocación) |
| `backend/src/api/groups.py` | CRUD grupos + asignación usuario↔grupo |
| `backend/src/api/consent.py` | GET/POST/DELETE consentimientos |
| `backend/alembic/versions/005_user_compliance_profiles.py` | Migración: tabla groups, consent_records, FKs en users/audit |
| `backend/src/services/redis_client.py` | Singleton Redis fail-open |

## Archivos modificados

| Archivo | Cambio |
|---------|--------|
| `backend/src/models/user.py` | Columna `group_id UUID FK → groups` en User; nuevo modelo Group |
| `backend/src/models/budget.py` | Columnas `rpm_limit INTEGER`, `tpm_limit INTEGER` en APIKey |
| `backend/src/models/audit.py` | Columnas `processing_purpose`, `user_group_id` |
| `backend/src/api/chat.py` | Resolución de proyecto de compliance por grupo; cabecera `X-Processing-Purpose` → audit log |
| `backend/src/api/keys.py` | rpm_limit / tpm_limit en create/list |
| `backend/src/services/audit_service.py` | Parámetros processing_purpose y user_group_id |
| `docker-compose.yml` | Contenedor `basa-redis`; variable `REDIS_HOST=basa-redis` |
| `litellm/config.yaml` | Sección `cache` con Redis |
| `frontend/src/pages/UsersPage.tsx` | Selector de grupo al crear usuario; sección Grupos |
| `frontend/src/pages/CompliancePage.tsx` | Tab DSR (exportar por sujeto); tab Consentimientos |
| `frontend/src/services/api.ts` | Métodos grupos, consentimientos, exportación DSR |

## Decisiones clave

- Group tiene `compliance_project_id FK` → el proyecto se hereda al usuario vía grupo, no se asigna individualmente.
- Redis fail-open: si no disponible, rate limiting se omite sin romper el servicio.
- ConsentRecord no almacena el texto completo del consentimiento, solo tipo/versión (GDPR minimización).
- Migración idempotente: `CREATE TABLE IF NOT EXISTS` + `ADD COLUMN IF NOT EXISTS`.
