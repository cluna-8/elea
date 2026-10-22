"""Detección metadata-only de las etiquetas que NO se pudieron restituir.

Antes de esto, un argumento de herramienta con la etiqueta alterada (el cliente ejecutaba la herramienta con el marcador en
vez del dato) era un fallo invisible: la fila de auditoría decía `passed` y el texto final salía bien. Ahora, DESPUÉS de
desenmascarar, se buscan los restos de etiquetas del pedido ACTIVO (tipo, índice cualquiera y NONCE del pedido, con o sin
corchetes) y, si quedan, se deja un resumen de TIPO y CANTIDAD —jamás texto de prompt, valores, tokens ni el nonce—:

- ``home["unmask_residue"] = [{"type", "count"}]``, un warning metadata-only y
  ``routing_decision.extensions.unmask = {"residual_count": N, "residual_types": "DNI,PERSON"}`` (la decisión de procedencia
  del motor; el plano interno ya persiste y sanea ``extensions``).
- No cambia el comportamiento: lo que se entrega al cliente es exactamente lo que se entregaba.
"""
import copy
import json
import logging

import pytest

import s14_helpers as h  # noqa: F401  (doble de litellm)
from extensions import sentinel_guardian_policy as policy  # noqa: E402
from extensions import sentinel_guardrail  # noqa: E402

NONCE = "0a81"
MAPA = {
    f"[PERSON_4_{NONCE}]": "Juan Ejemplo Prueba",
    f"[PERSON_1_{NONCE}]": "Ana Sintética",
    f"[DNI_0_{NONCE}]": "12345678",
    f"[EMAIL_ADDRESS_0_{NONCE}]": "prueba.sintetica@example.com",
}
VALORES = list(MAPA.values())


# ── La función pura ─────────────────────────────────────────────────────────────────────────────

def test_sin_restos_el_resumen_es_vacio():
    texto = policy.unmask_text("ficha de [PERSON_4_0a81], DNI_0_0a81 y <EMAIL_ADDRESS_0_0a81>", MAPA)
    assert policy.residual_marker_summary(texto, MAPA) == []
    assert policy.residual_marker_summary("", MAPA) == [] and policy.residual_marker_summary("x", {}) == []


def test_cuenta_por_tipo_los_restos_con_y_sin_corchetes():
    # Índices que el pedido no tiene (el modelo inventó/alteró el índice), corchete suelto, tipo en minúsculas…
    texto = ("a PERSON_9_0a81, b [PERSON_7_0a81], c [DNI_3_0_0a81], d email_address_5_0A81, e [PERSON_1_0a81, "
             "f PERSON_4_0a81]")
    assert policy.residual_marker_summary(texto, MAPA) == [
        {"type": "DNI", "count": 1}, {"type": "EMAIL_ADDRESS", "count": 1}, {"type": "PERSON", "count": 4}]


def test_solo_cuenta_las_del_pedido_activo():
    # Otro nonce, otro tipo (sin etiqueta activa de ese tipo) y prosa/código que se le parece: no son restos.
    texto = "PERSON_4_beef [DNI_0_beef] CUIL_0_0a81 get_user_9_0a82 cliente_id_0_1234 TIPO_n_xxxx [PERSON_0_a1b2]"
    assert policy.residual_marker_summary(texto, MAPA) == []


def test_el_resumen_no_trae_texto_ni_valores_ni_nonce():
    texto = "mira PERSON_9_0a81 y Juan Ejemplo Prueba y 12345678"
    resumen = policy.residual_marker_summary(texto, MAPA)
    assert resumen == [{"type": "PERSON", "count": 1}]
    serializado = json.dumps(resumen)
    assert NONCE not in serializado and not any(v in serializado for v in VALORES)
    assert all(set(item) == {"type", "count"} for item in resumen)


def test_estructuras_anidadas_valores_y_claves():
    estructura = {"a": ["x PERSON_9_0a81"], "DNI_8_0a81": {"b": 1}, "n": 2}
    assert policy.residual_marker_summary(estructura, MAPA) == [{"type": "DNI", "count": 1}, {"type": "PERSON", "count": 1}]


def test_texto_de_300k_sin_restos():
    grande = ("prosa y get_user_by_id_9_beef " * 12_000)[:300_000]
    assert policy.residual_marker_summary(grande, MAPA) == []


