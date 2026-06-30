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


def require_role(*roles: str) -> Callable:
    """
    FastAPI dependency factory. Usage:
        @router.post("/...", dependencies=[Depends(require_role("admin", "compliance_officer"))])
    If no session token is present, falls back to permissive mode (backward compat).
    """
    allowed = set(roles)

    def _check(user: User = Depends(get_current_user)):
        if user is None:
            # No session token: allow (backward-compat for playground / virtual key flows)
            return
        if user.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Acción no permitida para el rol '{user.role}'. Se requiere uno de: {', '.join(sorted(allowed))}.",
            )

    return _check
