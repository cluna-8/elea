"""Unit tests de basa_guardian_policy (spec 014 T006, FR-022).

Librería PURA: la detección se inyecta como callable — acá un detector fake por
patrones fijos, sin Presidio ni DB. Cubre: mask reversible con nonce, colisión de
placeholder con literal del usuario, carry-split (placeholder partido vs '[' suelto
de código), round-trip text/thinking/tool_use y stream truncado.
"""
import json
import re

import pytest

from extensions import basa_guardian_policy as policy

# Detector fake: emails y el nombre "Juan Pérez" (spans exactos, estilo Presidio)
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
_NAME = "Juan Pérez"


async def fake_analyze(text: str) -> list:
    entities = []
    for m in _EMAIL_RE.finditer(text):
        entities.append({"start": m.start(), "end": m.end(), "entity_type": "EMAIL_ADDRESS"})
    start = text.find(_NAME)
    while start != -1:
        entities.append({"start": start, "end": start + len(_NAME), "entity_type": "PERSON"})
        start = text.find(_NAME, start + 1)
    return entities


@pytest.mark.asyncio
async def test_mask_is_reversible_and_upstream_sees_placeholders():
    body = {"messages": [
        {"role": "user", "content": f"Soy {_NAME}, mi mail es juan@acme.com"},
    ]}
    masked, ph_to_orig = await policy.mask_body(body, fake_analyze)

    text = masked["messages"][0]["content"]
    assert _NAME not in text and "juan@acme.com" not in text
    assert "[PERSON_0_" in text and "[EMAIL_ADDRESS_0_" in text
    # Round-trip completo
    assert policy.unmask_text(text, ph_to_orig) == f"Soy {_NAME}, mi mail es juan@acme.com"


@pytest.mark.asyncio
async def test_same_value_gets_same_placeholder_across_request():
    body = {"messages": [
        {"role": "user", "content": f"{_NAME} escribió"},
        {"role": "assistant", "content": "ok"},
        {"role": "user", "content": f"resumí lo de {_NAME}"},
    ]}
    masked, ph_to_orig = await policy.mask_body(body, fake_analyze)
    ph_first = masked["messages"][0]["content"].split(" escribió")[0]
    assert ph_first in masked["messages"][2]["content"]
    assert len([p for p in ph_to_orig if p.startswith("[PERSON_")]) == 1


@pytest.mark.asyncio
async def test_system_and_assistant_turns_are_not_masked():
    """Mismo alcance que el demo: solo turnos user (el system prompt no se toca)."""
    body = {
        "system": f"Sos el asistente de {_NAME}",
        "messages": [{"role": "assistant", "content": f"Hola {_NAME}"}],
    }
    masked, ph_to_orig = await policy.mask_body(body, fake_analyze)
    assert masked["system"] == f"Sos el asistente de {_NAME}"
    assert masked["messages"][0]["content"] == f"Hola {_NAME}"
    assert ph_to_orig == {}


@pytest.mark.asyncio
async def test_tool_result_blocks_are_masked():
    body = {"messages": [{
        "role": "user",
        "content": [
            {"type": "text", "text": f"mail: juan@acme.com"},
            {"type": "tool_result", "content": [
                {"type": "text", "text": f"cliente: {_NAME}"},
            ]},
        ],
    }]}
    masked, ph_to_orig = await policy.mask_body(body, fake_analyze)
    assert "juan@acme.com" not in json.dumps(masked)
    assert _NAME not in json.dumps(masked)
    assert len(ph_to_orig) == 2


@pytest.mark.asyncio
async def test_user_typed_placeholder_literal_does_not_collide():
    """El nonce por request evita que un literal tipeado por el usuario
    ("[PERSON_0]" o incluso un placeholder con otro nonce) colisione en el unmask."""
    literal = "[PERSON_0]"
    body = {"messages": [{"role": "user", "content": f"{literal} no es {_NAME}"}]}
    masked, ph_to_orig = await policy.mask_body(body, fake_analyze)

    text = masked["messages"][0]["content"]
    assert literal in text  # el literal del usuario queda intacto
    restored = policy.unmask_text(text, ph_to_orig)
    assert restored == f"{literal} no es {_NAME}"


