"""Envoltorio SSE: ping por silencio, reescritura de modelo, sin reordenar (D4; FR-024; R13)."""
import asyncio
import json

from sentinel.redirect.stream import CLAUDE_PING, OPENAI_KEEPALIVE, wrap_sse


async def gen(chunks, delays=None):
    for i, c in enumerate(chunks):
        if delays and delays[i]:
            await asyncio.sleep(delays[i])
        yield c


async def collect(it):
    return b"".join([c async for c in it])


def frames(raw: bytes):
    return [f for f in raw.decode().split("\n\n") if f]


def data_of(frame: str):
    lines = [ln[5:].lstrip() for ln in frame.split("\n") if ln.startswith("data:")]
    return json.loads("\n".join(lines))


MSG_START = (b'event: message_start\ndata: {"type":"message_start","message":{"id":"m1","type":"message",'
             b'"role":"assistant","model":"qwen-destino","content":[],"usage":{"input_tokens":1}}}\n\n')
DELTA = b'event: content_block_delta\ndata: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"hola"}}\n\n'
STOP = b'event: message_stop\ndata: {"type":"message_stop"}\n\n'


async def test_claude_rewrites_message_start_model():
    out = await collect(wrap_sse(gen([MSG_START, DELTA, STOP]), public_model="claude-sonnet-4-5", face="claude"))
    fs = frames(out)
    assert [f.split("\n")[0] for f in fs] == ["event: message_start", "event: content_block_delta", "event: message_stop"]
    assert data_of(fs[0])["message"]["model"] == "claude-sonnet-4-5"
    assert "qwen-destino" not in out.decode()
    assert data_of(fs[1])["delta"]["text"] == "hola"


async def test_frames_split_across_chunks():
    blob = MSG_START + DELTA + STOP
    pieces = [blob[i:i + 7] for i in range(0, len(blob), 7)]
    out = await collect(wrap_sse(gen(pieces), public_model="pub", face="claude"))
    fs = frames(out)
    assert len(fs) == 3 and data_of(fs[0])["message"]["model"] == "pub"


async def test_crlf_frames():
    blob = MSG_START.replace(b"\n", b"\r\n")
    out = await collect(wrap_sse(gen([blob]), public_model="pub", face="claude"))
    assert b"qwen-destino" not in out and b'"pub"' in out


async def test_ping_injected_on_silence_without_reordering():
    src = gen([MSG_START, DELTA, STOP], delays=[0, 0.25, 0])
    out = await collect(wrap_sse(src, public_model="pub", face="claude", ping_after=0.1))
    fs = frames(out)
    kinds = [f.split("\n")[0] for f in fs]
    assert kinds[0] == "event: message_start" and kinds[-1] == "event: message_stop"
    assert kinds.count("event: ping") >= 1
    non_ping = [k for k in kinds if k != "event: ping"]
    assert non_ping == ["event: message_start", "event: content_block_delta", "event: message_stop"]
    assert CLAUDE_PING.startswith(b"event: ping\n") and CLAUDE_PING.endswith(b"\n\n")


async def test_ping_not_inside_partial_frame():
    half = len(DELTA) // 2

    async def src():
        yield MSG_START + DELTA[:half]
        await asyncio.sleep(0.25)
        yield DELTA[half:] + STOP

    out = await collect(wrap_sse(src(), public_model="pub", face="claude", ping_after=0.1))
    for f in frames(out):                      # cada trama sigue siendo SSE válida
        assert f.startswith("event: ")
    assert DELTA.decode().strip() in out.decode()


async def test_no_ping_when_disabled():
    src = gen([MSG_START, STOP], delays=[0, 0.15])
    out = await collect(wrap_sse(src, public_model="pub", face="claude", ping_after=None))
    assert b"ping" not in out


async def test_openai_chunks_rewritten_and_keepalive():
    c1 = b'data: {"id":"x","object":"chat.completion.chunk","model":"hosted_vllm/qwen","choices":[{"index":0,"delta":{"content":"a"}}]}\n\n'
    done = b"data: [DONE]\n\n"
    out = await collect(wrap_sse(gen([c1, done], delays=[0, 0.25]), public_model="pro", face="openai",
                                 ping_after=0.1))
    fs = frames(out)
    assert data_of(fs[0])["model"] == "pro"
    assert fs[-1] == "data: [DONE]"
    assert OPENAI_KEEPALIVE.strip().decode() in fs
    assert b"hosted_vllm" not in out


async def test_responses_events_rewritten():
    ev = b'event: response.created\ndata: {"type":"response.created","response":{"id":"r","model":"gpt-real"}}\n\n'
    out = await collect(wrap_sse(gen([ev]), public_model="gpt-pub", face="openai"))
    assert data_of(frames(out)[0])["response"]["model"] == "gpt-pub"


async def test_non_json_and_comments_pass_through():
    raw = b": comentario\n\nevent: x\ndata: no-es-json\n\n"
    out = await collect(wrap_sse(gen([raw]), public_model="pub", face="claude"))
    assert out == raw


async def test_trailing_partial_flushed():
    out = await collect(wrap_sse(gen([STOP + b"data: {\"type\":\"x\"}"]), public_model="pub", face="claude"))
    assert out.endswith(b'data: {"type":"x"}')


async def test_upstream_error_propagates():
    async def boom():
        yield MSG_START
        raise RuntimeError("corte")

    it = wrap_sse(boom(), public_model="pub", face="claude")
    got = [await it.__anext__()]
    try:
        await it.__anext__()
        assert False, "debió propagar"
    except RuntimeError:
        pass
    assert b"pub" in got[0]
