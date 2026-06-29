# Tasks: Feature 004 — Analytics & Compliance Dashboard

**Branch**: `feature/004-analytics-dashboard` | **Plan**: [plan.md](plan.md)

**Status key**: `[ ]` pendiente · `[x]` completada · `[~]` en progreso · `[!]` bloqueada

---

## Fase 1 — Analytics Backend

### T-001 · analytics.py: endpoint summary

- [ ] **T-001-A** Crear `backend/src/api/analytics.py`:
  - `GET /api/v1/analytics/summary?range=day|week|month`
  - Calcula `from_date` según el range (hoy, -7 días, -30 días desde NOW())
  - Query SQL agregada sobre `audit_logs` filtrando `timestamp >= from_date`
  - Retorna:
    ```json
    {
      "range": "week",
      "from_date": "...",
      "to_date": "...",
      "total_requests": N,
      "total_cost_usd": 0.0,
      "total_prompt_tokens": N,
      "total_completion_tokens": N,
      "pii_incidents": N,
      "guardian_blocks": N,
      "compliance_passed": N,
      "compliance_blocked": N,
      "avg_latency_ms": N,
      "tokens_saved_by_optimization": N,
      "models": [{"model": "...", "requests": N, "cost_usd": 0.0}],
      "guardian_activations": {"total": N, "by_guardian": {"Nombre display": N}}
    }
    ```
  - `guardian_activations.by_guardian`: agregar los `guardian_events` JSONB usando `jsonb_array_elements`; joinear `guardians.name` por `engine_guardrail_name` para nombre white-label
  - `guardian_blocks`: count de rows donde `compliance_status = 'blocked_by_policy'` OR `guardian_events` no está vacío con bloqueo

- [ ] **T-001-B** Agregar `GET /api/v1/analytics/engine-status` en el mismo router:
  - Hace `GET {ENGINE_URL}/health` o `GET {ENGINE_URL}/health/readiness`
  - Retorna `{"status": "online" | "offline", "checked_at": "..."}`
  - Timeout de 2s, no lanza excepción si offline (retorna `{"status": "offline"}`)

### T-002 · Registrar analytics router

- [ ] **T-002-A** Editar `backend/src/api/__init__.py`:
  - Importar y registrar el router de analytics con prefix `/analytics`

---

## Fase 2 — Audit Export + Filtro de Fechas

### T-003 · audit.py: filtro de fechas en listado

- [ ] **T-003-A** Leer `backend/src/api/audit.py` para entender su estructura actual
- [ ] **T-003-B** Agregar parámetros `from_date: Optional[str] = None` y `to_date: Optional[str] = None` al endpoint `GET /api/v1/audit-logs`
  - Si `from_date` provisto, filtrar `AuditLog.timestamp >= datetime.fromisoformat(from_date)`
  - Si `to_date` provisto, filtrar `AuditLog.timestamp <= datetime.fromisoformat(to_date)`

### T-004 · audit.py: exportación CSV

- [ ] **T-004-A** Agregar endpoint `GET /api/v1/audit-logs/export` en `backend/src/api/audit.py`:
  - Parámetros: mismos filtros que el listado (`pii_detected`, `compliance_status`, `from_date`, `to_date`)
  - Usa `fastapi.responses.StreamingResponse` con un generador Python
  - Content-Type: `text/csv`
  - Content-Disposition: `attachment; filename="audit_export_{timestamp}.csv"`
  - Columnas CSV: `id,timestamp,model,prompt_tokens,completion_tokens,cost_usd,pii_detected,compliance_status,latency_ms,tokens_saved_by_optimization,guardian_events_count`
  - `guardian_events_count` = `len(log.guardian_events or [])`
  - Sin texto de prompts, sin PII

---

## Fase 3 — Dashboard Page

### T-005 · DashboardPage.tsx: KPI cards + top modelos + guardianes

- [ ] **T-005-A** Crear `frontend/src/pages/DashboardPage.tsx`:
  - Estado inicial: `range = "week"`, `summary = null`, `engineStatus = null`, `loading = true`
  - `useEffect`: fetches paralelos a `api.getAnalyticsSummary(range)` y `api.getEngineStatus()`
  - Cuando cambia `range`, re-fetch el summary

- [ ] **T-005-B** UI — Selector de período:
  - 3 botones: "Hoy" / "Semana" / "Mes" (activo resaltado con bg-primary)

- [ ] **T-005-C** UI — 4 KPI cards en grid 2x2:
  - Peticiones totales (ícono de mensaje)
  - Costo total USD (formato `$X.XXXX`)
  - Incidentes PII (cantidad de `pii_incidents`)
  - Bloqueos de guardianes (`guardian_activations.total`)
  - Cada card: número grande en blanco, label pequeño en text-secondary

