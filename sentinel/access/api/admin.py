"""API `/api/v1/access/*` — perfiles de acceso por riesgo (069 US2; contracts/admin-perfiles.md; T049).

- Roles: `admin` escribe perfiles `company` y `key`, asignaciones y perfil de llave;
  `compliance_officer` escribe los techos (perfiles `ceiling`); admin, cumplimiento y lectura leen.
- El tenant es SIEMPRE el de la sesión (RLS + filtro explícito); un id ajeno es 404.
- Toda escritura deja fila de auditoría (`_audit` del catálogo) y sube la versión de la instantánea
  (`bump`): los demás planos ven el cambio sin reemitir llaves (FR-014).
- Nada falla por «habilitar de más»: el efectivo siempre recorta (FR-012b); la API advierte.
"""
from __future__ import annotations

import contextlib
import hashlib
import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from src.auth.rbac import effective_roles, require_role

from sentinel.catalog.api.admin import _audit
from sentinel.catalog.models import CAPABILITIES, PROVIDERS
from sentinel.catalog.semaforo import ESTADOS

from .. import models as am
from .. import runtime as rt
from .. import snapshot as snap
from ..resolver import (PermitidosNoResueltos, Profile, Rule, evaluate_profile, modelos_permitidos)

router = APIRouter(prefix="/access", tags=["access"])

ADMIN = ("admin",)
CUMPLIMIENTO = ("compliance_officer",)
READERS = ("admin", "compliance_officer", "lectura")
WRITERS = ("admin", "compliance_officer")
WRITER_OF = {"company": "admin", "key": "admin", "ceiling": "compliance_officer"}
MAX_RULES = 100

# Inyectables para tests (sin Postgres ni tablas de la base).
SESSION_FACTORY = None
ACTOR = None             # (db, tenant, user, group, key) -> dict(user_id, group_id, key_id, user_risk, key_risk)
SUBJECT_EXISTS = None    # (db, tenant, subject_type, subject_id) -> bool
KEY_EXISTS = None        # (db, tenant, key_id) -> bool


# ── infraestructura ───────────────────────────────────────────────────────────

def _err(code: int, msg):
    raise HTTPException(code, msg)


def _uuid(value, what="id") -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        raise HTTPException(404, f"{what} inexistente") from None


@contextlib.contextmanager
def _db(user, *, seed=True):
    from src.database import tenant_context
    factory = SESSION_FACTORY or rt.SESSION_FACTORY
    if factory is None:
        from src.database import SessionLocal as factory
    with tenant_context(user.tenant_id):
        db = factory()
        try:
            db.info["dirty"] = False
            if seed and snap.ensure_seed(db, user.tenant_id, getattr(user, "id", None)):
                db.info["dirty"] = True
            yield db
            db.commit()
            if db.info.get("dirty"):
                rt.bump(user.tenant_id)
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()


def _touch(db):
    db.info["dirty"] = True


def _can_write(user, kind: str):
    if WRITER_OF[kind] not in effective_roles(user):
        _err(403, f"Acción no permitida para el rol '{user.role}': los perfiles «{kind}» los escribe "
                  f"{'el administrador' if WRITER_OF[kind] == 'admin' else 'cumplimiento'}.")


def _entries(user) -> list:
    return rt.catalog_entries(user.tenant_id)


# ── cuerpos ───────────────────────────────────────────────────────────────────

class RuleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    effect: str
    selector: str
    value: str


class ProfileIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: str
    name: str
    rules: List[RuleIn] = Field(default_factory=list)


class ProfilePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Optional[str] = None
    rules: Optional[List[RuleIn]] = None


class ArchiveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str


class CeilingsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    minimal: Optional[str] = None
    limited: Optional[str] = None
    high_risk_annex1: Optional[str] = None
    high_risk_annex3: Optional[str] = None


class AssignIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    profiles: List[str]
    confirm_empty: bool = False


class KeyProfileIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    profile_id: Optional[str] = None


class PreviewIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user: Optional[str] = None
    group: Optional[str] = None
    key: Optional[str] = None
    model: str


# ── validación ────────────────────────────────────────────────────────────────

def _clean_name(name: str) -> str:
    n = (name or "").strip()
    if not n or len(n) > 128:
        _err(422, "el nombre es obligatorio (hasta 128 caracteres)")
    return n


def _clean_rules(rules: List[RuleIn]) -> list:
    if len(rules) > MAX_RULES:
        _err(422, f"hasta {MAX_RULES} reglas por perfil")
    out = []
    for r in rules:
        if r.effect not in am.EFFECTS:
            _err(422, f"efecto inválido: {r.effect!r} (uno de {', '.join(am.EFFECTS)})")
        if r.selector not in am.SELECTORS:
            _err(422, f"selector inválido: {r.selector!r} (uno de {', '.join(am.SELECTORS)})")
        v = (r.value or "").strip()
        if not v or len(v) > 256:
            _err(422, "el valor de la regla es obligatorio")
        if r.selector == "semaforo" and v not in ESTADOS:
            _err(422, f"semáforo inválido: {v!r} (uno de {', '.join(ESTADOS)})")
        if r.selector == "capacidad" and v not in CAPABILITIES:
            _err(422, f"capacidad inválida: {v!r} (una de {', '.join(CAPABILITIES)})")
        if r.selector == "proveedor" and v not in PROVIDERS:
            _err(422, f"proveedor inválido: {v!r}")
        if r.selector == "jurisdiccion":
            v = v.upper()
            if not v.replace("_", "").isalnum() or len(v) > 16:
                _err(422, f"jurisdicción inválida: {v!r}")
        out.append((r.effect, r.selector, v))
    return out


def _rules_of(db, pid) -> list:
    rows = (db.query(am.AccessProfileRule).filter_by(profile_id=pid)
            .order_by(am.AccessProfileRule.position).all())
    return [{"effect": r.effect, "selector": r.selector, "value": r.value} for r in rows]


def _as_profile(p: am.AccessProfile, rules: list) -> Profile:
    return Profile(str(p.id), p.kind, p.name, tuple(Rule(**r) for r in rules))


def _view(db, user, p: am.AccessProfile, entries=None) -> dict:
    rules = _rules_of(db, p.id)
    entries = _entries(user) if entries is None else entries
    return {"id": str(p.id), "kind": p.kind, "name": p.name, "rules": rules,
            "archived": p.archived_at is not None, "seeded": bool(p.seeded),
            "allows": len(evaluate_profile(_as_profile(p, rules), entries)), "version": p.version}


def _load(db, user, pid, *, kind=None, live=False) -> am.AccessProfile:
    p = db.get(am.AccessProfile, _uuid(pid, "perfil"))
    if p is None or p.tenant_id != uuid.UUID(str(user.tenant_id)):
        _err(404, "perfil inexistente")
    if kind and p.kind != kind:
        _err(422, f"el perfil «{p.name}» no es de tipo {kind}")
    if live and p.archived_at is not None:
        _err(422, f"el perfil «{p.name}» está archivado")
    return p


def _set_rules(db, p, rules: list):
    db.query(am.AccessProfileRule).filter_by(profile_id=p.id).delete()
    for i, (effect, selector, value) in enumerate(rules):
        db.add(am.AccessProfileRule(profile_id=p.id, position=i, effect=effect, selector=selector,
                                    value=value))


def _usage(db, p) -> list:
    """Sujetos que usan el perfil (asignaciones, techos, llaves)."""
    out = [{"subject_type": a.subject_type, "subject_id": str(a.subject_id)}
           for a in db.query(am.AccessAssignment).filter_by(profile_id=p.id).all()]
    out += [{"subject_type": "ceiling", "subject_id": c.risk_level}
            for c in db.query(am.AiActCeiling).filter_by(profile_id=p.id).all()]
    out += [{"subject_type": "key", "subject_id": str(k.api_key_id)}
            for k in db.query(am.AccessKeyProfile).filter_by(profile_id=p.id).all()]
    return out


