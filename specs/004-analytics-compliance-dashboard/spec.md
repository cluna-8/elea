# Feature Spec 004: Analytics & Compliance Dashboard

**Status**: Implementado ✅ (mergeado a master, 2026-06-29) | **Branch**: `feature/004-analytics-dashboard` | **Date**: 2026-06-29

## Problem Statement

El sistema tiene logs de auditoría completos pero no hay forma de visualizar el rendimiento, los costos, los incidentes de seguridad o el estado de cumplimiento de manera agregada. Los responsables de cumplimiento (compliance officers) de una institución sanitaria necesitan:

1. Métricas de uso en tiempo real y por período para justificar el gasto en IA
2. Resumen de incidentes de seguridad (PII detectado, guardianes activados) para auditorías GDPR
3. Vista agregada de eventos de guardianes (qué se bloqueó, con qué frecuencia)
4. Capacidad de exportar registros para informes de cumplimiento normativos

Sin esta visibilidad, el sistema es una caja negra para los administradores y compliance officers.

## User Stories

### US1 — Dashboard de Overview
**Como** administrador del sistema,
**Quiero** ver un dashboard con métricas clave del sistema al abrir la aplicación,
**Para** tener visibilidad inmediata del uso, costos e incidentes de seguridad.

**Criterios de aceptación**:
- Dashboard muestra: total peticiones, costo total, incidentes PII, bloqueos de guardianes (día/semana/mes)
- Top 5 modelos por uso y costo
- Utilización de presupuesto por grupo (si hay presupuestos configurados)
- Indicador de estado del sistema (motor de IA online/offline)

### US2 — Logs de Auditoría con Eventos de Guardianes
**Como** compliance officer,
**Quiero** ver los eventos de guardianes en cada registro de auditoría,
**Para** entender exactamente qué políticas de seguridad se activaron en cada petición.

**Criterios de aceptación**:
- Cada fila del log tiene un indicador de guardianes activados
- Click en una fila expande el detalle (tokens, entidades, guardian_events del motor)
- Filtro adicional: "Con eventos de guardianes" / "Sin eventos"

### US3 — Exportación CSV para Informes de Cumplimiento
**Como** compliance officer,
**Quiero** exportar los logs de auditoría en formato CSV con filtros aplicados,
**Para** incluirlos en informes de cumplimiento GDPR, AI Act o auditorías internas.

**Criterios de aceptación**:
- Botón "Exportar CSV" en la página de Logs de Auditoría
- El CSV respeta los filtros activos (fecha, PII, compliance_status)
- El CSV incluye: timestamp, model, tokens, cost, pii_detected, compliance_status, latency_ms, guardian_events_count
- El CSV NO incluye texto de prompts ni PII desenmascado (privacidad por diseño)

### US4 — Métricas de Guardianes en Dashboard
**Como** responsable de seguridad,
**Quiero** ver un desglose de qué guardianes se activaron y cuántas veces,
**Para** evaluar la efectividad de las políticas de seguridad configuradas.

**Criterios de aceptación**:
- Listado de guardianes activos con conteo de activaciones en el período
- Separación: guardianes locales vs guardianes del motor
- Indicador: "N bloqueos" vs "N detecciones sin bloqueo" (log mode)

## Functional Requirements

| ID | Descripción |
|----|-------------|
| FR-001 | `GET /api/v1/analytics/summary?range=day\|week\|month` retorna métricas agregadas del período |
| FR-002 | El endpoint analytics opera sobre la tabla `audit_logs` con SQL agregado (sin datos externos) |
| FR-003 | `GET /api/v1/audit-logs/export` retorna archivo CSV con Content-Disposition: attachment |
| FR-004 | El CSV de exportación respeta parámetros de filtro: `pii_detected`, `compliance_status`, fechas |
| FR-005 | `GET /api/v1/audit-logs` acepta `from_date` y `to_date` como parámetros adicionales |
| FR-006 | `GET /api/v1/analytics/summary` incluye desglose por modelo y conteo de guardian_events |
| FR-007 | Nueva página "Panel Principal" como página de inicio de la aplicación |
| FR-008 | La página de Logs muestra columna de guardianes activados con badge de conteo |
| FR-009 | Expansión de fila en Logs muestra guardian_events detallado en formato legible |
| FR-010 | El dashboard muestra estado del motor de IA (ping al health check) |
| FR-011 | Las métricas se pueden filtrar por período: hoy / última semana / último mes |
| FR-012 | Indicador de presupuesto: costo del período vs presupuesto total del grupo (si está configurado) |
| FR-013 | White-label: ninguna respuesta del analytics endpoint revela nombres de proveedores de guardrails |