def test_safe_split_holds_placeholder_fragment_but_not_code():
    # Fragmento que PUEDE ser un placeholder en curso → se retiene
    safe, carry = policy.safe_split("hola [PERSON_0_a")
    assert safe == "hola " and carry == "[PERSON_0_a"
    # '[' suelto de código/prosa → se emite ya (el streaming no se frena)
    safe, carry = policy.safe_split("arr[i")
    assert safe == "arr[i" and carry == ""
    safe, carry = policy.safe_split("nums[0")
    assert safe == "nums[0" and carry == ""
    # placeholder ya cerrado → nada que retener
    safe, carry = policy.safe_split("hola [PERSON_0_ab12] chau")
    assert carry == ""
    # fragmento absurdo de largo > MAX_CARRY no se retiene
    safe, carry = policy.safe_split("x[" + "A" * 60)
    assert carry == ""


def _stream_roundtrip(deltas, ph_to_orig, delta_type="text_delta"):
    """Alimenta deltas al StreamUnmasker y devuelve el texto reconstruido."""
    field = policy.DELTA_FIELDS[delta_type]
    um = policy.StreamUnmasker(ph_to_orig)
    out = []
    for chunk in deltas:
        events = um.feed({"type": "content_block_delta", "index": 0,
                          "delta": {"type": delta_type, field: chunk}})
        out.extend(e["delta"][field] for e in events if e.get("type") == "content_block_delta")
    events = um.feed({"type": "content_block_stop", "index": 0})
    out.extend(e["delta"][field] for e in events if e.get("type") == "content_block_delta")
    return "".join(out)


def test_stream_unmask_placeholder_split_across_chunks():
    ph_to_orig = {"[PERSON_0_ab12]": _NAME}
    # El placeholder viene partido en 3 chunks
    text = _stream_roundtrip(["Hola [PER", "SON_0_", "ab12], todo bien"], ph_to_orig)
    assert text == f"Hola {_NAME}, todo bien"


def test_stream_unmask_roundtrip_thinking_and_tool_use():
    ph_to_orig = {"[EMAIL_ADDRESS_0_ff00]": "juan@acme.com"}
    thinking = _stream_roundtrip(
        ["analizo [EMAIL_ADD", "RESS_0_ff00] a ver"], ph_to_orig, "thinking_delta")
    assert thinking == "analizo juan@acme.com a ver"

    tool_json = _stream_roundtrip(
        ['{"to": "[EMAIL', '_ADDRESS_0_ff00]"}'], ph_to_orig, "input_json_delta")
    assert tool_json == '{"to": "juan@acme.com"}'


def test_stream_truncated_flushes_carry_without_losing_text():
    """Stream cortado a mitad de un posible placeholder: flush() emite el carry —
    0 texto perdido (aunque quede sin des-enmascarar por incompleto)."""
    ph_to_orig = {"[PERSON_0_ab12]": _NAME}
    um = policy.StreamUnmasker(ph_to_orig)
    events = um.feed({"type": "content_block_delta", "index": 0,
                      "delta": {"type": "text_delta", "text": "hola [PERSON_0"}})
    emitted = "".join(e["delta"]["text"] for e in events)
    assert emitted == "hola "
    flushed = um.flush()
    assert flushed and flushed[0]["delta"]["text"] == "[PERSON_0"


def test_rewrite_sse_block_full_stream():
    """Nivel SSE (Estrategia B / passthrough OAuth): reescritura de bloques crudos,
    con extracción de usage al pasar."""
    ph_to_orig = {"[PERSON_0_ab12]": _NAME}
    blocks = [
        'event: message_start\ndata: {"type": "message_start", "message": {"usage": {"input_tokens": 12}}}',
        'event: content_block_start\ndata: {"type": "content_block_start", "index": 0}',
        'event: content_block_delta\ndata: {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Hola [PERSON"}}',
        'event: content_block_delta\ndata: {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "_0_ab12]!"}}',
        'event: content_block_stop\ndata: {"type": "content_block_stop", "index": 0}',
        'event: message_delta\ndata: {"type": "message_delta", "usage": {"output_tokens": 7}}',
    ]
    carry, field = "", None
    out_text, in_tok, out_tok = [], None, None
    for block in blocks:
        outs, carry, field, itk, otk = policy.rewrite_sse_block(block, carry, field, ph_to_orig)
        in_tok = itk if itk is not None else in_tok
        out_tok = otk if otk is not None else out_tok
        for ob in outs:
            for line in ob.split("\n"):
                if line.startswith("data:"):
                    data = json.loads(line[5:])
                    if data.get("type") == "content_block_delta":
                        out_text.append(data["delta"]["text"])
    assert "".join(out_text) == f"Hola {_NAME}!"
    assert in_tok == 12 and out_tok == 7
    assert carry == ""
