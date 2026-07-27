"""Reconciliación periódica LOCAL de seats por tenant (spec 021 US3 —
FR-015/016/017).

Red de seguridad detrás del gate de creación (US2): re-cuenta los seats con
la MISMA definición (``seat_counter.count_active_seats``, [D-021]) y detecta
drift que el gate no puede ver — DB directa, restauración de backup, bugs,
``seed_client`` (013) — publicando ``{ok|over_seat|expired}`` POR TENANT en un
registro en memoria. 100% local: ninguna corrida sale de la caja (sin
phone-home; el true-up verificable es US5).

Aislamiento (FR-017, Principio III): cada tenant se evalúa solo — su conteo,
su estado. Un tenant SIN entitlement con seats activos publica ``over_seat``
(fail-closed: seats sin licencia están sobre el entitlement, que es cero); el
estado ``expired`` refleja el ciclo de vida del entitlement del deployment.

El audit es POR TRANSICIÓN (entrada/salida de over_seat), no por corrida: la
evidencia queda sin spamear el AuditLog. Las transiciones de ciclo de vida
(active→grace→expired) las audita US4 sobre este mismo estado publicado.
"""
import logging
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Optional

from ..models.tenant import DEFAULT_TENANT_ID
from .audit_events import (
    EVENT_CLOCK_ROLLBACK,
    EVENT_OVER_SEAT,
    EVENT_OVER_SEAT_RESOLVED,
    emit_license_event,
)
from .entitlement import STATUS_EXPIRED, get_state, refresh
from .seat_counter import count_active_seats

logger = logging.getLogger(__name__)

RECON_OK = "ok"
RECON_OVER_SEAT = "over_seat"
RECON_EXPIRED = "expired"

DEFAULT_INTERVAL_SECONDS = 300.0
INTERVAL_ENV = "BASA_LICENSE_RECONCILE_INTERVAL_SECONDS"

# Tolerancia del anti-rollback (FR-023). El ataque que la marca persigue es retrasar
# el reloj HORAS o DÍAS para estirar una licencia; una inversión de micro/milisegundos
# es ruido de concurrencia, no un ataque: con N workers, cada uno con su thread de
# reconciliación, el tick de un worker puede capturar `now` un instante ANTES de que
# otro worker commitee un evento que avanza la marca — y ese falso positivo degradaba
# la creación con 403 hasta el próximo tick (300s). Reproducido en el ensayo del
# 2026-07-27 sobre una instalación recién arrancada: bootstrap de admin → alta del
# primer usuario → 403 "rollback de reloj sospechado", con todos los relojes sanos.
# 60s no le regala nada a un atacante (para ganar tiempo de licencia necesitaría
# retroceder muchísimo más) y elimina la clase entera de carreras entre workers.
CLOCK_ROLLBACK_TOLERANCE_SECONDS = 60.0


@dataclass(frozen=True)
class TenantSeatStatus:
    status: str
    seats_used: int
    max_seats: Optional[int]  # None = tenant sin entitlement (fail-closed)
    checked_at: datetime


# Estado publicado {str(tenant_id): TenantSeatStatus}. Se reemplaza ATÓMICO
# (swap de referencia) al final de cada corrida: el gate lee snapshots
# consistentes sin locks.
_registry: Dict[str, TenantSeatStatus] = {}

_thread: Optional[threading.Thread] = None
_stop = threading.Event()

# Episodio de rollback de reloj sospechado (US5, FR-023): flag en memoria; la
# MARCA que lo sostiene persiste en license_runtime_state (sobrevive reinicios).
_clock_rollback = False


def clock_rollback_suspected() -> bool:
    """True mientras el reloj local esté DETRÁS de la marca monotónica
    persistida — el gate degrada la creación durante el episodio."""
    return _clock_rollback


