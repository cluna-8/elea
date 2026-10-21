"""Prevención del desenmascarado fallido: la instrucción ESTÁTICA que le pide al modelo copiar los marcadores tal cual.

Medido (informe 42 §1.2, sintético): un modelo chico sin la instrucción devolvió los datos originales 0 de 50 veces (copia el
marcador SIN corchetes dentro de los argumentos de una herramienta); con la instrucción en el mensaje de SISTEMA, 25 de 25
(al final del mensaje de usuario, 15 de 25: gana el sistema). Contrato de la pieza:

- Solo cuando el pedido TIENE al menos una etiqueta (``bool(ph_to_orig)``): un pedido sin datos protegidos sale idéntico.
- Texto FIJO: sin el nonce del pedido ni datos del usuario (la caché de prefijo del proveedor no se invalida entre turnos).
- Idempotente: si el sistema ya la lleva, no se agrega otra vez.
- Todas las formas de pedido del hook: chat/completions (``system`` | ``developer``; sin ninguno, un mensaje de sistema al
  principio) y mensajes tipo Anthropic (``system`` como cadena, como lista de bloques o ausente).
"""
import copy
import re

import pytest

import s14_helpers as h  # noqa: F401  (doble de litellm)
from extensions import sentinel_guardian_policy as policy  # noqa: E402
from extensions import sentinel_guardrail  # noqa: E402

DNI = "30123456"
MAIL = "ana@ejemplo.es"
CON_PII = f"Cargá la ficha: DNI {DNI}, mail {MAIL}."
SIN_PII = "Resumime el acta de la reunión de ayer."
NONCE_DE_MARCADOR = re.compile(r"_([0-9a-f]{4})\]$")


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
    def __init__(self, **sentinel):
        self.metadata = {"sentinel": {"region": "latam_ar", "redact_enabled": True, **sentinel}}


async def _openai(mensajes, **extra):
    data = {"model": "m", "messages": copy.deepcopy(mensajes), **extra}
    await sentinel_guardrail.SentinelGuardrail().async_pre_call_hook(_Identidad(), None, data, "acompletion")
    return data


async def _anthropic(mensajes, **extra):
    data = {"model": "m", "max_tokens": 8, "messages": copy.deepcopy(mensajes), **extra}
    await sentinel_guardrail.SentinelGuardrail().async_pre_call_hook(
        _Identidad(), None, data, "anthropic_messages")
    return data


def _veces(valor) -> int:
    """Cuántas veces aparece la instrucción en todo el valor (cadena, lista de bloques o mensajes)."""
    return repr(valor).count(policy.MARKER_INSTRUCTION)


# ── El texto ─────────────────────────────────────────────────────────────────────────

def test_el_texto_es_estatico_y_no_lleva_datos_ni_nonce_ni_marca():
    t = policy.MARKER_INSTRUCTION
    assert "[TIPO_n_xxxx]" in t and "[" in t and "]" in t
    assert "corchetes" in t and "carácter por carácter" in t
    # Ejemplos fijos y sintéticos; ningún marcador real (con índice y nonce de un pedido) ni datos del usuario.
    assert "[PERSON_0_a1b2]" in t and "[DNI_0_c3d4]" in t
    for prohibido in ("litellm", "sentinel", "eleia", "elea", "guardian", "presidio", "openai", "anthropic"):
        assert prohibido not in t.lower()


# ── chat/completions ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_openai_agrega_la_instruccion_al_mensaje_de_sistema_existente():
    data = await _openai([{"role": "system", "content": "Sos un asistente."},
                          {"role": "user", "content": CON_PII}])
    sistema = data["messages"][0]
    assert sistema["role"] == "system"
    assert sistema["content"] == "Sos un asistente.\n\n" + policy.MARKER_INSTRUCTION
    assert len(data["messages"]) == 2 and _veces(data) == 1


@pytest.mark.asyncio
async def test_openai_developer_tambien_cuenta_como_sistema():
    data = await _openai([{"role": "developer", "content": "Reglas."},
                          {"role": "user", "content": CON_PII}])
    assert data["messages"][0]["role"] == "developer"
    assert data["messages"][0]["content"].endswith(policy.MARKER_INSTRUCTION)
    assert len(data["messages"]) == 2 and _veces(data) == 1


@pytest.mark.asyncio
async def test_openai_sin_sistema_agrega_uno_al_principio():
    data = await _openai([{"role": "user", "content": CON_PII}])
    assert data["messages"][0] == {"role": "system", "content": policy.MARKER_INSTRUCTION}
    assert data["messages"][1]["role"] == "user" and len(data["messages"]) == 2


