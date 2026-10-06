"""T091 de Sentinel (FR-037–FR-039, FR-056, SC-007): el stream de la cara Claude.

`ping` con silencio; `message_start.model` = id público; `usage` con los cuatro contadores; un error después
de `message_start` ⇒ `event: error` y cierre sin `message_stop`; en la cara genérica, comentario
`: keep-alive`. La mitad corre sobre el envoltorio y la otra sobre la pasarela real con motor falso.
"""
import asyncio
import json

import pytest

from sentinel.redirect import stream
from sentinel.redirect.plugin import RedirectPlugin
from sentinel.tests import corpus_claude as corpus
from sentinel.tests import gw_harness as h
from sentinel.tests import redirect_fixtures as fx

COUNTERS = ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")


def frames(raw: bytes):
    return [f for f in raw.decode().split("\n\n") if f]


def kind(frame: str) -> str:
    first = frame.split("\n")[0]
    return first[len("event: "):] if first.startswith("event: ") else first


def data_of(frame: str):
    return json.loads("\n".join(ln[5:].lstrip() for ln in frame.split("\n") if ln.startswith("data:")))


async def collect(it):
    return b"".join([c async for c in it])


async def source(chunks):
    for c in chunks:
        if isinstance(c, (int, float)):
            await asyncio.sleep(c)
        elif isinstance(c, BaseException):
            raise c
        else:
            yield c


def ev(name, data):
    return f"event: {name}\ndata: {json.dumps(data)}\n\n".encode()


START = ev("message_start", {"type": "message_start", "message": {"id": "m", "type": "message", "role": "assistant",
                                                                 "model": "gpt-real", "content": [],
                                                                 "usage": {"input_tokens": 25, "output_tokens": 1}}})
DELTA = ev("content_block_delta", {"type": "content_block_delta", "index": 0,
                                   "delta": {"type": "text_delta", "text": "hola"}})
MDELTA = ev("message_delta", {"type": "message_delta", "delta": {"stop_reason": "end_turn"},
                              "usage": {"output_tokens": 40}})
STOP = ev("message_stop", {"type": "message_stop"})


# ── usage con los cuatro contadores ────────────────────────────────────────────

async def test_message_start_lleva_los_cuatro_contadores_con_cero_si_el_destino_no_informa():
    out = await collect(stream.wrap_sse(source([START, DELTA, MDELTA, STOP]), public_model="claude-sonnet-4-5",
                                        face="claude", ping_after=None))
    usage = data_of(frames(out)[0])["message"]["usage"]
    assert usage == {"input_tokens": 25, "output_tokens": 1, "cache_creation_input_tokens": 0,
                     "cache_read_input_tokens": 0}


async def test_los_contadores_que_el_destino_si_informa_se_conservan_y_los_nulos_pasan_a_cero():
    start = ev("message_start", {"type": "message_start", "message": {"model": "x", "usage": {
        "input_tokens": 9, "cache_read_input_tokens": 5, "cache_creation_input_tokens": None}}})
    out = await collect(stream.wrap_sse(source([start]), public_model="p", face="claude", ping_after=None))
    usage = data_of(frames(out)[0])["message"]["usage"]
    assert usage["input_tokens"] == 9 and usage["cache_read_input_tokens"] == 5
    assert usage["cache_creation_input_tokens"] == 0 and usage["output_tokens"] == 0


async def test_message_start_sin_usage_lo_completa():
    start = ev("message_start", {"type": "message_start", "message": {"model": "x"}})
    out = await collect(stream.wrap_sse(source([start]), public_model="p", face="claude", ping_after=None))
    assert data_of(frames(out)[0])["message"]["usage"] == dict.fromkeys(COUNTERS, 0)


async def test_message_delta_no_pisa_con_ceros_lo_que_informo_message_start():
    # el SDK de la herramienta acumula: un `input_tokens: 0` en `message_delta` borraría el del inicio
    out = await collect(stream.wrap_sse(source([START, MDELTA, STOP]), public_model="p", face="claude",
                                        ping_after=None))
    fs = frames(out)
    snapshot = dict(data_of(fs[0])["message"]["usage"])
    delta = data_of(fs[1])["usage"]
    snapshot.update({k: v for k, v in delta.items() if v is not None})
    assert snapshot["input_tokens"] == 25 and snapshot["output_tokens"] == 40
    assert set(snapshot) >= set(COUNTERS)
    assert "input_tokens" not in delta                 # no se agrega nada que el destino no dijo


