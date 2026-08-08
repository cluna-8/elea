"""Tests de contrato del stub (spec 035, T018; contract ``stub-wire.md``).

In-process con el ASGI de FastAPI (httpx ``AsyncClient`` + ``ASGITransport``, sin levantar
un servidor real). Verifican los DOS wires (frames SSE bien formados), el pacing
registrado, el centinela de canarios (inline con doble red + partido entre chunks + spool
finalizado == inline), la inyección de error determinista con sus palancas, el tráfico no
auditable y el 404 ruidoso contado.

Los asserts de tiempo son ESTRUCTURALES (orden/forma/registro) o usan un reloj FALSO
determinista — nunca el reloj real (el contrato prohíbe asserts frágiles de timing).
"""
from __future__ import annotations

import gzip
import json

import pytest
from httpx import ASGITransport, AsyncClient

from basa_harness.corpus import generate_canaries
from basa_harness.stub import (
    CanarySentinel,
    SpoolTruncatedError,
    StubState,
    create_app,
    sweep_spool,
)


# ── fixtures / helpers ───────────────────────────────────────────────────────────────────

@pytest.fixture
async def stub():
    state = StubState(now_iso=lambda: "2026-08-12T00:00:00Z")
    app = create_app(state)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://stub") as client:
        yield client, state


def _client(state: StubState) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=create_app(state)),
                       base_url="http://stub")


class _FakeClock:
    """Reloj determinista: ``sleep(d)`` avanza el tiempo EXACTO ``d`` (A5)."""

    def __init__(self) -> None:
        self.t = 0.0

    def now(self) -> float:
        return self.t

    async def sleep(self, d: float) -> None:
        if d and d > 0:
            self.t += d


async def _collect_openai_sse(resp) -> tuple[list[dict], bool]:
    payloads: list[dict] = []
    done = False
    async for line in resp.aiter_lines():
        if not line.strip():
            continue
        assert line.startswith("data: "), f"frame OpenAI malformado: {line!r}"
        data = line[len("data: "):]
        if data == "[DONE]":
            done = True
            continue
        payloads.append(json.loads(data))  # bien formado o revienta acá
    return payloads, done


async def _collect_anthropic_sse(resp) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    cur_event = None
    async for line in resp.aiter_lines():
        if not line.strip():
            continue
        if line.startswith("event: "):
            cur_event = line[len("event: "):]
        elif line.startswith("data: "):
            events.append((cur_event, json.loads(line[len("data: "):])))
            cur_event = None
        else:
            raise AssertionError(f"línea SSE Anthropic malformada: {line!r}")
    return events


# ── Wire OpenAI ─────────────────────────────────────────────────────────────────────────

async def test_openai_chat_no_stream_shape(stub):
    client, _ = stub
    r = await client.post("/v1/chat/completions", json={
        "model": "gpt-stub", "messages": [{"role": "user", "content": "hola"}]})
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body["choices"][0]["message"]["content"], str)
    assert body["choices"][0]["finish_reason"] == "stop"
    assert "prompt_tokens" in body["usage"] and "completion_tokens" in body["usage"]


async def test_openai_chat_sse_frames_y_headers(stub):
    client, _ = stub
    await client.post("/control/config", json={
        "aliases": {"gpt-stub": {"latency_ms": 5, "token_rate": 200,
                                 "stream_duration_s": 0.03}}})
    async with client.stream("POST", "/v1/chat/completions", json={
        "model": "gpt-stub", "stream": True,
        "messages": [{"role": "user", "content": "hola"}]}) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        # headers anti-buffering de proveedor real (B1)
        assert resp.headers.get("x-accel-buffering") == "no"
        assert resp.headers.get("cache-control") == "no-cache"
        payloads, done = await _collect_openai_sse(resp)
    assert done, "faltó el cierre data: [DONE]"
    assert payloads[0]["choices"][0]["delta"].get("role") == "assistant"
    assert any(p["choices"][0]["delta"].get("content") for p in payloads if p["choices"])
    assert payloads[-1]["choices"][0]["finish_reason"] == "stop"


async def test_openai_embeddings_deterministas(stub):
    client, _ = stub
    await client.post("/control/config", json={"embedding_dim": 8})
    req = {"model": "emb-stub", "input": ["alfa", "beta"]}
    a = (await client.post("/v1/embeddings", json=req)).json()
    b = (await client.post("/v1/embeddings", json=req)).json()
    assert [d["index"] for d in a["data"]] == [0, 1]
    assert len(a["data"][0]["embedding"]) == 8
    assert a["data"][0]["embedding"] == b["data"][0]["embedding"]
    assert a["data"][0]["embedding"] != a["data"][1]["embedding"]


