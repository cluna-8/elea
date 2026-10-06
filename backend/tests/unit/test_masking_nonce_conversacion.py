"""S13 — marcadores estables por conversación (057 T067; FR-045; research R18; contracts/costuras-base.md §S13).

La caché del proveedor exige el MISMO historial enmascarado byte a byte en cada turno. Con `MASKING_NONCE_KEY` (secreto del
servidor) y la referencia de conversación `sentinel_conversation_ref` (que solo escribe la pasarela), el sufijo y el índice de
cada marcador se derivan por HMAC con esa clave; sin alguna de las dos, aleatorio como hoy. El marcador no se puede reproducir
sin la clave, no se comparte entre conversaciones, personas ni empresas y la restauración de la respuesta no cambia."""
import asyncio
import copy
import json
import re

import pytest

import s14_helpers as h  # noqa: F401  (doble de litellm)
from s14_helpers import DNI, DNI_PUNTOS
from extensions import sentinel_guardian_policy as policy  # noqa: E402
from extensions import sentinel_guardrail  # noqa: E402
from src.api import gateway_plugins as gp  # noqa: E402

gpolicy = sentinel_guardrail.policy
KEY = "k" * 48
OTRA = "z" * 48
REF = "conv-ref-1"
MARCADOR = re.compile(r"\[[A-Z_]+_(\d+)_([0-9a-f]{4})\]")


class _Identidad:
    def __init__(self, **sentinel):
        self.metadata = {"sentinel": {"region": "latam_ar", "tenant_id": "t1", "key_id": "k1", **sentinel}}


@pytest.fixture(autouse=True)
def _entorno(monkeypatch):
    monkeypatch.setenv("MASKING_NONCE_KEY", KEY)

    async def _nada(*_a, **_k):
        return None

    monkeypatch.setattr(sentinel_guardrail, "_auditar_bloqueo", _nada)
    monkeypatch.setattr(sentinel_guardrail, "_marcar_nlp_degradado", _nada)
    monkeypatch.setattr(sentinel_guardrail, "_PRESIDIO_URL", None)


def _historial(extra=()):
    base = [{"role": "user", "content": f"Mi DNI es {DNI_PUNTOS} y mi mail es ana@ejemplo.com"},
            {"role": "assistant", "content": "Anotado."}]
    return base + list(extra)


def _pedido(mensajes, ref=REF):
    data = {"model": "claude-sonnet-4-5", "max_tokens": 8, "messages": copy.deepcopy(mensajes)}
    if ref is not None:
        data["litellm_metadata"] = {"sentinel_conversation_ref": ref}
    return data


async def _hook(data, **identidad):
    salida = await sentinel_guardrail.SentinelGuardrail().async_pre_call_hook(
        _Identidad(**identidad), None, data, "anthropic_messages")
    return salida


def _mensajes(salida):
    return json.dumps(salida["messages"], ensure_ascii=False)


# ── 1. estable dentro de la conversación ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_dos_pedidos_de_la_misma_conversacion_dan_el_mismo_historial_enmascarado_byte_a_byte():
    a = await _hook(_pedido(_historial()))
    b = await _hook(_pedido(_historial()))
    assert _mensajes(a) == _mensajes(b)
    assert DNI_PUNTOS not in _mensajes(a) and MARCADOR.search(_mensajes(a))


@pytest.mark.asyncio
async def test_un_dato_nuevo_en_el_turno_siguiente_no_mueve_los_marcadores_del_historial():
    """El índice se deriva del valor, no del orden de aparición: lo ya enmascarado no cambia aunque aparezca otro dato antes."""
    t1 = await _hook(_pedido(_historial()))
    nuevo = [{"role": "user", "content": "Otro cliente: DNI 11.222.333"}]
    t2 = await _hook(_pedido(nuevo + _historial()))
    assert t2["messages"][1:] == t1["messages"]


