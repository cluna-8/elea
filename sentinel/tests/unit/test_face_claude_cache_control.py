"""057 T069/T075 (FR-044; T125/T130 de Sentinel): las marcas de caché (`cache_control`) de la herramienta se conservan hacia
un destino traducido que las declara (`capability_profile.cache_control`): en `system`, en los mensajes y en los bloques
(`tool_use`, `tool_result`), sin aplanar el `system` ni reordenar nada (la caché del proveedor exige los mismos bytes en cada
turno). Sin la capacidad se quitan como hasta ahora. La herramienta pone las marcas en `system` y mensajes; si la pasarela las
quita, la conversación se factura sin caché en cada turno, sin ningún error."""
import copy
import json

import pytest

from sentinel.redirect.faces import claude as face

MARCA = {"type": "ephemeral"}
CON = {"thinking": False, "cache_control": True, "mid_system_messages": True, "documents_pdf": True, "images": True}
SIN = {**CON, "cache_control": False}
SIN_SYSTEM_INTERMEDIO = {**CON, "mid_system_messages": False}


def _pedido():
    return {
        "model": "claude-sonnet-4-5", "max_tokens": 64,
        "system": [{"type": "text", "text": "S0", "cache_control": {"type": "ephemeral", "ttl": "1h"}},
                   {"type": "text", "text": "S1", "cache_control": dict(MARCA)}],
        "messages": [
            {"role": "user", "content": [{"type": "text", "text": "hola", "cache_control": dict(MARCA)}]},
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "toolu_1", "name": "Read", "input": {"p": "/a"}, "cache_control": dict(MARCA)}]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_1", "cache_control": dict(MARCA),
                                          "content": [{"type": "text", "text": "res", "cache_control": dict(MARCA)}]}]},
            {"role": "user", "content": "siguiente"},
        ],
        "tools": [{"name": "Read", "input_schema": {"type": "object"}, "cache_control": dict(MARCA)}],
    }


def _marcas(obj):
    return json.dumps(obj, sort_keys=True).count('"cache_control"')


def test_con_la_capacidad_todas_las_marcas_se_conservan_tal_cual():
    original = _pedido()
    out, removed = face.normalize_for_translated(copy.deepcopy(original), CON, max_output=64)
    assert _marcas(out) == _marcas(original) == 7
    assert out["system"] == original["system"]                    # el `system` en bloques no se aplana ni se toca
    assert isinstance(out["system"], list) and out["system"][0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}
    assert out["messages"] == original["messages"]
    assert out["tools"] == original["tools"]
    assert "cache_control" not in removed


def test_sin_la_capacidad_se_quitan_como_hoy():
    out, removed = face.normalize_for_translated(_pedido(), SIN, max_output=64)
    assert _marcas(out) == 0 and "cache_control" in removed


def test_un_system_en_cadena_no_se_convierte_ni_pierde_nada():
    p = _pedido()
    p["system"] = "instrucciones"
    out, _ = face.normalize_for_translated(p, CON, max_output=64)
    assert out["system"] == "instrucciones"


def test_aplanar_los_system_intermedios_conserva_las_marcas_de_todos_los_bloques():
    p = _pedido()
    p["messages"].insert(1, {"role": "system", "content": [{"type": "text", "text": "S2", "cache_control": dict(MARCA)}]})
    out, removed = face.normalize_for_translated(p, SIN_SYSTEM_INTERMEDIO, max_output=64)
    assert [b["text"] for b in out["system"]] == ["S0", "S1", "S2"]
    assert all("cache_control" in b for b in out["system"]) and "mid_system_messages" in removed


def test_la_nota_que_reemplaza_a_un_bloque_sin_soporte_conserva_la_marca():
    p = _pedido()
    p["messages"][0]["content"].append({"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                                                      "data": "AAAA"}, "cache_control": dict(MARCA)})
    out, _ = face.normalize_for_translated(p, {**CON, "images": False}, max_output=64)
    nota = out["messages"][0]["content"][-1]
    assert nota["type"] == "text" and nota["cache_control"] == MARCA
    assert "image" not in {b.get("type") for b in out["messages"][0]["content"]}


def test_el_resultado_es_determinista_el_mismo_pedido_da_los_mismos_bytes():
    a, _ = face.normalize_for_translated(_pedido(), CON, max_output=64)
    b, _ = face.normalize_for_translated(_pedido(), CON, max_output=64)
    assert json.dumps(a, sort_keys=False) == json.dumps(b, sort_keys=False)


@pytest.mark.parametrize("marca", [{"type": "ephemeral"}, {"type": "ephemeral", "ttl": "5m"}])
def test_las_formas_del_protocolo_pasan_sin_cambios(marca):
    p = _pedido()
    p["system"][0]["cache_control"] = dict(marca)
    out, _ = face.normalize_for_translated(p, CON, max_output=64)
    assert out["system"][0]["cache_control"] == marca
