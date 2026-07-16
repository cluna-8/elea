"""Gate de seats en la CREACIÓN (spec 021 US2 — FR-008/009/010/011).

Segunda guarda del call-site de creación (la primera es el 409 de duplicados,
FR-011: independientes). Corre ANTES de cualquier provisioning al motor:
una request rechazada no toca ``ai_engine_client`` ni crea filas de dominio —
sólo deja el evento de audit del rechazo (T021).

Fail-closed en TODOS los caminos (FR-010): sin entitlement válido PARA ESTE
tenant no se crea nada; "sin token" jamás significa "ilimitado".
"""
import logging

from fastapi import HTTPException

from .audit_events import EVENT_SEAT_LIMIT, emit_license_event
from .entitlement import CREATION_ALLOWED_STATUSES, get_state
from .seat_counter import count_active_seats

logger = logging.getLogger(__name__)


def enforce_seat_gate(db, tenant_id) -> None:
    """Levanta 402/403 si la creación del seat no está licenciada.

    402 = tope de seats alcanzado (``license_seat_limit_exceeded``).
    403 = licencia degradada/ausente/de otro tenant (``license_creation_blocked``).
    """
    state = get_state()
    token = state.token
    if state.status not in CREATION_ALLOWED_STATUSES or token is None:
        # missing/invalid/mismatch (FR-006) y grace/expired (FR-019/020):
        # el tráfico existente sigue; sólo la CREACIÓN se bloquea.
        detail = (f"license_creation_blocked: licencia en estado '{state.status}' — "
                  "la creación de seats está bloqueada (fail-closed).")
        if state.reason:
            detail = f"{detail} {state.reason}"
        raise HTTPException(status_code=403, detail=detail)
    if token.tenant_id != str(tenant_id):
        # Principio III: un entitlement de OTRO tenant no habilita crear acá.
        raise HTTPException(
            status_code=403,
            detail="license_creation_blocked: sin entitlement para este tenant (fail-closed).",
        )
    seats_used = count_active_seats(db, tenant_id)
    if seats_used >= token.max_seats:
        try:
            emit_license_event(
                db, EVENT_SEAT_LIMIT,
                tenant_id=tenant_id,
                license_id=token.license_id,
                seats_used=seats_used,
                max_seats=token.max_seats,
                reason="creación de seat rechazada por tope de licencia",
            )
        except Exception:  # noqa: BLE001 — audit best-effort, el rechazo va igual
            db.rollback()
            logger.exception("licencia: no se pudo auditar el rechazo del seat-gate")
        raise HTTPException(
            status_code=402,
            detail=(f"license_seat_limit_exceeded: {seats_used}/{token.max_seats} seats "
                    "activos — la licencia no permite crear más. Revocá una Connection "
                    "o ampliá la licencia."),
        )
