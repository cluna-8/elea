"""T084 de Sentinel (FR-036, research D7): continuidad de razonamiento entre turnos con un destino traducido.

Los bloques `thinking` que produce un destino traducido salen con firma HMAC de la pasarela (atada al destino
y al texto); en el turno siguiente una firma propia se reconstruye (sin la firma) para el destino que lo exige,
y una firma ajena o inválida descarta el bloque sin error ni rastros.
"""
import asyncio
import json

import pytest

from sentinel.redirect import authz, stream, thinking
from sentinel.redirect.plugin import RedirectPlugin
from sentinel.tests import corpus_claude as corpus
from sentinel.tests import redirect_fixtures as fx

DEST = "d-chat"
REPLAY = {**fx.DEST_CHAT, "id": "d-replay", "name": "Con replay", "provider": "deepseek",
          "capability_profile": {"thinking": True, "cache_control": False}}


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setenv(authz.KEY_ENV, fx.INTERNAL_KEY)


# ── la firma ───────────────────────────────────────────────────────────────────

def test_firma_ida_y_vuelta_atada_al_destino_y_al_texto():
    sig = thinking.sign(DEST, "Pienso en el plan.")
    assert sig.startswith(thinking.PREFIX) and thinking.verify(DEST, "Pienso en el plan.", sig)
    assert not thinking.verify("otro-destino", "Pienso en el plan.", sig)          # rastro de otro destino
    assert not thinking.verify(DEST, "Pienso en otro plan.", sig)                  # texto alterado
    assert not thinking.verify(DEST, "Pienso en el plan.", sig[:-2] + "xx")        # firma alterada


@pytest.mark.parametrize("sig", [None, "", 12, "FIRMA-AJENA-DE-OTRO-PROVEEDOR", thinking.PREFIX, thinking.PREFIX + "%%%"])
def test_cualquier_firma_ajena_o_malformada_no_valida_y_no_levanta(sig):
    assert thinking.verify(DEST, "texto", sig) is False


def test_la_firma_no_revela_ni_el_texto_ni_el_destino_ni_la_clave():
    sig = thinking.sign(DEST, "texto secreto del razonamiento")
    for dato in ("texto secreto", DEST, fx.INTERNAL_KEY):
        assert dato not in sig


def test_sin_clave_no_hay_firma_ni_validacion(monkeypatch):
    monkeypatch.delenv(authz.KEY_ENV)
    assert thinking.sign(DEST, "x") == "" and thinking.verify(DEST, "x", "rdxs1.abc") is False


def test_la_clave_de_la_firma_es_distinta_de_la_de_la_autorizacion(monkeypatch):
    sig = thinking.sign(DEST, "x")
    monkeypatch.setenv(authz.KEY_ENV, "z" * 48)
    assert not thinking.verify(DEST, "x", sig)                                      # otra instalación


# ── stream: firma al cerrar el bloque ──────────────────────────────────────────

async def _run(events, *, dest=DEST):
    async def src():
        for e in events:
            yield corpus.sse([e]) if isinstance(e, dict) else e

    out = b"".join([c async for c in stream.wrap_sse(src(), public_model="claude-sonnet-4-5", face="claude",
                                                     ping_after=None, thinking_signer=lambda t: thinking.sign(dest, t))])
    return [f for f in out.decode().split("\n\n") if f]


def _datas(frames):
    return [json.loads("\n".join(ln[5:].lstrip() for ln in f.split("\n") if ln.startswith("data:"))) for f in frames]


async def test_el_bloque_thinking_sale_con_la_firma_de_la_pasarela_y_sin_la_del_destino():
    events = [e for e in corpus.stream_events() if e["event"] != "ping"]
    frames = await _run(events)
    datas = _datas(frames)
    sigs = [d for d in datas if d.get("delta", {}).get("type") == "signature_delta"]
    assert len(sigs) == 1 and "FIRMA-DEL-DESTINO" not in "".join(frames)
    assert thinking.verify(DEST, "Pienso en el plan.", sigs[0]["delta"]["signature"])
    # la firma va antes del content_block_stop del mismo bloque y el orden del resto no cambia
    kinds = [d["type"] for d in datas]
    i = datas.index(sigs[0])
    assert kinds[i + 1] == "content_block_stop" and datas[i + 1]["index"] == 0
    assert kinds.count("content_block_stop") == 3


async def test_un_destino_que_no_firma_igual_recibe_la_firma_de_la_pasarela():
    events = [e for e in corpus.stream_events() if e["event"] != "ping"
              and e["data"].get("delta", {}).get("type") != "signature_delta"]
    sigs = [d for d in _datas(await _run(events)) if d.get("delta", {}).get("type") == "signature_delta"]
    assert len(sigs) == 1 and thinking.verify(DEST, "Pienso en el plan.", sigs[0]["delta"]["signature"])


