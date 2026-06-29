# Tasks — 008 Audit Export & GDPR Art. 30

## Phase 1 — Backend
- [ ] T-001: Create `backend/src/api/reports.py` router
- [ ] T-002: GET /reports/rat → CSV Registro de Actividades de Tratamiento
- [ ] T-003: GET /reports/dsar/{subject_identifier} → JSON/CSV DSAR export
- [ ] T-004: GET /reports/executive → JSON resumen ejecutivo
- [ ] T-005: GET /reports/human-review-log → CSV revisiones completadas
- [ ] T-006: Register reports router in api/__init__.py

## Phase 2 — Frontend
- [ ] T-007: Export buttons in CompliancePage DPO Panel
- [ ] T-008: DSAR export button in DSR tab (per subject)
- [ ] T-009: Add report API methods to api.ts
