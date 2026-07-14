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


# ── F3 [MED]: el masking NO se trunca — la PII del tail (>8000) también se enmascara ──

def test_inspect_masks_pii_beyond_old_8000_cap(client):
    # Antes: el texto se truncaba a 8000 chars ANTES de enmascarar → PII más allá del cap
    # salía CRUDA hacia el modelo. Ahora se enmascara el texto COMPLETO.
    text = "x" * 9000 + f" contactar a {EMAIL}"  # el email vive en el char ~9012 (>8000)
    r = client.post("/gw/inspect", json={"text": text}, headers={"X-Basa-Key": "sk-basa-valid"})
    assert r.status_code == 200
    j = r.json()
    assert EMAIL not in j["masked"]                    # el email del tail fue enmascarado
    assert "[EMAIL_ADDRESS_" in j["masked"]
    originals = {rp["original"] for rp in j["replacements"]}
    assert EMAIL in originals                           # y es reconstruible por la extensión


def test_inspect_short_text_still_masks(client):
    # Regresión F3: el texto corto sigue enmascarando igual (no rompimos el caso base).
    r = client.post("/gw/inspect", json={"text": f"mi email {EMAIL}"},
                    headers={"X-Basa-Key": "sk-basa-valid"})
    j = r.json()
    assert EMAIL not in j["masked"] and "[EMAIL_ADDRESS_" in j["masked"]


# ── F7 [LOW]: `text` no-string no debe crashear (500) — coerción a "" ────────────────

def test_inspect_non_string_int_text_does_not_500(client):
    r = client.post("/gw/inspect", json={"text": 123}, headers={"X-Basa-Key": "sk-basa-valid"})
    assert r.status_code == 200                         # NO 500
    assert r.json()["replacements"] == []               # coerción a "": nada que enmascarar


def test_inspect_non_string_list_text_does_not_500(client):
    r = client.post("/gw/inspect", json={"text": ["a", "b"]}, headers={"X-Basa-Key": "sk-basa-valid"})
    assert r.status_code == 200                         # NO 500
    assert r.json()["replacements"] == []


# ── F5 [LOW]: audit_service preserva el `count` de entidades ya agregadas ─────────────

def test_audit_preserves_preaggregated_entity_count():
    # El caller (gateway/inspect) pasa masked_entities YA agregadas: [{"type":…, "count":3}].
    # El bug re-contaba cada entrada como 1 (perdía el count real). Fix: + ent.get("count",1).
    from src.services.audit_service import AuditService

    class _FakeDB:
        def add(self, _obj): pass
        def commit(self): pass
        def refresh(self, _obj): pass
        def rollback(self): pass

    entry = AuditService.log_transaction(
        db=_FakeDB(), model="claude-3-5-sonnet",
        prompt_tokens=0, completion_tokens=0, cost_usd=0.0,
        pii_detected=True,
        masked_entities=[{"type": "EMAIL_ADDRESS", "count": 3}],
        compliance_status="passed", latency_ms=1,
    )
    assert entry is not None
    counts = {e["type"]: e["count"] for e in entry.masked_entities}
    assert counts["EMAIL_ADDRESS"] == 3                 # antes del fix: 1


def test_audit_defaults_count_to_one_without_count_key():
    # Regresión F5: entradas sin `count` (una por entidad) siguen contando 1 c/u.
    from src.services.audit_service import AuditService

    class _FakeDB:
        def add(self, _obj): pass
        def commit(self): pass
        def refresh(self, _obj): pass
        def rollback(self): pass

    entry = AuditService.log_transaction(
        db=_FakeDB(), model="m",
        prompt_tokens=0, completion_tokens=0, cost_usd=0.0,
        pii_detected=True,
        masked_entities=[{"type": "DNI"}, {"type": "DNI"}],
        compliance_status="passed", latency_ms=1,
    )
    counts = {e["type"]: e["count"] for e in entry.masked_entities}
    assert counts["DNI"] == 2
