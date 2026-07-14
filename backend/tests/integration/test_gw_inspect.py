"""Endpoints browser-DLP (spec 019 US3): /gw/whoami + /gw/inspect.

Verifica fail-closed (sin key → 401), el masking vía la librería compartida y el shape
de ``replacements`` que la extensión necesita para reescribir el body y des-enmascarar
el DOM (FR-014/FR-015/FR-019). Identidad monkeypatcheada (la resolución DB se prueba en
013); acá el foco es el contrato del endpoint.
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import gateway, inspect

EMAIL = "juan.perez@hospital.es"
DNI = "12.345.678"

VALID = {"tenant_id": "00000000-0000-0000-0000-000000000001", "api_key_id": "key-1",
         "user_id": "u1", "group_id": "g1", "client_username": "dev.browser",
         "tenant_slug": "acme", "group_name": "Equipo Web", "key_label": "chatgpt-key",
         "tool_type": "chatgpt", "redact_enabled": None, "oauth_credential_ref": None}
ANON = {**VALID, "api_key_id": None}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(gateway, "_resolve_attribution",
                        lambda k: VALID if k == "sk-basa-valid" else ANON)
    monkeypatch.setattr(gateway, "_audit", lambda *a, **k: None)
    monkeypatch.setattr(gateway, "_publish_monitor", lambda *a, **k: None)
    app = FastAPI()
    app.include_router(gateway.router)
    app.include_router(inspect.router)
    return TestClient(app)


def test_whoami_valid_key(client):
    r = client.get("/gw/whoami", headers={"X-Basa-Key": "sk-basa-valid"})
    assert r.status_code == 200
    j = r.json()
    assert j["ok"] and j["user"] == "dev.browser" and j["team"] == "Equipo Web"


def test_whoami_fail_closed(client):
    assert client.get("/gw/whoami").status_code == 401
    assert client.get("/gw/whoami", headers={"X-Basa-Key": "sk-basa-wrong"}).status_code == 401


def test_inspect_fail_closed(client):
    r = client.post("/gw/inspect", json={"text": f"mi email es {EMAIL}"})
    assert r.status_code == 401


def test_inspect_masks_and_returns_replacements(client):
    r = client.post("/gw/inspect", json={"text": f"Contactá a {EMAIL}, DNI {DNI}", "tool": "ChatGPT (web)"},
                    headers={"X-Basa-Key": "sk-basa-valid"})
    assert r.status_code == 200
    j = r.json()
    # el modelo (ChatGPT) verá placeholders, no la PII
    assert EMAIL not in j["masked"] and DNI not in j["masked"]
    assert "[EMAIL_ADDRESS_" in j["masked"] and "[DNI_" in j["masked"]
    # replacements = token→original para que la extensión des-enmascare el DOM
    tokens = {r_["token"]: r_["original"] for r_ in j["replacements"]}
    assert EMAIL in tokens.values() and DNI in tokens.values()
    # reconstruir el original desde masked + replacements (lo que hace la extensión)
    restored = j["masked"]
    for tok, orig in sorted(tokens.items(), key=lambda kv: -len(kv[1])):
        restored = restored.replace(tok, orig)
    assert EMAIL in restored and DNI in restored
    types = {e["type"] for e in j["entities"]}
    assert "EMAIL_ADDRESS" in types and "DNI" in types


def test_inspect_empty_text_ok(client):
    r = client.post("/gw/inspect", json={"text": ""}, headers={"X-Basa-Key": "sk-basa-valid"})
    assert r.status_code == 200 and r.json()["replacements"] == []