def test_extension_de_la_decision_de_ruteo_acota_los_tipos_y_conserva_lo_previo():
    resumen = [{"type": "DNI", "count": 2}, {"type": "PERSON", "count": 1}]
    home = {}
    policy.record_unmask_residue(home, resumen)
    assert home["unmask_residue"] == resumen
    assert policy.trusted_routing_decision(home) == {
        "extensions": {"unmask": {"residual_count": 3, "residual_types": "DNI,PERSON"}}}
    # Se suma a una decisión previa del motor (auto-router, redirección) sin pisarla.
    home = {}
    policy.mark_routing_decision(home, {"route": "r", "extensions": {"redirect": {"x": 1}}})
    policy.record_unmask_residue(home, resumen)
    assert policy.trusted_routing_decision(home) == {
        "route": "r", "extensions": {"redirect": {"x": 1}, "unmask": {"residual_count": 3, "residual_types": "DNI,PERSON"}}}
    # Lista de tipos acotada a lo que el plano interno acepta (≤ 128 caracteres por valor).
    muchos = [{"type": f"TIPO_LARGO_NUMERO_{i:03d}", "count": 1} for i in range(40)]
    home = {}
    policy.record_unmask_residue(home, muchos)
    valor = policy.trusted_routing_decision(home)["extensions"]["unmask"]
    assert len(valor["residual_types"]) <= 128 and valor["residual_count"] == 40
    # Sin restos, no hay nada que registrar.
    home = {}
    policy.record_unmask_residue(home, [])
    assert home == {}


# ── Streaming: el contador acumula lo EMITIDO, también con la cola partida entre deltas ──────────────

def test_contador_de_streaming_ve_el_resto_partido_entre_deltas():
    cont = policy.ResidueCounter(MAPA)
    for frag in ("ver PERS", "ON_9_", "0a8", "1 y fin"):
        cont.feed(frag)
    assert cont.summary() == [{"type": "PERSON", "count": 1}]
    # El mismo resto no se cuenta dos veces aunque la ventana lo conserve.
    cont.feed(" otra vez, sin nada")
    assert cont.summary() == [{"type": "PERSON", "count": 1}]
    cont.feed(" y DNI_5_0a81.")
    assert cont.summary() == [{"type": "DNI", "count": 1}, {"type": "PERSON", "count": 1}]


def test_contador_de_chunks_openai_y_de_frames_sse():
    cont = policy.ResidueCounter(MAPA)
    cont.feed_openai_chunk({"choices": [{"delta": {"content": "x PERSON_9_0a81", "tool_calls": None}}]})
    cont.feed_openai_chunk({"choices": [{"delta": {"content": None, "tool_calls": [
        {"index": 0, "function": {"name": "f", "arguments": '{"d": "DNI_6_0a81"}'}}]}}]})
    sse = ("event: content_block_delta\ndata: " + json.dumps(
        {"type": "content_block_delta", "index": 0, "delta": {"type": "input_json_delta",
                                                               "partial_json": '{"p": "[PERSON_8_0a81]"}'}}) + "\n\n")
    cont.feed_sse_block(sse)
    cont.feed_sse_block(sse.encode())
    assert cont.summary() == [{"type": "DNI", "count": 1}, {"type": "PERSON", "count": 3}]
    cont.feed_openai_chunk(object())            # formas raras: no rompen
    cont.feed_sse_block("event: ping\ndata: no-json")


# ── El hook: no streaming ─────────────────────────────────────────────────────────────────────

def _datos():
    return {"model": "m", "messages": [], "metadata": {"pii_tokens": dict(MAPA), "user_id": "u"}}


@pytest.mark.asyncio
async def test_hook_no_streaming_deja_el_resumen_y_no_cambia_la_respuesta(caplog):
    respuesta = {"choices": [{"message": {"content": "ficha de PERSON_1_0a81", "tool_calls": [
        {"id": "c1", "type": "function", "function": {"name": "f", "arguments": json.dumps(
            {"dni": "DNI_0_0a81", "otro": "PERSON_9_0a81", "otro2": "[DNI_7_0_0a81]"})}}]}}]}
    esperado = copy.deepcopy(respuesta)
    policy.unmask_response_payload(esperado, MAPA)
    datos = _datos()
    with caplog.at_level(logging.WARNING, logger="sentinel-guardrail"):
        salida = await sentinel_guardrail.SentinelGuardrail().async_post_call_success_hook(datos, None, respuesta)
    assert salida == esperado                              # idéntica a la de siempre
    home = datos["metadata"]
    assert home["unmask_residue"] == [{"type": "DNI", "count": 1}, {"type": "PERSON", "count": 1}]
    assert policy.trusted_routing_decision(home) == {
        "extensions": {"unmask": {"residual_count": 2, "residual_types": "DNI,PERSON"}}}
    avisos = [r.getMessage() for r in caplog.records if r.name == "sentinel-guardrail"]
    assert any("PERSON" in a and "2" in a for a in avisos)
    todo = "\n".join(avisos)
    assert NONCE not in todo and not any(v in todo for v in VALORES) and "ficha" not in todo


@pytest.mark.asyncio
async def test_hook_no_streaming_sin_restos_no_deja_nada():
    respuesta = {"choices": [{"message": {"content": "ficha de [PERSON_1_0a81] DNI_0_0a81", "tool_calls": None}}]}
    datos = _datos()
    salida = await sentinel_guardrail.SentinelGuardrail().async_post_call_success_hook(datos, None, respuesta)
    assert salida["choices"][0]["message"]["content"] == "ficha de Ana Sintética 12345678"
    assert "unmask_residue" not in datos["metadata"] and policy.trusted_routing_decision(datos["metadata"]) is None


