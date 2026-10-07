"""API de administración `/api/v1/redirect/*` (contracts/admin-api.md; T061/T062/T076).

MVP: destinos (SOLO LECTURA desde la 069 E3: son las entradas del catálogo único, que se dan de alta y
se editan en Modelos), ids publicados, reglas, estado de política por alcance, posturas con las reglas de
rol de FR-014a y vista previa de resolución (la MISMA función que el plano de datos). Kits, fidelidad y
costos: `us5.py`.

Reglas transversales:
- sesión de usuario con `require_role` del backend (las llaves virtuales no entran);
- toda escritura deja fila en `sentinel_redirect_config_audit` (antes/después **sin secretos**)
  y sube la versión de la caché del plano de datos (`store.bump`);
- los avisos de destino son DERIVADOS al leer, no se guardan: `GET /rules` y `GET /destinations` anotan
  `warnings: [{code, destination_id}]` con `offer_withdrawn` (FR-005b: era de instalación y ya no se le
  ofrece a la organización) o `destination_unavailable` (069 E3: el id no es hoy una entrada activa, de
  texto y visible del catálogo: archivada, inactiva, de otro tipo o inexistente);
- las credenciales son **write-only**: nunca vuelven en una respuesta ni en la auditoría (solo
  `has_credential`);
- el tenant es SIEMPRE el de la sesión; la sesión de base se abre con `tenant_context` (RLS), y
  con bypass solo para super_admin en operaciones de nivel instalación.

Roles (FR-014a/b): `admin` es el alias que la base expande para tenant_admin y super_admin.
"""
from __future__ import annotations

import contextlib
import os
import uuid
from datetime import datetime, timezone
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from sentinel.access import bridge
from src.auth.rbac import effective_roles, require_role

from .. import residency, resolver
from .. import models as m
from ..scopes import RequestScope
from ..store import default_store, destination_dict, load_from_session, region_dicts

router = APIRouter(prefix="/redirect", tags=["redirect"])

TENANT_ADMIN = ("admin",)                       # tenant_admin y super_admin (alias de la base)
READERS = ("admin", "compliance_officer")
POSTURE_WRITERS = ("compliance_officer", "super_admin")

# Inyectables para tests (sin Postgres): fábrica de sesiones y caché del plano de datos.
SESSION_FACTORY = None
STORE = None


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


def _store():
    return STORE if STORE is not None else default_store()


def _roles(user) -> set:
    return effective_roles(user)


def _is_operator_tenant(user) -> bool:
    """Tenant operador de la instalación, declarado por el operador del SERVIDOR con
    `REDIRECT_OPERATOR_TENANT=<uuid>`. En una instalación de un solo tenant no existe
    super_admin: su tenant_admin ES quien opera la instalación. Declararlo por entorno no abre
    nada nuevo (quien controla ese entorno ya controla las credenciales `REDIRECT_CRED_*`).
    Sin la variable: nadie más que super_admin."""
    declarado = os.environ.get("REDIRECT_OPERATOR_TENANT", "").strip()
    return bool(declarado) and str(getattr(user, "tenant_id", "")) == declarado \
        and getattr(user, "role", None) in ("tenant_admin", "admin")


def _is_super(user) -> bool:
    """Autoridad de instalación: super_admin, o tenant_admin del tenant operador."""
    return getattr(user, "role", None) == "super_admin" or _is_operator_tenant(user)


def _manages_postures(user) -> bool:
    return "compliance_officer" in _roles(user) or _is_super(user)


def _real_role(user) -> Optional[str]:
    """Rol **real** con autoridad para regiones, `default_posture` y relajaciones (057 FR-023; research R30):
    `super_admin` o `compliance_officer`. El tenant operador declarado por entorno (`REDIRECT_OPERATOR_TENANT`) NO
    cuenta: su `tenant_admin` sigue siendo admin de empresa para esto. Devuelve el rol (`super_admin` gana)."""
    if getattr(user, "role", None) == "super_admin" or "super_admin" in _roles(user):
        return "super_admin"
    if "compliance_officer" in _roles(user):
        return "compliance_officer"
    return None


def _authority_label(user) -> str:
    """`created_by_role` de una fila de postura: con qué autoridad se escribió (data-model §1). El admin de empresa
    escribe filas que solo restringen; cumplimiento, super-admin y el operador declarado escriben filas de base."""
    real = _real_role(user)
    if real:
        return real
    return "super_admin" if _is_super(user) else (getattr(user, "role", None) or "tenant_admin")


def _now():
    return datetime.now(timezone.utc)


def _uuid(value, what="id") -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{what} inexistente") from None


def _err(code: int, msg: str):
    raise HTTPException(code, msg)


def _audit(db, user, *, entity: str, entity_id, action: str, before=None, after=None,
           reason: Optional[str] = None, tenant_id=...):
    db.add(m.RedirectConfigAudit(
        tenant_id=user.tenant_id if tenant_id is ... else tenant_id, entity=entity,
        entity_id=str(entity_id) if entity_id is not None else None, action=action,
        before=before, after=after, actor_id=getattr(user, "id", None),
        actor_role=getattr(user, "role", None), reason=reason))


def _bump(tenant_id=None):
    try:
        _store().bump(str(tenant_id) if tenant_id is not None else None)
    except Exception:  # noqa: BLE001 — la caché corta vence sola (TTL)
        pass


def _bump_region(tenant_id=None):
    """Una región cambia lo que dicen el plano de datos **y** el semáforo del catálogo (FR-030a): sube las dos versiones."""
    _bump(tenant_id)
    try:
        from sentinel.catalog.runtime import catalog_version
        catalog_version().bump(str(tenant_id) if tenant_id is not None else None)
    except Exception:  # noqa: BLE001 — rige el TTL
        pass


def _scope_ok(scope_type: str, scope_value: str):
    if scope_type not in m.SCOPE_TYPES:
        _err(422, f"alcance desconocido: {scope_type}")
    if scope_type == "tenant" and scope_value != "*":
        _err(422, "el alcance tenant se escribe con scope_value='*'")
    if scope_type != "tenant":
        _uuid(scope_value, "alcance")


