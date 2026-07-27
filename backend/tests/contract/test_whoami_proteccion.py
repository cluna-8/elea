"""Contract test del bloque ``proteccion`` de ``GET /gw/whoami`` (spec 028, US4/T016).

La extensión pinta un chip de honestidad ("cobertura parcial") con este bloque y **no lo
hardcodea**: el copy es server-side (fuente única en ``governance_status``). Este archivo
fija el contrato de ``contracts/whoami-proteccion.md``:

- ``deteccion == "patrones"`` (vocabulario cerrado; hoy ninguna capa declara servicio propio).
- ``titulo == "Detección por patrones"``.
- ``detalle`` TERMINA con el literal ``_PISO_SIGUE`` (importado, jamás copiado a mano).
- ``capas_delegadas`` = las capas delegables en suscripción (content_moderation,
  prompt_injection).
- **Anti-fuga de motor**: ningún campo de ``proteccion`` contiene ``presidio``/``regex``/
  ``litellm`` (Constitución VII / C1).

Harness idéntico al de ``tests/integration/test_gw_inspect.py``: ``_resolve_attribution`` se
monkeypatchea a una identidad válida, así el foco es el contrato del endpoint y el test no
necesita Postgres.
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import gateway, inspect
from src.services.governance_status import _PISO_SIGUE

VALID = {"tenant_id": "00000000-0000-0000-0000-000000000001", "api_key_id": "key-1",
         "user_id": "u1", "group_id": "g1", "client_username": "dev.browser",
         "tenant_slug": "acme", "group_name": "Equipo Web", "key_label": "chatgpt-key",
         "tool_type": "chatgpt", "redact_enabled": None, "oauth_credential_ref": None}
ANON = {**VALID, "api_key_id": None}

# Nombres de motor/tecnología que NUNCA pueden salir en un campo de cliente (C1 / VII).
NOMBRES_DE_MOTOR = ("presidio", "regex", "litellm")


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(gateway, "_resolve_attribution",
                        lambda k: VALID if k == "sk-basa-valid" else ANON)
    app = FastAPI()
    app.include_router(inspect.router)
    return TestClient(app)


@pytest.fixture
def proteccion(client):
    r = client.get("/gw/whoami", headers={"X-Basa-Key": "sk-basa-valid"})
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert "proteccion" in cuerpo, "whoami conectado debe traer el bloque proteccion (US4)"
    return cuerpo["proteccion"]


def test_deteccion_es_patrones(proteccion):
    """Vocabulario cerrado: hoy la superficie detecta por patrones (sin servicio NLP)."""
    assert proteccion["deteccion"] == "patrones"


def test_titulo_exacto(proteccion):
    assert proteccion["titulo"] == "Detección por patrones"


def test_detalle_termina_con_piso_sigue(proteccion):
    """Fuente única de copy: el detalle cierra con el literal de governance_status, no con
    una copia a mano que se desincronizaría."""
    assert proteccion["detalle"].endswith(_PISO_SIGUE)


def test_capas_delegadas_son_moderacion_y_prompt_injection(proteccion):
    """Las capas que en suscripción aporta el upstream (FR-013), derivadas del registry."""
    assert proteccion["capas_delegadas"] == ["content_moderation", "prompt_injection"]


def test_ningun_campo_filtra_nombre_de_motor(proteccion):
    """Anti-fuga (Constitución VII): ni el motor de PII ni el de la pasarela pueden aparecer
    en un campo que ve el cliente, en ningún casing."""
    for clave, valor in proteccion.items():
        texto = " ".join(valor) if isinstance(valor, list) else str(valor)
        bajo = texto.casefold()
        for prohibido in NOMBRES_DE_MOTOR:
            assert prohibido not in bajo, (
                f"proteccion.{clave} filtra el nombre de motor '{prohibido}'")


def test_fail_closed_sin_key_no_trae_proteccion(client):
    """El bloque solo existe conectado: un 401 no expone copy ni estructura."""
    r = client.get("/gw/whoami")
    assert r.status_code == 401
    assert "proteccion" not in r.json()
