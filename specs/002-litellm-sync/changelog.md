# Changelog: LiteLLM Real Integration

**Proyecto**: Basa Secure AI Gateway (by basa dev)
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

<!-- Las sesiones de implementación se agregan aquí a medida que se van completando -->
