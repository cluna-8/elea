"""Política del modo degradado (spec 021 US4 — FR-019/FR-020).

Default = **read-only para creación** (aterrizaje suave, SC-013): en
grace/expired/over_seat el gate (gate.py) bloquea seats nuevos y el tráfico
existente sigue. El toggle ``SENTINEL_LICENSE_HARD_BLOCK=true`` endurece
``expired``/``over_seat`` a **bloqueo total**: el tráfico de /gw también se
corta (403), antes de rutear o tocar upstream. ``grace`` JAMÁS corta tráfico
(FR-019: la renovación urge, pero el cliente opera).
"""
import logging
import os
from typing import Optional

from fastapi import HTTPException

from ..models.tenant import DEFAULT_TENANT_ID
from .entitlement import STATUS_EXPIRED, expected_tenant_id, get_state
from .reconcile import RECON_OVER_SEAT, get_tenant_status

logger = logging.getLogger(__name__)

HARD_BLOCK_ENV = "SENTINEL_LICENSE_HARD_BLOCK"

# Mensaje FIJO al cliente: el corte corre ANTES de resolver identidad, así que
# jamás se filtra estado interno (seats, expiry) a un caller sin autenticar.
CLIENT_MESSAGE = ("license_degraded: acceso bloqueado por el estado de la licencia "
                  "del deployment — contactá al administrador.")


def hard_block_enabled() -> bool:
    return os.getenv(HARD_BLOCK_ENV, "").lower() == "true"


def hard_block_reason() -> Optional[str]:
    """No-None ⇒ TODO el tráfico /gw se corta con 403 (FR-020, toggle activo).

    ``expired`` sale del entitlement (deployment); ``over_seat`` del estado
    PUBLICADO por la reconciliación para el tenant licenciado (incl. el alias
    DEFAULT de la deuda 013 — mismo criterio que gate.py)."""
    if not hard_block_enabled():
        return None
    state = get_state()
    if state.status == STATUS_EXPIRED:
        return "licencia expirada más allá del grace (bloqueo total habilitado)"
    for tenant_id in (expected_tenant_id(), str(DEFAULT_TENANT_ID)):
        recon = get_tenant_status(tenant_id)
        if recon is not None and recon.status == RECON_OVER_SEAT:
            return (f"tenant en over_seat ({recon.seats_used}/{recon.max_seats} seats) "
                    "— bloqueo total habilitado")
    return None


async def require_not_hard_blocked() -> None:
    """Dependency de las rutas de SERVICIO bajo /gw (FR-020, bloqueo total):
    messages, count_tokens, models, whoami e inspect — el discovery (GET /gw)
    queda abierto para diagnóstico. El detalle del motivo va a logs
    server-side; el cliente recibe el mensaje genérico."""
    reason = hard_block_reason()
    if reason is not None:
        logger.warning("gateway: tráfico cortado por bloqueo total de licencia — %s", reason)
        raise HTTPException(status_code=403, detail=CLIENT_MESSAGE)
