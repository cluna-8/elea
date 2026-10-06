"""Pasarela REAL del backend + motor falso (httpx doblado) para las pruebas de contrato de la cara Claude
(T034–T036). Sin Docker ni Postgres; necesita el venv del backend (`src.api.gateway`).

    env = gateway_env(monkeypatch)        # {"client", "audits", "engine"}
    env.register(snapshot)                # registra el plugin con ese estado de la política
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
gateway = pytest.importorskip("src.api.gateway", reason="requiere el venv del backend")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from src.api import gateway_openai  # noqa: E402
from src.api import gateway_plugins as gp  # noqa: E402

from sentinel.redirect import authz  # noqa: E402
from sentinel.redirect.plugin import RedirectPlugin  # noqa: E402
from sentinel.tests import redirect_fixtures as fx  # noqa: E402

VK = "sk-sentinel-contract-0001"
COUNT_FROM_ENGINE = 7777        # lo que contesta el motor a un count_tokens reenviado (distinguible de una estimación)


class _Resp:
    def __init__(self, status, content, chunks=(), delay=0.0, ctype="application/json", headers=None):
        self.status_code, self.content, self._chunks, self._delay = status, content, chunks, delay
        self.headers = {"content-type": ctype, **(headers or {})}

    def json(self):
        return json.loads(self.content)

    async def aiter_raw(self):
        for i, c in enumerate(self._chunks):
            if isinstance(c, (int, float)):          # un número = silencio del destino
                await asyncio.sleep(c)
                continue
            if i and self._delay:
                await asyncio.sleep(self._delay)
            if isinstance(c, BaseException):
                raise c
            yield c

    async def aread(self):
        return self.content

    async def aclose(self):
        pass


class Engine:
    """Motor falso: registra cada envío (motor y proveedor) y contesta según su configuración."""
    sent: list = []
    status = 200
    error_body = b'{"error": {"message": "upstream"}}'
    error_headers: dict = {}
    stream_chunks: tuple = ()
    stream_delay = 0.0
    models = {"data": [{"id": "modelo-base"}, {"id": "rdx-chatcompat/gpt-image-1"}], "object": "list"}

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    @classmethod
    def reset(cls):
        cls.sent, cls.status, cls.stream_chunks, cls.stream_delay = [], 200, (), 0.0
        cls.error_body, cls.error_headers = b'{"error": {"message": "upstream"}}', {}

    def _reply(self, url, headers, content, stream=False):
        body = json.loads(content) if content else {}
        Engine.sent.append({"url": url, "headers": dict(headers or {}), "body": body})
        if url.split("?")[0].endswith("/v1/models"):
            return _Resp(200, json.dumps(Engine.models).encode())
        if Engine.status != 200:
            return _Resp(Engine.status, Engine.error_body, headers=Engine.error_headers)
        if url.split("?")[0].endswith("/count_tokens"):
            return _Resp(200, json.dumps({"input_tokens": COUNT_FROM_ENGINE}).encode())
        if stream:
            return _Resp(200, b"", ctype="text/event-stream", delay=Engine.stream_delay,
                         chunks=Engine.stream_chunks or (
                             b'event: message_start\ndata: {"type":"message_start","message":'
                             b'{"id":"m1","model":"qwen-destino","usage":{"input_tokens":3}}}\n\n',
                             b'event: message_stop\ndata: {"type":"message_stop"}\n\n'))
        return _Resp(200, json.dumps({"id": "m1", "type": "message", "model": "qwen-destino", "content": [],
                                      "usage": {"input_tokens": 1, "output_tokens": 1}}).encode())

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


def gateway_env(monkeypatch, *, ident=None, ping_after=0.05):
    Engine.reset()
    gp.clear_gateway_plugins()
    monkeypatch.delenv(gp.PLUGINS_ENV, raising=False)
    monkeypatch.setenv(authz.KEY_ENV, fx.INTERNAL_KEY)
    monkeypatch.setattr("src.services.auto_router_service.load_config", lambda: {})
    audits = []
    monkeypatch.setattr(gateway.httpx, "AsyncClient", Engine)
    monkeypatch.setattr(gateway, "_audit", lambda *a, **k: audits.append((a, k)) or True)
    monkeypatch.setattr(gateway, "_publish_monitor", lambda *a, **k: None)
    monkeypatch.setattr(gateway, "_audit_precheck_ok", lambda *_a: True)
    monkeypatch.setattr(gateway, "_resolve_attribution", lambda _k: ident or fx.ident())
    app = FastAPI()
    app.include_router(gateway.router)
    app.include_router(gateway_openai.router)

    def register(snap, *, key_models=None, **plugin_kw):
        plugin = RedirectPlugin(store=fx.store(snap, key_models=key_models), ping_after=ping_after, **plugin_kw)
        gp.register_gateway_plugin(plugin)
        return plugin

    env = SimpleNamespace(client=TestClient(app), audits=audits, engine=Engine, register=register)
    return env


def close_env():
    gp.clear_gateway_plugins()