@pytest.mark.asyncio
async def test_openai_sistema_como_lista_de_partes_suma_una_parte_al_final():
    partes = [{"type": "text", "text": "Sos un asistente.", "cache_control": {"type": "ephemeral"}}]
    data = await _openai([{"role": "system", "content": partes}, {"role": "user", "content": CON_PII}])
    contenido = data["messages"][0]["content"]
    assert contenido[0] == partes[0]                         # la parte del cliente (y su marca de caché) intacta
    assert contenido[1] == {"type": "text", "text": policy.MARKER_INSTRUCTION}
    assert len(contenido) == 2


@pytest.mark.asyncio
async def test_openai_sin_pii_el_pedido_sale_identico():
    mensajes = [{"role": "system", "content": "Sos un asistente."}, {"role": "user", "content": SIN_PII}]
    data = await _openai(mensajes)
    assert data["messages"] == mensajes and _veces(data) == 0
    sin_sistema = await _openai([{"role": "user", "content": SIN_PII}])
    assert sin_sistema["messages"] == [{"role": "user", "content": SIN_PII}]


@pytest.mark.asyncio
async def test_openai_es_idempotente_si_el_sistema_ya_la_lleva():
    ya = "Sos un asistente.\n\n" + policy.MARKER_INSTRUCTION
    data = await _openai([{"role": "system", "content": ya}, {"role": "user", "content": CON_PII}])
    assert data["messages"][0]["content"] == ya and _veces(data) == 1
    # Aplicada dos veces sobre el mismo cuerpo: una sola.
    assert policy.inject_marker_instruction(data, "openai") is False
    assert _veces(data) == 1


@pytest.mark.asyncio
async def test_openai_varios_turnos_una_sola_instruccion_y_el_mismo_texto():
    historial = [{"role": "system", "content": "Sos un asistente."},
                 {"role": "user", "content": CON_PII},
                 {"role": "assistant", "content": "Listo, la ficha quedó cargada."},
                 {"role": "user", "content": f"Ahora agregá el mail {MAIL} a la lista."}]
    data = await _openai(historial)
    assert _veces(data) == 1
    assert [m["role"] for m in data["messages"]] == ["system", "user", "assistant", "user"]


@pytest.mark.asyncio
async def test_openai_el_mensaje_agregado_es_el_mismo_byte_a_byte_entre_pedidos():
    a = await _openai([{"role": "user", "content": CON_PII}])
    b = await _openai([{"role": "user", "content": CON_PII}])
    # Cada pedido tiene su propio nonce aleatorio (los usuarios sí cambian), pero el sistema agregado es idéntico:
    # la caché de prefijo del proveedor no se invalida entre turnos.
    assert a["messages"][0] == b["messages"][0] == {"role": "system", "content": policy.MARKER_INSTRUCTION}
    # Ni el nonce ni el valor de ESTE pedido aparecen en el texto agregado.
    for pedido in (a, b):
        for ph, original in pedido["metadata"]["pii_tokens"].items():
            nonce = NONCE_DE_MARCADOR.search(ph).group(1)
            if nonce not in ("a1b2", "c3d4"):             # (un nonce aleatorio puede coincidir con el ejemplo fijo)
                assert nonce not in pedido["messages"][0]["content"]
            assert original not in pedido["messages"][0]["content"]


# ── Mensajes tipo Anthropic ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_anthropic_system_cadena():
    data = await _anthropic([{"role": "user", "content": CON_PII}], system="Sos un asistente.")
    assert data["system"] == "Sos un asistente.\n\n" + policy.MARKER_INSTRUCTION
    assert _veces(data) == 1 and data["messages"][0]["role"] == "user"


@pytest.mark.asyncio
async def test_anthropic_system_lista_de_bloques_suma_un_bloque_al_final():
    bloques = [{"type": "text", "text": "Sos un asistente.", "cache_control": {"type": "ephemeral"}}]
    data = await _anthropic([{"role": "user", "content": CON_PII}], system=copy.deepcopy(bloques))
    assert data["system"][0] == bloques[0]
    assert data["system"][1] == {"type": "text", "text": policy.MARKER_INSTRUCTION}
    assert len(data["system"]) == 2


