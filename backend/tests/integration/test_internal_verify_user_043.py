"""`/internal/verify-user` (spec 043 US2, T026, consumido por el motor vía
`custom_auth._verify_acting_user`) — verificación real: usuario del mismo tenant → válido,
de otro tenant → inválido, inexistente → inválido, UUID mal formado → inválido sin 500,
sin el secreto compartido → 404 (mismo criterio fail-closed que `/internal/identity`)."""
import os
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from migration_harness import fresh_db, owner_engine, require_postgres, run_alembic

require_postgres()

DB = "sentinel_test_internal_verify_user_043"
SECRETO = "secreto-de-prueba-043"


@pytest.fixture(scope="module")
def factory():
    fresh_db(DB)
    run_alembic(DB, "upgrade", "head")
    engine = owner_engine(DB)
    yield sessionmaker(autocommit=False, autoflush=False, bind=engine)
    engine.dispose()


@pytest.fixture
def client(factory, monkeypatch):
    monkeypatch.setenv("SENTINEL_ENGINE_MASTER_KEY", SECRETO)
    from src.api import internal
    from src.database import get_db

    app = FastAPI()
    app.include_router(internal.router, prefix="/api/v1")

    def override_get_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()
    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def _seed_two_tenants_one_user_each(factory):
    from src.models.tenant import Tenant
    from src.models.user import User
    db = factory()
    try:
        t1, t2 = uuid.uuid4(), uuid.uuid4()
        db.add_all([Tenant(id=t1, name="T1", slug=f"t1-{uuid.uuid4().hex[:6]}"),
                   Tenant(id=t2, name="T2", slug=f"t2-{uuid.uuid4().hex[:6]}")])
        u1 = User(id=uuid.uuid4(), tenant_id=t1, username=f"u1-{uuid.uuid4().hex[:6]}",
                  email=f"{uuid.uuid4().hex[:6]}@x.test", password_hash="!", role="client")
        db.add(u1)
        db.commit()
        return str(t1), str(u1.id), str(t2)
    finally:
        db.close()


def test_usuario_del_mismo_tenant_es_valido(factory, client):
    t1, u1, t2 = _seed_two_tenants_one_user_each(factory)
    r = client.get("/api/v1/internal/verify-user", params={"user_id": u1, "tenant_id": t1},
                   headers={"X-Sentinel-Internal": SECRETO})
    assert r.status_code == 200
    assert r.json()["valid"] is True


def test_usuario_de_otro_tenant_es_invalido(factory, client):
    t1, u1, t2 = _seed_two_tenants_one_user_each(factory)
    r = client.get("/api/v1/internal/verify-user", params={"user_id": u1, "tenant_id": t2},
                   headers={"X-Sentinel-Internal": SECRETO})
    assert r.status_code == 200
    assert r.json()["valid"] is False


def test_usuario_inexistente_es_invalido(factory, client):
    t1, u1, t2 = _seed_two_tenants_one_user_each(factory)
    r = client.get("/api/v1/internal/verify-user",
                   params={"user_id": str(uuid.uuid4()), "tenant_id": t1},
                   headers={"X-Sentinel-Internal": SECRETO})
    assert r.status_code == 200
    assert r.json()["valid"] is False


def test_uuid_mal_formado_no_revienta(client):
    r = client.get("/api/v1/internal/verify-user",
                   params={"user_id": "no-es-un-uuid", "tenant_id": "tampoco"},
                   headers={"X-Sentinel-Internal": SECRETO})
    assert r.status_code == 200
    assert r.json()["valid"] is False


def test_sin_el_secreto_compartido_404(factory, client):
    t1, u1, t2 = _seed_two_tenants_one_user_each(factory)
    r = client.get("/api/v1/internal/verify-user", params={"user_id": u1, "tenant_id": t1})
    assert r.status_code == 404
