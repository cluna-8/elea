"""RLS real sobre las tablas nuevas de la 043 (workspaces/workspace_memberships/
workspace_threads, migración 018) — mismo patrón de verificación que la 010/017: conectado
como ``rls_owner`` (NOSUPERUSER, dueño de las tablas), sin esto ``FORCE ROW LEVEL SECURITY``
no es observable (un superuser bypasea RLS siempre).

No es un test de la lógica de negocio de US1 (eso es ``workspace_service`` + el router, más
adelante) — es la garantía de más bajo nivel: aunque toda la capa de aplicación tuviera un bug
y dejara pasar una query sin filtrar por tenant, Postgres la bloquea igual.
"""
import uuid

import pytest
from sqlalchemy import text

from migration_harness import fresh_db, owner_engine, require_postgres, run_alembic

require_postgres()

DB = "sentinel_test_workspace_rls_018"

TENANT_A = uuid.uuid4()
TENANT_B = uuid.uuid4()


@pytest.fixture(scope="module")
def engine():
    fresh_db(DB)
    run_alembic(DB, "upgrade", "head")
    eng = owner_engine(DB)
    with eng.begin() as cx:
        cx.execute(text("INSERT INTO tenants (id, name, slug) VALUES (:id, 'A', 'tenant-a')"),
                   {"id": TENANT_A})
        cx.execute(text("INSERT INTO tenants (id, name, slug) VALUES (:id, 'B', 'tenant-b')"),
                   {"id": TENANT_B})
        cx.execute(text(
            "INSERT INTO workspaces (id, tenant_id, engine_slug, display_name, status) "
            "VALUES (:id, :tenant_id, 'contabilidad', 'Contabilidad', 'active')"
        ), {"id": uuid.uuid4(), "tenant_id": TENANT_A})
        cx.execute(text(
            "INSERT INTO workspaces (id, tenant_id, engine_slug, display_name, status) "
            "VALUES (:id, :tenant_id, 'legal', 'Legal', 'active')"
        ), {"id": uuid.uuid4(), "tenant_id": TENANT_B})
    yield eng
    eng.dispose()


def _count_workspaces_as_tenant(engine, tenant_id):
    with engine.connect() as cx:
        cx.execute(text("SET app.current_tenant = :t"), {"t": str(tenant_id)})
        return cx.execute(text("SELECT count(*) FROM workspaces")).scalar()


def test_tenant_a_no_ve_los_workspaces_de_tenant_b(engine):
    assert _count_workspaces_as_tenant(engine, TENANT_A) == 1
    assert _count_workspaces_as_tenant(engine, TENANT_B) == 1


def test_sin_tenant_seteado_bootstrap_ve_todo_ventana_de_deploy(engine):
    # Mismo comportamiento heredado de la 010/017: sin GUC seteado, la sesión ve todo (ventana
    # de deploy on-prem). No es un bug de esta migración — es el mismo trade-off documentado.
    with engine.connect() as cx:
        total = cx.execute(text("SELECT count(*) FROM workspaces")).scalar()
    assert total == 2


def test_insertar_en_tenant_ajeno_lo_rechaza_el_with_check(engine):
    with engine.connect() as cx:
        cx.execute(text("SET app.current_tenant = :t"), {"t": str(TENANT_A)})
        with pytest.raises(Exception):
            cx.execute(text(
                "INSERT INTO workspaces (id, tenant_id, engine_slug, display_name, status) "
                "VALUES (:id, :tenant_id, 'colado', 'Colado', 'active')"
            ), {"id": uuid.uuid4(), "tenant_id": TENANT_B})
            cx.commit()


def test_membership_y_thread_heredan_el_mismo_aislamiento(engine):
    with engine.begin() as cx:
        ws_a = cx.execute(text(
            "SELECT id FROM workspaces WHERE tenant_id = :t"
        ), {"t": TENANT_A}).scalar()
        user_a = uuid.uuid4()
        cx.execute(text(
            "INSERT INTO users (id, tenant_id, username, email, password_hash, role) "
            "VALUES (:id, :t, 'ana', 'ana@example.test', '!', 'client')"
        ), {"id": user_a, "t": TENANT_A})
        cx.execute(text(
            "INSERT INTO workspace_memberships (id, tenant_id, workspace_id, user_id, role) "
            "VALUES (:id, :t, :ws, :u, 'owner')"
        ), {"id": uuid.uuid4(), "t": TENANT_A, "ws": ws_a, "u": user_a})
        cx.execute(text(
            "INSERT INTO workspace_threads (id, tenant_id, workspace_id, owner_user_id) "
            "VALUES (:id, :t, :ws, :u)"
        ), {"id": uuid.uuid4(), "t": TENANT_A, "ws": ws_a, "u": user_a})

    with engine.connect() as cx:
        cx.execute(text("SET app.current_tenant = :t"), {"t": str(TENANT_B)})
        assert cx.execute(text("SELECT count(*) FROM workspace_memberships")).scalar() == 0
        assert cx.execute(text("SELECT count(*) FROM workspace_threads")).scalar() == 0

    with engine.connect() as cx:
        cx.execute(text("SET app.current_tenant = :t"), {"t": str(TENANT_A)})
        assert cx.execute(text("SELECT count(*) FROM workspace_memberships")).scalar() == 1
        assert cx.execute(text("SELECT count(*) FROM workspace_threads")).scalar() == 1
