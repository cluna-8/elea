"""Plugin + pasarela REAL del backend + motor falso (httpx doblado); sin Docker ni Postgres.

Corre con el venv del backend (necesita `src.api.gateway`); con otro intérprete se saltea:

    cd sentinel/tests && ../../backend/.venv/bin/python -m pytest integration/test_redirect_gateway_e2e.py

Cubre T039 (no-regresión: sin filas ⇒ lo mismo que sin plugin), T035 (`rdx-*` fuera de
`/gw/v1/models`), la cara genérica y la cara Claude de punta a punta (stream con `ping` y
`model` público), y la autorización interna verificada por el guard del motor.
"""
import asyncio
import json
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))
gateway = pytest.importorskip("src.api.gateway", reason="requiere el venv del backend")
from src.api import gateway_openai  # noqa: E402
from src.api import gateway_plugins as gp  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from sentinel.engine import redirect_guard as guard  # noqa: E402
from sentinel.redirect import authz  # noqa: E402
from sentinel.redirect.plugin import RedirectPlugin  # noqa: E402
from sentinel.tests import redirect_fixtures as fx  # noqa: E402

VK = "sk-sentinel-e2e-0001"
MODELS = {"data": [{"id": "modelo-base"}, {"id": "rdx-chatcompat/gpt-image-1"},
                   {"id": "rdx-anthropic/claude-x"}], "object": "list"}


class _Resp:
    def __init__(self, status, content, chunks=(), delay=0.0, ctype="application/json"):
        self.status_code, self.content, self._chunks, self._delay = status, content, chunks, delay
        self.headers = {"content-type": ctype}

    def json(self):
        return json.loads(self.content)

    async def aiter_raw(self):
        for i, c in enumerate(self._chunks):
            if i and self._delay:
                await asyncio.sleep(self._delay)
            yield c

    async def aread(self):
        return self.content

    async def aclose(self):
        pass


class Engine:
    """Motor falso: registra cada pedido y contesta según la ruta y el modelo recibido."""
    sent: list = []
    status = 200
    stream_delay = 0.0

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def _reply(self, url, headers, content, stream=False):
        body = json.loads(content) if content else {}
        Engine.sent.append({"url": url, "headers": dict(headers or {}), "body": body})
        if url.endswith("/v1/models"):
            return _Resp(200, json.dumps(MODELS).encode())
        model = body.get("model")
        if Engine.status != 200:
            return _Resp(Engine.status, b'{"error": {"message": "upstream"}}')
        if url.endswith("/v1/messages"):
            if stream:
                return _Resp(200, b"", ctype="text/event-stream", delay=Engine.stream_delay, chunks=(
                    b'event: message_start\ndata: {"type":"message_start","message":'
                    b'{"id":"m1","model":"qwen-destino","usage":{"input_tokens":3}}}\n\n',
                    b'event: content_block_delta\ndata: {"type":"content_block_delta","index":0,'
                    b'"delta":{"type":"text_delta","text":"hola"}}\n\n',
                    b'event: message_stop\ndata: {"type":"message_stop"}\n\n'))
            return _Resp(200, json.dumps({"id": "m1", "type": "message", "model": "qwen-destino",
                                          "content": [], "usage": {"input_tokens": 1,
                                                                   "output_tokens": 1}}).encode())
        if stream:
            return _Resp(200, b"", ctype="text/event-stream", chunks=(
                b'data: {"id":"c1","model":"qwen-destino","choices":[{"delta":{"content":"ho"}}]}\n\n',
                b"data: [DONE]\n\n"))
        return _Resp(200, json.dumps({"id": "c1", "object": "chat.completion", "model": model or "x",
                                      "choices": []}).encode())

    async def post(self, url, headers=None, content=None):
        return self._reply(url, headers, content)

    async def get(self, url, headers=None):
        return self._reply(url, headers, None)

    def build_request(self, _m, url, headers=None, content=None):
        return (url, headers, content)

    async def send(self, req, stream=False):
        return self._reply(*req, stream=True)

    async def aclose(self):
        pass