async def test_varios_deltas_de_razonamiento_se_firman_juntos_y_los_bloques_de_texto_no_se_firman():
    def d(i, t):
        return {"event": "content_block_delta", "data": {"type": "content_block_delta", "index": i,
                                                         "delta": {"type": "thinking_delta", "thinking": t}}}
    events = [corpus.stream_events()[0],
              {"event": "content_block_start", "data": {"type": "content_block_start", "index": 0,
                                                        "content_block": {"type": "thinking", "thinking": ""}}},
              d(0, "uno "), d(0, "dos"), {"event": "content_block_stop", "data": {"type": "content_block_stop", "index": 0}},
              {"event": "content_block_start", "data": {"type": "content_block_start", "index": 1,
                                                        "content_block": {"type": "text", "text": ""}}},
              {"event": "content_block_stop", "data": {"type": "content_block_stop", "index": 1}}]
    sigs = [x for x in _datas(await _run(events)) if x.get("delta", {}).get("type") == "signature_delta"]
    assert len(sigs) == 1 and thinking.verify(DEST, "uno dos", sigs[0]["delta"]["signature"])


async def test_sin_signer_el_stream_no_cambia_el_razonamiento():          # nativos y cara genérica
    async def src():
        yield corpus.sse(corpus.stream_events()[:5])

    out = b"".join([c async for c in stream.wrap_sse(src(), public_model="p", face="claude", ping_after=None)])
    assert b"FIRMA-DEL-DESTINO" in out


# ── respuesta no-stream ────────────────────────────────────────────────────────

async def test_respuesta_no_stream_firma_los_bloques_thinking():
    p = RedirectPlugin(store=fx.store(fx.snapshot("on")), ping_after=0.05)
    c = fx.ctx(route="/v1/messages", model="claude-sonnet-4-5")
    await p.pre_request(c)
    body = {"id": "m", "type": "message", "model": "qwen", "content": [
        {"type": "thinking", "thinking": "razono", "signature": "FIRMA-DEL-DESTINO"},
        {"type": "thinking", "thinking": "sin firma"}, {"type": "text", "text": "hola"}], "usage": {}}
    _, content, _ = p.map_response(c, 200, json.dumps(body).encode())
    blocks = json.loads(content)["content"]
    assert thinking.verify(DEST, "razono", blocks[0]["signature"]) and thinking.verify(DEST, "sin firma", blocks[1]["signature"])
    assert "signature" not in blocks[2] and "FIRMA-DEL-DESTINO" not in content.decode()


# ── turno siguiente: reconstrucción o descarte ─────────────────────────────────

def _turno2(sig, text="Primero busco las notas.", extra_blocks=()):
    return {"model": "claude-sonnet-4-5", "max_tokens": 100, "messages": [
        {"role": "user", "content": "hola"},
        {"role": "assistant", "content": [{"type": "thinking", "thinking": text, "signature": sig},
                                          *extra_blocks, {"type": "text", "text": "Busco."}]},
        {"role": "user", "content": "seguí"}]}


def _snapshot_con(dest):
    snap = fx.snapshot("on", claude_targets=(dest["id"],))
    return snap.__class__(**{**snap.__dict__, "destinations": {**snap.destinations, dest["id"]: dest},
                             "credentials": {**snap.credentials, dest["id"]: fx.CREDS["d-chat"]}})


async def _enviar(snap, body):
    p = RedirectPlugin(store=fx.store(snap), ping_after=0.05)
    c = fx.ctx(route="/v1/messages", model="claude-sonnet-4-5")
    assert await p.pre_request(c) is None
    out, _ = p.pre_engine(c, body, {})
    return c, out


def _asistente(out):
    return next(m for m in out["messages"] if m["role"] == "assistant")["content"]


async def test_firma_propia_valida_se_reconstruye_sin_la_firma_para_el_destino_que_lo_exige():
    sig = thinking.sign("d-replay", "Primero busco las notas.")
    c, out = await _enviar(_snapshot_con(REPLAY), _turno2(sig))
    assert _asistente(out)[0] == {"type": "thinking", "thinking": "Primero busco las notas."}
    assert sig not in json.dumps(out)
    assert c.routing_decision["extensions"]["redirect"]["thinking_replayed"] == 1


async def test_firma_propia_valida_pero_destino_que_no_lo_exige_se_descarta():
    sig = thinking.sign(DEST, "Primero busco las notas.")
    c, out = await _enviar(fx.snapshot("on"), _turno2(sig))
    assert [b["type"] for b in _asistente(out)] == ["text"]
    assert "Primero busco" not in json.dumps(out)
    assert c.routing_decision["extensions"]["redirect"]["thinking_dropped"] == 1


