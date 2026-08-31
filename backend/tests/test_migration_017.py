"""Tests de la migración 017 — ``sso_providers``: esquema, unicidad, RLS y downgrade (spec 017 US2, T013).

Cubre lo que el brief pide y el hallazgo A1 heredado de la 012: ``sso_providers`` es una tabla
nueva con ``tenant_id`` y guarda la config del IdP (incluida la REFERENCIA Fernet al client
secret) — sin RLS, un UPSERT/DELETE por PK del CRUD admin con un id ajeno pisaría el proveedor
SSO de OTRO tenant.

Corre contra el Postgres de Docker Compose conectado como ``rls_owner`` (rol NOSUPERUSER dueño
de las tablas): con ``sentinel_admin`` —superuser— la RLS se bypasea SIEMPRE, incluso con FORCE, y
estos tests pasarían en verde sin probar nada. Self-skip si Postgres no está.
"""
import json
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from migration_harness import (
    DEFAULT_TENANT, fresh_db, owner_engine, require_postgres, run_alembic,
)

require_postgres()

DB = "sentinel_test_migration_017"

TENANT_B = uuid.UUID("bbbbbbbb-0000-0000-0000-0000000000dd")

# Fila válida de referencia: el proveedor v1 (Microsoft Entra ID).
VALID_ROW = {
    "provider_type": "entra",
    "config": None,
    "client_secret_encrypted": None,
    "enabled": False,
}


@pytest.fixture(scope="module")
def engine():
    fresh_db(DB)
    run_alembic(DB, "upgrade", "head")
    eng = owner_engine(DB)
    yield eng
    eng.dispose()


def _insert(cx, tenant_id=DEFAULT_TENANT, **overrides):
    row = dict(VALID_ROW, **overrides)
    row["id"] = overrides.get("id", uuid.uuid4())
    row["tenant_id"] = tenant_id
    # config castea explícito a JSONB: el bind llega como texto JSON (o NULL) y sin el CAST
    # psycopg no adapta un str a jsonb.
    cx.execute(text("""
        INSERT INTO sso_providers
            (id, tenant_id, provider_type, config, client_secret_encrypted, enabled)
        VALUES (:id, :tenant_id, :provider_type, CAST(:config AS JSONB),
                :client_secret_encrypted, :enabled)
    """), row)
    return row["id"]


def _ensure_tenant_b(cx):
    cx.execute(text("""
        INSERT INTO tenants (id, name, slug, deployment_mode)
        VALUES (:id, 'Tenant B', 'tenant-b-017', 'cloud') ON CONFLICT (id) DO NOTHING
    """), {"id": TENANT_B})


# ── Esquema ────────────────────────────────────────────────────────────────────────────────

def test_table_has_expected_columns_and_types(engine):
    """El contrato de columnas del brief: ids UUID, provider_type/secret VARCHAR, config JSONB,
    enabled BOOLEAN, timestamps."""
    with engine.connect() as cx:
        types = {r.column_name: r.data_type for r in cx.execute(text("""
            SELECT column_name, data_type FROM information_schema.columns
            WHERE table_name = 'sso_providers'
        """))}
    assert types == {
        "id": "uuid",
        "tenant_id": "uuid",
        "provider_type": "character varying",
        "config": "jsonb",
        "client_secret_encrypted": "character varying",
        "enabled": "boolean",
        "created_at": "timestamp without time zone",
        "updated_at": "timestamp without time zone",
    }, types


def test_fk_tenant_and_tenant_index_exist(engine):
    """``tenant_id`` es FK a ``tenants(id)`` (nombre del brief) y tiene su índice."""
    with engine.connect() as cx:
        fk = cx.execute(text("""
            SELECT contype FROM pg_constraint
            WHERE conname = 'fk_sso_providers_tenant'
              AND conrelid = 'sso_providers'::regclass
        """)).scalar()
        idx = cx.execute(text("""
            SELECT indexdef FROM pg_indexes
            WHERE tablename = 'sso_providers' AND indexname = 'ix_sso_providers_tenant_id'
        """)).scalar()
    assert fk == "f", "falta fk_sso_providers_tenant"
    assert idx is not None and "(tenant_id)" in idx


def test_unique_index_on_tenant_and_provider_type(engine):
    """La unicidad es (tenant_id, provider_type), como índice único
    ``uq_sso_providers_tenant_type`` (no un CONSTRAINT: la migración lo crea con CREATE UNIQUE
    INDEX IF NOT EXISTS por idempotencia)."""
    with engine.connect() as cx:
        indexdef = cx.execute(text("""
            SELECT indexdef FROM pg_indexes
            WHERE tablename = 'sso_providers' AND indexname = 'uq_sso_providers_tenant_type'
        """)).scalar()
    assert indexdef is not None, "falta uq_sso_providers_tenant_type"
    assert "UNIQUE" in indexdef, f"el índice debe ser único: {indexdef}"
    assert "(tenant_id, provider_type)" in indexdef, indexdef


