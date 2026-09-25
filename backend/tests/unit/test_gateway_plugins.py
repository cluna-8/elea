"""Plugins de la pasarela ``/gw`` (``src/api/gateway_plugins.py``).

Lo primero que se fija es la propiedad de identidad: SIN plugins registrados, lo que sale
hacia el motor/upstream y lo que vuelve al cliente es byte a byte lo de siempre (body
verbatim, los 4 headers del byok, respuesta de ``/v1/models`` sin re-serializar, fila de
auditoría sin claves nuevas, byok sin resolver identidad). Después, un test por hook.

Sin base ni motor: el ``httpx`` del módulo se dobla con un fake que captura lo enviado, y la
auditoría/pre-check/atribución se reemplazan por espías (este archivo no estudia auditoría).
"""
import contextlib
import json
import sys
import uuid

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from src.api import gateway
from src.api import gateway_plugins as gp

KEY = "sk-sentinel-abc123"
EMAIL = "juan.perez@hospital.es"
BODY = {"model": "m-1", "messages": [{"role": "user", "content": f"hola {EMAIL}"}]}
MODELS_RAW = b'{"data": [ {"id": "a"}, {"id":"b"} ],  "has_more":false}'


class _Resp:
    def __init__(self, status, content, ctype="application/json"):
        self.status_code, self.content = status, content
        self.headers = {"content-type": ctype}

    def json(self):
        return json.loads(self.content)

    async def aiter_raw(self):
        for c in (b"data: uno\n\n", b"data: dos\n\n"):
            yield c

    async def aread(self):
        return self.content

    async def aclose(self):
        pass


class _Fake:
    """Hace de motor y de upstream: registra cada envío y contesta lo configurado."""
    enviados: list = []
    status = 200
    content = b'{"ok": 1,  "usage": {"input_tokens": 1, "output_tokens": 2}}'

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def _anotar(self, url, headers, content):
        _Fake.enviados.append({"url": url, "headers": dict(headers or {}), "content": content})
        body = MODELS_RAW if url.endswith("/v1/models") else _Fake.content
        return _Resp(_Fake.status, body)

    async def post(self, url, headers=None, content=None):
        return self._anotar(url, headers, content)

    async def get(self, url, headers=None):
        return self._anotar(url, headers, None)

    def build_request(self, _m, url, headers=None, content=None):
        return (url, headers, content)

    async def send(self, req, stream=False):
        return self._anotar(*req)

    async def aclose(self):
        pass


@pytest.fixture
def espias(monkeypatch):
    _Fake.enviados, _Fake.status = [], 200
    gp.clear_gateway_plugins()
    monkeypatch.delenv(gp.PLUGINS_ENV, raising=False)
    s = {"audit": [], "attr": 0, "nlp": []}

    def _attr(_key):
        s["attr"] += 1
        return {"tenant_id": str(uuid.uuid4()), "api_key_id": str(uuid.uuid4()),
                "user_id": None, "group_id": None, "redact_enabled": False,
                "governance_decisions": (), "nlp": {}, "applied_risk_level": "minimal"}

    real_eval = gateway.evaluate_request_policy

    async def _eval(body, profile=None, nlp=None):
        s["nlp"].append(nlp)
        return await real_eval(body, profile, nlp)

    monkeypatch.setattr(gateway.httpx, "AsyncClient", _Fake)
    monkeypatch.setattr(gateway, "_audit", lambda *a, **k: s["audit"].append((a, k)) or True)
    monkeypatch.setattr(gateway, "_publish_monitor", lambda *a, **k: None)
    monkeypatch.setattr(gateway, "_audit_precheck_ok", lambda *_a: True)
    monkeypatch.setattr(gateway, "_resolve_attribution", _attr)
    monkeypatch.setattr(gateway, "evaluate_request_policy", _eval)
    app = FastAPI()
    app.include_router(gateway.router)
    s["client"] = TestClient(app)
    yield s
    gp.clear_gateway_plugins()


def _byok(c, **kw):
    return c.post("/gw/v1/messages", content=json.dumps(BODY).encode(),
                  headers={"Authorization": f"Bearer {KEY}", "x-extra": "1", **kw})


# ── identidad sin plugins ─────────────────────────────────────────────────────────