def _row(obj, fields) -> dict:
    out = {}
    for f in fields:
        v = getattr(obj, f)
        out[f] = str(v) if isinstance(v, uuid.UUID) else (v.isoformat() if isinstance(v, datetime) else v)
    if "strategy" in fields and not out["strategy"]:
        out["strategy"] = "order"            # filas anteriores a la estrategia por regla
    return out


# ── destinos ──────────────────────────────────────────────────────────────────
# Desde la 069 E3 los destinos SON las entradas del catálogo único: se dan de alta, se editan, se archivan,
# se habilitan y se ofrecen en Modelos (`/api/v1/catalog/*`). Esta pantalla solo los lista (qué destinos
# puede usar la organización en sus reglas) y los escritores de la 068 responden 410.

def _is_missing_catalog(exc: Exception) -> bool:
    return "ext_" in str(getattr(exc, "orig", exc)).lower()


def _legacy_destinations(db, user) -> list:
    """Respaldo cuando las tablas del catálogo no existen (migración sin aplicar): la tabla propia de la 068."""
    offered = {o.destination_id for o in db.query(m.RedirectOffer).filter(
        (m.RedirectOffer.tenant_id == user.tenant_id) | (m.RedirectOffer.tenant_id.is_(None)))}
    return [destination_dict(d) for d in db.query(m.RedirectDestination)
            if d.tenant_id == user.tenant_id or (d.tenant_id is None and d.id in offered)]


def _usable_destinations(db, user) -> list:
    """Los destinos que la organización de la sesión puede usar: entradas activas de texto del catálogo, propias
    o de instalación ofrecidas. Es la fuente de la lista, de la validación de reglas y de los avisos; el plano
    de datos arma su instantánea con la misma lectura (`sentinel.catalog.store`)."""
    try:
        from sentinel.catalog.store import redirect_destinations
        with db.begin_nested():
            return redirect_destinations(db, user.tenant_id)
    except ImportError:                     # imagen sin el paquete del catálogo
        return _legacy_destinations(db, user)
    except Exception as exc:  # noqa: BLE001
        if not _is_missing_catalog(exc):
            raise
        return _legacy_destinations(db, user)


def _rule_targets(db, user):
    return [t for r in db.query(m.RedirectRule).filter(m.RedirectRule.tenant_id == user.tenant_id)
            for t in (r.targets or [])]


@router.get("/destinations")
def list_destinations(user=Depends(require_role(*READERS))):
    with _db(user) as db:
        rows = _usable_destinations(db, user)
        targets = _rule_targets(db, user)
    # Avisos (FR-005b / E3): los destinos que las reglas del tenant nombran y hoy no puede usar. No aparecen
    # en `data` (FR-005a), así que el aviso va también arriba, junto a la lista.
    unavailable = _unavailable_targets(user, targets, {r["id"] for r in rows})
    for row in rows:
        row["warnings"] = []
    return {"data": sorted(rows, key=lambda r: (r["level"], r["name"])),
            "warnings": [_warning(t, code) for t, code in sorted(unavailable.items())]}


class Reason(BaseModel):
    reason: str = Field(min_length=3, max_length=2000)


def _gone(replacement: str):
    """410: la política de redirección ya no escribe destinos; el alta y la edición son del catálogo."""
    _err(status.HTTP_410_GONE,
         "Los destinos se dan de alta y se editan en Modelos (catálogo único): "
         f"{replacement}. Esta ruta de la política de redirección ya no escribe.")


@router.post("/destinations", status_code=201)
def create_destination(user=Depends(require_role(*TENANT_ADMIN))):
    _gone("POST /api/v1/catalog/entries")


@router.patch("/destinations/{dest_id}")
def update_destination(dest_id: str, user=Depends(require_role(*TENANT_ADMIN))):
    _gone(f"PATCH /api/v1/catalog/entries/{dest_id}")


@router.post("/destinations/{dest_id}/revoke")
def revoke_destination(dest_id: str, user=Depends(require_role(*TENANT_ADMIN))):
    _gone(f"POST /api/v1/catalog/entries/{dest_id}/archive")


@router.post("/destinations/{dest_id}/enable")
def enable_destination(dest_id: str, user=Depends(require_role("admin", "compliance_officer"))):
    _gone(f"POST /api/v1/catalog/entries/{dest_id}/enable")


@router.put("/destinations/{dest_id}/offer")
def offer_destination(dest_id: str, user=Depends(require_role("admin"))):
    _gone(f"PUT /api/v1/catalog/entries/{dest_id}/offers")


# ── ids publicados ────────────────────────────────────────────────────────────

class PublishedIn(BaseModel):
    face: str
    public_id: str = Field(min_length=1, max_length=128, pattern=r"^\S+$")
    family_tier: Optional[str] = None
    is_family_default: bool = False
    label: Optional[str] = Field(default=None, max_length=256)
    label_mode: str = "requested"
    scope_type: str = "tenant"
    scope_value: str = "*"
    reference_model: Optional[str] = Field(default=None, max_length=256)


class PublishedPatch(BaseModel):
    family_tier: Optional[str] = None
    is_family_default: Optional[bool] = None
    label: Optional[str] = Field(default=None, max_length=256)
    label_mode: Optional[str] = None
    reference_model: Optional[str] = Field(default=None, max_length=256)


_PUB_FIELDS = ("id", "face", "public_id", "family_tier", "is_family_default", "label", "label_mode",
               "scope_type", "scope_value", "reference_model")


def _check_published(face, public_id, family_tier, label_mode):
    if face is not None and face not in m.FACES:
        _err(422, "cara desconocida")
    if public_id is not None and public_id.startswith("rdx-"):
        _err(422, "el prefijo rdx- es interno")
    if face == "claude" and public_id is not None and not public_id.lower().startswith("claude"):
        _err(422, "en la cara Claude el id publicado tiene que empezar con «claude»: Claude Code descarta del lado "
                  "del cliente los modelos que no reconoce, así que otro id no lo usaría esa herramienta")
    if family_tier is not None and family_tier not in m.FAMILY_TIERS:
        _err(422, "tier desconocido")
    if label_mode is not None and label_mode not in m.LABEL_MODES:
        _err(422, "modo de etiqueta desconocido")


