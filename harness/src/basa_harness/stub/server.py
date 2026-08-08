"""Proveedor simulado (stub) del harness — servidor de dos wire-protocols (spec 035,
T015; contract ``stub-wire.md``).

UN proceso FastAPI/asyncio que REEMPLAZA a los proveedores de IA durante los gates. Cero
egress (coste $0): no llama a nadie, todo lo responde con datos sintéticos deterministas.

Dos wires, exactamente como los consumen el motor y el backend:

- **Wire OpenAI** (consumidor: motor LiteLLM) — ``POST /v1/chat/completions`` (JSON y SSE)
  y ``POST /v1/embeddings`` (vectores deterministas por hash del input, dimensión
  configurable, orden por ``index``).
- **Wire Anthropic** (consumidor: passthrough del backend) — ``POST /v1/messages`` (JSON y
  SSE con la secuencia EXACTA de eventos Anthropic), ``POST /v1/messages/count_tokens`` y
  ``GET /v1/models``.

Todo request:
1. se leen los bytes completos; si vienen con ``Content-Encoding`` gzip/deflate se
   DESCOMPRIMEN antes de escanear (un encoding no soportado se marca RUIDOSAMENTE como
   tráfico no auditable — nunca 0 hits en silencio, hallazgo A4);
2. el centinela escanea el cuerpo ACUMULADO ANTES de que el handler lo use (buffer por
   request: un canario partido entre chunks entrantes queda dentro del cuerpo);
3. se resuelve el alias y su comportamiento programado (latencia/ritmo/duración/error);
4. la latencia programada se registra (referencia del overhead FR-008);
5. se emite la respuesta con el pacing del cronograma de modelo abierto, midiendo el drift.

Todo lo que NO matchee un endpoint contratado → **404 RUIDOSO y contado** (delata
cableado incompleto — nunca silencio), y su cuerpo también se escanea/spoolea (una fuga
puede aparecer en un request mal ruteado).

DETERMINISMO: embeddings, tokens, ids y decisión de error son función pura de la entrada
y la semilla (sin time/uuid/random). Lo único no-determinista —el timestamp de la
evidencia y las duraciones reales de sleep— se inyecta (``state.clock``/``state.sleep``) o
se auto-mide.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import math
import struct
import zlib
from typing import AsyncIterator, Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from .control import AliasBehavior, StubState, register_control_routes

# Léxico fijo para tokens sintéticos (determinista, sin random).
_LEXICON = ("Hola", "desde", "el", "stub", "de", "la", "ITV", "respuesta",
            "sintetica", "token", "carga", "modelo", "abierto", "prueba", "gate")

SSE_MEDIA_TYPE = "text/event-stream"

# Headers que emiten los proveedores reales en SSE: evitan que un proxy bufferee y
# falsee el TTFT medido (B1).
SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no",
               "Connection": "keep-alive"}

# Encodings que sabemos descomprimir para poder auditar el cuerpo (A4). ``br`` (brotli)
# NO está: requeriría una dep — un request br se marca no auditable, jamás 0 en silencio.
_SUPPORTED_ENCODINGS = frozenset({"", "identity", "gzip", "x-gzip", "deflate"})


# ── helpers deterministas ─────────────────────────────────────────────────────────────

def _approx_tokens(text: str) -> int:
    """Conteo aproximado len/4 (contract: suficiente para count_tokens y usage)."""
    return max(1, len(text) // 4)


def _n_tokens(beh: AliasBehavior) -> int:
    """Cuántos tokens emitir: ``token_rate × stream_duration_s`` (mínimo 1)."""
    return max(1, int(round(beh.token_rate * beh.stream_duration_s)))


def _make_tokens(n: int) -> list[str]:
    return [_LEXICON[i % len(_LEXICON)] for i in range(n)]


def _prompt_text_openai(payload: dict) -> str:
    msgs = payload.get("messages") or []
    parts = []
    for m in msgs:
        c = m.get("content", "")
        parts.append(c if isinstance(c, str) else json.dumps(c, ensure_ascii=False))
    return "\n".join(parts)


def _prompt_text_anthropic(payload: dict) -> str:
    parts = []
    system = payload.get("system")
    if isinstance(system, str):
        parts.append(system)
    for m in payload.get("messages") or []:
        c = m.get("content", "")
        if isinstance(c, str):
            parts.append(c)
        elif isinstance(c, list):
            for block in c:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(block.get("text", ""))
    return "\n".join(parts)


def _embed(text: str, dim: int) -> list[float]:
    """Vector determinista por hash del input, L2-normalizado. Mismo texto → mismo vector."""
    out: list[float] = []
    counter = 0
    while len(out) < dim:
        block = hashlib.sha256(f"{text}::{counter}".encode("utf-8")).digest()
        for j in range(0, len(block), 4):
            if len(out) >= dim:
                break
            (u,) = struct.unpack(">I", block[j:j + 4])
            out.append((u / 0xFFFFFFFF) * 2.0 - 1.0)
        counter += 1
    norm = math.sqrt(sum(x * x for x in out)) or 1.0
    return [x / norm for x in out]


def _sse_data(obj: dict) -> bytes:
    """Frame SSE estilo OpenAI: solo línea ``data:`` + terminador en blanco."""
    return ("data: " + json.dumps(obj, ensure_ascii=False) + "\n\n").encode("utf-8")


def _sse_event(event: str, obj: dict) -> bytes:
    """Frame SSE estilo Anthropic: línea ``event:`` + línea ``data:`` + blanco."""
    return (f"event: {event}\n"
            + "data: " + json.dumps(obj, ensure_ascii=False) + "\n\n").encode("utf-8")


def _openai_error_body(terminal: bool) -> dict:
    kind = "invalid_request_error" if terminal else "stub_error"
    return {"error": {"message": "stub-injected error (deterministic)",
                      "type": kind, "param": None,
                      "code": "stub_terminal" if terminal else "stub_injected"}}


def _anthropic_error_body(terminal: bool) -> dict:
    kind = "api_error" if terminal else "overloaded_error"
    return {"type": "error",
            "error": {"type": kind, "message": "stub-injected error (deterministic)"}}


def _decode_body(raw: bytes, encoding: str) -> tuple[bytes, bool, str]:
    """Devuelve ``(cuerpo_a_escanear, no_auditable, nota)``.

    gzip/deflate se descomprimen; un encoding no soportado o un cuerpo corrupto se marcan
    ``no_auditable=True`` (el crudo comprimido no dice nada) — nunca un 0 en silencio."""
    enc = (encoding or "").lower().strip()
    if enc not in _SUPPORTED_ENCODINGS:
        return raw, True, f"unsupported:{enc}"
    if enc in ("", "identity"):
        return raw, False, ""
    try:
        if enc in ("gzip", "x-gzip"):
            return gzip.decompress(raw), False, enc
        # deflate: probamos zlib y, si falla, deflate crudo (sin cabecera)
        try:
            return zlib.decompress(raw), False, enc
        except zlib.error:
            return zlib.decompress(raw, -zlib.MAX_WBITS), False, enc
    except (OSError, zlib.error) as exc:
        return raw, True, f"{enc}-decode-failed:{exc}"


# ── ingest (escaneo inline común a todo endpoint) ──────────────────────────────────────

async def _ingest(request: Request, state: StubState, endpoint: str) -> tuple[bytes, str]:
    """Lee el cuerpo COMPLETO, lo descomprime si hace falta, escanea canarios inline
    (antes de que el handler lo use) y spoolea. Devuelve ``(cuerpo_decodificado, id)``."""
    raw = await request.body()
    request_id = state.next_request_id()
    timestamp = state.now_iso()
    encoding = request.headers.get("content-encoding", "") or ""
    body, unauditable, _note = _decode_body(raw, encoding)
    # además del cuerpo primario (descomprimido) escaneamos el crudo cuando difieren, por
    # si el encoding estuviera mal declarado y el canario viajara en claro (A4).
    also_scan = [raw] if raw != body else None
    evidences = state.sentinel.scan_body(
        request_id=request_id, endpoint=endpoint, body=body, also_scan=also_scan,
        content_encoding=encoding, unauditable=unauditable,
        config_masking=state.masking_config, timestamp=timestamp,
    )
    state.record_leaks(evidences)
    if unauditable:
        state.record_unauditable(request_id, endpoint, encoding)
    return body, request_id


def _parse_json(body: bytes) -> dict:
    if not body:
        return {}
    try:
        data = json.loads(body)
        return data if isinstance(data, dict) else {}
    except (ValueError, UnicodeDecodeError):
        return {}


# ── generadores SSE con pacing y medición de drift ─────────────────────────────────────

async def _pace(state: StubState, start: float, i: int, beh: AliasBehavior) -> None:
    """Duerme hasta el instante objetivo del token ``i`` (grilla de modelo abierto
    ``start + (i+1)/token_rate``) y registra el drift (lateness) — usa el reloj/sleep
    inyectados para que la grilla sea verificable sin asserts de tiempo real (A5)."""
    if beh.token_rate <= 0:
        return
    target = start + (i + 1) / beh.token_rate
    now = state.clock()
    if target > now:
        await state.sleep(target - now)
    state.record_drift(max(0.0, (state.clock() - target) * 1000.0))


async def _openai_sse(state: StubState, alias: str, request_id: str, beh: AliasBehavior,
                      *, prompt_tokens: int, include_usage: bool = False,
                      inject_error: bool = False,
                      terminal: bool = False) -> AsyncIterator[bytes]:
    created = 0
    cid = f"chatcmpl-{request_id}"
    if beh.latency_ms > 0:
        await state.sleep(beh.latency_ms / 1000.0)
    start = state.clock()
    base = {"id": cid, "object": "chat.completion.chunk", "created": created, "model": alias}
    yield _sse_data({**base, "choices": [{"index": 0, "delta": {"role": "assistant"},
                                          "finish_reason": None}]})
    n = _n_tokens(beh)
    tokens = _make_tokens(n)
    # si hay error a mitad (B3), emitimos frames válidos hasta la mitad y cortamos
    cut = (n + 1) // 2 if inject_error else n
    for i, tok in enumerate(tokens[:cut]):
        await _pace(state, start, i, beh)
        text = tok if i == 0 else " " + tok
        yield _sse_data({**base, "choices": [{"index": 0, "delta": {"content": text},
                                              "finish_reason": None}]})
    if inject_error:
        # error EN EL STREAM (frames válidos, luego objeto de error, sin [DONE])
        yield _sse_data({**base, "choices": [], "error": _openai_error_body(terminal)["error"]})
        return
    yield _sse_data({**base, "choices": [{"index": 0, "delta": {},
                                          "finish_reason": "stop"}]})
    if include_usage:
        # stream_options.include_usage: usage determinista cruza el wire streameado (B2)
        yield _sse_data({**base, "choices": [],
                         "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": n,
                                   "total_tokens": prompt_tokens + n}})
    yield b"data: [DONE]\n\n"


async def _anthropic_sse(state: StubState, alias: str, request_id: str, beh: AliasBehavior,
                         input_tokens: int, *, inject_error: bool = False,
                         terminal: bool = False) -> AsyncIterator[bytes]:
    mid = f"msg_{request_id}"
    if beh.latency_ms > 0:
        await state.sleep(beh.latency_ms / 1000.0)
    start = state.clock()
    n = _n_tokens(beh)
    tokens = _make_tokens(n)
    # PING/KEEPALIVE (B4): ningún gate actual programa silencio ≥60s (TTFT<1s, tokens
    # cada ~25ms), así que NO emitimos ``event: ping``. Si un perfil futuro programara un
    # hueco ≥ el read-timeout de 60s del gateway, habría que intercalar ``event: ping``
    # periódico acá para que el gateway no aborte el stream por silencio.
    yield _sse_event("message_start", {
        "type": "message_start",
        "message": {"id": mid, "type": "message", "role": "assistant", "model": alias,
                    "content": [], "stop_reason": None, "stop_sequence": None,
                    "usage": {"input_tokens": input_tokens, "output_tokens": 0}},
    })
    yield _sse_event("content_block_start", {
        "type": "content_block_start", "index": 0,
        "content_block": {"type": "text", "text": ""},
    })
    cut = (n + 1) // 2 if inject_error else n
    for i, tok in enumerate(tokens[:cut]):
        await _pace(state, start, i, beh)
        text = tok if i == 0 else " " + tok
        yield _sse_event("content_block_delta", {
            "type": "content_block_delta", "index": 0,
            "delta": {"type": "text_delta", "text": text},
        })
    if inject_error:
        # corte a mitad: frames válidos y luego ``event: error`` (sin message_stop) (B3)
        yield _sse_event("error", _anthropic_error_body(terminal))
        return
    yield _sse_event("content_block_stop", {"type": "content_block_stop", "index": 0})
    yield _sse_event("message_delta", {
        "type": "message_delta",
        "delta": {"stop_reason": "end_turn", "stop_sequence": None},
        "usage": {"output_tokens": n},
    })
    yield _sse_event("message_stop", {"type": "message_stop"})


# ── app factory ────────────────────────────────────────────────────────────────────────

def create_app(state: Optional[StubState] = None) -> FastAPI:
    """Construye la app FastAPI del stub. Un ``state`` inyectado permite a los tests tener
    referencia directa; si no, se crea uno nuevo y se guarda en ``app.state.stub``."""
    st = state if state is not None else StubState()
    app = FastAPI(title="basa-harness stub", docs_url=None, redoc_url=None)
    app.state.stub = st

    # ── Wire OpenAI ─────────────────────────────────────────────────────────────────
    @app.post("/v1/chat/completions")
    async def chat_completions(request: Request):  # noqa: ANN202
        body, request_id = await _ingest(request, st, "/v1/chat/completions")
        payload = _parse_json(body)
        alias = payload.get("model", "unknown")
        beh = st.behavior_for(alias)
        st.record_request(alias=alias, endpoint="/v1/chat/completions",
                          request_id=request_id, latency_ms=beh.latency_ms)
        stream = payload.get("stream") is True
        prompt_tokens = _approx_tokens(_prompt_text_openai(payload))
        include_usage = bool((payload.get("stream_options") or {}).get("include_usage"))
        if st.should_error(alias):
            st.errors_inyectados += 1
            if stream and beh.error_mid_stream:
                return StreamingResponse(
                    _openai_sse(st, alias, request_id, beh, prompt_tokens=prompt_tokens,
                                include_usage=include_usage, inject_error=True,
                                terminal=beh.error_terminal),
                    media_type=SSE_MEDIA_TYPE, headers=SSE_HEADERS)
            status = 500 if beh.error_terminal else 429
            return JSONResponse(status_code=status,
                                content=_openai_error_body(beh.error_terminal))
        if stream:
            return StreamingResponse(
                _openai_sse(st, alias, request_id, beh, prompt_tokens=prompt_tokens,
                            include_usage=include_usage),
                media_type=SSE_MEDIA_TYPE, headers=SSE_HEADERS)
        if beh.latency_ms > 0:
            await st.sleep(beh.latency_ms / 1000.0)
        tokens = _make_tokens(_n_tokens(beh))
        return {
            "id": f"chatcmpl-{request_id}", "object": "chat.completion",
            "created": 0, "model": alias,
            "choices": [{"index": 0,
                         "message": {"role": "assistant", "content": " ".join(tokens)},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": len(tokens),
                      "total_tokens": prompt_tokens + len(tokens)},
        }

    @app.post("/v1/embeddings")
    async def embeddings(request: Request):  # noqa: ANN202
        body, request_id = await _ingest(request, st, "/v1/embeddings")
        payload = _parse_json(body)
        alias = payload.get("model", "unknown")
        beh = st.behavior_for(alias)
        st.record_request(alias=alias, endpoint="/v1/embeddings",
                          request_id=request_id, latency_ms=beh.latency_ms)
        if st.should_error(alias):
            st.errors_inyectados += 1
            status = 500 if beh.error_terminal else 429
            return JSONResponse(status_code=status,
                                content=_openai_error_body(beh.error_terminal))
        raw = payload.get("input", "")
        inputs = raw if isinstance(raw, list) else [raw]
        if beh.latency_ms > 0:
            await st.sleep(beh.latency_ms / 1000.0)
        dim = st.embedding_dim
        data = []
        total_tokens = 0
        for index, text in enumerate(inputs):
            text_s = text if isinstance(text, str) else json.dumps(text, ensure_ascii=False)
            total_tokens += _approx_tokens(text_s)
            data.append({"object": "embedding", "index": index,
                         "embedding": _embed(text_s, dim)})
        return {"object": "list", "data": data, "model": alias,
                "usage": {"prompt_tokens": total_tokens, "total_tokens": total_tokens}}

    # ── Wire Anthropic ──────────────────────────────────────────────────────────────
    @app.post("/v1/messages")
    async def messages(request: Request):  # noqa: ANN202
        body, request_id = await _ingest(request, st, "/v1/messages")
        payload = _parse_json(body)
        alias = payload.get("model", "unknown")
        beh = st.behavior_for(alias)
        st.record_request(alias=alias, endpoint="/v1/messages",
                          request_id=request_id, latency_ms=beh.latency_ms)
        stream = payload.get("stream") is True
        input_tokens = _approx_tokens(_prompt_text_anthropic(payload))
        if st.should_error(alias):
            st.errors_inyectados += 1
            if stream and beh.error_mid_stream:
                return StreamingResponse(
                    _anthropic_sse(st, alias, request_id, beh, input_tokens,
                                   inject_error=True, terminal=beh.error_terminal),
                    media_type=SSE_MEDIA_TYPE, headers=SSE_HEADERS)
            status = 500 if beh.error_terminal else 529
            return JSONResponse(status_code=status,
                                content=_anthropic_error_body(beh.error_terminal))
        if stream:
            return StreamingResponse(
                _anthropic_sse(st, alias, request_id, beh, input_tokens),
                media_type=SSE_MEDIA_TYPE, headers=SSE_HEADERS)
        if beh.latency_ms > 0:
            await st.sleep(beh.latency_ms / 1000.0)
        tokens = _make_tokens(_n_tokens(beh))
        return {
            "id": f"msg_{request_id}", "type": "message", "role": "assistant",
            "model": alias,
            "content": [{"type": "text", "text": " ".join(tokens)}],
            "stop_reason": "end_turn", "stop_sequence": None,
            "usage": {"input_tokens": input_tokens, "output_tokens": len(tokens)},
        }

    @app.post("/v1/messages/count_tokens")
    async def count_tokens(request: Request):  # noqa: ANN202
        body, request_id = await _ingest(request, st, "/v1/messages/count_tokens")
        payload = _parse_json(body)
        alias = payload.get("model", "unknown")
        st.record_request(alias=alias, endpoint="/v1/messages/count_tokens",
                          request_id=request_id, latency_ms=0.0)
        return {"input_tokens": _approx_tokens(_prompt_text_anthropic(payload))}

    @app.get("/v1/models")
    async def models(request: Request):  # noqa: ANN202
        # pasa por el centinela como cualquier request (A6): una fuga podría venir acá
        _body, request_id = await _ingest(request, st, "/v1/models")
        st.record_request(endpoint="/v1/models", request_id=request_id, latency_ms=0.0)
        return {
            "data": [
                {"type": "model", "id": "claude-sonnet-4-5-stub",
                 "display_name": "Stub Claude Sonnet 4.5", "created_at": "2026-01-01T00:00:00Z"},
                {"type": "model", "id": "claude-opus-4-stub",
                 "display_name": "Stub Claude Opus 4", "created_at": "2026-01-01T00:00:00Z"},
            ],
            "has_more": False, "first_id": "claude-sonnet-4-5-stub",
            "last_id": "claude-opus-4-stub",
        }

    # ── API de control (orquestador) ────────────────────────────────────────────────
    register_control_routes(app, st)

    # ── 404 ruidoso y contado (SIEMPRE al final — atrapa todo lo no contratado) ──────
    @app.api_route("/{full_path:path}",
                   methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"])
    async def not_contracted(full_path: str, request: Request):  # noqa: ANN202
        await _ingest(request, st, f"/{full_path}")  # también se escanea/spoolea
        st.not_found += 1
        return JSONResponse(
            status_code=404,
            content={"error": "endpoint no contratado (cableado incompleto)",
                     "path": "/" + full_path, "method": request.method},
        )

    return app


# Instancia por defecto para ``uvicorn basa_harness.stub.server:app`` (serving real). El
# spool queda deshabilitado hasta que el orquestador configure ``spool_dir`` vía control.
app = create_app()
