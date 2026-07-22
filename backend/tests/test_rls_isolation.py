"""Tests de aislamiento RLS con dos tenants (spec 013 US3, SC-003, SC-004).

Corren conectados como ``rls_owner`` — rol NOSUPERUSER **dueño** de las tablas — para
que ``FORCE ROW LEVEL SECURITY`` sea observable. Incluye el test explícito de la
trampa superuser: ``basa_admin`` (superuser del compose) bypasea RLS SIEMPRE, incluso
con FORCE → el runtime productivo debe conectarse con un rol NOSUPERUSER (spec 017).
"""
import uuid

import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

from migration_harness import (
    RLS_TENANT_TABLES, TENANT_TABLES, fresh_db, owner_engine, require_postgres, run_alembic,
    superuser_engine,
)

require_postgres()

DB = "basa_test_rls"

TENANT_A = uuid.UUID("aaaaaaaa-0000-0000-0000-00000000000a")
TENANT_B = uuid.UUID("bbbbbbbb-0000-0000-0000-00000000000b")


def _set_tenant(cx, tenant_id):
    cx.execute(text("SELECT set_config('app.current_tenant', :t, true)"),
               {"t": str(tenant_id) if tenant_id is not None else ""})


@pytest.fixture(scope="module")
def engine():
    fresh_db(DB)
    run_alembic(DB, "upgrade", "head")
    eng = owner_engine(DB)
    # Seed de dos tenants con datos espejo (sin GUC: aplica la policy bootstrap)
    with eng.begin() as cx:
        for tenant_id, tag in [(TENANT_A, "a"), (TENANT_B, "b")]:
            cx.execute(text("""
                INSERT INTO tenants (id, name, slug, deployment_mode)
                VALUES (:id, :name, :slug, 'cloud') ON CONFLICT (id) DO NOTHING
            """), {"id": tenant_id, "name": f"Tenant {tag.upper()}", "slug": f"tenant-{tag}"})
            cx.execute(text("""
                INSERT INTO groups (id, tenant_id, name) VALUES (:id, :t, :name)
            """), {"id": uuid.uuid4(), "t": tenant_id, "name": f"group-{tag}"})
            cx.execute(text("""
                INSERT INTO users (tenant_id, username, email, password_hash, role)
                VALUES (:t, :username, :email, 'x', 'client')
            """), {"t": tenant_id, "username": f"user-{tag}", "email": f"user-{tag}@t.test"})
            cx.execute(text("""
                INSERT INTO api_keys (tenant_id, key_hash, key_preview, name, tool_type)
                VALUES (:t, :hash, 'sk-...tst', :name, 'claude-code')
            """), {"t": tenant_id, "hash": f"hash-{tag}", "name": f"key-{tag}"})
    yield eng
    eng.dispose()


def test_select_is_isolated_per_tenant(engine):
    """SC-003: con app.current_tenant=<A>, 0 filas de B en tablas tenant-scoped."""
    for tenant_id, own_user, other_user in [
        (TENANT_A, "user-a", "user-b"), (TENANT_B, "user-b", "user-a"),
    ]:
        with engine.begin() as cx:
            _set_tenant(cx, tenant_id)
            for table in ["users", "groups", "api_keys"]:
                rows = cx.execute(text(
                    f"SELECT tenant_id FROM {table}"
                )).fetchall()
                assert rows, f"{table}: el tenant debe ver sus propias filas"
                assert all(r.tenant_id == tenant_id for r in rows), \
                    f"{table}: se filtraron filas de otro tenant"
            usernames = {r.username for r in cx.execute(text("SELECT username FROM users"))}
            assert own_user in usernames and other_user not in usernames


def test_cross_tenant_insert_rejected_by_with_check(engine):
    """SC-003: INSERT con tenant_id ajeno no pasa el WITH CHECK."""
    with pytest.raises(DBAPIError, match="row-level security"):
        with engine.begin() as cx:
            _set_tenant(cx, TENANT_A)
            cx.execute(text("""
                INSERT INTO users (tenant_id, username, email, password_hash, role)
                VALUES (:t, 'intruso', 'intruso@t.test', 'x', 'client')
            """), {"t": TENANT_B})


def test_force_rls_applies_to_table_owner(engine):
    """SC-004: conectado como el DUEÑO de las tablas (NOSUPERUSER), la RLS aísla.
    Prueba explícita de que sin FORCE fallaría: con NO FORCE el dueño ve todo."""
    # Con FORCE (estado de la migración): el dueño está aislado
    with engine.begin() as cx:
        _set_tenant(cx, TENANT_A)
        count = cx.execute(text("SELECT COUNT(*) FROM users")).scalar()
        assert count == 1

    # Sin FORCE, el dueño bypasea la RLS → esto es lo que la 010 evita
    with engine.begin() as cx:
        cx.execute(text("ALTER TABLE users NO FORCE ROW LEVEL SECURITY"))
    try:
        with engine.begin() as cx:
            _set_tenant(cx, TENANT_A)
            count = cx.execute(text("SELECT COUNT(*) FROM users")).scalar()
            assert count == 2, "sin FORCE el dueño debería ver ambos tenants (bypass)"
    finally:
        with engine.begin() as cx:
            cx.execute(text("ALTER TABLE users FORCE ROW LEVEL SECURITY"))

    with engine.begin() as cx:
        _set_tenant(cx, TENANT_A)
        assert cx.execute(text("SELECT COUNT(*) FROM users")).scalar() == 1


def test_bypass_rls_for_super_admin(engine):
    """FR-021: app.bypass_rls='on' (super_admin) ve todos los tenants."""
    with engine.begin() as cx:
        _set_tenant(cx, TENANT_A)
        cx.execute(text("SELECT set_config('app.bypass_rls', 'on', true)"))
        count = cx.execute(text("SELECT COUNT(*) FROM users")).scalar()
    assert count == 2