# ── Unicidad, ejercitada de verdad ───────────────────────────────────────────────────────────

def test_valid_row_is_accepted(engine):
    """Control positivo: sin esto, un esquema roto que rechace TODO pasaría en verde los
    negativos de abajo."""
    with engine.begin() as cx:
        _insert(cx, provider_type="entra-ok",
                config=json.dumps({"client_id": "abc-123", "directory_id": "dir-1"}))
        stored = cx.execute(text(
            "SELECT config FROM sso_providers WHERE provider_type = 'entra-ok'"
        )).scalar()
    assert stored == {"client_id": "abc-123", "directory_id": "dir-1"}


def test_unique_rejects_duplicate_provider_type_same_tenant(engine):
    """Un solo proveedor por (tenant, tipo): dos filas 'entra' para el mismo tenant no van."""
    with engine.begin() as cx:
        _insert(cx, provider_type="entra-dup")
    with pytest.raises(IntegrityError) as exc:
        with engine.begin() as cx:
            _insert(cx, provider_type="entra-dup")
    assert "uq_sso_providers_tenant_type" in str(exc.value), str(exc.value)


def test_same_provider_type_different_tenant_is_allowed(engine):
    """El UNIQUE incluye tenant_id: dos tenants registran su propio proveedor 'entra'."""
    with engine.begin() as cx:
        _ensure_tenant_b(cx)
        _insert(cx, tenant_id=DEFAULT_TENANT, provider_type="entra")
        _insert(cx, tenant_id=TENANT_B, provider_type="entra")
        rows = cx.execute(text(
            "SELECT tenant_id FROM sso_providers WHERE provider_type = 'entra'"
        )).fetchall()
    assert {r.tenant_id for r in rows} == {DEFAULT_TENANT, TENANT_B}


# ── RLS (mismo tratamiento que las tablas de la 010) ─────────────────────────────────────────

def test_rls_enabled_forced_and_two_policies(engine):
    """ENABLE + FORCE + las DOS policies de la 010, con el MISMO predicado (scopea por el GUC
    y admite el bypass explícito, en USING y en WITH CHECK). Espeja test_rls_isolation.py:177."""
    with engine.connect() as cx:
        flags = cx.execute(text("""
            SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = 'sso_providers'
        """)).one()
        policies = {r.policyname: r for r in cx.execute(text(
            "SELECT policyname, qual, with_check FROM pg_policies WHERE tablename = 'sso_providers'"
        ))}
    assert flags.relrowsecurity, "RLS no habilitada"
    assert flags.relforcerowsecurity, "falta FORCE RLS"
    assert set(policies) == {"tenant_isolation", "tenant_isolation_bootstrap"}, set(policies)

    strict = policies["tenant_isolation"]
    for pred in (strict.qual, strict.with_check):
        assert "app.current_tenant" in pred and "app.bypass_rls" in pred, pred
    boot = policies["tenant_isolation_bootstrap"]
    for pred in (boot.qual, boot.with_check):
        assert "app.current_tenant" in pred, pred


def test_predicate_is_identical_to_the_010_tables(engine):
    """El predicado se copió literal de la 010: si alguien lo 'mejora' acá, esta tabla queda con
    una semántica de aislamiento propia y la 017/T020 la dejaría atrás."""
    with engine.connect() as cx:
        preds = {r.tablename: (r.qual, r.with_check) for r in cx.execute(text("""
            SELECT tablename, qual, with_check FROM pg_policies
            WHERE policyname = 'tenant_isolation'
              AND tablename IN ('sso_providers', 'api_keys')
        """))}
    assert preds["sso_providers"] == preds["api_keys"]


def test_cross_tenant_select_isolated_and_bypass_sees_it(engine):
    """Con app.current_tenant=<A>, una fila del tenant B NO es visible; con app.bypass_rls=on sí.
    (Espeja test_rls_isolation.py.)"""
    victim = uuid.uuid4()
    with engine.begin() as cx:
        _ensure_tenant_b(cx)
        _insert(cx, id=victim, tenant_id=TENANT_B, provider_type="entra-victim")

    with engine.begin() as cx:
        cx.execute(text("SELECT set_config('app.current_tenant', :t, true)"),
                   {"t": str(DEFAULT_TENANT)})
        assert cx.execute(text(
            "SELECT COUNT(*) FROM sso_providers WHERE id = :id"
        ), {"id": victim}).scalar() == 0, "la fila del otro tenant es visible"

        # UPDATE/DELETE por PK con un id ajeno: RLS no deja tocar nada (el escenario A1).
        updated = cx.execute(text(
            "UPDATE sso_providers SET enabled = TRUE WHERE id = :id"
        ), {"id": victim}).rowcount
        deleted = cx.execute(text(
            "DELETE FROM sso_providers WHERE id = :id"
        ), {"id": victim}).rowcount
    assert (updated, deleted) == (0, 0), "RLS no frenó la escritura cross-tenant por PK"

    with engine.begin() as cx:
        cx.execute(text("SELECT set_config('app.bypass_rls', 'on', true)"))
        enabled = cx.execute(text(
            "SELECT enabled FROM sso_providers WHERE id = :id"
        ), {"id": victim}).scalar()
    assert enabled is False, "la fila del tenant B quedó intacta bajo bypass"