# ── perfiles ──────────────────────────────────────────────────────────────────

@router.get("/profiles")
def list_profiles(include_archived: bool = Query(False), user=Depends(require_role(*READERS))):
    with _db(user) as db:
        q = db.query(am.AccessProfile).filter_by(tenant_id=uuid.UUID(str(user.tenant_id)))
        if not include_archived:
            q = q.filter(am.AccessProfile.archived_at.is_(None))
        entries = _entries(user)
        return {"data": [_view(db, user, p, entries)
                         for p in q.order_by(am.AccessProfile.kind, am.AccessProfile.name).all()]}


def _check_unique(db, user, kind, name, *, except_id=None):
    q = db.query(am.AccessProfile).filter_by(tenant_id=uuid.UUID(str(user.tenant_id)), kind=kind,
                                             name=name).filter(am.AccessProfile.archived_at.is_(None))
    if except_id is not None:
        q = q.filter(am.AccessProfile.id != except_id)
    if q.first() is not None:
        _err(409, f"ya existe un perfil «{name}» de tipo {kind}")


@router.post("/profiles", status_code=201)
def create_profile(body: ProfileIn, user=Depends(require_role(*WRITERS))):
    if body.kind not in am.KINDS:
        _err(422, f"tipo inválido: {body.kind!r} (uno de {', '.join(am.KINDS)})")
    _can_write(user, body.kind)
    name, rules = _clean_name(body.name), _clean_rules(body.rules)
    with _db(user) as db:
        _check_unique(db, user, body.kind, name)
        p = am.AccessProfile(id=uuid.uuid4(), tenant_id=uuid.UUID(str(user.tenant_id)), kind=body.kind,
                             name=name, seeded=False, version=1, created_by=user.id, updated_by=user.id)
        db.add(p)
        db.flush()
        _set_rules(db, p, rules)
        db.flush()
        view = _view(db, user, p)
        _audit(db, user, entity="access_profile", entity_id=p.id, action="create", after=view)
        _touch(db)
        return view


@router.patch("/profiles/{profile_id}")
def update_profile(profile_id: str, body: ProfilePatch, user=Depends(require_role(*WRITERS))):
    with _db(user) as db:
        p = _load(db, user, profile_id)
        _can_write(user, p.kind)
        if p.archived_at is not None:
            _err(409, "perfil archivado: crear uno nuevo")
        before = _view(db, user, p)
        ch = body.model_dump(exclude_unset=True)
        if ch.get("name") is not None:
            name = _clean_name(ch["name"])
            _check_unique(db, user, p.kind, name, except_id=p.id)
            p.name = name
        if ch.get("rules") is not None:
            _set_rules(db, p, _clean_rules(body.rules))
        p.version = (p.version or 1) + 1
        p.updated_by = user.id
        db.flush()
        after = _view(db, user, p)
        _audit(db, user, entity="access_profile", entity_id=p.id, action="update", before=before,
               after=after)
        _touch(db)
        return after


@router.post("/profiles/{profile_id}/archive")
def archive_profile(profile_id: str, body: ArchiveIn, user=Depends(require_role(*WRITERS))):
    reason = (body.reason or "").strip()
    if len(reason) < 3:
        _err(422, "el motivo es obligatorio (al menos 3 caracteres)")
    with _db(user) as db:
        p = _load(db, user, profile_id)
        _can_write(user, p.kind)
        if p.archived_at is not None:
            _err(409, "el perfil ya está archivado")
        usage = _usage(db, p)
        if usage:
            return JSONResponse(status_code=409, content={
                "detail": "el perfil está en uso: desasignarlo antes de archivarlo", "subjects": usage})
        before = _view(db, user, p)
        from sqlalchemy import func
        p.archived_at, p.archived_reason, p.updated_by = func.now(), reason, user.id
        db.flush()
        db.refresh(p)
        _audit(db, user, entity="access_profile", entity_id=p.id, action="archive", before=before,
               after=_view(db, user, p), reason=reason)
        _touch(db)
        return _view(db, user, p)


