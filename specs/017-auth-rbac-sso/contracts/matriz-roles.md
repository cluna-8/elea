# Contrato · La matriz canónica rol×superficie (FR-001/002/003)

**Fuente única.** `backend/src/auth/matrix.py` es su espejo 1:1 en código; el harness (FR-005) recorre TODOS los endpoints gateados y falla si el código diverge de esta tabla. Cambiar la matriz = cambiar este archivo + matrix.py en el mismo PR.

Roles canónicos: `super_admin` · `tenant_admin` · `compliance_officer` · `client` · `lectura` (nuevo).
En C2 `super_admin` sigue operativamente equivalente a `tenant_admin` (su semántica cross-tenant despierta con el multi-tenant real — Out of scope). El shim traduce hacia los literales legacy de los routers; los labels sectoriales (`clinician`/`developer`) siguen siendo display (D9 constitución).

## La matriz (por grupos de superficie)

| Grupo de superficie (routers) | super/tenant_admin | compliance_officer | client | lectura |
|---|---|---|---|---|
| Gestión de identidad y acceso (users, keys, groups) | **RW** | R | — (solo su perfil/sus keys, como hoy) | — |
| Config de producto (guardians, policy, router_config, governance, budgets) | **RW** | R | — | — |
| Compliance config (retention ← FR-009 de la 018, security policies, consent admin) | **RW** | **R** (pierde W) | — | — |
| Artefactos compliance (projects, DPAs, DSRs) | **RW** | **R** (pierde W) | — | — |
| **Human reviews — resolver (aprobar/rechazar)** | RW | **W** ✅ *única escritura del auditor, nombrada* | — | — |
| Vitrinas y lectura (audit, monitor, reports, costs-read, health detallado) | R | R | (lo suyo, como hoy) | **R** ✅ |
| Costs config (budgets write, compression por grupo) | **RW** | **R** (pierde W) | — | — |
| Chat / Playground (`POST /chat/completions`, camino JWT) | ✔ | ✔ | ✔ | **✖ 403** (FR-003: el camino JWT del dual-auth gatea rol — hoy no gatea, chat.py:744-782) |
| Chat camino sk-sentinel (herramientas) | n/a — autentica la KEY, no el rol (sin cambios) | | | |

## Reglas duras

1. **compliance_officer**: solo-lectura con la excepción nombrada (resolver human reviews). Sus 8 escrituras actuales (compliance.py:319 retention; :133-271 projects/DPAs/DSRs; consent.py:91,125; policy.py:76-138; costs.py:299,338) pasan a tenant_admin. **Deja de probar «dueño»**: `ROLES_QUE_PRUEBAN_DUENO = {tenant_admin, super_admin}` (users.py:32) — evita el deadlock instalación-con-dueño-sin-admin-creable.
2. **lectura**: cero mutaciones, cero chat, no prueba dueño, no consume seat (el seat sigue siendo la Connection — sin cambios en seat_counter). Paquete de ~5 ediciones acopladas: CHECK `ck_users_role` + `normalize_legacy_role` + shim + frontend (toLegacyRole/nav) + el `u.role` del SQL espejo al motor — UNA tarea, un checklist.
3. **Actor propagado (FR-004, cierra #72)**: la dependencia de autorización inyecta el `User` al endpoint; toda mutación admin audita actor (id + rol) además del hecho.
4. **El harness es la ley (FR-005)**: test parametrizado que enumera los 15 routers + chat-JWT contra esta tabla; endpoint nuevo sin fila en la matriz = test rojo (feature, no bug). El router #147 de Cristian entra al harness vía el shim sin tocar su código.
5. Migración de instalaciones vivas (Cámara): CERO migración de datos — cambia la matriz, no las filas; nota de release obligatoria (SC-007) y el test ancla `test_rol_auditor.py` se actualiza en el mismo PR que el recorte.
