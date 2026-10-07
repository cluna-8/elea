"""S14 — excepción configurable del prompt de sistema y de las definiciones de herramientas (057 T111; research R34).

Por defecto APAGADA: todo se analiza (la caché de S17 lo vuelve barato). La instalación puede encender, por variable de
entorno, dos exenciones que suman posiciones OPACAS (ni se analizan ni se reescriben) a la tabla de E2:
`MASKING_EXEMPT_SYSTEM_PROMPT` (el `system`; en OpenAI, los turnos `system`/`developer`) y `MASKING_EXEMPT_TOOL_DEFINITIONS`
(`tools`). El informe lista los nombres exentos y el pedido no puede encenderlas."""
import copy
import json

import pytest

import s14_helpers as h
from s14_helpers import DNI_PUNTOS, policy
from extensions import sentinel_guardrail  # noqa: E402

gpolicy = sentinel_guardrail.policy
SISTEMA, TOOLS = "MASKING_EXEMPT_SYSTEM_PROMPT", "MASKING_EXEMPT_TOOL_DEFINITIONS"


class _Identidad:
    def __init__(self, **sentinel):
        self.metadata = {"sentinel": {"region": "latam_ar", **sentinel}}


@pytest.fixture(autouse=True)
def _entorno(monkeypatch):
    monkeypatch.delenv(SISTEMA, raising=False)
    monkeypatch.delenv(TOOLS, raising=False)

    async def _nada(*_a, **_k):
        return None

    monkeypatch.setattr(sentinel_guardrail, "_auditar_bloqueo", _nada)
    monkeypatch.setattr(sentinel_guardrail, "_marcar_nlp_degradado", _nada)
    monkeypatch.setattr(sentinel_guardrail, "_PRESIDIO_URL", None)


def _anthropic(system=None):
    return {"model": "claude-sonnet-4-5", "max_tokens": 8,
            "system": f"Atendés a un cliente con DNI {DNI_PUNTOS}." if system is None else system,
            "messages": [{"role": "user", "content": f"Mi DNI es {DNI_PUNTOS}"}],
            "tools": [{"name": "buscar", "description": f"Busca por DNI, ej. {DNI_PUNTOS}",
                       "input_schema": {"type": "object", "properties": {}}}]}


def _openai():
    return {"model": "gpt-x", "max_tokens": 8, "messages": [
        {"role": "system", "content": f"Sistema con DNI {DNI_PUNTOS}"},
        {"role": "developer", "content": f"Desarrollo con DNI {DNI_PUNTOS}"},
        {"role": "user", "content": f"Mi DNI es {DNI_PUNTOS}"},
        {"role": "assistant", "content": f"Anoto el DNI {DNI_PUNTOS}"}],
        "tools": [{"type": "function", "function": {"name": "f", "description": f"Ej. {DNI_PUNTOS}",
                                                    "parameters": {"type": "object", "properties": {}}}}]}


async def _hook(data, call_type="anthropic_messages", **identidad):
    home = sentinel_guardrail._metadata_home(data, call_type)
    gpolicy.mark_forced_masking(home)
    salida = await sentinel_guardrail.SentinelGuardrail().async_pre_call_hook(
        _Identidad(**identidad), None, data, call_type)
    return salida, data["litellm_metadata"]["masking_report"] if "litellm_metadata" in data else \
        sentinel_guardrail._metadata_home(data, call_type)["masking_report"]


def _txt(obj):
    return json.dumps(obj, ensure_ascii=False)


# ── apagada: todo se analiza ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_por_defecto_todo_se_analiza_y_el_informe_no_lleva_exenciones():
    assert gpolicy.optional_exemptions() == frozenset()
    salida, informe = await _hook(_anthropic())
    assert DNI_PUNTOS not in _txt({k: v for k, v in salida.items() if k not in ("litellm_metadata", "metadata")})
    assert "exempt" not in informe and informe["scope"] == "full"


@pytest.mark.asyncio
async def test_por_defecto_openai_enmascara_system_y_developer():
    salida, informe = await _hook(_openai(), call_type="completion")
    assert DNI_PUNTOS not in _txt(salida["messages"]) and DNI_PUNTOS not in _txt(salida["tools"])
    assert "exempt" not in informe


@pytest.mark.parametrize("valor", ["", "quizás", "0", "false", "no", "2"])
def test_valores_que_no_son_de_encendido_dejan_todo_apagado(monkeypatch, valor):
    monkeypatch.setenv(SISTEMA, valor)
    monkeypatch.setenv(TOOLS, valor)
    assert gpolicy.optional_exemptions() == frozenset()


@pytest.mark.parametrize("valor", ["1", "true", "TRUE", "yes", "on"])
def test_valores_de_encendido(monkeypatch, valor):
    monkeypatch.setenv(SISTEMA, valor)
    assert gpolicy.optional_exemptions() == frozenset({"system_prompt"})


def test_la_tabla_opcional_es_un_contrato_con_instantanea():
    assert policy.S14_EXEMPT_POSITIONS_OPTIONAL == {
        "system_prompt": {"anthropic": ("system",), "openai": ("messages.*.content@system", "messages.*.content@developer")},
        "tool_definitions": {"anthropic": ("tools",), "openai": ("tools", "functions")},
    }


