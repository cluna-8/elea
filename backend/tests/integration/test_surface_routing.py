"""Ruteo de superficies base_url (spec 019 US1+US2): passthrough vs auto-byok.

Verifica la PUERTA ÚNICA: a qué upstream rutea cada cliente y la **exclusión
load-bearing de `x-basa-*`** que hace coexistir Claude Code (passthrough) y Copilot
(byok) sobre el mismo gateway (SC-001/SC-002/SC-003).

El fake de httpx registra la URL + headers con que se llamó al upstream, así podemos
afirmar byok→motor (`http://litellm:4000`) vs passthrough→`api.anthropic.com`.
"""
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import gateway

ENGINE = "http://engine:4000"
ANTHROPIC = "https://api.anthropic.com"
BENIGN = {"model": "claude-3-5-sonnet", "messages": [{"role": "user", "content": "hola mundo"}]}


class _Resp:
    def __init__(self):
        self._raw = json.dumps({"content": [{"type": "text", "text": "ok"}],
                                "usage": {"input_tokens": 3, "output_tokens": 2}}).encode()
        self.status_code = 200
        self.headers = {"content-type": "application/json"}

    @property
    def content(self):
        return self._raw

    def json(self):
        return json.loads(self._raw)


class _FakeClient:
    """Registra la última llamada al upstream (URL + headers) para afirmar el ruteo."""
    last: dict = {}

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, headers=None, content=None):
        _FakeClient.last = {"url": url, "headers": headers or {}, "content": content}
        return _Resp()

    async def get(self, url, headers=None):
        _FakeClient.last = {"url": url, "headers": headers or {}}
        return _Resp()


@pytest.fixture
def client(monkeypatch):
    _FakeClient.last = {}
    monkeypatch.setattr(gateway.httpx, "AsyncClient", _FakeClient)
    monkeypatch.setattr(gateway, "_audit", lambda *a, **k: None)
    monkeypatch.setattr(gateway, "_publish_monitor", lambda *a, **k: None)
    monkeypatch.setattr(gateway, "_resolve_attribution", lambda k: {
        "tenant_id": "00000000-0000-0000-0000-000000000001", "user_id": None, "group_id": None,
        "api_key_id": None, "client_username": None, "tenant_slug": None,
        "tool_type": None, "redact_enabled": None, "oauth_credential_ref": None})
    app = FastAPI()
    app.include_router(gateway.router)
    return TestClient(app)


def _auth(headers: dict) -> str:
    return {k.lower(): v for k, v in headers.items()}.get("authorization", "")


# ── US1: Claude Code passthrough de suscripción ─────────────────────────────────

def test_passthrough_routes_to_anthropic_verbatim_oauth(client):
    # T006/SC-001: OAuth del cliente → verbatim a api.anthropic.com (no lo consume).
    r = client.post("/gw/v1/messages", json=BENIGN,
                    headers={"Authorization": "Bearer oauth-sub-tok"})
    assert r.status_code == 200
    assert _FakeClient.last["url"].startswith(ANTHROPIC)
    assert _auth(_FakeClient.last["headers"]) == "Bearer oauth-sub-tok"


def test_passthrough_forwards_anthropic_headers(client):
    # T007/FR-003: anthropic-version/beta + user-agent llegan sin alterar.
    client.post("/gw/v1/messages", json=BENIGN, headers={
        "Authorization": "Bearer oauth", "anthropic-version": "2023-06-01",
        "anthropic-beta": "oauth-2025", "user-agent": "claude-cli/1.2"})
    h = {k.lower(): v for k, v in _FakeClient.last["headers"].items()}
    assert h.get("anthropic-version") == "2023-06-01"
    assert h.get("anthropic-beta") == "oauth-2025"
    assert h.get("user-agent") == "claude-cli/1.2"


# ── US2: Copilot auto-byok + key-in-URL + exclusión x-basa-* ────────────────────

def test_auto_byok_routes_to_engine(client):
    # T012/SC-003: sk-basa-… en x-api-key (sin X-Basa-Upstream) → motor + la key va como auth.
    r = client.post("/gw/v1/messages", json=BENIGN,
                    headers={"x-api-key": "sk-basa-copilot123"})
    assert r.status_code == 200
    assert _FakeClient.last["url"].startswith(ENGINE)
    assert _auth(_FakeClient.last["headers"]) == "Bearer sk-basa-copilot123"


def test_xbasa_key_excluded_stays_passthrough(client):
    # T013/SC-002 (load-bearing): Claude Code trae sk-basa SOLO en X-Basa-Key (atribución)
    # + su OAuth real → DEBE quedar en passthrough, NO desviarse a byok.
    client.post("/gw/v1/messages", json=BENIGN, headers={
        "X-Basa-Key": "sk-basa-attrib999", "Authorization": "Bearer oauth-real"})
    assert _FakeClient.last["url"].startswith(ANTHROPIC)          # NO fue al motor
    assert _auth(_FakeClient.last["headers"]) == "Bearer oauth-real"


def test_same_key_in_xapikey_would_go_byok(client):
    # Prueba negativa de la exclusión: el MISMO valor en x-api-key SÍ va a byok
    # (demuestra que el scan lo detectaría si no se excluyera x-basa-*).
    client.post("/gw/v1/messages", json=BENIGN, headers={"x-api-key": "sk-basa-attrib999"})
    assert _FakeClient.last["url"].startswith(ENGINE)


