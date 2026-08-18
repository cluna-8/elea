from typing import Callable
from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.user import User
from .session import get_current_user

# ── (T006, spec 017) `PERMISSIONS`/`ROLE_HIERARCHY` borrados: eran dead code ──
# `require_role` nunca consultó `PERMISSIONS` (gatea con los literales que recibe) y
# `ROLE_HIERARCHY` no tenía un solo lector fuera de este archivo (grep en todo backend/).
# La fuente única de verdad rol×superficie es ahora `auth/matrix.py` (MATRIZ), verificada
# endpoint-por-endpoint por el harness FR-005 (`tests/integration/test_role_matrix.py`).

# ── Shim de compatibilidad post-013 (transicional hasta el refactor RBAC de 017) ──
# La migración 010 reconcilió los roles ([D9]): admin→tenant_admin,
# clinician/developer→client+display_label. Los gates de la API siguen escritos con
# los nombres legacy; este mapeo expande el rol del usuario a sus equivalentes para
# que un usuario migrado conserve EXACTAMENTE los permisos que tenía (SC-002, cero
# regresión). La matriz definitiva por-tenant la define la spec 017.
_LEGACY_EQUIVALENTS = {
    "tenant_admin": {"admin"},
    "super_admin": {"admin"},   # cross-tenant ≥ admin dentro del tenant
}
_CLIENT_LABEL_EQUIVALENTS = {"clinician", "developer"}


def effective_roles(user: User) -> set:
    roles = {user.role}
    roles |= _LEGACY_EQUIVALENTS.get(user.role, set())
    label = getattr(user, "display_label", None)
    if user.role == "client" and label in _CLIENT_LABEL_EQUIVALENTS:
        roles.add(label)
    return roles


def require_role(*roles: str) -> Callable:
    """
    FastAPI dependency factory. Dos usos, MISMA puerta (ambos fail-closed):
        # (1) puerta sola — no necesitás el actor:
        @router.post("/...", dependencies=[Depends(require_role("admin", "compliance_officer"))])
        # (2) puerta + actor inyectado (FR-004 / #72 — auditar QUIÉN mutó):
        async def endpoint(..., user: User = Depends(require_role("admin"))):
    `_check` devuelve el `User` autenticado. En la forma (1) FastAPI descarta el retorno del
    dependency, así que agregar el `return` es backward-compatible con los ~45 call sites
    `dependencies=[...]` existentes; la forma (2) lo recibe para escribir el actor en la bitácora.

    Fail-closed: a valid session JWT resolving to an active user is REQUIRED. If no token is
    present (or it's invalid/expired), the request is rejected with 401. Virtual keys (sk-*)
    never resolve to a session user, so admin/management endpoints protected by this dependency
    are not reachable via virtual keys — by design. Inference endpoints that must accept
    virtual keys (chat/completions) implement their own dual-auth and do NOT use this dependency.
    """
    allowed = set(roles)

    def _check(user: User = Depends(get_current_user)):
        if user is None:
            # No valid session user → deny. Never fail-open on management endpoints.
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Autenticación requerida: sesión JWT válida no proporcionada o expirada.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        if allowed.isdisjoint(effective_roles(user)):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Acción no permitida para el rol '{user.role}'. Se requiere uno de: {', '.join(sorted(allowed))}.",
            )
        return user  # actor inyectable (FR-004); descartado en la forma dependencies=[...]

    return _check


def require_authenticated() -> Callable:
    """
    FastAPI dependency factory. Requires a valid session JWT (any role) — used for read-only
    endpoints shown to all logged-in users (dashboard status, model catalog, pricing).
    Fail-closed: no valid session → 401. Virtual keys are not accepted here.
    """

    def _check(user: User = Depends(get_current_user)):
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Autenticación requerida: sesión JWT válida no proporcionada o expirada.",
                headers={"WWW-Authenticate": "Bearer"},
            )

    return _check