@pytest.fixture
def env(monkeypatch):
    Engine.sent, Engine.status, Engine.stream_delay = [], 200, 0.0
    gp.clear_gateway_plugins()
    monkeypatch.delenv(gp.PLUGINS_ENV, raising=False)
    monkeypatch.setenv(authz.KEY_ENV, fx.INTERNAL_KEY)
    # Sin router configurado «auto» no se suma al listado (069 T186); el caso con router va aparte.
    monkeypatch.setattr("src.services.auto_router_service.load_config", lambda: {})
    audits = []
    monkeypatch.setattr(gateway.httpx, "AsyncClient", Engine)
    monkeypatch.setattr(gateway, "_audit", lambda *a, **k: audits.append((a, k)) or True)
    monkeypatch.setattr(gateway, "_publish_monitor", lambda *a, **k: None)
    monkeypatch.setattr(gateway, "_audit_precheck_ok", lambda *_a: True)
    monkeypatch.setattr(gateway, "_resolve_attribution", lambda _k: fx.ident())
    app = FastAPI()
    app.include_router(gateway.router)
    app.include_router(gateway_openai.router)
    yield {"client": TestClient(app), "audits": audits}
    gp.clear_gateway_plugins()


def _register(snap, **kw):
    gp.register_gateway_plugin(RedirectPlugin(store=fx.store(snap, **kw), ping_after=0.05))


def _chat(c, model="pro", stream=False, **extra):
    return c.post("/gw/v1/chat/completions", headers={"Authorization": f"Bearer {VK}"},
                  json={"model": model, "messages": [{"role": "user", "content": "hola"}],
                        "stream": stream, **extra})


def _messages(c, model="claude-sonnet-4-5", stream=False):
    return c.post("/gw/v1/messages", headers={"Authorization": f"Bearer {VK}",
                                              "anthropic-version": "2023-06-01",
                                              "anthropic-beta": "algo-2025"},
                  json={"model": model, "max_tokens": 16, "stream": stream,
                        "messages": [{"role": "user", "content": "hola"}]})


# ── T039: no-regresión ────────────────────────────────────────────────────────

@pytest.mark.parametrize("call", ["chat", "chat_stream", "messages", "messages_stream"])
def test_sin_filas_el_plugin_no_cambia_nada(env, call):
    def run():
        c = env["client"]
        r = {"chat": lambda: _chat(c), "chat_stream": lambda: _chat(c, stream=True),
             "messages": lambda: _messages(c), "messages_stream": lambda: _messages(c, stream=True)
             }[call]()
        sent = Engine.sent[-1]
        return (r.status_code, r.content, sent["url"], sent["body"],
                {k: v for k, v in sent["headers"].items()})

    base = run()
    _register(None)
    with_plugin = run()
    assert with_plugin == base
    assert authz.HEADER not in {k.lower() for k in Engine.sent[-1]["headers"]}


def test_sin_filas_el_listado_solo_pierde_rdx(env):
    c = env["client"]
    base = c.get("/gw/v1/models", headers={"Authorization": f"Bearer {VK}"}).json()
    _register(None)
    out = c.get("/gw/v1/models", headers={"Authorization": f"Bearer {VK}"}).json()
    assert [m["id"] for m in base["data"]] == ["modelo-base", "rdx-chatcompat/gpt-image-1",
                                               "rdx-anthropic/claude-x"]
    assert out == {**base, "data": [{"id": "modelo-base"}]}


def test_politica_on_con_otro_modelo_no_publicado_sin_cambios(env):
    _register(fx.snapshot("on"))
    r = _chat(env["client"], model="modelo-base")
    assert r.status_code == 200 and Engine.sent[-1]["body"]["model"] == "modelo-base"
    assert authz.HEADER not in {k.lower() for k in Engine.sent[-1]["headers"]}


# ── cara genérica ─────────────────────────────────────────────────────────────

def test_cara_generica_no_stream(env):
    _register(fx.snapshot("on"))
    r = _chat(env["client"], api_base="http://atacante")
    sent = Engine.sent[-1]
    assert sent["url"].endswith("/v1/chat/completions")
    assert sent["body"]["model"] == "rdx-chatcompat/qwen-destino" and "api_base" not in sent["body"]
    assert r.status_code == 200 and r.json()["model"] == "pro"
    # el guard del motor acepta lo que mandó la pasarela
    data = {**sent["body"], "proxy_server_request": {"headers": sent["headers"]}, "metadata": {}}
    out = guard.apply_redirect(data, environ={})
    assert out["api_key"] == "sk-destino-chat" and out["api_base"] == "http://destino.local/v1"
    # y rechaza la misma autorización para otro modelo
    data = {**sent["body"], "model": "rdx-chatcompat/otro",
            "proxy_server_request": {"headers": sent["headers"]}}
    with pytest.raises(guard.GuardRejection):
        guard.apply_redirect(data, environ={})


def test_cara_generica_stream_reescribe_el_modelo(env):
    _register(fx.snapshot("on"))
    r = _chat(env["client"], stream=True)
    assert r.status_code == 200
    assert b'"model":"pro"' in r.content and b"qwen-destino" not in r.content
    assert r.content.rstrip().endswith(b"data: [DONE]")