@pytest.mark.asyncio
async def test_el_valor_igual_da_el_mismo_marcador_en_todo_el_pedido():
    s = await _hook(_pedido([{"role": "user", "content": f"DNI {DNI_PUNTOS} y de nuevo {DNI_PUNTOS}"}]))
    marcadores = MARCADOR.findall(_mensajes(s))
    assert len(marcadores) == 2 and marcadores[0] == marcadores[1]


# ── 2. no se comparte ──────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("cambio", ["ref", "tenant", "llave"])
async def test_otra_conversacion_empresa_o_llave_dan_otro_sufijo(cambio):
    base = await _hook(_pedido(_historial()))
    if cambio == "ref":
        otra = await _hook(_pedido(_historial(), ref="conv-ref-2"))
    elif cambio == "tenant":
        otra = await _hook(_pedido(_historial()), tenant_id="t2")
    else:
        otra = await _hook(_pedido(_historial()), key_id="k2")
    assert {s for _, s in MARCADOR.findall(_mensajes(base))}.isdisjoint({s for _, s in MARCADOR.findall(_mensajes(otra))})


@pytest.mark.asyncio
async def test_otra_clave_del_servidor_da_otro_sufijo(monkeypatch):
    base = await _hook(_pedido(_historial()))
    monkeypatch.setenv("MASKING_NONCE_KEY", OTRA)
    otra = await _hook(_pedido(_historial()))
    assert _mensajes(base) != _mensajes(otra)


def test_el_sufijo_no_se_puede_reproducir_sin_la_clave():
    a = policy.PlaceholderMap.for_conversation(KEY, tenant="t1", key_id="k1", ref=REF)
    b = policy.PlaceholderMap.for_conversation(OTRA, tenant="t1", key_id="k1", ref=REF)
    assert a.nonce != b.nonce and re.fullmatch(r"[0-9a-f]{4}", a.nonce)
    assert a.placeholder_for("x", "DNI") != b.placeholder_for("x", "DNI")


def test_los_marcadores_conservan_la_gramatica_que_restauran_los_streams():
    pm = policy.PlaceholderMap.for_conversation(KEY, tenant="t1", key_id="k1", ref=REF)
    ph = pm.placeholder_for("ana@ejemplo.com", "EMAIL_ADDRESS")
    assert policy.PLACEHOLDER_TOKEN_RE.fullmatch(ph) and policy.PH_TYPE_RE.match(ph) and len(ph) < policy.MAX_CARRY
    assert pm.placeholder_for("ana@ejemplo.com", "EMAIL_ADDRESS") == ph


def test_colision_de_indice_entre_dos_valores_se_resuelve_sin_pisar():
    pm = policy.PlaceholderMap.for_conversation(KEY, tenant="t1", key_id="k1", ref=REF)
    valores = [f"valor-{i}" for i in range(500)]
    marcadores = {pm.placeholder_for(v, "X") for v in valores}
    assert len(marcadores) == len(valores) and len(pm.ph_to_orig) == len(valores)


# ── 3. sin la referencia o sin la clave: aleatorio como hoy ───────────────────────────────────

@pytest.mark.asyncio
async def test_sin_referencia_el_sufijo_es_aleatorio():
    a = await _hook(_pedido(_historial(), ref=None))
    b = await _hook(_pedido(_historial(), ref=None))
    assert _mensajes(a) != _mensajes(b)


@pytest.mark.asyncio
async def test_sin_clave_o_con_clave_corta_el_sufijo_es_aleatorio(monkeypatch):
    for valor in (None, "", "corta"):
        if valor is None:
            monkeypatch.delenv("MASKING_NONCE_KEY", raising=False)
        else:
            monkeypatch.setenv("MASKING_NONCE_KEY", valor)
        a = await _hook(_pedido(_historial()))
        b = await _hook(_pedido(_historial()))
        assert _mensajes(a) != _mensajes(b), valor


@pytest.mark.asyncio
async def test_el_informe_dice_el_alcance_del_sufijo_sin_valores(monkeypatch):
    d1 = _pedido(_historial())
    await _hook(d1)
    assert d1["litellm_metadata"]["masking_report"]["nonce_scope"] == "conversation"
    d2 = _pedido(_historial(), ref=None)
    await _hook(d2)
    assert "nonce_scope" not in d2["litellm_metadata"]["masking_report"]      # sin S13 el informe es el de siempre
    assert REF not in json.dumps(d1["litellm_metadata"]["masking_report"])


