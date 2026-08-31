# Spec 011 — Budget Dual-Layer & Users/Keys UX Redesign

**Status**: Implementado ✅ (mergeado a master, 2026-07-01)
**Branch**: `feature/011-budget-users-redesign`

## Contexto

Durante el QA de las features 001–010 se identificaron los siguientes problemas:

1. **Sin eliminación de presupuestos**: no hay endpoint DELETE ni botón en UI para eliminar un budget una vez creado.
2. **Presupuesto de grupo ignorado cuando existe el personal**: el sistema elige uno solo (personal > grupo). En un entorno sanitario lo correcto es que ambas capas apliquen simultáneamente (el personal limita al individuo, el de grupo limita el gasto total del departamento).
3. **UsersPage sobrecargada**: una sola pantalla con usuarios, grupos, llaves, presupuestos y SSO causa confusión. Se necesitan tabs claras.
4. **Display de presupuesto con poca precisión**: `max_spend_usd` se mostraba con 2 decimales — cantidades sub-centavo ($0.001) se veían como "$0.00".

## Objetivos

- Permitir eliminar presupuestos desde la UI.
- Implementar doble capa presupuestaria con modelo secuencial: el personal se consume primero; cuando se agota, el grupo actúa como fallback. Bloquea solo cuando ambos están agotados.
- Rediseñar UsersPage con 5 tabs bien separadas.
- Mejorar display y UX general de presupuestos.

## Modelo de negocio: doble capa presupuestaria (secuencial)

El personal se consume primero. El grupo actúa como reserva departamental. Solo se carga una capa por request.

```
Ejemplo: usuario dr.garcia, grupo cardiologia
  Personal: $10.00 → queda $0.50  ← asignación individual
  Grupo:     $5.00 → queda $2.00  ← bolsa departamental (sin tocar aún)

  Request de $0.30:
    Personal tiene crédito ($0.50) → cobra $0.30 del personal → para
    Grupo: no se toca

  Cuando personal se agota (queda $0.00):
    Personal agotado → siguiente request carga del grupo
    Grupo tiene crédito ($2.00) → cobra del grupo

  Cuando ambos agotados → BLOQUEA (402)
```

**Regla de gate (`has_sufficient_budget`):** permite si AL MENOS UNO tiene crédito (`any()`).
**Regla de cargo (`update_budget`):** cobra del primero con crédito y para (`break`). Orden: personal → grupo.

## Diseño de tabs — UsersPage

### Tab 1: Resumen
- Cards KPI: usuarios activos, llaves activas, presupuestos activos, gasto total del mes
- Tabla de presupuestos cerca del límite (>80% gastado) con alerta visual
- Top 3 usuarios por gasto

### Tab 2: Usuarios & Equipos
- Tabla de usuarios: username, email, rol, grupo, proyecto compliance, acciones (editar grupo, editar compliance)
- Tabla de grupos: nombre, proyecto compliance, miembros, acciones (editar perfil)
- Botón crear usuario, botón crear grupo

### Tab 3: Llaves Virtuales
- Tabla de llaves con: nombre, usuario/equipo asignado, rpm/tpm, proyecto compliance, gasto, estado
- Botón crear llave
- Revocar llave

### Tab 4: Presupuestos
- Cards de presupuestos: tipo badge (Personal/Equipo), propietario, gasto/límite barra, tokens, periodo
- Acciones: Editar, Eliminar
- Botón crear presupuesto
- Display a 4 decimales para max y current

### Tab 5: Autenticación & SSO
- Tab actual de SSO (7 proveedores, solo JWT activo)
- Sin cambios en contenido

## Impacto en backend

### Nuevo endpoint
- `DELETE /budgets/{id}` — elimina un presupuesto por ID

### Cambio en BudgetService
- `has_sufficient_budget(db, user_id, group_id)`:
  - Permite si AL MENOS UNO (personal o grupo) tiene crédito (`any()`)
  - Bloquea solo si TODOS están agotados
  - Sin presupuestos → permite (sin límite)

- `update_budget(db, user_id, group_id, ...)`:
  - Cobra del PRIMERO con crédito en orden `[personal, grupo]` y para (`break`)
  - Solo una capa se carga por request
  - Transacción única

## Consideración: LiteLLM

LiteLLM expone endpoints nativos de budget (`/user/new`, `/team/new`, `/key/generate`) con `max_budget` y `budget_duration`. Los equipos creados en Sentinel ya se sincronizan a LiteLLM (engine_team_id). Sin embargo, las requests del chat usan el master key — LiteLLM no ve el usuario real. Delegar el presupuesto a LiteLLM requeriría pasar claves por-usuario en cada request (cambio arquitectural mayor). Se deja como mejora futura (Spec 013).

## No en scope
- Presupuestos por organización (multi-tenant)
- Delegar budget tracking a LiteLLM (Spec 013)
- SSO funcional (Spec 012)
- Alertas por email cuando se acerca al límite
