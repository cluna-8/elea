"""Contract test de PARIDAD de rutas (spec 014 T033, FR-029, SC-005).

Protege el invariante central del port: la ruta **motor BYOK** (``BasaGuardrail``) y
el **passthrough OAuth** (``api/gateway.py``) aplican la MISMA política porque ambas
importan la MISMA ``basa_guardian_policy``. Si una deriva de la otra, esto rompe.

Dos niveles:

1. **Paridad de decisión** (puro, sin HTTP): para inputs representativos, el verdicto
   de bloqueo + los tipos enmascarados de ``gateway.evaluate_request_policy`` coinciden
   con lo que produce la librería compartida directamente — que es EXACTAMENTE lo que
   hace ``BasaGuardrail.async_pre_call_hook`` (mismo orden: AI-Act → secretos → mask).
2. **E2E del endpoint** con upstream mockeado: bloqueo→400, mask sale al upstream y
   unmask vuelve al caller (no-streaming y streaming, incluido un frame partido).

No hay LLM real en dev; el fake de ``httpx`` hace de ``api.anthropic.com`` y **eco** del
texto-user enmascarado que recibió, para verificar el round-trip mask→unmask entero.
"""
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import gateway
from extensions import basa_guardian_policy as policy

EMAIL = "juan.perez@hospital.es"
DNI = "12.345.678"
PII_TEXT = f"Contactá a {EMAIL}, DNI {DNI}, para el alta."
PROHIBITED_TEXT = "Implementá social scoring de los ciudadanos por barrio."
SECRET_TEXT = "Mi key es sk-abc123def456ghi789 y no la compartas."


def _body(user_text: str) -> dict:
    return {"model": "claude-3-5-sonnet", "messages": [{"role": "user", "content": user_text}]}


def _last_user(body: dict) -> str:
    return gateway._last_user_text(body)


def _entry(attribution, layer_code: str) -> dict:
    """El elemento de `applied_layers` de una capa (spec 027). Se afirma sobre el dict
    COMPLETO donde importa: el contrato prohíbe claves fuera de las 4 canónicas, y ahí es
    por donde volvería a fugarse texto del prompt (C1)."""
    return next(e for e in attribution.applied_layers if e["layer_code"] == layer_code)


# ════════════════════ Nivel 1 — paridad de decisión (puro) ════════════════════

@pytest.mark.asyncio
async def test_parity_aiact_block():
    reason, status, ph, ents, attr = await gateway.evaluate_request_policy(
        _body(PROHIBITED_TEXT), True)
    # Idéntico a lo que decide el guardrail: policy.evaluate_ai_act primero.
    assert policy.evaluate_ai_act(PROHIBITED_TEXT)["status"] == "blocked_prohibited"
    assert status == "blocked_prohibited" and reason and not ph and not ents
    # 027: el bloqueo es ATRIBUIBLE a la capa que lo produjo, no un "hubo bloqueo" pelado.
    assert attr.blocked_by_layer == "ai_act_evaluation"
    assert _entry(attr, "ai_act_evaluation") == {"layer_code": "ai_act_evaluation",
                                                 "status": "applied", "decision": "block"}
    # Y la capa que NO llegó a correr no se reporta como aplicada (SC-003): "no la
    # aplicamos" y "no corrió" dejan de ser indistinguibles.
    assert _entry(attr, "secret_detection")["status"] == "not_configured"


@pytest.mark.asyncio
async def test_parity_secret_block():
    reason, status, ph, ents, attr = await gateway.evaluate_request_policy(
        _body(SECRET_TEXT), True)
    assert policy.detect_secrets(SECRET_TEXT)  # el guardrail bloquea con esto mismo
    assert status == "blocked_secret" and reason and not ph and not ents
    assert attr.blocked_by_layer == "secret_detection"
    assert _entry(attr, "secret_detection")["decision"] == "block"


@pytest.mark.asyncio
async def test_parity_mask_entities_match_shared_lib():
    # El gateway enmascara EXACTAMENTE lo que policy.mask_body (lo que usa el guardrail).
    _, status, ph, ents, attr = await gateway.evaluate_request_policy(_body(PII_TEXT), True)
    assert status == "passed" and ph
    assert attr.blocked_by_layer is None
    assert _entry(attr, "pii_masking")["decision"] == "mask"
    gw_types = sorted(e["type"] for e in ents)

    _, ph_ref = await policy.mask_body(_body(PII_TEXT), policy.default_analyze)
    ref_types = sorted({policy.PH_TYPE_RE.match(p).group(1) for p in ph_ref})
    assert gw_types == ref_types
    assert "EMAIL_ADDRESS" in gw_types and "DNI" in gw_types


