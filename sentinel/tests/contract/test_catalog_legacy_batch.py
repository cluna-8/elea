"""Adopción en lote y estado de la fuente única (069 US7, T143/T144). Corre con el venv del backend."""
import json
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))
pytest.importorskip("src.auth.rbac", reason="requiere el venv del backend")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from src.auth.session import get_current_user  # noqa: E402
from src.plugins import mount_plugin_routers  # noqa: E402

from sentinel.catalog import credentials as cr  # noqa: E402
from sentinel.catalog import models as cm  # noqa: E402
from sentinel.catalog.api import admin, legacy  # noqa: E402
from sentinel.redirect import credentials as rc  # noqa: E402
from sentinel.redirect import models as rm  # noqa: E402

T1 = uuid.UUID("11111111-1111-1111-1111-111111111111")
T2 = uuid.UUID("22222222-2222-2222-2222-222222222222")
LITERAL = "sk-literal-del-yaml-NO-DEBE-VOLVER"

CONFIG = {
    "model_list": [
        {"model_name": "gpt-5.4", "litellm_params": {"model": "openai/gpt-5.4", "api_key": LITERAL},
         "model_info": {"max_output_tokens": 8192}},
        {"model_name": "claude-x", "litellm_params": {"model": "anthropic/claude-x",
                                                      "api_key": "os.environ/ANTHROPIC_API_KEY"}},
        {"model_name": "deepseek-chat", "litellm_params": {"model": "deepseek/deepseek-chat",
                                                          "api_key": "os.environ/REDIRECT_CRED_DS"}},
        {"model_name": "llama", "litellm_params": {"model": "ollama/llama3", "api_base": "http://ollama:11434"}},
        {"model_name": "master", "litellm_params": {"model": "openai/x",
                                                    "api_key": "os.environ/LITELLM_MASTER_KEY"}},
        {"model_name": "rdx-openai", "litellm_params": {"model": "openai/x", "api_key": "k"}},
        {"model_name": "de-plugin", "litellm_params": {"model": "openai/y", "api_key": "k"},
         "model_info": {"plugin_owner": "algo"}},
        {"model_name": "sin-prefijo", "litellm_params": {"model": "raro"}},
    ],
    "router_settings": {"fallbacks": [{"gpt-5.4": ["llama"]}]},
}


def _user(role, tenant=T1):
    return SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant, role=role, display_label=None)


class _Store:
    def __init__(self):
        self.bumps = []

    def bump(self, tenant=None):
        self.bumps.append(tenant)


@pytest.fixture
def api(monkeypatch):
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    cm.CatalogBase.metadata.create_all(engine)
    rm.RedirectBase.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    store = _Store()
    monkeypatch.setattr(admin, "SESSION_FACTORY", Session)
    monkeypatch.setattr(admin, "ENCRYPT", lambda s: "cifrado:" + s[::-1])
    monkeypatch.setattr(admin, "DECRYPT", lambda b: b[len("cifrado:"):][::-1])
    monkeypatch.setattr(admin, "STORE", store)
    monkeypatch.setattr(legacy, "CONFIG_LOADER", lambda: json.loads(json.dumps(CONFIG)))
    app = FastAPI()
    assert mount_plugin_routers(app, "sentinel.catalog.api") == 6
    who = {}
    app.dependency_overrides[get_current_user] = lambda: who["u"]
    client = TestClient(app)

    def call(method, path, role=None, tenant=T1, **kw):
        who["u"] = _user(role, tenant) if role else None
        return client.request(method, "/api/v1/catalog" + path, **kw)
    return SimpleNamespace(call=call, Session=Session, store=store)


def _env(monkeypatch, **kw):
    for k in ("CATALOG_ONLY", "CATALOG_DIRECT_ENABLED"):
        monkeypatch.delenv(k, raising=False)
    for k, v in kw.items():
        monkeypatch.setenv(k, v)


def _adopt_all(api, role="super_admin", tenant=T1):
    return api.call("POST", "/legacy-models/adopt-all", role, tenant=tenant)


def test_adopt_all_solo_admin(api):
    assert api.call("POST", "/legacy-models/adopt-all").status_code == 401
    for r in ("client", "lectura", "compliance_officer"):
        assert _adopt_all(api, r).status_code == 403


def test_adopt_all_adopta_lo_adoptable_y_no_aborta_por_un_fallo(api):
    r = _adopt_all(api)
    assert r.status_code == 207, r.text
    d = r.json()
    por = {x["model_name"]: x for x in d["data"]}
    # visibles para el operador: gpt-5.4, claude-x, deepseek-chat, llama, master, sin-prefijo
    assert set(por) == {"gpt-5.4", "claude-x", "deepseek-chat", "llama", "master", "sin-prefijo"}
    assert por["sin-prefijo"]["status"] == "failed" and por["sin-prefijo"]["error"]
    assert por["gpt-5.4"]["status"] == "adopted" and por["llama"]["status"] == "adopted"
    assert d["adopted"] == sum(x["status"] == "adopted" for x in d["data"])
    assert d["failed"] == sum(x["status"] == "failed" for x in d["data"]) and d["failed"] >= 1
    assert d["skipped"] == 0
    assert LITERAL not in r.text and "ANTHROPIC_API_KEY" not in r.text


def test_adopt_all_es_idempotente(api):
    first = _adopt_all(api).json()
    r = _adopt_all(api)
    assert r.status_code == 207
    d = r.json()
    assert d["adopted"] == 0 and d["skipped"] == first["adopted"]
    assert {x["status"] for x in d["data"]} <= {"skipped", "failed"}


def test_adopt_all_de_organizacion_solo_adopta_locales(api):
    d = _adopt_all(api, "tenant_admin").json()
    assert [(x["model_name"], x["status"]) for x in d["data"]] == [("llama", "adopted")]
    entries = api.call("GET", "/legacy-models", "tenant_admin").json()["data"]
    assert entries[0]["adopted"] is True


def test_estado_roles(api):
    assert api.call("GET", "/status").status_code == 401
    assert api.call("GET", "/status", "client").status_code == 403
    for r in ("tenant_admin", "compliance_officer", "lectura"):
        assert api.call("GET", "/status", r).status_code == 200


def test_estado_refleja_interruptores_y_pendientes(api, monkeypatch):
    _env(monkeypatch)
    d = api.call("GET", "/status", "super_admin").json()
    assert d["catalog_only"] is False and d["direct_enabled"] is False
    assert d["legacy_total"] == 6 and d["legacy_pending"] == 6
    _env(monkeypatch, CATALOG_ONLY="1", CATALOG_DIRECT_ENABLED="true")
    d = api.call("GET", "/status", "super_admin").json()
    assert d["catalog_only"] is True and d["direct_enabled"] is True
    api.call("POST", "/legacy-models/llama/adopt", "super_admin")
    d = api.call("GET", "/status", "super_admin").json()
    assert (d["legacy_total"], d["legacy_pending"]) == (6, 5)


def test_estado_de_lectura_ve_solo_lo_visible_para_el_usuario(api, monkeypatch):
    _env(monkeypatch)
    d = api.call("GET", "/status", "lectura").json()
    assert (d["legacy_total"], d["legacy_pending"]) == (1, 1)     # solo el local, como el admin de organización
