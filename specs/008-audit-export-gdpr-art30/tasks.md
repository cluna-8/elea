# Tasks — 008 Audit Export & GDPR Art. 30

## Phase 1 — Backend
- [x] T-001: Create `backend/src/api/reports.py` router
- [x] T-002: GET /reports/rat → CSV Registro de Actividades de Tratamiento
- [x] T-003: GET /reports/dsar/{subject_identifier} → JSON/CSV DSAR export
- [x] T-004: GET /reports/executive → JSON resumen ejecutivo
- [x] T-005: GET /reports/human-review-log → CSV revisiones completadas
- [x] T-006: Register reports router in api/__init__.py

## Phase 2 — Frontend
- [x] T-007: Export buttons in CompliancePage DPO Panel
- [x] T-008: DSAR export button in DSR tab (per subject) — global export via reports/dsar/{id}
- [x] T-009: Add report API methods to api.ts
