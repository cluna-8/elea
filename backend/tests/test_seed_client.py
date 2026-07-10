"""Tests de onboarding-as-data (spec 013 US6, SC-008, FR-025)."""
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from migration_harness import (
    BACKEND_ROOT, fresh_db, owner_engine, require_postgres, run_alembic,
)
from src.models.budget import APIKey, Budget
from src.models.tenant import Tenant
from src.models.user import User
from src.services.onboarding import seed_client, seed_clients_from_config

require_postgres()

DB = "basa_test_seed"

TENANT_A = uuid.UUID("aaaaaaaa-0000-0000-0000-00000000000a")
TENANT_B = uuid.UUID("bbbbbbbb-0000-0000-0000-00000000000b")

SPEC = {
    "username": "seed-client",
    "email": "seed-client@t.test",
    "display_label": "developer",
    "client_type": "base_url",
    "group": "seed-group",
    "budget": {"max_spend_usd": 25.0, "max_tokens": 100000, "reset_period": "monthly"},
    "tools": [
        {"tool_type": "claude-code", "name": "cc", "upstream_mode": "byok",
         "redact_enabled": True},
        {"tool_type": "cursor", "name": "cur", "upstream_mode": "byok"},
    ],
}


@pytest.fixture(scope="module")
def session_factory():
    fresh_db(DB)
    run_alembic(DB, "upgrade", "head")
    eng = owner_engine(DB)
    factory = sessionmaker(bind=eng)
    with factory() as db:
        for tenant_id, tag in [(TENANT_A, "a"), (TENANT_B, "b")]:
            db.add(Tenant(id=tenant_id, name=f"Tenant {tag.upper()}", slug=f"tenant-{tag}"))
        db.commit()
    yield factory
    eng.dispose()


def _counts(db, tenant_id, username):
    users = db.query(User).filter(User.tenant_id == tenant_id,
                                  User.username == username).count()
    keys = (db.query(APIKey).join(User, APIKey.user_id == User.id)
            .filter(User.username == username, APIKey.tenant_id == tenant_id).count())
    budgets = (db.query(Budget).join(User, Budget.user_id == User.id)
               .filter(User.username == username, Budget.tenant_id == tenant_id).count())
    return users, keys, budgets


def test_seed_client_creates_user_connections_budget(session_factory):
    with session_factory() as db:
        tenant = db.get(Tenant, TENANT_A)
        result = seed_client(db, tenant, SPEC)

        assert result["created_user"] is True
        assert {c["tool_type"] for c in result["created_connections"]} == {"claude-code", "cursor"}
        # La key en claro solo se devuelve al crearla; en DB solo hay hash+preview
        assert all(c["plain_key"].startswith("sk-basa-") for c in result["created_connections"])

        assert _counts(db, TENANT_A, "seed-client") == (1, 2, 1)

        user = db.query(User).filter(User.tenant_id == TENANT_A,
                                     User.username == "seed-client").one()
        assert user.role == "client"
        assert user.client_type == "base_url"
        assert user.group.name == "seed-group"
        assert user.group.tenant_id == TENANT_A


def test_seed_client_is_idempotent(session_factory):
    """SC-008: re-ejecutar con el mismo spec = 0 duplicados, 0 keys re-emitidas."""
    with session_factory() as db:
        tenant = db.get(Tenant, TENANT_A)
        result = seed_client(db, tenant, SPEC)

        assert result["created_user"] is False
        assert result["created_connections"] == []
        assert _counts(db, TENANT_A, "seed-client") == (1, 2, 1)


def test_same_username_in_two_tenants_does_not_collide(session_factory):
    """SC-006/SC-008: unicidad compuesta — el mismo username convive en 2 tenants."""
    with session_factory() as db:
        tenant_b = db.get(Tenant, TENANT_B)
        result = seed_client(db, tenant_b, SPEC)

        assert result["created_user"] is True
        assert _counts(db, TENANT_A, "seed-client") == (1, 2, 1)
        assert _counts(db, TENANT_B, "seed-client") == (1, 2, 1)


def test_seed_from_example_yaml_against_default_tenant(session_factory):
    """FR-025 end-to-end: el YAML de ejemplo siembra contra el default tenant que la
    migración garantiza; re-ejecutar es idempotente. Sumar un demo = 0 líneas de código."""
    path = str(BACKEND_ROOT / "config" / "clients.example.yaml")
    with session_factory() as db:
        results = seed_clients_from_config(db, "default", path)
        assert [r["created_user"] for r in results] == [True, True]

        rerun = seed_clients_from_config(db, "default", path)
        assert [r["created_user"] for r in rerun] == [False, False]
        assert all(r["created_connections"] == [] for r in rerun)


def test_seed_unknown_tenant_fails_closed(session_factory):
    with session_factory() as db:
        with pytest.raises(ValueError, match="no existe"):
            seed_clients_from_config(db, "tenant-fantasma", "/dev/null")