def test_key_in_url_routes_to_engine(client):
    # T014/FR-010: Copilot con x-api-key vacío + ?k=sk-basa-… → byok por fallback.
    client.post("/gw/v1/messages?k=sk-basa-inurl456", json=BENIGN, headers={"x-api-key": ""})
    assert _FakeClient.last["url"].startswith(ENGINE)
    assert _auth(_FakeClient.last["headers"]) == "Bearer sk-basa-inurl456"


# ── F2 [HIGH]: byok sin virtual key es fail-closed (NO master-key → motor) ──────────

def test_explicit_upstream_byok_without_key_is_fail_closed(client):
    # F2/FR-002 (post-hotfix): X-Basa-Upstream: byok SIN sk-basa ya NO rutea al motor con
    # el master key (sería un bypass a PROXY_ADMIN saltando auth/budgets). Ahora es 401 y
    # el motor NUNCA es contactado (el fake de httpx no registra llamada).
    r = client.post("/gw/v1/messages", json=BENIGN, headers={"X-Basa-Upstream": "byok"})
    assert r.status_code == 401
    assert _FakeClient.last == {}  # el motor jamás recibió el master key


def test_byok_with_virtual_key_still_routes_with_client_key(client):
    # F2 regresión: con una sk-basa real, byok SÍ rutea al motor y usa la key del cliente
    # como auth (jamás el master key). Preserva SC-003.
    r = client.post("/gw/v1/messages", json=BENIGN, headers={"x-api-key": "sk-basa-x"})
    assert r.status_code == 200
    assert _FakeClient.last["url"].startswith(ENGINE)
    assert _auth(_FakeClient.last["headers"]) == "Bearer sk-basa-x"


# ── F1 [HIGH]: keys online sk-basa-… rutean a byok (no caen a passthrough) ──────────

def test_online_sk_basa_key_in_authorization_routes_to_engine(client):
    # F1 (routing lock): una virtual key emitida online (sk-basa-…) que llega en
    # Authorization: Bearer DEBE resolver byok → motor y NO caer a passthrough. Cierra el
    # misruteo que fugaba la engine key a Anthropic con doble-masking.
    r = client.post("/gw/v1/messages", json=BENIGN,
                    headers={"Authorization": "Bearer sk-basa-onlineXYZ"})
    assert r.status_code == 200
    assert _FakeClient.last["url"].startswith(ENGINE)          # byok → motor, NO passthrough
    assert not _FakeClient.last["url"].startswith(ANTHROPIC)
    assert _auth(_FakeClient.last["headers"]) == "Bearer sk-basa-onlineXYZ"


def test_models_endpoint_honors_auto_byok(client):
    # FR-011: /v1/models con virtual key → motor (para que la tool liste modelos byok).
    client.get("/gw/v1/models", headers={"x-api-key": "sk-basa-copilot123"})
    assert _FakeClient.last["url"].startswith(ENGINE)


# ── P2 [Codex pase 2]: helpers honran byok explícito + virtual key en X-Basa-Key ────
# El scan de headers excluye x-basa-* (load-bearing), así que la virtual key que viaja
# SOLO en X-Basa-Key debe threadearse a _detect_mode_and_key igual que en /v1/messages.
# Antes del fix _plain_passthrough la descartaba → 401 espurio / motor no contactado.

def test_helper_models_byok_with_xbasa_key_routes_to_engine(client):
    # P2: GET /v1/models con X-Basa-Upstream: byok + la virtual key SOLO en X-Basa-Key
    # → motor (paridad con /v1/messages). Antes del fix: 401, motor jamás contactado.
    r = client.get("/gw/v1/models",
                   headers={"X-Basa-Upstream": "byok", "X-Basa-Key": "sk-basa-helperX"})
    assert r.status_code == 200
    assert _FakeClient.last["url"].startswith(ENGINE)
    assert _auth(_FakeClient.last["headers"]) == "Bearer sk-basa-helperX"


def test_helper_count_tokens_byok_with_xbasa_key_routes_to_engine(client):
    # P2: idem para POST /v1/messages/count_tokens (el otro helper que Claude Code llama).
    r = client.post("/gw/v1/messages/count_tokens", json=BENIGN,
                    headers={"X-Basa-Upstream": "byok", "X-Basa-Key": "sk-basa-helperX"})
    assert r.status_code == 200
    assert _FakeClient.last["url"].startswith(ENGINE)
    assert _auth(_FakeClient.last["headers"]) == "Bearer sk-basa-helperX"


def test_helper_models_byok_without_any_key_is_fail_closed(client):
    # F2 regresión sobre los helpers: byok SIN ninguna virtual key sigue siendo 401 y el
    # motor NUNCA se contacta (no cae al master key → sin bypass a PROXY_ADMIN). El fix P2
    # NO debe aflojar esto: X-Basa-Key ausente ⇒ basa_key None ⇒ fail-closed.
    r = client.get("/gw/v1/models", headers={"X-Basa-Upstream": "byok"})
    assert r.status_code == 401
    assert _FakeClient.last == {}  # el motor jamás recibió el master key