@pytest.mark.asyncio
async def test_anthropic_sin_system_lo_crea_como_cadena():
    data = await _anthropic([{"role": "user", "content": CON_PII}])
    assert data["system"] == policy.MARKER_INSTRUCTION
    assert [m["role"] for m in data["messages"]] == ["user"]      # nunca un mensaje `system` dentro de `messages`


@pytest.mark.asyncio
async def test_anthropic_sin_pii_sale_identico_y_sin_clave_system():
    mensajes = [{"role": "user", "content": SIN_PII}]
    data = await _anthropic(mensajes)
    assert "system" not in data and data["messages"] == mensajes
    con_sistema = await _anthropic(mensajes, system="Sos un asistente.")
    assert con_sistema["system"] == "Sos un asistente."


@pytest.mark.asyncio
async def test_anthropic_idempotente():
    ya = [{"type": "text", "text": "Hola."}, {"type": "text", "text": policy.MARKER_INSTRUCTION}]
    data = await _anthropic([{"role": "user", "content": CON_PII}], system=copy.deepcopy(ya))
    assert data["system"] == ya and _veces(data) == 1
    assert policy.inject_marker_instruction(data, "anthropic") is False


# ── La función pura ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("cuerpo,fmt", [({"messages": "no es lista"}, "openai"), ({}, "openai"),
                                        ({"system": 5}, "anthropic")])
def test_funcion_pura_formas_raras_no_rompen_ni_cambian_nada(cuerpo, fmt):
    original = copy.deepcopy(cuerpo)
    assert policy.inject_marker_instruction(cuerpo, fmt) is False
    assert cuerpo == original


# ── Con la exención del system (S14) y el interruptor de apagado ─────────────────────

async def _forzado(data, call_type):
    home = sentinel_guardrail._metadata_home(data, call_type)
    policy.mark_forced_masking(home)
    await sentinel_guardrail.SentinelGuardrail().async_pre_call_hook(_Identidad(), None, data, call_type)
    return data


@pytest.mark.asyncio
async def test_con_la_exencion_del_system_el_texto_del_cliente_sale_igual_y_la_instruccion_va_aparte(monkeypatch):
    monkeypatch.setenv("MASKING_EXEMPT_SYSTEM_PROMPT", "true")
    cliente = f"Atendés al cliente con DNI {DNI}."
    data = await _forzado({"model": "m", "max_tokens": 8, "system": cliente,
                           "messages": [{"role": "user", "content": CON_PII}]}, "anthropic_messages")
    assert data["system"].startswith(cliente + "\n\n") and data["system"].endswith(policy.MARKER_INSTRUCTION)
    assert data["system"][:len(cliente)] == cliente                     # el texto del cliente, ni una letra distinta
    bloques = [{"type": "text", "text": cliente, "cache_control": {"type": "ephemeral"}}]
    data = await _forzado({"model": "m", "max_tokens": 8, "system": copy.deepcopy(bloques),
                           "messages": [{"role": "user", "content": CON_PII}]}, "anthropic_messages")
    assert data["system"] == bloques + [{"type": "text", "text": policy.MARKER_INSTRUCTION}]
    data = await _forzado({"model": "m", "messages": [{"role": "system", "content": cliente},
                                                       {"role": "user", "content": CON_PII}]}, "completion")
    assert data["messages"][0]["content"] == cliente + "\n\n" + policy.MARKER_INSTRUCTION


@pytest.mark.parametrize("valor", ["0", "false", "FALSE", "off", "no", " Off "])
@pytest.mark.asyncio
async def test_interruptor_de_apagado_deja_el_pedido_como_antes(monkeypatch, valor):
    monkeypatch.setenv("SENTINEL_PLACEHOLDER_HINT", valor)
    assert policy.placeholder_hint_enabled() is False
    data = await _openai([{"role": "system", "content": "Sos un asistente."}, {"role": "user", "content": CON_PII}])
    assert data["messages"][0]["content"] == "Sos un asistente." and _veces(data) == 0
    data = await _anthropic([{"role": "user", "content": CON_PII}])
    assert "system" not in data and _veces(data) == 0


@pytest.mark.parametrize("valor", [None, "", "1", "true", "on", "cualquier cosa"])
def test_por_defecto_y_con_cualquier_otro_valor_esta_encendida(monkeypatch, valor):
    if valor is None:
        monkeypatch.delenv("SENTINEL_PLACEHOLDER_HINT", raising=False)
    else:
        monkeypatch.setenv("SENTINEL_PLACEHOLDER_HINT", valor)
    assert policy.placeholder_hint_enabled() is True