# ── techos ────────────────────────────────────────────────────────────────────

def _ceilings(db, user) -> dict:
    out = {lvl: None for lvl in am.RISK_LEVELS}
    for c in db.query(am.AiActCeiling).filter_by(tenant_id=uuid.UUID(str(user.tenant_id))).all():
        out[c.risk_level] = str(c.profile_id)
    return out


@router.get("/ceilings")
def get_ceilings(user=Depends(require_role(*READERS))):
    with _db(user) as db:
        return {"data": _ceilings(db, user)}


@router.put("/ceilings")
def put_ceilings(body: CeilingsIn, user=Depends(require_role(*CUMPLIMIENTO))):
    changes = body.model_dump(exclude_unset=True)
    with _db(user) as db:
        before = _ceilings(db, user)
        tid = uuid.UUID(str(user.tenant_id))
        for level, pid in changes.items():
            db.query(am.AiActCeiling).filter_by(tenant_id=tid, risk_level=level).delete()
            if pid is not None:
                p = _load(db, user, pid, kind="ceiling", live=True)
                db.add(am.AiActCeiling(tenant_id=tid, risk_level=level, profile_id=p.id))
        db.flush()
        after = _ceilings(db, user)
        _audit(db, user, entity="access_ceiling", entity_id=str(tid), action="update", before=before,
               after=after)
        _touch(db)
        return {"data": after}


# ── asignaciones ──────────────────────────────────────────────────────────────

def _subject(db, user, subject_type: str, subject_id: str) -> uuid.UUID:
    if subject_type not in am.SUBJECT_TYPES:
        _err(404, "tipo de sujeto inexistente")
    if subject_type == "tenant" and subject_id == "*":      # «*» = la organización de la sesión
        return uuid.UUID(str(user.tenant_id))
    sid = _uuid(subject_id, "sujeto")
    if subject_type == "tenant":
        if sid != uuid.UUID(str(user.tenant_id)):
            _err(404, "sujeto inexistente")
    elif not (SUBJECT_EXISTS or _default_subject_exists)(db, user.tenant_id, subject_type, sid):
        _err(404, "sujeto inexistente")
    return sid


def _default_subject_exists(db, tenant, subject_type, sid) -> bool:
    from src.models.user import Group, User
    row = db.get(User if subject_type == "user" else Group, sid)
    return row is not None and str(row.tenant_id) == str(tenant)


def _assigned(db, user, subject_type, sid) -> list:
    rows = db.query(am.AccessAssignment).filter_by(tenant_id=uuid.UUID(str(user.tenant_id)),
                                                   subject_type=subject_type, subject_id=sid).all()
    return sorted(str(r.profile_id) for r in rows)


@router.get("/assignments/{subject_type}/{subject_id}")
def get_assignment(subject_type: str, subject_id: str, user=Depends(require_role(*READERS))):
    with _db(user) as db:
        sid = _subject(db, user, subject_type, subject_id)
        return {"subject_type": subject_type, "subject_id": subject_id,
                "profiles": _assigned(db, user, subject_type, sid)}


