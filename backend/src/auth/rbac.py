from typing import Callable
from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.user import User
from .session import get_current_user

ROLE_HIERARCHY = {
    "admin": 4,
    "compliance_officer": 3,
    "clinician": 2,
    "developer": 1,
}

# Permissions matrix: action -> minimum role required
PERMISSIONS = {
    # User management
    "create_user": {"admin"},
    "delete_user": {"admin"},
    # Key management
    "create_key": {"admin", "developer"},
    "revoke_key": {"admin", "developer"},
    # Compliance management
    "edit_compliance": {"admin", "compliance_officer"},
    "view_compliance": {"admin", "compliance_officer"},
    # Human review
    "approve_review": {"admin", "compliance_officer", "clinician"},
    # Audit logs
    "view_audit": {"admin", "compliance_officer"},
    "export_reports": {"admin", "compliance_officer"},
    # Chat / inference (all roles)
    "chat": {"admin", "compliance_officer", "clinician", "developer"},
}

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
    FastAPI dependency factory. Usage:
        @router.post("/...", dependencies=[Depends(require_role("admin", "compliance_officer"))])

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
