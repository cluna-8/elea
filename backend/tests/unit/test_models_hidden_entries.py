"""Entradas ocultas del catálogo del motor (`model_info.plugin_owner`).

Un plugin puede declarar en el `config.yaml` del motor entradas propias (p. ej. un modelo
que sólo usa un servicio interno). Esas entradas son del plugin, no del admin: la consola
no las lista, no las ofrece al auto-router, y los escritores del catálogo no pueden
borrarlas, editarlas ni usarlas como respaldo. Sin entradas marcadas, todo queda idéntico.

Todos PUROS: sin Postgres ni motor; los endpoints se llaman como corrutinas.
"""
import asyncio

import pytest
import yaml
from fastapi import HTTPException

from src.api import chat

_OCULTA = {
    "model_name": "interno-plugin",
    "litellm_params": {"model": "ollama/qwen3:4b"},
    "model_info": {"plugin_owner": "un-plugin"},
}
_CATALOGO = {
    "model_list": [
        {"model_name": "local-qwen", "litellm_params": {"model": "ollama/qwen3:4b"}},
        {"model_name": "nube-gpt", "litellm_params": {"model": "openai/gpt-4o"}},
    ],
    "router_settings": {"disable_cooldowns": True},
}


def _escribir(tmp_path, monkeypatch, datos):
    destino = tmp_path / "config.yaml"
    destino.write_text(yaml.safe_dump(datos, default_flow_style=False), encoding="utf-8")
    monkeypatch.setattr(chat, "_get_config_path", lambda: str(destino))
    monkeypatch.setattr(chat, "_router_config_safe", lambda: {"enabled": False})
    return destino


def _con_oculta(primero=False):
    datos = yaml.safe_load(yaml.safe_dump(_CATALOGO))
    if primero:
        datos["model_list"].insert(0, dict(_OCULTA))
    else:
        datos["model_list"].append(dict(_OCULTA))
    return datos


def _leer(destino):
    return yaml.safe_load(destino.read_text(encoding="utf-8"))


def test_is_hidden_entry_exige_plugin_owner_no_vacio():
    assert chat._is_hidden_entry(_OCULTA)
    assert not chat._is_hidden_entry({"model_name": "x", "model_info": {"plugin_owner": ""}})
    assert not chat._is_hidden_entry({"model_name": "x", "model_info": {"max_output_tokens": 5}})
    assert not chat._is_hidden_entry({"model_name": "x"})
    assert not chat._is_hidden_entry("no-es-dict")


def test_listado_sin_ocultas_es_identico(tmp_path, monkeypatch):
    _escribir(tmp_path, monkeypatch, _CATALOGO)
    nombres = [m["model_name"] for m in asyncio.run(chat.list_available_models())]
    assert nombres == ["local-qwen", "nube-gpt"]


def test_listado_excluye_ocultas(tmp_path, monkeypatch):
    _escribir(tmp_path, monkeypatch, _con_oculta())
    nombres = [m["model_name"] for m in asyncio.run(chat.list_available_models())]
    assert nombres == ["local-qwen", "nube-gpt"]


def test_catalogo_del_router_excluye_ocultas():
    assert chat._catalog_model_names(_con_oculta()) == {"local-qwen", "nube-gpt"}
    assert chat._catalog_model_names(_CATALOGO) == {"local-qwen", "nube-gpt"}


def test_baja_de_oculta_es_404_y_no_toca_el_config(tmp_path, monkeypatch):
    destino = _escribir(tmp_path, monkeypatch, _con_oculta())
    antes = destino.read_text(encoding="utf-8")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(chat.delete_model("interno-plugin"))
    assert exc.value.status_code == 404
    assert destino.read_text(encoding="utf-8") == antes


def test_edicion_de_oculta_es_404_y_no_toca_el_config(tmp_path, monkeypatch):
    destino = _escribir(tmp_path, monkeypatch, _con_oculta())
    antes = destino.read_text(encoding="utf-8")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(chat.update_model_credential(
            "interno-plugin", chat.ModelCredentialSchema(litellm_params={"api_key": "sk-x"})))
    assert exc.value.status_code == 404
    assert destino.read_text(encoding="utf-8") == antes


def test_baja_de_visible_conserva_la_oculta(tmp_path, monkeypatch):
    destino = _escribir(tmp_path, monkeypatch, _con_oculta())
    asyncio.run(chat.delete_model("nube-gpt"))
    nombres = [m["model_name"] for m in _leer(destino)["model_list"]]
    assert nombres == ["local-qwen", "interno-plugin"]


def test_respaldo_automatico_no_cae_en_una_oculta(tmp_path, monkeypatch):
    # La oculta es local y está PRIMERA: sin el filtro sería el respaldo elegido.
    destino = _escribir(tmp_path, monkeypatch, _con_oculta(primero=True))
    r = asyncio.run(chat.register_model(chat.ModelCreateSchema(
        model_name="nube-nueva", provider="openai", model_id="gpt-4o-mini")))
    assert r["fallback_model"] == "local-qwen"
    assert {"nube-nueva": ["local-qwen"]} in _leer(destino)["router_settings"]["fallbacks"]


def test_respaldo_automatico_sin_locales_visibles_no_se_escribe(tmp_path, monkeypatch):
    datos = {"model_list": [dict(_OCULTA),
                            {"model_name": "nube-gpt", "litellm_params": {"model": "openai/gpt-4o"}}]}
    _escribir(tmp_path, monkeypatch, datos)
    r = asyncio.run(chat.register_model(chat.ModelCreateSchema(
        model_name="nube-nueva", provider="openai", model_id="gpt-4o-mini")))
    assert r["fallback_model"] is None


@pytest.mark.parametrize("origen,destino_fb", [
    ("nube-gpt", "interno-plugin"),   # oculta como destino
    ("interno-plugin", "local-qwen"),  # oculta como origen
])
def test_put_fallback_rechaza_ocultas(tmp_path, monkeypatch, origen, destino_fb):
    destino = _escribir(tmp_path, monkeypatch, _con_oculta())
    antes = destino.read_text(encoding="utf-8")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(chat.set_fallback(origen, chat.FallbackBody(fallback_model=destino_fb)))
    assert exc.value.status_code == 404
    assert destino.read_text(encoding="utf-8") == antes


def test_get_fallbacks_no_muestra_ocultas(tmp_path, monkeypatch):
    datos = _con_oculta()
    datos["router_settings"]["fallbacks"] = [
        {"nube-gpt": ["local-qwen"]}, {"interno-plugin": ["local-qwen"]}]
    _escribir(tmp_path, monkeypatch, datos)
    assert asyncio.run(chat.get_fallbacks()) == {"nube-gpt": "local-qwen"}
