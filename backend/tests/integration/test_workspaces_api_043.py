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

    # Bug real encontrado en vivo (11-sep, spec 046): GET /workspaces armaba el dict a mano
    # en `list_for_user` sin `kind` — el Hub nunca podía distinguir un espacio de análisis
    # exacto (DB-GPT, spec 048) de uno de chat RAG desde ese listado, aunque el espacio se
    # hubiera creado bien con el `kind` correcto.
    r_list = tc_ana.get("/workspaces")
    assert r_list.status_code == 200
    creado = next(w for w in r_list.json()["workspaces"] if w["id"] == ws_id)
    assert creado["kind"] == "rag", "GET /workspaces debe incluir kind en cada fila"

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

    # Bug real 10-sep (migración 019): el hilo PRINCIPAL (engine_thread_slug=None) tiene que
    # poder guardar el slug REAL del motor que lo respalda — sin esto, "hilo principal" no
    # tenía ningún hilo real detrás y el Hub terminaba hablando con el chat compartido a
    # nivel de espacio (el reclamo original de Tomás: "la memoria de chats es compartida").
    r = tc_ana.post(f"/workspaces/{ws_id}/threads",
                    json={"engine_thread_slug": None, "principal_engine_thread_slug": "engine-thread-ana"})
    assert r.status_code == 200, r.text
    assert r.json()["principal_engine_thread_slug"] == "engine-thread-ana"

    # Reclamarlo de nuevo (idempotente, como hace el Hub en cada pregunta) NO lo pisa con
    # otro valor — el mismo hilo real se reutiliza siempre.
    r2 = tc_ana.post(f"/workspaces/{ws_id}/threads",
                     json={"engine_thread_slug": None, "principal_engine_thread_slug": "otro-slug-distinto"})
    assert r2.status_code == 200, r2.text
    assert r2.json()["principal_engine_thread_slug"] == "engine-thread-ana", \
        "el hilo principal ya reclamado no debe pisarse con un slug nuevo"

    # El de Luis es un hilo real DISTINTO, y sigue sin cruzarse con el de Ana.
    r3 = tc_luis.post(f"/workspaces/{ws_id}/threads",
                      json={"engine_thread_slug": None, "principal_engine_thread_slug": "engine-thread-luis"})
    assert r3.status_code == 200, r3.text
    assert r3.json()["principal_engine_thread_slug"] == "engine-thread-luis"
    ana_principal = [t for t in tc_ana.get(f"/workspaces/{ws_id}/threads").json()["threads"]
                     if t["engine_thread_slug"] is None]
    assert len(ana_principal) == 1
    assert ana_principal[0]["principal_engine_thread_slug"] == "engine-thread-ana"

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


def test_asignar_miembro_a_espacio_sin_asignar_lo_saca_de_la_lista_y_lo_hace_dueno(factory, app_and_client):
    """Bug real encontrado en revisión (09-sep): `add_member` nunca seteaba
    `owner_user_id`/`status` en un espacio "sin asignar" (herencia de migración) — la UI
    ("Espacios sin asignar") prometía "Asignales un dueño" pero el espacio se quedaba en
    esa lista para siempre, y la persona asignada quedaba como "member", no "owner"."""
    from src.models.tenant import DEFAULT_TENANT_ID, Tenant
    from src.models.user import User
    from src.models.workspace import Workspace

    app = app_and_client
    db = factory()
    try:
        if not db.query(Tenant).filter(Tenant.id == DEFAULT_TENANT_ID).first():
            db.add(Tenant(id=DEFAULT_TENANT_ID, name="Default", slug="default"))
        suf = uuid.uuid4().hex[:8]
        admin = User(id=uuid.uuid4(), tenant_id=DEFAULT_TENANT_ID, username=f"admin-{suf}",
                    email=f"admin-{suf}@x.test", password_hash="!", role="tenant_admin")
        ana = User(id=uuid.uuid4(), tenant_id=DEFAULT_TENANT_ID, username=f"ana-{suf}",
                  email=f"ana-{suf}@x.test", password_hash="!", role="client")
        ws = Workspace(id=uuid.uuid4(), tenant_id=DEFAULT_TENANT_ID,
                       engine_slug=f"heredado-{suf}", display_name="Espacio heredado",
                       owner_user_id=None, status="unassigned")
        db.add_all([admin, ana, ws])
        db.commit()
        admin_id, ana_id, ana_username, ws_id = str(admin.id), str(ana.id), ana.username, str(ws.id)
    finally:
        db.close()

    tc_admin = _tc_as(app, admin_id)

    # Antes de asignar: aparece en "sin asignar".
    r = tc_admin.get("/workspaces", params={"status_filter": "unassigned"})
    assert r.status_code == 200, r.text
    assert any(w["id"] == ws_id for w in r.json()["workspaces"])

    r = tc_admin.post(f"/workspaces/{ws_id}/members", json={"username": ana_username})
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "owner", "el primer miembro de un espacio sin dueño debe quedar como owner"

    # Después de asignar: YA NO aparece en "sin asignar".
    r2 = tc_admin.get("/workspaces", params={"status_filter": "unassigned"})
    assert r2.status_code == 200, r2.text
    assert not any(w["id"] == ws_id for w in r2.json()["workspaces"]), \
        "el espacio debe salir de la lista de sin asignar una vez asignado"

    # Y Ana lo ve en su propio listado, como dueña.
    tc_ana = _tc_as(app, ana_id)
    r3 = tc_ana.get("/workspaces")
    assert r3.status_code == 200, r3.text
    mio = next((w for w in r3.json()["workspaces"] if w["id"] == ws_id), None)
    assert mio is not None
    assert mio["role"] == "owner"
