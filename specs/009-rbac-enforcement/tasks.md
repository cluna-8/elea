# Tasks — 009 RBAC & Permission Enforcement

## Phase 1 — Backend
- [ ] T-001: Create `backend/src/auth/rbac.py` — require_role(*roles) FastAPI dependency
- [ ] T-002: Create `backend/src/auth/session.py` — get_current_user from Bearer token
- [ ] T-003: Add session token generation to login endpoint (users.py)
- [ ] T-004: Apply require_role to users/keys/compliance/reports endpoints
- [ ] T-005: Add Alembic migration for sessions table

## Phase 2 — Frontend
- [ ] T-006: Login page → store token + role in localStorage
- [ ] T-007: Auth context / hook (useCurrentUser)
- [ ] T-008: Hide admin-only UI elements based on role
- [ ] T-009: Add Authorization header to all api.ts requests
