"""`GET /users/me/budget` (spec 043 US2, contrato 2, T031) — verificación real: la ruta
literal `/me/budget` no cae en `/{user_id}` (bug de ordering fácil de reintroducir), la
persona ve su propio presupuesto sin sesión de admin, y sin presupuesto configurado no queda
bloqueada (mismo criterio que `has_sufficient_budget`)."""
import uuid
from decimal import Decimal

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from migration_harness import fresh_db, owner_engine, require_postgres, run_alembic

require_postgres()

DB = "sentinel_test_own_budget_043"


@pytest.fixture(scope="module")
def factory():
    fresh_db(DB)
    run_alembic(DB, "upgrade", "head")
    engine = owner_engine(DB)
    yield sessionmaker(autocommit=False, autoflush=False, bind=engine)
    engine.dispose()


def _seed_user(factory, *, max_usd=None, current_usd="0.00"):
    from src.models.tenant import DEFAULT_TENANT_ID, Tenant
    from src.models.user import User
    from src.models.budget import Budget

    db = factory()
    try:
        if not db.query(Tenant).filter(Tenant.id == DEFAULT_TENANT_ID).first():
            db.add(Tenant(id=DEFAULT_TENANT_ID, name="Default", slug="default"))
            db.flush()
        user = User(id=uuid.uuid4(), tenant_id=DEFAULT_TENANT_ID,
                    username=f"u-{uuid.uuid4().hex[:8]}", email=f"{uuid.uuid4().hex[:8]}@x.test",
                    password_hash="!", role="client")
        db.add(user)
        db.flush()
        user_id = user.id  # leído ANTES del commit, que expira los atributos del objeto
        if max_usd is not None:
            db.add(Budget(id=uuid.uuid4(), tenant_id=DEFAULT_TENANT_ID, user_id=user_id,
                          max_spend_usd=Decimal(max_usd), current_spend_usd=Decimal(current_usd),
                          max_tokens=100000, current_tokens=0, reset_period="never"))
        db.commit()
        return user_id
    finally:
        db.close()


@pytest.fixture
def client(factory, monkeypatch):
    from src.api import users
    from src.database import get_db

    app = FastAPI()
    # `users.router` ya trae su propio prefix="/users" (definido en el módulo) — no
    # duplicarlo acá (bug real del harness de este test, no de la app).
    app.include_router(users.router)

    def override_get_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()
    app.dependency_overrides[get_db] = override_get_db
    return app, users


def _client_as(app, users_mod, user_id, monkeypatch):
    # Consulta por id DENTRO de la sesión de la request (get_db, ya overrideada arriba) —
    # `_seed_user` devuelve un UUID plano, no un objeto ORM, justamente para no arrastrar
    # una instancia `detached` de otra sesión ya cerrada hasta acá (`get_own_budget` toca
    # `user.group_id`, lazy). Mismo shape que el `get_current_user` real: usa el `db` de
    # la request.
    from sqlalchemy.orm import Session as _Session
    from src.database import get_db
    from src.models.user import User as _User

    def _fake_get_current_user(db: _Session = Depends(get_db)):
        return db.query(_User).filter(_User.id == user_id).first()

    from src.auth.session import get_current_user as real_get_current_user
    app.dependency_overrides[real_get_current_user] = _fake_get_current_user
    return TestClient(app)


def test_me_budget_no_cae_en_user_id(client, factory, monkeypatch):
    app, users_mod = client
    user = _seed_user(factory, max_usd="1.00", current_usd="0.25")
    tc = _client_as(app, users_mod, user, monkeypatch)
    r = tc.get("/users/me/budget")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["used_usd"] == 0.25
    assert body["max_usd"] == 1.0
    assert body["status"] == "ok"


def test_me_budget_status_exceeded(client, factory, monkeypatch):
    app, users_mod = client
    user = _seed_user(factory, max_usd="1.00", current_usd="1.00")
    tc = _client_as(app, users_mod, user, monkeypatch)
    r = tc.get("/users/me/budget")
    assert r.json()["status"] == "exceeded"


def test_me_budget_sin_presupuesto_configurado(client, factory, monkeypatch):
    app, users_mod = client
    user = _seed_user(factory, max_usd=None)
    tc = _client_as(app, users_mod, user, monkeypatch)
    r = tc.get("/users/me/budget")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert r.json()["max_usd"] is None


def test_me_budget_sin_sesion_401(client):
    app, _ = client
    tc = TestClient(app)
    r = tc.get("/users/me/budget")
    assert r.status_code == 401