def test_cara_generica_error_con_forma_de_cara(env):
    _register(fx.snapshot("on"))
    Engine.status = 503
    r = _chat(env["client"])
    assert r.status_code == 503 and r.json()["error"]["type"] == "api_error"
    assert "upstream" not in r.text


def test_cara_generica_sin_destino_es_404_auditado(env):
    _register(fx.snapshot("on", targets=("no-existe",)))
    n = len(Engine.sent)
    r = _chat(env["client"])
    assert r.status_code == 404 and r.json()["error"]["code"] == "model_not_found"
    assert len(Engine.sent) == n, "no llega al motor"
    (args, kw), = env["audits"]
    assert args[4] == gp.STATUS_PLUGIN_BLOCK
    assert kw["routing_decision"]["extensions"]["redirect"]["unavailable"] == "no_eligible_target"


def test_listado_generico_con_politica_on(env):
    _register(fx.snapshot("on"))
    r = env["client"].get("/gw/v1/models", headers={"Authorization": f"Bearer {VK}"})
    assert [m["id"] for m in r.json()["data"]] == ["pro"]
    assert all(m["owned_by"] == "organization" for m in r.json()["data"])


@pytest.mark.skip(reason='Necesita fd515ff (ADAPT-052, _con_auto_en_listado), fuera del MVP: HANDOFF A.4. 057 T017')
def test_listado_generico_suma_auto_para_los_servicios(env, monkeypatch):
    # 069 T186: Presenton valida su modelo contra esta lista; «auto» va primero, y el catálogo
    # sigue filtrado por el acceso de la llave.
    monkeypatch.setattr("src.services.auto_router_service.load_config",
                        lambda: {"default_model": "pro"})
    _register(fx.snapshot("on"))
    r = env["client"].get("/gw/v1/models", headers={"Authorization": f"Bearer {VK}"})
    assert [m["id"] for m in r.json()["data"]] == ["auto", "pro"]


# ── cara Claude ───────────────────────────────────────────────────────────────

def test_cara_claude_no_stream(env):
    _register(fx.snapshot("on"))
    r = _messages(env["client"])
    sent = Engine.sent[-1]
    assert sent["url"].endswith("/v1/messages") and sent["body"]["model"] == "rdx-chatcompat/qwen-destino"
    assert "anthropic-beta" not in {k.lower() for k in sent["headers"]}   # traducido: se descarta
    assert r.status_code == 200 and r.json()["model"] == "claude-sonnet-4-5"


def test_cara_claude_stream_con_ping_y_modelo_publico(env):
    _register(fx.snapshot("on"))
    Engine.stream_delay = 0.2
    r = _messages(env["client"], stream=True)
    body = r.content
    assert r.status_code == 200
    assert b'"model":"claude-sonnet-4-5"' in body and b"qwen-destino" not in body
    assert b"event: ping" in body
    assert body.index(b"message_start") < body.index(b"event: ping") < body.index(b"message_stop")


def test_cara_claude_nativa_reenvia_anthropic_beta(env, monkeypatch):
    monkeypatch.setattr(gateway, "_resolve_attribution", lambda _k: fx.ident(nlp={"region": "us"}))
    _register(fx.snapshot("on", claude_targets=("d-ant",)))
    _messages(env["client"])
    sent = Engine.sent[-1]
    assert sent["body"]["model"] == "rdx-anthropic/claude-real"
    assert {k.lower(): v for k, v in sent["headers"].items()}["anthropic-beta"] == "algo-2025"


def test_cara_claude_listado_anthropic(env):
    _register(fx.snapshot("on"))
    r = env["client"].get("/gw/v1/models", headers={"Authorization": f"Bearer {VK}",
                                                    "anthropic-version": "2023-06-01"})
    data = r.json()
    assert [m["id"] for m in data["data"]] == ["claude-sonnet-4-5"]
    assert data["has_more"] is False and data["data"][0]["type"] == "model"


# ── sombra ────────────────────────────────────────────────────────────────────

def test_sombra_sirve_igual_y_firma_la_decision(env):
    base_r = _chat(env["client"])
    base = (base_r.status_code, base_r.content, Engine.sent[-1]["body"])
    _register(fx.snapshot("shadow"))
    r = _chat(env["client"])
    sent = Engine.sent[-1]
    assert (r.status_code, r.content, sent["body"]) == base
    tok = {k.lower(): v for k, v in sent["headers"].items()}[authz.HEADER]
    grant = authz.verify(tok, expected_model="pro")
    assert grant.decision["shadow"] is True and grant.credential == {}
