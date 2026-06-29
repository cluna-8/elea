# Tasks: Feature 006 — User Compliance Profiles

## Fase 1 — Backend: Grupos y Consentimiento

- [x] **T-001** Modelo `Group` en `backend/src/models/user.py` (id, name, description, default_legal_basis, default_risk_level, compliance_project_id)
- [x] **T-002** Crear `backend/src/models/consent.py`: modelo `ConsentRecord` (id, user_id, consent_type, version, granted_at, revoked_at, ip_address, notes)
- [x] **T-003** Actualizar `backend/src/models/user.py`: columna `group_id UUID FK → groups`
- [x] **T-004** Actualizar `backend/src/models/budget.py`: columnas `rpm_limit INTEGER DEFAULT 60`, `tpm_limit INTEGER DEFAULT 100000`
- [x] **T-005** Actualizar `backend/src/models/audit.py`: columnas `processing_purpose VARCHAR`, `user_group_id UUID`
- [x] **T-006** Actualizar `backend/src/models/__init__.py`: exportar nuevos modelos (ConsentRecord)
- [x] **T-007** Crear `backend/alembic/versions/005_user_compliance_profiles.py`: migración idempotente + seed grupos
- [x] **T-008** Crear `backend/src/api/groups.py`: CRUD de grupos + asignación usuario↔grupo
- [x] **T-009** Crear `backend/src/api/consent.py`: GET/POST consentimientos + revocación
- [x] **T-010** Actualizar `backend/src/api/__init__.py`: registrar groups_router y consent_router

## Fase 2 — Pipeline y Portabilidad

- [x] **T-011** Actualizar `backend/src/api/chat.py`: resolución de proyecto de compliance por grupo del usuario
- [x] **T-012** Actualizar `backend/src/api/chat.py`: leer cabecera `X-Processing-Purpose` y guardar en audit log
- [x] **T-013** Actualizar `backend/src/services/audit_service.py`: parámetros `processing_purpose` y `user_group_id`
- [x] **T-014** Endpoint `GET /reports/dsar/{subject_identifier}` en `reports.py`: CSV con audit logs del sujeto

## Fase 3 — Redis

- [x] **T-015** Contenedor `basa-redis` en `docker-compose.yml`
- [x] **T-016** Variable `REDIS_HOST=basa-redis` en docker-compose environment
- [x] **T-017** Actualizar `litellm/config.yaml`: sección `cache` con Redis
- [x] **T-018** Actualizar `backend/src/api/keys.py`: `rpm_limit` y `tpm_limit` en create/list de API keys

## Fase 4 — Frontend

- [x] **T-019** `frontend/src/pages/UsersPage.tsx`: selector de grupo en modal de crear usuario + columna grupo en tabla
- [x] **T-020** Sección "Grupos" en `UsersPage.tsx`: tabla de grupos con proyecto de compliance + miembros
- [ ] **T-021** `CompliancePage.tsx` pestaña DSR: botón "Exportar datos" por solicitud individual
- [ ] **T-022** Añadir pestaña "Consentimientos" en `CompliancePage.tsx`: tabla por usuario + formulario nuevo
- [ ] **T-023** Panel DPO: tarjeta de distribución de propósitos de tratamiento (clínico / admin / investigación)
- [x] **T-024** `frontend/src/services/api.ts`: métodos para grupos, consentimientos, exportación DSR y reports

## Fase 5 — Docs y Git

- [ ] **T-025** Actualizar `docs/compliance-policies.md`: sección de grupos y consentimiento
- [ ] **T-026** Crear `specs/006-user-compliance-profiles/changelog.md`
- [x] **T-027** Commits por fase — implementación completa en rama feature/007-rate-limiting
