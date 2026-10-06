"""`api_base` de las entradas de empresa en la API del catálogo (057 H1 del QA de T-B).

Prueba descartable del QA, hecha test: un `tenant_admin` con `provider=openai_compatible` y una `api_base` interna
daba 201 en los seis casos. Ahora una entrada de **empresa** exige un host público por https (alta, edición, alta
masiva y adopción desde el config del motor); las de instalación no cambian; el interruptor de instalación
`CATALOG_ALLOW_PRIVATE_API_BASE` permite modelos locales on-prem y nunca los metadatos de nube; y la sonda de
despliegue de Azure no llama a una dirección rechazada.
"""
import uuid

import pytest

from sentinel.catalog import api_base as ab
from sentinel.catalog import models as cm
from sentinel.catalog.api import admin
from sentinel.tests.catalog_fixtures import T1, VALOR_SECRETO, make_api

SEIS_DE_H1 = [
    "http://169.254.169.254/latest",
    "http://engine:4000/v1",
    "http://db:5432",
    "http://127.0.0.1:8000/api/v1/gw/v1",
    "file:///etc/passwd",
    "ftp://x",
]
PUBLICA = "https://api.proveedor-ejemplo.com/v1"


@pytest.fixture
def api(monkeypatch):
    monkeypatch.delenv(ab.ALLOW_PRIVATE_ENV, raising=False)
    return make_api(monkeypatch)


def _body(api_base, name="Compatible", **kw):
    body = {"level": "tenant", "name": name, "provider": "openai_compatible", "real_model": "modelo-x",
            "protocol_family": "openai_chat", "api_base": api_base,
            "credential": {"new": {"name": f"c-{uuid.uuid4().hex[:6]}", "value": VALOR_SECRETO}}}
    body.update(kw)
    return body


def _post(api, api_base, role="tenant_admin", **kw):
    return api.call("POST", "/entries", role, json=_body(api_base, **kw))


def _entradas(api):
    with api.Session() as s:
        return s.query(cm.CatalogEntry).count()


@pytest.mark.parametrize("api_base", SEIS_DE_H1)
def test_el_alta_de_empresa_con_una_base_interna_es_422(api, api_base):
    r = _post(api, api_base)
    assert r.status_code == 422, r.text
    assert _entradas(api) == 0
    assert VALOR_SECRETO not in r.text


@pytest.mark.parametrize("rol", ["tenant_admin", "super_admin"])
def test_una_base_publica_https_se_acepta(api, rol):
    r = _post(api, PUBLICA, role=rol)
    assert r.status_code == 201, r.text
    assert r.json()["api_base"] == PUBLICA


@pytest.mark.parametrize("api_base", SEIS_DE_H1)
def test_la_edicion_de_empresa_con_una_base_interna_es_422_y_no_cambia_la_entrada(api, api_base):
    e = _post(api, PUBLICA).json()
    r = api.call("PATCH", f"/entries/{e['id']}", "tenant_admin", json={"api_base": api_base})
    assert r.status_code == 422, r.text
    assert api.call("GET", f"/entries/{e['id']}", "tenant_admin").json()["api_base"] == PUBLICA


def test_cambiar_el_proveedor_a_uno_con_base_interna_tambien_se_valida(api):
    e = _post(api, PUBLICA).json()
    # el proveedor cambia y la base vigente sigue siendo la pública: se acepta; la base interna no
    assert api.call("PATCH", f"/entries/{e['id']}", "tenant_admin",
                    json={"api_base": "https://otra.proveedor-ejemplo.com/v1"}).status_code == 200
    assert api.call("PATCH", f"/entries/{e['id']}", "tenant_admin",
                    json={"api_base": "http://10.1.2.3:8000/v1"}).status_code == 422


def test_las_entradas_de_instalacion_no_cambian(api):
    for i, base in enumerate(("http://engine:4000/v1", "http://ollama:11434", "http://10.0.0.5:8000/v1")):
        r = _post(api, base, role="super_admin", level="installation", name=f"Local {i}")
        assert r.status_code == 201, r.text


