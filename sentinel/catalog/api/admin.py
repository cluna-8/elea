"""API de administración `/api/v1/catalog/*` (contracts/admin-catalogo.md; 069 T028).

Catálogo único en dos niveles (FR-001a): entradas de **instalación** (las carga el operador y las
ofrece por nombre) y de **organización** (las carga su administrador con su propia credencial).
Reglas transversales, las mismas que la API de la 068:
- sesión de usuario con `require_role` del backend (las llaves virtuales no entran);
- el tenant es SIEMPRE el de la sesión; la sesión de base se abre con `tenant_context` (RLS), y con
  bypass solo para operaciones de nivel instalación;
- las credenciales son **solo escritura**: ni la respuesta, ni el registro de cambios, ni los
  exportes las llevan (solo la huella);
- el **semáforo es derivado** y no se puede escribir: los cuerpos rechazan campos desconocidos;
- toda escritura deja fila en el registro de cambios (hoy `sentinel_redirect_config_audit`; la
  tabla `config_changes` de la base la reemplaza en T039) y sube la versión de la caché del plano
  de datos: el motor ve el cambio en segundos, sin reinicio (SC-001).
"""
from __future__ import annotations

import contextlib
import uuid
from datetime import date, datetime, timezone
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from src.auth.rbac import effective_roles, require_role

from sentinel.redirect import credentials as rc
from sentinel.redirect import models as rm
from sentinel.redirect.api.admin import _is_super  # autoridad de instalación (operador)

from .. import credentials as cr
from .. import habilitacion as hb
from .. import models as cm
from .. import region as cregion
from .. import relaxation as crelax
from .. import store as cs
from .. import validation as cv

router = APIRouter(prefix="/catalog", tags=["catalog"])

ADMIN = ("admin",)                                  # tenant_admin y super_admin (alias de la base)
READERS = ("admin", "compliance_officer", "lectura")
SHEET_WRITERS = ("admin", "compliance_officer")

# Inyectables para tests (sin Postgres): sesiones, cifrado, caché del plano de datos, DPA y reloj.
SESSION_FACTORY = None
ENCRYPT = None
DECRYPT = None
STORE = None
DPA_LOOKUP = None
DPA_LIST = None
TODAY = None


def _session_factory():
    if SESSION_FACTORY is not None:
        return SESSION_FACTORY
    from src.database import SessionLocal
    return SessionLocal


@contextlib.contextmanager
def _db(user, *, bypass: bool = False):
    from src.database import tenant_context
    with tenant_context(user.tenant_id, bypass=bypass):
        db = _session_factory()()
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()


def _encrypt(s: str) -> str:
    if ENCRYPT is not None:
        return ENCRYPT(s)
    from src.services import encryption_service
    blob = encryption_service.encrypt(s)
    if not blob:
        _err(503, "cifrado no disponible (clave de cifrado del backend ausente)")
    return blob


def _decrypt(blob: str) -> str:
    if DECRYPT is not None:
        return DECRYPT(blob)
    from src.services import encryption_service
    return encryption_service.descifrar_estricto(blob)


def _store():
    if STORE is not None:
        return STORE
    from ..runtime import catalog_version
    return catalog_version()


def _today() -> date:
    return TODAY() if TODAY is not None else datetime.now(timezone.utc).date()


def _dpa(db, entry: cm.CatalogEntry, sheet: Optional[cm.ComplianceSheet]):
    if sheet is None or sheet.dpa_registry_id is None:
        return None
    return _dpa_of(db, entry, sheet.dpa_registry_id)


def _dpa_of(db, entry: cm.CatalogEntry, dpa_id):
    row = (DPA_LOOKUP or _default_dpa_lookup)(db, entry.tenant_id, dpa_id)
    if row is None:
        return None
    owner = row.get("tenant_id")
    if owner is not None and entry.tenant_id is not None and str(owner) != str(entry.tenant_id):
        return None                   # el DPA de otra organización nunca cuenta
    return row


def _default_dpa_lookup(db, tenant_id, dpa_id):
    """Fila del registro de DPAs (base). Lectura con bypass: el DPA de una entrada de instalación es
    del operador y las organizaciones que la ven necesitan su vigencia para el semáforo; solo salen
    fechas y región, nunca el documento."""
    from src.database import tenant_context
    from src.models.compliance import DPARegistry
    with tenant_context(None, bypass=True):
        s = _session_factory()()
        try:
            r = s.get(DPARegistry, uuid.UUID(str(dpa_id)))
            if r is None:
                return None
            return {"tenant_id": r.tenant_id, "expiration_date": r.expiration_date,
                    "processing_region": r.processing_region, "is_active": bool(r.is_active)}
        finally:
            s.close()


def _default_dpa_list(db, tenant_id):
    """DPAs del registro de la organización (base). Solo metadatos: nunca el documento ni las notas."""
    from src.database import tenant_context
    from src.models.compliance import DPARegistry
    with tenant_context(None, bypass=True):
        s = _session_factory()()
        try:
            rows = s.query(DPARegistry).filter(DPARegistry.tenant_id == tenant_id).all()
            return [{"id": r.id, "tenant_id": r.tenant_id, "provider_name": r.provider_name,
                     "dpa_type": r.dpa_type, "processing_region": r.processing_region,
                     "expiration_date": r.expiration_date, "is_active": bool(r.is_active)} for r in rows]
        finally:
            s.close()


def _err(code: int, msg: str):
    raise HTTPException(code, msg)


def _uuid(value, what="id") -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{what} inexistente") from None


