# Changelog — Feature 006: User Compliance Profiles

## [1.0.0] — 2026-06-30

### Added

**Backend**
- `backend/src/models/user.py` — modelo `Group` con campos `default_legal_basis`, `default_risk_level`, `compliance_project_id`; columna `group_id` FK en modelo `User`
- `backend/src/models/budget.py` — columnas `rpm_limit INTEGER DEFAULT 60` y `tpm_limit INTEGER DEFAULT 100000` en `APIKey`
- `backend/src/models/audit.py` — columnas `processing_purpose VARCHAR` y `user_group_id UUID` en `AuditLog`
- `backend/src/models/consent.py` — modelo `ConsentRecord` (user_id, consent_type, version, granted_at, revoked_at, ip_address, notes)
- `backend/src/models/__init__.py` — exporta `ConsentRecord`
- `backend/alembic/versions/005_user_compliance_profiles.py` — migración idempotente: nuevas tablas, columnas, seed de 4 grupos por defecto
- `backend/alembic/versions/006_user_key_compliance_fields.py` — migración complementaria para campos de compliance en claves
- `backend/src/api/groups.py` — CRUD de grupos + endpoint `PUT /groups/users/{user_id}/group`
- `backend/src/api/consent.py` — GET/POST consentimientos + revocación; endpoint `GET /compliance/consent` (listado global)
- `backend/src/api/__init__.py` — registra `groups_router` y `consent_router`
- `backend/src/api/chat.py` — resolución de proyecto de compliance por grupo del usuario; lectura de `X-Processing-Purpose`; almacena `processing_purpose` y `user_group_id` en audit log
- `backend/src/api/compliance.py` — endpoint `/dashboard` incluye `processing_purpose_distribution` (distribución por propósito)
- `docker-compose.yml` — contenedor `basa-redis` (redis:7-alpine, 256 MB maxmemory, healthcheck)
- `litellm/config.yaml` — sección `cache` con Redis (host, port, ttl: 3600)

**Frontend**
- `frontend/src/pages/UsersPage.tsx` — selector de grupo en modal de crear usuario; sección "Grupos" con tabla, miembros y proyecto asignado; columnas RPM/TPM en tabla de llaves; inputs rpm/tpm en modal de nueva llave
- `frontend/src/pages/CompliancePage.tsx` — nueva pestaña "Consentimientos" con tabla completa, modal de registro y botón de revocación; botón "↓ Exportar" por fila en tabla DSR; tarjeta de distribución de propósitos en Panel DPO
- `frontend/src/services/api.ts` — métodos `getGroupsCompliance`, `updateGroupCompliance`, `assignUserGroup`, `getUserConsents`, `getAllConsents`, `recordConsent`, `revokeConsent`

### Compliance Coverage

| Requisito | Estado |
|-----------|--------|
| GDPR Art. 7 — Consentimiento revocable y documentado | ✅ ConsentRecord con IP, timestamp y tipo |
| GDPR Art. 9(2)(a) — Consentimiento explícito datos de salud | ✅ Tipo `special_category` con registro de versión |
| GDPR Art. 20 — Portabilidad por sujeto | ✅ Exportación DSAR por solicitud individual |
| GDPR Art. 5(1)(b) — Limitación de la finalidad | ✅ `X-Processing-Purpose` registrado en audit log |
| EU AI Act — Diferenciación de riesgo por rol | ✅ Grupos con nivel de riesgo y base legal por defecto |
