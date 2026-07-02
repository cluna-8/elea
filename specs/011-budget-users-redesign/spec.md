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
- Implementar doble capa presupuestaria: personal Y grupo se evalúan simultáneamente. Bloquea si cualquiera de los dos está agotado.
- Rediseñar UsersPage con 5 tabs bien separadas.
- Mejorar display y UX general de presupuestos.

## Modelo de negocio: doble capa presupuestaria

```
Ejemplo: usuario admin, grupo cardiologia
  Personal: $10.00 → gasta $9.50 → queda $0.50  ← LIMITA al individuo
  Grupo:     $5.00 → gasta $4.80 → queda $0.20  ← LIMITA al departamento

  Próxima request de $0.30:
    ¿Personal suficiente? $0.50 >= $0.30 → ✓
    ¿Grupo suficiente?    $0.20 >= $0.30 → ✗ BLOQUEA (grupo agotado)

  Próxima request de $0.10:
    ¿Personal suficiente? $0.50 >= $0.10 → ✓
    ¿Grupo suficiente?    $0.20 >= $0.10 → ✓
    → PASA, descuenta $0.10 de AMBOS
```

Cuando ambos aplican, el gasto se descuenta de los dos simultáneamente.

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
  - Si el usuario tiene presupuesto personal → verifica personal
  - Si el usuario está en un grupo con presupuesto → verifica grupo TAMBIÉN
  - Si cualquiera está agotado → bloquea
  - Si ninguno existe → permite (sin límite)

- `update_budget(db, user_id, group_id, ...)`:
  - Si el usuario tiene presupuesto personal → descuenta de personal
  - Si el usuario está en un grupo con presupuesto → descuenta de grupo TAMBIÉN
  - Ambas operaciones en la misma transacción

## Consideración: LiteLLM

LiteLLM expone endpoints nativos de budget (`/user/new`, `/team/new`, `/key/generate`) con `max_budget` y `budget_duration`. Los equipos creados en Basa ya se sincronizan a LiteLLM (engine_team_id). Sin embargo, las requests del chat usan el master key — LiteLLM no ve el usuario real. Delegar el presupuesto a LiteLLM requeriría pasar claves por-usuario en cada request (cambio arquitectural mayor). Se deja como mejora futura (Spec 013).

## No en scope
- Presupuestos por organización (multi-tenant)
- Delegar budget tracking a LiteLLM (Spec 013)
- SSO funcional (Spec 012)
- Alertas por email cuando se acerca al límite