def _own(db, model, obj_id, user):
    obj = db.get(model, _uuid(obj_id))
    if obj is None or obj.tenant_id != user.tenant_id:
        _err(404, "inexistente")
    return obj


@router.get("/published-models")
def list_published(user=Depends(require_role(*READERS))):
    with _db(user) as db:
        rows = db.query(m.RedirectPublishedModel).filter(
            m.RedirectPublishedModel.tenant_id == user.tenant_id)
        return {"data": sorted((_row(r, _PUB_FIELDS) for r in rows),
                               key=lambda r: (r["face"], r["public_id"], r["scope_type"]))}


@router.post("/published-models", status_code=201)
def create_published(body: PublishedIn, user=Depends(require_role(*TENANT_ADMIN))):
    _check_published(body.face, body.public_id, body.family_tier, body.label_mode)
    _scope_ok(body.scope_type, body.scope_value)
    with _db(user) as db:
        dup = db.query(m.RedirectPublishedModel).filter_by(
            tenant_id=user.tenant_id, face=body.face, public_id=body.public_id,
            scope_type=body.scope_type, scope_value=body.scope_value).first()
        if dup is not None:
            _err(409, "ese id ya está publicado en ese alcance")
        r = m.RedirectPublishedModel(id=uuid.uuid4(), tenant_id=user.tenant_id, created_by=user.id,
                                     updated_by=user.id, **body.model_dump())
        db.add(r)
        db.flush()
        after = _row(r, _PUB_FIELDS)
        _audit(db, user, entity="published_model", entity_id=r.id, action="create", after=after)
    _bump(user.tenant_id)
    return after


@router.patch("/published-models/{pub_id}")
def update_published(pub_id: str, body: PublishedPatch, user=Depends(require_role(*TENANT_ADMIN))):
    changes = body.model_dump(exclude_unset=True)
    _check_published(None, None, changes.get("family_tier"), changes.get("label_mode"))
    with _db(user) as db:
        r = _own(db, m.RedirectPublishedModel, pub_id, user)
        before = _row(r, _PUB_FIELDS)
        for k, v in changes.items():
            setattr(r, k, v)
        r.updated_by = user.id
        db.flush()
        after = _row(r, _PUB_FIELDS)
        entity = "label" if set(changes) <= {"label", "label_mode"} else "published_model"
        _audit(db, user, entity=entity, entity_id=r.id, action="update", before=before, after=after)
    _bump(user.tenant_id)
    return after


@router.delete("/published-models/{pub_id}", status_code=204)
def delete_published(pub_id: str, user=Depends(require_role(*TENANT_ADMIN))):
    with _db(user) as db:
        r = _own(db, m.RedirectPublishedModel, pub_id, user)
        before = _row(r, _PUB_FIELDS)
        for rule in db.query(m.RedirectRule).filter(m.RedirectRule.published_model_id == r.id):
            db.delete(rule)
        db.delete(r)
        _audit(db, user, entity="published_model", entity_id=pub_id, action="delete", before=before)
    _bump(user.tenant_id)


# ── reglas ────────────────────────────────────────────────────────────────────

class RuleIn(BaseModel):
    published_model_id: Optional[str] = None
    family_tier: Optional[str] = None
    request_class: Optional[str] = None
    scope_type: str = "tenant"
    scope_value: str = "*"
    targets: List[str] = Field(min_length=1)
    strategy: str = "order"


class RulePatch(BaseModel):
    request_class: Optional[str] = None
    strategy: Optional[str] = None
    targets: Optional[List[str]] = Field(default=None, min_length=1)


_RULE_FIELDS = ("id", "published_model_id", "family_tier", "request_class", "scope_type",
                "scope_value", "targets", "strategy")


def _check_targets(db, user, targets):
    """Cada destino de una regla tiene que ser hoy una entrada usable del catálogo (la misma lista de
    `GET /destinations`): propia o de instalación ofrecida, activa y de texto."""
    visible = {d["id"] for d in _usable_destinations(db, user)}
    for t in targets:
        if str(_uuid(t, "destino")) not in visible:
            _err(422, f"destino no disponible para este tenant: {t}")
    return [str(uuid.UUID(t)) for t in targets]


OFFER_WITHDRAWN = "offer_withdrawn"
DESTINATION_UNAVAILABLE = "destination_unavailable"


def _warning(dest_id: str, code: str = OFFER_WITHDRAWN) -> dict:
    """Solo código + id: el id ya está en la regla del tenant; nada más del destino."""
    return {"code": code, "destination_id": dest_id}


def _installation_ids(user, ids) -> Optional[set]:
    """Ids (de `ids`) que son hoy entradas ACTIVAS de texto de INSTALACIÓN. Lectura con bypass: la RLS le oculta
    a la organización las que no se le ofrecen, y justo eso es lo que hay que distinguir de un id inexistente.
    Solo clasifica ids que la propia regla de la organización ya nombra; no devuelve datos de la entrada.
    `None` si no hay tablas de catálogo (respaldo de la 068: todo faltante es una oferta retirada)."""
    try:
        from sentinel.catalog import models as cm
        with _db(user, bypass=True) as db:
            rows = db.query(cm.CatalogEntry.id).filter(
                cm.CatalogEntry.id.in_([uuid.UUID(i) for i in ids]), cm.CatalogEntry.tenant_id.is_(None),
                cm.CatalogEntry.status == "active", cm.CatalogEntry.role == "text").all()
    except ImportError:
        return None
    except Exception as exc:  # noqa: BLE001
        if _is_missing_catalog(exc):
            return None
        raise
    return {str(r[0]) for r in rows}