def test_sin_plugins_byok_va_verbatim_con_los_cuatro_headers_y_sin_resolver_identidad(espias):
    raw = json.dumps(BODY).encode()
    r = _byok(espias["client"])
    enviado = _Fake.enviados[0]
    assert enviado["content"] == raw
    assert set(enviado["headers"]) == {"Content-Type", "Accept-Encoding", "anthropic-version",
                                       "Authorization"}
    assert r.content == _Fake.content
    assert espias["attr"] == 0 and espias["audit"] == []


def test_sin_plugins_models_devuelve_los_bytes_del_upstream_sin_reserializar(espias):
    r = espias["client"].get("/gw/v1/models")
    assert r.content == MODELS_RAW


def test_sin_plugins_la_fila_de_auditoria_no_lleva_claves_nuevas(espias):
    espias["client"].post("/gw/v1/messages", json=BODY)
    (_args, kw), = espias["audit"]
    assert kw.get("routing_decision") is None  # el escritor recibe su default de siempre


# ── registro y carga ──────────────────────────────────────────────────────────────

def test_registro_idempotente_y_carga_desde_env(espias, monkeypatch, tmp_path):
    (tmp_path / "plug_demo_gw.py").write_text("class P:\n    pass\ngateway_plugin = P()\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setenv(gp.PLUGINS_ENV, " plug_demo_gw , ")
    assert len(gp.plugins()) == 1
    gp.register_gateway_plugin(gp.plugins()[0])
    assert len(gp.plugins()) == 1
    sys.modules.pop("plug_demo_gw", None)


def test_un_modulo_configurado_que_no_importa_levanta(espias, monkeypatch):
    monkeypatch.setenv(gp.PLUGINS_ENV, "no_existe_este_modulo_gw")
    with pytest.raises(ImportError):
        gp.plugins()


# ── hooks ─────────────────────────────────────────────────────────────────────────

class _Corta:
    def pre_request(self, ctx):
        ctx.state["visto"] = (ctx.route, ctx.mode, ctx.request_headers.get("x-extra"))
        return JSONResponse({"error": "no"}, status_code=403)


@pytest.mark.parametrize("modo", ["byok", "subscription"])
def test_pre_request_corta_sin_tocar_el_destino_y_audita(espias, modo):
    p = _Corta()
    gp.register_gateway_plugin(p)
    if modo == "byok":
        r = _byok(espias["client"])
    else:
        r = espias["client"].post("/gw/v1/messages", json=BODY, headers={"x-extra": "1"})
    assert r.status_code == 403 and _Fake.enviados == []
    (args, _kw), = espias["audit"]
    assert args[4] == gp.STATUS_PLUGIN_BLOCK


def test_pre_request_recibe_ruta_modo_y_headers(espias):
    seen = {}

    class P:
        def pre_request(self, ctx):
            seen.update(route=ctx.route, mode=ctx.mode, h=ctx.request_headers.get("x-extra"))

    gp.register_gateway_plugin(P())
    _byok(espias["client"])
    assert seen == {"route": "/v1/messages", "mode": "byok", "h": "1"}


def test_pre_engine_y_allowlist_en_byok(espias):
    class P:
        async def pre_engine(self, ctx, body, headers):
            return {**body, "model": "otro"}, {**headers, "X-Plugin": "si"}

        def forward_headers_allowlist(self, ctx):
            return {"X-Extra", "x-sentinel-key", "host"}

    gp.register_gateway_plugin(P())
    _byok(espias["client"])
    enviado = _Fake.enviados[0]
    assert json.loads(enviado["content"])["model"] == "otro"
    assert enviado["headers"]["X-Plugin"] == "si" and enviado["headers"]["x-extra"] == "1"
    assert "host" not in enviado["headers"]  # un plugin no reabre los de control/hop-by-hop


def test_pre_engine_en_suscripcion_ve_el_body_ya_enmascarado(espias):
    vistos = []

    class P:
        def pre_request(self, ctx):
            ctx.governance_overrides["pii_masking"] = True

        def pre_engine(self, ctx, body, headers):
            vistos.append(json.dumps(body))
            return body, headers

    gp.register_gateway_plugin(P())
    espias["client"].post("/gw/v1/messages", json=BODY)
    assert EMAIL not in vistos[0]
    assert json.loads(_Fake.enviados[0]["content"]) == json.loads(vistos[0])


@pytest.mark.parametrize("byok", [True, False])
def test_models_filter_se_aplica_en_los_dos_modos(espias, byok):
    class P:
        def models_filter(self, ctx, listing):
            return {**listing, "data": [m for m in listing["data"] if m["id"] == "a"]}

    gp.register_gateway_plugin(P())
    h = {"Authorization": f"Bearer {KEY}"} if byok else {}
    r = espias["client"].get("/gw/v1/models", headers=h)
    assert [m["id"] for m in r.json()["data"]] == ["a"]


@pytest.mark.parametrize("stream", [False, True])
def test_map_error_traduce_el_error_del_destino(espias, stream):
    _Fake.status = 429

    class P:
        def map_error(self, ctx, status, body):
            return 503, b'{"mapeado": true}', {"Retry-After": "7"}

    gp.register_gateway_plugin(P())
    raw = json.dumps({**BODY, "stream": stream}).encode()
    for h in ({"Authorization": f"Bearer {KEY}"}, {}):
        r = espias["client"].post("/gw/v1/messages", content=raw, headers=h)
        assert r.status_code == 503 and r.json() == {"mapeado": True}
        assert r.headers["retry-after"] == "7"


def test_wrap_stream_envuelve_los_bytes_en_byok(espias):
    class P:
        def wrap_stream(self, ctx, it):
            async def gen():
                async for c in it:
                    yield c.upper()
            return gen()

    gp.register_gateway_plugin(P())
    raw = json.dumps({**BODY, "stream": True}).encode()
    r = espias["client"].post("/gw/v1/messages", content=raw,
                              headers={"Authorization": f"Bearer {KEY}"})
    assert r.content == b"DATA: UNO\n\nDATA: DOS\n\n"


def test_governance_overrides_fuerzan_masking_y_fail_mode_block(espias):
    class P:
        def pre_request(self, ctx):
            ctx.governance_overrides.update(pii_masking=True, nlp_fail_mode="block")

    # Sin plugin: la Connection apaga el masking y el email sale tal cual.
    espias["client"].post("/gw/v1/messages", json=BODY)
    assert EMAIL in _Fake.enviados[-1]["content"].decode()
    gp.register_gateway_plugin(P())
    espias["client"].post("/gw/v1/messages", json=BODY)
    assert EMAIL not in _Fake.enviados[-1]["content"].decode()
    assert espias["nlp"][-1]["nlp_fail_mode"] == "block"


def test_governance_overrides_no_pueden_relajar(espias):
    class P:
        def pre_request(self, ctx):
            ctx.governance_overrides.update(pii_masking=False, nlp_fail_mode="degrade")

    gp.register_gateway_plugin(P())
    espias["client"].post("/gw/v1/messages", json=BODY)
    assert "nlp_fail_mode" not in (espias["nlp"][-1] or {})


def test_post_mask_puede_bloquear_y_la_fila_queda(espias):
    class P:
        def pre_request(self, ctx):
            ctx.governance_overrides["pii_masking"] = True

        def post_mask(self, ctx, report):
            if report["masked_entities"]:
                return JSONResponse({"error": "pii"}, status_code=403)

    gp.register_gateway_plugin(P())
    r = espias["client"].post("/gw/v1/messages", json=BODY)
    assert r.status_code == 403 and _Fake.enviados == []
    (args, _kw), = espias["audit"]
    assert args[4] == gp.STATUS_PLUGIN_BLOCK and args[5]


def test_routing_decision_del_ctx_llega_a_audit(espias):
    class P:
        def pre_request(self, ctx):
            ctx.routing_decision = {"route": "x", "model_selected": "m-2"}

    gp.register_gateway_plugin(P())
    espias["client"].post("/gw/v1/messages", json=BODY)
    (_a, kw), = espias["audit"]
    assert kw["routing_decision"] == {"route": "x", "model_selected": "m-2"}


def test_audit_pasa_routing_decision_al_escritor(monkeypatch):
    capturado = {}

    class _Db:
        def close(self):
            pass

    monkeypatch.setattr(gateway, "SessionLocal", _Db)
    monkeypatch.setattr(gateway, "tenant_context", lambda _t: contextlib.nullcontext())
    monkeypatch.setattr(gateway.AuditService, "log_transaction",
                        staticmethod(lambda **kw: capturado.update(kw) or object()))
    assert gateway._audit({}, "m", 0, 0, "passed", [], 1, None, routing_decision={"r": 1})
    assert capturado["routing_decision"] == {"r": 1}
    capturado.clear()
    gateway._audit({}, "m", 0, 0, "passed", [], 1, None)
    assert capturado["routing_decision"] is None
