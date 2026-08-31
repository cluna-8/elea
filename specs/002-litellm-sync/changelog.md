# Changelog: LiteLLM Real Integration

**Proyecto**: Sentinel Secure AI Gateway (by sentinel dev)
**Rama**: `feature/002-litellm-sync`
**Última actualización**: 2026-06-29

---

## Sesión 1 — 2026-06-29: Spec, Plan y Tasks

### Resumen
Creación de la documentación completa del feature: spec.md, plan.md, tasks.md, contracts/litellm-api.md. Definición de la arquitectura de sincronización con LiteLLM. Commit inicial del MVP en `master`.

### Decisiones tomadas
- **Motor de IA como fuente de verdad** para users/teams/keys/budgets — delegamos el enforcement financiero al motor subyacente.
- **Rollback best-effort**: sin transacciones distribuidas, pero con rollback en el motor si falla nuestra DB.
- **Registros legacy no se migran**: los users/groups del MVP anterior (sin `engine_team_id`) se tratan como legacy y no generan errores en UI.
- **White-label estricto en capa de producto**: naming en código usa `AIEngineClient`, `engine_team_id`, `engine_user_id`, `engine_key_token`. Ninguna referencia a tecnología subyacente en API pública, campos de DB, logs de aplicación ni UI. Los archivos de config de infraestructura (`config.yaml`, `.env`) quedan excluidos de esta regla.

---

## Sesión 2 — 2026-06-29: Implementación Fases 2-5 (Phases completas)

### Resumen
Implementación completa de la sincronización real con el motor de IA: grupos, usuarios, keys reales y gasto en tiempo real en la UI.

### Archivos modificados

| Archivo | Cambios |
|---------|---------|
| `backend/src/api/users.py` | `create_group` y `create_user` ahora async, sincronizan con motor, rollback en error. Endpoints `/groups/{id}/spend` y `/{id}/spend`. |
| `backend/src/api/keys.py` | `generate_key` usa motor real, `revoke_key` revoca en motor antes de DB, rollback best-effort. Endpoint `/{id}/spend`. Schema: `max_budget`, `budget_duration`, `models`. |
| `frontend/src/services/api.ts` | Interfaces `SpendInfo`, campos `engine_team_id` y `engine_user_id`. Métodos `getKeySpend`, `getGroupSpend`, `getUserSpend`. `createKey` acepta `max_budget`, `budget_duration`. |
| `frontend/src/pages/UsersPage.tsx` | Fetch de spend en paralelo post-carga. Tarjetas de grupo con consumo real y barra de progreso. Tabla de keys con columna de consumo. Modal de generación con campos de presupuesto. Fix `res.key` → `res.plain_key`. |

### Decisiones técnicas
- **Groups y users en selector de keys** filtrados por `engine_team_id` / `engine_user_id` presentes: evita generar keys para registros legacy que el motor desconoce.
- **Spend fetch paralelo**: `Promise.allSettled` para no bloquear la UI si algún spend falla.
- **Rollback best-effort en keys**: si falla el guardado en DB post-creación de key en el motor, se intenta revocar la key del motor para evitar huérfanas.

### Bugs corregidos
- **BUG-006**: `res.key` → `res.plain_key` en `handleCreateKey`. El backend siempre retornó `plain_key` pero el frontend leía un campo inexistente, mostrando `undefined` en el modal de key generada.

---

## Sesión 3 — 2026-06-29: Fase 6 — Polish & White-label audit

### Resumen
Corrección del pipeline de chat para forwarding de keys reales al motor, auditoría y limpieza de strings white-label en mensajes visibles al cliente.

### Archivos modificados

| Archivo | Cambios |
|---------|---------|
| `backend/src/api/chat.py` | Variables internas renombradas a `_ENGINE_URL`/`_ENGINE_MASTER_KEY`. Si la key del cliente tiene `engine_key_token`, se forwardea esa key al motor (enforcement real de budget). 4 mensajes de error client-facing limpiados de referencias al motor. |

### Decisiones técnicas
- **Forwarding selectivo**: solo keys con `engine_key_token` se forwardean al motor. Las sesiones del Playground (sin key) siguen usando el master key internamente.
- **Variables internas**: `LITELLM_URL`/`LITELLM_KEY` renombradas a `_ENGINE_URL`/`_ENGINE_MASTER_KEY` para consistencia white-label en el código fuente.

### Resultado final
- 28/28 tasks completadas ✅
- 0 strings con nombres de tecnología subyacente visibles al cliente
- Frontend limpio (0 ocurrencias)
- Backend: solo referencias en logs internos, rutas de archivo de config, y variables de entorno (infraestructura, no producto)