async def test_include_usage_en_stream(stub):
    """stream_options.include_usage → choices vacíos + usage determinista antes de [DONE] (B2)."""
    client, _ = stub
    await client.post("/control/config", json={
        "aliases": {"gpt-stub": {"token_rate": 100, "stream_duration_s": 0.03}}})
    async with client.stream("POST", "/v1/chat/completions", json={
        "model": "gpt-stub", "stream": True, "stream_options": {"include_usage": True},
        "messages": [{"role": "user", "content": "hola"}]}) as resp:
        payloads, done = await _collect_openai_sse(resp)
    assert done
    usage_frames = [p for p in payloads if "usage" in p]
    assert usage_frames and usage_frames[-1]["choices"] == []
    u = usage_frames[-1]["usage"]
    assert {"prompt_tokens", "completion_tokens", "total_tokens"} <= set(u)


# ── Wire Anthropic ──────────────────────────────────────────────────────────────────────

async def test_anthropic_messages_sse_secuencia_exacta(stub):
    client, _ = stub
    await client.post("/control/config", json={
        "aliases": {"claude-stub": {"latency_ms": 5, "token_rate": 200,
                                    "stream_duration_s": 0.03}}})
    async with client.stream("POST", "/v1/messages", json={
        "model": "claude-stub", "stream": True, "max_tokens": 64,
        "messages": [{"role": "user", "content": "hola"}]}) as resp:
        assert resp.status_code == 200
        events = await _collect_anthropic_sse(resp)
    tipos = [e for e, _ in events]
    assert tipos[0] == "message_start"
    assert tipos[1] == "content_block_start"
    assert tipos[-3] == "content_block_stop"
    assert tipos[-2] == "message_delta"
    assert tipos[-1] == "message_stop"
    assert tipos.count("content_block_delta") >= 1
    first_delta = tipos.index("content_block_delta")
    assert first_delta > 1 and tipos.index("content_block_stop") > first_delta
    md = next(d for e, d in events if e == "message_delta")
    assert "output_tokens" in md["usage"]


async def test_anthropic_no_stream_count_tokens_models(stub):
    client, _ = stub
    r = await client.post("/v1/messages", json={
        "model": "claude-stub", "max_tokens": 32,
        "messages": [{"role": "user", "content": "hola mundo"}]})
    assert r.status_code == 200
    body = r.json()
    assert body["type"] == "message" and body["role"] == "assistant"
    assert body["content"][0]["type"] == "text"
    assert "input_tokens" in body["usage"] and "output_tokens" in body["usage"]

    ct = await client.post("/v1/messages/count_tokens", json={
        "model": "claude-stub", "messages": [{"role": "user", "content": "hola"}]})
    assert ct.status_code == 200 and isinstance(ct.json()["input_tokens"], int)

    ms = await client.get("/v1/models")
    assert ms.status_code == 200 and len(ms.json()["data"]) >= 1


# ── Pacing / auto-headroom ───────────────────────────────────────────────────────────────

async def test_pacing_programado_queda_registrado(stub):
    client, _ = stub
    await client.post("/control/config", json={
        "aliases": {"gpt-stub": {"latency_ms": 20, "token_rate": 200,
                                 "stream_duration_s": 0.03}}})
    async with client.stream("POST", "/v1/chat/completions", json={
        "model": "gpt-stub", "stream": True,
        "messages": [{"role": "user", "content": "hola"}]}) as resp:
        await _collect_openai_sse(resp)
    rep = (await client.get("/control/report")).json()
    assert rep["programmed_latency_ms_por_alias"]["gpt-stub"]["latency_ms"] == 20
    assert rep["requests_por_alias"]["gpt-stub"] == 1
    for k in ("p50", "p95", "p99", "max", "n"):
        assert k in rep["pacing_drift_ms"]
    assert rep["pacing_drift_ms"]["n"] >= 1
    assert "cpu_pct" in rep and rep["umbral"]["drift_p99_ms"] == 5.0


