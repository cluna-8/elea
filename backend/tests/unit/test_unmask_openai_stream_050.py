"""Spec 050 (12/13-sep-2026): restitución de placeholders en streaming de la API OpenAI.

Hueco real: `async_post_call_streaming_iterator_hook` solo reescribía frames SSE crudos (ruta
Anthropic); los chunks de `/v1/chat/completions` (objetos) pasaban tal cual y Presenton recibía
`[PERSON_0_66a5]` en vez de "OTC". Verificado en vivo con texto, JSON y tool calls.
"""
from types import SimpleNamespace as NS

import pytest

from extensions import sentinel_guardian_policy as policy

MAP = {"[PERSON_0_66a5]": "OTC", "[PERSON_1_66a5]": "Julián Pérez"}


def chunk(content=None, args=None, finish=None, as_dict=False):
    tc = None
    if args is not None:
        tc = [{"index": 0, "id": "c1", "type": "function", "function": {"name": "slide", "arguments": args}}]
    if as_dict:
        return {"choices": [{"index": 0, "finish_reason": finish, "delta": {"content": content, "tool_calls": tc}}]}
    tcs = None if tc is None else [NS(index=0, id="c1", type="function", function=NS(name="slide", arguments=args))]
    return NS(choices=[NS(index=0, finish_reason=finish, delta=NS(content=content, tool_calls=tcs))])


def feed(chunks, ph=MAP):
    carries, out, last = {}, [], None
    for c in chunks:
        last = c
        out.append(policy.unmask_openai_chunk(c, carries, ph))
    flushed = policy.flush_openai_carries(last, carries, ph)
    if flushed is not None:
        out.append(flushed)
    assert carries == {}
    return out


def text_of(chunks):
    return "".join((policy._get(policy._get(policy._get(c, "choices")[0], "delta"), "content") or "") for c in chunks)


def args_of(chunks):
    out = ""
    for c in chunks:
        for tc in policy._get(policy._get(policy._get(c, "choices")[0], "delta"), "tool_calls") or []:
            out += policy._get(policy._get(tc, "function"), "arguments") or ""
    return out


def test_placeholder_entero_en_un_chunk():
    out = feed([chunk("En marzo [PERSON_0_66a5] vendió"), chunk(None, finish="stop")])
    assert text_of(out) == "En marzo OTC vendió"


def test_placeholder_partido_entre_chunks():
    out = feed([chunk("En marzo [PERSON_"), chunk("0_66a5] vendió "), chunk("[PERSON_1_66a5]."), chunk(None, finish="stop")])
    assert text_of(out) == "En marzo OTC vendió Julián Pérez."


def test_placeholder_partido_justo_en_el_corchete():
    out = feed([chunk("Responsable: ["), chunk("PERSON_1_66a5]"), chunk("", finish="stop")])
    assert text_of(out) == "Responsable: Julián Pérez"


def test_tool_call_arguments_partidos():
    out = feed([chunk(args='{"titulo":"[PERS'), chunk(args='ON_0_66a5] vendió"}'), chunk(None, finish="tool_calls")])
    assert args_of(out) == '{"titulo":"OTC vendió"}'


def test_chunks_dict_tambien():
    out = feed([chunk("Hola [PERSON_1_66a5]", as_dict=True), chunk(None, finish="stop", as_dict=True)])
    assert text_of(out) == "Hola Julián Pérez"


def test_sin_placeholders_pasa_intacto():
    c = chunk("texto normal con [corchetes] y arr[i]")
    out = feed([c, chunk(None, finish="stop")])
    assert text_of(out) == "texto normal con [corchetes] y arr[i]"


def test_stream_truncado_sin_finish_flushea_el_carry():
    # No llega nunca el finish_reason: el carry pendiente se vuelca en un chunk extra.
    out = feed([chunk("Hola [PERSON_1_66a5"), ])
    assert text_of(out) == "Hola [PERSON_1_66a5"  # texto incompleto: se entrega tal cual, 0 pérdida
    assert len(out) == 2


def test_finish_con_carry_lo_vuelca_en_el_mismo_chunk():
    out = feed([chunk("Hola [PERSON_1"), chunk("_66a5]", finish="stop")])
    assert text_of(out) == "Hola Julián Pérez"
    assert len(out) == 2


@pytest.mark.asyncio
async def test_hook_completo_ruta_openai(monkeypatch):
    """El hook real: objetos → reescritos; bytes → ruta SSE de siempre (sin cambios)."""
    import sentinel_guardrail as sg
    g = sg.SentinelGuardrail.__new__(sg.SentinelGuardrail)

    async def stream():
        yield chunk("En marzo [PERSON_")
        yield chunk("0_66a5] vendió", finish="stop")
    data = {"metadata": {"pii_tokens": MAP}}
    out = [c async for c in g.async_post_call_streaming_iterator_hook(None, stream(), data)]
    assert text_of(out) == "En marzo OTC vendió"


MAP_RARO = {"[PERSON_0_ab12]": 'Pérez, "el Flaco"\nJulián'}


def test_json_mode_escapa_el_original_para_no_romper_el_json():
    carries = {}
    c = policy.unmask_openai_chunk(chunk('{"t":"[PERSON_0_ab12]"}', finish="stop"), carries, MAP_RARO, json_content=True)
    import json
    assert json.loads(policy._get(policy._get(c.choices[0], "delta"), "content")) == {"t": 'Pérez, "el Flaco"\nJulián'}


def test_tool_call_arguments_siempre_escapados():
    carries = {}
    c = policy.unmask_openai_chunk(chunk(args='{"t":"[PERSON_0_ab12]"}', finish="tool_calls"), carries, MAP_RARO)
    import json
    assert json.loads(c.choices[0].delta.tool_calls[0].function.arguments) == {"t": 'Pérez, "el Flaco"\nJulián'}


def test_texto_plano_no_se_escapa():
    carries = {}
    c = policy.unmask_openai_chunk(chunk("Hola [PERSON_0_ab12]", finish="stop"), carries, MAP_RARO)
    assert policy._get(policy._get(c.choices[0], "delta"), "content") == 'Hola Pérez, "el Flaco"\nJulián'


def test_request_wants_json():
    assert policy.request_wants_json({"response_format": {"type": "json_schema", "json_schema": {}}})
    assert policy.request_wants_json({"response_format": {"type": "json_object"}})
    assert not policy.request_wants_json({"response_format": {"type": "text"}})
    assert not policy.request_wants_json({})
