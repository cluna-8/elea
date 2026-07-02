# Plan — Feature 008: Audit Export & GDPR Art. 30

> As-built: documenta lo que se implementó.

## Archivos creados

| Archivo | Descripción |
|---------|-------------|
| `backend/src/api/reports.py` | Router con 4 endpoints de exportación |

## Archivos modificados

| Archivo | Cambio |
|---------|--------|
| `backend/src/api/__init__.py` | Registro de `reports_router` |
| `frontend/src/pages/CompliancePage.tsx` | Botones de exportación en Panel DPO y tab DSR |
| `frontend/src/services/api.ts` | Métodos `getRatReport()`, `getDsarExport(id)`, `getExecutiveReport()`, `getHumanReviewLog()` |

## Endpoints implementados

| Endpoint | Formato | Descripción |
|----------|---------|-------------|
| `GET /api/v1/reports/rat` | CSV | Registro de Actividades de Tratamiento (GDPR Art. 30) |
| `GET /api/v1/reports/dsar/{subject_identifier}` | JSON/CSV | Todos los logs asociados al sujeto (pseudonimizado) |
| `GET /api/v1/reports/executive` | JSON | Resumen ejecutivo: totales, tasas, alertas |
| `GET /api/v1/reports/human-review-log` | CSV | Revisiones humanas completadas (aprobadas/rechazadas) |

## Decisiones clave

- DSAR usa `subject_identifier` (pseudónimo) — nunca nombre real, en cumplimiento GDPR Art. 5(1)(e).
- RAT incluye campos Art. 30: responsable, finalidad, base jurídica, categoría, destinatarios, plazos, medidas.
- Exportación CSV usa `StreamingResponse` para no cargar todo el log en memoria.