def test_unset_or_empty_guc_does_not_explode(engine):
    """Edge case FR-020: GUC vacío no explota el cast (NULLIF). Sin GUC aplica la
    policy bootstrap (ventana de deploy on-prem): se ve todo — la elimina la 017."""
    with engine.begin() as cx:
        count = cx.execute(text("SELECT COUNT(*) FROM users")).scalar()
    assert count == 2  # ventana bootstrap documentada, no un fallo

    with engine.begin() as cx:
        _set_tenant(cx, None)  # setea '' explícito — NULLIF lo trata como no-seteado
        count = cx.execute(text("SELECT COUNT(*) FROM users")).scalar()
    assert count == 2


def test_superuser_trap_is_documented(engine):
    """⚠️ basa_admin (superuser del compose) bypasea RLS SIEMPRE, incluso con FORCE.
    Este test documenta la trampa: el runtime productivo DEBE usar un rol NOSUPERUSER
    (cableado en 017). Si este test falla, basa_admin dejó de ser superuser (mejor)."""
    su = superuser_engine(DB)
    try:
        with su.begin() as cx:
            _set_tenant(cx, TENANT_A)
            count = cx.execute(text("SELECT COUNT(*) FROM users")).scalar()
        assert count == 2, "superuser ve todo aunque FORCE esté activo"
    finally:
        su.dispose()


def test_rls_enabled_and_forced_on_all_tenant_tables(engine):
    """FR-019/FR-020: ENABLE + FORCE + las 2 policies en TODA tabla tenant-scoped.

    Barre ``RLS_TENANT_TABLES`` —las 13 de la 010 **más** las que agregan migraciones
    posteriores— y no ``TENANT_TABLES``, que quedó acotada a las backfilleadas por la 010
    (``test_migration_010`` les exige ``COUNT(*) > 0``, imposible para una tabla nueva sin
    seed). La 027 encontró el agujero: ``governance_profiles`` nació sin RLS y ningún test
    lo detectaba porque la lista era fija.
    """
    with engine.connect() as cx:
        for table in RLS_TENANT_TABLES:
            flags = cx.execute(text("""
                SELECT relrowsecurity, relforcerowsecurity
                FROM pg_class WHERE relname = :table
            """), {"table": table}).one()
            assert flags.relrowsecurity, f"{table}: RLS no habilitada"
            assert flags.relforcerowsecurity, f"{table}: falta FORCE RLS"

            policies = {r.policyname: r for r in cx.execute(text(
                "SELECT policyname, qual, with_check FROM pg_policies WHERE tablename = :table"
            ), {"table": table})}
            assert set(policies) == {"tenant_isolation", "tenant_isolation_bootstrap"}, \
                f"{table}: policies inesperadas {set(policies)}"
            # No solo el NOMBRE: el predicado real debe scopear por el GUC y admitir bypass
            strict = policies["tenant_isolation"]
            for pred in (strict.qual, strict.with_check):
                assert "app.current_tenant" in pred and "app.bypass_rls" in pred, \
                    f"{table}: predicado inesperado: {pred}"


def test_tenants_table_itself_is_isolated(engine):
    """Hallazgo de review: sin RLS en la PROPIA tabla tenants, una sesión scopeada
    vería nombres/slugs de todos los demás tenants."""
    with engine.begin() as cx:
        _set_tenant(cx, TENANT_A)
        slugs = {r.slug for r in cx.execute(text("SELECT slug FROM tenants"))}
    assert slugs == {"tenant-a"}

    with engine.begin() as cx:
        _set_tenant(cx, TENANT_A)
        cx.execute(text("SELECT set_config('app.bypass_rls', 'on', true)"))
        slugs = {r.slug for r in cx.execute(text("SELECT slug FROM tenants"))}
    assert {"tenant-a", "tenant-b"}.issubset(slugs)


def test_rls_bypass_contextvar_via_listener(engine):
    """FR-021 vía el mecanismo de runtime: tenant_context(..., bypass=True) inyecta
    app.bypass_rls por el listener y ve cross-tenant (super_admin)."""
    from src.database import _inject_tenant_guc, tenant_context

    TestSession = sessionmaker(bind=engine)
    event.listen(TestSession, "after_begin", _inject_tenant_guc)
    try:
        session = TestSession()
        with tenant_context(TENANT_A, bypass=True):
            count = session.execute(text("SELECT COUNT(*) FROM users")).scalar()
            assert count == 2  # bypass: ve ambos tenants
        session.close()
    finally:
        event.remove(TestSession, "after_begin", _inject_tenant_guc)


def test_tenant_context_injects_guc_per_transaction(engine):
    """FR-024 (mecanismo, no activación): tenant_context + el listener de database.py
    inyectan el GUC en CADA transacción — sobrevive commits intermedios."""
    from src.database import _inject_tenant_guc, tenant_context

    TestSession = sessionmaker(bind=engine)
    event.listen(TestSession, "after_begin", _inject_tenant_guc)
    try:
        session = TestSession()
        with tenant_context(TENANT_A):
            count = session.execute(text("SELECT COUNT(*) FROM users")).scalar()
            assert count == 1
            session.commit()  # mata el SET LOCAL → el listener debe re-inyectar
            count = session.execute(text("SELECT COUNT(*) FROM users")).scalar()
            assert count == 1
        session.close()

        # Fuera del contexto: sin GUC → ventana bootstrap (no default silencioso)
        session = TestSession()
        assert session.execute(text("SELECT COUNT(*) FROM users")).scalar() == 2
        session.close()
    finally:
        event.remove(TestSession, "after_begin", _inject_tenant_guc)
