"""`/exact-analysis` — motor de análisis exacto de datos (spec 048, DB-GPT).

Verifica el contrato del backend (nunca el motor real — eso ya se probó en vivo, ver
`specs/048-motor-analisis-exacto-dbgpt/contracts/02-dbgpt-real-api.md`): aislamiento por
espacio (reusa 043), presupuesto ANTES de reenviar (FR-008), `kind` correcto, y que el motor
de análisis exacto se llama SOLO a través del servicio (nunca expuesto directo — se verifica
mockeando `exact_analysis_service`, mismo patrón que el resto de `backend/tests/`)."""
import uuid

import pytest
from fastapi import Depends, FastAPI, Header
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from migration_harness import fresh_db, owner_engine, require_postgres, run_alembic

require_postgres()

DB = "sentinel_test_exact_analysis_048"


@pytest.fixture(scope="module")
def factory():
    fresh_db(DB)
    run_alembic(DB, "upgrade", "head")
    engine = owner_engine(DB)
    yield sessionmaker(autocommit=False, autoflush=False, bind=engine)
    engine.dispose()


def _seed_users(factory):
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
        return str(ana.id), str(luis.id)
    finally:
        db.close()


@pytest.fixture
def app_and_client(factory):
    from src.api.exact_analysis import router as exact_analysis_router
    from src.database import get_db
    from src.auth.session import get_current_user as real_get_current_user
    from src.models.user import User as _User

    app = FastAPI()
    app.include_router(exact_analysis_router)

    def override_get_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()
    app.dependency_overrides[get_db] = override_get_db

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


def test_crear_espacio_queda_kind_exact_analysis(factory, app_and_client):
    ana_id, _ = _seed_users(factory)
    tc = _tc_as(app_and_client, ana_id)
    r = tc.post("/exact-analysis/workspaces", json={"display_name": "Ventas Q3"})
    assert r.status_code == 200, r.text
    assert r.json()["kind"] == "exact_analysis"


def test_sin_sesion_401(app_and_client):
    tc = _tc_as(app_and_client, None)
    r = tc.post("/exact-analysis/workspaces", json={"display_name": "x"})
    assert r.status_code == 401


def test_no_miembro_no_puede_subir_archivo(factory, app_and_client):
    ana_id, luis_id = _seed_users(factory)
    tc_ana = _tc_as(app_and_client, ana_id)
    ws = tc_ana.post("/exact-analysis/workspaces", json={"display_name": "Solo de Ana"}).json()

    tc_luis = _tc_as(app_and_client, luis_id)
    r = tc_luis.post(
        f"/exact-analysis/workspaces/{ws['id']}/files",
        files={"doc_file": ("x.csv", b"a,b\n1,2\n", "text/csv")},
    )
    assert r.status_code == 403


def test_subida_reenvia_al_motor_via_el_servicio(factory, app_and_client, monkeypatch):
    """Confirma que el archivo NUNCA se sube directo a DB-GPT desde afuera del backend — pasa
    por `exact_analysis_service.upload_file`, acá mockeado (el motor real ya se probó en vivo,
    T074)."""
    ana_id, _ = _seed_users(factory)
    tc = _tc_as(app_and_client, ana_id)
    ws = tc.post("/exact-analysis/workspaces", json={"display_name": "Con archivo"}).json()

    llamados = []

    async def fake_upload_file(*, conv_uid, filename, content, content_type):
        llamados.append((conv_uid, filename))
        return {"file_path": "dbgpt-fs://fake", "file_name": filename}

    import src.api.exact_analysis as mod
    monkeypatch.setattr(mod.engine, "upload_file", fake_upload_file)

    r = tc.post(
        f"/exact-analysis/workspaces/{ws['id']}/files",
        files={"doc_file": ("ventas.csv", b"depto,monto\nVentas,100\n", "text/csv")},
    )
    assert r.status_code == 200, r.text
    assert r.json()["file_name"] == "ventas.csv"
    assert len(llamados) == 1, "el motor se debe llamar EXACTAMENTE una vez, del lado del backend"


def test_rechaza_formato_no_tabular(factory, app_and_client):
    ana_id, _ = _seed_users(factory)
    tc = _tc_as(app_and_client, ana_id)
    ws = tc.post("/exact-analysis/workspaces", json={"display_name": "Formatos"}).json()
    r = tc.post(
        f"/exact-analysis/workspaces/{ws['id']}/files",
        files={"doc_file": ("informe.pdf", b"%PDF-1.4", "application/pdf")},
    )
    assert r.status_code == 422


def test_presupuesto_agotado_bloquea_antes_de_llamar_al_motor(factory, app_and_client, monkeypatch):
    """FR-008: el 402 sale ANTES de tocar el motor — el mock de `ask_question` no debe
    llamarse nunca en este caso."""
    ana_id, _ = _seed_users(factory)
    tc = _tc_as(app_and_client, ana_id)
    ws = tc.post("/exact-analysis/workspaces", json={"display_name": "Sin presupuesto"}).json()

    import src.api.exact_analysis as mod
    monkeypatch.setattr(mod.BudgetService, "has_sufficient_budget", staticmethod(lambda *a, **k: False))

    motor_llamado = False

    async def fake_ask_question(**kwargs):
        nonlocal motor_llamado
        motor_llamado = True
        raise AssertionError("no debería llegar acá con presupuesto agotado")

    monkeypatch.setattr(mod.engine, "ask_question", fake_ask_question)

    r = tc.post(
        f"/exact-analysis/workspaces/{ws['id']}/query",
        json={"question": "¿algo?", "conv_uid": "x", "select_param": {"file_path": "x"}},
    )
    assert r.status_code == 402
    assert motor_llamado is False


def test_query_exitosa_devuelve_sql_ejecutado(factory, app_and_client, monkeypatch):
    ana_id, _ = _seed_users(factory)
    tc = _tc_as(app_and_client, ana_id)
    ws = tc.post("/exact-analysis/workspaces", json={"display_name": "Con SQL"}).json()

    import src.api.exact_analysis as mod
    monkeypatch.setattr(mod.BudgetService, "has_sufficient_budget", staticmethod(lambda *a, **k: True))

    async def fake_ask_question(*, conv_uid, question, model_name, select_param):
        return mod.engine.ExactAnalysisAnswer(
            content="La suma es 2100.", sql_executed="SELECT SUM(monto) FROM t",
            model_used=model_name,
        )
    monkeypatch.setattr(mod.engine, "ask_question", fake_ask_question)

    r = tc.post(
        f"/exact-analysis/workspaces/{ws['id']}/query",
        json={"question": "¿cuánto suma?", "conv_uid": "abc", "select_param": {"file_path": "x"}},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["sql_executed"] == "SELECT SUM(monto) FROM t"
    assert body["model_used"] == "azure-gpt-4o-mini"
