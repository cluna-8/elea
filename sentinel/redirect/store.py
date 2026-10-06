"""Carga de la política desde la base + caché corta (research D11; T030/T048/T050).

`RedirectStore.snapshot(tenant_id)` devuelve las filas que el resolver puro necesita, ya como
dicts planos con ids en texto. Se cachea por tenant con TTL corto (`REDIRECT_CACHE_TTL_S`,
default 5 s ⇒ propagación muy por debajo de los 60 s de SC-009) y una **versión**: cada
escritura de la API de administración llama `bump(tenant)` (o `bump(None)` para cambios de
nivel instalación), que invalida la caché local al instante y, si hay Redis, sube un contador
compartido que los demás procesos comparan en cada lectura.

Las credenciales NO entran al snapshot en claro: se guarda el blob cifrado aparte y se
descifra solo para el destino elegido de cada pedido (`credential`).

Fallas:
- tablas inexistentes (migración no aplicada) ⇒ snapshot vacío = política apagada, con log:
  instalar el plugin sin migrar no puede tumbar el tráfico;
- cualquier otra falla ⇒ `StoreUnavailable`; el plugin decide (fail-closed con política on,
  FR-004a, usando el último snapshot conocido para saber si lo estaba).
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

logger = logging.getLogger("sentinel.redirect.store")

DEFAULT_TTL = 5.0
_VERSION_KEY = "sentinel:redirect:v:{}"
_GLOBAL = "*"


class StoreUnavailable(RuntimeError):
    """No se pudo leer la política (no es «no hay filas»)."""


@dataclass(frozen=True)
class Snapshot:
    policy: tuple = ()
    postures: tuple = ()
    published: tuple = ()
    rules: tuple = ()
    destinations: dict = field(default_factory=dict)   # id → dict (sin credencial)
    offers: tuple = ()
    credentials: dict = field(default_factory=dict, repr=False)  # id → blob cifrado

    def empty(self) -> bool:
        return not (self.policy or self.postures)


EMPTY = Snapshot()


def _s(v) -> Optional[str]:
    return None if v is None else str(v)


def _iso(v) -> Optional[str]:
    return v.isoformat() if hasattr(v, "isoformat") else _s(v)


def destination_dict(d) -> dict:
    """Fila de destino → dict del resolver/admin (NUNCA con la credencial)."""
    return {
        "id": _s(d.id), "level": d.level, "tenant_id": _s(d.tenant_id), "name": d.name,
        "provider": d.provider, "real_model": d.real_model, "protocol_family": d.protocol_family,
        "inference_jurisdiction": d.inference_jurisdiction,
        "entity_jurisdiction": d.entity_jurisdiction,
        "blocked_by_default": bool(d.blocked_by_default), "enabled_at": _iso(d.enabled_at),
        "enable_reason": d.enable_reason, "has_credential": bool(d.credential_encrypted),
        "api_base": d.api_base, "provider_options": dict(d.provider_options or {}),
        "capability_profile": dict(d.capability_profile or {}),
        "context_window": d.context_window, "max_output": d.max_output,
        "price_override": d.price_override, "status": d.status,
    }


def _scoped(r, **extra) -> dict:
    out = {"id": _s(r.id), "tenant_id": _s(r.tenant_id), "scope_type": r.scope_type,
           "scope_value": r.scope_value}
    out.update(extra)
    return out


def load_from_session(db, tenant_id: str, *, always: bool = False) -> Snapshot:
    """Lectura pura de la sesión (ya scopeada al tenant por el llamador).

    `always=False` (plano de datos): sin filas de política ni de postura devuelve `EMPTY` tras
    2 lecturas — el camino caliente del «apagado». Las pantallas de administración que
    muestran la configuración aunque la política esté apagada (kits, fidelidad, costos) piden
    `always=True`."""
    from . import models as m
    tid = uuid.UUID(str(tenant_id))
    policy = tuple(_scoped(r, state=r.state) for r in
                   db.query(m.RedirectPolicy).filter(m.RedirectPolicy.tenant_id == tid))
    postures = tuple(_scoped(r, mode=r.mode, jurisdictions=list(r.jurisdictions or []),
                             accept_foreign_entity=bool(r.accept_foreign_entity))
                     for r in db.query(m.RedirectPosture).filter(m.RedirectPosture.tenant_id == tid))
    if not (policy or postures) and not always:
        return EMPTY          # camino caliente del «apagado»: 2 lecturas y nada más
    published = tuple(_scoped(r, face=r.face, public_id=r.public_id, family_tier=r.family_tier,
                              is_family_default=bool(r.is_family_default), label=r.label,
                              label_mode=r.label_mode, reference_model=r.reference_model,
                              created_at=_iso(r.created_at))
                      for r in db.query(m.RedirectPublishedModel)
                      .filter(m.RedirectPublishedModel.tenant_id == tid))
    rules = tuple(_scoped(r, published_model_id=_s(r.published_model_id), family_tier=r.family_tier,
                          request_class=r.request_class, targets=[str(t) for t in (r.targets or [])],
                          strategy=getattr(r, "strategy", None) or "order")
                  for r in db.query(m.RedirectRule).filter(m.RedirectRule.tenant_id == tid))
    offers = tuple({"destination_id": _s(o.destination_id),
                    "tenant_id": _s(o.tenant_id) if o.tenant_id else "*",
                    "enabled_at": _iso(o.enabled_at)}
                   for o in db.query(m.RedirectOffer).filter(
                       (m.RedirectOffer.tenant_id == tid) | (m.RedirectOffer.tenant_id.is_(None))))
    offered = {o["destination_id"] for o in offers}
    dests, creds = {}, {}
    for d in db.query(m.RedirectDestination).filter(
            (m.RedirectDestination.tenant_id == tid) | (m.RedirectDestination.tenant_id.is_(None))):
        if d.tenant_id is None and str(d.id) not in offered:
            continue          # defensa en profundidad además de la RLS
        dests[str(d.id)] = destination_dict(d)
        if d.credential_encrypted:
            creds[str(d.id)] = d.credential_encrypted
    dests, offers, creds = _overlay_catalog(db, tid, dests, offers, creds)
    return Snapshot(policy=policy, postures=postures, published=published, rules=rules,
                    destinations=dests, offers=offers, credentials=creds)


def _overlay_catalog(db, tid, dests, offers, creds):
    """El catálogo único es la ÚNICA fuente de los destinos (069 FR-001, E3): una entrada es un destino con
    su mismo id, y sus ofertas son las ofertas. Una fila de la tabla propia de la 068 sin entrada de catálogo
    no se sirve (destino no disponible: la regla que la nombra lo reporta). La tabla solo rige como respaldo
    cuando las tablas del catálogo no existen (migración sin aplicar o imagen sin el paquete)."""
    try:
        from sentinel.catalog.store import catalog_destinations
        c_dests, c_offers, c_creds = catalog_destinations(db, tid)
    except ImportError:                 # imagen sin el paquete del catálogo: la 068 sigue sola
        return dests, offers, creds
    except Exception as exc:  # noqa: BLE001
        if "ext_" in str(getattr(exc, "orig", exc)).lower():
            return dests, offers, creds
        raise
    return c_dests, tuple(c_offers), c_creds


def _missing_table(exc: Exception) -> bool:
    text = str(getattr(exc, "orig", exc)).lower()
    return ("sentinel_redirect_" in text or "ext_catalog" in text) and ("does not exist" in text or "no such table" in text
                                              or "undefinedtable" in text)


def _default_loader(tenant_id: str) -> Snapshot:
    from src.database import SessionLocal, tenant_context
    with tenant_context(uuid.UUID(str(tenant_id))):
        db = SessionLocal()
        try:
            return load_from_session(db, tenant_id)
        finally:
            db.close()


def models_de_la_llave(tool_type, allowed):
    """Allowlist efectiva de una llave. Las de servicio (`svc.*`, tool_type «servicio») no llevan
    la propia: toman el catálogo y el acceso por perfil (069, T186); un `allowed_models` fijo de
    antes del catálogo único las dejaba sin ningún modelo servible."""
    if tool_type == "servicio":
        return None
    return list(allowed) if isinstance(allowed, list) else None


def _default_key_models(api_key_id: str):
    from src.database import SessionLocal
    from src.models.budget import APIKey
    db = SessionLocal()
    try:
        key = db.query(APIKey).filter(APIKey.id == uuid.UUID(str(api_key_id))).first()
        if not key:
            return None
        return models_de_la_llave(getattr(key, "tool_type", None), getattr(key, "allowed_models", None))
    finally:
        db.close()


def _default_redis():
    try:
        from src.services.redis_client import get_redis
        return get_redis()
    except Exception:  # noqa: BLE001
        return None


def decrypt_credential(blob: Optional[str]) -> dict:
    if not blob:
        return {}
    from src.services import encryption_service
    if blob.startswith("env_ref:"):        # referencia a variable del servidor (solo la resuelve el motor)
        from sentinel.catalog.credentials import env_ref_dict
        return env_ref_dict(blob[len("env_ref:"):])
    raw = encryption_service.decrypt(blob)
    if raw is None:
        raise StoreUnavailable("credencial de destino ilegible")
    return json.loads(raw)


def encrypt_credential(cred: dict) -> str:
    from src.services import encryption_service
    blob = encryption_service.encrypt(json.dumps(cred, sort_keys=True))
    if not blob:
        raise StoreUnavailable("cifrado no disponible (clave de cifrado del backend ausente)")
    return blob


class RedirectStore:
    def __init__(self, loader: Callable[[str], Snapshot] = None, *, ttl: Optional[float] = None,
                 key_models: Callable[[str], Any] = None, redis_factory: Callable[[], Any] = None,
                 decrypt: Callable[[Optional[str]], dict] = None,
                 clock: Callable[[], float] = time.monotonic):
        self._loader = loader or _default_loader
        self._key_models = key_models or _default_key_models
        self._redis_factory = redis_factory if redis_factory is not None else _default_redis
        self._decrypt = decrypt or decrypt_credential
        self._clock = clock
        self.ttl = float(os.getenv("REDIRECT_CACHE_TTL_S", DEFAULT_TTL) if ttl is None else ttl)
        self._cache: dict = {}        # tenant → (expira, versión, snapshot)
        self._last: dict = {}         # tenant → último snapshot bueno (para fail-closed)
        self._keys: dict = {}         # api_key_id → (expira, modelos)
        self._local_version = 0
        self._lock = threading.Lock()

    # ── versión ─────────────────────────────────────────────────────────────
    def _version(self, tenant_id: str):
        r = self._redis_factory() if self._redis_factory else None
        if r is None:
            return self._local_version
        try:
            vals = r.mget(_VERSION_KEY.format(tenant_id), _VERSION_KEY.format(_GLOBAL))
            return (self._local_version, tuple(vals))
        except Exception:  # noqa: BLE001 — sin Redis rige el TTL
            return self._local_version

    def bump(self, tenant_id: Optional[str] = None) -> None:
        with self._lock:
            self._local_version += 1
            if tenant_id is None:
                self._cache.clear()
            else:
                self._cache.pop(str(tenant_id), None)
        r = self._redis_factory() if self._redis_factory else None
        if r is not None:
            try:
                r.incr(_VERSION_KEY.format(tenant_id if tenant_id is not None else _GLOBAL))
            except Exception:  # noqa: BLE001
                logger.warning("redirect: no se pudo publicar la versión en Redis; rige el TTL")

    # ── lecturas ────────────────────────────────────────────────────────────
    def last_known(self, tenant_id: str) -> Optional[Snapshot]:
        return self._last.get(str(tenant_id))

    def snapshot(self, tenant_id: str) -> Snapshot:
        tenant_id = str(tenant_id)
        now = self._clock()
        version = self._version(tenant_id)
        hit = self._cache.get(tenant_id)
        if hit and hit[0] > now and hit[1] == version:
            return hit[2]
        try:
            snap = self._loader(tenant_id)
        except Exception as exc:  # noqa: BLE001
            if _missing_table(exc):
                logger.warning("redirect: tablas sentinel_redirect_* ausentes (¿migración sin "
                               "aplicar?); política apagada")
                snap = EMPTY
            else:
                raise StoreUnavailable(str(exc)) from exc
        with self._lock:
            self._cache[tenant_id] = (now + self.ttl, version, snap)
            self._last[tenant_id] = snap
        return snap

    def credential(self, snap: Snapshot, destination_id: str) -> dict:
        return self._decrypt(snap.credentials.get(str(destination_id)))

    def key_allowed_models(self, api_key_id: Optional[str]):
        if not api_key_id:
            return None
        now = self._clock()
        hit = self._keys.get(api_key_id)
        if hit and hit[0] > now:
            return hit[1]
        models = self._key_models(api_key_id)
        self._keys[api_key_id] = (now + self.ttl, models)
        return models


_default_store: Optional[RedirectStore] = None


def default_store() -> RedirectStore:
    global _default_store
    if _default_store is None:
        _default_store = RedirectStore()
    return _default_store
