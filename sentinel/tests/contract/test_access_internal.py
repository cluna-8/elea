"""Canal interno `GET /api/v1/internal/model-access` (069 T152/T153; US2): el guard del motor lo usa
para aplicar el acceso por perfil a quienes hablan DIRECTO con el motor. Mismo secreto interno y mismo
404 sin él que `/internal/model-catalog`; falla del resolutor ⇒ 503 (fail-closed)."""
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))
pytest.importorskip("src.auth.rbac", reason="requiere el venv del backend")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from src.plugins import mount_plugin_routers  # noqa: E402

from sentinel.access import bridge  # noqa: E402

T1 = uuid.UUID("11111111-1111-1111-1111-111111111111")
INTERNAL = "interno-compartido"
U, G, K = "u-1", "g-1", "k-1"


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setenv("SENTINEL_ENGINE_MASTER_KEY", INTERNAL)
    seen = {"args": [], "answer": frozenset({"glm"}), "boom": False}

    def resolver(tenant, **kw):
        seen["args"].append((tenant, kw))
        if seen["boom"]:
            raise RuntimeError("resolutor caído")
        return seen["answer"]

    monkeypatch.setattr(bridge, "RESOLVER", resolver)
    monkeypatch.setattr(bridge, "RISK", lambda ident: ("medium", None))
    monkeypatch.setattr(bridge, "CATALOG", lambda tenant: {"glm": {}, "gpt": {}})
    app = FastAPI()
    mount_plugin_routers(app, "sentinel.catalog.api")
    client = TestClient(app)

    def call(secret=INTERNAL, **params):
        h = {"X-Sentinel-Internal": secret} if secret is not None else {}
        q = {"tenant": str(T1), **params}
        return client.get("/api/v1/internal/model-access", params=q, headers=h)

    seen["call"] = call
    return seen


def test_exige_el_secreto_interno_y_sin_el_responde_404(api):
    assert api["call"](secret=None, user=U).status_code == 404
    assert api["call"](secret="otro", user=U).status_code == 404
    assert api["args"] == []                                  # ni siquiera llegó al resolutor


def test_con_politica_devuelve_los_permitidos(api):
    r = api["call"](user=U, group=G, key=K)
    assert r.status_code == 200 and r.json() == {"restringe": True, "permitidos": ["glm"]}
    tenant, kw = api["args"][0]
    assert tenant == str(T1) and kw["user_id"] == U and kw["group_id"] == G and kw["key_id"] == K
    assert kw["user_risk"] == "medium"


def test_sin_politica_no_restringe(api):
    api["answer"] = None
    assert api["call"](user=U).json() == {"restringe": False, "permitidos": []}


def test_identidad_parcial_usa_lo_que_haya(api):
    assert api["call"](group=G).status_code == 200
    _, kw = api["args"][0]
    assert kw["user_id"] is None and kw["group_id"] == G and kw["key_id"] is None


def test_falla_del_resolutor_responde_503(api):
    api["boom"] = True
    assert api["call"](user=U).status_code == 503