def _unavailable_targets(user, targets, usable_ids) -> dict:
    """`{id: código}` de los destinos de `targets` (los de las reglas del tenant) que ya no puede usar:
    `offer_withdrawn` si es una entrada de instalación que dejó de ofrecérsele (FR-005b); `destination_unavailable`
    si el id no es hoy una entrada activa de texto del catálogo (archivada, inactiva, de otro tipo o inexistente;
    E3). Sin tablas de catálogo (respaldo de la 068), lo que falta es una oferta retirada, como antes."""
    wanted = {str(t) for t in targets} - set(usable_ids)
    if not wanted:
        return {}
    valid = set()
    for t in wanted:
        try:
            valid.add(str(uuid.UUID(t)))
        except ValueError:
            pass
    installation = _installation_ids(user, valid) if valid else set()
    return {t: (OFFER_WITHDRAWN if installation is None or t in installation else DESTINATION_UNAVAILABLE)
            for t in wanted}


@router.get("/rules")
def list_rules(user=Depends(require_role(*READERS))):
    with _db(user) as db:
        rows = [_row(r, _RULE_FIELDS) for r in db.query(m.RedirectRule).filter(m.RedirectRule.tenant_id == user.tenant_id)]
        usable = {d["id"] for d in _usable_destinations(db, user)}
    unavailable = _unavailable_targets(user, [t for row in rows for t in row["targets"]], usable)
    for row in rows:
        row["warnings"] = [_warning(t, unavailable[str(t)]) for t in row["targets"] if str(t) in unavailable]
    return {"data": rows}


@router.post("/rules", status_code=201)
def create_rule(body: RuleIn, user=Depends(require_role(*TENANT_ADMIN))):
    if body.published_model_id is None and body.family_tier is None:
        _err(422, "la regla necesita un id publicado o un tier")
    if body.family_tier is not None and body.family_tier not in m.FAMILY_TIERS:
        _err(422, "tier desconocido")
    if body.request_class is not None and body.request_class not in m.REQUEST_CLASSES:
        _err(422, "clase de pedido desconocida")
    if body.strategy not in resolver.STRATEGIES:
        _err(422, "estrategia desconocida")
    _scope_ok(body.scope_type, body.scope_value)
    with _db(user) as db:
        pub = None
        if body.published_model_id is not None:
            pub = _own(db, m.RedirectPublishedModel, body.published_model_id, user).id
        r = m.RedirectRule(id=uuid.uuid4(), tenant_id=user.tenant_id, published_model_id=pub,
                           family_tier=body.family_tier, request_class=body.request_class,
                           scope_type=body.scope_type, scope_value=body.scope_value,
                           targets=_check_targets(db, user, body.targets),
                           strategy=body.strategy, created_by=user.id, updated_by=user.id)
        db.add(r)
        db.flush()
        after = _row(r, _RULE_FIELDS)
        _audit(db, user, entity="rule", entity_id=r.id, action="create", after=after)
    _bump(user.tenant_id)
    return after


@router.patch("/rules/{rule_id}")
def update_rule(rule_id: str, body: RulePatch, user=Depends(require_role(*TENANT_ADMIN))):
    changes = body.model_dump(exclude_unset=True)
    if changes.get("request_class") is not None and changes["request_class"] not in m.REQUEST_CLASSES:
        _err(422, "clase de pedido desconocida")
    if "strategy" in changes and changes["strategy"] not in resolver.STRATEGIES:
        _err(422, "estrategia desconocida")
    with _db(user) as db:
        r = _own(db, m.RedirectRule, rule_id, user)
        before = _row(r, _RULE_FIELDS)
        if "targets" in changes:
            changes["targets"] = _check_targets(db, user, changes["targets"])
        for k, v in changes.items():
            setattr(r, k, v)
        r.updated_by = user.id
        db.flush()
        after = _row(r, _RULE_FIELDS)
        _audit(db, user, entity="rule", entity_id=r.id, action="update", before=before, after=after)
    _bump(user.tenant_id)
    return after


@router.delete("/rules/{rule_id}", status_code=204)
def delete_rule(rule_id: str, user=Depends(require_role(*TENANT_ADMIN))):
    with _db(user) as db:
        r = _own(db, m.RedirectRule, rule_id, user)
        before = _row(r, _RULE_FIELDS)
        db.delete(r)
        _audit(db, user, entity="rule", entity_id=rule_id, action="delete", before=before)
    _bump(user.tenant_id)


# ── estado de política ────────────────────────────────────────────────────────

class PolicyIn(BaseModel):
    state: str
    reason: Optional[str] = Field(default=None, max_length=2000)


_POLICY_FIELDS = ("id", "scope_type", "scope_value", "state", "reason", "changed_at")


@router.get("/policy")
def list_policy(user=Depends(require_role(*READERS))):
    with _db(user) as db:
        rows = db.query(m.RedirectPolicy).filter(m.RedirectPolicy.tenant_id == user.tenant_id)
        return {"data": [_row(r, _POLICY_FIELDS) for r in rows]}


@router.put("/policy/{scope_type}/{scope_value}")
def put_policy(scope_type: str, scope_value: str, body: PolicyIn,
               user=Depends(require_role(*TENANT_ADMIN))):
    if body.state not in m.POLICY_STATES:
        _err(422, "estado desconocido")
    _scope_ok(scope_type, scope_value)
    with _db(user) as db:
        r = db.query(m.RedirectPolicy).filter_by(tenant_id=user.tenant_id, scope_type=scope_type,
                                                 scope_value=scope_value).first()
        before = _row(r, _POLICY_FIELDS) if r is not None else None
        if r is None:
            r = m.RedirectPolicy(id=uuid.uuid4(), tenant_id=user.tenant_id, scope_type=scope_type,
                                 scope_value=scope_value)
            db.add(r)
        r.state, r.reason, r.changed_by, r.changed_at = body.state, body.reason, user.id, _now()
        db.flush()
        after = _row(r, _POLICY_FIELDS)
        _audit(db, user, entity="policy", entity_id=r.id, action="put", before=before, after=after,
               reason=body.reason)
    _bump(user.tenant_id)
    return after


# ── posturas (FR-014a) ────────────────────────────────────────────────────────