def _audit(db, user, *, entity: str, entity_id, action: str, before=None, after=None,
           reason: Optional[str] = None, tenant_id=...):
    db.add(rm.RedirectConfigAudit(
        tenant_id=user.tenant_id if tenant_id is ... else tenant_id, entity=entity,
        entity_id=str(entity_id) if entity_id is not None else None, action=action,
        before=before, after=after, actor_id=getattr(user, "id", None),
        actor_role=getattr(user, "role", None), reason=reason))


def _audit_rule_changes(db, user, changed) -> None:
    """Una fila por entrada que una regla (o un cambio de su proveedor, host o ficha) bloqueó o desbloqueó."""
    for e, what in changed:
        _audit(db, user, entity="catalog_entry", entity_id=e.id,
               action="block_by_rule" if what == "block" else "unblock_by_rule",
               before={"blocked_by_default": what == "unblock"},
               after={"blocked_by_default": what == "block"}, tenant_id=e.tenant_id)


def _bump(tenant_id=None):
    try:
        _store().bump(str(tenant_id) if tenant_id is not None else None)
    except Exception:  # noqa: BLE001 — la caché corta vence sola (TTL)
        pass


# ── acceso a filas ─────────────────────────────────────────────────────────────

def _load_entry(db, user, entry_id) -> cm.CatalogEntry:
    """La entrada, solo si el usuario puede verla; si no, 404 (no «prohibido»: no se confirma que exista)."""
    e = db.get(cm.CatalogEntry, _uuid(entry_id, "entrada"))
    if e is None:
        _err(404, "entrada inexistente")
    if e.tenant_id is not None and e.tenant_id != user.tenant_id:
        _err(404, "entrada inexistente")
    if e.tenant_id is None and not _is_super(user):
        offered = db.query(cm.CatalogOffer).filter(
            cm.CatalogOffer.entry_id == e.id,
            (cm.CatalogOffer.tenant_id == user.tenant_id) | (cm.CatalogOffer.tenant_id.is_(None))).first()
        if offered is None:
            _err(404, "entrada inexistente")
    return e


def _can_write(user, e: cm.CatalogEntry):
    if e.level == "installation" and not _is_super(user):
        _err(403, "solo el operador de la instalación administra entradas de instalación")


def _view(db, user, e: cm.CatalogEntry) -> dict:
    sheet = cs.sheet_of(db, e.id)
    cred = cs.credential_of(db, e)
    owner = e.tenant_id == user.tenant_id or (e.tenant_id is None and _is_super(user))
    out = cs.entry_view(e, sheet, cred, _dpa(db, e, sheet), _today(), owner=owner,
                        region_codes=cregion.effective_codes(db, user.tenant_id))
    if e.level == "installation" and _is_super(user):
        out["offered_to"] = cs.offered_tenants(db, e.id)
    return out


def _bump_for(tenant_id):
    """`None` = entrada de instalación: sube la versión global."""
    _bump(tenant_id)


def _credential_row(db, user, cred_id, *, level: str) -> cm.Credential:
    """Credencial que `user` puede usar para una entrada de `level`; ajena o revocada ⇒ 422."""
    c = db.get(cm.Credential, _uuid(cred_id, "credencial"))
    ok = c is not None and c.status == "active" and (
        (c.tenant_id is not None and c.tenant_id == user.tenant_id and level == "tenant")
        or (c.tenant_id is None and level == "installation" and _is_super(user)))
    if not ok:
        _err(422, "credencial inexistente o no utilizable para esta entrada")
    return c


def _new_credential(db, user, spec: dict, *, level: str) -> cm.Credential:
    """Alta de la credencial de una entrada: `{id}` | `{new: {name, value}}` | `{env_ref}`."""
    if "id" in spec:
        return _credential_row(db, user, spec["id"], level=level)
    tenant = None if level == "installation" else user.tenant_id
    try:
        if "env_ref" in spec:
            if not _is_super(user) or level != "installation":
                _err(403, "las referencias a variables del servidor son solo del operador")
            # Varios modelos comparten la misma variable (p. ej. imagen y audio del mismo proveedor): comparten
            # UNA credencial `env_ref` en vez de chocar por el nombre.
            same = db.query(cm.Credential).filter(cm.Credential.tenant_id == tenant, cm.Credential.kind == "env_ref",
                                                  cm.Credential.env_name == spec["env_ref"],
                                                  cm.Credential.status == "active").first()
            if same is not None:
                return same
            return _create_cred(db, user, level=level, tenant=tenant, name=spec["env_ref"],
                                kind="env_ref", env_name=spec["env_ref"])
        if "new" in spec:
            n = spec["new"] or {}
            return _create_cred(db, user, level=level, tenant=tenant, name=n.get("name") or "",
                                kind="secret", value=n.get("value"))
    except rc.CredentialError as exc:
        _err(422, str(exc))
    _err(422, "credential debe traer id, new o env_ref")


def _create_cred(db, user, *, level, tenant, name, kind, value=None, env_name=None) -> cm.Credential:
    if not name:
        _err(422, "la credencial necesita un nombre")
    dup = db.query(cm.Credential).filter(cm.Credential.tenant_id == tenant, cm.Credential.name == name,
                                         cm.Credential.status == "active").first()
    if dup is not None:
        _err(409, "ya hay una credencial con ese nombre")
    row = cr.create(db, level=level, tenant_id=tenant, name=name, kind=kind, value=value,
                    env_name=env_name, user_id=user.id, encrypt=_encrypt)
    _audit(db, user, entity="credential", entity_id=row.id, action="create",
           after=cr.fingerprint_of(row), tenant_id=tenant)
    return row


