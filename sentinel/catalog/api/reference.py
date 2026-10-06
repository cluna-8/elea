"""Rutas de `/api/v1/catalog` — referencia del motor y alta múltiple (069 T125; contracts/admin-modelos.md).

Alta guiada de la pantalla única «Modelos» (US8): el servidor lee las listas del motor (la consola
nunca le habla, FR-057) y las ofrece como **sugerencias**; el alta múltiple crea varias entradas con una
misma credencial reusando EXACTAMENTE la lógica de `POST /entries` (`admin._create_one`).

- `GET  /providers`                  proveedores soportados y no soportados (con motivo) + campos de credencial
- `GET  /providers/{p}/models`       modelos del proveedor con precio, contexto, capacidades y tipo
- `POST /reference/refresh`          «Actualizar precios» (solo admin)
- `POST /entries/bulk`               alta de varios modelos (solo admin); 207 con el resultado por modelo

Motor caído ⇒ `available: false` (nunca error): el alta manual sigue funcionando (SC-014).
Una sugerencia nunca pisa un valor que el cuerpo traiga explícito.
"""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import Field

from src.auth.rbac import require_role

from .. import models as cm
from .. import reference as ref
from . import admin
from .admin import ADMIN, READERS, EntryIn, _Body

router = APIRouter(prefix="/catalog", tags=["catalog"])

REFERENCE: Optional[ref.Reference] = None          # inyectable para tests
MAX_BULK = 200
_PROTOCOL = {"anthropic": "anthropic_messages", "openai": "openai_responses"}


def _ref() -> ref.Reference:
    return REFERENCE if REFERENCE is not None else ref.default()


@router.get("/providers")
def list_providers(user=Depends(require_role(*READERS))):
    return _ref().providers()


@router.get("/providers/{provider}/models")
def provider_models(provider: str, q: str = "", limit: int = Query(50, ge=1, le=200),
                    offset: int = Query(0, ge=0), user=Depends(require_role(*READERS))):
    if provider not in cm.PROVIDERS:
        raise HTTPException(404, "proveedor inexistente")
    return _ref().models(provider, q=q, limit=limit, offset=offset)


@router.post("/reference/refresh")
def refresh_reference(user=Depends(require_role(*ADMIN))):
    r = _ref()
    r.refresh()
    out = r.providers()
    return {k: v for k, v in out.items() if k != "data"}


# ── alta múltiple ─────────────────────────────────────────────────────────────

class BulkModel(_Body):
    real_model: str = Field(min_length=1, max_length=256)
    name: Optional[str] = Field(default=None, min_length=1, max_length=128)
    public_id: Optional[str] = Field(default=None, max_length=128)
    accept_suggestion: bool = False
    # valores explícitos: ganan siempre sobre la sugerencia del motor
    role: Optional[str] = None
    capability: Optional[str] = None
    context_window: Optional[int] = Field(default=None, ge=1)
    max_output: Optional[int] = Field(default=None, ge=1)
    price_input: Optional[float] = Field(default=None, ge=0)
    price_output: Optional[float] = Field(default=None, ge=0)
    price_cache_read: Optional[float] = Field(default=None, ge=0)
    price_cache_write: Optional[float] = Field(default=None, ge=0)
    features: Optional[dict] = None
    limits: Optional[dict] = None
    advanced: Optional[dict] = None
    base_model: Optional[str] = Field(default=None, max_length=256)


class BulkIn(_Body):
    provider: str
    level: str = "tenant"
    credential: Optional[dict] = None
    api_base: Optional[str] = Field(default=None, max_length=512)
    protocol_family: Optional[str] = None            # por defecto, la del proveedor
    models: List[BulkModel] = Field(min_length=1, max_length=MAX_BULK)


_SUGGESTED = ("context_window", "max_output")
_PRICES = (("price_input", "input"), ("price_output", "output"),
           ("price_cache_read", "cache_read"), ("price_cache_write", "cache_write"))


def _entry_body(bulk: BulkIn, m: BulkModel, suggestion: Optional[dict]) -> EntryIn:
    """El `EntryIn` de un modelo: lo explícito, completado con la sugerencia si se aceptó."""
    fields: dict = {k: v for k, v in m.model_dump(exclude_unset=True).items()
                    if k not in ("real_model", "name", "public_id", "accept_suggestion") and v is not None}
    suggested_price = False
    if suggestion is not None:
        for k in _SUGGESTED:
            if fields.get(k) is None and suggestion.get(k) is not None:
                fields[k] = suggestion[k]
        for k, sk in _PRICES:
            if fields.get(k) is None and suggestion["price"].get(sk) is not None:
                fields[k], suggested_price = suggestion["price"][sk], True
        fields["features"] = {**suggestion.get("features", {}), **(m.features or {})}
        fields.setdefault("role", suggestion["role"])
    return EntryIn(
        level=bulk.level, name=m.name or m.real_model, public_id=m.public_id, provider=bulk.provider,
        real_model=m.real_model, protocol_family=bulk.protocol_family or _PROTOCOL.get(bulk.provider, "openai_chat"),
        api_base=bulk.api_base, price_source=ref.SOURCE if suggested_price else None, **fields)


@router.post("/entries/bulk")
def create_entries_bulk(body: BulkIn, user=Depends(require_role(*ADMIN))):
    admin._check_vocab(body.provider, body.protocol_family, None, None, None, body.level)
    admin._check_create_authority(user, EntryIn(
        level=body.level, name="x", provider=body.provider, real_model="x",
        protocol_family="openai_chat", credential=body.credential))
    installation = body.level == "installation"
    tenant = None if installation else user.tenant_id
    # Validación previa de TODA la pedida (credencial con la forma del proveedor, base): nada se guarda.
    with admin._db(user, bypass=installation) as db:
        cred = admin._new_credential(db, user, body.credential, level=body.level) if body.credential else None
        admin._check_binding(body.provider, body.level, cred, body.api_base)
        db.rollback()
    # La credencial se crea con el primer modelo que se guarda y los demás la reutilizan; si ese modelo
    # falla, su transacción se deshace y no queda una credencial huérfana.
    shared = {"id": body.credential["id"] if body.credential and "id" in body.credential else None}
    pending: dict = {}

    def cred_of(d):
        if body.credential is None:
            return None
        if shared["id"]:
            return admin._credential_row(d, user, shared["id"], level=body.level)
        row = admin._new_credential(d, user, body.credential, level=body.level)
        pending["id"] = row.id
        return row

    results, created = [], 0
    for m in body.models:
        out = {"real_model": m.real_model}
        try:
            suggestion = None
            if m.accept_suggestion:
                suggestion = _ref().model(body.provider, m.real_model)
                if suggestion is None:
                    raise HTTPException(422, "no hay referencia del motor para este modelo: cargarlo a mano")
            entry = _entry_body(body, m, suggestion)
            with admin._db(user, bypass=installation) as db:
                view = admin._create_one(db, user, entry, cred_of)
            if pending:
                shared["id"] = pending.pop("id")
            out |= {"status": 201, "entry": view}
            created += 1
        except HTTPException as exc:
            pending.clear()
            out |= {"status": exc.status_code, "error": str(exc.detail)}
        results.append(out)
    if created:
        admin._bump_for(tenant)
    return JSONResponse({"created": created, "failed": len(results) - created, "data": results},
                        status_code=207)
