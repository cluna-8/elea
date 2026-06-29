# Implementation Plan: Feature 004 — Analytics & Compliance Dashboard

**Branch**: `feature/004-analytics-dashboard` | **Date**: 2026-06-29 | **Spec**: [spec.md](spec.md)

## Summary

Agregar un Dashboard de Analytics como página principal de la aplicación. El dashboard muestra métricas agregadas del período (peticiones, costos, incidentes de seguridad) calculadas con SQL sobre `audit_logs`. También mejora la página de Logs con expansión de filas para ver `guardian_events` y agrega exportación CSV.

Sin nuevas dependencias de frontend ni librerías de charting. Los gráficos de activación de guardianes se implementan con barras CSS puras.

## Technical Context

**Language/Version**: Python 3.12 (backend), TypeScript/React 18 (frontend)

**New Dependencies**: ninguna — se usan SQLAlchemy aggregation functions y `csv` stdlib de Python

**Stack Constraints**: No se agrega ninguna librería de charting al frontend

**Performance**: El endpoint analytics usa índice existente en `audit_logs.timestamp`. Para rango "day" la query debe ser < 500ms.

## Architecture

```
Frontend DashboardPage
  → GET /api/v1/analytics/summary?range=week     (métricas agregadas)
  → GET /api/v1/analytics/engine-status          (estado del motor)
  → GET /api/v1/guardians                        (guardianes activos count)

Frontend AuditPage (enhanced)
  → GET /api/v1/audit-logs?...&from_date=&to_date=  (con filtro fecha)
  → GET /api/v1/audit-logs/export?...               (CSV download)
```

## Decisiones de diseño

### Agregación sin ORM — SQL directo para analytics
SQLAlchemy ORM es verboso para aggregation queries complejas. Se usa `db.execute(text(...))` con parámetros bindados. Esto evita N+1 y es más mantenible que `.func.count()` anidados.

### guardian_events.by_guardian usa nombres display
La query agrega los `guardian_events` del JSON con `jsonb_array_elements`. El nombre del guardián se obtiene haciendo JOIN con la tabla `guardians` usando `engine_guardrail_name`. Esto garantiza que los nombres mostrados son los nombres white-label configurados en DB, no los nombres del proveedor.

Fallback: si no hay match por `engine_guardrail_name` (p.ej. guardián eliminado), se muestra "Guardián de seguridad" como nombre genérico.

### CSV streaming con StreamingResponse
Para evitar cargar 10.000 registros en memoria, usamos `fastapi.responses.StreamingResponse` con un generador que produce líneas CSV una a una desde la DB.

### Dashboard sin recharts — barras CSS
Las barras de activación de guardianes usan `<div style={{ width: `${pct}%` }}` con transición CSS. Simple y sin dependencias.

## Project Structure

```text
specs/004-analytics-compliance-dashboard/
├── spec.md              ✅ creado
├── plan.md              ✅ este archivo
├── tasks.md             (pendiente)
└── changelog.md         (al finalizar)

backend/
├── src/
│   ├── api/
│   │   ├── analytics.py          ← NUEVO: /analytics/summary + /analytics/engine-status
│   │   ├── audit.py              ← ACTUALIZAR: exportación CSV + filtro de fechas
│   │   └── __init__.py           ← agregar analytics router
│   └── models/
│       └── (sin cambios de schema — analytics solo lee datos)

frontend/src/
├── pages/
│   ├── DashboardPage.tsx         ← NUEVO: página principal con KPIs
│   └── AuditPage.tsx             ← ACTUALIZAR: guardian_events, expand row, CSV export
├── services/
│   └── api.ts                    ← ACTUALIZAR: analytics endpoints
└── App.tsx                       ← ACTUALIZAR: agregar Dashboard a navegación
```

## Alembic

No hay cambios de schema — el dashboard solo lee datos existentes. No se necesita nueva migración.

## Fases de implementación

### Fase 1 — Analytics backend (US1 + US4)
Crear `backend/src/api/analytics.py` con:
- `GET /api/v1/analytics/summary?range=day|week|month`
- `GET /api/v1/analytics/engine-status`
Registrar el router en `api/__init__.py`.

### Fase 2 — Audit export + fechas (US2 + US3)
Actualizar `backend/src/api/audit.py`:
- Agregar parámetros `from_date` y `to_date` al endpoint de listado
- Agregar endpoint `GET /api/v1/audit-logs/export` con StreamingResponse CSV

### Fase 3 — Dashboard page (US1 + US4)
Crear `frontend/src/pages/DashboardPage.tsx` con:
- Selector de período (Hoy/Semana/Mes)
- 4 KPI cards: Peticiones, Costo, Incidentes PII, Bloqueos de Guardianes
- Tabla de top modelos
- Estado del sistema
- Barras de activación de guardianes

### Fase 4 — Audit page mejorada (US2 + US3)
Actualizar `frontend/src/pages/AuditPage.tsx`:
- Columna de guardian_events con badge de conteo
- Click en fila → expand con detalle completo
- Filtro por rango de fechas (from/to)
- Botón "Exportar CSV" que dispara download

### Fase 5 — Navegación y entrega
Actualizar `App.tsx` para incluir Dashboard como primer ítem de navegación y página por defecto.
Actualizar `api.ts` con los nuevos métodos.
Changelog + commit.