def _check_binding(provider: str, level: str, cred_row: Optional[cm.Credential], api_base: Optional[str]):
    """La credencial tiene la forma del proveedor y el proveedor tiene su base (FR-004)."""
    if provider not in rc.SHAPES:
        _err(422, "proveedor desconocido")
    if cred_row is None:
        if rc.requires_secret(provider):
            _err(422, "este proveedor requiere credencial")
    else:
        try:
            cr.validate_for(provider, cr.resolve(cred_row, _decrypt), level)
        except rc.CredentialError as exc:
            _err(422, str(exc))
    if rc.requires_api_base(provider) and not api_base:
        _err(422, "este proveedor requiere api_base")


def _name_taken(db, level, tenant_id, name, *, except_id=None) -> bool:
    q = db.query(cm.CatalogEntry).filter(cm.CatalogEntry.tenant_id == tenant_id,
                                         cm.CatalogEntry.name == name,
                                         cm.CatalogEntry.status != "archived")
    return any(e.id != except_id for e in q)


def _public_id_taken(db, tenant_id, public_id, *, except_id=None) -> bool:
    q = db.query(cm.CatalogEntry).filter(cm.CatalogEntry.tenant_id == tenant_id,
                                         cm.CatalogEntry.public_id == public_id,
                                         cm.CatalogEntry.status != "archived")
    return any(e.id != except_id for e in q)


def _check_public_id(public_id: str):
    if not public_id or any(c.isspace() for c in public_id) or public_id.startswith("rdx-"):
        _err(422, "el id público no puede estar vacío, tener espacios ni empezar con rdx-")


# ── cuerpos (extra=forbid: el semáforo y cualquier campo desconocido son 422) ──────

class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EntryIn(_Body):
    level: str = "tenant"
    name: str = Field(min_length=1, max_length=128)
    public_id: Optional[str] = Field(default=None, max_length=128)   # por defecto, el slug del nombre
    provider: str
    real_model: str = Field(min_length=1, max_length=256)
    protocol_family: str
    api_base: Optional[str] = Field(default=None, max_length=512)
    credential: Optional[dict] = None
    is_aggregator: Optional[bool] = None
    role: str = "text"
    capability: str = "standard"
    features: dict = Field(default_factory=dict)
    provider_options: dict = Field(default_factory=dict)
    context_window: Optional[int] = Field(default=None, ge=1)
    max_output: Optional[int] = Field(default=None, ge=1)
    price_input: Optional[float] = Field(default=None, ge=0)
    price_output: Optional[float] = Field(default=None, ge=0)
    price_source: Optional[str] = Field(default=None, max_length=256)
    price_cache_read: Optional[float] = Field(default=None, ge=0)
    price_cache_write: Optional[float] = Field(default=None, ge=0)
    price_tiers: Optional[list] = None
    limits: dict = Field(default_factory=dict)
    base_model: Optional[str] = Field(default=None, max_length=256)
    advanced: dict = Field(default_factory=dict)
    unsupported_params: list = Field(default_factory=list)


class EntryPatch(_Body):
    name: Optional[str] = Field(default=None, min_length=1, max_length=128)
    public_id: Optional[str] = Field(default=None, min_length=1, max_length=128)
    provider: Optional[str] = None
    real_model: Optional[str] = Field(default=None, min_length=1, max_length=256)
    protocol_family: Optional[str] = None
    api_base: Optional[str] = Field(default=None, max_length=512)
    credential: Optional[dict] = None
    is_aggregator: Optional[bool] = None
    role: Optional[str] = None
    capability: Optional[str] = None
    features: Optional[dict] = None
    provider_options: Optional[dict] = None
    context_window: Optional[int] = Field(default=None, ge=1)
    max_output: Optional[int] = Field(default=None, ge=1)
    price_input: Optional[float] = Field(default=None, ge=0)
    price_output: Optional[float] = Field(default=None, ge=0)
    price_source: Optional[str] = Field(default=None, max_length=256)
    price_cache_read: Optional[float] = Field(default=None, ge=0)
    price_cache_write: Optional[float] = Field(default=None, ge=0)
    price_tiers: Optional[list] = None
    limits: Optional[dict] = None
    base_model: Optional[str] = Field(default=None, max_length=256)
    advanced: Optional[dict] = None
    unsupported_params: Optional[list] = None
    status: Optional[str] = None
    reason: Optional[str] = None


class Reason(_Body):
    reason: str = Field(min_length=3, max_length=2000)


class SheetIn(_Body):
    provider_legal_entity: Optional[str] = Field(default=None, max_length=256)
    entity_jurisdiction: Optional[str] = Field(default=None, max_length=8)
    control_jurisdiction: Optional[str] = Field(default=None, max_length=8)   # quién controla a la entidad (FR-028a)
    inference_jurisdiction: str = Field(default="unknown", max_length=16)
    logs_jurisdiction: str = Field(default="unknown", max_length=16)
    zero_data_retention: Optional[bool] = None
    trains_on_data: Optional[bool] = None
    transfer_mechanism: str = "unknown"
    dpa_registry_id: Optional[str] = None
    eu_region_contracted: Optional[bool] = None
    notes: Optional[str] = None


class OffersIn(_Body):
    tenants: List[str]
    reason: Optional[str] = None


class CredentialIn(_Body):
    name: str = Field(min_length=1, max_length=128)
    kind: str = "secret"
    value: Any = None
    env_name: Optional[str] = Field(default=None, max_length=128)
    level: str = "tenant"