@router.put("/assignments/{subject_type}/{subject_id}")
def put_assignment(subject_type: str, subject_id: str, body: AssignIn,
                   user=Depends(require_role(*ADMIN))):
    with _db(user) as db:
        sid = _subject(db, user, subject_type, subject_id)
        profs = [_load(db, user, pid, kind="company", live=True) for pid in dict.fromkeys(body.profiles)]
        entries = _entries(user)
        if profs and entries and not body.confirm_empty:
            union = set()
            for p in profs:
                union |= evaluate_profile(_as_profile(p, _rules_of(db, p.id)), entries)
            if not union:
                return JSONResponse(status_code=422, content={
                    "detail": "con estos perfiles el sujeto quedaría SIN modelos; confirmá para continuar",
                    "empty": True})
        before = _assigned(db, user, subject_type, sid)
        tid = uuid.UUID(str(user.tenant_id))
        db.query(am.AccessAssignment).filter_by(tenant_id=tid, subject_type=subject_type,
                                                subject_id=sid).delete()
        for p in profs:
            db.add(am.AccessAssignment(id=uuid.uuid4(), tenant_id=tid, profile_id=p.id,
                                       subject_type=subject_type, subject_id=sid))
        db.flush()
        after = sorted(str(p.id) for p in profs)
        _audit(db, user, entity="access_assignment", entity_id=f"{subject_type}:{sid}", action="update",
               before={"profiles": before}, after={"profiles": after})
        _touch(db)
        return {"subject_type": subject_type, "subject_id": subject_id, "profiles": after}


# ── actor, efectivo y vista previa ────────────────────────────────────────────

def _actor(db, user, user_id, group_id, key_id) -> dict:
    tenant = user.tenant_id
    for v in (user_id, group_id, key_id):
        if v is not None:
            _uuid(v, "sujeto")
    if ACTOR is not None:
        return ACTOR(db, tenant, user_id, group_id, key_id)
    return _default_actor(db, tenant, user_id, group_id, key_id)


def _default_actor(db, tenant, user_id, group_id, key_id) -> dict:
    from src.models.budget import APIKey
    k = None
    if key_id is not None:
        k = db.get(APIKey, uuid.UUID(str(key_id)))
        if k is None or str(k.tenant_id) != str(tenant):
            _err(404, "llave inexistente")
        user_id = user_id or (str(k.user_id) if k.user_id else None)
        group_id = group_id or (str(k.group_id) if k.group_id else None)
    from src.models.user import Group, User
    for model, ident in ((User, user_id), (Group, group_id)):
        if ident is not None:
            row = db.get(model, uuid.UUID(str(ident)))
            if row is None or str(row.tenant_id) != str(tenant):
                _err(404, "sujeto inexistente")
    u = db.get(User, uuid.UUID(str(user_id))) if user_id else None
    if group_id is None and u is not None and u.group_id:
        group_id = str(u.group_id)
    ur, kr = rt.effective_risk(db, key=k, user=u, group=group_id, tenant=tenant)
    return {"user_id": user_id, "group_id": group_id, "key_id": key_id, "user_risk": ur, "key_risk": kr}


def _resolve_for(db, user, actor: dict, *, key_profile=True):
    snapshot = snap.load(db, user.tenant_id)      # lectura fresca: la pantalla muestra la verdad
    if not key_profile:
        from copy import copy
        snapshot = copy(snapshot)
        snapshot.key_profiles = {}
    return modelos_permitidos(snapshot, _entries(user), user_id=actor.get("user_id"),
                              group_id=actor.get("group_id"), key_id=actor.get("key_id"),
                              user_risk=actor.get("user_risk"), key_risk=actor.get("key_risk"))


def _origen(res) -> dict:
    return {"restringe": res.restringe, "techo": res.techo, "perfiles": list(res.perfiles),
            "llave": res.llave}


def _version(tenant) -> str:
    return hashlib.sha256(repr((str(tenant), rt.access_version().current(str(tenant)))).encode()
                          ).hexdigest()[:16]


def _resolve_or_503(fn):
    try:
        return fn()
    except PermitidosNoResueltos as e:
        raise HTTPException(503, f"no se pudo resolver el acceso: {e}") from e


