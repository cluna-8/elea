# Tasks: Feature 005 — Compliance Policies GDPR & EU AI Act

## Phase 1 — Backend: Models + Migration

- [x] **T-001** Crear `backend/src/models/compliance.py` con modelos `ComplianceProject`, `DPARegistry`, `DataSubjectRequest`, `HumanReview`, `RetentionPolicy`
- [x] **T-002** Actualizar `backend/src/models/audit.py`: agregar columnas `review_token UUID` y `ai_disclosure_delivered BOOLEAN DEFAULT false`
- [x] **T-003** Actualizar `backend/src/models/__init__.py`: exportar nuevos modelos
- [x] **T-004** Crear `backend/alembic/versions/004_compliance_tables.py`: migración idempotente con CREATE TABLE IF NOT EXISTS para las 5 tablas nuevas + ALTER TABLE audit_logs para las 2 columnas nuevas + seed de 4 filas en retention_policies

## Phase 2 — Backend: API

- [x] **T-005** Crear `backend/src/api/compliance.py` con endpoints:
  - `GET/POST /compliance/projects`
  - `PUT/DELETE /compliance/projects/{id}`
  - `GET/POST /compliance/dpas`
  - `PUT/DELETE /compliance/dpas/{id}`
  - `GET/POST /compliance/dsr`
  - `PUT /compliance/dsr/{id}`
  - `GET /compliance/dsr/search`
  - `POST /compliance/review/{review_token}`
  - `GET /compliance/review/pending`
  - `GET/PUT /compliance/retention`
  - `GET /compliance/dashboard`
- [x] **T-006** Actualizar `backend/src/api/__init__.py`: importar y registrar `compliance_router`
- [x] **T-007** Actualizar `backend/src/api/chat.py`: agregar 3 compliance checks en el pipeline:
  1. AI disclosure (prepend message + log `ai_disclosure_delivered=true`)
  2. Human review token (generate UUID, store in audit log, include in response)
  3. EU region enforcement (block if project requires EU and model is non-EU)

## Phase 3 — Frontend

- [x] **T-008** Actualizar `frontend/src/services/api.ts`: agregar todos los métodos de compliance (proyectos, DPAs, DSR, retención, dashboard)
- [x] **T-009** Crear `frontend/src/pages/CompliancePage.tsx` con 5 tabs:
  1. **Proyectos** — tabla + modal crear/editar con campos: nombre, base legal, categoría de datos, nivel de riesgo AI Act, notificación IA, revisión humana, referencia DPIA
  2. **DPAs** — tabla con badge de estado (Activo/Por vencer/Expirado) + modal crear/editar
  3. **Derechos del Interesado** — tabla de solicitudes + formulario nueva solicitud + buscador por ID
  4. **Retención** — tabla de 4 filas (prompt content, metadata, security events, config audit) con inputs de días y campo de justificación
  5. **Panel DPO** — tarjetas de resumen: proyectos por estado, DPAs por estado, DPIAs pendientes, DSRs abiertos, tasa de enmascaramiento PHI, tasa de rutas EU, tasa de entrega de notificación IA
- [x] **T-010** Actualizar `frontend/src/App.tsx`: reemplazar `PoliciesPage` por `CompliancePage` en import, tipo Page y render

## Phase 4 — Docs & Git

- [x] **T-011** Crear `specs/005-compliance-policies-gdpr-ai-act/changelog.md`
- [x] **T-012** Commit `docs(spec): add feature 005 — compliance policies GDPR & EU AI Act`
- [x] **T-013** Commit `feat(005): compliance models + Alembic migration 004`
- [x] **T-014** Commit `feat(005): compliance API — projects, DPA, DSR, retention, DPO dashboard`
- [x] **T-015** Commit `feat(005): compliance UI — CompliancePage 5 tabs`

## Integration Tests (manual — pendientes de verificación con docker compose up)

- [ ] **T-016** Verificar que Alembic migration 004 corre limpia: `docker compose logs backend | grep alembic`
- [ ] **T-017** Crear un proyecto con base legal Art. 9(2)(h), activarlo → verificar que el chat incluye disclosure en primera respuesta
- [ ] **T-018** Registrar un DPA → verificar que aparece en el Panel DPO
- [ ] **T-019** Crear una DSR de tipo "acceso" → búsqueda por subject_id → verificar resultados
- [ ] **T-020** Configurar retención de prompt content a 30 días → verificar que el job de purga se ejecuta al arrancar
