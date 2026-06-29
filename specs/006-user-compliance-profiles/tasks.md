# Tasks: Feature 006 — User Compliance Profiles

## Fase 1 — Backend: Grupos y Consentimiento

- [ ] **T-001** Crear `backend/src/models/user_group.py`: modelo `UserGroup` (id, name, description, default_legal_basis, default_risk_level, compliance_project_id)
- [ ] **T-002** Crear `backend/src/models/consent.py`: modelo `ConsentRecord` (id, user_id, consent_type, version, granted_at, revoked_at, ip_address, notes)
- [ ] **T-003** Actualizar `backend/src/models/user.py`: añadir columna `group_id UUID FK → user_groups`
- [ ] **T-004** Actualizar `backend/src/models/api_key.py`: añadir columnas `rpm_limit INTEGER DEFAULT 60`, `tpm_limit INTEGER DEFAULT 100000`
- [ ] **T-005** Actualizar `backend/src/models/audit.py`: añadir columnas `processing_purpose VARCHAR`, `user_group_id UUID`
- [ ] **T-006** Actualizar `backend/src/models/__init__.py`: exportar nuevos modelos
- [ ] **T-007** Crear `backend/alembic/versions/005_user_compliance_profiles.py`: migración idempotente + seed 4 grupos por defecto
- [ ] **T-008** Crear `backend/src/api/groups.py`: CRUD de grupos + asignación usuario↔grupo
- [ ] **T-009** Crear `backend/src/api/consent.py`: GET/POST consentimientos + revocación
- [ ] **T-010** Actualizar `backend/src/api/__init__.py`: registrar nuevos routers

## Fase 2 — Pipeline y Portabilidad

- [ ] **T-011** Actualizar `backend/src/api/chat.py`: resolución de proyecto de compliance por grupo del usuario
- [ ] **T-012** Actualizar `backend/src/api/chat.py`: leer cabecera `X-Processing-Purpose` y guardar en audit log
- [ ] **T-013** Actualizar `backend/src/services/audit_service.py`: parámetros `processing_purpose` y `user_group_id`
- [ ] **T-014** Añadir endpoint `GET /compliance/dsr/{id}/export` en `compliance.py`: genera JSON con audit logs del sujeto

## Fase 3 — Redis

- [ ] **T-015** Añadir contenedor `basa-redis` al `docker-compose.yml`
- [ ] **T-016** Añadir variable `REDIS_HOST=basa-redis` al `.env`
- [ ] **T-017** Actualizar `litellm/config.yaml`: sección `cache` con Redis
- [ ] **T-018** Actualizar `backend/src/api/keys.py`: incluir `rpm_limit` y `tpm_limit` en create/update de API keys

## Fase 4 — Frontend

- [ ] **T-019** Actualizar `frontend/src/pages/UsersPage.tsx`: selector de grupo en modal de crear/editar usuario
- [ ] **T-020** Añadir pestaña "Grupos" en `UsersPage.tsx`: tabla + modal crear/editar grupo con proyecto de compliance asignado
- [ ] **T-021** Actualizar `frontend/src/pages/CompliancePage.tsx` pestaña DSR: botón "Exportar datos" por solicitud
- [ ] **T-022** Añadir pestaña "Consentimientos" en `CompliancePage.tsx`: tabla de consentimientos por usuario + formulario nuevo
- [ ] **T-023** Actualizar Panel DPO: añadir tarjeta de distribución de propósitos de tratamiento
- [ ] **T-024** Actualizar `frontend/src/services/api.ts`: métodos para grupos, consentimientos y exportación DSR

## Fase 5 — Docs y Git

- [ ] **T-025** Actualizar `docs/compliance-policies.md`: añadir sección de grupos y consentimiento
- [ ] **T-026** Crear `specs/006-user-compliance-profiles/changelog.md`
- [ ] **T-027** Commits por fase + push a GitHub
