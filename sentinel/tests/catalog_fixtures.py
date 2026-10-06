"""API del catálogo montada de verdad, sobre SQLite en memoria (sin Docker ni Postgres; RLS aparte).

Compartido por los tests nuevos de Eleia (T022, T024, T025, T087, T090, T099): cada módulo define
su propio `@pytest.fixture` que llama a `make_api(monkeypatch)`. Usa la costura S1 real
(`mount_plugin_routers`) y los guardas de rol reales del backend (`require_role`).
"""
import sys
import uuid
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
pytest.importorskip("src.auth.rbac", reason="requiere el venv del backend")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from src.auth.session import get_current_user  # noqa: E402
from src.plugins import mount_plugin_routers  # noqa: E402

from sentinel.catalog import models as cm  # noqa: E402
from sentinel.catalog.api import admin  # noqa: E402
from sentinel.redirect import models as rm  # noqa: E402

T1 = uuid.UUID("11111111-1111-1111-1111-111111111111")
T2 = uuid.UUID("22222222-2222-2222-2222-222222222222")
VALOR_SECRETO = "valor-inventado-de-prueba-NO-DEBE-VOLVER"   # nunca una credencial real


def user_of(role, tenant=T1):
    return SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant, role=role, display_label=None)


class _Store:
    def __init__(self):
        self.bumps = []

    def bump(self, tenant=None):
        self.bumps.append(tenant)


def make_api(monkeypatch, *, paquetes="sentinel.catalog.api", rutas=6):
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    cm.CatalogBase.metadata.create_all(engine)
    rm.RedirectBase.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    store = _Store()
    dpas = {}
    monkeypatch.delenv("REDIRECT_OPERATOR_TENANT", raising=False)   # Eleia no la define (R30)
    monkeypatch.setattr(admin, "SESSION_FACTORY", Session)
    monkeypatch.setattr(admin, "ENCRYPT", lambda s: "cifrado:" + s[::-1])
    monkeypatch.setattr(admin, "DECRYPT", lambda b: b[len("cifrado:"):][::-1])
    monkeypatch.setattr(admin, "STORE", store)
    monkeypatch.setattr(admin, "DPA_LOOKUP", lambda db, tenant, dpa_id: dpas.get(str(dpa_id)))
    monkeypatch.setattr(admin, "TODAY", lambda: date(2026, 10, 1))
    app = FastAPI()
    assert mount_plugin_routers(app, paquetes) == rutas
    who = {"user": None}
    app.dependency_overrides[get_current_user] = lambda: who["user"]
    client = TestClient(app)

    def call(method, path, role=None, tenant=T1, prefix="/api/v1/catalog", **kw):
        who["user"] = user_of(role, tenant) if role else None
        return client.request(method, prefix + path, **kw)

    def audit(entity=None):
        db = Session()
        try:
            q = db.query(rm.RedirectConfigAudit)
            if entity:
                q = q.filter(rm.RedirectConfigAudit.entity == entity)
            return [{"entity": r.entity, "action": r.action, "reason": r.reason, "before": r.before,
                     "after": r.after, "actor_role": r.actor_role, "tenant_id": r.tenant_id}
                    for r in q.order_by(rm.RedirectConfigAudit.at)]
        finally:
            db.close()

    return SimpleNamespace(call=call, Session=Session, store=store, dpas=dpas, audit=audit)


def entry_body(**kw):
    body = {"level": "tenant", "name": "OpenRouter GLM", "provider": "openrouter",
            "real_model": "z-ai/glm-4.6", "protocol_family": "openai_chat",
            "credential": {"new": {"name": "or-key", "value": VALOR_SECRETO}},
            "capability": "standard", "role": "text", "context_window": 128000}
    body.update(kw)
    return body


def create_entry(api, role="tenant_admin", tenant=T1, **kw):
    r = api.call("POST", "/entries", role, tenant=tenant, json=entry_body(**kw))
    assert r.status_code == 201, r.text
    return r.json()