class ReplaceIn(_Body):
    value: Any


class RevokeIn(_Body):
    replacement_id: Optional[str] = None
    deactivate_entries: bool = False
    reason: Optional[str] = None


def _check_vocab(provider=None, protocol=None, role=None, capability=None, features=None, level=None):
    if level is not None and level not in cm.LEVELS:
        _err(422, "nivel desconocido")
    if provider is not None and provider not in cm.PROVIDERS:
        _err(422, "proveedor desconocido")
    if protocol is not None and protocol not in cm.PROTOCOL_FAMILIES:
        _err(422, "familia de protocolo desconocida")
    if role is not None and role not in cm.ROLES:
        _err(422, "rol desconocido")
    if capability is not None and capability not in cm.CAPABILITIES:
        _err(422, "capacidad desconocida")
    if features is not None:
        bad = set(features) - set(cm.FEATURES)
        if bad or any(not isinstance(v, bool) for v in features.values()):
            _err(422, f"capacidades inválidas: {', '.join(sorted(bad)) or 'valores no booleanos'}")


def _check_extras(limits=None, advanced=None, tiers=None):
    """`limits`, `advanced` y `price_tiers` (FR-051, FR-052): claves y valores validados, 422 si no."""
    try:
        if limits is not None:
            cv.check_limits(limits)
        if advanced is not None:
            cv.check_advanced(advanced)
        cv.check_tiers(tiers)
    except ValueError as exc:
        _err(422, str(exc))


def _unsupported(params) -> list:
    """`unsupported_params` normalizado (sin duplicados ni espacios), 422 si no es una lista de nombres válidos."""
    try:
        return cv.check_unsupported_params(params)
    except ValueError as exc:
        _err(422, str(exc))


# ── entradas ───────────────────────────────────────────────────────────────────

@router.get("/entries")
def list_entries(include_archived: bool = False, region_ue: Optional[bool] = None,
                 user=Depends(require_role(*READERS))):
    with _db(user, bypass=_is_super(user)) as db:
        rows = cs.visible_entries(db, user.tenant_id, operator=_is_super(user),
                                  include_archived=include_archived)
        views = [_view(db, user, e) for e in rows]
        if region_ue is not None:                 # «desconocida» (null) no es «fuera de la UE»
            views = [v for v in views if v["region_ue"] is region_ue]
        return {"data": views}


@router.get("/entries/{entry_id}")
def get_entry(entry_id: str, user=Depends(require_role(*READERS))):
    with _db(user, bypass=_is_super(user)) as db:
        return _view(db, user, _load_entry(db, user, entry_id))


def _check_create_authority(user, body: EntryIn):
    if body.level == "installation" and not _is_super(user):
        _err(403, "solo el operador crea entradas de instalación")
    if body.credential is not None and "env_ref" in body.credential and not _is_super(user):
        _err(403, "las referencias a variables del servidor son solo del operador")


def _create_one(db, user, body: EntryIn, cred_of) -> dict:
    """Alta de UNA entrada dentro de `db` (la comparten `POST /entries` y `POST /entries/bulk`).
    `cred_of(db)` resuelve la credencial en el punto en que el alta la necesita. No hace commit ni
    sube la versión de la caché: lo hace quien llama."""
    _check_vocab(body.provider, body.protocol_family, body.role, body.capability, body.features,
                 body.level)
    _check_extras(body.limits, body.advanced, body.price_tiers)
    unsupported = _unsupported(body.unsupported_params)
    tenant = None if body.level == "installation" else user.tenant_id
    if _name_taken(db, body.level, tenant, body.name):
        _err(409, "ya hay una entrada con ese nombre")
    public_id = body.public_id or cm.slugify(body.name)
    _check_public_id(public_id)
    if _public_id_taken(db, tenant, public_id):
        _err(409, "ya hay una entrada con ese id público")
    cred = cred_of(db)
    _check_binding(body.provider, body.level, cred, body.api_base)
    priced = any(v is not None for v in (body.price_input, body.price_output, body.price_cache_read,
                                         body.price_cache_write))
    e = cm.CatalogEntry(
        id=uuid.uuid4(), level=body.level, tenant_id=tenant, name=body.name, public_id=public_id,
        provider=body.provider, real_model=body.real_model, protocol_family=body.protocol_family,
        api_base=body.api_base, credential_id=cred.id if cred else None,
        is_aggregator=(body.provider == "openrouter") if body.is_aggregator is None
        else body.is_aggregator,                             # FR-002a
        role=body.role, capability=body.capability, features=body.features,
        provider_options=body.provider_options, context_window=body.context_window,
        max_output=body.max_output, price_input=body.price_input, price_output=body.price_output,
        price_cache_read=body.price_cache_read, price_cache_write=body.price_cache_write,
        price_tiers=body.price_tiers, limits=body.limits, base_model=body.base_model,
        advanced=body.advanced, unsupported_params=unsupported,
        price_source=body.price_source, price_at=_today() if priced else None,
        # FR-029: nace bloqueada solo si una regla de habilitación aplicable coincide (sin reglas, nunca)
        blocked_by_default=hb.is_blocked(db, tenant, provider=body.provider, api_base=body.api_base),
        status="active", source="console", created_by=user.id, updated_by=user.id)
    db.add(e)
    db.flush()
    db.add(cm.ComplianceSheet(entry_id=e.id))               # nace sin clasificar (FR-039)
    db.flush()
    after = _view(db, user, e)
    _audit(db, user, entity="catalog_entry", entity_id=e.id, action="create",
           after=_audit_view(after), tenant_id=e.tenant_id)
    return after