def _check_clock(db, now) -> None:
    """FR-023: si ``now`` < marca persistida → evento (una vez por episodio) +
    degradado; si el reloj la supera, cierra el episodio y avanza la marca
    (también en ticks sin eventos — el primer tick la SIEMBRA).

    IMPORTANTE: sale SIEMPRE con la transacción cerrada (commit/rollback) — el
    FOR UPDATE de la fila singleton no puede quedar tomado cuando refresh()
    emita con su propia sesión, o se bloquearían entre sí."""
    global _clock_rollback
    from .audit_events import _locked_state

    lic_state = get_state()
    state = _locked_state(db, lic_state.token.license_id if lic_state.token else None)
    mark = state.monotonic_ts
    now_naive = now.replace(tzinfo=None) if now.tzinfo else now
    if mark is not None and (mark - now_naive).total_seconds() > CLOCK_ROLLBACK_TOLERANCE_SECONDS:
        if not _clock_rollback:
            _clock_rollback = True
            logger.warning("licencia: ROLLBACK de reloj sospechado — now=%s < marca=%s; "
                           "creación degradada (FR-023)", now_naive, mark)
            try:
                emit_license_event(
                    db, EVENT_CLOCK_ROLLBACK,
                    license_id=lic_state.token.license_id if lic_state.token else None,
                    reason=f"now {now_naive.isoformat()} < marca monotónica {mark.isoformat()}",
                    now=now,
                )  # commit adentro → libera el lock
            except Exception:  # noqa: BLE001 — audit best-effort, el degradado va igual
                db.rollback()
                logger.exception("licencia: no se pudo auditar el rollback de reloj")
        else:
            db.rollback()  # mismo episodio: nada que persistir, liberar el lock
        return
    if _clock_rollback:
        logger.info("licencia: reloj recuperado (now=%s ≥ marca) — episodio cerrado", now_naive)
    _clock_rollback = False
    if mark is None or now_naive > mark:
        state.monotonic_ts = now_naive
    db.commit()  # persiste marca/creación de la fila y libera el lock


def get_tenant_status(tenant_id) -> Optional[TenantSeatStatus]:
    """Estado publicado del tenant en la ÚLTIMA corrida (None = nunca corrió
    o el tenant no existía). El gate (US2) lo consulta para el degradado."""
    return _registry.get(str(tenant_id))


def get_all_statuses() -> Dict[str, TenantSeatStatus]:
    return dict(_registry)


def _emit_transition(db, tenant_id, previous, entry) -> None:
    """Audit de entrada/salida de over_seat (FR-016 → canal de US2/T021).
    Best-effort: la publicación del estado va igual si el audit falla."""
    state = get_state()
    license_id = state.token.license_id if state.token else None
    event = None
    if entry.status == RECON_OVER_SEAT and (previous is None or previous.status != RECON_OVER_SEAT):
        event = EVENT_OVER_SEAT
    elif (entry.status == RECON_OK and previous is not None
          and previous.status == RECON_OVER_SEAT):
        event = EVENT_OVER_SEAT_RESOLVED
    if event is None:
        return
    try:
        emit_license_event(
            db, event,
            tenant_id=tenant_id,
            license_id=license_id,
            seats_used=entry.seats_used,
            max_seats=entry.max_seats,
            reason=("reconciliación: seats activos por encima del entitlement"
                    if event == EVENT_OVER_SEAT
                    else "reconciliación: conteo de seats de vuelta dentro del entitlement"),
            now=entry.checked_at,  # ts de la evidencia = el del tick (reloj inyectable)
        )
    except Exception:  # noqa: BLE001 — audit best-effort, criterio de AuditService
        db.rollback()
        logger.exception("reconciliación: no se pudo auditar la transición %s", event)


