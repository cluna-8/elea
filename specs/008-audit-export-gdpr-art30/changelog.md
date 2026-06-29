# Changelog — Feature 008: Audit Export & GDPR Art. 30

## [1.0.0] — 2026-06-30

### Added

**Backend**
- `backend/src/api/reports.py` — router en `/api/v1/reports` con 4 endpoints:
  - `GET /reports/rat` → CSV del Registro de Actividades de Tratamiento (Art. 30) con todos los proyectos de compliance activos
  - `GET /reports/dsar/{subject_identifier}` → CSV con audit logs del sujeto (sin contenido de prompts — GDPR Art. 5 minimización)
  - `GET /reports/human-review-log` → CSV de revisiones humanas completadas (aprobadas y rechazadas)
  - `GET /reports/executive` → JSON con resumen ejecutivo: totales, tasas de compliance, alertas activas
- `backend/src/api/__init__.py` — registra `reports_router`
- Todos los endpoints de reports requieren rol `admin` o `compliance_officer` via `require_role()`

**Frontend**
- `frontend/src/pages/CompliancePage.tsx` — sección "Exportar documentos GDPR" en Panel DPO con 3 botones: RAT Art. 30 CSV, Log Revisiones Humanas CSV, DSAR por sujeto CSV
- `frontend/src/pages/CompliancePage.tsx` — botón "↓ Exportar" por fila en tabla DSR (llama a exportDSAR con el subject_identifier de esa fila)
- `frontend/src/services/api.ts` — métodos `exportRAT()`, `exportDSAR(subjectIdentifier)`, `exportHumanReviewLog()`, `getExecutiveSummary()`

### Compliance Coverage

| Requisito | Estado |
|-----------|--------|
| GDPR Art. 30 — Registro de actividades de tratamiento | ✅ RAT exportable en CSV con todos los campos requeridos |
| GDPR Art. 15/20 — Derecho de acceso y portabilidad | ✅ DSAR export por sujeto sin incluir contenido de prompts |
| EU AI Act — Documentación para supervisión | ✅ Informe ejecutivo con tasas de compliance y alertas |
| Revisión humana Art. 14 — Registro de decisiones | ✅ Log de revisiones con revisor, acción y notas |

### Design Decisions
- El DSAR export **no incluye el texto de los prompts** (GDPR Art. 5 minimización). Solo metadatos: timestamp, modelo, propósito, tokens, coste, PII detectado (boolean), estado de compliance.
- El nombre del motor de IA no aparece en ningún campo exportado (restricción white-label).