def test_la_alta_masiva_de_empresa_valida_la_base(api):
    body = {"provider": "openai_compatible", "api_base": "http://engine:4000/v1",
            "credential": {"new": {"name": "masivo", "value": VALOR_SECRETO}},
            "models": [{"real_model": "modelo-a"}]}
    r = api.call("POST", "/entries/bulk", "tenant_admin", json=body)
    assert r.status_code == 422, r.text
    assert _entradas(api) == 0
    body["api_base"] = PUBLICA
    r = api.call("POST", "/entries/bulk", "tenant_admin", json=body)
    assert r.status_code == 207 and r.json()["created"] == 1 and _entradas(api) == 1


# ── el interruptor de instalación: modelos locales on-prem ─────────────────────────────────────────

def test_con_el_interruptor_una_empresa_carga_un_modelo_local(api, monkeypatch):
    monkeypatch.setenv(ab.ALLOW_PRIVATE_ENV, "true")
    assert _post(api, "http://ollama:11434/v1", name="Local").status_code == 201
    assert _post(api, "http://10.0.0.5:8000/v1", name="Local 2").status_code == 201


@pytest.mark.parametrize("api_base", ["http://169.254.169.254/latest", "http://metadata.google.internal/x",
                                      "file:///etc/passwd", "ftp://x"])
def test_con_el_interruptor_los_metadatos_y_los_esquemas_ajenos_siguen_en_422(api, monkeypatch, api_base):
    monkeypatch.setenv(ab.ALLOW_PRIVATE_ENV, "true")
    assert _post(api, api_base).status_code == 422


def test_los_mensajes_de_error_son_neutros(api):
    for base in SEIS_DE_H1:
        texto = _post(api, base).text.lower()
        for prohibido in ("engine", "litellm", "presidio", "docker", "compose", "metadata", "ssrf"):
            assert prohibido not in texto


# ── la sonda de despliegue de Azure no llama a una dirección rechazada ───────────────────────────────

def test_la_sonda_de_azure_no_llama_a_una_base_rechazada(api, monkeypatch):
    llamadas = []
    monkeypatch.setattr(admin, "DEPLOYMENT_PROBE", lambda e, c: llamadas.append(e.api_base) or {"status": "ok"})
    azure = {"provider": "azure", "real_model": "gpt-5.1-chat",
             "credential": {"new": {"name": "az", "value": {"api_key": VALOR_SECRETO, "api_version": "2025-04-01"}}}}
    # alta con una base rechazada: ni se crea ni se sondea
    assert _post(api, "http://engine:4000", name="Azure malo", **azure).status_code == 422
    assert llamadas == []
    # una entrada cargada con el interruptor y revisada después con el interruptor apagado: la sonda no sale
    monkeypatch.setenv(ab.ALLOW_PRIVATE_ENV, "true")
    r = _post(api, "https://recurso.interno.local", name="Azure local", **azure)
    assert r.status_code == 201, r.text
    assert llamadas == ["https://recurso.interno.local"]
    llamadas.clear()
    monkeypatch.delenv(ab.ALLOW_PRIVATE_ENV)
    r = api.call("POST", f"/entries/{r.json()['id']}/check", "tenant_admin")
    assert r.status_code == 200, r.text
    assert llamadas == []
    assert r.json()["deployment_check"]["status"] == "error"


def test_la_sonda_por_defecto_no_se_alcanza_con_una_base_rechazada(monkeypatch):
    """`default_deployment_probe` es lo que llama al motor: `_verify_deployment` no debe llegar a ella."""
    import types
    llamadas = []
    monkeypatch.setattr(admin, "default_deployment_probe", lambda e, c: llamadas.append(1) or {"status": "ok"})
    e = types.SimpleNamespace(level="tenant", api_base="http://engine:4000", provider="azure", real_model="x",
                              status="active", provider_options={}, id=uuid.uuid4(), tenant_id=T1)
    monkeypatch.setattr(admin.cs, "credential_of", lambda db, e: None)
    monkeypatch.setattr(admin, "_audit", lambda *a, **k: None)
    out = admin._verify_deployment(None, types.SimpleNamespace(id=uuid.uuid4(), tenant_id=T1, role="tenant_admin"), e)
    assert out["status"] == "error" and llamadas == []
