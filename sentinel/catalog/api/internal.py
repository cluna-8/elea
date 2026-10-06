"""Canal interno pasarela ↔ motor: `GET /api/v1/internal/model-catalog` (069 T032; FR-008; D2).

El guard del motor lo consulta para resolver a los clientes que hablan DIRECTO con el motor (Hub,
tabular, presentaciones): `public_id → entrada`. **Nunca incluye credenciales**: la credencial viaja
en la autorización firmada o la resuelve el guard por `entry_id` con la clave interna.

Mismo patrón que `/internal/identity` de la base: solo por la red de compose (el ingress lo niega) y
con el secreto compartido que ya existe (`SENTINEL_ENGINE_MASTER_KEY`); sin él, el mismo 404.
Instantánea por organización con TTL corto + versión: un cambio se ve en segundos (FR-008, FR-014).
"""
from __future__ import annotations

import contextlib
import hashlib
import uuid
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, Query, Response

from src.api.internal import _require_internal_secret

from .. import models as cm
from .. import store as cs
from . import admin

router = APIRouter(prefix="/internal", tags=["Internal"], include_in_schema=False)

# Inyectables para tests.
SESSION_FACTORY = None
DPA_LOOKUP = None
TODAY = None
VERSION = None
DECRYPT = None

_caches: dict = {}


def _version():
    if VERSION is not None:
        return VERSION
    from ..runtime import catalog_version
    return catalog_version()


def _today() -> date:
    return TODAY() if TODAY is not None else datetime.now(timezone.utc).date()


@contextlib.contextmanager
def _session(tenant: uuid.UUID):
    from src.database import tenant_context
    factory = SESSION_FACTORY
    if factory is None:
        from src.database import SessionLocal as factory
    with tenant_context(tenant):
        db = factory()
        try:
            yield db
        finally:
            db.close()


def _serves(e: cm.CatalogEntry, cred) -> bool:
    """Se sirve lo activo y utilizable: con credencial vigente o que no la necesita."""
    if e.status != "active":
        return False
    from sentinel.redirect import credentials as rc
    return cred is not None and cred.status == "active" or not rc.requires_secret(e.provider)


def build(tenant: str) -> dict:
    tid = uuid.UUID(str(tenant))
    entries: dict = {}
    with _session(tid) as db:
        # las de instalación primero: la entrada propia con el mismo id público las reemplaza
        rows = sorted(cs.visible_entries(db, tid, operator=False), key=lambda e: e.tenant_id is not None)
        for e in rows:
            cred = cs.credential_of(db, e)
            if not _serves(e, cred):
                continue
            sheet = cs.sheet_of(db, e.id)
            dpa = _dpa(db, e, sheet)
            entries[e.public_id] = {
                "entry_id": str(e.id), "name": e.name, "provider": e.provider,
                "real_model": e.real_model, "api_base": e.api_base,
                "protocol_family": e.protocol_family, "level": e.level,
                "semaforo": cs.semaforo_of(e, sheet, dpa, _today()),
                "jurisdiccion": cs.sheet_view(sheet)["inference_jurisdiction"],
                "capability": e.capability, "features": dict(e.features or {}),
                "role": e.role, "limits": dict(e.limits or {}), "base_model": e.base_model,
                "unsupported_params": list(e.unsupported_params or []),
                "price": cs.entry_view(e, sheet, cred, dpa, _today(), owner=False)["price"],
            }
    return {"entries": entries}


def direct_enabled() -> bool:
    """Interruptor de instalación: ¿el motor sirve del catálogo a los clientes que le hablan directo
    (Hub, tabular, presentaciones)? Apagado por defecto: sin él nada cambia en el motor."""
    import os
    return os.environ.get("CATALOG_DIRECT_ENABLED", "").strip().lower() in ("1", "true", "yes")


def _require_direct_enabled() -> None:
    """Sin la ruta directa (`CATALOG_DIRECT_ENABLED`), la credencial **descifrada** no sale por HTTP: el mismo 404
    que sin secreto, aun con el secreto interno correcto (057 QA A10; FR-013). La llamada en proceso del chat de la
    consola (`chat_route`) invoca la función directamente y no pasa por esta dependencia."""
    from fastapi import HTTPException
    if not direct_enabled():
        raise HTTPException(404, "Not Found")


