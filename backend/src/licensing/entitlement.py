"""Entitlement en memoria + estado de licencia (spec 021, US1; FR-003/005/006/018/026).

Al arranque el backend lee el token inyectado por la 020 (env/secret/fichero),
lo verifica OFFLINE (verifier.py) y mantiene el resultado como singleton en
memoria (el token crudo NUNCA se persiste). Fail-closed: cualquier defecto
(ausente/corrupto/firma/mismatch) deja el sistema en modo degradado — el gate
de creación (gate.py) bloquea seats nuevos — pero JAMÁS mata el proceso
(SC-013: expiry degrada, nunca mata; tampoco un token roto).
"""
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from ..models.tenant import DEFAULT_TENANT_ID
from .token import LicenseError, LicenseToken
from .verifier import (
    BasaPublicKeySet,
    LicenseTenantMismatchError,
    verify_license_blob,
)

logger = logging.getLogger(__name__)

# Estados de licencia (FR-018; over_seat lo aporta la reconciliación de US3).
STATUS_ACTIVE = "active"
STATUS_GRACE = "grace"
STATUS_EXPIRED = "expired"
STATUS_INVALID = "invalid"
STATUS_MISMATCH = "mismatch"
STATUS_MISSING = "missing"

# Único estado que permite CREAR seats (FR-006/FR-010/FR-019/FR-020: en grace,
# expired y degradados la creación se bloquea; el tráfico existente no se toca).
CREATION_ALLOWED_STATUSES = frozenset({STATUS_ACTIVE})

DEFAULT_KEYSET_PATH = Path(__file__).resolve().parent.parent / "keys" / "basa_public_keys.pem"

# Prefijo de los key_id DEV/DEMO (emitidos por scripts/issue_dev_license.py).
# La licencia dev y su pública son PÚBLICAS en el repo: sin este guard, el
# fail-closed quedaría neutralizado por configuración default en cualquier
# imagen que no excluya el kid dev. Sólo dev/demo (compose) setea el opt-in.
DEV_KID_PREFIX = "basa-dev-"


@dataclass(frozen=True)
class LicenseState:
    status: str
    reason: Optional[str]
    token: Optional[LicenseToken]  # cargado sólo si la firma validó (incl. grace/expired)
    checked_at: datetime


_state: Optional[LicenseState] = None


def expected_tenant_id() -> str:
    """Tenant del deployment (013/020): la 020 lo inyecta; default = tenant
    seed de la 013 para dev/demo de caja única."""
    return os.getenv("BASA_DEPLOYMENT_TENANT_ID", str(DEFAULT_TENANT_ID))


def _read_blob() -> Optional[str]:
    inline = os.getenv("BASA_LICENSE_TOKEN")
    if inline and inline.strip():
        return inline
    path = os.getenv("BASA_LICENSE_TOKEN_FILE")
    if path:
        try:
            return Path(path).read_text(encoding="utf-8")
        except OSError:
            logger.warning("licencia: BASA_LICENSE_TOKEN_FILE ilegible: %s", path)
            return None
    return None


def _load_keyset() -> BasaPublicKeySet:
    path = os.getenv("BASA_LICENSE_PUBLIC_KEYS_FILE", str(DEFAULT_KEYSET_PATH))
    return BasaPublicKeySet.from_pem_file(path)


def _lifecycle(token: LicenseToken, now: datetime):
    """`active → grace → expired` con reloj LOCAL (FR-018/FR-021, offline)."""
    if now < token.not_before:
        return STATUS_INVALID, "not_yet_valid: el token todavía no entró en vigencia"
    if now <= token.expiry:
        return STATUS_ACTIVE, None
    grace_limit = token.expiry + timedelta(days=token.grace_days)
    if now <= grace_limit:
        return STATUS_GRACE, f"expiry {token.expiry.date()} vencido, dentro de grace ({token.grace_days}d)"
    return STATUS_EXPIRED, f"expiry {token.expiry.date()} vencido más allá del grace"


