"""`/workspaces` — aislamiento real de punta a punta (spec 043 US1, contrato 1, T013/T014).

Dos personas, dos sesiones: A crea un espacio, B no lo ve ni puede acceder por id conocido;
A lo agrega como miembro; B lo ve y sus hilos no se cruzan con los de A; sin sesión, 401 en
todo. Es exactamente el guion de `quickstart.md` §1 de la 043, contra la API real."""
import uuid

import pytest
from fastapi import Depends, FastAPI, Header
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from migration_harness import fresh_db, owner_engine, require_postgres, run_alembic

require_postgres()

DB = "sentinel_test_workspaces_api_043"


@pytest.fixture(scope="module")
def factory():
    fresh_db(DB)
    run_alembic(DB, "upgrade", "head")
    engine = owner_engine(DB)
    yield sessionmaker(autocommit=False, autoflush=False, bind=engine)
    engine.dispose()


def _seed_tenant_and_users(factory):
    from src.models.tenant import DEFAULT_TENANT_ID, Tenant
    from src.models.user import User
    db = factory()
    try:
        if not db.query(Tenant).filter(Tenant.id == DEFAULT_TENANT_ID).first():
            db.add(Tenant(id=DEFAULT_TENANT_ID, name="Default", slug="default"))
        suf = uuid.uuid4().hex[:8]
        ana = User(id=uuid.uuid4(), tenant_id=DEFAULT_TENANT_ID, username=f"ana-{suf}",
                  email=f"ana-{suf}@x.test", password_hash="!", role="client")
        luis = User(id=uuid.uuid4(), tenant_id=DEFAULT_TENANT_ID, username=f"luis-{suf}",
                   email=f"luis-{suf}@x.test", password_hash="!", role="client")
        db.add_all([ana, luis])
        db.commit()
        return str(ana.id), str(luis.id), ana.username, luis.username
    finally:
        db.close()


@pytest.fixture
def app_and_client(factory):
    from src.api.workspaces import router as workspaces_router
    from src.database import get_db
    from src.auth.session import get_current_user as real_get_current_user
    from src.models.user import User as _User

    app = FastAPI()
    app.include_router(workspaces_router)

    def override_get_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()
    app.dependency_overrides[get_db] = override_get_db

    # Identidad simulada vía cabecera propia del harness (nunca `X-Sentinel-*`, para no
    # confundirla con producción) — CADA request lee la suya, en vez de un swap global de
    # `app.dependency_overrides` que dos TestClient "distintos" pisarían entre sí (bug real
    # de la primera versión de este harness: dos sesiones compartiendo el mismo `app`
    # mutable colapsaban a "la última que se logueó").
    def _fake_user_impl(db=Depends(get_db), x_test_user_id: str = Header(None)):
        if not x_test_user_id:
            return None
        return db.query(_User).filter(_User.id == x_test_user_id).first()

    app.dependency_overrides[real_get_current_user] = _fake_user_impl
    return app


def _tc_as(app, user_id):
    tc = TestClient(app)
    if user_id is not None:
        tc.headers.update({"X-Test-User-Id": str(user_id)})
    return tc


def test_flujo_completo_aislamiento_y_membresia(factory, app_and_client):
    ana_id, luis_id, ana_username, luis_username = _seed_tenant_and_users(factory)
    app = app_and_client

    # A crea un espacio
    tc_ana = _tc_as(app, ana_id)
    r = tc_ana.post("/workspaces", json={"display_name": "Contabilidad"})
    assert r.status_code == 200, r.text
    ws_id = r.json()["id"]
    assert r.json()["role"] == "owner"

    # B no lo ve en su listado
    tc_luis = _tc_as(app, luis_id)
    r = tc_luis.get("/workspaces")
    assert r.status_code == 200
    assert all(w["id"] != ws_id for w in r.json()["workspaces"])

    # B no puede acceder por id conocido -> 403, nunca 404
    r = tc_luis.get(f"/workspaces/{ws_id}")
    assert r.status_code == 403

    # FR-005 (T020): el intento queda auditado — identidad del solicitante y recurso, sin
    # contenido — verificación real contra la fila, no solo que el 403 no rompe nada.
    from sqlalchemy import text
    db = factory()
    try:
        row = db.execute(text(
            "SELECT user_id, document_group_id, event_type, compliance_status FROM audit_logs "
            "WHERE event_type = 'access_denied' ORDER BY timestamp DESC LIMIT 1"
        )).fetchone()
        assert row is not None
        assert str(row.user_id) == luis_id
        assert str(row.document_group_id) == ws_id
        assert row.compliance_status == "blocked_by_policy"
    finally:
        db.close()

    # B no puede leer hilos ni agregar miembros de un espacio ajeno
    assert tc_luis.get(f"/workspaces/{ws_id}/threads").status_code == 403
    assert tc_luis.post(f"/workspaces/{ws_id}/members",
                        json={"username": luis_username}).status_code == 403

    # A agrega a B como miembro
    r = tc_ana.post(f"/workspaces/{ws_id}/members", json={"username": luis_username})
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "member"

    # Ahora B sí lo ve y puede acceder
    r = tc_luis.get("/workspaces")
    assert any(w["id"] == ws_id for w in r.json()["workspaces"])
    r = tc_luis.get(f"/workspaces/{ws_id}")
    assert r.status_code == 200
    assert r.json()["role"] == "member"

    # Hilos: cada uno ve solo los suyos
    tc_ana.post(f"/workspaces/{ws_id}/threads", json={})
    tc_luis.post(f"/workspaces/{ws_id}/threads", json={})
    ana_threads = tc_ana.get(f"/workspaces/{ws_id}/threads").json()["threads"]
    luis_threads = tc_luis.get(f"/workspaces/{ws_id}/threads").json()["threads"]
    assert len(ana_threads) == 1
    assert len(luis_threads) == 1
    assert ana_threads[0]["id"] != luis_threads[0]["id"]

    # B (member, no owner) no puede quitar miembros
    r = tc_luis.delete(f"/workspaces/{ws_id}/members/{ana_id}")
    assert r.status_code == 403

    # B no puede ser quitado por sí mismo tampoco vía owner-only... A (owner) sí puede
    # quitarlo, y no puede quitarse a sí mismo (dueño) sin transferir antes.
    r = tc_ana.delete(f"/workspaces/{ws_id}/members/{ana_id}")
    assert r.status_code == 409


def test_transferencia_de_propiedad(factory, app_and_client):
    ana_id, luis_id, ana_username, luis_username = _seed_tenant_and_users(factory)
    app = app_and_client
    tc_ana = _tc_as(app, ana_id)
    tc_luis = _tc_as(app, luis_id)

    ws_id = tc_ana.post("/workspaces", json={"display_name": "Legal"}).json()["id"]
    tc_ana.post(f"/workspaces/{ws_id}/members", json={"username": luis_username})

    r = tc_ana.patch(f"/workspaces/{ws_id}/transfer-owner",
                     json={"new_owner_user_id": luis_id})
    assert r.status_code == 200, r.text

    # Ahora Luis es owner y puede quitar a Ana (ya no dueña)
    r = tc_luis.delete(f"/workspaces/{ws_id}/members/{ana_id}")
    assert r.status_code == 200


def test_sin_sesion_401_en_todo(app_and_client):
    tc = _tc_as(app_and_client, None)
    assert tc.get("/workspaces").status_code == 401
    assert tc.post("/workspaces", json={"display_name": "x"}).status_code == 401
    assert tc.get(f"/workspaces/{uuid.uuid4()}").status_code == 401
