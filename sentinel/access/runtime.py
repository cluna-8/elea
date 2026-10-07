"""Plano de datos de los perfiles de acceso: instantánea cacheada y fachada para los demás planos
(069 T048; D6). Los planos (`/gw`, motor, chat, 068) llaman SOLO a `allowed_public_ids`."""
from __future__ import annotations

import contextlib
import logging
import uuid
from typing import Optional

from sentinel.common.snapshot_version import SnapshotCache, SnapshotVersion

from . import snapshot as snap
from .resolver import AccessSnapshot, Permitidos, PermitidosNoResueltos, modelos_permitidos

__all__ = ["PermitidosNoResueltos", "allowed_public_ids", "effective_risk", "resolve"]

# Inyectables para tests.
SESSION_FACTORY = None
ENTRIES = None            # callable(tenant) -> lista de vistas de entradas; por defecto, el catálogo
VERSION = None

_version: Optional[SnapshotVersion] = None
_cache: Optional[SnapshotCache] = None


def access_version() -> SnapshotVersion:
    """Contador `ext:access:v:<organización>`; lo sube `bump` en cada escritura de la API."""
    global _version
    if VERSION is not None:
        return VERSION
    if _version is None:
        _version = SnapshotVersion("access")
    return _version


def bump(tenant_id) -> None:
    try:
        access_version().bump(str(tenant_id))
    except Exception:  # noqa: BLE001 — la caché corta vence sola (TTL)
        pass


@contextlib.contextmanager
def session(tenant_id):
    from src.database import tenant_context
    factory = SESSION_FACTORY
    if factory is None:
        from src.database import SessionLocal as factory
    with tenant_context(uuid.UUID(str(tenant_id))):
        db = factory()
        try:
            yield db
        finally:
            db.close()


def _missing_table(exc: Exception) -> bool:
    text = str(getattr(exc, "orig", exc)).lower()
    return "ext_access" in text or "ext_ai_act" in text and (
        "does not exist" in text or "no such table" in text or "undefinedtable" in text)


def _load(tenant_id: str):
    """Sin las tablas de acceso (migración sin aplicar) no hay política: la instalación sigue como antes
    en vez de dejar al chat y a la pasarela sin modelos. Cualquier otra falla sí es fail-closed."""
    try:
        with session(tenant_id) as db:
            return snap.load(db, tenant_id)
    except Exception as exc:  # noqa: BLE001
        if _missing_table(exc):
            logging.getLogger("sentinel.access").warning(
                "acceso: tablas ext_access_* ausentes (¿migración sin aplicar?); sin política")
            return AccessSnapshot(tenant_id=str(tenant_id))
        raise


def _snapshot_cache() -> SnapshotCache:
    global _cache
    ver = access_version()
    if _cache is None or _cache.version is not ver:
        _cache = SnapshotCache(ver, _load, ttl=5.0)
    return _cache


def get_snapshot(tenant_id):
    return _snapshot_cache().get(str(tenant_id))


def catalog_entries(tenant_id) -> list:
    """Vistas de las entradas servibles del catálogo (mismo semáforo que la API, FR-003a)."""
    if ENTRIES is not None:
        return list(ENTRIES(str(tenant_id)))
    from sentinel.catalog.api import internal
    built = internal._cache().get(str(tenant_id)).get("entries") or {}
    return [{"id": v["entry_id"], "public_id": pid, "name": v["name"], "provider": v["provider"],
             "capability": v["capability"], "semaforo": v["semaforo"],
             "jurisdiccion": v["jurisdiccion"]} for pid, v in built.items()]


def resolve(tenant_id, *, user_id=None, group_id=None, key_id=None, user_risk=None,
            key_risk=None) -> Permitidos:
    """Resolución completa; cualquier falla (datos, base, catálogo) ⇒ `PermitidosNoResueltos`."""
    try:
        return modelos_permitidos(get_snapshot(tenant_id), catalog_entries(tenant_id),
                                  user_id=user_id, group_id=group_id, key_id=key_id,
                                  user_risk=user_risk, key_risk=key_risk)
    except PermitidosNoResueltos:
        raise
    except Exception as e:  # noqa: BLE001
        raise PermitidosNoResueltos(f"no se pudo resolver el acceso: {type(e).__name__}") from e


def allowed_public_ids(tenant_id: str, *, user_id: Optional[str] = None, group_id: Optional[str] = None,
                       key_id: Optional[str] = None, user_risk: Optional[str] = None,
                       key_risk: Optional[str] = None) -> Optional[frozenset]:
    """`None` = sin política que restrinja (todo lo del catálogo está permitido); si no, el conjunto de
    `public_id` permitidos. Levanta `PermitidosNoResueltos` si no se puede decidir."""
    r = resolve(tenant_id, user_id=user_id, group_id=group_id, key_id=key_id, user_risk=user_risk,
                key_risk=key_risk)
    return r.ids if r.restringe else None


def _get(db, model, ident):
    if ident is None or not isinstance(ident, (str, uuid.UUID)):
        return ident                       # ya es un objeto (o None)
    return db.get(model, uuid.UUID(str(ident)))


def effective_risk(db, *, key=None, user=None, group=None, tenant=None):
    """→ `(user_risk, key_risk)` SIN modificar la base. `user_risk` = cascada usuario → grupo →
    organización (`users.risk_level`, `groups.default_risk_level` —el grupo del USUARIO si no se pasó
    uno—, `tenants.default_risk_level`); `key_risk` = la clasificación propia de la llave (hoy la base
    no la guarda: `None`). Acepta ids u objetos ORM; el resolutor toma el más estricto de los dos."""
    from src.models.tenant import Tenant
    from src.models.user import Group, User
    u = _get(db, User, user)
    g = _get(db, Group, group if group is not None else getattr(u, "group_id", None))
    t = _get(db, Tenant, tenant)
    user_risk = ((getattr(u, "risk_level", None) if u else None)
                 or (getattr(g, "default_risk_level", None) if g else None)
                 or (getattr(t, "default_risk_level", None) if t else None))
    return user_risk, getattr(key, "risk_level", None) if key is not None else None
