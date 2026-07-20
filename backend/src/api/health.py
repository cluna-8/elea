"""Health de licencia (spec 021 US5, T034 — FR-027).

Metadata-only para operación/soporte: NUNCA el token crudo ni claves. Dos
niveles (lección del review de US4 — números no viajan a anónimos):

- sin sesión: sólo ``{status, clock_rollback_suspected}`` — suficiente para un
  probe de ops ("¿la licencia está sana?") sin filtrar dimensionamiento.
- con sesión válida (JWT): además ``seats_used/max_seats/expiry/reason`` y el
  resumen por tenant de la última reconciliación.
"""
from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..auth.rbac import effective_roles
from ..auth.session import get_current_user
from ..database import get_db
from ..licensing import reconcile
from ..licensing.entitlement import expected_tenant_id, get_state
from ..licensing.seat_counter import count_active_seats
from ..models.user import User

router = APIRouter(tags=["Health"])

# Tier detallado: solo roles de operación/soporte (hardening post-review — un
# user client autenticado tampoco tiene por qué ver dimensionamiento/reasons).
_DETAIL_ROLES = {"admin", "compliance_officer"}


@router.get("/health/license")
def license_health(user: Optional[User] = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    state = get_state()
    body = {
        "status": state.status,
        "clock_rollback_suspected": reconcile.clock_rollback_suspected(),
    }
    if user is None or effective_roles(user).isdisjoint(_DETAIL_ROLES):
        return body
    from ..models.license_state import LicenseRuntimeState
    runtime = db.query(LicenseRuntimeState).filter(LicenseRuntimeState.id == 1).one_or_none()
    token = state.token
    tenant_id = expected_tenant_id()
    recon = reconcile.get_tenant_status(tenant_id)
    body.update({
        "reason": state.reason,
        "expiry": token.expiry.isoformat() if token else None,
        "grace_days": token.grace_days if token else None,
        "max_seats": token.max_seats if token else None,
        "seats_used": count_active_seats(db, tenant_id),
        # Génesis EFECTIVA de la cadena: lo que el onboarding debe registrar
        # (si el primer boot fue sin licencia, viaja también el anclaje).
        "chain": {
            "genesis_license_id": runtime.genesis_license_id if runtime else None,
            "anchored_license_id": runtime.anchored_license_id if runtime else None,
            "event_counter": runtime.event_counter if runtime else 0,
        },
        "reconcile": {
            "tenant_status": recon.status if recon else None,
            "checked_at": recon.checked_at.isoformat() if recon else None,
        },
    })
    return body