async def test_pacing_grilla_modelo_abierto_reloj_falso():
    """Grilla de modelo abierto verificada con reloj FALSO: targets = latency + i/rate,
    drift ~ 0 (no hay assert de tiempo real — A5)."""
    fc = _FakeClock()
    state = StubState(now_iso=lambda: "t", clock=fc.now, sleep=fc.sleep)
    state.apply_config({"aliases": {"m": {"latency_ms": 30, "token_rate": 100,
                                          "stream_duration_s": 0.10}}})
    n = 10  # round(100 * 0.10)
    async with _client(state) as client:
        async with client.stream("POST", "/v1/chat/completions", json={
                "model": "m", "stream": True,
                "messages": [{"role": "user", "content": "x"}]}) as resp:
            await _collect_openai_sse(resp)
    # reloj final = latencia (0.030) + n/token_rate (0.100); drift exacto 0
    assert fc.t == pytest.approx(0.030 + n / 100.0)
    rep = state.report()
    assert rep["pacing_drift_ms"]["n"] == n
    assert rep["pacing_drift_ms"]["max"] == 0.0


def test_cpu_pct_rango():
    """cpu_pct asume 1 proceso/1 loop → float >= 0 (B4)."""
    st = StubState()
    total = 0
    for i in range(200_000):
        total += i
    c = st.cpu_pct()
    assert isinstance(c, float) and c >= 0.0


# ── Canarios: detección inline (doble red) ───────────────────────────────────────────────

async def test_canario_inline_por_http(stub):
    client, _ = stub
    canaries = generate_canaries("run-http", 2)
    await client.post("/control/config", json={"masking_config": {"default": "on"}})
    r = await client.post("/control/canaries", json={"canaries": canaries})
    assert r.json()["canary_set_size"] == 2

    ok = await client.post("/v1/chat/completions", json={
        "model": "m", "messages": [{"role": "user", "content": "texto sin pii"}]})
    assert ok.status_code == 200

    leaked = canaries[0]["value"]
    await client.post("/v1/chat/completions", json={
        "model": "m", "messages": [{"role": "user", "content": f"mi dato {leaked}"}]})

    rep = (await client.get("/control/report")).json()
    assert rep["leak_count"] == 1
    ev = rep["canarios_detectados"][0]
    assert ev["canary_id"] == canaries[0]["canary_id"]
    assert ev["request_id"]
    assert ev["surface"] == "/v1/chat/completions"
    assert ev["config_masking_vigente"] == {"default": "on"}


def test_canario_escapado_json_detectado(tmp_path):
    """Un canario con tilde, comilla y backslash, embebido vía json.dumps (viaja
    escapado), DEBE detectarse inline y en el barrido (hallazgo A3 — corazón del SLO)."""
    nasty = {"canary_id": "canary-nasty", "run_id": "r", "nonce": "n",
             "entity_type": "PERSON", "value": 'José"O\'Brien\\ruta-9f3a'}
    sentinel = CanarySentinel(spool_dir=tmp_path)
    sentinel.configure_run("run-nasty")
    sentinel.load_canaries([nasty])
    body = json.dumps({"model": "m", "messages": [
        {"role": "user", "content": f"dato {nasty['value']}"}]}).encode("utf-8")
    ev = sentinel.scan_body(request_id="r1", endpoint="/v1/chat/completions", body=body,
                            config_masking={}, timestamp="t")
    assert len(ev) == 1 and ev[0].canary_id == "canary-nasty"
    sentinel.close()
    swept = sweep_spool(sentinel.current_spool_path, [nasty])
    assert len(swept) == 1


def test_canario_partido_entre_chunks_detectado():
    """Buffer POR REQUEST: chunks aislados no contienen el canario que cruza la frontera;
    el cuerpo ACUMULADO sí (contract: caso borde obligatorio)."""
    canaries = generate_canaries("run-split", 1)
    value = canaries[0]["value"].encode("utf-8")
    mid = len(value) // 2
    sentinel = CanarySentinel()  # sin spool
    sentinel.load_canaries(canaries)
    half1 = b'{"c":"' + value[:mid]
    half2 = value[mid:] + b'"}'
    assert sentinel.scan_body(request_id="r1", endpoint="/v1/messages", body=half1) == []
    assert sentinel.scan_body(request_id="r2", endpoint="/v1/messages", body=half2) == []
    ev = sentinel.scan_body(request_id="r3", endpoint="/v1/messages", body=half1 + half2)
    assert len(ev) == 1 and ev[0].canary_id == canaries[0]["canary_id"]


# ── Canarios: spool (finalize, sweep, namespaciado) ──────────────────────────────────────