async def test_message_delta_sin_usage_o_con_nulos_queda_valido():
    sin = ev("message_delta", {"type": "message_delta", "delta": {"stop_reason": "end_turn"}})
    nulo = ev("message_delta", {"type": "message_delta", "delta": {}, "usage": {"output_tokens": None,
                                                                                "input_tokens": None}})
    out = await collect(stream.wrap_sse(source([sin, nulo]), public_model="p", face="claude", ping_after=None))
    a, b = (data_of(f)["usage"] for f in frames(out))
    assert a == {"output_tokens": 0} and b == {"output_tokens": 0}


def test_la_respuesta_no_stream_tambien_lleva_los_cuatro_contadores():
    p = RedirectPlugin(store=fx.store(fx.snapshot("on")), ping_after=0.05)
    c = fx.ctx(route="/v1/messages", model="claude-sonnet-4-5")
    import asyncio as _a
    _a.run(p.pre_request(c))
    body = {"id": "m", "type": "message", "model": "qwen", "content": [], "usage": {"input_tokens": 3}}
    st, content, _ = p.map_response(c, 200, json.dumps(body).encode())
    out = json.loads(content)
    assert st == 200 and out["model"] == "claude-sonnet-4-5"
    assert out["usage"] == {"input_tokens": 3, "output_tokens": 0, "cache_creation_input_tokens": 0,
                            "cache_read_input_tokens": 0}


# ── ping y orden ───────────────────────────────────────────────────────────────

def test_el_silencio_maximo_por_defecto_es_15_s(monkeypatch):
    assert stream.DEFAULT_PING_AFTER == 15.0 and RedirectPlugin(store=fx.store(None)).ping_after == 15.0
    capturado = {}
    monkeypatch.setattr(stream, "wrap_sse", lambda it, **kw: capturado.update(kw) or it)
    p = RedirectPlugin(store=fx.store(fx.snapshot("on")))
    c = fx.ctx(route="/v1/messages", model="claude-sonnet-4-5")
    asyncio.run(p.pre_request(c))
    p.wrap_stream(c, object())
    assert capturado["ping_after"] == 15.0 and capturado["face"] == "claude"


async def test_stream_largo_con_silencios_trae_pings_entre_tramas_y_el_orden_del_destino():
    events = corpus.stream_events()
    chunks = []
    for i, e in enumerate(events):
        chunks.append(corpus.sse([e]))
        if i in (3, 40, 120):
            chunks.append(0.25)                       # el destino calla
    out = await collect(stream.wrap_sse(source(chunks), public_model="claude-sonnet-4-5", face="claude",
                                        ping_after=0.1))
    fs = frames(out)
    pings = [f for f in fs if kind(f) == "ping"]
    assert len(pings) >= 3
    # cada trama sigue siendo SSE completa y el orden de los demás eventos es el del destino
    assert all(f.startswith("event: ") for f in fs)
    original = [e["event"] for e in events if e["event"] != "ping"]
    assert [kind(f) for f in fs if kind(f) != "ping"] == original
    assert data_of(fs[0])["message"]["model"] == "claude-sonnet-4-5" and b"gpt-destino-real" not in out
    assert fs[-1].startswith("event: message_stop")


# ── error después de message_start ─────────────────────────────────────────────

async def test_una_falla_del_destino_despues_de_message_start_es_event_error_sin_message_stop():
    out = await collect(stream.wrap_sse(source([START, DELTA, RuntimeError("boom con detalle interno")]),
                                        public_model="p", face="claude", ping_after=None))
    fs = frames(out)
    assert [kind(f) for f in fs] == ["message_start", "content_block_delta", "error"]
    err = data_of(fs[-1])
    assert err == {"type": "error", "error": {"type": "overloaded_error",
                                              "message": "El modelo está saturado. Reintentá en unos segundos."}}
    assert b"boom" not in out and b"message_stop" not in out