@pytest.mark.parametrize("sig", ["FIRMA-AJENA-DE-OTRO-PROVEEDOR", "", None])
async def test_firma_ajena_o_ausente_se_descarta_sin_error_y_sin_rastros(sig):
    block = {"type": "thinking", "thinking": "razonamiento del otro proveedor"}
    if sig is not None:
        block["signature"] = sig
    body = _turno2(sig)
    body["messages"][1]["content"][0] = block
    c, out = await _enviar(_snapshot_con(REPLAY), body)
    assert [b["type"] for b in _asistente(out)] == ["text"]
    texto = json.dumps(out)
    assert "otro proveedor" not in texto and (not sig or sig not in texto)


async def test_firma_de_otro_destino_se_descarta_aunque_sea_valida_para_este_sistema():
    sig = thinking.sign("d-chat", "Primero busco las notas.")                     # la hizo OTRO destino
    c, out = await _enviar(_snapshot_con(REPLAY), _turno2(sig))
    assert [b["type"] for b in _asistente(out)] == ["text"] and "Primero busco" not in json.dumps(out)


async def test_redacted_thinking_siempre_se_descarta_y_el_resto_del_turno_se_conserva():
    extra = ({"type": "redacted_thinking", "data": "CIFRADO"}, {"type": "tool_use", "id": "t1", "name": "Read", "input": {}})
    sig = thinking.sign("d-replay", "Primero busco las notas.")
    _, out = await _enviar(_snapshot_con(REPLAY), _turno2(sig, extra_blocks=extra))
    assert [b["type"] for b in _asistente(out)] == ["thinking", "tool_use", "text"] and "CIFRADO" not in json.dumps(out)


async def test_un_turno_que_queda_vacio_se_quita_y_el_pedido_sigue_valido():
    body = {"model": "claude-sonnet-4-5", "max_tokens": 10, "messages": [
        {"role": "user", "content": "hola"},
        {"role": "assistant", "content": [{"type": "thinking", "thinking": "x", "signature": "ajena"}]},
        {"role": "user", "content": "seguí"}]}
    _, out = await _enviar(fx.snapshot("on"), body)
    assert all(m["content"] for m in out["messages"]) and [m["role"] for m in out["messages"]] == ["user", "user"]


async def test_hacia_un_nativo_el_razonamiento_no_se_toca():
    body = _turno2("FIRMA-REAL-DEL-PROVEEDOR")
    snap = fx.snapshot("on", claude_targets=("d-ant",))
    p = RedirectPlugin(store=fx.store(snap), ping_after=0.05)
    c = fx.ctx(route="/v1/messages", model="claude-sonnet-4-5", nlp={"region": "us"})
    await p.pre_request(c)
    out, _ = p.pre_engine(c, body, {})
    assert _asistente(out)[0]["signature"] == "FIRMA-REAL-DEL-PROVEEDOR"


async def test_el_corpus_de_cowork_con_razonamiento_ajeno_no_llega_al_destino():
    body = corpus.load("cowork_multiturno")["body"]
    _, out = await _enviar(fx.snapshot("on"), {**body, "model": "claude-sonnet-4-5"})
    assert "thinking" not in json.dumps([m["content"] for m in out["messages"] if m["role"] == "assistant"]) \
        and "FIRMA-AJENA" not in json.dumps(out) and "Primero busco las notas de ejemplo" not in json.dumps(out)


# ── de punta a punta: turno 1 con razonamiento y turno 2 con la historia ────────

def test_e2e_el_razonamiento_firmado_en_el_turno_1_vuelve_reconstruido_en_el_turno_2(monkeypatch):
    from sentinel.tests import gw_harness as h
    env = h.gateway_env(monkeypatch)
    try:
        env.register(_snapshot_con(REPLAY))
        headers = {"Authorization": f"Bearer {h.VK}", "anthropic-version": "2023-06-01"}
        env.engine.stream_chunks = (corpus.sse([e for e in corpus.stream_events() if e["event"] != "ping"][:5]),)
        r = env.client.post("/gw/v1/messages", headers=headers, json={
            "model": "claude-sonnet-4-5", "max_tokens": 50, "stream": True,
            "messages": [{"role": "user", "content": "hola"}]})
        datas = _datas([f for f in r.content.decode().split("\n\n") if f])
        sig = next(d["delta"]["signature"] for d in datas if d.get("delta", {}).get("type") == "signature_delta")
        assert sig.startswith(thinking.PREFIX) and "FIRMA-DEL-DESTINO" not in r.text

        env.client.post("/gw/v1/messages", headers=headers, json=_turno2(sig, text="Pienso en el plan."))
        enviado = env.engine.sent[-1]["body"]
        assert _asistente(enviado)[0] == {"type": "thinking", "thinking": "Pienso en el plan."}

        env.client.post("/gw/v1/messages", headers=headers, json=_turno2("FIRMA-AJENA", text="de otro"))
        enviado = env.engine.sent[-1]["body"]
        assert [b["type"] for b in _asistente(enviado)] == ["text"] and "de otro" not in json.dumps(enviado)
    finally:
        h.close_env()
