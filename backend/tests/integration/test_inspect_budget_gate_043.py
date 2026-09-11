"""Gate 402 pre-request en `/gw/inspect` (spec 043 US2, FR-012, T030) — verificación real: un
usuario con presupuesto agotado recibe 402 ANTES de que el pedido llegue a `evaluate_request_
policy` (nunca se enmascara ni se audita como tráfico), y uno con crédito (o sin presupuesto
configurado, el caso de la mayoría de las llaves/extensión hoy) sigue funcionando igual."""
import uuid
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from migration_harness import fresh_db, owner_engine, require_postgres, run_alembic

require_postgres()

DB = "sentinel_test_inspect_budget_gate_043"


@pytest.fixture(scope="module")
def factory():
    fresh_db(DB)
    run_alembic(DB, "upgrade", "head")
    engine = owner_engine(DB)
    yield sessionmaker(autocommit=False, autoflush=False, bind=engine)
    engine.dispose()


def _seed_user_with_budget(factory, *, exhausted):
    from src.models.tenant import Tenant, DEFAULT_TENANT_ID
    from src.models.user import User
    from src.models.budget import Budget

    db = factory()
    try:
        if not db.query(Tenant).filter(Tenant.id == DEFAULT_TENANT_ID).first():
            db.add(Tenant(id=DEFAULT_TENANT_ID, name="Default", slug="default"))
            db.flush()
        user = User(
            id=uuid.uuid4(), tenant_id=DEFAULT_TENANT_ID,
            username=f"u-{uuid.uuid4().hex[:8]}", email=f"{uuid.uuid4().hex[:8]}@x.test",
            password_hash="!", role="client",
        )
        db.add(user)
        db.flush()
        budget = Budget(
            id=uuid.uuid4(), tenant_id=DEFAULT_TENANT_ID, user_id=user.id,
            max_spend_usd=Decimal("1.00"),
            current_spend_usd=Decimal("1.00") if exhausted else Decimal("0.00"),
            max_tokens=100000, current_tokens=0, reset_period="never",
        )
        db.add(budget)
        db.commit()
        return str(user.id)
    finally:
        db.close()


@pytest.fixture
def client_for(factory, monkeypatch):
    from src.api import gateway, inspect

    monkeypatch.setattr(gateway, "SessionLocal", factory)
    monkeypatch.setattr(inspect, "SessionLocal", factory)

    def make(user_id):
        ident = {
            "tenant_id": "00000000-0000-0000-0000-000000000001", "api_key_id": "key-1",
            "user_id": user_id, "group_id": None, "client_username": "ana",
            "tenant_slug": "default", "group_name": None, "key_label": "hub-key",
            "redact_enabled": None, "oauth_credential_ref": None,
            "can_act_on_behalf": False, "tool_type": "servicio",
            "governance_decisions": (), "nlp": {}, "applied_risk_level": "low",
        }
        monkeypatch.setattr(gateway, "_resolve_attribution",
                            lambda k: ident if k == "sk-valid" else {**ident, "api_key_id": None})
        monkeypatch.setattr(gateway, "_audit", lambda *a, **k: True)
        monkeypatch.setattr(gateway, "_publish_monitor", lambda *a, **k: None)
        app = FastAPI()
        app.include_router(gateway.router)
        app.include_router(inspect.router)
        return TestClient(app)

    return make


def test_402_cuando_el_presupuesto_esta_agotado(factory, client_for):
    user_id = _seed_user_with_budget(factory, exhausted=True)
    client = client_for(user_id)
    r = client.post("/gw/inspect", json={"text": "hola", "tool": "elea-rag-client"},
                    headers={"X-Sentinel-Key": "sk-valid"})
    assert r.status_code == 402
    body = r.json()
    assert body["ok"] is False
    assert body["code"] == "budget_exceeded"


def test_200_cuando_hay_credito(factory, client_for):
    user_id = _seed_user_with_budget(factory, exhausted=False)
    client = client_for(user_id)
    r = client.post("/gw/inspect", json={"text": "hola", "tool": "elea-rag-client"},
                    headers={"X-Sentinel-Key": "sk-valid"})
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_200_cuando_el_usuario_no_tiene_presupuesto_configurado(factory, client_for):
    from src.models.tenant import DEFAULT_TENANT_ID
    from src.models.user import User
    db = factory()
    try:
        user = User(id=uuid.uuid4(), tenant_id=DEFAULT_TENANT_ID,
                    username=f"u-{uuid.uuid4().hex[:8]}", email=f"{uuid.uuid4().hex[:8]}@x.test",
                    password_hash="!", role="client")
        db.add(user)
        db.commit()
        user_id = str(user.id)
    finally:
        db.close()
    client = client_for(user_id)
    r = client.post("/gw/inspect", json={"text": "hola", "tool": "elea-rag-client"},
                    headers={"X-Sentinel-Key": "sk-valid"})
    assert r.status_code == 200