def test_la_tabla_de_e2_no_cambia_con_las_exenciones_apagadas():
    assert set(policy.S14_EXEMPT_POSITIONS) == {"anthropic", "openai"}
    assert "system" not in policy.S14_EXEMPT_POSITIONS["anthropic"]["opaque"]
    assert "tools" not in policy.S14_EXEMPT_POSITIONS["anthropic"]["opaque"]


# ── encendidas ─────────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_system_exento_no_se_analiza_ni_se_reescribe_y_lo_demas_si(monkeypatch):
    monkeypatch.setenv(SISTEMA, "true")
    espia = []

    async def analizar(texto):
        espia.append(texto)
        return await policy.default_analyze(texto, region="latam_ar")

    original = _anthropic()
    cuerpo = copy.deepcopy(original)
    tally = policy.MaskingTally()
    out, _ = await policy.mask_body(cuerpo, analizar, policy.PlaceholderMap(), scope="full", fmt="anthropic",
                                    tally=tally, exempt=gpolicy.optional_exemptions())
    assert out["system"] == original["system"]
    assert not any("Atendés" in t for t in espia)
    assert DNI_PUNTOS not in _txt(out["messages"]) and DNI_PUNTOS not in _txt(out["tools"])


@pytest.mark.asyncio
async def test_system_en_bloques_exento(monkeypatch):
    monkeypatch.setenv(SISTEMA, "true")
    sistema = [{"type": "text", "text": f"Cliente {DNI_PUNTOS}", "cache_control": {"type": "ephemeral"}}]
    salida, informe = await _hook(_anthropic(system=copy.deepcopy(sistema)))
    assert salida["system"] == sistema
    assert informe["exempt"] == ["system_prompt"] and informe["unanalyzable"] == 0 and informe["scope"] == "full"


@pytest.mark.asyncio
async def test_herramientas_exentas_y_system_enmascarado(monkeypatch):
    monkeypatch.setenv(TOOLS, "true")
    original = _anthropic()
    salida, informe = await _hook(copy.deepcopy(original))
    assert salida["tools"] == original["tools"]
    assert DNI_PUNTOS not in _txt(salida["system"]) and DNI_PUNTOS not in _txt(salida["messages"])
    assert informe["exempt"] == ["tool_definitions"]


@pytest.mark.asyncio
async def test_las_dos_exenciones_y_el_informe_lista_solo_nombres(monkeypatch):
    monkeypatch.setenv(SISTEMA, "true")
    monkeypatch.setenv(TOOLS, "true")
    salida, informe = await _hook(_anthropic())
    assert informe["exempt"] == ["system_prompt", "tool_definitions"]
    assert DNI_PUNTOS not in _txt(salida["messages"])
    assert DNI_PUNTOS not in _txt(informe)


@pytest.mark.asyncio
async def test_openai_exime_los_turnos_system_y_developer_pero_no_los_demas(monkeypatch):
    monkeypatch.setenv(SISTEMA, "true")
    original = _openai()
    salida, informe = await _hook(copy.deepcopy(original), call_type="completion")
    assert salida["messages"][0] == original["messages"][0] and salida["messages"][1] == original["messages"][1]
    assert DNI_PUNTOS not in _txt(salida["messages"][2:]) and DNI_PUNTOS not in _txt(salida["tools"])
    assert informe["exempt"] == ["system_prompt"]


@pytest.mark.asyncio
async def test_openai_herramientas_exentas_tools(monkeypatch):
    monkeypatch.setenv(TOOLS, "true")
    original = _openai()
    salida, _ = await _hook(copy.deepcopy(original), call_type="completion")
    assert salida["tools"] == original["tools"] and DNI_PUNTOS not in _txt(salida["messages"])


@pytest.mark.asyncio
async def test_el_texto_exento_no_se_analiza_pero_los_secretos_y_la_ley_de_ia_siguen_mirandolo_todo(monkeypatch):
    monkeypatch.setenv(SISTEMA, "true")
    segmentos = policy.inspect_segments(_anthropic(), "anthropic", exempt=gpolicy.optional_exemptions())
    assert not any("Atendés" in t for t in segmentos) and any("Mi DNI" in t for t in segmentos)
    assert "Atendés" in " ".join(policy.inspect_segments(_anthropic(), "anthropic"))
    # un secreto en el `system` exento sigue bloqueando el pedido: la exención es del análisis de datos personales
    bloqueos = []

    async def _bloqueo(*_a, **kw):
        bloqueos.append(kw.get("compliance_status"))

    monkeypatch.setattr(sentinel_guardrail, "_auditar_bloqueo", _bloqueo)
    cuerpo = _anthropic(system="Usá la llave sk-abcdefghij1234567890 para llamar")
    respuesta, _ = await _hook(cuerpo)
    assert isinstance(respuesta, str) and bloqueos == ["blocked_secret"]


# ── el pedido no puede encenderlas ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_el_pedido_no_puede_encender_las_exenciones():
    cuerpo = _anthropic()
    cuerpo["exempt"] = ["system_prompt", "tool_definitions"]
    cuerpo["masking_exempt"] = "system_prompt,tool_definitions"
    cuerpo["metadata"] = {"masking_exempt": ["system_prompt"], "exempt": ["tool_definitions"]}
    cuerpo["litellm_metadata"] = {"masking_exempt": ["system_prompt"]}
    salida, informe = await _hook(cuerpo)
    assert DNI_PUNTOS not in _txt(salida["system"]) and DNI_PUNTOS not in _txt(salida["tools"])
    assert "exempt" not in informe