@router.post("/entries", status_code=201)
def create_entry(body: EntryIn, user=Depends(require_role(*ADMIN))):
    _check_vocab(body.provider, body.protocol_family, body.role, body.capability, body.features,
                 body.level)
    _check_create_authority(user, body)
    with _db(user, bypass=body.level == "installation") as db:
        after = _create_one(db, user, body, lambda d: _new_credential(d, user, body.credential,
                                                                      level=body.level)
                            if body.credential else None)
        tenant = uuid.UUID(after["tenant_id"]) if after["tenant_id"] else None
    _bump_for(tenant)
    return after


def _audit_view(view: dict) -> dict:
    """La vista sin nada que pueda ser un secreto (la vista ya no los lleva; se deja explícito)."""
    return {k: v for k, v in view.items() if k not in ("credential",)} | (
        {"credential_fingerprint": view["credential"]["fingerprint"]} if view.get("credential") else {})


_STALE_FIELDS = ("provider", "real_model")


@router.patch("/entries/{entry_id}")
def update_entry(entry_id: str, body: EntryPatch, user=Depends(require_role(*ADMIN))):
    with _db(user, bypass=_is_super(user)) as db:
        e = _load_entry(db, user, entry_id)
        _can_write(user, e)
        if e.status == "archived":
            _err(409, "entrada archivada: cargar una nueva")
        changes = body.model_dump(exclude_unset=True)
        reason = changes.pop("reason", None)
        cred_spec = changes.pop("credential", None)
        _check_vocab(changes.get("provider"), changes.get("protocol_family"), changes.get("role"),
                     changes.get("capability"), changes.get("features"))
        for k, empty in (("limits", {}), ("advanced", {}), ("unsupported_params", [])):
            if k in changes and changes[k] is None:      # `null` = vaciar (la columna no admite NULL)
                changes[k] = empty
        _check_extras(changes.get("limits"), changes.get("advanced"), changes.get("price_tiers"))
        if "unsupported_params" in changes:
            changes["unsupported_params"] = _unsupported(changes["unsupported_params"])
        if "status" in changes and changes["status"] not in ("active", "inactive"):
            _err(422, "estado inválido (archivar tiene su propia ruta)")
        if "name" in changes and _name_taken(db, e.level, e.tenant_id, changes["name"], except_id=e.id):
            _err(409, "ya hay una entrada con ese nombre")
        if "public_id" in changes:
            _check_public_id(changes["public_id"])
            if _public_id_taken(db, e.tenant_id, changes["public_id"], except_id=e.id):
                _err(409, "ya hay una entrada con ese id público")
        before = _audit_view(_view(db, user, e))
        stale = any(k in changes and changes[k] != getattr(e, k) for k in _STALE_FIELDS)
        identity_before = (e.provider, e.api_base)
        price_changed = any(k in changes for k in ("price_input", "price_output", "price_cache_read",
                                                   "price_cache_write", "price_tiers"))
        for k, v in changes.items():
            setattr(e, k, v)
        if price_changed:
            e.price_at = _today()
        cred = cs.credential_of(db, e)
        if cred_spec is not None:
            cred = _new_credential(db, user, cred_spec, level=e.level)
            e.credential_id = cred.id
        if cred_spec is not None or {"provider", "api_base"} & set(changes):
            _check_binding(e.provider, e.level, cred, e.api_base)
        e.updated_by = user.id
        if stale:
            sheet = cs.sheet_of(db, e.id)
            if sheet is not None:
                sheet.classification_version = cs.STALE
        # FR-029: cambiar proveedor o `api_base` re-evalúa las reglas de habilitación de la entrada
        moved = hb.reapply(db, e, hb.load_rules(db), sheet=cs.sheet_of(db, e.id),
                           identity_changed=(e.provider, e.api_base) != identity_before)
        db.flush()
        after = _view(db, user, e)
        if moved:
            _audit_rule_changes(db, user, [(e, moved)])
        _audit(db, user, entity="catalog_entry", entity_id=e.id, action="update", before=before,
               after=_audit_view(after), reason=reason, tenant_id=e.tenant_id)
        tenant = e.tenant_id
    _bump_for(tenant)
    return after


@router.post("/entries/{entry_id}/archive")
def archive_entry(entry_id: str, body: Reason, user=Depends(require_role(*ADMIN))):
    with _db(user, bypass=_is_super(user)) as db:
        e = _load_entry(db, user, entry_id)
        _can_write(user, e)
        before = _audit_view(_view(db, user, e))
        e.status, e.archived_reason, e.updated_by = "archived", body.reason, user.id
        db.flush()
        after = _view(db, user, e)
        _audit(db, user, entity="catalog_entry", entity_id=e.id, action="archive", before=before,
               after=_audit_view(after), reason=body.reason, tenant_id=e.tenant_id)
        tenant = e.tenant_id
    _bump_for(tenant)
    return after