class PostureIn(BaseModel):
    scope_type: str = "tenant"
    scope_value: str = "*"
    mode: str
    jurisdictions: List[str] = Field(default_factory=list)
    accept_foreign_entity: bool = False
    reason: str = Field(min_length=3, max_length=2000)


class PosturePatch(BaseModel):
    mode: Optional[str] = None
    jurisdictions: Optional[List[str]] = None
    accept_foreign_entity: Optional[bool] = None
    reason: str = Field(min_length=3, max_length=2000)


_POSTURE_FIELDS = ("id", "scope_type", "scope_value", "mode", "jurisdictions",
                   "accept_foreign_entity", "reason", "created_by_role", "created_at")


def _check_posture(mode, jurisdictions, accept_foreign, user):
    if mode is not None and mode not in m.POSTURE_MODES:
        _err(422, "modo de postura desconocido")
    if mode == "allowlist" and not jurisdictions:
        _err(422, "allowlist requiere jurisdicciones")
    if accept_foreign and not _manages_postures(user):
        _err(403, "aceptar entidades de otra jurisdicción es de cumplimiento o super_admin")


def _less_strict_error():
    _err(422, {"code": "posture_less_strict",
               "message": "Esa postura es menos estricta que la vigente; el administrador de empresa solo puede endurecer."})


def _candidate_scope(user, scope_type, scope_value) -> RequestScope:
    tenant = str(user.tenant_id)
    if scope_type == "connection":
        return RequestScope(tenant_id=tenant, connection_id=scope_value)
    if scope_type == "user":
        return RequestScope(tenant_id=tenant, user_id=scope_value)
    if scope_type == "group":
        return RequestScope(tenant_id=tenant, group_ids=(scope_value,))
    return RequestScope(tenant_id=tenant)


def _check_not_less_strict(db, user, body) -> None:
    """Una fila del admin de empresa menos estricta que la postura efectiva de su alcance se rechaza (FR-023, QA A8)."""
    rows = [{**_row(r, _POSTURE_FIELDS), "tenant_id": str(user.tenant_id)}
            for r in db.query(m.RedirectPosture).filter(m.RedirectPosture.tenant_id == user.tenant_id)]
    eff = residency.effective_posture(
        rows, _candidate_scope(user, body.scope_type, body.scope_value), redirected=True,
        tenant_region=residency.resolve_profile(), regions=_region_dicts(db, user))
    if residency.is_less_strict({"mode": body.mode, "jurisdictions": body.jurisdictions}, eff):
        _less_strict_error()


def _region_dicts(db, user) -> list:
    return list(region_dicts(db, user.tenant_id))


def _effective_view(eff) -> dict:
    return {"mode": eff.mode, "jurisdictions": sorted(eff.jurisdictions), "explicit": eff.explicit,
            "default_applied": eff.default_applied, "region_status": eff.region_status,
            "forced_everywhere": any(not h for h in eff.forcers),
            "scope_cap": None if eff.cap is None else sorted(eff.cap)}


@router.get("/postures")
def list_postures(region: Optional[str] = None, user=Depends(require_role(*READERS))):
    """Filas y postura efectiva del alcance tenant para tráfico redirigido (`region` = región
    del tenant; sin ella, la de la instalación)."""
    profile = residency.resolve_profile(region)             # la misma resolución que el tráfico (R28): sin caída a eu
    with _db(user) as db:
        rows = [_row(r, _POSTURE_FIELDS) for r in db.query(m.RedirectPosture).filter(
            m.RedirectPosture.tenant_id == user.tenant_id)]
        regions = _region_dicts(db, user)
    tenant_scope = RequestScope(tenant_id=str(user.tenant_id))
    eff = residency.effective_posture(
        [{**r, "tenant_id": str(user.tenant_id)} for r in rows if r["scope_type"] == "tenant"],
        tenant_scope, redirected=True, tenant_region=profile, regions=regions)
    return {"data": rows, "effective_tenant_redirected": _effective_view(eff)}


@router.post("/postures", status_code=201)
def create_posture(body: PostureIn, user=Depends(require_role("admin", "compliance_officer"))):
    """compliance_officer y super_admin escriben cualquier fila; tenant_admin solo AGREGA (con
    «más restrictiva gana», agregar nunca relaja) y no puede aceptar entidades ajenas."""
    _check_posture(body.mode, body.jurisdictions, body.accept_foreign_entity, user)
    _scope_ok(body.scope_type, body.scope_value)
    with _db(user) as db:
        if not _manages_postures(user):
            _check_not_less_strict(db, user, body)
        r = m.RedirectPosture(id=uuid.uuid4(), tenant_id=user.tenant_id, scope_type=body.scope_type,
                              scope_value=body.scope_value, mode=body.mode,
                              jurisdictions=[j.upper() for j in body.jurisdictions],
                              accept_foreign_entity=body.accept_foreign_entity, reason=body.reason,
                              created_by=user.id, created_by_role=_authority_label(user))
        db.add(r)
        db.flush()
        after = _row(r, _POSTURE_FIELDS)
        _audit(db, user, entity="posture", entity_id=r.id, action="create", after=after,
               reason=body.reason)
    _bump(user.tenant_id)
    return after


@router.patch("/postures/{posture_id}")
def update_posture(posture_id: str, body: PosturePatch,
                   user=Depends(require_role("admin", "compliance_officer"))):
    if not _manages_postures(user):
        _err(403, "editar posturas es de cumplimiento o del operador de la instalación")
    changes = body.model_dump(exclude_unset=True)
    reason = changes.pop("reason")
    with _db(user) as db:
        r = _own(db, m.RedirectPosture, posture_id, user)
        _check_posture(changes.get("mode", r.mode), changes.get("jurisdictions", r.jurisdictions),
                       changes.get("accept_foreign_entity", False), user)
        before = _row(r, _POSTURE_FIELDS)
        if "jurisdictions" in changes:
            changes["jurisdictions"] = [j.upper() for j in changes["jurisdictions"]]
        for k, v in changes.items():
            setattr(r, k, v)
        r.reason = reason
        r.created_by_role = _authority_label(user)
        db.flush()
        after = _row(r, _POSTURE_FIELDS)
        _audit(db, user, entity="posture", entity_id=r.id, action="update", before=before,
               after=after, reason=reason)
    _bump(user.tenant_id)
    return after


