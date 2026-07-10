"""Onboarding-as-data (spec 013 US6, FR-025).

``seed_client(db, tenant, client_spec)`` crea de forma **idempotente** un client
(`User role='client'` + ``client_type``) con sus Connections (una ``APIKey`` por
herramienta) y su ``Budget``, todo tenant-scoped, leyendo un spec de config (ver
``backend/config/clients.example.yaml``). Sumar un cliente o un demo = datos, nunca
código (Constitución IV/VII). Productiviza el ``seed_gateway_demo`` hardcodeado del
fork demo (gatelite), que no existe en este repo.

Reuse over reinvent: reutiliza el esquema de key de ``src/api/keys.py``
(sha256 → ``key_hash``, preview ``sk-...<últimos 6>``). El registro de la key en el
motor (``ai_engine_client.generate_key``) queda fuera del seed: el seeding debe
funcionar sin el motor arriba; la sincronización con el motor es responsabilidad del
flujo de emisión online (``/keys``) o de una reconciliación posterior (spec 014).
"""
import secrets
from typing import Optional

import yaml
from sqlalchemy.orm import Session

from ..models.budget import APIKey, Budget
from ..models.tenant import Tenant
from ..models.user import Group, User
from .key_material import hash_key, key_preview

# Placeholder de password para identidades "client" sembradas por config: el client
# consume vía virtual key (Connection), no hace login interactivo. Un login real para
# estas identidades llega con SSO/auth hardening (spec 017).
_SEEDED_PASSWORD_SENTINEL = "!seeded-client-no-login"


def _get_or_create_group(db: Session, tenant: Tenant, name: str) -> Group:
    group = (
        db.query(Group)
        .filter(Group.tenant_id == tenant.id, Group.name == name)
        .first()
    )
    if group is None:
        group = Group(tenant_id=tenant.id, name=name)
        db.add(group)
        db.flush()
    return group


def seed_client(db: Session, tenant: Tenant, client_spec: dict) -> dict:
    """Upsert de un client + N Connections + Budget para ``tenant`` según spec.

    Idempotente por claves naturales: ``(tenant_id, username)`` para el User,
    ``(tenant_id, user_id, tool_type)`` para cada Connection, 1 Budget por user.
    Devuelve un resumen con las keys en claro SOLO de las Connections recién creadas
    (una key existente nunca se re-emite ni se puede recuperar: solo hay hash).
    """
    username = client_spec["username"]

    group: Optional[Group] = None
    if client_spec.get("group"):
        group = _get_or_create_group(db, tenant, client_spec["group"])

    user = (
        db.query(User)
        .filter(User.tenant_id == tenant.id, User.username == username)
        .first()
    )
    created_user = user is None
    if user is None:
        user = User(
            tenant_id=tenant.id,
            username=username,
            email=client_spec["email"],
            password_hash=_SEEDED_PASSWORD_SENTINEL,
            role="client",
            client_type=client_spec.get("client_type"),
            display_label=client_spec.get("display_label"),
            group_id=group.id if group else None,
            legal_basis=client_spec.get("legal_basis"),
            risk_level=client_spec.get("risk_level"),
        )
        db.add(user)
        db.flush()

    budget_spec = client_spec.get("budget")
    if budget_spec:
        budget = (
            db.query(Budget)
            .filter(Budget.tenant_id == tenant.id, Budget.user_id == user.id)
            .first()
        )
        if budget is None:
            db.add(Budget(
                tenant_id=tenant.id,
                user_id=user.id,
                max_spend_usd=budget_spec["max_spend_usd"],
                max_tokens=budget_spec["max_tokens"],
                reset_period=budget_spec.get("reset_period", "monthly"),
            ))

    created_connections = []
    for tool_spec in client_spec.get("tools", []):
        tool_type = tool_spec["tool_type"]
        existing = (
            db.query(APIKey)
            .filter(
                APIKey.tenant_id == tenant.id,
                APIKey.user_id == user.id,
                APIKey.tool_type == tool_type,
                APIKey.is_active.is_(True),
            )
            .first()
        )
        if existing is not None:
            continue

        # Mismo esquema de key que el flujo online (src/api/keys.py): sha256 + preview.
        plain_key = f"sk-basa-{secrets.token_urlsafe(24)}"
        db.add(APIKey(
            tenant_id=tenant.id,
            user_id=user.id,
            group_id=group.id if group else None,
            name=tool_spec.get("name", f"{tool_type} — {username}"),
            key_hash=hash_key(plain_key),
            key_preview=key_preview(plain_key),
            tool_type=tool_type,
            upstream_mode=tool_spec.get("upstream_mode", "byok"),
            oauth_credential_ref=tool_spec.get("oauth_credential_ref"),
            redact_enabled=tool_spec.get("redact_enabled"),
            compression_mode=tool_spec.get("compression_mode"),
            allowed_models=tool_spec.get("allowed_models"),
            allowed_tools=tool_spec.get("allowed_tools"),
            rpm_limit=tool_spec.get("rpm_limit", 60),
            tpm_limit=tool_spec.get("tpm_limit", 100000),
        ))
        created_connections.append({"tool_type": tool_type, "plain_key": plain_key})

    db.commit()
    return {
        "username": username,
        "user_id": user.id,
        "created_user": created_user,
        "created_connections": created_connections,
    }


def seed_clients_from_config(db: Session, tenant_slug: str, path: str) -> list[dict]:
    """Lee el YAML de clients (schema en config/clients.example.yaml) y siembra cada
    client contra el tenant ``tenant_slug``. Idempotente end-to-end."""
    tenant = db.query(Tenant).filter(Tenant.slug == tenant_slug).first()
    if tenant is None:
        raise ValueError(f"Tenant '{tenant_slug}' no existe — sembrar el tenant primero")

    with open(path, "r", encoding="utf-8") as fh:
        config = yaml.safe_load(fh) or {}

    return [seed_client(db, tenant, spec) for spec in config.get("clients", [])]