@pytest.mark.asyncio
async def test_parity_redact_off_no_mask():
    _, status, ph, ents, attr = await gateway.evaluate_request_policy(_body(PII_TEXT), False)
    assert status == "passed" and not ph and not ents  # toggle off = detección sin mutar
    # D8: con el enmascarado apagado la DETECCIÓN igual corre (es piso) y queda contada.
    # Esa combinación ES el registro "datos personales detectados, no enmascarados por
    # configuración" (FR-002) — codificado, sin una sola línea de texto libre (C1).
    detec = _entry(attr, "pii_detection")
    assert detec["status"] == "applied" and detec["decision"] == "flag" and detec["count"] >= 2
    assert _entry(attr, "pii_masking") == {"layer_code": "pii_masking",
                                           "status": "skipped", "decision": None}


@pytest.mark.asyncio
async def test_preview_scrubs_secrets_and_pii():
    # La vitrina (Redis, TTL) NUNCA debe mostrar credenciales ni PII cruda (C1).
    prev = await gateway._safe_preview(_body(f"{PII_TEXT} key sk-abc123def456ghi789"))
    assert "sk-abc123def456ghi789" not in prev and "[SECRET_REDACTED]" in prev
    assert EMAIL not in prev and "[EMAIL_ADDRESS_" in prev


@pytest.mark.asyncio
async def test_parity_unmask_roundtrip():
    body = _body(PII_TEXT)
    _, _, ph, _, _ = await gateway.evaluate_request_policy(body, True)
    masked = _last_user(body)
    assert EMAIL not in masked and DNI not in masked          # el upstream ve placeholders
    assert policy.unmask_text(masked, ph) == PII_TEXT          # el caller recupera el original


# ════════════════════ Nivel 2 — E2E del endpoint (upstream mockeado) ════════════════════

def _sse(text: str) -> bytes:
    events = [
        'event: message_start\ndata: {"type":"message_start","message":{"usage":{"input_tokens":11}}}',
        "event: content_block_start\n"
        'data: {"type":"content_block_start","index":0,"content_block":{"type":"text","text":""}}',
        "event: content_block_delta\n"
        'data: ' + json.dumps({"type": "content_block_delta", "index": 0,
                               "delta": {"type": "text_delta", "text": text}}),
        'event: content_block_stop\ndata: {"type":"content_block_stop","index":0}',
        'event: message_delta\ndata: {"type":"message_delta","usage":{"output_tokens":7}}',
    ]
    return ("\n\n".join(events) + "\n\n").encode("utf-8")


class _FakeResp:
    def __init__(self, payload: dict):
        self._raw = json.dumps(payload).encode("utf-8")
        self.status_code = 200
        self.headers = {"content-type": "application/json"}

    @property
    def content(self):
        return self._raw

    def json(self):
        return json.loads(self._raw)


class _FakeStream:
    def __init__(self, masked_text: str, split: bool):
        self.status_code = 200
        self.headers = {"content-type": "text/event-stream"}
        self._data = _sse(masked_text)
        self._split = split

    async def aiter_raw(self):
        if self._split:                       # frame partido entre chunks (prueba el buffer)
            mid = len(self._data) // 2
            yield self._data[:mid]
            yield self._data[mid:]
        else:
            yield self._data

    async def aread(self):
        return b""

    async def aclose(self):
        pass


class _FakeAsyncClient:
    """Hace de api.anthropic.com: captura lo que el gateway envía y ECO del texto-user
    enmascarado que recibió (así el unmask del gateway debe devolver el original)."""
    captured: dict = {}
    stream_split = False

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, headers=None, content=None):
        _FakeAsyncClient.captured = {"url": url, "headers": headers or {}, "content": content}
        masked = _last_user(json.loads(content))
        return _FakeResp({"content": [{"type": "text", "text": masked}],
                          "usage": {"input_tokens": 11, "output_tokens": 7}})

    def build_request(self, method, url, headers=None, content=None):
        _FakeAsyncClient.captured = {"url": url, "headers": headers or {}, "content": content}
        return {"content": content}

    async def send(self, req, stream=False):
        masked = _last_user(json.loads(req["content"]))
        return _FakeStream(masked, _FakeAsyncClient.stream_split)

    async def aclose(self):
        pass


@pytest.fixture
def client(monkeypatch):
    _FakeAsyncClient.captured = {}
    _FakeAsyncClient.stream_split = False
    monkeypatch.setattr(gateway.httpx, "AsyncClient", _FakeAsyncClient)
    monkeypatch.setattr(gateway, "_audit", lambda *a, **k: None)       # sin DB en este test
    monkeypatch.setattr(gateway, "_publish_monitor", lambda *a, **k: None)
    app = FastAPI()
    app.include_router(gateway.router)
    return TestClient(app)


