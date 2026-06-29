# Changelog — Feature 005: Compliance Policies GDPR & EU AI Act

## [1.0.0] — 2026-06-29

### Added

**Backend**
- `backend/src/models/compliance.py` — 5 nuevos modelos SQLAlchemy: `ComplianceProject`, `DPARegistry`, `DataSubjectRequest`, `HumanReview`, `RetentionPolicy`
- `backend/alembic/versions/004_compliance_tables.py` — migración idempotente que crea las 5 tablas y añade columnas `review_token` y `ai_disclosure_delivered` a `audit_logs`; siembra 4 políticas de retención por defecto
- `backend/src/api/compliance.py` — router completo en `/api/v1/compliance` con CRUD de Proyectos, DPAs, DSRs, gestión de Retención, revisión humana y Panel DPO
- `backend/src/models/audit.py` — columnas `review_token` (UUID) y `ai_disclosure_delivered` (Boolean)
- `backend/src/api/chat.py` — middleware de compliance: bloqueo por región EU, entrega de notificación IA (Art. 50), creación de token de revisión humana
- `backend/src/services/audit_service.py` — parámetros `review_token` y `ai_disclosure_delivered` en `log_transaction()`

**Frontend**
- `frontend/src/pages/CompliancePage.tsx` — página de 5 pestañas: Panel DPO, Proyectos, DPAs, Derechos del Interesado, Retención de Datos
- `frontend/src/services/api.ts` — 15 nuevos métodos para todos los endpoints de compliance
- `frontend/src/App.tsx` — reemplaza `PoliciesPage` con `CompliancePage`

### Compliance Coverage

| Requisito | Estado |
|-----------|--------|
| GDPR Art. 5(1)(e) — Limitación del plazo de conservación | ✅ Políticas de retención configurables por tipo de log |
| GDPR Art. 9(2)(h) — Base legal para datos sanitarios | ✅ Obligatorio en cada Proyecto de Compliance |
| GDPR Art. 12–22 — Derechos del interesado | ✅ DSR tracker con búsqueda por sujeto y plazo de 30 días |
| GDPR Art. 28 — Acuerdos con encargados (DPA) | ✅ Registro DPA con alertas de vencimiento |
| GDPR Art. 35 — Evaluación de impacto (DPIA) | ✅ Referencia DPIA y fecha de revisión en Proyectos |
| EU AI Act Art. 50 — Notificación de IA | ✅ Disclosure automático por sesión (en vigor ago. 2026) |
| EU AI Act Art. 14 — Supervisión humana | ✅ Token de revisión humana por transacción cuando se requiere |
| Zero Data Retention — Región EU | ✅ Bloqueo automático si modelo no es azure-/bedrock-/vertex- |
