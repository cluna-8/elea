"""Resolución de la URL pública de la pasarela para los kits (US5; T110).

La base de los kits sale, en orden, de (1) la variable ``REDIRECT_GATEWAY_URL`` del
entorno, (2) los encabezados del pedido del panel (``X-Forwarded-Proto``/``X-Forwarded-Host``
o ``Host``), y (3) nunca un hostname interno de compose (``backend``, ``engine``…):
si no puede resolverla, pone el marcador ``kits.URL_PLACEHOLDER`` y el segundo elemento
del par a ``False`` para que el panel lo avise.
"""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))
pytest.importorskip("src.auth.rbac", reason="requiere el venv del backend")

from sentinel.redirect import kits  # noqa: E402
from sentinel.redirect.api import us5  # noqa: E402


def _req(headers=None, scheme="http", netloc="testserver"):
    return SimpleNamespace(
        headers=headers or {},
        url=SimpleNamespace(scheme=scheme, netloc=netloc),
    )


def test_env_var_toma_prioridad(monkeypatch):
    monkeypatch.setenv("REDIRECT_GATEWAY_URL", "https://gw.acme.test/api/v1/gw")
    url, resolved = us5._gateway_url(_req(headers={"host": "backend:8000"}))
    assert url == "https://gw.acme.test/api/v1/gw"
    assert resolved is True


def test_env_var_sin_barra_final(monkeypatch):
    monkeypatch.setenv("REDIRECT_GATEWAY_URL", "https://gw.acme.test/api/v1/gw/")
    url, resolved = us5._gateway_url(_req())
    assert url == "https://gw.acme.test/api/v1/gw"
    assert resolved is True


def test_encabezados_x_forwarded(monkeypatch):
    monkeypatch.delenv("REDIRECT_GATEWAY_URL", raising=False)
    url, resolved = us5._gateway_url(
        _req(headers={"x-forwarded-proto": "https", "x-forwarded-host": "elea.example.com:8091"}))
    assert url == "https://elea.example.com:8091/api/v1/gw"
    assert resolved is True


def test_encabezados_host_publico(monkeypatch):
    monkeypatch.delenv("REDIRECT_GATEWAY_URL", raising=False)
    url, resolved = us5._gateway_url(
        _req(headers={"host": "elea.example.com:8091"}, scheme="https"))
    assert url == "https://elea.example.com:8091/api/v1/gw"
    assert resolved is True


@pytest.mark.parametrize("host", ["backend:8000", "backend", "engine:4000", "engine",
                                    "db:5432", "redis:6379", "nlp-analyzer:3000",
                                    "frontend:5173", "api-proxy:8091"])
def test_hostname_interno_de_compose_da_marcador(monkeypatch, host):
    monkeypatch.delenv("REDIRECT_GATEWAY_URL", raising=False)
    url, resolved = us5._gateway_url(_req(headers={"host": host}, scheme="http"))
    assert url == kits.URL_PLACEHOLDER
    assert resolved is False


def test_hostname_interno_con_x_forwarded_tambien_da_marcador(monkeypatch):
    monkeypatch.delenv("REDIRECT_GATEWAY_URL", raising=False)
    url, resolved = us5._gateway_url(
        _req(headers={"x-forwarded-proto": "http", "x-forwarded-host": "backend:8000"}))
    assert url == kits.URL_PLACEHOLDER
    assert resolved is False


def test_localhost_no_es_hostname_interno(monkeypatch):
    monkeypatch.delenv("REDIRECT_GATEWAY_URL", raising=False)
    url, resolved = us5._gateway_url(
        _req(headers={"host": "localhost:8091"}, scheme="http"))
    assert url == "http://localhost:8091/api/v1/gw"
    assert resolved is True


def test_placeholder_es_neutro_de_marca():
    assert kits.URL_PLACEHOLDER == "REEMPLAZAR_CON_LA_URL_DE_LA_PASARELA"
    assert "sentinel" not in kits.URL_PLACEHOLDER.lower()
    assert "guardian" not in kits.URL_PLACEHOLDER.lower()
    assert "elea" not in kits.URL_PLACEHOLDER.lower()