@router.post("/entries/{entry_id}/enable")
def enable_entry(entry_id: str, body: Reason, user=Depends(require_role("admin", "compliance_officer"))):
    """Habilita una entrada bloqueada por defecto (p. ej. DeepSeek API, FR-017 de la 068). Cumplimiento
    de la organización la habilita para SU organización (en la oferta si es de instalación); el
    operador, la entrada entera."""
    with _db(user, bypass=_is_super(user)) as db:
        e = _load_entry(db, user, entry_id)
        if not e.blocked_by_default:
            _err(409, "la entrada no está bloqueada por defecto")
        if e.level == "installation" and not _is_super(user):
            offer = db.query(cm.CatalogOffer).filter(cm.CatalogOffer.entry_id == e.id,
                                                     cm.CatalogOffer.tenant_id == user.tenant_id).first()
            if offer is None:
                _err(409, "habilitar por organización requiere una oferta explícita a esta organización")
            before = {"enabled_at": offer.enabled_at.isoformat() if offer.enabled_at else None}
            offer.enabled_at, offer.enabled_by, offer.enable_reason = datetime.now(timezone.utc), user.id, body.reason
            tenant = user.tenant_id
        else:
            before = {"enabled_at": e.enabled_at.isoformat() if e.enabled_at else None}
            e.enabled_at, e.enabled_by, e.enable_reason = datetime.now(timezone.utc), user.id, body.reason
            tenant = e.tenant_id
        db.flush()
        after = _view(db, user, e)
        _audit(db, user, entity="catalog_entry", entity_id=e.id, action="enable", before=before,
               after={"enabled_at": datetime.now(timezone.utc).isoformat()}, reason=body.reason,
               tenant_id=tenant)
    _bump_for(tenant)
    return after


# ── reglas de habilitación explícita (057 FR-029; contracts/admin-api.md) ───────────────────────

class RuleIn(_Body):
    kind: str
    value: str = Field(min_length=1, max_length=256)
    level: str = "tenant"
    reason: str = Field(min_length=3, max_length=2000)


def _rule_view(r: cm.EnablementRule) -> dict:
    return {"id": str(r.id), "kind": r.kind, "value": r.value, "level": r.level,
            "tenant_id": None if r.tenant_id is None else str(r.tenant_id), "reason": r.reason,
            "created_by_role": r.created_by_role,
            "created_at": r.created_at.isoformat() if r.created_at else None}


def _visible_rules(db, user) -> list:
    """Las de instalación y las de la empresa del usuario; las de otra empresa nunca (defensa en profundidad
    además de la RLS)."""
    rows = [r for r in db.query(cm.EnablementRule)
            if r.tenant_id is None or r.tenant_id == user.tenant_id]
    return sorted(rows, key=lambda r: (r.level, r.kind, r.value))


@router.get("/enablement-rules")
def list_enablement_rules(user=Depends(require_role("admin", "compliance_officer"))):
    with _db(user) as db:
        return {"data": [_rule_view(r) for r in _visible_rules(db, user)]}


@router.post("/enablement-rules", status_code=201)
def create_enablement_rule(body: RuleIn, user=Depends(require_role("admin", "compliance_officer"))):
    """Agrega una regla y re-evalúa las entradas afectadas (devuelve cuántas cambiaron). La empresa solo agrega
    reglas propias (endurece); las de instalación son del operador."""
    if body.level not in cm.LEVELS:
        _err(422, "nivel desconocido")
    installation = body.level == "installation"
    if installation and not _is_super(user):
        _err(403, "las reglas de instalación son del operador de la instalación")
    try:
        value = hb.validate(body.kind, body.value)
    except ValueError as exc:
        _err(422, str(exc))
    tenant = None if installation else user.tenant_id
    with _db(user, bypass=installation) as db:
        dup = db.query(cm.EnablementRule).filter(
            cm.EnablementRule.tenant_id == tenant if tenant is not None else cm.EnablementRule.tenant_id.is_(None),
            cm.EnablementRule.kind == body.kind, cm.EnablementRule.value == value).first()
        if dup is not None:
            _err(409, "ya hay una regla igual")
        row = cm.EnablementRule(id=uuid.uuid4(), level=body.level, tenant_id=tenant, kind=body.kind, value=value,
                                reason=body.reason, created_by=user.id,
                                created_by_role=str(getattr(user, "role", None) or "admin")[:32])
        db.add(row)
        db.flush()
        changed = hb.reevaluate(db, tenant_id=tenant, only_tenant=not installation)
        view = _rule_view(row)
        _audit(db, user, entity="enablement_rule", entity_id=row.id, action="create",
               after={k: view[k] for k in ("kind", "value", "level")} | {"changed": len(changed)},
               reason=body.reason, tenant_id=tenant)
        _audit_rule_changes(db, user, changed)
    _bump(tenant)
    return view | {"changed": len(changed)}


@router.delete("/enablement-rules/{rule_id}")
def delete_enablement_rule(rule_id: str, user=Depends(require_role("admin", "compliance_officer"))):
    """Quita una regla (devuelve cuántas entradas se desbloquearon). Instalación: el operador; empresa:
    cumplimiento de esa empresa (el admin de empresa agrega pero no quita)."""
    with _db(user, bypass=_is_super(user)) as db:
        r = db.get(cm.EnablementRule, _uuid(rule_id, "regla"))
        if r is None or (r.tenant_id is not None and r.tenant_id != user.tenant_id):
            _err(404, "regla inexistente")
        if r.tenant_id is None and not _is_super(user):
            _err(403, "las reglas de instalación son del operador de la instalación")
        if r.tenant_id is not None and not (_is_super(user) or "compliance_officer" in effective_roles(user)):
            _err(403, "quitar una regla de la empresa es de cumplimiento")
        tenant, view = r.tenant_id, _rule_view(r)
        db.delete(r)
        db.flush()
        changed = hb.reevaluate(db, tenant_id=tenant, only_tenant=tenant is not None)
        _audit(db, user, entity="enablement_rule", entity_id=rule_id, action="delete",
               before={k: view[k] for k in ("kind", "value", "level")}, after={"changed": len(changed)},
               reason=None, tenant_id=tenant)
        _audit_rule_changes(db, user, changed)
    _bump(tenant)
    return {"id": view["id"], "changed": len(changed)}


