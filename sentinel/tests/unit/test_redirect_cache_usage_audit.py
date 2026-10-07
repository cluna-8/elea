"""057 T076 (FR-046; T128/T134 de Sentinel; decisión del coordinador 2026-10-06): los tokens de caché que informa el destino
(leídos y escritos) quedan en la auditoría, en `routing_decision.extensions.redirect` (`cache_read_tokens`,
`cache_write_tokens`; enteros, nunca contenido). El plugin los lee del `usage` de la respuesta: de `map_response` (no stream) y
de las tramas del stream (`wrap_stream`), y los suma a la decisión que comparte con la pasarela, que escribe la fila al final.

Cara Claude: `cache_read_input_tokens` / `cache_creation_input_tokens`. Cara genérica: `prompt_tokens_details.cached_tokens` y
`cache_write_tokens` (OpenAI/OpenRouter) o `input_tokens_details.cached_tokens` (Responses). Si el destino no informa caché, la
decisión no lleva los campos."""
import json

import pytest

from sentinel.redirect import authz
from sentinel.redirect.plugin import RedirectPlugin
from sentinel.tests import redirect_fixtures as fx


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv(authz.KEY_ENV, fx.INTERNAL_KEY)


async def _plugin(route="/v1/messages", model="claude-sonnet-4-5"):
    p = RedirectPlugin(store=fx.store(fx.snapshot("on")), ping_after=0.05)
    c = fx.ctx(route=route, model=model)
    assert await p.pre_request(c) is None
    return p, c


def _red(ctx):
    return ctx.routing_decision["extensions"]["redirect"]


def _respuesta(usage, face="claude"):
    if face == "claude":
        return json.dumps({"type": "message", "model": "real", "content": [], "usage": usage}).encode()
    return json.dumps({"model": "real", "choices": [], "usage": usage}).encode()


@pytest.mark.asyncio
async def test_no_stream_cara_claude_suma_los_tokens_de_cache_a_la_decision():
    p, c = await _plugin()
    p.map_response(c, 200, _respuesta({"input_tokens": 10, "output_tokens": 2, "cache_read_input_tokens": 7,
                                       "cache_creation_input_tokens": 3}))
    assert _red(c)["cache_read_tokens"] == 7 and _red(c)["cache_write_tokens"] == 3


@pytest.mark.asyncio
async def test_no_stream_cara_generica_openai_y_openrouter():
    p, c = await _plugin(route="/v1/chat/completions", model="pro")
    p.map_response(c, 200, _respuesta({"prompt_tokens": 100, "completion_tokens": 5,
                                       "prompt_tokens_details": {"cached_tokens": 60, "cache_write_tokens": 20}},
                                      face="openai"))
    assert _red(c)["cache_read_tokens"] == 60 and _red(c)["cache_write_tokens"] == 20


@pytest.mark.asyncio
async def test_no_stream_cara_generica_responses():
    p, c = await _plugin(route="/v1/chat/completions", model="pro")
    p.map_response(c, 200, _respuesta({"input_tokens": 100, "output_tokens": 5,
                                       "input_tokens_details": {"cached_tokens": 40}}, face="openai"))
    assert _red(c)["cache_read_tokens"] == 40 and "cache_write_tokens" not in _red(c)


@pytest.mark.asyncio
@pytest.mark.parametrize("usage", [None, {}, {"input_tokens": 5, "output_tokens": 1}, {"cache_read_input_tokens": "x"},
                                   {"cache_read_input_tokens": -4}, {"cache_read_input_tokens": True}])
async def test_sin_informe_de_cache_o_con_valores_invalidos_la_decision_no_lleva_los_campos(usage):
    p, c = await _plugin()
    p.map_response(c, 200, _respuesta(usage))
    assert "cache_read_tokens" not in _red(c) and "cache_write_tokens" not in _red(c)


@pytest.mark.asyncio
async def test_un_cero_informado_se_registra_el_destino_dijo_que_no_hubo_aciertos():
    p, c = await _plugin()
    p.map_response(c, 200, _respuesta({"input_tokens": 5, "output_tokens": 1, "cache_read_input_tokens": 0,
                                       "cache_creation_input_tokens": 0}))
    assert _red(c)["cache_read_tokens"] == 0 and _red(c)["cache_write_tokens"] == 0


def _sse(*objs):
    return [(f"event: {o['type']}\ndata: {json.dumps(o)}\n\n").encode() for o in objs]


async def _consumir(p, c, chunks):
    async def _fuente():
        for ch in chunks:
            yield ch

    return [x async for x in p.wrap_stream(c, _fuente())]


@pytest.mark.asyncio
async def test_stream_cara_claude_toma_message_start_y_message_delta():
    p, c = await _plugin()
    chunks = _sse({"type": "message_start", "message": {"model": "real", "usage": {
        "input_tokens": 10, "output_tokens": 1, "cache_read_input_tokens": 7, "cache_creation_input_tokens": 0}}},
                  {"type": "message_delta", "delta": {"stop_reason": "end_turn"},
                   "usage": {"output_tokens": 9, "cache_creation_input_tokens": 3}},
                  {"type": "message_stop"})
    salida = await _consumir(p, c, chunks)
    assert b"message_stop" in b"".join(salida)
    assert _red(c)["cache_read_tokens"] == 7 and _red(c)["cache_write_tokens"] == 3


@pytest.mark.asyncio
async def test_stream_cara_generica_toma_el_usage_del_chunk_final():
    p, c = await _plugin(route="/v1/chat/completions", model="pro")
    cuerpo = [b'data: {"model":"real","choices":[{"delta":{"content":"hola"}}]}\n\n',
              b'data: {"model":"real","choices":[],"usage":{"prompt_tokens":50,"completion_tokens":2,'
              b'"prompt_tokens_details":{"cached_tokens":30}}}\n\n', b"data: [DONE]\n\n"]
    await _consumir(p, c, cuerpo)
    assert _red(c)["cache_read_tokens"] == 30


@pytest.mark.asyncio
async def test_el_stream_pasa_igual_con_o_sin_tokens_de_cache():
    """El tap no cambia ni reordena lo que llega al cliente."""
    p, c = await _plugin()
    chunks = _sse({"type": "message_start", "message": {"model": "real", "usage": {}}}, {"type": "message_stop"})
    p2, c2 = await _plugin()
    assert await _consumir(p, c, chunks) == await _consumir(p2, c2, chunks)
    assert "cache_read_tokens" not in _red(c)


@pytest.mark.asyncio
async def test_en_modo_sombra_no_se_toca_nada():
    p = RedirectPlugin(store=fx.store(fx.snapshot("shadow")), ping_after=0.05)
    c = fx.ctx(route="/v1/messages", model="claude-sonnet-4-5")
    await p.pre_request(c)
    assert p.map_response(c, 200, _respuesta({"cache_read_input_tokens": 7})) is None
    assert "cache_read_tokens" not in json.dumps(c.routing_decision or {})
