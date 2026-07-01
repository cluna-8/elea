# Changelog — Feature 011: Budget Dual-Layer & Users/Keys UX Redesign

## Backend

### T-037 — DELETE /budgets/{id}
- `backend/src/api/budgets.py`: nuevo endpoint `DELETE /{budget_id}` con HTTP 204. Elimina el presupuesto de la base de datos. Devuelve 404 si no existe.

### T-038/T-039 — BudgetService dual-layer
- `backend/src/services/budget_service.py`: refactorizado completamente.
  - Nuevo método `get_personal_budget(db, user_id)` — busca presupuesto personal del usuario.
  - Nuevo método `get_group_budget(db, group_id)` — busca presupuesto del grupo.
  - Nuevo método `get_applicable_budgets(db, user_id, group_id)` — devuelve la lista de presupuestos que aplican a la request (personal + grupo si ambos existen; solo grupo si no hay personal; fallback a grupo vía user.group_id si no se pasa group_id explícito).
  - `has_sufficient_budget`: ahora verifica TODOS los presupuestos aplicables. Bloquea si cualquiera está agotado (USD o tokens).
  - `update_budget`: ahora descuenta de TODOS los presupuestos aplicables en una sola transacción. Ya no retorna el budget (retorna None).
  - `get_budget_by_owner` y `get_user_budget` conservados por compatibilidad.

## Frontend

### T-040–T-045 — UsersPage rediseño 5 tabs
- `frontend/src/pages/UsersPage.tsx`: reescritura completa con 5 tabs:
  1. **Resumen**: 4 KPI cards (usuarios activos, llaves activas, presupuestos, gasto total), alerta presupuestos ≥80%, grid de equipos con consumo.
  2. **Usuarios & Equipos**: tabla de grupos con columnas Base Legal / Riesgo AI Act / Proyecto Compliance / Consumo + botón "Editar perfil"; tabla de usuarios con "Asignar equipo". Ambas con botones de creación.
  3. **Llaves Virtuales**: tabla completa (nombre, propietario, compliance, token preview, RPM/TPM, consumo, fecha) + "Revocar".
  4. **Presupuestos**: cards con badge Personal/Equipo, barra de progreso a color, display 4 decimales, botones Editar y **Eliminar**.
  5. **Autenticación & SSO**: contenido previo sin cambios (7 proveedores, JWT activo).
- Tab de compliance anterior ("Perfiles de Compliance") fusionada dentro de "Usuarios & Equipos" (columnas en la tabla de grupos + modal existente).

### T-046 — api.ts deleteBudget
- `frontend/src/services/api.ts`: nuevo método `deleteBudget(budgetId: string): Promise<void>` → `DELETE /budgets/{id}`.

## tasks.md

Actualizar estado de tareas a completadas:
- [x] T-037
- [x] T-038
- [x] T-039
- [x] T-040–T-045
- [x] T-046
