# Tasks — 009 RBAC & Permission Enforcement

## Phase 1 — Backend
- [x] T-001: Create `backend/src/auth/rbac.py` — require_role(*roles) FastAPI dependency
- [x] T-002: Create `backend/src/auth/session.py` — get_current_user from Bearer token
- [x] T-003: Add session token generation to login endpoint (users.py)
- [x] T-004: Apply require_role to users/keys/compliance/reports endpoints
- [ ] T-005: Add Alembic migration for sessions table — N/A: using stateless JWT, no sessions table needed

## Phase 2 — Frontend
- [x] T-006: Login page → store token + role in localStorage
- [x] T-007: Auth context / hook (useCurrentUser) — implemented as authStorage in auth.ts
- [x] T-008: Hide admin-only UI elements based on role
- [x] T-009: Add Authorization header to all api.ts requests