@router.delete("/postures/{posture_id}")
def delete_posture(posture_id: str, body: Reason,
                   user=Depends(require_role("admin", "compliance_officer"))):
    if not _manages_postures(user):
        _err(403, "borrar posturas es de cumplimiento o del operador de la instalación")
    with _db(user) as db:
        r = _own(db, m.RedirectPosture, posture_id, user)
        before = _row(r, _POSTURE_FIELDS)
        db.delete(r)
        _audit(db, user, entity="posture", entity_id=posture_id, action="delete", before=before,
               reason=body.reason)
    _bump(user.tenant_id)
    return {"deleted": posture_id}


# ── regiones del perfil (057 FR-021, FR-030, FR-031; contracts/admin-api.md; research R13, R23, R28, R30) ───────────
# Escribir regiones y `default_posture` es de cumplimiento (nivel empresa) o super-admin (nivel instalación), por rol
# REAL: `REDIRECT_OPERATOR_TENANT` no da esta autoridad. El admin de empresa solo lee.

_REGION_FIELDS = ("id", "level", "tenant_id", "name", "jurisdictions", "region_profiles", "default_posture",
                  "is_zone", "created_at", "updated_at")
_CODE_RE = __import__("re").compile(r"^[A-Z][A-Z0-9_-]{0,15}$")
_NAME_RE = __import__("re").compile(r"^[A-Z][A-Z0-9_-]{0,63}$")


def _jurisdictions(values) -> list:
    out = []
    for v in values or ():
        code = str(v or "").strip().upper()
        if not code:
            continue
        if not _CODE_RE.match(code):
            _err(422, f"jurisdicción inválida: {v!r}")
        if code not in out:
            out.append(code)
    if not out:
        _err(422, "la región necesita al menos una jurisdicción")
    return out


def _profiles(values) -> list:
    out = []
    for v in values or ():
        p = str(v or "").strip().lower()
        if p and p not in out:
            out.append(p)
    return out


def _check_region_fields(name=None, jurisdictions=None, default_posture=None):
    if name is not None and not _NAME_RE.match(name):
        _err(422, "el nombre de la región va en mayúsculas, sin espacios")
    if default_posture is not None and default_posture not in residency.DEFAULT_POSTURES:
        _err(422, "default_posture desconocido")


def _require_region_writer(user, level: str):
    """403 salvo super_admin (cualquier nivel) o compliance_officer (su empresa)."""
    real = _real_role(user)
    if real == "super_admin" or (real == "compliance_officer" and level == "tenant"):
        return real
    _err(403, "las regiones y la postura por defecto las cambia cumplimiento (su empresa) o el super_admin")


class RegionIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    level: str = "installation"
    jurisdictions: List[str] = Field(default_factory=list)
    region_profiles: List[str] = Field(default_factory=list)
    default_posture: str = "reject_offregion"
    is_zone: bool = False
    reason: str = Field(min_length=3, max_length=2000)


class RegionPatch(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=64)
    level: Optional[str] = None
    jurisdictions: Optional[List[str]] = None
    region_profiles: Optional[List[str]] = None
    default_posture: Optional[str] = None
    is_zone: Optional[bool] = None
    reason: str = Field(min_length=3, max_length=2000)


def _region_visible(db, user):
    return [r for r in db.query(m.RedirectRegion) if r.tenant_id is None or r.tenant_id == user.tenant_id]


def _region_conflict(db, user, level, tenant_id, name, profiles, *, exclude=None):
    for r in db.query(m.RedirectRegion):
        if exclude is not None and r.id == exclude:
            continue
        if r.level != level or r.tenant_id != tenant_id:
            continue
        if r.name == name:
            _err(409, "ya hay una región con ese nombre en ese nivel")
        taken = {str(p).strip().lower() for p in (r.region_profiles or ())} & set(profiles)
        if taken:
            _err(409, "un perfil de país ya resuelve a otra región en ese nivel")


@router.get("/regions")
def list_regions(user=Depends(require_role(*READERS))):
    with _db(user) as db:
        rows = sorted((_row(r, _REGION_FIELDS) for r in _region_visible(db, user)),
                      key=lambda r: (r["level"], r["name"]))
    return {"data": rows}


@router.get("/regions/effective")
def effective_region(user=Depends(require_role(*READERS))):
    """Región efectiva de quien pregunta (empresa > instalación > respaldo fijo) y su postura por defecto."""
    with _db(user) as db:
        rows = _region_dicts(db, user)
    region = residency.resolve_region(residency.resolve_profile(), rows, str(user.tenant_id))
    view = None
    if region.row_found:
        view = next((r for r in rows if r["name"] == region.name and r["level"] == region.level), None)
    return {"source": ("tenant" if region.level == "tenant" else "installation") if region.row_found
            else ("fallback" if region.profile else "unresolved"),
            "region": view, "jurisdictions": sorted(region.codes),
            "default_posture": region.default_posture or residency.CODE_FALLBACK, "health": region.status}


@router.post("/regions", status_code=201)
def create_region(body: RegionIn, user=Depends(require_role(*READERS))):
    if body.level not in m.LEVELS:
        _err(422, "nivel desconocido")
    _require_region_writer(user, body.level)
    _check_region_fields(body.name, None, body.default_posture)
    jurisdictions, profiles = _jurisdictions(body.jurisdictions), _profiles(body.region_profiles)
    tenant_id = None if body.level == "installation" else user.tenant_id
    with _db(user, bypass=body.level == "installation") as db:
        _region_conflict(db, user, body.level, tenant_id, body.name, profiles)
        r = m.RedirectRegion(id=uuid.uuid4(), level=body.level, tenant_id=tenant_id, name=body.name,
                             jurisdictions=jurisdictions, region_profiles=profiles,
                             default_posture=body.default_posture, is_zone=body.is_zone,
                             created_by=user.id, updated_by=user.id)
        db.add(r)
        db.flush()
        after = _row(r, _REGION_FIELDS)
        _audit(db, user, entity="region", entity_id=r.id, action="create", after=after, reason=body.reason,
               tenant_id=tenant_id)
    _bump_region(tenant_id)
    return after


