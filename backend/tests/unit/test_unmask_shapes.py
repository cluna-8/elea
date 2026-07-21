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


def test_stream_truncado_carry_pendiente_se_flushea_en_stop():
    # Truncación REAL (review 024): el placeholder queda incompleto (sin ']') → el
    # carry llega VIVO al content_block_stop y el flush emite lo retenido tal cual
    # (irrestaurable sin cierre) — 0 texto perdido.
    got = _feed(["fin ", "[", "EMAIL_ADDRESS_0_ab"])
    assert got == "fin [EMAIL_ADDRESS_0_ab"


def test_stream_multiples_placeholders_en_un_item():
    m = dict(MAP)
    m["[PERSON_1_cd34]"] = "Laura Pérez"
    ev = {"type": "content_block_delta", "index": 0,
          "delta": {"type": "text_delta",
                    "text": "de [PERSON_1_cd34] con [EMAIL_ADDRESS_0_ab12] hoy"}}
    events, carry, cf = policy.unmask_delta_event(ev, "", None, m)
    assert events[0]["delta"]["text"] == f"de Laura Pérez con {ORIG} hoy"
    assert carry == ""


def test_sse_bytes_loop_multibyte_y_placeholder_partidos():
    # Réplica del algoritmo del hook (decoder incremental + buffer \n\n +
    # rewrite_sse_block + flush framed): un multibyte UTF-8 partido entre chunks de
    # BYTES y el placeholder partido tras el '[' — el texto reconstruido es exacto.
    import codecs as _codecs
    import json as _json

    def _sse(text):
        ev = {"type": "content_block_delta", "index": 0,
              "delta": {"type": "text_delta", "text": text}}
        return ("event: content_block_delta\ndata: "
                + _json.dumps(ev, ensure_ascii=False) + "\n\n").encode("utf-8")

    frames = _sse("operó ") + _sse("[") + _sse("EMAIL_ADDRESS_0_ab12") + _sse("] fin")
    # partir los bytes en pedazos que rompen un multibyte ('ó' = 2 bytes)
    chunks = [frames[:9], frames[9:31], frames[31:]]

    decoder = _codecs.getincrementaldecoder("utf-8")(errors="replace")
    buffer, carry, cf, txt = "", "", None, ""
    out_blocks_all = []
    for ch in chunks:
        buffer += decoder.decode(ch)
        while "\n\n" in buffer:
            block, buffer = buffer.split("\n\n", 1)
            if not block.strip():
                continue
            obs, carry, cf, _, _ = policy.rewrite_sse_block(block, carry, cf, MAP)
            out_blocks_all += obs
    if carry:
        out_blocks_all.append(policy.flush_carry_sse_block(carry, cf, MAP).strip())
    import json as _j
    for ob in out_blocks_all:
        for line in ob.split("\n"):
            if line.startswith("data: "):
                d = _j.loads(line[6:])
                txt += (d.get("delta") or {}).get("text", "")
    assert txt == f"operó {ORIG} fin"


def test_flush_carry_sse_block_va_framed():
    # Review 024: el flush del carry en un stream truncado DEBE salir como evento SSE
    # completo (data: + terminador) — crudo, el parser del cliente lo descarta.
    out = policy.flush_carry_sse_block("[EMAIL_ADDRESS_0_ab12]", "text", MAP)
    assert out.startswith("event: content_block_delta\ndata: ")
    assert out.endswith("\n\n")
    import json as _j
    d = _j.loads(out.split("data: ", 1)[1])
    assert d["delta"]["text"] == ORIG


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


def test_unmask_openai_tool_calls_y_text():
    # Review 024: los argumentos de tools y el shape /v1/completions también vuelven
    # restaurados — sin esto un agente ejecuta su tool con el placeholder.
    resp = {"choices": [{
        "text": f"visto {PH}",
        "message": {
            "role": "assistant", "content": None,
            "tool_calls": [{"id": "c1", "type": "function",
                            "function": {"name": "buscar",
                                         "arguments": f'{{"q": "{PH}"}}'}}],
        },
    }]}
    policy.unmask_response_payload(resp, MAP)
    assert resp["choices"][0]["text"] == f"visto {ORIG}"
    assert resp["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"] == \
        f'{{"q": "{ORIG}"}}'


def test_unmask_objeto_con_atributos_no_regresiona():
    # El shape de la ruta passthrough (objeto con .content) sigue funcionando.
    block = {"type": "text", "text": f"ver {PH}"}
    resp = SimpleNamespace(content=[block])
    policy.unmask_response_payload(resp, MAP)
    assert block["text"] == f"ver {ORIG}"


def test_unmask_sin_placeholders_queda_intacto():
    # Con mapping REAL sobre texto sin placeholders (invariante #1 del contrato):
    # recorre el payload y no cambia nada. El caso mapping vacío (early-return,
    # FR-005) se cubre aparte.
    resp = _dict_anthropic()
    resp["content"] = [{"type": "text", "text": "sin datos sensibles [nota]"}]
    before = repr(resp)
    policy.unmask_response_payload(resp, MAP)
    assert repr(resp) == before


def test_unmask_mapping_vacio_early_return():
    resp = _dict_anthropic()
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
