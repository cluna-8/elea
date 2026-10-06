"""057 T076 (FR-046; decisión del coordinador 2026-10-06): la fila de auditoría del camino no-stream de ``/gw/v1/messages``
(suscripción/passthrough) se escribe DESPUÉS de ``map_response`` de los plugins, dentro de un ``try/finally``.

Por qué: un plugin que lee el ``usage`` de la respuesta (tokens de caché leídos y escritos) lo suma a su
``routing_decision``; con la auditoría antes de ``map_response`` esa fila salía sin ellos (el stream sí los llevaba: su fila se
escribe al cerrar la respuesta). Y si ``map_response`` lanza, la fila se escribe igual, con la decisión que haya y el estado
``upstream_error`` (no hay respuesta que entregar). Sin plugins, la fila es la de siempre."""
import copy
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import gateway
from src.api import gateway_plugins as gp

BODY = {"model": "m-1", "messages": [{"role": "user", "content": "hola"}]}
USAGE_CACHE = {"input_tokens": 10, "output_tokens": 2, "cache_read_input_tokens": 7, "cache_creation_input_tokens": 3}


class _Resp:
    def __init__(self, status, content):
        self.status_code, self.content = status, content
        self.headers = {"content-type": "application/json"}

    def json(self):
        return json.loads(self.content)


class _Fake:
    status = 200
    content = json.dumps({"type": "message", "model": "m", "usage": USAGE_CACHE}).encode()

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, headers=None, content=None):
        return _Resp(_Fake.status, _Fake.content)

    async def aclose(self):
        pass


@pytest.fixture
def espias(monkeypatch):
    _Fake.status = 200
    gp.clear_gateway_plugins()
    monkeypatch.delenv(gp.PLUGINS_ENV, raising=False)
    filas, orden = [], []

    def _audit(*a, **k):
        # fotografía de la decisión AL MOMENTO de escribir la fila
        filas.append({"args": a, "routing_decision": copy.deepcopy(k.get("routing_decision")), "orden": len(orden)})
        orden.append("audit")
        return True

    monkeypatch.setattr(gateway.httpx, "AsyncClient", _Fake)
    monkeypatch.setattr(gateway, "_audit", _audit)
    monkeypatch.setattr(gateway, "_publish_monitor", lambda *a, **k: None)
    monkeypatch.setattr(gateway, "_audit_precheck_ok", lambda *_a: True)
    monkeypatch.setattr(gateway, "_resolve_attribution", lambda _k: {
        "tenant_id": "t", "api_key_id": "k", "user_id": None, "group_id": None, "redact_enabled": False,
        "governance_decisions": (), "nlp": {}, "applied_risk_level": "minimal"})
    app = FastAPI()
    app.include_router(gateway.router)
    yield {"client": TestClient(app, raise_server_exceptions=False), "filas": filas, "orden": orden}
    gp.clear_gateway_plugins()


def _status_de(fila):
    return fila["args"][4]


def test_la_fila_del_no_stream_lleva_lo_que_map_response_suma_a_la_decision(espias):
    class P:
        def pre_request(self, ctx):
            ctx.routing_decision = {"extensions": {"x": {"face": "claude"}}}

        def map_response(self, ctx, status, content):
            usage = json.loads(content)["usage"]
            ctx.routing_decision["extensions"]["x"].update(cache_read_tokens=usage["cache_read_input_tokens"],
                                                           cache_write_tokens=usage["cache_creation_input_tokens"])
            return None

    gp.register_gateway_plugin(P())
    r = espias["client"].post("/gw/v1/messages", json=BODY)
    assert r.status_code == 200
    (fila,) = espias["filas"]
    assert fila["routing_decision"]["extensions"]["x"] == {"face": "claude", "cache_read_tokens": 7,
                                                           "cache_write_tokens": 3}
    assert _status_de(fila) != "upstream_error"


def test_si_map_response_lanza_la_fila_se_escribe_igual_con_la_decision_que_haya(espias):
    class P:
        def pre_request(self, ctx):
            ctx.routing_decision = {"extensions": {"x": {"face": "claude"}}}

        def map_response(self, ctx, status, content):
            raise RuntimeError("falla del plugin")

    gp.register_gateway_plugin(P())
    r = espias["client"].post("/gw/v1/messages", json=BODY)
    assert r.status_code == 500
    (fila,) = espias["filas"]
    assert fila["routing_decision"] == {"extensions": {"x": {"face": "claude"}}}
    assert _status_de(fila) == "upstream_error"


def test_la_fila_se_escribe_una_sola_vez_tambien_ante_un_error_del_destino(espias):
    _Fake.status = 429

    class P:
        def map_error(self, ctx, status, body):
            return 503, b'{"mapeado": true}', None

    gp.register_gateway_plugin(P())
    espias["client"].post("/gw/v1/messages", json=BODY)
    assert len(espias["filas"]) == 1 and _status_de(espias["filas"][0]) == "upstream_error"


def test_sin_plugins_la_fila_es_la_de_siempre(espias):
    r = espias["client"].post("/gw/v1/messages", json=BODY)
    assert r.status_code == 200
    (fila,) = espias["filas"]
    assert fila["routing_decision"] is None
    assert fila["args"][2:4] == (10, 2)