def _own_region(db, user, region_id):
    r = db.get(m.RedirectRegion, _uuid(region_id, "región"))
    if r is None or (r.tenant_id is not None and r.tenant_id != user.tenant_id):
        _err(404, "inexistente")
    return r


@router.patch("/regions/{region_id}")
def update_region(region_id: str, body: RegionPatch, user=Depends(require_role(*READERS))):
    changes = body.model_dump(exclude_unset=True)
    reason = changes.pop("reason")
    if "level" in changes:
        _err(422, "el nivel de una región no se cambia")
    _check_region_fields(changes.get("name"), None, changes.get("default_posture"))
    with _db(user, bypass=True) as db:               # la fila de instalación la lee solo quien la puede escribir
        r = _own_region(db, user, region_id)
        _require_region_writer(user, r.level)
        before = _row(r, _REGION_FIELDS)
        if "jurisdictions" in changes:
            changes["jurisdictions"] = _jurisdictions(changes["jurisdictions"])
        if "region_profiles" in changes:
            changes["region_profiles"] = _profiles(changes["region_profiles"])
        if {"name", "region_profiles"} & set(changes):
            _region_conflict(db, user, r.level, r.tenant_id, changes.get("name", r.name),
                             changes.get("region_profiles", list(r.region_profiles or ())), exclude=r.id)
        for k, v in changes.items():
            setattr(r, k, v)
        r.updated_by = user.id
        db.flush()
        after = _row(r, _REGION_FIELDS)
        tenant_id = r.tenant_id
        _audit(db, user, entity="region", entity_id=r.id, action="update", before=before, after=after, reason=reason,
               tenant_id=tenant_id)
    _bump_region(tenant_id)
    return after


@router.delete("/regions/{region_id}")
def delete_region(region_id: str, body: Reason, user=Depends(require_role(*READERS))):
    with _db(user, bypass=True) as db:
        r = _own_region(db, user, region_id)
        _require_region_writer(user, r.level)
        profile = residency.resolve_profile()
        if r.level == "installation" and profile and profile in {str(p).strip().lower() for p in (r.region_profiles or ())}:
            _err(409, "es la región que resuelve el perfil de la instalación: cambiala o editala, no la borres")
        before = _row(r, _REGION_FIELDS)
        tenant_id = r.tenant_id
        db.delete(r)
        _audit(db, user, entity="region", entity_id=region_id, action="delete", before=before, reason=body.reason,
               tenant_id=tenant_id)
    _bump_region(tenant_id)
    return {"deleted": region_id}


@router.get("/health")
def region_health():
    """Estado de la región del perfil, sin sesión y sin datos de empresas (research R28): 200 si hay fila que la
    resuelva; 503 `region_unresolved` (sin perfil) o `region_row_missing` (sin fila: rige el respaldo en código)."""
    from fastapi.responses import JSONResponse
    profile = residency.resolve_profile()
    if profile is None:
        reason = residency.STATUS_UNRESOLVED
    else:
        try:
            from src.database import tenant_context
            with tenant_context(None, bypass=True):
                db = _session_factory()()
                try:
                    rows = [{"tenant_id": None, "name": r.name, "jurisdictions": list(r.jurisdictions or ()),
                             "region_profiles": list(r.region_profiles or ()), "default_posture": r.default_posture,
                             "is_zone": bool(r.is_zone), "level": r.level}
                            for r in db.query(m.RedirectRegion)]
                finally:
                    db.close()
            reason = residency.resolve_region(profile, rows, None).status
        except Exception:  # noqa: BLE001 — sin la tabla (migración sin aplicar) rige el respaldo
            reason = residency.STATUS_ROW_MISSING
    if reason == residency.STATUS_OK:
        return {"status": "ok"}
    return JSONResponse(status_code=503, content={"status": "degraded", "reason": reason})


# ── relajaciones del enmascarado forzado por destino (057 FR-031a; research R24) ───────────────────────────────

_RELAX_FIELDS = ("id", "level", "tenant_id", "entry_id", "reason", "created_by", "created_by_role", "revoked_at",
                 "revoked_by", "revoke_reason", "created_at")


class RelaxationIn(BaseModel):
    entry_id: str
    level: str = "tenant"
    reason: str = Field(min_length=3, max_length=2000)


class RevokeIn(BaseModel):
    reason: str = Field(min_length=3, max_length=2000)


def _relaxation_writer(user, level: str):
    real = _real_role(user)
    if real == "super_admin" or (real == "compliance_officer" and level == "tenant"):
        return real
    _err(403, "las relajaciones del enmascarado las crea cumplimiento (su empresa) o el super_admin")


@router.get("/masking-relaxations")
def list_relaxations(user=Depends(require_role(*READERS))):
    from sentinel.catalog import models as cm
    with _db(user) as db:
        rows = [r for r in db.query(m.RedirectMaskingRelaxation)
                if r.tenant_id is None or r.tenant_id == user.tenant_id]
        try:
            from sentinel.catalog.store import visible_entries
            names = {e.id: e.name for e in visible_entries(db, user.tenant_id, operator=False, include_archived=True)}
        except Exception:  # noqa: BLE001
            names = {}
        data = []
        for r in sorted(rows, key=lambda r: r.created_at or _now(), reverse=True):
            row = _row(r, _RELAX_FIELDS)
            row["entry_name"] = names.get(r.entry_id)
            data.append(row)
    return {"data": data}