def test_spool_barrido_coincide_con_inline(tmp_path):
    """SC-004 en pequeño: el barrido post-run del spool finalizado reproduce EXACTO los
    hits del detector inline."""
    canaries = generate_canaries("run-spool", 3)
    sentinel = CanarySentinel(spool_dir=tmp_path)
    sentinel.configure_run("run-spool")
    sentinel.load_canaries(canaries)
    inline = []
    inline += sentinel.scan_body(request_id="r1", endpoint="/v1/chat/completions",
                                 body=b"cuerpo limpio")
    inline += sentinel.scan_body(request_id="r2", endpoint="/v1/chat/completions",
                                 body=("fuga " + canaries[0]["value"]).encode("utf-8"))
    inline += sentinel.scan_body(request_id="r3", endpoint="/v1/messages",
                                 body=("otra " + canaries[2]["value"]).encode("utf-8"))
    sentinel.close()
    swept = sweep_spool(sentinel.current_spool_path, canaries)
    inline_keys = sorted((e.request_id, e.canary_id) for e in inline)
    swept_keys = sorted((e.request_id, e.canary_id) for e in swept)
    assert inline_keys == swept_keys
    assert len(inline_keys) == 2


def test_spool_sin_finalize_falla_ruidoso(tmp_path):
    """Barrer un spool sin finalizar (frame truncado) → error RUIDOSO, jamás menos
    registros en silencio (hallazgo A1)."""
    canaries = generate_canaries("run-a1b", 1)
    sentinel = CanarySentinel(spool_dir=tmp_path)
    sentinel.configure_run("run-a1b")
    sentinel.load_canaries(canaries)
    sentinel.scan_body(request_id="r0", endpoint="/v1/messages",
                       body=canaries[0]["value"].encode("utf-8"))
    with pytest.raises(SpoolTruncatedError):
        sweep_spool(sentinel.current_spool_path, canaries)  # sin close() → truncado


def test_spool_finalize_barre_todos(tmp_path):
    """Con finalize, el barrido encuentra TODOS los hits (nada perdido en silencio)."""
    canaries = generate_canaries("run-a1", 1)
    sentinel = CanarySentinel(spool_dir=tmp_path)
    sentinel.configure_run("run-a1")
    sentinel.load_canaries(canaries)
    for i in range(5):
        body = (("con " + canaries[0]["value"]).encode("utf-8")
                if i % 2 == 0 else b"limpio")
        sentinel.scan_body(request_id=f"r{i}", endpoint="/v1/messages", body=body)
    sentinel.close()
    swept = sweep_spool(sentinel.current_spool_path, canaries)
    assert len(swept) == 3  # i = 0, 2, 4


def test_spool_finalize_run_vacio_no_es_truncado(tmp_path):
    """Un run limpio/sin tráfico finalizado barre a [] SIN falso SpoolTruncatedError (el
    orquestador finaliza TODOS los runs, incluidos los vacíos)."""
    sentinel = CanarySentinel(spool_dir=tmp_path)
    sentinel.configure_run("run-vacio")
    sentinel.close()
    assert sweep_spool(sentinel.current_spool_path, []) == []


def test_spool_namespaciado_por_run(tmp_path):
    """Dos run_id → dos archivos; el segundo NO destruye la evidencia del primero (A2)."""
    canaries = generate_canaries("shared", 1)
    sentinel = CanarySentinel(spool_dir=tmp_path)
    sentinel.load_canaries(canaries)

    sentinel.configure_run("run-A")
    sentinel.scan_body(request_id="a0", endpoint="/v1/messages",
                       body=canaries[0]["value"].encode("utf-8"))
    path_a = sentinel.current_spool_path
    sentinel.close()

    sentinel.configure_run("run-B")
    sentinel.scan_body(request_id="b0", endpoint="/v1/messages", body=b"limpio")
    path_b = sentinel.current_spool_path
    sentinel.close()

    assert path_a != path_b and path_a.exists() and path_b.exists()
    assert len(sweep_spool(path_a, canaries)) == 1
    assert len(sweep_spool(path_b, canaries)) == 0


# ── Content-Encoding: gzip auditable / no soportado marcado ──────────────────────────────