def evaluate(now: Optional[datetime] = None) -> LicenseState:
    """Evaluación pura (sin side-effects): lee config, verifica, computa estado."""
    now = now or datetime.now(timezone.utc)
    blob = _read_blob()
    if blob is None:
        return LicenseState(STATUS_MISSING, "token ausente (BASA_LICENSE_TOKEN[_FILE])", None, now)
    try:
        keyset = _load_keyset()
    except (LicenseError, OSError) as exc:
        # Sin keyset no hay verificación posible → fail-closed, nunca fail-open.
        return LicenseState(STATUS_INVALID, f"keyset no disponible: {exc}", None, now)
    try:
        token = verify_license_blob(blob, keyset, expected_tenant_id=expected_tenant_id())
    except LicenseTenantMismatchError:
        reason = "tenant del token no coincide con el deployment"
        try:
            foreign = verify_license_blob(blob, keyset)  # sólo para el audit (metadata)
            reason = (f"token de tenant {foreign.tenant_id} "
                      f"(lic {foreign.license_id}), deployment {expected_tenant_id()}")
        except LicenseError:
            pass
        return LicenseState(STATUS_MISMATCH, reason, None, now)
    except LicenseError as exc:
        return LicenseState(STATUS_INVALID, str(exc), None, now)
    if (token.key_id.startswith(DEV_KID_PREFIX)
            and os.getenv("BASA_ALLOW_DEV_LICENSE", "").lower() != "true"):
        return LicenseState(
            STATUS_INVALID,
            f"licencia dev '{token.key_id}' no permitida en este deployment "
            "(falta el opt-in BASA_ALLOW_DEV_LICENSE=true, sólo para dev/demo)",
            None, now,
        )
    status, reason = _lifecycle(token, now)
    if status == STATUS_INVALID:
        return LicenseState(status, reason, None, now)
    return LicenseState(status, reason, token, now)


def initialize(force: bool = False, emit_audit: bool = True,
               session_factory=None, now: Optional[datetime] = None) -> LicenseState:
    """Gate de ARRANQUE (research §verificación): idempotente, jamás levanta.

    Cualquier excepción inesperada degrada a `invalid` (fail-closed) en vez de
    tumbar el proceso; la emisión del evento de audit es best-effort.
    """
    global _state
    if _state is not None and not force:
        return _state
    try:
        state = evaluate(now=now)
    except Exception as exc:  # noqa: BLE001 — el arranque nunca muere por licencia
        logger.exception("licencia: error inesperado evaluando el token")
        state = LicenseState(STATUS_INVALID, f"error interno: {exc}",
                             None, now or datetime.now(timezone.utc))
    _state = state
    if state.status == STATUS_ACTIVE:
        logger.info("licencia: entitlement cargado (tenant=%s max_seats=%s expiry=%s)",
                    state.token.tenant_id, state.token.max_seats, state.token.expiry.date())
    else:
        logger.warning("licencia: estado %s — creación de seats BLOQUEADA (%s)",
                       state.status, state.reason)
    if emit_audit:
        try:
            from .audit_events import emit_state_event
            emit_state_event(state, session_factory=session_factory)
        except Exception:  # noqa: BLE001 — audit best-effort, mismo criterio que AuditService
            logger.exception("licencia: no se pudo emitir el evento de audit de arranque")
    return state


def refresh(now: Optional[datetime] = None, session_factory=None) -> LicenseState:
    """Re-evaluación en RUNTIME (US4/T027, FR-018/FR-021): un proceso vivo debe
    transicionar ``active→grace→expired`` con el reloj LOCAL, sin reinicio. La
    llama el tick de la reconciliación (US3/T029). Audita SOLO transiciones de
    estado (FR-022) — idempotente si el estado no cambió. Fail-closed y jamás
    levanta, mismo criterio que initialize()."""
    global _state
    previous = _state
    try:
        state = evaluate(now=now)
    except Exception as exc:  # noqa: BLE001 — el tick nunca muere por licencia
        logger.exception("licencia: error inesperado re-evaluando el token")
        state = LicenseState(STATUS_INVALID, f"error interno: {exc}",
                             None, now or datetime.now(timezone.utc))
    _state = state
    if previous is None or previous.status == state.status:
        return state
    log = logger.info if state.status == STATUS_ACTIVE else logger.warning
    log("licencia: transición %s → %s (%s)", previous.status, state.status, state.reason)
    try:
        from .audit_events import emit_state_event
        emit_state_event(state, session_factory=session_factory)
    except Exception:  # noqa: BLE001 — audit best-effort
        logger.exception("licencia: no se pudo auditar la transición de estado")
    return state


def get_state() -> LicenseState:
    """Estado vigente; si nadie inicializó (p.ej. import parcial en tests),
    evalúa fail-closed en el momento en vez de asumir nada."""
    if _state is None:
        return initialize(emit_audit=False)
    return _state


def reset_for_tests() -> None:
    global _state
    _state = None
