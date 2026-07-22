"""Regresión: el `tool` del body NO define la etiqueta auditada de la superficie.

Hallazgo de la verificación adversarial de la US2 (027, MEDIA): ``/gw/inspect`` tomaba
``body["tool"]`` —texto libre que manda la extensión, es decir la página— y lo pasaba crudo
como argumento ``model`` de ``gateway._audit``, o sea a la columna ``audit_logs.model``, y
al evento del monitor.

El escenario concreto: el agregado de cobertura de ``analytics`` excluye
``model <> 'license'`` (los eslabones de hash-chain de la 021 no son tráfico). Un usuario
que mandara ``{"text": "…", "tool": "license"}`` seguía quedando auditado pero DESAPARECÍA
del panel de cobertura — podía esconderse del reporte eligiendo la etiqueta de su propio
tráfico. Es además una fuga C1: texto libre del cliente dentro de una estructura auditada.

Estos tests fijan el invariante: la superficie que se audita sale de un **vocabulario
cerrado** (el ``tool_type`` de la Connection, dato del admin; si no, el enum ``SURFACES``
del registry; si no, un centinela explícito), nunca del string recibido.
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import gateway, inspect
from src.services.governance_catalog import SURFACES

BASE = {"tenant_id": "00000000-0000-0000-0000-000000000001", "api_key_id": "key-1",
        "user_id": "u1", "group_id": "g1", "client_username": "dev.browser",
        "tenant_slug": "acme", "group_name": "Equipo Web", "key_label": "browser-key",
        "redact_enabled": None, "oauth_credential_ref": None}

VALIDOS = {"desconocido", *SURFACES}


@pytest.fixture
def harness(monkeypatch):
    """Cliente + captura de lo que recibirían auditoría y monitor. Devuelve un setter del
    ``tool_type`` de la Connection: es el eje del que depende la resolución."""
    ident = {"actual": {**BASE, "tool_type": "chatgpt"}}
    auditado: list = []
    publicado: list = []

    monkeypatch.setattr(gateway, "_resolve_attribution",
                        lambda k: ident["actual"] if k == "sk-basa-valid"
                        else {**ident["actual"], "api_key_id": None})
    monkeypatch.setattr(gateway, "_audit",
                        lambda i, model, *a, **k: auditado.append(model))
    monkeypatch.setattr(gateway, "_publish_monitor",
                        lambda i, tool, model, *a, **k: publicado.append((tool, model)))

    app = FastAPI()
    app.include_router(gateway.router)
    app.include_router(inspect.router)
    client = TestClient(app)

    def set_tool_type(value):
        ident["actual"] = {**BASE, "tool_type": value}

    return client, auditado, publicado, set_tool_type


def _post(client, body):
    return client.post("/gw/inspect", json=body, headers={"X-Basa-Key": "sk-basa-valid"})


def test_tool_del_body_no_puede_disfrazarse_de_license(harness):
    # El caso del hallazgo: 'license' es justo el valor que analytics EXCLUYE del agregado
    # de cobertura. Antes se auditaba tal cual y el pedido se volvía invisible en el panel.
    client, auditado, publicado, _ = harness
    assert _post(client, {"text": "hola", "tool": "license"}).status_code == 200
    assert auditado == ["chatgpt"]                      # el tool_type de la Connection
    assert "license" not in auditado
    assert all("license" not in par for par in publicado[0])


def test_tool_type_de_la_connection_gana_al_tool_del_body(harness):
    # Confianza: la Connection la provisiona el admin; el body lo escribe la página.
    client, auditado, _, set_tool_type = harness
    set_tool_type("claude-code")
    _post(client, {"text": "hola", "tool": "cursor"})
    assert auditado == ["claude-code"]


def test_sin_tool_type_el_body_solo_vale_si_esta_en_el_enum(harness):
    # Señal no confiable pero acotada: se acepta por pertenencia al enum y lo que se propaga
    # es el token canónico del registry, no el string recibido.
    client, auditado, _, set_tool_type = harness
    set_tool_type(None)
    _post(client, {"text": "hola", "tool": "  ChatGPT  "})   # normaliza a 'chatgpt'
    assert auditado == ["chatgpt"]


@pytest.mark.parametrize("tool", [
    "license",              # el valor que esconde del reporte
    "ChatGPT (web)",        # etiqueta de display de la extensión desplegada
    "'; DROP TABLE audit_logs; --",
    "mi email es juan.perez@hospital.es",   # C1: texto libre del cliente
    {"a": 1}, 42, None, "",
])
def test_todo_lo_no_canonico_cae_al_centinela(harness, tool):
    client, auditado, publicado, set_tool_type = harness
    set_tool_type(None)                      # sin dato confiable de superficie
    assert _post(client, {"text": "hola", "tool": tool}).status_code == 200
    assert auditado == ["desconocido"]
    assert publicado == [("desconocido", "desconocido")]


def test_el_codominio_es_finito_y_todo_el_se_cuenta(harness):
    """El punto del fix: el cliente ya no elige cómo se llama su tráfico. Sea cual sea el
    body, la etiqueta auditada pertenece a un conjunto cerrado — y ningún valor de ese
    conjunto es el que analytics excluye."""
    client, auditado, _, set_tool_type = harness
    set_tool_type(None)
    for tool in ["license", "cursor", "copilot", "xxx", 1, None]:
        _post(client, {"text": "hola", "tool": tool})
    assert set(auditado) <= VALIDOS
    assert "license" not in VALIDOS
