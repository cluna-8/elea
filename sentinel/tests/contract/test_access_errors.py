"""Errores de acceso por cara (069 US2; contracts/errores-por-cara.md; D9; T043).

403 «modelo no permitido» en las dos caras (nunca 401: dispara reloguear en las herramientas),
503 `policy_unavailable` si no se pueden resolver los permitidos (fail-closed, FR-014a), y textos
neutros: jamás nombran motor, destino ni proveedor."""
import json

import pytest

from sentinel.access import bridge
from sentinel.redirect import authz
from sentinel.redirect.faces import claude as claude_face
from sentinel.redirect.faces import generic as generic_face
from sentinel.redirect.plugin import RedirectPlugin
from sentinel.tests import redirect_fixtures as fx

MENSAJE = "Este modelo no está permitido para tu perfil."


@pytest.fixture(autouse=True)
def _bridge(monkeypatch):
    monkeypatch.setenv(authz.KEY_ENV, fx.INTERNAL_KEY)
    monkeypatch.setattr(bridge, "RISK", lambda ident: (None, None))
    monkeypatch.setattr(bridge, "CATALOG", lambda tenant: {"gpt-x": {}, "local-y": {}})
    monkeypatch.setattr(bridge, "RESOLVER", lambda tenant, **kw: frozenset({"local-y"}))


def body_of(resp):
    return json.loads(resp.body)


def test_cara_claude_403_permission_error():
    status, headers, body = claude_face.error_response("model_not_allowed")
    assert status == 403 and status != 401
    assert body == {"type": "error", "error": {"type": "permission_error", "message": MENSAJE}}
    assert "x-should-retry" not in headers


def test_cara_generica_403_con_codigo():
    status, headers, body = generic_face.error_response("model_not_allowed")
    assert status == 403
    assert body == {"error": {"message": MENSAJE, "type": "permission_error", "param": None,
                              "code": "model_not_allowed"}}
    assert "retry-after" not in headers


@pytest.mark.parametrize("route,face", [("/v1/messages", "claude"), ("/v1/chat/completions", "generic")])
async def test_el_plugin_corta_con_el_error_de_la_cara(route, face):
    c = fx.ctx(route=route, model="gpt-x")
    resp = await RedirectPlugin(store=fx.store(None)).pre_request(c)
    assert resp.status_code == 403
    body = body_of(resp)
    if face == "claude":
        assert body["error"]["type"] == "permission_error" and body["type"] == "error"
    else:
        assert body["error"]["code"] == "model_not_allowed"
    assert body["error"]["message"] == MENSAJE
    for prohibida in ("litellm", "openai", "anthropic", "gpt-x"):
        assert prohibida not in resp.body.decode().lower()


@pytest.mark.parametrize("route", ["/v1/messages", "/v1/chat/completions"])
async def test_falla_del_resolutor_es_503_policy_unavailable(monkeypatch, route):
    def boom(tenant, **kw):
        raise RuntimeError("base caída")
    monkeypatch.setattr(bridge, "RESOLVER", boom)
    resp = await RedirectPlugin(store=fx.store(None)).pre_request(fx.ctx(route=route, model="gpt-x"))
    assert resp.status_code == 503
    assert resp.status_code != 401
    if route == "/v1/messages":
        assert resp.headers["x-should-retry"] == "true"
        assert body_of(resp)["error"]["type"] == "api_error"
    assert "caída" not in resp.body.decode()


async def test_falla_del_resolutor_no_se_abre_ni_con_modelo_desconocido(monkeypatch):
    monkeypatch.setattr(bridge, "RESOLVER", lambda tenant, **kw: (_ for _ in ()).throw(RuntimeError()))
    resp = await RedirectPlugin(store=fx.store(None)).pre_request(fx.ctx(model="cualquiera"))
    assert resp is not None and resp.status_code == 503


def test_map_error_nunca_devuelve_401_por_acceso():
    # el rechazo del motor por acceso de llave se presenta como 403 de Sentinel, jamás 401 (D9)
    assert claude_face.error_response("model_not_allowed")[0] == 403
    assert generic_face.error_response("model_not_allowed")[0] == 403
