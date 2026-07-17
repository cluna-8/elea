"""Eventos de licencia → AuditLog inmutable existente (spec 021, FR-022/024/025).

Reusa el canal append-only de la 013 SIN cambios de schema (Assumption de la
spec / T012): cada transición de licencia es una fila con ``model='license'``
y el detalle metadata-only dentro de ``guardian_events``. NUNCA se persiste el
token crudo, la firma ni claves (Constraint C1). La cadena de hashes (FR-028)
se añade en US5 sobre estas mismas entradas.
"""
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

EVENT_LOADED = "license_loaded"
EVENT_GRACE = "license_grace"
EVENT_EXPIRED = "license_expired"
EVENT_INVALID = "license_invalid"
EVENT_MISMATCH = "license_tenant_mismatch"
EVENT_MISSING = "license_missing"
EVENT_SEAT_LIMIT = "license_seat_limit_exceeded"
# Transiciones de la reconciliación (US3, FR-016): entrada/salida de over_seat.
EVENT_OVER_SEAT = "license_over_seat"
EVENT_OVER_SEAT_RESOLVED = "license_over_seat_resolved"

_EVENT_BY_STATUS = {
    "active": EVENT_LOADED,
    "grace": EVENT_GRACE,
    "expired": EVENT_EXPIRED,
    "invalid": EVENT_INVALID,
    "mismatch": EVENT_MISMATCH,
    "missing": EVENT_MISSING,
}

# Convención del canal existente: passed | flagged_high_risk | blocked_by_policy.
_COMPLIANCE_BY_EVENT = {
    EVENT_LOADED: "passed",
    EVENT_GRACE: "flagged_high_risk",  # advierte: opera pero la renovación urge
    EVENT_OVER_SEAT_RESOLVED: "passed",
}


def emit_license_event(db, event_type: str, *, tenant_id=None, license_id=None,
                       seats_used: Optional[int] = None, max_seats: Optional[int] = None,
                       reason: Optional[str] = None) -> None:
    """Persiste UNA transición de licencia como fila del AuditLog (metadata-only)."""
    from ..models.audit import AuditLog
    from ..models.tenant import DEFAULT_TENANT_ID

    entry = {
        "event_type": event_type,
        "license_id": license_id,
        "seats_used": seats_used,
        "max_seats": max_seats,
        "reason": reason,
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    row_tenant = tenant_id or DEFAULT_TENANT_ID
    if isinstance(row_tenant, str):
        row_tenant = uuid.UUID(row_tenant)
    db.add(AuditLog(
        tenant_id=row_tenant,
        model="license",
        prompt_tokens=0,
        completion_tokens=0,
        cost_usd=0,
        pii_detected=False,
        compliance_status=_COMPLIANCE_BY_EVENT.get(event_type, "blocked_by_policy"),
        latency_ms=0,
        guardian_events=[entry],
    ))
    db.commit()


def emit_startup_event(state, session_factory=None) -> None:
    """Evento del gate de arranque (US1/T012). El tenant de la fila es SIEMPRE
    el del deployment (existe por seed 013); si el token era de otro tenant,
    ese dato viaja en ``reason`` (no como FK, que no existiría acá)."""
    from .entitlement import expected_tenant_id

    event_type = _EVENT_BY_STATUS.get(state.status, EVENT_INVALID)
    token = state.token
    if session_factory is None:
        from ..database import SessionLocal
        session_factory = SessionLocal
    db = session_factory()
    try:
        emit_license_event(
            db,
            event_type,
            tenant_id=expected_tenant_id(),
            license_id=token.license_id if token else None,
            max_seats=token.max_seats if token else None,
            reason=state.reason,
        )
    except Exception:  # noqa: BLE001 — fail-soft (criterio de AuditService)
        db.rollback()
        logger.exception("licencia: fallo al persistir el evento %s", event_type)
    finally:
        db.close()