async def test_gzip_body_canario_detectado(tmp_path):
    """Body gzip con canario → descomprimido y DETECTADO (A4)."""
    state = StubState(spool_dir=tmp_path, now_iso=lambda: "t")
    canaries = generate_canaries("run-gz", 1)
    payload = json.dumps({"model": "m", "messages": [
        {"role": "user", "content": canaries[0]["value"]}]}).encode("utf-8")
    gz = gzip.compress(payload)
    async with _client(state) as client:
        await client.post("/control/config", json={"run_id": "run-gz"})
        await client.post("/control/canaries", json={"canaries": canaries})
        r = await client.post("/v1/chat/completions", content=gz,
                              headers={"content-encoding": "gzip",
                                       "content-type": "application/json"})
        assert r.status_code == 200
        rep = (await client.get("/control/report")).json()
    assert rep["leak_count"] == 1
    assert rep["trafico_no_auditable"]["count"] == 0


async def test_encoding_no_soportado_marcado_no_auditable(tmp_path):
    """Encoding no soportado (br) → NO se scanea a ciegas: se marca RUIDOSAMENTE como
    tráfico no auditable, jamás 0 en silencio (A4)."""
    state = StubState(spool_dir=tmp_path, now_iso=lambda: "t")
    canaries = generate_canaries("run-br", 1)
    async with _client(state) as client:
        await client.post("/control/config", json={"run_id": "run-br"})
        await client.post("/control/canaries", json={"canaries": canaries})
        r = await client.post("/v1/chat/completions", content=b"\x1f\x8b\xde\xad\xbe\xef",
                              headers={"content-encoding": "br"})
        assert r.status_code == 200
        rep = (await client.get("/control/report")).json()
    assert rep["trafico_no_auditable"]["count"] == 1
    assert rep["trafico_no_auditable"]["requests"][0]["content_encoding"] == "br"
    assert rep["leak_count"] == 0


async def test_encoding_mal_declarado_igual_se_detecta(tmp_path):
    """Encoding mal declarado (dice gzip, viaja en claro): el decode falla → se marca
    no auditable PERO el crudo se escanea best-effort y el canario se DETECTA igual
    (nunca 0 en silencio — A4)."""
    state = StubState(spool_dir=tmp_path, now_iso=lambda: "t")
    canaries = generate_canaries("run-mislabel", 1)
    plano = json.dumps({"model": "m", "messages": [
        {"role": "user", "content": canaries[0]["value"]}]}).encode("utf-8")
    async with _client(state) as client:
        await client.post("/control/config", json={"run_id": "run-mislabel"})
        await client.post("/control/canaries", json={"canaries": canaries})
        r = await client.post("/v1/chat/completions", content=plano,
                              headers={"content-encoding": "gzip"})  # miente: no es gzip
        assert r.status_code == 200
        rep = (await client.get("/control/report")).json()
    assert rep["leak_count"] == 1              # detectado best-effort
    assert rep["trafico_no_auditable"]["count"] == 1  # y flaggeado ruidosamente


# ── Conteo honesto + models por el centinela + masking en sweep ──────────────────────────

async def test_conteo_honesto_models_y_masking_en_sweep(tmp_path):
    state = StubState(spool_dir=tmp_path, now_iso=lambda: "t")
    canaries = generate_canaries("run-a6", 2)
    async with _client(state) as client:
        await client.post("/control/config", json={"run_id": "run-a6",
                                                   "masking_config": {"default": "on"}})
        await client.post("/control/canaries", json={"canaries": canaries})
        await client.post("/v1/chat/completions", json={
            "model": "m", "messages": [
                {"role": "user", "content": f"x {canaries[0]['value']}"}]})
        await client.get("/v1/models")
        await client.get("/nope-inexistente")
        await client.post("/control/finalize")
        rep = (await client.get("/control/report")).json()
    # models pasó por el centinela y quedó contado
    assert rep["requests_por_endpoint"]["/v1/models"] == 1
    # honesto: chat(1)+models(1)=2 contratados + 1 not_found = 3 total
    assert rep["requests_contratados"] == 2
    assert rep["requests_total"] == 3
    assert rep["not_found"] == 1
    # el barrido reconstruye el masking vigente del record (A6a)
    swept = sweep_spool(state.sentinel.current_spool_path, canaries)
    assert len(swept) == 1
    assert swept[0].config_masking_vigente == {"default": "on"}


