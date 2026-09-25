"""`masking_report`: el resumen del paso de PII que el guardrail SIEMPRE deja en la
metadata interna del pedido (mismo home que `sentinel_compliance`).

Contrato: ``{"completed": bool, "degraded": bool, "detected": int, "masked": int}``

- ``completed``: el pre-call terminó y el pedido sigue hacia el proveedor con el paso de
  PII hecho (detección, y mask si la Connection lo tiene activo). False si se bloqueó o
  si la detección no pudo correr.
- ``degraded``: se usó el detector regex por el NLP caído (``nlp_fail_mode=degrade``).
- ``detected``: entidades PII encontradas; ``masked``: entidades reemplazadas por
  placeholder. Con redact desactivado ``masked == 0`` aunque ``detected > 0``.

Solo conteos — jamás valores (C1). Un valor sembrado por el cliente con la misma clave
se sobrescribe siempre.
"""
import sys
import types

import pytest


def _instalar_doble_litellm():
    if "litellm.integrations.custom_guardrail" in sys.modules:
        return

    class CustomGuardrail:
        def __init__(self, *args, **kwargs):
            pass

    litellm_mod = sys.modules.setdefault("litellm", types.ModuleType("litellm"))
    integrations = sys.modules.setdefault(
        "litellm.integrations", types.ModuleType("litellm.integrations"))
    modulo = types.ModuleType("litellm.integrations.custom_guardrail")
    modulo.CustomGuardrail = CustomGuardrail
    sys.modules["litellm.integrations.custom_guardrail"] = modulo
    litellm_mod.integrations = integrations
    integrations.custom_guardrail = modulo


_instalar_doble_litellm()

from extensions import sentinel_guardian_policy as policy  # noqa: E402
from extensions import sentinel_guardrail  # noqa: E402

DOS_MAILS = "escribí a ana@ejemplo.es y a luis@ejemplo.es, y de nuevo a ana@ejemplo.es"


@pytest.fixture(autouse=True)
def entorno(monkeypatch):
    monkeypatch.delenv("SENTINEL_AUDIT_FAIL", raising=False)
    monkeypatch.setattr(sentinel_guardrail, "_PRESIDIO_URL", None)

    async def _nada(*_a, **_k):
        return None
    monkeypatch.setattr(sentinel_guardrail, "_auditar_bloqueo", _nada)
    monkeypatch.setattr(sentinel_guardrail, "_marcar_nlp_degradado", _nada)


class _Identidad:
    def __init__(self, **sentinel):
        self.metadata = {"sentinel": sentinel}


def _body(prompt, **extra):
    return {"model": "m", "messages": [{"role": "user", "content": prompt}], **extra}


async def _hook(data, **sentinel):
    sentinel.setdefault("redact_enabled", True)
    await sentinel_guardrail.SentinelGuardrail().async_pre_call_hook(
        _Identidad(**sentinel), None, data, "acompletion")
    return data["metadata"]["masking_report"]


@pytest.mark.asyncio
async def test_mask_completo_cuenta_detectadas_y_enmascaradas():
    reporte = await _hook(_body(DOS_MAILS))
    assert reporte == {"completed": True, "degraded": False, "detected": 3, "masked": 3}


@pytest.mark.asyncio
async def test_sin_pii():
    reporte = await _hook(_body("resumime el acta"))
    assert reporte == {"completed": True, "degraded": False, "detected": 0, "masked": 0}


@pytest.mark.asyncio
async def test_redact_desactivado_detecta_pero_no_enmascara():
    data = _body(DOS_MAILS)
    reporte = await _hook(data, redact_enabled=False)
    assert reporte == {"completed": True, "degraded": False, "detected": 3, "masked": 0}
    # Sin cambio de comportamiento: el body sale intacto y sin mapa reversible.
    assert data["messages"][0]["content"] == DOS_MAILS
    assert "pii_tokens" not in data["metadata"]


@pytest.mark.asyncio
async def test_redact_desactivado_con_nlp_caido_no_bloquea(monkeypatch):
    async def _caido(*_a, **_k):
        raise policy.NlpUnavailableError("down")
    monkeypatch.setattr(sentinel_guardrail, "_PRESIDIO_URL", "http://nlp")
    monkeypatch.setattr(policy, "presidio_analyze", _caido)
    data = _body(DOS_MAILS)
    salida = await sentinel_guardrail.SentinelGuardrail().async_pre_call_hook(
        _Identidad(redact_enabled=False), None, data, "acompletion")
    assert salida is data, "redact desactivado nunca bloqueó por NLP caído"
    assert data["metadata"]["masking_report"] == {
        "completed": False, "degraded": False, "detected": 0, "masked": 0}


@pytest.mark.asyncio
async def test_degradado_a_regex(monkeypatch):
    async def _caido(*_a, **_k):
        raise policy.NlpUnavailableError("down")
    monkeypatch.setattr(sentinel_guardrail, "_PRESIDIO_URL", "http://nlp")
    monkeypatch.setattr(policy, "presidio_analyze", _caido)
    reporte = await _hook(_body(DOS_MAILS), nlp_fail_mode="degrade")
    assert reporte == {"completed": True, "degraded": True, "detected": 3, "masked": 3}


@pytest.mark.asyncio
async def test_bloqueo_por_tipo_deja_reporte_no_completado():
    data = _body(DOS_MAILS)
    salida = await sentinel_guardrail.SentinelGuardrail().async_pre_call_hook(
        _Identidad(redact_enabled=True,
                   entity_configs={"EMAIL_ADDRESS": "BLOCK"}),
        None, data, "acompletion")
    assert isinstance(salida, str)
    assert data["metadata"]["masking_report"] == {
        "completed": False, "degraded": False, "detected": 3, "masked": 0}


@pytest.mark.asyncio
async def test_bloqueo_ai_act_deja_reporte_no_completado():
    data = _body("necesito un social scoring de los socios")
    await sentinel_guardrail.SentinelGuardrail().async_pre_call_hook(
        _Identidad(redact_enabled=True), None, data, "acompletion")
    assert data["metadata"]["masking_report"]["completed"] is False


@pytest.mark.asyncio
async def test_valor_del_cliente_se_sobrescribe():
    data = _body("hola", metadata={"masking_report": {"completed": True, "detected": 99,
                                                      "masked": 99, "degraded": False}})
    reporte = await _hook(data)
    assert reporte == {"completed": True, "degraded": False, "detected": 0, "masked": 0}


@pytest.mark.asyncio
async def test_ruta_anthropic_usa_litellm_metadata():
    data = _body(DOS_MAILS)
    await sentinel_guardrail.SentinelGuardrail().async_pre_call_hook(
        _Identidad(redact_enabled=True), None, data, "anthropic_messages")
    assert data["litellm_metadata"]["masking_report"]["masked"] == 3
