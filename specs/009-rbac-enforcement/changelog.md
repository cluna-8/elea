# Changelog — Feature 009: RBAC & Permission Enforcement

## [1.0.0] — 2026-06-30

### Added

**Backend**
- `backend/src/auth/session.py` — `create_session_token(user_id, role, username)` genera JWT HS256 con TTL 24h; `decode_session_token(token)` valida y extrae payload; `get_current_user(authorization, db)` FastAPI dependency que distingue llaves virtuales (SHA-256 lookup) de tokens JWT de sesión
- `backend/src/auth/rbac.py` — `require_role(*roles)` dependency factory; fail-open si no hay token de sesión (backward-compat con flujos de llave virtual)
- `backend/src/api/users.py` — endpoint `POST /users/login` con lógica de bootstrap: si el usuario `admin` no existe y se intenta hacer login como admin, se crea automáticamente con la contraseña proporcionada; retorna `access_token` JWT + datos del usuario; endpoint `POST /users` (crear usuario) protegido con `require_role("admin")`
- `backend/src/api/compliance.py`, `reports.py`, `keys.py` — endpoints sensibles protegidos con `require_role("admin", "compliance_officer")` según la matriz de permisos del spec

**Frontend**
- `frontend/src/services/auth.ts` — `authStorage` object: `save(token, user)`, `clear()`, `getToken()`, `getUser()`, `isLoggedIn()`; interface `SessionUser` (id, username, role, email); helpers `ROLE_LABELS` y `ROLE_PERMISSIONS`
- `frontend/src/pages/LoginPage.tsx` — reemplaza autenticación hardcodeada (`admin/admin`) por llamada real a `POST /users/login`; muestra logo de la aplicación; almacena token y usuario en localStorage via `authStorage`
- `frontend/src/App.tsx` — gestión de sesión con `SessionUser | null`; visibilidad de rutas según rol (compliance y audit solo para admin/compliance_officer); logo en sidebar; logout llama `authStorage.clear()`
- `frontend/src/services/api.ts` — helpers `authHeaders()` y `jsonHeaders()` que inyectan `Authorization: Bearer <token>` en todos los fetch; el token de sesión tiene menor prioridad que una llave virtual explícita en `sendChatMessage`

### Design Decisions
- **Stateless JWT**: se optó por JWT stateless en lugar de tabla de sesiones en DB. Elimina T-005 (Alembic migration para sessions table) — la revocación se maneja por expiración de 24h, aceptable para el caso de uso clínico.
- **Fail-open RBAC**: si no hay token de sesión (llamada directa con llave virtual), `require_role` no bloquea. Mantiene compatibilidad con flujos headless sin romper la API.
- **Bootstrap admin**: el usuario admin se crea automáticamente en el primer login si no existe. Evita la necesidad de scripts de seed separados para onboarding.
- **Prioridad de token en chat**: la llave virtual del usuario tiene prioridad sobre el JWT de sesión en `sendChatMessage`. El Playground sigue funcionando correctamente al usar la llave del usuario en lugar de la sesión de admin.

### Roles implementados

| Rol                 | Permisos clave |
|---------------------|---------------|
| `admin`             | Todo |
| `compliance_officer`| Compliance, reports, aprobar revisiones, ver audit logs |
| `clinician`         | Chat/inferencia, aprobar revisiones humanas |
| `developer`         | Chat/inferencia, gestionar sus propias llaves |
