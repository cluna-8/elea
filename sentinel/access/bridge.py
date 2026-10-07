"""Puente de los planos de la pasarela y del chat hacia el resolutor de permitidos (069 US2; D6).

Dos preguntas: «¿qué `public_id` del catálogo puede usar esta identidad?» (`allowed_for_ident`) y
«¿cuáles son todos los que el catálogo gobierna?» (`governed`). Un modelo que el catálogo NO conoce
(p. ej. uno heredado del archivo de configuración del motor) no está en `governed` y no se gobierna:
es el límite documentado de esta fase.

Sin `register_hooks()` ni resolutor inyectado el puente está INACTIVO: devuelve «sin política» y no
toca la base (mismo criterio que las costuras de la base: sin extensión, nada cambia). Si el
resolutor FALLA, levanta: el llamador responde 503 fail-closed, nunca abre.

Inyectables para tests: `RESOLVER`, `RISK`, `CATALOG`, `CLOCK`.
"""
from __future__ import annotations

import logging
import time
from typing import Optional

logger = logging.getLogger("sentinel.access.bridge")

RESOLVER = None      # fn(tenant_id, *, user_id, group_id, key_id, user_risk, key_risk) -> frozenset | None
RISK = None          # fn(ident) -> (user_risk, key_risk)
CATALOG = None       # fn(tenant_id) -> {public_id: entrada}
CLOCK = time.monotonic
RISK_TTL = 30.0      # el riesgo de una identidad cambia poco; los permitidos se leen frescos (FR-014)

_registered = False
_risk_cache: dict = {}


def active() -> bool:
    return _registered or RESOLVER is not None


def _resolver():
    if RESOLVER is not None:
        return RESOLVER
    from sentinel.access import runtime
    return runtime.allowed_public_ids


def _catalog(tenant_id: str) -> dict:
    if CATALOG is not None:
        return CATALOG(tenant_id)
    from sentinel.catalog.api import internal
    return internal._cache().get(str(tenant_id)).get("entries") or {}


def _risk_from_db(ident: dict):
    import uuid
    from src.database import SessionLocal, tenant_context
    from src.models.budget import APIKey
    from src.models.tenant import Tenant
    from src.models.user import Group, User
    from sentinel.access import runtime
    tid = uuid.UUID(str(ident["tenant_id"]))
    with tenant_context(tid):
        db = SessionLocal()
        try:
            key = db.query(APIKey).filter(APIKey.id == ident["api_key_id"]).first() if ident.get("api_key_id") else None
            user = db.query(User).filter(User.id == ident["user_id"]).first() if ident.get("user_id") else None
            group_id = ident.get("group_id") or (user.group_id if user is not None else None)
            group = db.query(Group).filter(Group.id == group_id).first() if group_id else None
            tenant = db.query(Tenant).filter(Tenant.id == tid).first()
            return runtime.effective_risk(db, key=key, user=user, group=group, tenant=tenant)
        finally:
            db.close()


def _risk(ident: dict):
    if RISK is not None:
        return RISK(ident)
    key = (str(ident.get("tenant_id")), str(ident.get("user_id")), str(ident.get("group_id")),
           str(ident.get("api_key_id")))
    now = CLOCK()
    hit = _risk_cache.get(key)
    if hit is not None and now - hit[0] < RISK_TTL:
        return hit[1]
    value = _risk_from_db(ident)
    _risk_cache[key] = (now, value)
    return value


def allowed_for_ident(ident: dict) -> tuple:
    """→ `(permitidos | None, governed)`. `None` = ninguna política restringe (y `governed` va vacío:
    no hace falta armarlo). Levanta si no se pudo resolver (fail-closed, FR-014a)."""
    if not active() or not ident or not ident.get("tenant_id"):
        return None, frozenset()
    tenant = str(ident["tenant_id"])
    user_risk, key_risk = _risk(ident)
    permitidos = _resolver()(tenant, user_id=ident.get("user_id"), group_id=ident.get("group_id"),
                             key_id=ident.get("api_key_id"), user_risk=user_risk, key_risk=key_risk)
    if permitidos is None:
        return None, frozenset()
    return frozenset(permitidos), frozenset(_catalog(tenant))


def _chat_checker(tenant_id, user, group, api_key_obj, model: str) -> None:
    """Verificador del chat de la consola (`src.services.access_hook`)."""
    from src.services import access_hook
    def _s(v):
        return str(v) if v is not None else None
    ident = {"tenant_id": _s(tenant_id or getattr(api_key_obj, "tenant_id", None)),
             "user_id": _s(getattr(user, "id", None) or getattr(api_key_obj, "user_id", None)),
             "group_id": _s(getattr(group, "id", None)),
             "api_key_id": _s(getattr(api_key_obj, "id", None))}
    permitidos, governed = allowed_for_ident(ident)
    if permitidos is not None and model in governed and model not in permitidos:
        raise access_hook.AccessDenied("profile_not_allowed")


def register_hooks() -> None:
    """Activa el puente y registra el verificador del chat de la consola. Idempotente."""
    global _registered
    _registered = True
    from src.services import access_hook
    access_hook.register_access_checker(_chat_checker)


def reset() -> None:
    """Desactiva el puente y suelta el verificador del chat (tests: el registro es estado global)."""
    global _registered
    _registered = False
    _risk_cache.clear()
    try:
        from src.services import access_hook
        access_hook.register_access_checker(None)
    except ImportError:
        pass
