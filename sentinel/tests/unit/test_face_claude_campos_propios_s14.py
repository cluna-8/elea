"""057 R42: los campos que la cara Claude ESCRIBE en el cuerpo hacia un destino traducido son del protocolo de la pasarela y el
enmascarado de alcance completo del motor (S14) tiene que tenerlos en su tabla de posiciones.

Hallazgo del 2026-10-07 (Claude Desktop, sonnet y opus, hasta un «hola» nuevo): con `thinking` u `output_config.effort` el normalizador
escribe `reasoning_effort` en el primer nivel (`faces/claude.py`); la base lo trataba como campo desconocido, analizaba su NOMBRE
con el NER real (LOCATION 0,85), lo contaba como `structural_entity` y el guard bloqueaba el pedido con `masking_required`. Haiku no
manda `thinking` ni esfuerzo, por eso pasaba. Este test fija el acople: todo campo que la cara agrega tiene posición estructural en la
tabla de la base y su valor está dentro del vocabulario cerrado (la base lo ve como una posición del protocolo, no como un campo suelto).
"""
import itertools

import pytest

from extensions import sentinel_guardian_policy as policy
from sentinel.redirect.faces import claude as face
from sentinel.tests import corpus_claude as corpus

PROFILE_RAZONA = {"thinking": True, "cache_control": True, "images": True, "documents_pdf": True, "mid_system_messages": True}
THINKING = [None, {"type": "adaptive"}, {"type": "adaptive", "display": "omitted"}, {"type": "enabled", "budget_tokens": 4096}]
ESFUERZOS = [None, "low", "medium", "high", "xhigh", "max"]


def _salida(thinking, esfuerzo):
    cuerpo = dict(corpus.load("claude_code_messages_beta")["body"])
    cuerpo.pop("thinking", None)
    cuerpo.pop("output_config", None)
    if thinking:
        cuerpo["thinking"] = thinking
    if esfuerzo:
        cuerpo["output_config"] = {"effort": esfuerzo}
    salida, _ = face.normalize_for_translated(cuerpo, PROFILE_RAZONA, max_output=8192)
    return cuerpo, salida


@pytest.mark.parametrize("thinking,esfuerzo", list(itertools.product(THINKING, ESFUERZOS)))
def test_todo_campo_que_la_cara_agrega_tiene_posicion_estructural_en_la_base(thinking, esfuerzo):
    entrada, salida = _salida(thinking, esfuerzo)
    agregados = set(salida) - set(entrada)
    for campo in agregados:
        assert policy._class_of("anthropic", campo) == "struct", f"{campo}: la cara lo escribe y la base no lo conoce (S14)"
    if "reasoning_effort" in salida:
        modo = policy._scan_mode("anthropic", "reasoning_effort")
        assert modo is not None and modo[0] == "closed"
        assert policy._in_vocabulary(modo[1], salida["reasoning_effort"]), "el valor que escribe la cara cae en el vocabulario cerrado"


def test_el_pedido_de_sonnet_con_esfuerzo_escribe_reasoning_effort():
    """Ancla del escenario real: sin `thinking` ni esfuerzo (haiku) la cara no agrega nada; con ellos agrega el campo."""
    entrada, sin = _salida(None, None)
    assert set(sin) - set(entrada) == set()
    entrada, con = _salida({"type": "adaptive"}, "medium")
    assert set(con) - set(entrada) == {"reasoning_effort"} and con["reasoning_effort"] == "medium"
