"""Tests del client model y la Connection (spec 013 US5, SC-006, FR-012–FR-018)."""
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from migration_harness import (
    DEFAULT_TENANT, fresh_db, owner_engine, require_postgres, run_alembic,
)
from src.services.context_resolution import resolve_connection_toggles

require_postgres()

DB = "sentinel_test_client"

TENANT_A = uuid.UUID("aaaaaaaa-0000-0000-0000-00000000000a")
TENANT_B = uuid.UUID("bbbbbbbb-0000-0000-0000-00000000000b")
CLIENT_A = uuid.UUID("aaaaaaaa-0000-0000-0000-0000000000c1")


@pytest.fixture(scope="module")
def engine():
    fresh_db(DB)
    run_alembic(DB, "upgrade", "head")
    eng = owner_engine(DB)
    with eng.begin() as cx:
        for tenant_id, tag in [(TENANT_A, "a"), (TENANT_B, "b")]:
            cx.execute(text("""
                INSERT INTO tenants (id, name, slug) VALUES (:id, :name, :slug)
                ON CONFLICT (id) DO NOTHING
            """), {"id": tenant_id, "name": f"Tenant {tag.upper()}", "slug": f"tenant-{tag}"})
        cx.execute(text("""
            INSERT INTO users (id, tenant_id, username, email, password_hash, role, client_type)
            VALUES (:id, :t, 'client-a', 'client-a@t.test', 'x', 'client', 'base_url')
        """), {"id": CLIENT_A, "t": TENANT_A})
    yield eng
    eng.dispose()


def test_client_type_persists_for_role_client(engine):
    with engine.connect() as cx:
        row = cx.execute(text(
            "SELECT role, client_type FROM users WHERE id = :id"
        ), {"id": CLIENT_A}).one()
    assert row.role == "client"
    assert row.client_type == "base_url"


def test_client_type_rejected_for_non_client_role(engine):
    """FR-012: CHECK (client_type IS NULL OR role='client')."""
    with pytest.raises(DBAPIError, match="ck_users_client_type_role"):
        with engine.begin() as cx:
            cx.execute(text("""
                INSERT INTO users (tenant_id, username, email, password_hash, role, client_type)
                VALUES (:t, 'admin-with-ct', 'awc@t.test', 'x', 'tenant_admin', 'base_url')
            """), {"t": TENANT_A})


def test_invalid_client_type_rejected(engine):
    with pytest.raises(DBAPIError, match="ck_users_client_type"):
        with engine.begin() as cx:
            cx.execute(text("""
                INSERT INTO users (tenant_id, username, email, password_hash, role, client_type)
                VALUES (:t, 'bad-ct', 'bct@t.test', 'x', 'client', 'browser')
            """), {"t": TENANT_A})


def test_invalid_tool_type_rejected(engine):
    with pytest.raises(DBAPIError, match="ck_api_keys_tool_type"):
        with engine.begin() as cx:
            cx.execute(text("""
                INSERT INTO api_keys (tenant_id, user_id, key_hash, key_preview, name, tool_type)
                VALUES (:t, :u, 'h-badtool', 'sk-...x', 'bad', 'netscape')
            """), {"t": TENANT_A, "u": CLIENT_A})


def test_one_connection_per_tool_per_client(engine):
    """FR-018: UNIQUE (tenant_id, user_id, tool_type) — la segunda Connection para la
    misma herramienta se rechaza; otra herramienta sí entra."""
    with engine.begin() as cx:
        cx.execute(text("""
            INSERT INTO api_keys (tenant_id, user_id, key_hash, key_preview, name, tool_type)
            VALUES (:t, :u, 'h-cc-1', 'sk-...1', 'cc', 'claude-code')
        """), {"t": TENANT_A, "u": CLIENT_A})

    with pytest.raises(DBAPIError, match="uq_api_keys_tenant_user_tool"):
        with engine.begin() as cx:
            cx.execute(text("""
                INSERT INTO api_keys (tenant_id, user_id, key_hash, key_preview, name, tool_type)
                VALUES (:t, :u, 'h-cc-2', 'sk-...2', 'cc-dup', 'claude-code')
            """), {"t": TENANT_A, "u": CLIENT_A})

    with engine.begin() as cx:
        cx.execute(text("""
            INSERT INTO api_keys (tenant_id, user_id, key_hash, key_preview, name, tool_type)
            VALUES (:t, :u, 'h-cursor', 'sk-...3', 'cursor', 'cursor')
        """), {"t": TENANT_A, "u": CLIENT_A})


def test_key_hash_stays_globally_unique(engine):
    """FR-006: key_hash es material secreto — una colisión debe ser global, aunque
    sea en OTRO tenant. Test autosuficiente: inserta su propia fila base."""
    with engine.begin() as cx:
        cx.execute(text("""
            INSERT INTO api_keys (tenant_id, key_hash, key_preview, name, tool_type)
            VALUES (:t, 'h-global-base', 'sk-...g', 'base-global', 'chat-ui')
        """), {"t": TENANT_A})
    with pytest.raises(DBAPIError, match="key_hash"):
        with engine.begin() as cx:
            cx.execute(text("""
                INSERT INTO api_keys (tenant_id, key_hash, key_preview, name, tool_type)
                VALUES (:t, 'h-global-base', 'sk-...9', 'colision-cross-tenant', 'claude-code')
            """), {"t": TENANT_B})