@router.post("/masking-relaxations", status_code=201)
def create_relaxation(body: RelaxationIn, user=Depends(require_role(*READERS))):
    if body.level not in m.LEVELS:
        _err(422, "nivel desconocido")
    real = _relaxation_writer(user, body.level)
    entry_id = _uuid(body.entry_id, "destino")
    from sentinel.catalog import models as cm
    from sentinel.catalog.relaxation import unmet_preconditions
    from sentinel.catalog.store import visible_entries
    tenant_id = None if body.level == "installation" else user.tenant_id
    with _db(user, bypass=body.level == "installation") as db:
        visibles = {e.id: e for e in visible_entries(db, user.tenant_id, operator=body.level == "installation")}
        entry = visibles.get(entry_id)
        if entry is None:
            _err(404, "destino inexistente")
        if body.level == "installation" and entry.tenant_id is not None:
            _err(422, "una relajación de instalación es sobre una entrada de instalación")
        unmet = unmet_preconditions(entry, db.get(cm.ComplianceSheet, entry.id))
        if unmet:
            _err(422, {"code": "relaxation_preconditions", "motivo": unmet,
                       "message": "La ficha del destino no cumple las condiciones para relajar el enmascarado."})
        vigente = db.query(m.RedirectMaskingRelaxation).filter(
            m.RedirectMaskingRelaxation.entry_id == entry.id, m.RedirectMaskingRelaxation.level == body.level,
            m.RedirectMaskingRelaxation.revoked_at.is_(None)).all()
        if any(r.tenant_id == tenant_id for r in vigente):
            _err(409, "ya hay una relajación vigente para ese destino")
        r = m.RedirectMaskingRelaxation(id=uuid.uuid4(), level=body.level, tenant_id=tenant_id, entry_id=entry.id,
                                        reason=body.reason, created_by=user.id, created_by_role=real)
        db.add(r)
        db.flush()
        after = _row(r, _RELAX_FIELDS)
        _audit(db, user, entity="masking_relaxation", entity_id=r.id, action="create",
               after={"entry_id": after["entry_id"], "level": body.level}, reason=body.reason, tenant_id=tenant_id)
    _bump(tenant_id)
    return after


@router.delete("/masking-relaxations/{relaxation_id}")
def revoke_relaxation(relaxation_id: str, body: RevokeIn, user=Depends(require_role(*READERS))):
    with _db(user, bypass=True) as db:
        r = db.get(m.RedirectMaskingRelaxation, _uuid(relaxation_id, "relajación"))
        if r is None or (r.tenant_id is not None and r.tenant_id != user.tenant_id):
            _err(404, "inexistente")
        _relaxation_writer(user, r.level)
        if r.revoked_at is not None:
            _err(409, "la relajación ya está revocada")
        r.revoked_at, r.revoked_by, r.revoke_reason = _now(), user.id, body.reason
        db.flush()
        after = _row(r, _RELAX_FIELDS)
        _audit(db, user, entity="masking_relaxation", entity_id=r.id, action="revoke",
               before={"entry_id": after["entry_id"], "level": r.level}, reason=body.reason, tenant_id=r.tenant_id)
        tenant_id = r.tenant_id
    _bump(tenant_id)
    return after


# ── vista previa de resolución ────────────────────────────────────────────────

class PreviewIn(BaseModel):
    face: str
    public_id: str
    request_class: Optional[str] = None
    connection_id: Optional[str] = None
    user_id: Optional[str] = None
    group_ids: List[str] = Field(default_factory=list)
    tenant_region: Optional[str] = None


@router.get("/capabilities")
def capabilities(user=Depends(require_role(*READERS))):
    """Qué puede operar la sesión (la pantalla decide qué muestra; la API manda igual)."""
    return {"operator": _is_super(user), "manages_regions": _real_role(user) is not None}


@router.post("/resolve-preview")
def resolve_preview(body: PreviewIn, user=Depends(require_role(*READERS))):
    """Misma función que el plano de datos, sobre las filas del tenant de la sesión."""
    if body.face not in m.FACES:
        _err(422, "cara desconocida")
    with _db(user) as db:
        snap = load_from_session(db, str(user.tenant_id))
    scope = RequestScope(tenant_id=str(user.tenant_id), connection_id=body.connection_id,
                         user_id=body.user_id, group_ids=tuple(body.group_ids))
    try:
        state = resolver.effective_state(snap.policy, scope)
        posture = residency.effective_posture(snap.postures, scope, redirected=True,
                                              tenant_region=residency.resolve_profile(body.tenant_region),
                                              regions=snap.regions, relaxations=snap.relaxations)
    except ValueError as exc:
        _err(409, f"configuración inválida: {exc}")
    # Perfil de acceso (069 US2): la vista previa usa los mismos permitidos que el plano de datos.
    ident = {"tenant_id": str(user.tenant_id), "user_id": body.user_id,
             "group_id": body.group_ids[0] if body.group_ids else None, "api_key_id": body.connection_id}
    try:
        permitidos, _ = bridge.allowed_for_ident(ident)
    except Exception:  # noqa: BLE001
        _err(503, "no se pudieron resolver los modelos permitidos")
    res = resolver.resolve(scope=scope, face=body.face, public_id=body.public_id,
                           request_class=body.request_class, published_rows=snap.published,
                           rules=snap.rules, destinations=snap.destinations, offers=snap.offers,
                           posture=posture, permitidos=permitidos)
    out: dict[str, Any] = {"state": state, "posture": {"mode": posture.mode,
                                                       "jurisdictions": sorted(posture.jurisdictions),
                                                       "default_applied": posture.default_applied},
                           "permitidos_origen": "perfil" if permitidos is not None else None}
    if isinstance(res, resolver.Resolved):
        out.update(result="resolved", destination_id=res.destination["id"],
                   destination_name=res.destination.get("name"), engine_model=res.engine_model,
                   fidelity=res.fidelity, rule_id=res.rule_id, forced_masking=res.forced_masking,
                   substitution_reason=res.substitution_reason, strategy=res.strategy,
                   skipped=[{"destination_id": d, "reason": r} for d, r in res.skipped])
    else:
        out.update(result="unavailable", kind=res.kind, error_class=res.error_class,
                   skipped=[{"destination_id": d, "reason": r} for d, r in res.skipped])
    return out
