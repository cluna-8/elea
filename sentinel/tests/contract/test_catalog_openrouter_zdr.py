"""OpenRouter con cero retención en el alta (057 FR-032; research R19; contracts/admin-api.md «OpenRouter»).

Alta o edición de una entrada `openrouter` sin `provider_options.providers_allowlist` no vacía ⇒ 422; `zdr` y
`data_collection` no se aceptan en contra del cero retención (`zdr: false`, `data_collection: allow`). El efecto en
cada pedido —cero retención, sin recolección y solo a la lista— lo fija el guard (`unit/test_guard_openrouter_zdr.py`)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from catalog_fixtures import entry_body, make_api  # noqa: E402


@pytest.fixture
def api(monkeypatch):
    return make_api(monkeypatch)


def post(api, **kw):
    kw.setdefault("name", "OR")
    return api.call("POST", "/entries", "tenant_admin", json=entry_body(**kw))


def test_alta_sin_lista_de_proveedores_es_422(api):
    r = post(api, provider_options={})
    assert r.status_code == 422 and "providers_allowlist" in r.text


@pytest.mark.parametrize("lista", [[], "acme", [""], [" "], [1], None, {"a": 1}])
def test_alta_con_una_lista_que_no_sirve_es_422(api, lista):
    assert post(api, provider_options={"providers_allowlist": lista}).status_code == 422


def test_alta_con_lista_es_201(api):
    r = post(api, provider_options={"providers_allowlist": ["acme-us", "otro-us"]})
    assert r.status_code == 201, r.text


@pytest.mark.parametrize("opts", [{"zdr": False}, {"data_collection": "allow"}, {"zdr": "no"}, {"data_collection": 1}])
def test_zdr_y_data_collection_en_contra_no_se_aceptan(api, opts):
    r = post(api, provider_options={"providers_allowlist": ["acme-us"], **opts})
    assert r.status_code == 422


def test_zdr_true_y_data_collection_deny_se_aceptan(api):
    r = post(api, provider_options={"providers_allowlist": ["acme-us"], "zdr": True, "data_collection": "deny"})
    assert r.status_code == 201


def test_un_proveedor_que_no_es_openrouter_no_exige_la_lista(api):
    r = post(api, provider="openai_compatible", real_model="m", api_base="https://api.ejemplo.com/v1",
             provider_options={})
    assert r.status_code == 201, r.text


def test_patch_que_deja_la_entrada_sin_lista_es_422(api):
    e = post(api, provider_options={"providers_allowlist": ["acme-us"]}).json()
    assert api.call("PATCH", f"/entries/{e['id']}", "tenant_admin", json={"provider_options": {}}).status_code == 422
    assert api.call("PATCH", f"/entries/{e['id']}", "tenant_admin",
                    json={"provider_options": {"providers_allowlist": []}}).status_code == 422
    assert api.call("PATCH", f"/entries/{e['id']}", "tenant_admin",
                    json={"provider_options": {"providers_allowlist": ["acme-us"], "zdr": False}}).status_code == 422
    ok = api.call("PATCH", f"/entries/{e['id']}", "tenant_admin",
                  json={"provider_options": {"providers_allowlist": ["otro-us"]}})
    assert ok.status_code == 200


def test_patch_de_otro_campo_no_toca_la_lista(api):
    e = post(api, provider_options={"providers_allowlist": ["acme-us"]}).json()
    assert api.call("PATCH", f"/entries/{e['id']}", "tenant_admin", json={"context_window": 64000}).status_code == 200


def test_pasar_una_entrada_a_openrouter_sin_lista_es_422(api):
    e = post(api, provider="openai_compatible", real_model="m", api_base="https://api.ejemplo.com/v1",
             provider_options={}).json()
    r = api.call("PATCH", f"/entries/{e['id']}", "tenant_admin", json={"provider": "openrouter", "api_base": None})
    assert r.status_code == 422
