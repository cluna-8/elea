# Changelog: Feature 004 — Analytics & Compliance Dashboard

**Branch**: `feature/004-analytics-dashboard` | **Date**: 2026-06-29

## Backend

### Nuevo módulo: `backend/src/api/analytics.py`
- `GET /api/v1/analytics/summary?range=day|week|month` — agrega métricas de la tabla `audit_logs` con SQL puro (no ORM verboso)
  - Total peticiones, costo, tokens, latencia media, incidentes PII, compliance stats
  - Top modelos ordenados por peticiones
  - Activaciones de guardianes: usa `jsonb_array_elements` para agregar guardian_events JSONB; join con `guardians.name` para nombres white-label
- `GET /api/v1/analytics/engine-status` — ping al motor de IA con timeout 2s; retorna `online/offline`

### Actualizado: `backend/src/api/audit.py`
- Nuevo parámetro `from_date` y `to_date` en `GET /api/v1/audit-logs` para filtro por período
- Nuevo endpoint `GET /api/v1/audit-logs/export` — StreamingResponse con CSV
  - Columnas: id, timestamp, model, tokens, cost, pii_detected, compliance_status, latency_ms, guardian_events_count
  - Sin texto de prompts ni PII (privacidad por diseño)
  - Límite de 5000 filas para evitar OOM
- Schema `AuditLogResponseSchema` actualizado con campo `guardian_events`

### Actualizado: `backend/src/api/__init__.py`
- Registrado el router de analytics

## Frontend

### Nuevo: `frontend/src/pages/DashboardPage.tsx`
- Selector de período: Hoy / Semana / Mes
- 4 KPI cards: Peticiones, Costo, Incidentes PII, Bloqueos de Guardianes
- Tabla de top 5 modelos por uso
- Panel de estado del sistema: motor online/offline, guardianes activos, latencia, tokens optimizados, AI Act stats
- Barras de activación de guardianes (CSS nativo, sin charting library)
- Carga con 3 llamadas paralelas: analytics/summary, analytics/engine-status, guardians

### Actualizado: `frontend/src/pages/AuditPage.tsx`
- Columna "Guardianes" con badge de conteo de eventos
- Click en fila expande detalle: tokens, PII entities, guardian_events, compliance status
- Filtros de fecha (from_date / to_date)
- Botón "Exportar CSV" con descarga automática del browser
- Importa `api` de services para reutilizar `exportAuditLogs`

### Actualizado: `frontend/src/services/api.ts`
- `getAnalyticsSummary(range)` — llama a `/analytics/summary`
- `getEngineStatus()` — llama a `/analytics/engine-status`
- `exportAuditLogs(filters)` — descarga CSV vía `URL.createObjectURL`

### Actualizado: `frontend/src/App.tsx`
- Importa `DashboardPage`
- "Panel Principal" agregado como primer ítem de navegación
- Página por defecto cambiada de "playground" a "dashboard"

## White-label compliance
- `guardian_activations.by_guardian` usa `guardians.name` (nombre display), no `engine_guardrail_name`
- CSV export no incluye nombres de proveedores
- Error responses del analytics endpoint no revelan tecnología interna