def _dpa(db, e, sheet):
    prev = (admin.DPA_LOOKUP, admin.TODAY)
    admin.DPA_LOOKUP = DPA_LOOKUP or admin.DPA_LOOKUP
    try:
        return admin._dpa(db, e, sheet)
    finally:
        admin.DPA_LOOKUP, admin.TODAY = prev


def _cache():
    ver = _version()
    c = _caches.get(id(ver))
    if c is None:
        from sentinel.common.snapshot_version import SnapshotCache
        c = _caches[id(ver)] = SnapshotCache(ver, build, ttl=5.0)
    return c


@router.get("/model-catalog", dependencies=[Depends(_require_internal_secret)])
def model_catalog(tenant: uuid.UUID = Query()):
    snap = _cache().get(str(tenant))
    token = hashlib.sha256(repr((str(tenant), _version().current(str(tenant)))).encode()).hexdigest()[:16]
    return {"version": token, "direct": direct_enabled(), **snap}


@router.get("/model-access", dependencies=[Depends(_require_internal_secret)])
def model_access(response: Response, tenant: uuid.UUID = Query(), user: str | None = Query(None),
                 group: str | None = Query(None), key: str | None = Query(None)):
    """Acceso por perfil de riesgo para quienes hablan DIRECTO con el motor (069 T153; US2): el guard
    pregunta «¿qué `public_id` puede usar esta identidad?» antes de servir una entrada del catálogo.
    Mismo resolutor y mismo riesgo efectivo que la pasarela y el chat (`sentinel.access.bridge`).
    `restringe=false` = ninguna política limita; si el resolutor falla, 503 (el guard no abre)."""
    from fastapi import HTTPException
    from sentinel.access import bridge
    response.headers["Cache-Control"] = "no-store"
    ident = {"tenant_id": str(tenant), "user_id": user, "group_id": group, "api_key_id": key}
    try:
        permitidos, _governed = bridge.allowed_for_ident(ident)
    except Exception:  # noqa: BLE001 — fail-closed: sin respuesta no se sirve por omisión
        raise HTTPException(503, "Service Unavailable") from None
    if permitidos is None:
        return {"restringe": False, "permitidos": []}
    return {"restringe": True, "permitidos": sorted(permitidos)}


@router.get("/model-credential", dependencies=[Depends(_require_internal_secret), Depends(_require_direct_enabled)])
def model_credential(response: Response, tenant: uuid.UUID = Query(), entry_id: uuid.UUID = Query()):
    """Credencial descifrada de UNA entrada servida, solo para el guard del motor (red interna + secreto
    compartido), y **solo con la ruta directa encendida** (`CATALOG_DIRECT_ENABLED`; apagada en Eleia, donde la
    credencial viaja en la autorización firmada). Nunca cacheable. Las referencias a variables del servidor viajan
    como referencia (`env:…`): solo las resuelve el motor."""
    from fastapi import HTTPException
    from .. import credentials as cr
    response.headers["Cache-Control"] = "no-store"
    with _session(tenant) as db:
        e = next((x for x in cs.visible_entries(db, tenant, operator=False) if x.id == entry_id), None)
        cred = cs.credential_of(db, e) if e is not None else None
        if e is None or not _serves(e, cred):
            raise HTTPException(404, "Not Found")
        if cred is None:
            return {"credential": {}}
        return {"credential": cr.resolve(cred, DECRYPT or _decrypt_default)}


def _decrypt_default(blob: str) -> str:
    from src.services import encryption_service
    return encryption_service.descifrar_estricto(blob)


def semaforo_for(tenant: str, model_name: str):
    """Resolutor del semáforo para la residencia de proyectos de la base (069 T034): el semáforo de la
    entrada cuyo id público es `model_name` para esa organización, o `None` si el catálogo no la conoce.
    Misma función y misma instantánea que la API y el canal interno (FR-003a)."""
    entry = (_cache().get(str(tenant)).get("entries") or {}).get(model_name)
    return entry["semaforo"] if entry else None