def test_cross_tenant_insert_rejected_by_with_check(engine):
    """Con la sesión scopeada al tenant A, sembrar un proveedor a nombre de B tampoco va: el
    WITH CHECK de RLS levanta InsufficientPrivilege (DBAPIError 'row-level security')."""
    with pytest.raises(DBAPIError, match="row-level security"):
        with engine.begin() as cx:
            _ensure_tenant_b(cx)
            cx.execute(text("SELECT set_config('app.current_tenant', :t, true)"),
                       {"t": str(DEFAULT_TENANT)})
            _insert(cx, tenant_id=TENANT_B, provider_type="entra-intruso")


# ── Client secret: referencia cifrada, jamás en claro (C1) ───────────────────────────────────

def test_client_secret_round_trips_encrypted_never_plaintext(engine, monkeypatch):
    """``client_secret_encrypted`` guarda una REFERENCIA cifrada Fernet, nunca el secreto en
    claro. Ejercita el ``encryption_service`` real (apagado en la suite por FERNET_SECRET_KEY='',
    conftest.py:29 — se le inyecta una clave por corrida) y prueba el ida-y-vuelta a través de la
    columna: lo guardado != el plaintext y decrypt lo recupera."""
    from cryptography.fernet import Fernet

    from src.services import encryption_service

    monkeypatch.setattr(encryption_service, "_fernet", Fernet(Fernet.generate_key()))

    plaintext = "entra-client-secret-super-sensible"
    ciphertext = encryption_service.encrypt(plaintext)
    assert ciphertext is not None and ciphertext != plaintext, "encrypt no cifró"

    row_id = uuid.uuid4()
    with engine.begin() as cx:
        _insert(cx, id=row_id, provider_type="entra-secret", client_secret_encrypted=ciphertext)
        stored = cx.execute(text(
            "SELECT client_secret_encrypted FROM sso_providers WHERE id = :id"
        ), {"id": row_id}).scalar()

    assert stored == ciphertext, "la columna truncó/alteró el ciphertext"
    assert stored != plaintext, "el secreto quedó en claro en la columna (C1)"
    assert encryption_service.decrypt(stored) == plaintext, "no se recupera el secreto"


# ── Ida y vuelta (upgrade/downgrade limpio) ──────────────────────────────────────────────────

def test_downgrade_then_reupgrade_is_clean(engine):
    """El downgrade no deja restos (tabla, ambos índices, policies) y un upgrade posterior vuelve
    a head sin errores — con la RLS re-armada, no solo la tabla."""
    run_alembic(DB, "downgrade", "016")

    with engine.connect() as cx:
        assert cx.execute(text("SELECT to_regclass('sso_providers')")).scalar() is None
        assert cx.execute(text(
            "SELECT COUNT(*) FROM pg_policies WHERE tablename = 'sso_providers'"
        )).scalar() == 0
        assert cx.execute(text(
            "SELECT COUNT(*) FROM pg_indexes WHERE indexname = 'uq_sso_providers_tenant_type'"
        )).scalar() == 0
        # Fuera de la feature no se pierde nada: tenants sigue en pie.
        assert cx.execute(text("SELECT to_regclass('tenants')")).scalar() is not None

    run_alembic(DB, "upgrade", "head")
    with engine.connect() as cx:
        assert cx.execute(text("SELECT to_regclass('sso_providers')")).scalar() is not None
        flags = cx.execute(text("""
            SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = 'sso_providers'
        """)).one()
        assert flags.relrowsecurity and flags.relforcerowsecurity
        assert cx.execute(text(
            "SELECT COUNT(*) FROM pg_policies WHERE tablename = 'sso_providers'"
        )).scalar() == 2
        # Cero seed: la tabla nace vacía.
        assert cx.execute(text("SELECT COUNT(*) FROM sso_providers")).scalar() == 0


def test_upgrade_body_is_idempotent(engine):
    """Re-ejecutar el CUERPO de la 017 sobre el esquema ya migrado (stamp 016 → upgrade head) no
    falla ni duplica policies/índices — el patrón IF NOT EXISTS / DROP POLICY del repo."""
    run_alembic(DB, "stamp", "016")
    run_alembic(DB, "upgrade", "head")

    with engine.connect() as cx:
        assert cx.execute(text(
            "SELECT COUNT(*) FROM pg_policies WHERE tablename = 'sso_providers'"
        )).scalar() == 2
        assert cx.execute(text(
            "SELECT COUNT(*) FROM pg_indexes WHERE indexname = 'uq_sso_providers_tenant_type'"
        )).scalar() == 1
