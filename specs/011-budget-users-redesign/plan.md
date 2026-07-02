# Plan — Spec 011: Budget Dual-Layer & Users/Keys UX Redesign

> As-built: documenta lo que se implementó.

## Archivos modificados

| Archivo | Cambio |
|---------|--------|
| `backend/src/api/budgets.py` | `DELETE /budgets/{id}` endpoint agregado |
| `backend/src/services/budget_service.py` | `get_applicable_budgets`: resuelve group_id desde user record; `has_sufficient_budget`: bloquea si CUALQUIER presupuesto agotado; `update_budget`: descuenta de TODOS los presupuestos aplicables en paralelo |
| `frontend/src/pages/UsersPage.tsx` | Reestructuración en 5 tabs: Resumen / Usuarios & Equipos / Llaves Virtuales / Presupuestos / Autenticación & SSO |
| `frontend/src/services/api.ts` | `deleteBudget(budgetId)` → `DELETE /budgets/{id}` |

## Lógica de presupuesto — modelo secuencial

```
get_applicable_budgets(user_id, group_id):
  1. Si user_id → busca presupuesto personal
  2. Si no hay group_id explícito → resuelve desde user.group_id en DB
  3. Si group_id → busca presupuesto de grupo
  → devuelve [personal?, grupo?] en ese orden de prioridad

has_sufficient_budget:
  → True si AL MENOS UNO tiene crédito (any())
  → True si no hay presupuestos (sin restricción)
  → Bloquea solo si TODOS están agotados

update_budget:
  → Cobra del PRIMERO con crédito y para (break)
  → Orden: personal primero, grupo como fallback
  → Una sola capa se cobra por request
  → Transacción única
```

**Flujo concreto:**
- Mientras el personal tiene saldo → se cobra del personal (el grupo no se toca)
- Cuando el personal se agota → se cobra del grupo
- Cuando ambos se agotan → bloquea con 402

## Decisiones clave

- **Modelo secuencial, no paralelo**: cada request carga un solo presupuesto (el primero con crédito). El grupo es la red de seguridad, no un contador paralelo.
- `has_sufficient_budget` usa `any()`: bloquea solo cuando ambas capas están agotadas.
- `update_budget` usa `break` después del primer presupuesto con crédito, respetando el orden `[personal, grupo]` que devuelve `get_applicable_budgets`.
- Display de presupuesto con 4 decimales para cantidades sub-centavo.
- Tab SSO mantiene el contenido de 010 sin cambios.