@pytest.mark.asyncio
async def test_si_la_derivacion_falla_se_usa_el_aleatorio_y_el_pedido_sigue(monkeypatch):
    def _rota(*a, **k):
        raise RuntimeError("falla simulada")

    monkeypatch.setattr(gpolicy.PlaceholderMap, "for_conversation", classmethod(_rota))
    d = _pedido(_historial())
    salida = await _hook(d)
    assert DNI_PUNTOS not in _mensajes(salida)
    assert "nonce_scope" not in d["litellm_metadata"]["masking_report"]


# ── 4. el valor del cliente se descarta ────────────────────────────────────────────────────────

def test_la_pasarela_descarta_la_referencia_que_manda_el_cliente_antes_de_los_enganches():
    vistos = []

    class P:
        def pre_engine(self, ctx, body, headers):
            vistos.append(copy.deepcopy(body))
            return body, headers

    gp.clear_gateway_plugins()
    gp.register_gateway_plugin(P())
    try:
        cuerpo = {"model": "m", "messages": [], "sentinel_conversation_ref": "del-cliente",
                  "metadata": {"user_id": "u", "sentinel_conversation_ref": "del-cliente"},
                  "litellm_metadata": {"sentinel_conversation_ref": "del-cliente", "otra": 1}}
        asyncio.run(gp.run_pre_engine(object(), cuerpo, {}))
    finally:
        gp.clear_gateway_plugins()
    assert "sentinel_conversation_ref" not in json.dumps(vistos[0])
    assert vistos[0]["metadata"] == {"user_id": "u"} and vistos[0]["litellm_metadata"] == {"otra": 1}


# ── 5. la restauración no cambia ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_la_respuesta_vuelve_restaurada_no_stream_sse_y_chunks_openai():
    d = _pedido([{"role": "user", "content": f"DNI {DNI_PUNTOS} y mail ana@ejemplo.com"}])
    await _hook(d)
    ph = {p: o for p, o in sentinel_guardrail._pii_tokens_from(d).items()}
    p_dni = next(p for p, o in ph.items() if o == DNI_PUNTOS)
    p_mail = next(p for p, o in ph.items() if o == "ana@ejemplo.com")
    guard = sentinel_guardrail.SentinelGuardrail()
    # no stream
    out = await guard.async_post_call_success_hook(d, None, {"content": [{"type": "text", "text": f"Listo {p_dni} / {p_mail}"}]})
    assert out["content"][0]["text"] == f"Listo {DNI_PUNTOS} / ana@ejemplo.com"

    # SSE de Anthropic, con el marcador partido entre deltas
    async def _sse():
        corte = len(p_dni) // 2
        for frag in (f"Listo {p_dni[:corte]}", f"{p_dni[corte:]} y {p_mail}"):
            yield ("event: content_block_delta\ndata: " + json.dumps(
                {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": frag}}) + "\n\n").encode()
        yield b'event: message_stop\ndata: {"type":"message_stop"}\n\n'

    texto = "".join([b.decode() if isinstance(b, bytes) else b async for b in
                     guard.async_post_call_streaming_iterator_hook(None, _sse(), d)])
    assert DNI_PUNTOS in texto.replace('\\"', '"') and "ana@ejemplo.com" in texto and p_dni not in texto

    # chunks OpenAI
    async def _chunks():
        for frag in (f"Listo {p_dni[:3]}", f"{p_dni[3:]}", None):
            yield {"choices": [{"index": 0, "finish_reason": None if frag else "stop",
                                "delta": {"content": frag, "tool_calls": None}}]}

    vistos = [c async for c in guard.async_post_call_streaming_iterator_hook(None, _chunks(), d)]
    unido = "".join((c["choices"][0]["delta"].get("content") or "") for c in vistos)
    assert unido == f"Listo {DNI_PUNTOS}"