## Non-Functional Requirements

| ID | Descripción |
|----|-------------|
| NFR-001 | El endpoint de analytics debe responder en < 500ms para el rango "day" (query con índice en timestamp) |
| NFR-002 | La exportación CSV no debe cargar todos los registros en memoria a la vez (streaming o limit 5000) |
| NFR-003 | El dashboard no debe hacer más de 3 llamadas API en la carga inicial |
| NFR-004 | Compatible con la arquitectura existente: sin nuevas dependencias de frontend (sin charting library) |

## Architecture Notes

### Analytics endpoint

```
GET /api/v1/analytics/summary?range=week
Response:
{
  "range": "week",
  "from_date": "2026-06-22T00:00:00",
  "to_date": "2026-06-29T23:59:59",
  "total_requests": 142,
  "total_cost_usd": 0.0234,
  "total_prompt_tokens": 48200,
  "total_completion_tokens": 12400,
  "pii_incidents": 12,
  "guardian_blocks": 3,
  "compliance_passed": 139,
  "compliance_blocked": 3,
  "avg_latency_ms": 1240,
  "tokens_saved_by_optimization": 890,
  "models": [
    {"model": "gemini-2.5-flash", "requests": 80, "cost_usd": 0.012},
    ...
  ],
  "guardian_events": {
    "total_activations": 5,
    "by_guardian": {
      "Filtro de Contenido": 3,
      "Protección Anti-Jailbreak": 2
    }
  },
  "engine_status": "online" | "offline"
}
```

`guardian_events.by_guardian` usa los nombres display (de la tabla `guardians.name`), no los `engine_guardrail_name`.

### CSV export format

```
timestamp,model,prompt_tokens,completion_tokens,cost_usd,pii_detected,compliance_status,latency_ms,guardian_events_count
2026-06-29T14:30:00,gemini-2.5-flash,120,45,0.000045,false,allowed,432,0
```

### Dashboard layout (sin charting library)

```
┌─────────────────────────────────────────────────────────────┐
│  Panel Principal                    [Hoy] [Semana] [Mes]    │
├─────────────┬─────────────┬──────────────┬──────────────────┤
│  Peticiones │   Costo     │ Incidentes   │ Bloqueos         │
│    142      │  $0.023     │ PII: 12      │ Guardianes: 3    │
├─────────────┴─────────────┴──────────────┴──────────────────┤
│  Top Modelos              │  Estado del Sistema              │
│  gemini-2.5-flash: 80     │  ● Motor de IA: Online          │
│  azure-gpt-4o-mini: 42    │  ● Base de datos: Online        │
│  gpt-4o: 20               │  Guardianes activos: 2/8        │
├───────────────────────────┴──────────────────────────────────┤
│  Activaciones de Guardianes                                  │
│  Filtro de Contenido ████████████ 3                          │
│  Anti-Jailbreak ████████ 2                                   │
└─────────────────────────────────────────────────────────────┘
```

## Constitution Check

| Principio | Estado | Notas |
|-----------|--------|-------|
| I. Privacy & PHI/PII Masking-First | ✅ | CSV export no incluye texto de prompts ni PII original |
| II. Strict Compliance (GDPR & AI Act) | ✅ **Mejora** | Facilita auditorías de cumplimiento GDPR y AI Act |
| III. Budget & Resource Enforcement | ✅ **Mejora** | Dashboard muestra utilización de presupuesto |
| IV. Containerized & White-Label | ✅ | guardian_events.by_guardian usa nombres display, no proveedores |
| V. Explanatory Playground | ✅ | Sin cambios al Playground |

## Scope Clarification

**En scope**:
- Analytics endpoint (SQL aggregation sobre audit_logs)
- CSV export de audit logs
- Dashboard page nueva
- Audit page con expand row + guardian events + filtro de fechas
- App.tsx: nueva navegación "Panel Principal"

**Fuera de scope**:
- Gráficos con charting library (mantenemos el stack sin nuevas dependencias)
- Alertas por email o webhook (Feature 005)
- Reportes PDF (Feature 005)
- Time series charts (barras de tendencia por día: se puede hacer con CSS puro, opcional)
- Real-time websocket updates (Feature futura)