async def test_reset_limpia_canarios_y_contadores(stub):
    client, _ = stub
    canaries = generate_canaries("run-reset", 1)
    await client.post("/control/canaries", json={"canaries": canaries})
    await client.post("/v1/messages", json={
        "model": "m", "max_tokens": 8,
        "messages": [{"role": "user", "content": canaries[0]["value"]}]})
    assert (await client.get("/control/report")).json()["leak_count"] == 1
    await client.post("/control/reset")
    rep = (await client.get("/control/report")).json()
    assert rep["leak_count"] == 0 and rep["canary_set_size"] == 0
    assert rep["requests_total"] == 0


# ── Inyección de error: shape, palancas terminal y mid-stream ────────────────────────────

async def test_error_inyectado_shape_openai(stub):
    client, _ = stub
    await client.post("/control/config", json={
        "seed": 7, "aliases": {"gpt-stub": {"error_rate": 1.0}}})
    r = await client.post("/v1/chat/completions", json={
        "model": "gpt-stub", "messages": [{"role": "user", "content": "x"}]})
    assert r.status_code == 429
    assert r.json()["error"]["type"] == "stub_error"


async def test_error_inyectado_shape_anthropic(stub):
    client, _ = stub
    await client.post("/control/config", json={
        "seed": 7, "aliases": {"claude-stub": {"error_rate": 1.0}}})
    r = await client.post("/v1/messages", json={
        "model": "claude-stub", "max_tokens": 8,
        "messages": [{"role": "user", "content": "x"}]})
    assert r.status_code == 529
    assert r.json()["type"] == "error"


async def test_error_terminal_status(stub):
    """Palanca error_terminal → clase NO reintentable (500) (B3)."""
    client, _ = stub
    await client.post("/control/config", json={
        "aliases": {"gpt-stub": {"error_rate": 1.0, "error_terminal": True}}})
    r = await client.post("/v1/chat/completions", json={
        "model": "gpt-stub", "messages": [{"role": "user", "content": "x"}]})
    assert r.status_code == 500
    assert r.json()["error"]["type"] == "invalid_request_error"


async def test_error_mid_stream_openai(stub):
    """Palanca error_mid_stream → frames válidos y luego objeto de error, sin [DONE] (B3)."""
    client, _ = stub
    await client.post("/control/config", json={
        "aliases": {"gpt-stub": {"error_rate": 1.0, "error_mid_stream": True,
                                 "token_rate": 100, "stream_duration_s": 0.06}}})
    async with client.stream("POST", "/v1/chat/completions", json={
        "model": "gpt-stub", "stream": True,
        "messages": [{"role": "user", "content": "x"}]}) as resp:
        assert resp.status_code == 200
        payloads, done = await _collect_openai_sse(resp)
    assert not done  # cortó a mitad: no hay [DONE]
    assert any("error" in p for p in payloads)
    assert any(p["choices"] and p["choices"][0]["delta"].get("content")
               for p in payloads if p.get("choices"))


async def test_error_mid_stream_anthropic(stub):
    client, _ = stub
    await client.post("/control/config", json={
        "aliases": {"claude-stub": {"error_rate": 1.0, "error_mid_stream": True,
                                    "token_rate": 100, "stream_duration_s": 0.06}}})
    async with client.stream("POST", "/v1/messages", json={
        "model": "claude-stub", "stream": True, "max_tokens": 32,
        "messages": [{"role": "user", "content": "x"}]}) as resp:
        events = await _collect_anthropic_sse(resp)
    tipos = [e for e, _ in events]
    assert "error" in tipos
    assert "message_stop" not in tipos  # se cortó a mitad


def test_error_determinista_por_semilla():
    """Misma semilla + misma SECUENCIA por alias ⇒ mismo patrón (reproducible). Bajo
    concurrencia solo la TASA es determinista, no QUÉ request puntual falla."""
    def secuencia() -> list[bool]:
        st = StubState()
        st.apply_config({"seed": 123, "aliases": {"m": {"error_rate": 0.4}}})
        return [st.should_error("m") for _ in range(60)]

    s1, s2 = secuencia(), secuencia()
    assert s1 == s2
    assert 0 < sum(s1) < 60


# ── 404 ruidoso y contado ────────────────────────────────────────────────────────────────

async def test_404_ruidoso_y_contado(stub):
    client, _ = stub
    r = await client.get("/v1/no-existe")
    assert r.status_code == 404
    assert "no contratado" in r.json()["error"]
    r2 = await client.post("/foo/bar", json={"x": 1})
    assert r2.status_code == 404
    rep = (await client.get("/control/report")).json()
    assert rep["not_found"] == 2
