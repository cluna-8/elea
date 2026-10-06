"""Montura compartida de la API de administración `/api/v1/redirect/*` para los tests de la 057 T-E.

Misma montura que `contract/test_redirect_admin_api.py` (costura S1 real, guardas de rol reales, SQLite en
memoria), con la región de la instalación sembrada: perfil `eu` y una fila `reject_offregion` (paridad con la 068)
salvo que el test pida otra cosa."""
import sys
import uuid
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
from sentinel.redirect import models as m  # noqa: E402
from sentinel.redirect.api import admin  # noqa: E402

sys.path.insert(0, str(ROOT / "sentinel" / "tests"))
from redirect_fixtures import seed_entry  # noqa: E402

T1 = uuid.UUID("11111111-1111-1111-1111-111111111111")
T2 = uuid.UUID("22222222-2222-2222-2222-222222222222")


def user_of(role, tenant=T1):
    return SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant, role=role, display_label=None)


class FakeStore:
    def __init__(self):
        self.bumps = []

    def bump(self, tenant=None):
        self.bumps.append(tenant)


def make_api(monkeypatch, *, profile="eu", region="reject_offregion", jurisdictions=("EU",)):
    """`profile=None` ⇒ sin `SENTINEL_ENTITY_REGION`; `region=None` ⇒ sin fila de región (rige el respaldo)."""
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    m.RedirectBase.metadata.create_all(engine)
    cm.CatalogBase.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    store = FakeStore()
    monkeypatch.setattr(admin, "SESSION_FACTORY", Session)
    monkeypatch.setattr(admin, "STORE", store)
    monkeypatch.delenv("REDIRECT_OPERATOR_TENANT", raising=False)
    if profile is None:
        monkeypatch.delenv("SENTINEL_ENTITY_REGION", raising=False)
    else:
        monkeypatch.setenv("SENTINEL_ENTITY_REGION", profile)
    if region is not None:
        with Session() as s:
            s.add(m.RedirectRegion(id=uuid.uuid4(), level="installation", tenant_id=None, name=(profile or "x").upper(),
                                   jurisdictions=list(jurisdictions), region_profiles=[profile or "x"],
                                   default_posture=region, is_zone=False))
            s.commit()
    app = FastAPI()
    assert mount_plugin_routers(app, "sentinel.redirect.api") == 1
    who = {"user": None}
    app.dependency_overrides[get_current_user] = lambda: who["user"]
    client = TestClient(app)

    def call(method, path, role=None, tenant=T1, **kw):
        who["user"] = user_of(role, tenant) if role else None
        return client.request(method, "/api/v1/redirect" + path, **kw)

    def seed(**kw):
        kw.setdefault("credential", {"api_key": "sk-x"})
        with Session() as s:
            return seed_entry(s, **kw)

    def audits(entity=None):
        with Session() as s:
            q = s.query(m.RedirectConfigAudit).order_by(m.RedirectConfigAudit.at)
            return [a for a in q if entity is None or a.entity == entity]

    return SimpleNamespace(call=call, Session=Session, store=store, seed=seed, audits=audits)
