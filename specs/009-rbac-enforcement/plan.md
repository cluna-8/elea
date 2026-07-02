# Plan — Feature 009: RBAC & Permission Enforcement

> As-built: documenta lo que se implementó.

## Archivos creados

| Archivo | Descripción |
|---------|-------------|
| `backend/src/auth/rbac.py` | `require_role(*roles)` — FastAPI dependency que valida el rol del JWT |
| `backend/src/auth/session.py` | `create_session_token(user)`, `decode_session_token(token)`, `get_current_user` dependency |

## Archivos modificados

| Archivo | Cambio |
|---------|--------|
| `backend/src/api/users.py` | Endpoint `POST /users/login` → genera JWT 24h; endpoints de creación/eliminación protegidos con `require_role("admin")` |
| `backend/src/api/compliance.py` | Endpoints de revisión humana protegidos con `require_role("admin", "compliance_officer", "clinician")` |
| `backend/src/api/reports.py` | Endpoints RAT/DSAR/executive protegidos con `require_role("admin", "compliance_officer")` |
| `frontend/src/pages/LoginPage.tsx` | Página de login real con logo, llamada a `/users/login`, almacena JWT + rol |
| `frontend/src/services/auth.ts` | `authStorage` (get/set/clear), `SessionUser`, `ROLE_LABELS` |
| `frontend/src/services/api.ts` | Header `Authorization: Bearer <token>` en todas las peticiones |
| `frontend/src/App.tsx` | Gestión de sesión, RBAC nav (oculta ítems según rol), logout |

## Decisiones clave

- JWT stateless HS256, TTL 24h — sin tabla de sesiones en DB. Revocación por expiración únicamente.
- RBAC fail-open: sin token de sesión → las llamadas se permiten (backward-compat con virtual keys directas).
- `require_role` lanza HTTP 403 si el token es válido pero el rol no tiene permiso; HTTP 401 si el token es inválido/ausente.
- No se implementó tabla de sesiones (T-005 N/A): el JWT es suficiente para el modelo de seguridad actual.
- Bootstrap admin: primer login como "admin" crea el usuario automáticamente con la contraseña proporcionada.
