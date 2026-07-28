"""Health de licencia (spec 021 US5, T034 — FR-027) y de AUDITORÍA (spec 031 US2, T009).

Metadata-only para operación/soporte: NUNCA el token crudo ni claves. Dos
niveles (lección del review de US4 — números no viajan a anónimos):

- sin sesión: sólo ``{status, clock_rollback_suspected}`` — suficiente para un
  probe de ops ("¿la licencia está sana?") sin filtrar dimensionamiento.
- con sesión válida (JWT): además ``seats_used/max_seats/expiry/reason`` y el
  resumen por tenant de la última reconciliación.

El mismo criterio de dos tiers se aplica al ``GET /api/v1/health`` de la 031: el
estado global (healthy/degraded) es público —es la pregunta que responde un probe— y
los NÚMEROS de auditoría (cuántos eventos se perdieron, cuándo fue el último fallo)
sólo viajan a admin/compliance_officer, que son exactamente los roles que pueden ver
Logs de Auditoría. Publicar "la auditoría lleva 40 eventos sin registrar" a un caller
anónimo es decirle a quien quiera fugar datos cuál es el mejor momento para hacerlo.
"""
import logging
import os
from typing import Optional, Tuple

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..auth.rbac import effective_roles
from ..auth.session import get_current_user
from ..database import get_db
from ..licensing import reconcile
from ..licensing.entitlement import expected_tenant_id, get_state
from ..licensing.seat_counter import count_active_seats
from ..models.user import User
from ..services import audit_service
from ..services.redis_client import get_redis

logger = logging.getLogger("basa-secure-gateway.health")

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


# ── Health de auditoría (spec 031 US2, T009 — FR-004 / contrato §health) ─────────────
#
# Por qué un `/health` NUEVO bajo /api/v1 y no el `/health` raíz de main.py: ese endpoint
# es el `healthcheck` del contenedor (compose.prod.yml:95). Meterle una lectura de Redis
# y un `SELECT 1` convertiría una degradación de una dependencia en "contenedor unhealthy"
# → reinicio → caída del servicio entero por algo que la 031 define explícitamente como
# NO fatal en `open`. El probe del orquestador tiene que seguir contestando barato y
# siempre; este es el health de PRODUCTO, que es el que puede decir "degradado".
# Lo consume el quickstart (`curl .../api/v1/health | jq .audit`) y el banner de Logs.


def _leer_contadores_de_perdida() -> Tuple[Optional[int], Optional[str]]:
    """`(lost_events, last_failure_at)` desde Redis (contrato §Contador de pérdidas).

    Distinción que importa y que el consumidor NO puede adivinar solo:

    * ``0``    — la auditoría no ha perdido nada (la clave nunca se escribió).
    * ``N``    — hay N eventos sin registrar desde ``last_failure_at``.
    * ``None`` — **no se pudo leer el contador** (Redis caído o valor ilegible). Es
      deliberadamente distinto de ``0``: decir "cero pérdidas" cuando no se pudo mirar
      sería exactamente la mentira que esta spec existe para borrar.

    Nunca propaga: el health no puede caerse porque Redis no esté.
    """
    try:
        redis_conn = get_redis()
        if redis_conn is None:
            logger.warning("health: contador de auditoría ilegible — Redis no disponible")
            return None, None
        crudo = redis_conn.get(audit_service.REDIS_KEY_AUDIT_LOST)
        ultimo = redis_conn.get(audit_service.REDIS_KEY_AUDIT_LAST_FAIL)
    except Exception as exc:  # noqa: BLE001 — Redis caído no puede tumbar el health
        logger.warning("health: contador de auditoría ilegible (%s)", exc)
        return None, None

    perdidos: Optional[int]
    if crudo is None:
        perdidos = 0  # clave nunca escrita = jamás hubo una pérdida
    else:
        try:
            # `decode_responses=True` devuelve str, pero un cliente configurado distinto
            # (o un Redis compartido) puede devolver bytes: se normaliza acá y no en el
            # caller, para que el contrato del bloque sea siempre int|None.
            perdidos = int(crudo.decode() if isinstance(crudo, bytes) else crudo)
        except (TypeError, ValueError):
            logger.warning("health: valor ilegible en %s: %r",
                           audit_service.REDIS_KEY_AUDIT_LOST, crudo)
            perdidos = None
    if isinstance(ultimo, bytes):
        ultimo = ultimo.decode()
    return perdidos, ultimo


def _estado_de_auditoria(db: Session) -> Tuple[str, Optional[str]]:
    """`(modo, motivo_degradado)`.

    El pre-check de escribibilidad SÓLO se paga en `closed` (edge case de la spec: "el
    health refleja el estado, no un healthy mentiroso"). En `open` una auditoría caída no
    degrada el servicio —el tráfico se sigue sirviendo por diseño— y su señal es el
    contador + el banner, así que no hay razón para pagar un `SELECT 1` por cada probe.
    """
    modo = audit_service.audit_fail_mode()
    if modo != audit_service.AUDIT_FAIL_CLOSED:
        return modo, None
    if audit_service.audit_writable(db):
        return modo, None
    return modo, ("auditoría no escribible y la instalación exige registro "
                  "(audit_fail=closed): el tráfico nuevo se rechaza con 503")


@router.get("/health")
def service_health(user: Optional[User] = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    """Health del producto, con el bloque `audit` del contrato §health.

    Tier anónimo: `{status, service, version}` — el estado global sí es público (un probe
    de ops sin credenciales tiene que poder preguntar "¿esto está sano?"), los números no.
    Tier admin/compliance_officer: además `audit {mode, lost_events, last_failure_at}` y el
    `reason` de la degradación.
    """
    modo, motivo_degradado = _estado_de_auditoria(db)
    body = {
        "status": "degraded" if motivo_degradado else "healthy",
        "service": os.getenv("BRAND_SERVICE_ID", "basa-secure-ai-gateway-backend"),
        "version": "1.0.0",
    }
    if user is None or effective_roles(user).isdisjoint(_DETAIL_ROLES):
        return body

    perdidos, ultimo_fallo = _leer_contadores_de_perdida()
    body["audit"] = {
        "mode": modo,
        "lost_events": perdidos,
        "last_failure_at": ultimo_fallo,
    }
    body["reason"] = motivo_degradado
    return body