- [ ] **T-005-D** UI — Estado del sistema (2 indicadores):
  - Motor de IA: dot verde "Online" / rojo "Offline"
  - Guardianes activos: `X activos` (cuenta los guardians del GET /guardians donde is_active=true)

- [ ] **T-005-E** UI — Top modelos (tabla simple):
  - Columnas: Modelo | Peticiones | Costo USD
  - Máximo 5 filas, ordenado por peticiones desc

- [ ] **T-005-F** UI — Barras de activación de guardianes:
  - Para cada entry en `guardian_activations.by_guardian`:
    - Nombre del guardián (text-xs)
    - Barra CSS: `<div style={{ width: `${(count/max)*100}%` }}` en color primary/20 con texto de count
  - Si no hay activaciones: "Sin activaciones en el período"

### T-006 · api.ts: nuevos métodos de analytics

- [ ] **T-006-A** Agregar a `frontend/src/services/api.ts`:
  ```typescript
  getAnalyticsSummary: async (range: "day" | "week" | "month"): Promise<any> => { ... }
  getEngineStatus: async (): Promise<{ status: "online" | "offline"; checked_at: string }> => { ... }
  exportAuditLogs: async (filters: { pii_detected?: boolean; compliance_status?: string; from_date?: string; to_date?: string }): Promise<void> => {
    // Trigger browser download
  }
  ```

---

## Fase 4 — Audit Page Mejorada

### T-007 · AuditPage.tsx: guardian_events column + expand + fechas + export

- [ ] **T-007-A** Agregar columna "Guardianes" en la tabla de logs:
  - Si `guardian_events?.length > 0`: badge `[N guardián(es)]` en color warning
  - Si `guardian_events?.length === 0 || null`: texto `—`

- [ ] **T-007-B** Expand de fila:
  - Click en cualquier fila la expande (toggle `expandedRow` state)
  - La fila expandida muestra un panel debajo con:
    - Prompt tokens / Completion tokens / Latencia / Costo
    - `pii_detected`: si true, lista de `masked_entities`
    - `guardian_events`: si hay eventos, lista con nombre del evento (sin mencionar proveedor)
    - `compliance_status`: descripción legible

- [ ] **T-007-C** Filtro de fechas:
  - Dos inputs tipo `date` (desde / hasta) en la barra de filtros
  - Formato ISO para la API

- [ ] **T-007-D** Botón "Exportar CSV":
  - Llama a `api.exportAuditLogs(filtros activos)`
  - El browser recibe el CSV y lo descarga automáticamente
  - Deshabilitar durante la descarga con texto "Exportando..."

- [ ] **T-007-E** Actualizar la interfaz TypeScript `AuditLog` en `AuditPage.tsx` para incluir `guardian_events: any[]`

---

## Fase 5 — Navegación + Entrega

### T-008 · App.tsx: agregar Dashboard

- [ ] **T-008-A** Editar `frontend/src/App.tsx`:
  - Importar `DashboardPage`
  - Agregar `"dashboard"` al tipo `Page`
  - Agregar "Panel Principal" como primer item en `navigation`
  - Cambiar `useState<Page>("playground")` a `useState<Page>("dashboard")`
  - Agregar `{currentPage === "dashboard" && <DashboardPage />}` al render

### T-009 · Tests manuales

- [ ] **T-009-A** Navegar a Panel Principal → verificar que los KPI cards muestran datos reales (o ceros si no hay logs)
- [ ] **T-009-B** Cambiar selector de período → verificar que los números cambian
- [ ] **T-009-C** Estado del sistema → verificar que Motor de IA muestra Online cuando el contenedor litellm está corriendo
- [ ] **T-009-D** Audit page → click en una fila → verifica que se expande con detalle
- [ ] **T-009-E** Exportar CSV → verificar que se descarga un archivo con las columnas correctas
- [ ] **T-009-F** Filtrar por fecha en Audit page → verificar que los resultados se filtran

### T-010 · Changelog + commit

- [ ] **T-010-A** Crear `specs/004-analytics-compliance-dashboard/changelog.md`
- [ ] **T-010-B** Commit `feat(004): analytics dashboard + audit CSV export + guardian events`

---

## Orden de implementación

```
T-001 → T-002       (backend analytics, independiente)
T-003 → T-004       (backend audit export, independiente)

T-006              (api.ts métodos, necesita conocer los endpoints)

T-005              (DashboardPage, necesita T-006)
T-007              (AuditPage enhanced, necesita T-006)

T-008              (App.tsx, necesita T-005)

T-009 → T-010      (tests + entrega)
```

## Dependencias

| Tarea | Depende de |
|-------|-----------|
| T-002 | T-001 (router creado) |
| T-005 | T-001, T-006 |
| T-006 | T-001, T-004 (conocer shape de respuesta) |
| T-007 | T-003, T-004, T-006 |
| T-008 | T-005 |
| T-009 | T-001–T-008 completos |
