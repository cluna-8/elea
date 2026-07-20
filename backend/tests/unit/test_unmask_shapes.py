"""Unit de la 024 — round-trip de restauración en rutas byok bridged (T003).

Los tres root causes verificados en vivo (research.md D1/D3 + apéndice T002):

1. Streaming: ``safe_split`` suelta un ``[`` pelado → un placeholder partido justo tras
   el ``[`` (deltas de 1-3 chars del bridge) pasa crudo al cliente.
2. No-streaming: la respuesta bridged es un ``dict`` plano y el unmask la leía con
   ``getattr`` → no-op silencioso.
3. Atribución: la identidad proxy se buscaba en un solo metadata-home y la ruta
   anthropic usa ``litellm_metadata``.

Escritos RED contra el código del 2026-07-20 (pre-fix); verdes con los fixes de la 024.
Contrato: specs/024-unmask-bridged-routes/contracts/unmask-roundtrip.md.
"""
from types import SimpleNamespace

from extensions import basa_guardian_policy as policy

PH = "[EMAIL_ADDRESS_0_ab12]"
ORIG = "laura.perez@hospital.es"
MAP = {PH: ORIG}


def _feed(chunks, field="text", typ="text_delta"):
    """Pasa una secuencia de deltas por el motor de carry y devuelve el texto emitido."""
    carry, cf, out = "", None, []
    for c in chunks:
        ev = {"type": "content_block_delta", "index": 2, "delta": {"type": typ, field: c}}
        events, carry, cf = policy.unmask_delta_event(ev, carry, cf, MAP)
        out += [e["delta"].get(field, "") for e in events if e.get("type") == "content_block_delta"]
    # cierre del bloque: flush del carry pendiente (0 texto perdido)
    events, carry, cf = policy.unmask_delta_event(
        {"type": "content_block_stop", "index": 2}, carry, cf, MAP)
    out += [e["delta"].get(field, "") for e in events if e.get("type") == "content_block_delta"]
    assert carry == ""
    return "".join(out)


# ── Root cause 1: streaming, placeholder partido en el borde exacto del '[' ──

def test_safe_split_retiene_bracket_pelado():
    # Un delta que termina en '[' puede ser el inicio de un placeholder partido:
    # se retiene UN delta (el siguiente decide). Hoy: se emite ya → RED.
    safe, carry = policy.safe_split("[")
    assert (safe, carry) == ("", "[")
    safe, carry = policy.safe_split("hola [")
    assert (safe, carry) == ("hola ", "[")


def test_stream_placeholder_partido_tras_el_bracket():
    # El caso EXACTO observado en vivo (bridge de Ollama, deltas de 1-3 chars):
    # el '[' llega solo y el resto del placeholder en pedacitos.
    got = _feed(["email ", "[", "EM", "AIL_ADDRESS", "_0_", "ab12", "]", " ayer"])
    assert got == f"email {ORIG} ayer"


def test_stream_bracket_de_prosa_no_se_pierde():
    # Un '[' que NO era placeholder (markdown/código) se emite en el siguiente delta
    # y el texto completo queda intacto — solo se difiere, jamás se pierde.
    got = _feed(["arr", "[", "i] = 3"])
    assert got == "arr[i] = 3"


def test_stream_placeholder_en_thinking_partido():
    got = _feed(["visto: ", "[", "EMAIL_ADDRESS_0_ab12", "]"], field="thinking", typ="thinking_delta")
    assert got == f"visto: {ORIG}"


def test_stream_truncado_flushea_carry_restaurado():
    # Stream cortado a mitad de placeholder: el cierre emite lo retenido (crudo si
    # incompleto, restaurado si completo) — 0 texto perdido.
    got = _feed(["fin ", "[", "EMAIL_ADDRESS_0_ab12]"])
    assert got == f"fin {ORIG}"


# ── Root cause 2: no-streaming, respuesta dict plano (shape bridged) ──

def _dict_anthropic():
    return {
        "id": "chatcmpl-x", "type": "message", "role": "assistant",
        "model": "propio", "stop_reason": "end_turn",
        "usage": {"input_tokens": 10, "output_tokens": 20},
        "content": [
            {"type": "thinking", "thinking": f"veo {PH} en el texto", "signature": None},
            {"type": "text", "text": f"El email es {PH}."},
            {"type": "tool_use", "id": "t1", "name": "buscar", "input": {"q": PH}},
        ],
    }


def test_unmask_dict_anthropic_restaura_text_thinking_y_tools():
    resp = _dict_anthropic()
    policy.unmask_response_payload(resp, MAP)
    assert resp["content"][0]["thinking"] == f"veo {ORIG} en el texto"
    assert resp["content"][1]["text"] == f"El email es {ORIG}."
    assert resp["content"][2]["input"] == {"q": ORIG}
    # FR-003: nada más cambia
    assert resp["id"] == "chatcmpl-x" and resp["usage"] == {"input_tokens": 10, "output_tokens": 20}


def test_unmask_dict_openai_choices():
    resp = {"choices": [{"message": {"role": "assistant", "content": f"mail: {PH}"}}]}
    policy.unmask_response_payload(resp, MAP)
    assert resp["choices"][0]["message"]["content"] == f"mail: {ORIG}"


def test_unmask_objeto_con_atributos_no_regresiona():
    # El shape de la ruta passthrough (objeto con .content) sigue funcionando.
    block = {"type": "text", "text": f"ver {PH}"}
    resp = SimpleNamespace(content=[block])
    policy.unmask_response_payload(resp, MAP)
    assert block["text"] == f"ver {ORIG}"


def test_unmask_sin_placeholders_queda_intacto():
    resp = _dict_anthropic()
    resp["content"] = [{"type": "text", "text": "sin datos"}]
    before = repr(resp)
    policy.unmask_response_payload(resp, {})
    assert repr(resp) == before


# ── Root cause 3: identidad proxy en ambos metadata-homes ──

def test_identidad_en_litellm_metadata_home():
    data = {"litellm_metadata": {"user_api_key_metadata": {"basa": {"tenant_slug": "default",
            "client_username": "spike-ollama", "tool_type": "claude-code"}}}}
    basa = policy.proxy_identity_from(data)
    assert basa["client_username"] == "spike-ollama"


def test_identidad_en_metadata_home_clasico():
    data = {"metadata": {"user_api_key_metadata": {"basa": {"client_username": "ana"}}}}
    assert policy.proxy_identity_from(data)["client_username"] == "ana"


def test_identidad_ausente_devuelve_vacio():
    assert policy.proxy_identity_from({}) == {}
    assert policy.proxy_identity_from({"metadata": {"user_api_key_metadata": {}}}) == {}
