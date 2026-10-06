"""Enmascarado apagado + `masking_report` (S5b): el guardrail cuenta y no toca (057 T008, QA M11).

S5b (`1a454ed`) cambia un camino: antes, con `redact_enabled=false` el guardrail del motor no
llamaba a ningún analizador; ahora lo llama **una vez, solo para contar** lo detectado y dejarlo en
`masking_report` (el guard de la redirección lo lee). El cambio de latencia y de carga del
analizador para las empresas con el enmascarado apagado se anota para T084/T085. Lo que este
archivo fija es lo que NO puede cambiar con ese camino nuevo:

1. el analizador se llama exactamente una vez y solo para contar (`masked == 0`);
2. el pedido sale **igual** (mismos mensajes, sin mapa reversible, sin entidades enmascaradas) y
   la única diferencia en la metadata interna es el informe;
3. no se escribe ninguna fila de auditoría de bloqueo ni marca de degradación;
4. con el analizador caído **no bloquea** (ni con `nlp_fail_mode=block`, el default) y el informe
   queda `completed=False`, `detected=0`.
"""
import copy
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

TEXTO = "escribí a ana@ejemplo.es y a luis@ejemplo.es"


class _Identidad:
    def __init__(self, **sentinel):
        self.metadata = {"sentinel": sentinel}


@pytest.fixture
def rastros(monkeypatch):
    """Espía las dos escrituras que un camino de bloqueo o degradación dejaría, y el analizador."""
    visto = {"bloqueos": 0, "degradaciones": 0, "analizados": []}

    async def _bloqueo(*_a, **_k):
        visto["bloqueos"] += 1

    async def _degradacion(*_a, **_k):
        visto["degradaciones"] += 1

    monkeypatch.setattr(sentinel_guardrail, "_auditar_bloqueo", _bloqueo)
    monkeypatch.setattr(sentinel_guardrail, "_marcar_nlp_degradado", _degradacion)
    monkeypatch.setattr(sentinel_guardrail, "_PRESIDIO_URL", None)

    original = policy.default_analyze

    async def _contado(texto, *a, **k):
        visto["analizados"].append(texto)
        return await original(texto, *a, **k)

    monkeypatch.setattr(policy, "default_analyze", _contado)
    return visto


def _pedido():
    return {"model": "m", "messages": [{"role": "user", "content": TEXTO}]}


async def _correr(data, **sentinel):
    return await sentinel_guardrail.SentinelGuardrail().async_pre_call_hook(
        _Identidad(**sentinel), None, data, "acompletion")


@pytest.mark.asyncio
async def test_con_redact_apagado_el_analizador_corre_una_vez_y_solo_cuenta(rastros):
    data = _pedido()
    salida = await _correr(data, redact_enabled=False)
    assert salida is data
    assert len(rastros["analizados"]) == 1, "una sola pasada de detección, solo para contar"
    assert TEXTO in rastros["analizados"][0]
    assert data["metadata"]["masking_report"] == {
        "completed": True, "degraded": False, "detected": 2, "masked": 0, "scope": "user", "unanalyzable": 0, "unanalyzable_kinds": []}


@pytest.mark.asyncio
async def test_con_redact_apagado_el_pedido_sale_igual_y_sin_filas(rastros):
    original = _pedido()
    data = copy.deepcopy(original)
    await _correr(data, redact_enabled=False)
    metadata = data.pop("metadata")
    assert data == original, "mensajes y campos del pedido idénticos: solo se suma metadata"
    assert set(metadata) == {"masking_report", "sentinel_compliance"}, (
        "la única novedad en la metadata interna es el informe; sin mapa reversible ni "
        "entidades enmascaradas")
    assert rastros["bloqueos"] == 0 and rastros["degradaciones"] == 0, (
        "contar no escribe filas de bloqueo ni marcas de degradación")


@pytest.mark.asyncio
@pytest.mark.parametrize("modo", ["block", "degrade", None])
async def test_con_redact_apagado_y_analizador_caido_no_bloquea(rastros, monkeypatch, modo):
    async def _caido(*_a, **_k):
        raise policy.NlpUnavailableError("down")

    monkeypatch.setattr(sentinel_guardrail, "_PRESIDIO_URL", "http://nlp")
    monkeypatch.setattr(policy, "presidio_analyze", _caido)
    original = _pedido()
    data = copy.deepcopy(original)
    extra = {} if modo is None else {"nlp_fail_mode": modo}
    salida = await _correr(data, redact_enabled=False, **extra)
    assert salida is data, "con el enmascarado apagado un analizador caído jamás bloquea"
    assert data["metadata"]["masking_report"] == {
        "completed": False, "degraded": False, "detected": 0, "masked": 0, "scope": "user", "unanalyzable": 0, "unanalyzable_kinds": []}
    assert data["messages"] == original["messages"]
    assert rastros["bloqueos"] == 0 and rastros["degradaciones"] == 0
