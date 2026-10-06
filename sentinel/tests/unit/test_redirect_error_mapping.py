"""Rechazos del guard ≠ fallas del proveedor (hallazgo de la demo del 28-sep, 069 FR-008d / D25).

Un 403 del guard (`masking_required`, `authz_*`) es definitivo: reintentar no cambia nada. Antes se
traducía como 502 reintentable y Claude Desktop reintentaba 10 veces sin mostrar el motivo."""
import json

import pytest

import redirect_fixtures as fx
from sentinel.redirect.plugin import RedirectPlugin

# Formas reales en que el motor devuelve la HTTPException del guard (vistas en nix y en el spike S1)
PY_REPR = (b'{"error":{"message":"{\'error\': \'El pedido no pudo protegerse para este destino y fue '
           b'bloqueado.\', \'code\': \'masking_required\', \'guardrail_name\': \'redirect-guard\'}",'
           b'"type":"None","param":"None","code":"403"}}')
JSON_FIELDS = (b'{"error":{"message":"Destino no autorizado.","type":"None","param":"None","code":"403",'
               b'"provider_specific_fields":{"error":"Destino no autorizado.","code":"authz_expired"}}}')
MISCONF = (b'{"error":{"message":"{\'error\': \'Modelo no disponible temporalmente.\', '
           b'\'code\': \'destination_misconfigured\'}","code":"503"}}')


def plugin(snap):
    return RedirectPlugin(store=fx.store(snap))


async def _plan(route="/v1/messages", model="claude-sonnet-4-5"):
    p, c = plugin(fx.snapshot("on")), fx.ctx(route=route, model=model)
    assert await p.pre_request(c) is None
    return p, c


def _retry(headers):
    return {k.lower(): v for k, v in headers.items()}.get("x-should-retry")


@pytest.mark.parametrize("route,model", [("/v1/messages", "claude-sonnet-4-5"),
                                         ("/v1/chat/completions", "pro")])
async def test_masking_required_es_definitivo_y_claro(route, model):
    p, c = await _plan(route, model)
    st, body, headers = p.map_error(c, 403, PY_REPR)
    err = json.loads(body)["error"]
    claude = route == "/v1/messages"
    # cara Claude: 400 (Claude Desktop muestra «Failed to authenticate» ante un 403)
    assert (st, err["type"]) == ((400, "invalid_request_error") if claude else (403, "permission_error"))
    assert "no pudo protegerse" in err["message"] and "larga" not in err["message"]
    assert _retry(headers) is None


async def test_autorizacion_del_guard_es_definitiva():
    p, c = await _plan()
    st, body, headers = p.map_error(c, 403, JSON_FIELDS)
    assert st == 400 and _retry(headers) is None
    assert json.loads(body)["error"]["type"] == "invalid_request_error"


async def test_destino_mal_configurado_no_se_reintenta():
    p, c = await _plan()
    st, body, headers = p.map_error(c, 503, MISCONF)
    assert _retry(headers) is None and st == 400
    assert "administrador" in json.loads(body)["error"]["message"]


async def test_falla_del_proveedor_sigue_reintentable():
    p, c = await _plan()
    st, body, headers = p.map_error(c, 500, b'{"error":{"message":"upstream boom"}}')
    assert st == 529 and _retry(headers) == "true"
    st, body, headers = p.map_error(c, 403, b'{"error":{"message":"invalid api key"}}')
    assert st == 502                      # 403 del PROVEEDOR: nuestra credencial de destino
