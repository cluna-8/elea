# Tasks — Spec 011: Budget Dual-Layer & Users/Keys UX Redesign

## Backend

- [x] T-037 — `DELETE /budgets/{id}` endpoint en `backend/src/api/budgets.py`
- [x] T-038 — `BudgetService.has_sufficient_budget`: verificar AMBOS (personal + grupo) si ambos existen; bloquear si cualquiera agotado
- [x] T-039 — `BudgetService.update_budget`: descontar de AMBOS (personal + grupo) si ambos existen; en una sola transacción

## Frontend

- [x] T-040 — UsersPage: restructurar en 5 tabs (Resumen / Usuarios & Equipos / Llaves Virtuales / Presupuestos / Autenticación & SSO)
- [x] T-041 — Tab Resumen: KPI cards (usuarios, llaves, presupuestos, gasto), tabla presupuestos cerca del límite (>80%)
- [x] T-042 — Tab Usuarios & Equipos: tabla de usuarios y tabla de grupos con todas las acciones
- [x] T-043 — Tab Llaves Virtuales: tabla de llaves con rpm/tpm, proyecto compliance
- [x] T-044 — Tab Presupuestos: cards con badge Personal/Equipo, barra progreso, botón Eliminar, display 4 decimales
- [x] T-045 — Tab Autenticación & SSO: contenido previo sin cambios

## API (frontend)

- [x] T-046 — `api.ts`: agregar `deleteBudget(budgetId)` → `DELETE /budgets/{id}`

## Docs

- [x] T-047 — Changelog 011 actualizado
- [ ] T-048 — Actualizar USE.md: sección presupuestos (doble capa, eliminar), nueva estructura UsersPage
