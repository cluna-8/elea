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

from ..models.tenant import DEFAULT_TENANT_ID
from .audit_events import EVENT_SEAT_LIMIT, emit_license_event
from .entitlement import CREATION_ALLOWED_STATUSES, get_state
from .reconcile import RECON_OVER_SEAT, get_tenant_status
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
    # Principio III: un entitlement de OTRO tenant no habilita crear acá.
    # El entitlement quedó anclado al tenant del DEPLOYMENT en el arranque
    # (FR-005: token.tenant == BASA_DEPLOYMENT_TENANT_ID); el parámetro es el
    # tenant de la FILA a crear. Deuda 013: los handlers aún no resuelven
    # tenant y toda fila cae en DEFAULT_TENANT_ID, así que el default es un
    # alias válido del tenant licenciado — sin él, un deployment con tenant
    # real y licencia válida bloquearía TODA creación con 403. Cuando los
    # call-sites pasen el tenant real de la fila, este check activa el
    # aislamiento por tenant de verdad.
    row_tenant = str(tenant_id)
    if row_tenant not in (token.tenant_id, str(DEFAULT_TENANT_ID)):
        raise HTTPException(
            status_code=403,
            detail="license_creation_blocked: sin entitlement para este tenant (fail-closed).",
        )
    # Modo degradado por drift (US3, FR-016/FR-020): si la reconciliación
    # PUBLICÓ over_seat para este tenant, la creación queda bloqueada hasta que
    # una corrida lo devuelva a ok — el estado manda aunque el conteo vivo haya
    # bajado del tope (la transición ya quedó auditada por la reconciliación).
    # US4 (T029) extiende este mismo punto a grace/expired del ciclo de vida.
    recon = get_tenant_status(row_tenant)
    if recon is not None and recon.status == RECON_OVER_SEAT:
        raise HTTPException(
            status_code=403,
            detail=(f"license_creation_blocked: tenant en over_seat por reconciliación "
                    f"({recon.seats_used}/{recon.max_seats} seats) — modo degradado, "
                    "la creación se rehabilita cuando la reconciliación vuelva a ok."),
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
