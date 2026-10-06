"""Modelos heredados del config del motor y su adopción al catálogo (069; etapa previa a T136).

Hasta la etapa de «fuente única» la pantalla de siempre administra `config.yaml`. Estas rutas
**solo leen** ese config (con las funciones de la base, importadas perezosamente), listan lo que
todavía no está en el catálogo y lo adoptan: crean la entrada `source='migrated_yaml'` con su
credencial cifrada (o referencia a variable) y NO tocan el archivo: el motor sigue sirviéndolo desde
ahí.

- Nunca se devuelve un valor de `api_key`, ni siquiera el nombre de la variable referenciada.
- Las entradas de plugin (`plugin_owner`, prefijo `rdx-`) no existen para esta pantalla.
- El config es de la instalación: lo ve entero el operador; el administrador de una organización ve
  solo los modelos locales (sin credencial) y los adopta como entradas de SU organización.
- Un `env_ref` adoptado admite cualquier nombre fuera de la lista negra (`credentials.ENV_DENYLIST`),
  pero el motor solo resuelve `REDIRECT_CRED_*`: ver el TODO de `credentials.env_ref_dict`.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from src.auth.rbac import require_role

from sentinel.redirect import credentials as rc
from sentinel.redirect.api.admin import _is_super

from .. import credentials as cr
from .. import models as cm
from .. import store as cs
from . import admin as _a

router = APIRouter(prefix="/catalog", tags=["catalog"])

CONFIG_LOADER = None        # inyectable para tests: () -> dict del config del motor
ENV_REF_PREFIX = "os.environ/"
_PROVIDER_ALIASES = {"ollama_chat": "ollama"}


def _config() -> dict:
    if CONFIG_LOADER is not None:
        return CONFIG_LOADER() or {}
    from src.api.chat import _read_engine_config
    return _read_engine_config()


def _chat():
    from src.api import chat
    return chat


def _visible(config: dict) -> list:
    out = []
    for m in _chat()._visible_entries(config):
        name = m.get("model_name")
        if isinstance(name, str) and name and not name.startswith("rdx-"):
            out.append(m)
    return out


def _split(entry: dict):
    full = (entry.get("litellm_params") or {}).get("model") or ""
    if isinstance(full, str) and "/" in full:
        prefix, model = full.split("/", 1)
        return _PROVIDER_ALIASES.get(prefix, prefix), model
    return None, full if isinstance(full, str) else ""


def _credential_ref(entry: dict):
    key = (entry.get("litellm_params") or {}).get("api_key")
    if not isinstance(key, str) or not key:
        return None
    return "env" if key.startswith(ENV_REF_PREFIX) else "literal"


def _fallback_of(config: dict, name: str):
    for item in ((config.get("router_settings") or {}).get("fallbacks") or []):
        if isinstance(item, dict) and name in item:
            dest = item[name]
            return dest[0] if isinstance(dest, list) and dest else (dest or None)
    return None


def _adopted_names(db, user) -> set:
    tenant = None if _is_super(user) else user.tenant_id
    return {e.public_id for e in db.query(cm.CatalogEntry).filter(
        cm.CatalogEntry.tenant_id == tenant, cm.CatalogEntry.status != "archived")}


def _allowed(user, entry: dict) -> bool:
    return _is_super(user) or (_chat()._is_local_entry(entry) and _credential_ref(entry) is None)


def _view(config: dict, entry: dict, adopted: set) -> dict:
    provider, model_id = _split(entry)
    info = entry.get("model_info") or {}
    params = entry.get("litellm_params") or {}
    ref = _credential_ref(entry)
    name = entry["model_name"]
    return {"model_name": name, "provider": provider, "model_id": model_id,
            "api_base": params.get("api_base"), "has_credential": ref is not None,
            "credential_ref": ref, "is_local": bool(_chat()._is_local_entry(entry)),
            "fallback": _fallback_of(config, name),
            "max_output_tokens": info.get("max_output_tokens"), "adopted": name in adopted}


@router.get("/legacy-models")
def list_legacy(user=Depends(require_role(*_a.ADMIN))):
    config = _config()
    with _a._db(user, bypass=_is_super(user)) as db:
        adopted = _adopted_names(db, user)
    return {"data": [_view(config, m, adopted) for m in _visible(config) if _allowed(user, m)]}


@router.post("/legacy-models/{model_name}/adopt", status_code=201)
def adopt_legacy(model_name: str, user=Depends(require_role(*_a.ADMIN))):
    return _adopt_one(user, _config(), model_name)


def _adopt_one(user, config: dict, model_name: str) -> dict:
    entry = next((m for m in _visible(config) if m["model_name"] == model_name and _allowed(user, m)), None)
    if entry is None:
        _a._err(404, "modelo inexistente en el config del motor")
    provider, real_model = _split(entry)
    if provider is None or provider not in cm.PROVIDERS or not real_model:
        _a._err(422, "no se puede derivar el proveedor del modelo: cargalo a mano en el catálogo")
    params = entry.get("litellm_params") or {}
    api_base = params.get("api_base")
    installation = _is_super(user)
    level, tenant = ("installation", None) if installation else ("tenant", user.tenant_id)
    with _a._db(user, bypass=installation) as db:
        if model_name in _adopted_names(db, user) or _a._name_taken(db, level, tenant, model_name):
            _a._err(409, "el modelo ya está en el catálogo")
        cred, key = None, params.get("api_key")
        try:
            if _credential_ref(entry) == "env":
                if rc.requires_api_base(provider) and not api_base:
                    _a._err(422, "este proveedor requiere api_base")
                cred = _adopt_credential(db, user, level, tenant, kind="env_ref",
                                         env_name=key[len(ENV_REF_PREFIX):])
            elif _credential_ref(entry) == "literal":
                cred = _adopt_credential(db, user, level, tenant, kind="secret", value=key,
                                         name=f"{model_name} (config)")
                _a._check_binding(provider, level, cred, api_base)
            else:
                _a._check_binding(provider, level, None, api_base)
        except rc.CredentialError as exc:
            _a._err(422, str(exc))
        e = cm.CatalogEntry(
            id=uuid.uuid4(), level=level, tenant_id=tenant, name=model_name, public_id=model_name,
            provider=provider, real_model=real_model,
            protocol_family="anthropic_messages" if provider == "anthropic" else "openai_chat",
            api_base=api_base, credential_id=cred.id if cred else None,
            is_aggregator=provider == "openrouter", role="text", capability="standard",
            features={}, provider_options={},
            max_output=(entry.get("model_info") or {}).get("max_output_tokens"),
            blocked_by_default=provider == "deepseek", status="active", source="migrated_yaml",
            created_by=user.id, updated_by=user.id)
        db.add(e)
        db.flush()
        db.add(cm.ComplianceSheet(entry_id=e.id))              # nace sin clasificar (FR-039)
        if installation:
            db.add(cm.CatalogOffer(id=uuid.uuid4(), entry_id=e.id, tenant_id=None, created_by=user.id))
        db.flush()
        view = _a._view(db, user, e)
        _a._audit(db, user, entity="catalog_entry", entity_id=e.id, action="adopt_yaml",
                  after=_a._audit_view(view), tenant_id=e.tenant_id)
        tid = e.tenant_id
    _a._bump_for(tid)
    return view


def _status_flags() -> tuple:
    import os
    on = ("1", "true", "yes")
    return (os.environ.get("CATALOG_ONLY", "").strip().lower() in on,
            os.environ.get("CATALOG_DIRECT_ENABLED", "").strip().lower() in on)


# Estático antes que la ruta con parámetro de ruta: `adopt-all` no es un nombre de modelo.
@router.post("/legacy-models/adopt-all")
def adopt_all_legacy(user=Depends(require_role(*_a.ADMIN))):
    """Adopta todos los heredados visibles que aún no están en el catálogo (corte de la fuente única).

    Idempotente y sin abortar: cada modelo se adopta con la misma función que el alta individual y un
    fallo (proveedor no derivable, nombre de credencial repetido…) queda anotado sin frenar al resto.
    """
    config = _config()
    with _a._db(user, bypass=_is_super(user)) as db:
        adopted = _adopted_names(db, user)
    data, counts = [], {"adopted": 0, "skipped": 0, "failed": 0}
    for m in _visible(config):
        if not _allowed(user, m):
            continue
        name = m["model_name"]
        if name in adopted:
            row = {"model_name": name, "status": "skipped"}
        else:
            try:
                _adopt_one(user, config, name)
                row = {"model_name": name, "status": "adopted"}
            except HTTPException as exc:
                row = ({"model_name": name, "status": "skipped"} if exc.status_code == 409 and
                       "ya está en el catálogo" in str(exc.detail)
                       else {"model_name": name, "status": "failed", "error": str(exc.detail)})
            except Exception:                                   # un fallo individual no aborta el lote
                row = {"model_name": name, "status": "failed", "error": "error inesperado al adoptar"}
        counts[row["status"]] += 1
        data.append(row)
    return JSONResponse(status_code=207, content={**counts, "data": data})


@router.get("/status")
def catalog_status(user=Depends(require_role(*_a.READERS))):
    """Estado de la fuente única para la consola: interruptores de la instalación y heredados pendientes."""
    config = _config()
    with _a._db(user, bypass=_is_super(user)) as db:
        adopted = _adopted_names(db, user)
    names = [m["model_name"] for m in _visible(config) if _allowed(user, m)]
    only, direct = _status_flags()
    return {"catalog_only": only, "direct_enabled": direct, "legacy_total": len(names),
            "legacy_pending": sum(1 for n in names if n not in adopted)}


def _adopt_credential(db, user, level, tenant, *, kind, value=None, env_name=None, name=None):
    name = name or env_name
    if kind == "env_ref":
        # Varios modelos comparten la misma variable (p. ej. OPENAI_API_KEY): comparten UNA credencial.
        same = db.query(cm.Credential).filter(cm.Credential.tenant_id == tenant, cm.Credential.kind == "env_ref",
                                              cm.Credential.env_name == env_name,
                                              cm.Credential.status == "active").first()
        if same is not None:
            return same
    dup = db.query(cm.Credential).filter(cm.Credential.tenant_id == tenant, cm.Credential.name == name,
                                         cm.Credential.status == "active").first()
    if dup is not None:
        _a._err(409, "ya hay una credencial con ese nombre")
    row = cr.create(db, level=level, tenant_id=tenant, name=name, kind=kind, value=value,
                    env_name=env_name, user_id=user.id, encrypt=_a._encrypt, allow_any_env=True)
    _a._audit(db, user, entity="credential", entity_id=row.id, action="create",
              after=cr.fingerprint_of(row), tenant_id=tenant)
    return row