# ── registro de DPAs (selector de la ficha) ────────────────────────────────────

@router.get("/dpas")
def list_dpas(user=Depends(require_role(*READERS))):
    """DPAs del registro de la organización, para elegir uno en la ficha sin tener que conocer su UUID."""
    today = _today()
    with _db(user, bypass=_is_super(user)) as db:
        rows = (DPA_LIST or _default_dpa_list)(db, user.tenant_id)
    out = []
    for r in rows:
        if str(r.get("tenant_id")) != str(user.tenant_id):
            continue                                 # el DPA de otra organización nunca sale
        vence = r.get("expiration_date")
        out.append({"id": str(r["id"]), "provider_name": r.get("provider_name"), "dpa_type": r.get("dpa_type"),
                    "processing_region": r.get("processing_region"),
                    "expiration_date": vence.isoformat() if vence else None,
                    "vigente": bool(r.get("is_active", True)) and (vence is None or vence >= today)})
    out.sort(key=lambda d: (d["provider_name"] or "").lower())
    return {"data": out}


# ── ficha de cumplimiento ──────────────────────────────────────────────────────

@router.get("/entries/{entry_id}/sheet")
def get_sheet(entry_id: str, user=Depends(require_role(*READERS))):
    with _db(user, bypass=_is_super(user)) as db:
        v = _view(db, user, _load_entry(db, user, entry_id))
        return {"sheet": v["sheet"], "semaforo": v["semaforo"]}


@router.put("/entries/{entry_id}/sheet")
def put_sheet(entry_id: str, body: SheetIn, user=Depends(require_role(*SHEET_WRITERS))):
    if body.transfer_mechanism not in cm.TRANSFER_MECHANISMS:
        _err(422, "mecanismo de transferencia desconocido")
    with _db(user, bypass=_is_super(user)) as db:
        e = _load_entry(db, user, entry_id)
        _can_write(user, e)
        if e.status == "archived":
            _err(409, "entrada archivada")
        dpa_id = None
        if body.dpa_registry_id:
            dpa_id = _uuid(body.dpa_registry_id, "DPA")
            if _dpa_of(db, e, dpa_id) is None:
                _err(422, "el DPA no existe en el registro de DPAs de esta organización")
        sheet = cs.sheet_of(db, e.id)
        if sheet is None:
            sheet = cm.ComplianceSheet(entry_id=e.id)
            db.add(sheet)
        before = {"sheet": cs.sheet_view(sheet), "semaforo": cs.semaforo_of(e, sheet, _dpa(db, e, sheet), _today())}
        juris_before = tuple(getattr(sheet, f, None) for f in hb.JURISDICTION_FIELDS)
        try:
            control = cv.check_jurisdiction(body.control_jurisdiction)
        except ValueError as exc:
            _err(422, str(exc))
        for f in cs.SHEET_FIELDS:
            setattr(sheet, f, getattr(body, f))
        sheet.control_jurisdiction = control
        sheet.dpa_registry_id = dpa_id
        for f in ("inference_jurisdiction", "logs_jurisdiction", "entity_jurisdiction"):
            v = getattr(sheet, f)
            if v:
                setattr(sheet, f, v.upper() if len(v) <= 3 else v.lower())
        sheet.classification_version = _next_version(sheet.classification_version)
        sheet.classified_by, sheet.classified_at = user.id, datetime.now(timezone.utc)
        e.updated_by = user.id
        # FR-029: las jurisdicciones de la ficha entran en las reglas de habilitación
        moved = hb.reapply(db, e, hb.load_rules(db), sheet=sheet, identity_changed=tuple(
            getattr(sheet, f, None) for f in hb.JURISDICTION_FIELDS) != juris_before)
        # FR-031a: una relajación por destino solo vale mientras la ficha cumpla sus precondiciones
        crelax.revoke_unmet(db, e, sheet, user, audit=lambda **kw: _audit(db, user, **kw))
        db.flush()
        after = _view(db, user, e)
        if moved:
            _audit_rule_changes(db, user, [(e, moved)])
        _audit(db, user, entity="catalog_sheet", entity_id=e.id, action="update", before=before,
               after={"sheet": after["sheet"], "semaforo": after["semaforo"]}, tenant_id=e.tenant_id)
        tenant = e.tenant_id
    _bump_for(tenant)
    return after


def _next_version(prev: Optional[str]) -> str:
    n = 0
    if prev and prev.startswith("console:"):
        with contextlib.suppress(ValueError):
            n = int(prev.split(":", 1)[1])
    return f"console:{n + 1}"


# ── ofertas (solo operador) ────────────────────────────────────────────────────