@pytest.mark.asyncio
async def test_hook_no_streaming_anthropic_tool_use_y_home_litellm_metadata():
    respuesta = {"content": [{"type": "tool_use", "id": "t", "name": "buscar", "input": {"q": "PERSON_9_0a81 y DNI_0_0a81"}}]}
    datos = {"litellm_metadata": {"pii_tokens": dict(MAPA)}}
    salida = await sentinel_guardrail.SentinelGuardrail().async_post_call_success_hook(datos, None, respuesta)
    assert salida["content"][0]["input"] == {"q": "PERSON_9_0a81 y 12345678"}
    assert datos["litellm_metadata"]["unmask_residue"] == [{"type": "PERSON", "count": 1}]
    assert "metadata" not in datos                                      # no inventa el otro home


@pytest.mark.asyncio
async def test_hook_sin_etiquetas_en_el_pedido_no_hace_nada():
    respuesta = {"choices": [{"message": {"content": "PERSON_9_0a81"}}]}
    datos = {"metadata": {}}
    salida = await sentinel_guardrail.SentinelGuardrail().async_post_call_success_hook(datos, None, respuesta)
    assert salida["choices"][0]["message"]["content"] == "PERSON_9_0a81" and datos == {"metadata": {}}


# ── El hook: streaming ────────────────────────────────────────────────────────────────────────

def _chunk(content=None, args=None, finish=None):
    tc = None if args is None else [{"index": 0, "id": "c1", "type": "function",
                                     "function": {"name": "f", "arguments": args}}]
    return {"choices": [{"index": 0, "finish_reason": finish, "delta": {"content": content, "tool_calls": tc}}]}


async def _correr(items, datos):
    async def fuente():
        for it in items:
            yield it
    return [c async for c in sentinel_guardrail.SentinelGuardrail().async_post_call_streaming_iterator_hook(
        None, fuente(), datos)]


@pytest.mark.asyncio
async def test_hook_streaming_openai_deja_el_resumen_y_no_cambia_lo_entregado():
    items = lambda: [_chunk("ficha de PERS"), _chunk("ON_1_0a81 y PERSON_"), _chunk("9_0a81 fin"),
                     _chunk(args='{"dni": "DNI_0_0a81", "x": "[PERSON_8_0'), _chunk(args='a81]"}'), _chunk(None, finish="stop")]
    datos = _datos()
    vistos = await _correr(items(), datos)
    texto = "".join((c["choices"][0]["delta"].get("content") or "") for c in vistos)
    args = "".join(tc["function"]["arguments"] or "" for c in vistos for tc in (c["choices"][0]["delta"].get("tool_calls") or []))
    assert texto == "ficha de Ana Sintética y PERSON_9_0a81 fin"
    assert json.loads(args) == {"dni": "12345678", "x": "[PERSON_8_0a81]"}
    assert datos["metadata"]["unmask_residue"] == [{"type": "PERSON", "count": 2}]
    # Idéntico a lo que entrega el desenmascarado sin la detección.
    carries, ref = {}, []
    for it in items():
        ref.append(policy.unmask_openai_chunk(it, carries, MAPA))
    volcado = policy.flush_openai_carries(ref[-1], carries, MAPA)
    ref = ref + ([volcado] if volcado is not None else [])
    assert vistos == ref


@pytest.mark.asyncio
async def test_hook_streaming_sse_anthropic():
    def frame(texto, tipo="text_delta", campo="text"):
        return ("event: content_block_delta\ndata: " + json.dumps(
            {"type": "content_block_delta", "index": 0, "delta": {"type": tipo, campo: texto}}) + "\n\n").encode()
    items = [frame("ver DNI_0_0"), frame("a81 y PERSON_"), frame("9_0a81!"),
             b'event: message_stop\ndata: {"type":"message_stop"}\n\n']
    datos = {"litellm_metadata": {"pii_tokens": dict(MAPA)}}
    vistos = await _correr(items, datos)
    salida = b"".join(v if isinstance(v, bytes) else v.encode() for v in vistos).decode()
    assert "ver 12345678 y PERSON_9_0a81!" in "".join(
        json.loads(l[5:])["delta"]["text"] for l in salida.split("\n") if l.startswith("data:") and "text_delta" in l)
    assert datos["litellm_metadata"]["unmask_residue"] == [{"type": "PERSON", "count": 1}]


@pytest.mark.asyncio
async def test_hook_streaming_sin_restos_no_deja_nada_y_sin_etiquetas_pasa_igual():
    datos = _datos()
    await _correr([_chunk("hola [PERSON_1_0a81]"), _chunk(None, finish="stop")], datos)
    assert "unmask_residue" not in datos["metadata"] and policy.trusted_routing_decision(datos["metadata"]) is None
    sin = {"metadata": {}}
    items = [_chunk("PERSON_9_0a81")]
    assert await _correr(items, sin) == [_chunk("PERSON_9_0a81")] and sin == {"metadata": {}}