def test_inactive_duplicate_does_not_collide(engine):
    """El índice único es PARCIAL (WHERE is_active): una Connection revocada no
    bloquea re-emitir la misma herramienta para el mismo client."""
    with engine.begin() as cx:
        cx.execute(text("""
            INSERT INTO api_keys (tenant_id, user_id, key_hash, key_preview, name,
                                  tool_type, is_active)
            VALUES (:t, :u, 'h-revoked', 'sk-...r', 'revocada', 'chatgpt', FALSE)
        """), {"t": TENANT_A, "u": CLIENT_A})
        # misma (tenant, user, tool) ACTIVA: entra porque la anterior está inactiva
        cx.execute(text("""
            INSERT INTO api_keys (tenant_id, user_id, key_hash, key_preview, name,
                                  tool_type, is_active)
            VALUES (:t, :u, 'h-reissued', 'sk-...i', 're-emitida', 'chatgpt', TRUE)
        """), {"t": TENANT_A, "u": CLIENT_A})


def test_same_email_and_group_name_allowed_across_tenants(engine):
    """SC-006 completo: email y group.name también son únicos POR TENANT (no global),
    y dentro del mismo tenant siguen rechazando duplicados."""
    with engine.begin() as cx:
        for tenant in (TENANT_A, TENANT_B):
            cx.execute(text("""
                INSERT INTO users (tenant_id, username, email, password_hash, role)
                VALUES (:t, :username, 'mismo@mail.test', 'x', 'client')
            """), {"t": tenant, "username": f"mail-{tenant.hex[:4]}"})
            cx.execute(text("""
                INSERT INTO groups (tenant_id, name) VALUES (:t, 'mismo-grupo')
            """), {"t": tenant})

    with pytest.raises(DBAPIError, match="uq_users_tenant_email"):
        with engine.begin() as cx:
            cx.execute(text("""
                INSERT INTO users (tenant_id, username, email, password_hash, role)
                VALUES (:t, 'otro-username', 'mismo@mail.test', 'x', 'client')
            """), {"t": TENANT_A})
    with pytest.raises(DBAPIError, match="uq_groups_tenant_name"):
        with engine.begin() as cx:
            cx.execute(text("""
                INSERT INTO groups (tenant_id, name) VALUES (:t, 'mismo-grupo')
            """), {"t": TENANT_A})


def test_subscription_passthrough_requires_oauth_ref(engine):
    """FR-013/FR-015: subscription-passthrough exige oauth_credential_ref (referencia
    Fernet, nunca token en claro); byok no lo exige."""
    with pytest.raises(DBAPIError, match="ck_api_keys_subscription_oauth"):
        with engine.begin() as cx:
            cx.execute(text("""
                INSERT INTO api_keys (tenant_id, user_id, key_hash, key_preview, name,
                                      tool_type, upstream_mode)
                VALUES (:t, :u, 'h-sub-x', 'sk-...s', 'sub-sin-ref', 'claude-desktop',
                        'subscription-passthrough')
            """), {"t": TENANT_A, "u": CLIENT_A})

    with engine.begin() as cx:
        cx.execute(text("""
            INSERT INTO api_keys (tenant_id, user_id, key_hash, key_preview, name,
                                  tool_type, upstream_mode, oauth_credential_ref)
            VALUES (:t, :u, 'h-sub-ok', 'sk-...k', 'sub-con-ref', 'claude-desktop',
                    'subscription-passthrough', 'fernet:oauth/client-a/claude-desktop')
        """), {"t": TENANT_A, "u": CLIENT_A})


def test_toggle_null_stored_as_null_not_false(engine):
    """FR-014: NULL = heredar ≠ False = off. La DB conserva la distinción."""
    with engine.begin() as cx:
        cx.execute(text("""
            INSERT INTO api_keys (tenant_id, user_id, key_hash, key_preview, name,
                                  tool_type, redact_enabled)
            VALUES (:t, :u, 'h-tgl-null', 'sk-...n', 'tgl-null', 'chat-ui', NULL)
        """), {"t": TENANT_A, "u": CLIENT_A})
        cx.execute(text("""
            INSERT INTO api_keys (tenant_id, user_id, key_hash, key_preview, name,
                                  tool_type, redact_enabled)
            VALUES (:t, :u, 'h-tgl-off', 'sk-...f', 'tgl-off', 'copilot', FALSE)
        """), {"t": TENANT_A, "u": CLIENT_A})

    with engine.connect() as cx:
        null_row = cx.execute(text(
            "SELECT redact_enabled FROM api_keys WHERE key_hash = 'h-tgl-null'"
        )).scalar()
        off_row = cx.execute(text(
            "SELECT redact_enabled FROM api_keys WHERE key_hash = 'h-tgl-off'"
        )).scalar()
    assert null_row is None
    assert off_row is False


class _Obj:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def test_toggle_resolution_null_inherits_value_overrides():
    """FR-014 (resolución): NULL hereda del group/tenant; True/False/valor hace
    override. Idem compression_mode / allowed_models."""
    group = _Obj(compression_mode="deterministic")
    tenant = _Obj(compression_mode="headroom")

    inherit = _Obj(redact_enabled=None, compression_mode=None,
                   allowed_models=None, allowed_tools=None)
    resolved = resolve_connection_toggles(inherit, group=group, tenant=tenant)
    assert resolved["redact_enabled"] is True          # masking-first sin override
    assert resolved["compression_mode"] == "deterministic"  # hereda del group
    assert resolved["allowed_models"] is None          # sin restricción propia

    no_group = resolve_connection_toggles(inherit, group=None, tenant=tenant)
    assert no_group["compression_mode"] == "headroom"  # hereda del tenant

    override = _Obj(redact_enabled=False, compression_mode="off",
                    allowed_models=["sentinel-fast"], allowed_tools=None)
    resolved = resolve_connection_toggles(override, group=group, tenant=tenant)
    assert resolved["redact_enabled"] is False         # override explícito ≠ heredar
    assert resolved["compression_mode"] == "off"
    assert resolved["allowed_models"] == ["sentinel-fast"]