async def test_un_event_error_del_destino_se_reescribe_neutro_y_cierra_el_stream():
    crudo = (b'event: error\ndata: {"type":"error","error":{"type":"overloaded_error",'
             b'"message":"Azure OpenAI deployment gpt-x overloaded at https://interno"}}\n\n')
    out = await collect(stream.wrap_sse(source([START, crudo, DELTA, STOP]), public_model="p", face="claude",
                                        ping_after=None))
    fs = frames(out)
    assert [kind(f) for f in fs] == ["message_start", "error"]       # nada después: ni deltas ni message_stop
    assert data_of(fs[1])["error"]["type"] == "overloaded_error"
    assert b"Azure" not in out and b"interno" not in out


@pytest.mark.parametrize("tipo,esperado", [("rate_limit_error", "rate_limit_error"),
                                           ("invalid_request_error", "invalid_request_error"),
                                           ("authentication_error", "api_error"),
                                           ("algo_nuevo", "api_error")])
async def test_el_tipo_del_error_del_destino_se_mapea_a_uno_conocido(tipo, esperado):
    crudo = ev("error", {"type": "error", "error": {"type": tipo, "message": "detalle"}})
    out = await collect(stream.wrap_sse(source([START, crudo]), public_model="p", face="claude", ping_after=None))
    body = data_of(frames(out)[-1])
    assert body["error"]["type"] == esperado and "detalle" not in json.dumps(body)


async def test_la_cancelacion_del_cliente_no_se_traga_ni_deja_el_destino_abierto():
    cerrado = []

    async def src():
        try:
            yield START
            await asyncio.sleep(30)
            yield STOP
        finally:
            cerrado.append(True)

    it = stream.wrap_sse(src(), public_model="p", face="claude", ping_after=None)
    assert b"message_start" in await it.__anext__()
    task = asyncio.ensure_future(it.__anext__())
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await it.aclose()
    await asyncio.sleep(0.05)
    assert cerrado == [True]


# ── cara genérica: keep-alive y sin cambios de contrato ─────────────────────────

async def test_cara_generica_keep_alive_como_comentario_y_la_falla_sigue_propagando():
    c1 = b'data: {"id":"x","model":"hosted/qwen","choices":[{"index":0,"delta":{"content":"a"}}]}\n\n'
    out = await collect(stream.wrap_sse(source([c1, 0.25, b"data: [DONE]\n\n"]), public_model="pro",
                                        face="openai", ping_after=0.1))
    fs = frames(out)
    assert ": keep-alive" in fs and fs[-1] == "data: [DONE]" and b"event: ping" not in out
    with pytest.raises(RuntimeError):
        await collect(stream.wrap_sse(source([c1, RuntimeError("corte")]), public_model="pro", face="openai"))


# ── de punta a punta por la pasarela ───────────────────────────────────────────

@pytest.fixture
def env(monkeypatch):
    e = h.gateway_env(monkeypatch)
    yield e
    h.close_env()


def _messages(env, stream_on=True):
    doc = corpus.load("claude_code_messages_beta")
    return env.client.post("/gw/v1/messages?beta=true", headers={"Authorization": f"Bearer {h.VK}",
                                                                 "anthropic-version": "2023-06-01"},
                           json={**doc["body"], "stream": stream_on})


def test_e2e_stream_con_pings_modelo_publico_y_uso_completo(env):
    env.register(fx.snapshot("on"))
    events = corpus.stream_events()
    env.engine.stream_chunks = tuple(c for i, e in enumerate(events)
                                     for c in ((corpus.sse([e]), 0.2) if i == 20 else (corpus.sse([e]),)))
    r = _messages(env)
    fs = frames(r.content)
    assert r.status_code == 200 and fs[0].startswith("event: message_start")
    start = data_of(fs[0])["message"]
    assert start["model"] == "claude-sonnet-4-5" and set(start["usage"]) >= set(COUNTERS)
    assert any(kind(f) == "ping" for f in fs) and b"gpt-destino-real" not in r.content
    assert fs[-1].startswith("event: message_stop")


def test_e2e_falla_del_destino_a_mitad_es_event_error_y_nunca_message_stop(env):
    env.register(fx.snapshot("on"))
    env.engine.stream_chunks = (corpus.sse(corpus.stream_events()[:3]),
                                ConnectionError("detalle interno del destino https://x"))
    r = _messages(env)
    fs = frames(r.content)
    assert r.status_code == 200 and kind(fs[-1]) == "error"
    assert b"message_stop" not in r.content and b"detalle interno" not in r.content
    assert data_of(fs[-1])["error"]["type"] == "overloaded_error"
