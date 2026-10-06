"""Datos de prueba compartidos: un tenant con destinos, ids publicados y reglas."""
import json
from types import SimpleNamespace

from sentinel.redirect.store import EMPTY, RedirectStore, Snapshot

TENANT = "11111111-1111-1111-1111-111111111111"
OTHER = "22222222-2222-2222-2222-222222222222"
KEY_ID = "33333333-3333-3333-3333-333333333333"
USER = "44444444-4444-4444-4444-444444444444"
INTERNAL_KEY = "k" * 48

DEST_CHAT = {  # destino traducido, compatible-OpenAI solo-chat (UE)
    "id": "d-chat", "level": "tenant", "tenant_id": TENANT, "name": "Qwen UE",
    "provider": "openai_compatible", "real_model": "qwen-destino", "protocol_family": "openai_chat",
    "inference_jurisdiction": "DE", "entity_jurisdiction": "DE", "blocked_by_default": False,
    "enabled_at": None, "has_credential": True, "api_base": "http://destino.local/v1",
    "capability_profile": {"thinking": False, "cache_control": False, "images": False},
    "context_window": 128000, "max_output": 8192, "status": "active",
}
DEST_ANTHROPIC = {  # destino nativo de la cara Claude (EE. UU.)
    "id": "d-ant", "level": "installation", "tenant_id": None, "name": "Nativo",
    "provider": "anthropic", "real_model": "claude-real", "protocol_family": "anthropic_messages",
    "inference_jurisdiction": "US", "entity_jurisdiction": "US", "blocked_by_default": False,
    "enabled_at": None, "has_credential": True, "api_base": None, "capability_profile": {},
    "context_window": 200000, "max_output": 64000, "status": "active",
}
CREDS = {"d-chat": json.dumps({"api_key": "sk-destino-chat"}),
         "d-ant": json.dumps({"api_key": "env:REDIRECT_CRED_ANT"})}


def snapshot(state="on", *, postures=(), targets=("d-chat",), claude_targets=("d-chat",),
             offers=({"destination_id": "d-ant", "tenant_id": "*", "enabled_at": None},)):
    policy = ({"tenant_id": TENANT, "scope_type": "tenant", "scope_value": "*", "state": state},) \
        if state else ()
    published = (
        {"id": "p-gen", "tenant_id": TENANT, "scope_type": "tenant", "scope_value": "*",
         "face": "openai_generic", "public_id": "pro"},
        {"id": "p-cl", "tenant_id": TENANT, "scope_type": "tenant", "scope_value": "*",
         "face": "claude", "public_id": "claude-sonnet-4-5", "family_tier": "sonnet",
         "is_family_default": True, "label_mode": "destination"},
    )
    rules = (
        {"id": "r-gen", "tenant_id": TENANT, "scope_type": "tenant", "scope_value": "*",
         "published_model_id": "p-gen", "targets": list(targets)},
        {"id": "r-cl", "tenant_id": TENANT, "scope_type": "tenant", "scope_value": "*",
         "published_model_id": "p-cl", "targets": list(claude_targets)},
    )
    return Snapshot(policy=policy, postures=tuple(postures), published=published, rules=rules,
                    destinations={"d-chat": DEST_CHAT, "d-ant": DEST_ANTHROPIC},
                    offers=tuple(offers), credentials=dict(CREDS))


def store(snap=None, *, key_models=None):
    snaps = {TENANT: snap if snap is not None else EMPTY}
    return RedirectStore(loader=lambda t: snaps.get(t, EMPTY), ttl=0,
                         key_models=lambda k: key_models, redis_factory=lambda: None,
                         decrypt=lambda blob: json.loads(blob) if blob else {})


def ident(**kw):
    base = {"tenant_id": TENANT, "api_key_id": KEY_ID, "user_id": USER, "group_id": None,
            "nlp": {"region": "eu"}}
    base.update(kw)
    return base


def ctx(route="/v1/chat/completions", model="pro", mode="byok", headers=None, **ident_kw):
    return SimpleNamespace(route=route, mode=mode, request_headers=headers or {},
                           ident=ident(**ident_kw), model=model, state={},
                           governance_overrides={}, routing_decision=None)


# ── destinos = entradas del catálogo (069 E3) ─────────────────────────────────────────────────────
# Los tests de la API de la 068 ya no dan de alta destinos por `POST /redirect/destinations` (responde 410):
# siembran la entrada del catálogo, que es de donde sale la lista, la validación de reglas y el plano de datos.

def seed_entry(db, *, name="Qwen UE", level="tenant", tenant=TENANT, provider="openai_compatible",
               real_model="qwen", protocol_family="openai_chat", api_base="http://destino/v1",
               credential=None, inference="DE", entity="DE", context_window=128000, max_output=None,
               price=None, status="active", role="text", features=None, unsupported=None,
               offered_to=(), blocked_by_default=False, enabled_at=None, public_id=None, id=None,
               credential_kind="secret", env_name=None):
    """Inserta una entrada del catálogo (con ficha y credencial) y devuelve `{"id": ..., ...}`.

    `price`: USD por millón de tokens, como lo escribía la 068 (`{"input_per_mtok", "output_per_mtok"}`).
    `offered_to`: tenants (o `"*"`) a los que se ofrece una entrada de instalación."""
    import uuid

    from sentinel.catalog import models as cm
    eid = uuid.UUID(str(id)) if id else uuid.uuid4()
    tenant_id = None if level == "installation" else uuid.UUID(str(tenant))
    cred = None
    if credential is not None or credential_kind == "env_ref":
        cred = cm.Credential(
            id=uuid.uuid4(), level=level, tenant_id=tenant_id, name=f"cred-{eid}", kind=credential_kind,
            ciphertext=None if credential_kind == "env_ref" else json.dumps(credential),
            env_name=env_name, fingerprint="abcd", status="active")
        db.add(cred)
    entry = cm.CatalogEntry(
        id=eid, level=level, tenant_id=tenant_id, name=name, public_id=public_id or cm.slugify(name),
        provider=provider, real_model=real_model, protocol_family=protocol_family, api_base=api_base,
        credential_id=cred.id if cred else None, role=role, features=dict(features or {}),
        context_window=context_window, max_output=max_output,
        price_input=None if not price else price["input_per_mtok"] / 1e6,
        price_output=None if not price else price["output_per_mtok"] / 1e6,
        unsupported_params=list(unsupported or []), blocked_by_default=blocked_by_default,
        enabled_at=enabled_at, status=status, source="console",
        archived_reason="archivada" if status == "archived" else None)
    db.add(entry)
    db.add(cm.ComplianceSheet(entry_id=eid, inference_jurisdiction=inference or "unknown",
                              entity_jurisdiction=entity, classification_version="console:0"))
    for t in offered_to:
        db.add(cm.CatalogOffer(id=uuid.uuid4(), entry_id=eid,
                               tenant_id=None if t == "*" else uuid.UUID(str(t))))
    db.flush()
    db.commit()
    return {"id": str(eid), "public_id": entry.public_id, "name": name}
