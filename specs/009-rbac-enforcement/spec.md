# Feature 009 — RBAC & Permission Enforcement

## Objetivo
Aplicar control de acceso basado en roles en todos los endpoints de la API. Los roles ya existen en la DB (`admin`, `compliance_officer`, `clinician`, `developer`) pero no están siendo validados.

## Roles y permisos
| Recurso                        | admin | compliance_officer | clinician | developer |
|--------------------------------|-------|--------------------|-----------|-----------|
| Crear/eliminar usuarios        | ✓     | ✗                  | ✗         | ✗         |
| Gestionar llaves virtuales     | ✓     | ✗                  | ✗         | ✓ (propias) |
| Editar proyectos de compliance | ✓     | ✓                  | ✗         | ✗         |
| Aprobar revisiones humanas     | ✓     | ✓                  | ✓         | ✗         |
| Ver audit logs                 | ✓     | ✓                  | ✗         | ✗         |
| Exportar RAT / informes        | ✓     | ✓                  | ✗         | ✗         |
| Chat / inferencia              | ✓     | ✓                  | ✓         | ✓         |

## Mecanismo
- Token de sesión (Bearer) o llave virtual incluye `user_id`
- Dependency FastAPI `require_role(*roles)` verifica en DB
- Sin sesión → usar rol `developer` por defecto (para compatibilidad con llaves sin usuario)

## Frontend
- Ocultar elementos UI según rol del usuario activo (almacenado en localStorage al login)
- Rol actual visible en header/perfil

## Fuera de alcance
- OAuth2 / SSO (fase posterior)
- Permisos a nivel de fila (row-level security)