@router.put("/entries/{entry_id}/offers")
def put_offers(entry_id: str, body: OffersIn, user=Depends(require_role(*ADMIN))):
    if not _is_super(user):
        _err(403, "ofrecer entradas es del operador de la instalación")
    tenants = [t.strip() for t in body.tenants]
    all_tenants = "*" in tenants
    ids = [] if all_tenants else [_uuid(t, "organización") for t in tenants]
    with _db(user, bypass=True) as db:
        e = _load_entry(db, user, entry_id)
        if e.level != "installation":
            _err(409, "solo las entradas de instalación se ofrecen")
        current = db.query(cm.CatalogOffer).filter(cm.CatalogOffer.entry_id == e.id).all()
        before = cs.offered_tenants(db, e.id)
        wanted = {None} if all_tenants else set(ids)
        for o in current:
            if o.tenant_id not in wanted:
                db.delete(o)                       # retirar la oferta la saca de esa organización
        for t in wanted - {o.tenant_id for o in current}:
            db.add(cm.CatalogOffer(id=uuid.uuid4(), entry_id=e.id, tenant_id=t, created_by=user.id))
        db.flush()
        after = sorted("*" if t is None else str(t) for t in wanted)
        _audit(db, user, entity="catalog_offer", entity_id=e.id, action="replace",
               before={"tenants": before}, after={"tenants": after}, reason=body.reason, tenant_id=None)
        eid = str(e.id)
    _bump(None)
    return {"entry_id": eid, "tenants": after}


# ── credenciales ───────────────────────────────────────────────────────────────

def _cred_view(db, c: cm.Credential) -> dict:
    return {"id": str(c.id), "name": c.name, "kind": c.kind, "level": c.level,
            "fingerprint": c.fingerprint, "status": c.status,
            "in_use_by": sorted(e.name for e in cr.in_use_by(db, c))}


def _load_credential(db, user, cred_id) -> cm.Credential:
    c = db.get(cm.Credential, _uuid(cred_id, "credencial"))
    if c is None or (c.tenant_id is not None and c.tenant_id != user.tenant_id) \
            or (c.tenant_id is None and not _is_super(user)):
        _err(404, "credencial inexistente")
    return c


@router.get("/credentials")
def list_credentials(user=Depends(require_role(*ADMIN))):
    with _db(user, bypass=_is_super(user)) as db:
        rows = [c for c in db.query(cm.Credential).filter(cm.Credential.status == "active")
                if c.tenant_id == user.tenant_id or (c.tenant_id is None and _is_super(user))]
        return {"data": [_cred_view(db, c) for c in sorted(rows, key=lambda c: c.name)]}


@router.post("/credentials", status_code=201)
def create_credential(body: CredentialIn, user=Depends(require_role(*ADMIN))):
    if body.kind not in cm.CREDENTIAL_KINDS:
        _err(422, "tipo de credencial desconocido")
    installation = body.level == "installation"
    if (installation or body.kind == "env_ref") and not _is_super(user):
        _err(403, "las credenciales de instalación y las referencias a variables del servidor "
                  "son del operador")
    tenant = None if installation else user.tenant_id
    try:
        with _db(user, bypass=installation) as db:
            row = _create_cred(db, user, level=body.level, tenant=tenant, name=body.name,
                               kind=body.kind, value=body.value, env_name=body.env_name)
            view = _cred_view(db, row)
    except rc.CredentialError as exc:
        _err(422, str(exc))
    return view


@router.post("/credentials/{cred_id}/replace")
def replace_credential(cred_id: str, body: ReplaceIn, user=Depends(require_role(*ADMIN))):
    try:
        with _db(user, bypass=_is_super(user)) as db:
            c = _load_credential(db, user, cred_id)
            if c.status != "active":
                _err(409, "credencial revocada")
            uses = cr.in_use_by(db, c)
            new = cr.to_dict(body.value)
            for e in uses:                       # la nueva debe servir a cada modelo que la usa
                cr.validate_for(e.provider, new, e.level)
            diff = cr.replace(db, c, new, encrypt=_encrypt)
            _audit(db, user, entity="credential", entity_id=c.id, action="replace",
                   before=diff["before"], after=diff["after"], tenant_id=c.tenant_id)
            view, tenant = _cred_view(db, c), c.tenant_id
    except rc.CredentialError as exc:
        _err(422, str(exc))
    _bump(tenant)
    return view


@router.post("/credentials/{cred_id}/revoke")
def revoke_credential(cred_id: str, body: RevokeIn, user=Depends(require_role(*ADMIN))):
    with _db(user, bypass=_is_super(user)) as db:
        c = _load_credential(db, user, cred_id)
        if c.status != "active":
            _err(409, "credencial ya revocada")
        repl = None
        if body.replacement_id:
            repl = db.get(cm.Credential, _uuid(body.replacement_id, "credencial de reemplazo"))
            if repl is None or repl.status != "active" or repl.id == c.id or repl.tenant_id != c.tenant_id:
                _err(422, "reemplazo inexistente o de otro nivel/organización")
        before = cr.fingerprint_of(c)
        try:
            for e in cr.in_use_by(db, c):
                if repl is not None:
                    cr.validate_for(e.provider, cr.resolve(repl, _decrypt), e.level)
            touched = cr.revoke(db, c, replacement=repl, deactivate_entries=body.deactivate_entries)
        except cr.CredentialInUse as exc:
            db.rollback()
            _err(409, "la credencial está en uso por: " + ", ".join(exc.entries)
                 + ". Elegí un reemplazo o desactivá esos modelos.")
        except rc.CredentialError as exc:
            _err(422, str(exc))
        _audit(db, user, entity="credential", entity_id=c.id, action="revoke", before=before,
               after={**cr.fingerprint_of(c), "affected": sorted(e.name for e in touched),
                      "replacement_id": body.replacement_id,
                      "deactivated": bool(body.deactivate_entries and touched)},
               reason=body.reason, tenant_id=c.tenant_id)
        view, tenant = {"id": str(c.id), "status": c.status}, c.tenant_id
    _bump(tenant)
    return view
