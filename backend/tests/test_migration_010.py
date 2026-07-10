"""Tests de la migración 010 — up/down, backfill, idempotencia (spec 013 US1).

SC-001, SC-002 (esquema), SC-009. Corre contra el Postgres de Docker Compose;
self-skip si no está levantado.
"""
import pytest
from sqlalchemy import text

from migration_harness import (
    DEFAULT_TENANT, LEGACY, TENANT_TABLES,
    migrated_legacy_db, require_postgres, run_alembic,
)

require_postgres()

DB = "basa_test_migration"


@pytest.fixture(scope="module")
def engine():
    eng = migrated_legacy_db(DB)
    yield eng
    eng.dispose()


def test_upgrade_creates_exactly_one_default_tenant(engine):
    with engine.connect() as cx:
        rows = cx.execute(text(
            "SELECT id, slug, deployment_mode FROM tenants"
        )).fetchall()
    assert len(rows) == 1
    assert rows[0].id == DEFAULT_TENANT
    assert rows[0].slug == "default"
    assert rows[0].deployment_mode == "on_premise"


def test_backfill_all_tables_default_tenant_and_not_null(engine):
    """SC-001: 100% de las filas de TODAS las tablas tenant-scoped quedan en el
    default tenant, y la columna queda NOT NULL con FK."""
    with engine.connect() as cx:
        for table in TENANT_TABLES:
            total = cx.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
            assert total > 0, f"{table}: el seed legacy debió poblarla"
            stray = cx.execute(text(
                f"SELECT COUNT(*) FROM {table} WHERE tenant_id IS DISTINCT FROM :t"
            ), {"t": DEFAULT_TENANT}).scalar()
            assert stray == 0, f"{table}: filas fuera del default tenant tras backfill"

            nullable = cx.execute(text("""
                SELECT is_nullable FROM information_schema.columns
                WHERE table_name = :table AND column_name = 'tenant_id'
            """), {"table": table}).scalar()
            assert nullable == "NO", f"{table}.tenant_id debe ser NOT NULL"

            fk = cx.execute(text("""
                SELECT COUNT(*) FROM pg_constraint
                WHERE conname = :name AND contype = 'f'
            """), {"name": f"fk_{table}_tenant"}).scalar()
            assert fk == 1, f"{table}: falta fk_{table}_tenant"


def test_orphan_rows_fall_to_default_tenant(engine):
    """Edge case FR-005: filas huérfanas (user_id NULL) caen explícitamente al default."""
    with engine.connect() as cx:
        orphan_key_tenant = cx.execute(text(
            "SELECT tenant_id FROM api_keys WHERE id = :id"
        ), {"id": LEGACY["key_orphan"]}).scalar()
        assert orphan_key_tenant == DEFAULT_TENANT

        orphan_audit = cx.execute(text(
            "SELECT COUNT(*) FROM audit_logs WHERE user_id IS NULL AND tenant_id = :t"
        ), {"t": DEFAULT_TENANT}).scalar()
        assert orphan_audit == 1

        orphan_budget = cx.execute(text(
            "SELECT COUNT(*) FROM budgets WHERE user_id IS NULL AND tenant_id = :t"
        ), {"t": DEFAULT_TENANT}).scalar()
        assert orphan_budget == 1


def test_api_keys_backfilled_to_claude_code(engine):
    with engine.connect() as cx:
        rows = cx.execute(text("SELECT tool_type, upstream_mode FROM api_keys")).fetchall()
    assert len(rows) == 3
    assert all(r.tool_type == "claude-code" for r in rows)
    assert all(r.upstream_mode == "byok" for r in rows)


def test_duplicate_legacy_keys_deduped_newest_stays_active(engine):
    """Hallazgo de review (crítico): el esquema legacy permitía N keys por user; el
    backfill las deja a todas en 'claude-code'. La 010 deduplica manteniendo ACTIVA
    la más reciente y el índice único es parcial (WHERE is_active) — la migración
    no explota y no se revoca nada en el motor."""
    with engine.connect() as cx:
        rows = {r.key_hash: r.is_active for r in cx.execute(text(
            "SELECT key_hash, is_active FROM api_keys WHERE user_id = :u"
        ), {"u": LEGACY["user_admin"]})}
    assert rows == {"hash-linked": False, "hash-dup": True}

    with engine.connect() as cx:
        active_dups = cx.execute(text("""
            SELECT tenant_id, user_id, tool_type, COUNT(*) FROM api_keys
            WHERE is_active IS TRUE AND user_id IS NOT NULL
            GROUP BY tenant_id, user_id, tool_type HAVING COUNT(*) > 1
        """)).fetchall()
    assert active_dups == []


def test_upgrade_is_idempotent_rerun_of_010_body(engine):
    """SC-001/FR-023: re-ejecutar el CUERPO de la 010 sobre el esquema ya migrado
    (stamp 009 → upgrade head) no falla ni duplica — idempotencia SQL real, no solo
    el no-op de alembic cuando ya está en head."""
    run_alembic(DB, "stamp", "009")
    run_alembic(DB, "upgrade", "head")

    with engine.connect() as cx:
        tenants = cx.execute(text("SELECT COUNT(*) FROM tenants")).scalar()
        users = cx.execute(text("SELECT COUNT(*) FROM users")).scalar()
        policies = cx.execute(text(
            "SELECT COUNT(*) FROM pg_policies WHERE tablename = 'users'"
        )).scalar()
    assert tenants == 1
    assert users == 5
    assert policies == 2  # tenant_isolation + tenant_isolation_bootstrap, sin duplicar


def test_downgrade_reverts_consistently_and_roundtrips(engine):
    """SC-009: downgrade -1 deja la DB consistente (sin restos multi-tenant, UNIQUE
    globales restaurados); un upgrade posterior vuelve a head sin errores."""
    run_alembic(DB, "downgrade", "009")

    with engine.connect() as cx:
        assert cx.execute(text("SELECT to_regclass('tenants')")).scalar() is None
        tenant_cols = cx.execute(text("""
            SELECT COUNT(*) FROM information_schema.columns
            WHERE column_name = 'tenant_id' AND table_schema = 'public'
        """)).scalar()
        assert tenant_cols == 0
        policies = cx.execute(text(
            "SELECT COUNT(*) FROM pg_policies WHERE policyname LIKE 'tenant_isolation%'"
        )).scalar()
        assert policies == 0
        restored = cx.execute(text(
            "SELECT COUNT(*) FROM pg_constraint WHERE conname = 'users_username_key'"
        )).scalar()
        assert restored == 1
        # Los datos siguen ahí (reversible, no borra filas de negocio)
        assert cx.execute(text("SELECT COUNT(*) FROM users")).scalar() == 5

    run_alembic(DB, "upgrade", "head")
    with engine.connect() as cx:
        assert cx.execute(text("SELECT COUNT(*) FROM tenants")).scalar() == 1
        stray = cx.execute(text(
            "SELECT COUNT(*) FROM users WHERE tenant_id IS DISTINCT FROM :t"
        ), {"t": DEFAULT_TENANT}).scalar()
        assert stray == 0
