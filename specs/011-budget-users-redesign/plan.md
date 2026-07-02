# Plan — Spec 011: Budget Dual-Layer & Users/Keys UX Redesign

> As-built: documenta lo que se implementó.

## Archivos modificados

| Archivo | Cambio |
|---------|--------|
| `backend/src/api/budgets.py` | `DELETE /budgets/{id}` endpoint agregado |
| `backend/src/services/budget_service.py` | `get_applicable_budgets`: resuelve group_id desde user record; `has_sufficient_budget`: bloquea si CUALQUIER presupuesto agotado; `update_budget`: descuenta de TODOS los presupuestos aplicables en paralelo |
| `frontend/src/pages/UsersPage.tsx` | Reestructuración en 5 tabs: Resumen / Usuarios & Equipos / Llaves Virtuales / Presupuestos / Autenticación & SSO |
| `frontend/src/services/api.ts` | `deleteBudget(budgetId)` → `DELETE /budgets/{id}` |

## Lógica de presupuesto dual-layer

```
get_applicable_budgets(user_id, group_id):
  1. Si user_id → busca presupuesto personal
  2. Si no hay group_id explícito → resuelve desde user.group_id en DB
  3. Si group_id → busca presupuesto de grupo
  → devuelve [personal?, grupo?] (0, 1 o 2 presupuestos)

has_sufficient_budget:
  → True si al menos uno tiene crédito (fallback)
  → True si no hay presupuestos (sin restricción)

update_budget:
  → Descuenta de CADA presupuesto que tenga crédito
  → Transacción única
```

## Decisiones clave

- El presupuesto personal y el de grupo son **independientes**: cada uno rastrea su propio gasto.
- El bloqueo es si CUALQUIERA se agota (no solo el personal) — el de grupo es un techo departamental.
- `has_sufficient_budget` usa `any()` (fallback): si el personal está agotado pero hay crédito de grupo, se permite (y viceversa).
- Display de presupuesto con 4 decimales para cantidades sub-centavo (sub-cent amounts visibles).
- Tab SSO mantiene el contenido de 010 sin cambios.
