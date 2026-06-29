# Changelog: LiteLLM Real Integration

**Proyecto**: Basa Secure AI Gateway (by basa dev)
**Rama**: `feature/002-litellm-sync`
**Última actualización**: 2026-06-29

---

## Sesión 1 — 2026-06-29: Spec, Plan y Tasks

### Resumen
Creación de la documentación completa del feature: spec.md, plan.md, tasks.md, contracts/litellm-api.md. Definición de la arquitectura de sincronización con LiteLLM. Commit inicial del MVP en `master`.

### Decisiones tomadas
- **Opción A (LiteLLM como fuente de verdad)** elegida sobre las alternativas.
- **Rollback best-effort**: sin transacciones distribuidas, pero con rollback en LiteLLM si falla nuestra DB.
- **Registros legacy no se migran**: los users/groups del MVP anterior (sin `litellm_team_id`) se tratan como legacy y no generan errors en UI.

---

<!-- Las sesiones de implementación se agregan aquí a medida que se van completando -->
