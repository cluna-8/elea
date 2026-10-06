"""Modelos heredados del config del motor y su adopción (069; US7 «fuente única», etapa previa).

La pantalla de siempre administra `config.yaml`; esta ruta los lista y los adopta al catálogo sin
tocar el archivo. Corre con el venv del backend.
"""
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


def _list(api, role="super_admin", tenant=T1):
    r = api.call("GET", "/legacy-models", role, tenant=tenant)
    assert r.status_code == 200, r.text
    return {m["model_name"]: m for m in r.json()["data"]}


# ── lista de solo lectura ─────────────────────────────────────────────────────

def test_roles(api):
    assert api.call("GET", "/legacy-models").status_code == 401
    for r in ("client", "lectura", "compliance_officer"):
        assert api.call("GET", "/legacy-models", r).status_code == 403
    assert api.call("GET", "/legacy-models", "tenant_admin").status_code == 200
    assert api.call("POST", "/legacy-models/llama/adopt", "lectura").status_code == 403


def test_lista_sin_plugins_ni_valores_de_clave(api):
    r = api.call("GET", "/legacy-models", "super_admin")
    names = {m["model_name"] for m in r.json()["data"]}
    assert "de-plugin" not in names and "rdx-openai" not in names
    assert LITERAL not in r.text and "ANTHROPIC_API_KEY" not in r.text   # ni siquiera el nombre de la variable
    assert "api_key" not in json.dumps(r.json())


def test_campos_de_la_lista(api):
    m = _list(api)
    g = m["gpt-5.4"]
    assert (g["provider"], g["model_id"], g["has_credential"], g["credential_ref"]) == \
        ("openai", "gpt-5.4", True, "literal")
    assert g["fallback"] == "llama" and g["max_output_tokens"] == 8192 and g["is_local"] is False
    assert g["adopted"] is False
    assert m["claude-x"]["credential_ref"] == "env"
    ll = m["llama"]
    assert (ll["provider"], ll["has_credential"], ll["credential_ref"], ll["is_local"]) == \
        ("ollama", False, None, True)
    assert ll["api_base"] == "http://ollama:11434"


def test_admin_de_organizacion_solo_ve_los_locales(api):
    assert set(_list(api, "tenant_admin")) == {"llama"}


# ── adopción ──────────────────────────────────────────────────────────────────

def test_adopta_modelo_local_como_entrada_de_organizacion(api):
    r = api.call("POST", "/legacy-models/llama/adopt", "tenant_admin")
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["source"] == "migrated_yaml" and d["public_id"] == "llama" and d["level"] == "tenant"
    assert d["provider"] == "ollama" and d["real_model"] == "llama3" and d["has_credential"] is False
    assert d["semaforo"]["estado"] == "unclassified" and d["blocked_by_default"] is False
    assert api.store.bumps == [str(T1)]
    assert _list(api, "tenant_admin")["llama"]["adopted"] is True


def test_adoptar_dos_veces_es_409(api):
    assert api.call("POST", "/legacy-models/llama/adopt", "tenant_admin").status_code == 201
    assert api.call("POST", "/legacy-models/llama/adopt", "tenant_admin").status_code == 409


def test_aislamiento_de_la_adopcion(api):
    api.call("POST", "/legacy-models/llama/adopt", "tenant_admin", tenant=T1)
    assert _list(api, "tenant_admin", tenant=T2)["llama"]["adopted"] is False
    assert api.call("POST", "/legacy-models/llama/adopt", "tenant_admin", tenant=T2).status_code == 201


def test_modelo_con_credencial_exige_operador(api):
    assert api.call("POST", "/legacy-models/gpt-5.4/adopt", "tenant_admin").status_code == 404
    assert api.call("POST", "/legacy-models/gpt-5.4/adopt", "client").status_code == 403


def test_literal_se_cifra_y_nunca_vuelve(api):
    r = api.call("POST", "/legacy-models/gpt-5.4/adopt", "super_admin")
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["level"] == "installation" and d["tenant_id"] is None
    assert d["provider"] == "openai" and d["real_model"] == "gpt-5.4" and d["max_output"] == 8192
    assert d["credential"]["kind"] == "secret" and d["credential"]["name"] == "gpt-5.4 (config)"
    assert LITERAL not in r.text and d["offered_to"] == ["*"]
    with api.Session() as s:
        c = s.query(cm.Credential).one()
        assert LITERAL not in (c.ciphertext or "") and c.ciphertext.startswith("cifrado:")
        audit = json.dumps([(a.before, a.after) for a in s.query(rm.RedirectConfigAudit)], default=str)
        assert LITERAL not in audit and any(a.action == "create" for a in s.query(rm.RedirectConfigAudit))
    assert api.call("GET", "/credentials", "super_admin").json()["data"][0]["name"] == "gpt-5.4 (config)"
    assert LITERAL not in api.call("GET", "/legacy-models", "super_admin").text


def test_referencia_de_entorno_queda_como_env_ref(api):
    r = api.call("POST", "/legacy-models/claude-x/adopt", "super_admin")
    assert r.status_code == 201, r.text
    assert r.json()["credential"]["kind"] == "env_ref" and r.json()["provider"] == "anthropic"
    with api.Session() as s:
        c = s.query(cm.Credential).one()
        assert c.kind == "env_ref" and c.env_name == "ANTHROPIC_API_KEY" and c.ciphertext is None