def run_once(session_factory=None, now: Optional[datetime] = None) -> Dict[str, TenantSeatStatus]:
    """UNA corrida: cuenta, compara, publica y audita transiciones.

    El entitlement vigente ancla qué tenant está licenciado (token.tenant_id
    + el alias DEFAULT de la deuda 013 — MISMO criterio que gate.py); el resto
    se evalúa fail-closed contra entitlement cero.
    """
    global _registry
    now = now or datetime.now(timezone.utc)
    if session_factory is None:
        from ..database import SessionLocal
        session_factory = SessionLocal
    from ..models.tenant import Tenant

    db = session_factory()
    try:
        # Anti-rollback (US5/T033, FR-023): compara now vs la marca monotónica
        # persistida ANTES de todo — el episodio degrada la creación (gate).
        _check_clock(db, now)
        # Tick del ciclo de vida (US4/T027-T029): el reloj local avanza ACÁ — un
        # proceso vivo cruza expiry/grace sin reinicio y la transición se audita.
        state = refresh(now=now, session_factory=session_factory)
        token = state.token
        licensed = {token.tenant_id, str(DEFAULT_TENANT_ID)} if token is not None else set()
        # Orden determinista: si la corrida muere a mitad, el reintento repite
        # la misma secuencia (y los tests pueden razonar sobre ella).
        tenants = (db.query(Tenant).filter(Tenant.is_active.is_(True))
                   .order_by(Tenant.id).all())
        fresh: Dict[str, TenantSeatStatus] = {}
        for tenant in tenants:
            key = str(tenant.id)
            seats_used = count_active_seats(db, tenant.id)
            if key in licensed:
                if state.status == STATUS_EXPIRED:
                    status = RECON_EXPIRED  # FR-015: el lifecycle manda sobre el conteo
                elif seats_used > token.max_seats:
                    status = RECON_OVER_SEAT
                else:
                    status = RECON_OK
                max_seats: Optional[int] = token.max_seats
            else:
                status = RECON_OVER_SEAT if seats_used > 0 else RECON_OK
                max_seats = None
            entry = TenantSeatStatus(status, seats_used, max_seats, now)
            fresh[key] = entry
            if entry.status != RECON_OK:
                logger.warning("reconciliación: tenant %s en %s (seats %s / max %s)",
                               key, entry.status, entry.seats_used, entry.max_seats)
            _emit_transition(db, tenant.id, _registry.get(key), entry)
            # Publicación INCREMENTAL (hardening post-review): el evento ya
            # quedó commiteado, así que el estado se publica ya — si la corrida
            # muere en el tenant siguiente, el reintento no re-emite esta
            # transición. Merge atómico (swap de referencia, sin locks).
            _registry = {**_registry, key: entry}
        # Swap final: descarta tenants que desaparecieron entre corridas.
        _registry = fresh
        return fresh
    finally:
        db.close()


def _interval_from_env() -> float:
    raw = os.getenv(INTERVAL_ENV, "")
    if not raw.strip():
        return DEFAULT_INTERVAL_SECONDS
    try:
        return float(raw)
    except ValueError:
        logger.warning("reconciliación: %s=%r inválido, uso el default %ss",
                       INTERVAL_ENV, raw, DEFAULT_INTERVAL_SECONDS)
        return DEFAULT_INTERVAL_SECONDS


def start_scheduler(interval_seconds: Optional[float] = None,
                    session_factory=None) -> Optional[threading.Thread]:
    """Job periódico en un thread daemon propio (T025): el backend no tenía
    scheduler, y un thread con ``Event.wait`` no bloquea el event loop ni suma
    dependencias. Corre al arrancar y luego cada ``interval_seconds``
    (env ``BASA_LICENSE_RECONCILE_INTERVAL_SECONDS``, default 300; ≤0 desactiva).
    """
    global _thread
    if interval_seconds is None:
        interval_seconds = _interval_from_env()
    if interval_seconds <= 0:
        logger.info("reconciliación: scheduler DESACTIVADO (%s<=0)", INTERVAL_ENV)
        return None
    if _thread is not None and _thread.is_alive():
        return _thread
    _stop.clear()

    def _loop():
        while not _stop.is_set():
            try:
                run_once(session_factory=session_factory)
            except Exception:  # noqa: BLE001 — el job jamás muere: la próxima corrida reintenta
                logger.exception("reconciliación: corrida fallida, reintento en %ss",
                                 interval_seconds)
            _stop.wait(interval_seconds)

    _thread = threading.Thread(target=_loop, name="basa-license-reconcile", daemon=True)
    _thread.start()
    logger.info("reconciliación: scheduler activo cada %ss (100%% local)", interval_seconds)
    return _thread


def stop_scheduler() -> None:
    global _thread
    _stop.set()
    if _thread is not None:
        _thread.join(timeout=5)
    _thread = None


def scheduler_running() -> bool:
    return _thread is not None and _thread.is_alive()


def reset_for_tests() -> None:
    global _registry, _clock_rollback
    stop_scheduler()
    _registry = {}
    _clock_rollback = False
