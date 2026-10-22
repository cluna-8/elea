"""Punta a punta de los hooks reales del guardrail: el pedido se enmascara (y lleva la instrucción), el «modelo» devuelve la
etiqueta ALTERADA como lo hace un modelo chico dentro de un argumento de herramienta, y el cliente recibe el dato original.

Sintético: DNI de prueba, nada real. El «modelo» es un doble que altera la etiqueta del pedido (sin corchetes, con un entero
de más) tal como se midió en la verificación de clientes.
"""
import copy
import json
import re

import pytest

import s14_helpers as h  # noqa: F401  (doble de litellm)
from extensions import sentinel_guardian_policy as policy  # noqa: E402
from extensions import sentinel_guardrail  # noqa: E402

DNI = "30123456"
MAIL = "ana@ejemplo.es"
PROMPT = f"Cargá la ficha: DNI {DNI}, mail {MAIL}. Llamá a guardar_ficha."


@pytest.fixture(autouse=True)
def _entorno(monkeypatch):
    monkeypatch.delenv("SENTINEL_AUDIT_FAIL", raising=False)
    monkeypatch.delenv("MASKING_NONCE_KEY", raising=False)
    monkeypatch.setattr(sentinel_guardrail, "_PRESIDIO_URL", None)

    async def _nada(*_a, **_k):
        return None

    monkeypatch.setattr(sentinel_guardrail, "_auditar_bloqueo", _nada)
    monkeypatch.setattr(sentinel_guardrail, "_marcar_nlp_degradado", _nada)


class _Identidad:
    def __init__(self):
        self.metadata = {"sentinel": {"region": "latam_ar", "redact_enabled": True}}


def _alterar(etiqueta: str, modo: str) -> str:
    """Lo que escribe el modelo chico al copiar ``[TIPO_idx_nonce]`` dentro de un argumento."""
    m = re.fullmatch(r"\[(.+)_(\d+)_([0-9a-f]{4})\]", etiqueta)
    tipo, idx, nonce = m.groups()
    return {"sin_corchetes": f"{tipo}_{idx}_{nonce}", "indice_de_mas": f"[{tipo}_{idx}_0_{nonce}]",
            "angulares_minusculas": f"<{tipo.lower()}_{idx}_{nonce}>"}[modo]


async def _pre(call_type, **extra):
    data = {"model": "m", "messages": [{"role": "user", "content": PROMPT}], **extra}
    await sentinel_guardrail.SentinelGuardrail().async_pre_call_hook(_Identidad(), None, data, call_type)
    tokens = sentinel_guardrail._pii_tokens_from(data)
    return data, next(ph for ph, o in tokens.items() if o == DNI), next(ph for ph, o in tokens.items() if o == MAIL)


@pytest.mark.parametrize("modo", ["sin_corchetes", "indice_de_mas", "angulares_minusculas"])
@pytest.mark.asyncio
async def test_openai_no_streaming_tool_call_alterado_vuelve_con_el_dato(modo):
    data, p_dni, p_mail = await _pre("acompletion")
    assert data["messages"][0]["role"] == "system" and policy.MARKER_INSTRUCTION in data["messages"][0]["content"]
    assert DNI not in json.dumps(data["messages"]) and MAIL not in json.dumps(data["messages"])
    args = json.dumps({"dni": _alterar(p_dni, modo), "email": _alterar(p_mail, modo)})
    respuesta = {"choices": [{"message": {"content": None, "tool_calls": [
        {"id": "c", "type": "function", "function": {"name": "guardar_ficha", "arguments": args}}]}}]}
    salida = await sentinel_guardrail.SentinelGuardrail().async_post_call_success_hook(data, None, respuesta)
    assert json.loads(salida["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"]) == {"dni": DNI, "email": MAIL}
    assert "unmask_residue" not in data["metadata"]                    # nada quedó sin restituir


@pytest.mark.parametrize("modo", ["sin_corchetes", "indice_de_mas"])
@pytest.mark.asyncio
async def test_openai_streaming_un_caracter_por_delta(modo):
    data, p_dni, p_mail = await _pre("acompletion")
    args = json.dumps({"dni": _alterar(p_dni, modo), "email": _alterar(p_mail, modo)})

    async def fuente():
        for c in args:
            yield {"choices": [{"index": 0, "finish_reason": None, "delta": {"content": None, "tool_calls": [
                {"index": 0, "id": "c", "type": "function", "function": {"name": "guardar_ficha", "arguments": c}}]}}]}
        yield {"choices": [{"index": 0, "finish_reason": "tool_calls", "delta": {"content": None, "tool_calls": None}}]}

    vistos = [c async for c in sentinel_guardrail.SentinelGuardrail().async_post_call_streaming_iterator_hook(
        None, fuente(), data)]
    bruto = "".join(tc["function"]["arguments"] or "" for c in vistos
                    for tc in (c["choices"][0]["delta"].get("tool_calls") or []))
    assert json.loads(bruto) == {"dni": DNI, "email": MAIL}
    assert "unmask_residue" not in data["metadata"]


@pytest.mark.asyncio
async def test_anthropic_tool_use_alterado_vuelve_con_el_dato():
    data, p_dni, p_mail = await _pre("anthropic_messages", max_tokens=8)
    assert policy.MARKER_INSTRUCTION in data["system"]
    respuesta = {"content": [{"type": "tool_use", "id": "t", "name": "guardar_ficha", "input": {
        "dni": _alterar(p_dni, "sin_corchetes"), "sql": f"UPDATE c SET mail='{_alterar(p_mail, 'indice_de_mas')}'"}}]}
    salida = await sentinel_guardrail.SentinelGuardrail().async_post_call_success_hook(data, None, respuesta)
    assert salida["content"][0]["input"] == {"dni": DNI, "sql": f"UPDATE c SET mail='{MAIL}'"}
    assert "unmask_residue" not in data["litellm_metadata"]


@pytest.mark.asyncio
async def test_lo_que_no_se_puede_restituir_queda_visible_y_el_resto_se_entrega():
    data, p_dni, _ = await _pre("acompletion")
    nonce = p_dni[-5:-1]
    inventada = f"DNI_7_{nonce}"                       # un índice que el pedido nunca tuvo: no se adivina
    respuesta = {"choices": [{"message": {"content": f"{_alterar(p_dni, 'sin_corchetes')} y {inventada}"}}]}
    salida = await sentinel_guardrail.SentinelGuardrail().async_post_call_success_hook(data, None, respuesta)
    assert salida["choices"][0]["message"]["content"] == f"{DNI} y {inventada}"
    assert data["metadata"]["unmask_residue"] == [{"type": "DNI", "count": 1}]