def test_modelos_que_comparten_la_misma_variable_reutilizan_la_credencial(api, monkeypatch):
    """Hallazgo del corte en nix: ocho modelos usan OPENAI_API_KEY; la segunda adopción chocaba con
    «ya hay una credencial con ese nombre». Comparten UNA credencial `env_ref`."""
    cfg = {"model_list": [
        {"model_name": f"nix-us-{n}", "litellm_params": {"model": f"openai/gpt-{n}", "api_key": "os.environ/OPENAI_API_KEY"}}
        for n in ("fast", "pro", "terra")]}
    monkeypatch.setattr(legacy, "CONFIG_LOADER", lambda: json.loads(json.dumps(cfg)))
    r = api.call("POST", "/legacy-models/adopt-all", "super_admin")
    assert r.status_code == 207 and r.json()["adopted"] == 3 and r.json()["failed"] == 0, r.text
    with api.Session() as s:
        creds = s.query(cm.Credential).all()
        assert len(creds) == 1 and creds[0].env_name == "OPENAI_API_KEY"
        assert {e.credential_id for e in s.query(cm.CatalogEntry)} == {creds[0].id}


def test_credencial_literal_con_el_mismo_nombre_sigue_siendo_conflicto(api):
    api.call("POST", "/credentials", "super_admin", json={"name": "gpt-5.4 (config)", "kind": "secret", "value": "x", "level": "installation"})
    r = api.call("POST", "/legacy-models/gpt-5.4/adopt", "super_admin")
    assert r.status_code == 409


def _regla_de_paridad(api):
    """Paridad con Sentinel (057 data-model §2): su bloqueo fijo por proveedor es hoy una regla de datos."""
    from sentinel.catalog import habilitacion
    with api.Session() as s:
        habilitacion.seed_rules(s, {"providers": ["deepseek"]})
        s.commit()


def test_deepseek_nace_bloqueado_por_defecto(api):
    _regla_de_paridad(api)
    d = api.call("POST", "/legacy-models/deepseek-chat/adopt", "super_admin").json()
    assert d["blocked_by_default"] is True


def test_variable_de_la_lista_negra_se_rechaza(api):
    r = api.call("POST", "/legacy-models/master/adopt", "super_admin")
    assert r.status_code == 422
    with api.Session() as s:
        assert s.query(cm.CatalogEntry).count() == 0 and s.query(cm.Credential).count() == 0


def test_sin_prefijo_y_no_local_es_422_y_plugin_es_404(api):
    assert api.call("POST", "/legacy-models/sin-prefijo/adopt", "super_admin").status_code == 422
    assert api.call("POST", "/legacy-models/de-plugin/adopt", "super_admin").status_code == 404
    assert api.call("POST", "/legacy-models/rdx-openai/adopt", "super_admin").status_code == 404
    assert api.call("POST", "/legacy-models/no-existe/adopt", "super_admin").status_code == 404


def test_la_adopcion_no_toca_el_config(api, monkeypatch):
    called = []
    monkeypatch.setattr(legacy, "CONFIG_LOADER", lambda: (called.append(1), json.loads(json.dumps(CONFIG)))[1])
    api.call("POST", "/legacy-models/llama/adopt", "super_admin")
    assert called   # solo lectura; no hay ningún escritor en el módulo
    assert not hasattr(legacy, "_write_engine_config")


# ── env_ref adoptado: lista negra y límite del motor ──────────────────────────

@pytest.mark.parametrize("name", ["LITELLM_MASTER_KEY", "SENTINEL_ENGINE_MASTER_KEY", "FERNET_SECRET_KEY",
                                  "FERNET_PREVIOUS_KEYS", "JWT_SECRET_KEY", "DATABASE_URL",
                                  "POSTGRES_PASSWORD", "REDIRECT_INTERNAL_KEY", "MY_MASTER_KEY_2",
                                  "DB_PASSWORD_X", "PG_DATABASE", "minusculas", "1_EMPIEZA", "CON-GUION", ""])
def test_lista_negra_y_formato(name):
    with pytest.raises(rc.CredentialError):
        cr.env_ref_dict(name, allow_any_env=True)


def test_allow_any_env_acepta_nombre_comun_y_por_defecto_sigue_estricto():
    assert cr.env_ref_dict("ANTHROPIC_API_KEY", allow_any_env=True) == {"api_key": "env:ANTHROPIC_API_KEY"}
    with pytest.raises(rc.CredentialError):
        cr.env_ref_dict("ANTHROPIC_API_KEY")
    assert cr.env_ref_dict("REDIRECT_CRED_OR") == {"api_key": "env:REDIRECT_CRED_OR"}


def test_el_motor_resuelve_el_env_ref_adoptado():
    from sentinel.engine import redirect_credentials as engine_rc
    ref = cr.env_ref_dict("ANTHROPIC_API_KEY", allow_any_env=True)
    assert engine_rc.resolve_env_refs(ref, {"ANTHROPIC_API_KEY": "sk-real"}) == {"api_key": "sk-real"}