@router.get("/effective")
def effective(user_: Optional[str] = Query(None, alias="user"), group: Optional[str] = Query(None),
              key: Optional[str] = Query(None), user=Depends(require_role(*WRITERS))):
    with _db(user) as db:
        actor = _actor(db, user, user_, group, key)
        res = _resolve_or_503(lambda: _resolve_for(db, user, actor))
        entries = _entries(user)
        shown = [e for e in entries if e["public_id"] in res.ids]
        return {"permitidos": [{"id": e["id"], "public_id": e["public_id"], "name": e["name"],
                                "provider": e["provider"], "semaforo": e["semaforo"]} for e in shown],
                "restringe": res.restringe, "techo": res.techo, "perfiles": list(res.perfiles),
                "llave": {"profile_id": res.llave["profile_id"]}, "version": _version(user.tenant_id)}


@router.post("/preview")
def preview(body: PreviewIn, user=Depends(require_role(*WRITERS))):
    with _db(user) as db:
        actor = _actor(db, user, body.user, body.group, body.key)
        if body.model not in {e["public_id"] for e in _entries(user)}:
            _err(404, "modelo inexistente en el catálogo")
        res = _resolve_or_503(lambda: _resolve_for(db, user, actor))
        ok = body.model in res.ids
        return {"allowed": ok, "motivo": None if ok else "profile_not_allowed",
                "permitidos_origen": _origen(res) | {"version": _version(user.tenant_id)}}


# ── perfil de llave ───────────────────────────────────────────────────────────

def _key_exists(db, user, key_id) -> bool:
    if KEY_EXISTS is not None:
        return KEY_EXISTS(db, user.tenant_id, key_id)
    from src.models.budget import APIKey
    k = db.get(APIKey, key_id)
    return k is not None and str(k.tenant_id) == str(user.tenant_id)


def _key_view(db, user, kid, warnings=None):
    row = db.get(am.AccessKeyProfile, kid)
    own = row is not None and row.tenant_id == uuid.UUID(str(user.tenant_id))
    out = {"key_id": str(kid), "profile_id": str(row.profile_id) if own else None}
    if warnings is not None:
        out["warnings"] = warnings
    return out


@router.get("/keys/{key_id}/profile")
def get_key_profile(key_id: str, user=Depends(require_role(*READERS))):
    with _db(user) as db:
        kid = _uuid(key_id, "llave")
        if not _key_exists(db, user, kid):
            _err(404, "llave inexistente")
        return _key_view(db, user, kid)


@router.put("/keys/{key_id}/profile")
def put_key_profile(key_id: str, body: KeyProfileIn, user=Depends(require_role(*ADMIN))):
    with _db(user) as db:
        kid = _uuid(key_id, "llave")
        if not _key_exists(db, user, kid):
            _err(404, "llave inexistente")
        tid = uuid.UUID(str(user.tenant_id))
        before = _key_view(db, user, kid)
        db.query(am.AccessKeyProfile).filter_by(api_key_id=kid, tenant_id=tid).delete()
        warnings: list = []
        if body.profile_id is not None:
            p = _load(db, user, body.profile_id, kind="key", live=True)
            db.add(am.AccessKeyProfile(api_key_id=kid, tenant_id=tid, profile_id=p.id,
                                       updated_by=user.id))
            entries = _entries(user)
            asked = evaluate_profile(_as_profile(p, _rules_of(db, p.id)), entries)
            # el efectivo del dueño SIN el perfil de la llave: lo que el perfil pida de más, se recorta
            owner = _actor(db, user, None, None, str(kid))
            base = _resolve_for(db, user, owner, key_profile=False)
            extra = sorted(asked - base.ids)
            if extra:
                warnings.append(
                    f"el perfil de la llave incluye {len(extra)} modelo(s) que su dueño no tiene "
                    f"permitidos ({', '.join(extra[:5])}{'…' if len(extra) > 5 else ''}): la llave solo "
                    f"achica, el efectivo los recorta")
        db.flush()
        after = _key_view(db, user, kid)
        _audit(db, user, entity="access_key_profile", entity_id=kid, action="update", before=before,
               after=after)
        _touch(db)
        return after | {"warnings": warnings}
