"""Pantalla de descubrimiento neutra (spec 057, T014; FR-004, Diagnóstico #16).

`GET /api/v1/gw` es lo primero que lee quien integra una herramienta contra la pasarela. No puede
nombrar componentes internos del producto (Constitución VII): ningún nombre de la lista compartida
`deploy/release/checks/prohibited_names.txt` —la misma que consumen los checks de UI y de docs—.

La lista vive fuera de `backend/`: si el árbol del repo no está montado (suite del backend en
contenedor) se usa la copia mínima de abajo, y cuando el archivo SÍ está, un test verifica que la
copia no se desvió de él (una lista, jamás dos que derivan).
"""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.main import app

LISTA = Path(__file__).resolve().parents[3] / "deploy" / "release" / "checks" / "prohibited_names.txt"
# Copia mínima para cuando el repo no está montado; el test de sincronía la vigila.
RESPALDO = ("litellm", "berriai", "presidio")


def _nombres_prohibidos():
    if not LISTA.exists():
        return RESPALDO
    return tuple(l.strip().lower() for l in LISTA.read_text(encoding="utf-8").splitlines()
                 if l.strip() and not l.lstrip().startswith("#"))


@pytest.fixture(scope="module")
def descubrimiento():
    r = TestClient(app).get("/api/v1/gw")
    assert r.status_code == 200
    return r.json()


def test_la_pantalla_de_descubrimiento_no_nombra_componentes_internos(descubrimiento):
    texto = json.dumps(descubrimiento, ensure_ascii=False).lower()
    hallados = [n for n in _nombres_prohibidos() if n in texto]
    assert not hallados, f"GET /api/v1/gw nombra componentes internos: {hallados}"


def test_la_pantalla_conserva_su_estructura(descubrimiento):
    """Solo cambia el texto: las claves que lee quien integra siguen."""
    assert set(descubrimiento) >= {"service", "usage", "endpoints", "modes", "routing", "headers"}
    assert set(descubrimiento["modes"]) == {"subscription-passthrough", "byok"}
    assert descubrimiento["endpoints"] == [
        "/gw/v1/messages", "/gw/v1/messages/count_tokens", "/gw/v1/models"]
    assert set(descubrimiento["headers"]) == {"X-Sentinel-Key", "X-Sentinel-Redact",
                                              "X-Sentinel-Upstream"}


@pytest.mark.skipif(not LISTA.exists(), reason="el repo no está montado: sin lista compartida")
def test_el_respaldo_no_se_desvio_de_la_lista_compartida():
    assert set(RESPALDO) == set(_nombres_prohibidos())
