"""Autodiscovery de routers de plugins (seam de extensión).

Contrato: `PLUGIN_PACKAGES` (módulos importables separados por coma); cada módulo expone
`get_routers() -> list[tuple[APIRouter, str]]` (router, prefix). Sin la env la app queda
EXACTAMENTE igual; un plugin roto hace fallar el arranque, no se monta a medias.
"""
import sys
import types

import pytest
from fastapi import APIRouter, FastAPI

from src import plugins


def _registrar_modulo(monkeypatch, nombre, **attrs):
    mod = types.ModuleType(nombre)
    for k, v in attrs.items():
        setattr(mod, k, v)
    monkeypatch.setitem(sys.modules, nombre, mod)
    return mod


def _router_de_prueba(path="/ping"):
    r = APIRouter()

    @r.get(path)
    def _ping():
        return {"ok": True}

    return r


def _paths(app):
    return sorted(getattr(r, "path", "") for r in app.routes)


# ── Sin la env: comportamiento idéntico ────────────────────────────────────────────
def test_sin_env_no_monta_nada(monkeypatch):
    monkeypatch.delenv("PLUGIN_PACKAGES", raising=False)
    app = FastAPI()
    antes = _paths(app)
    assert plugins.mount_plugin_routers(app) == 0
    assert _paths(app) == antes


@pytest.mark.parametrize("valor", ["", "  ", " , ,"])
def test_env_vacia_equivale_a_ausente(monkeypatch, valor):
    monkeypatch.setenv("PLUGIN_PACKAGES", valor)
    assert plugins.plugin_packages() == []
    assert plugins.load_plugin_routers() == []


def test_main_sin_env_no_trae_rutas_de_plugin(monkeypatch):
    monkeypatch.delenv("PLUGIN_PACKAGES", raising=False)
    import src.main as main

    assert not any("/plugin-test" in p for p in _paths(main.app))


# ── Con un plugin válido: las rutas aparecen ───────────────────────────────────────
def test_plugin_valido_monta_sus_rutas(monkeypatch):
    _registrar_modulo(
        monkeypatch, "plugin_de_prueba_ok",
        get_routers=lambda: [(_router_de_prueba("/ping"), "/api/v1/plugin-test")],
    )
    monkeypatch.setenv("PLUGIN_PACKAGES", "plugin_de_prueba_ok")
    app = FastAPI()
    assert plugins.mount_plugin_routers(app) == 1
    assert "/api/v1/plugin-test/ping" in _paths(app)
    assert "/api/v1/plugin-test/ping" in app.openapi()["paths"]


def test_varios_plugins_en_orden(monkeypatch):
    _registrar_modulo(monkeypatch, "plugin_a", get_routers=lambda: [(_router_de_prueba("/a"), "/pa")])
    _registrar_modulo(
        monkeypatch, "plugin_b",
        get_routers=lambda: [(_router_de_prueba("/b1"), "/pb"), (_router_de_prueba("/b2"), "")],
    )
    monkeypatch.setenv("PLUGIN_PACKAGES", " plugin_a , plugin_b ")
    assert plugins.plugin_packages() == ["plugin_a", "plugin_b"]
    app = FastAPI()
    assert plugins.mount_plugin_routers(app) == 3
    assert {"/pa/a", "/pb/b1", "/b2"} <= set(_paths(app))


# ── Plugin roto: error explícito, nada montado a medias ─────────────────────────────
def test_modulo_inexistente_falla_explicito(monkeypatch):
    monkeypatch.setenv("PLUGIN_PACKAGES", "modulo_que_no_existe_xyz")
    with pytest.raises(plugins.PluginLoadError, match="modulo_que_no_existe_xyz"):
        plugins.load_plugin_routers()


def test_modulo_sin_get_routers_falla(monkeypatch):
    _registrar_modulo(monkeypatch, "plugin_sin_contrato")
    monkeypatch.setenv("PLUGIN_PACKAGES", "plugin_sin_contrato")
    with pytest.raises(plugins.PluginLoadError, match="get_routers"):
        plugins.load_plugin_routers()


@pytest.mark.parametrize("devuelve", [
    None,
    [APIRouter()],                      # falta el prefix
    [("no-es-router", "/x")],
    [(APIRouter(), 123)],
])
def test_forma_invalida_falla(monkeypatch, devuelve):
    _registrar_modulo(monkeypatch, "plugin_forma_mala", get_routers=lambda: devuelve)
    monkeypatch.setenv("PLUGIN_PACKAGES", "plugin_forma_mala")
    with pytest.raises(plugins.PluginLoadError, match="plugin_forma_mala"):
        plugins.load_plugin_routers()


def test_get_routers_que_explota_falla(monkeypatch):
    def _revienta():
        raise ValueError("boom")

    _registrar_modulo(monkeypatch, "plugin_explota", get_routers=_revienta)
    monkeypatch.setenv("PLUGIN_PACKAGES", "plugin_explota")
    with pytest.raises(plugins.PluginLoadError, match="boom"):
        plugins.load_plugin_routers()


def test_un_plugin_roto_no_deja_montados_los_anteriores(monkeypatch):
    _registrar_modulo(monkeypatch, "plugin_bueno", get_routers=lambda: [(_router_de_prueba("/x"), "/bueno")])
    monkeypatch.setenv("PLUGIN_PACKAGES", "plugin_bueno,modulo_que_no_existe_xyz")
    app = FastAPI()
    antes = _paths(app)
    with pytest.raises(plugins.PluginLoadError):
        plugins.mount_plugin_routers(app)
    assert _paths(app) == antes