def test_endpoint_blocks_aiact(client):
    r = client.post("/gw/v1/messages", json=_body(PROHIBITED_TEXT))
    assert r.status_code == 400
    assert "AI Act" in r.json()["error"]["message"] or "Ley de IA" in r.json()["error"]["message"]
    assert not _FakeAsyncClient.captured  # jamás tocó el upstream


def test_endpoint_blocks_secret(client):
    r = client.post("/gw/v1/messages", json=_body(SECRET_TEXT))
    assert r.status_code == 400
    assert "secreto" in r.json()["error"]["message"].lower()
    assert not _FakeAsyncClient.captured


def test_endpoint_masks_upstream_and_unmasks_reply(client):
    r = client.post("/gw/v1/messages", json=_body(PII_TEXT))
    assert r.status_code == 200
    sent = _FakeAsyncClient.captured["content"].decode()
    assert EMAIL not in sent and DNI not in sent              # upstream sólo ve placeholders
    assert "[EMAIL_ADDRESS_" in sent and "[DNI_" in sent
    reply = "".join(b.get("text", "") for b in r.json()["content"])
    assert EMAIL in reply and DNI in reply                    # el caller recupera lo real


def test_endpoint_redact_off_header_is_ignored(client):
    # CAMBIO DE COMPORTAMIENTO (spec 027, cierre del bypass D5): `X-Basa-Redact: 0` era un
    # override por-request, controlado por el CLIENTE, que apagaba el control más fuerte del
    # producto por encima de la postura del admin. Ahora el header es solo restrictivo: el
    # "off" se ignora y el enmascarado del perfil se aplica igual.
    r = client.post("/gw/v1/messages", json=_body(PII_TEXT), headers={"X-Basa-Redact": "0"})
    assert r.status_code == 200
    sent = _FakeAsyncClient.captured["content"].decode()
    assert EMAIL not in sent and "[EMAIL_ADDRESS_" in sent    # el header NO relajó nada


def test_endpoint_redact_on_header_forces_masking(client):
    # El sentido restrictivo SÍ aplica: agregar protección desde una señal no confiable es
    # legal, y es lo único que el header puede hacer.
    r = client.post("/gw/v1/messages", json=_body(PII_TEXT), headers={"X-Basa-Redact": "1"})
    assert r.status_code == 200
    sent = _FakeAsyncClient.captured["content"].decode()
    assert EMAIL not in sent and "[EMAIL_ADDRESS_" in sent


@pytest.mark.parametrize("split", [False, True])
def test_endpoint_streaming_unmask(client, split):
    _FakeAsyncClient.stream_split = split
    r = client.post("/gw/v1/messages", json={**_body(PII_TEXT), "stream": True})
    assert r.status_code == 200
    sent = _FakeAsyncClient.captured["content"].decode()
    assert EMAIL not in sent and "[EMAIL_ADDRESS_" in sent    # upstream ve placeholders
    # Reensamblar el texto de los text_delta del SSE devuelto al caller.
    got = ""
    for block in r.text.split("\n\n"):
        line = next((ln for ln in block.split("\n") if ln.startswith("data:")), None)
        if not line:
            continue
        data = json.loads(line[5:].strip())
        if data.get("type") == "content_block_delta":
            got += data.get("delta", {}).get("text", "")
    assert EMAIL in got and DNI in got                        # unmask sobre el stream (aun partido)


@pytest.mark.parametrize("bad_body,desc", [
    ("[1,2,3]", "top-level array"),
    ('"hola"', "top-level string"),
    ("42", "top-level number"),
    ("null", "top-level null"),
    ('{"model":"x","messages":123}', "messages scalar"),
    ('{"messages":true}', "messages bool"),
    ("{not json", "unparseable"),
])
def test_endpoint_malformed_body_is_400_not_500(client, bad_body, desc):
    # Trust boundary (review US4): un body malformado debe dar 400 honesto (como
    # Anthropic), nunca un 500, y jamás tocar el upstream.
    r = client.post("/gw/v1/messages", content=bad_body,
                    headers={"content-type": "application/json"})
    assert r.status_code == 400, f"{desc}: got {r.status_code}"
    assert not _FakeAsyncClient.captured


def test_endpoint_forwards_oauth_verbatim(client):
    """El Authorization del cliente (OAuth de suscripción) llega intacto al upstream."""
    client.post("/gw/v1/messages", json=_body("hola mundo"),
                headers={"Authorization": "Bearer oauth-subscription-token-xyz"})
    fwd = _FakeAsyncClient.captured["headers"]
    got = {k.lower(): v for k, v in fwd.items()}
    assert got.get("authorization") == "Bearer oauth-subscription-token-xyz"
