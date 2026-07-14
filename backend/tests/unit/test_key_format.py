"""Formato de la virtual key emitida online (F1, spec 019 hotfix).

``ai_engine_client.generate_key`` DEBE fijar un ``key`` con prefijo ``sk-basa-`` en el
payload a LiteLLM (que lo honra verbatim). Sin eso LiteLLM emite ``sk-<token>``, que el
router del gateway (``_BASA_KEY_RE = sk-basa-…``) no matchea → byok con key online cae a
passthrough (doble-masking + engine key fugada a Anthropic). Este test bloquea la regresión.
"""
import pytest

from src.services import ai_engine_client


@pytest.mark.asyncio
async def test_generate_key_forces_sk_basa_prefix(monkeypatch):
    captured: dict = {}

    async def _fake_post(path, payload):
        captured["path"] = path
        captured["payload"] = payload
        # LiteLLM honra un `key` provisto y lo devuelve verbatim.
        return {"key": payload["key"], "token": "sk-basa-01"}

    monkeypatch.setattr(ai_engine_client, "_post", _fake_post)

    result = await ai_engine_client.generate_key(name="copilot-conn")

    assert captured["path"] == "/key/generate"
    # el payload enviado a LiteLLM lleva un `key` con prefijo sk-basa-
    assert captured["payload"]["key"].startswith("sk-basa-")
    # y por ende la key en claro devuelta también (lo que se hashea/almacena en keys.py)
    assert result["plain_key"].startswith("sk-basa-")
    assert result["engine_key_token"].startswith("sk-basa-")
    # entropía real, no un literal fijo
    assert len(result["plain_key"]) > len("sk-basa-")


@pytest.mark.asyncio
async def test_generate_key_prefix_is_matchable_by_gateway_router(monkeypatch):
    # La key emitida DEBE matchear el regex de auto-byok del gateway, o el ruteo falla.
    from src.api import gateway

    async def _fake_post(path, payload):
        return {"key": payload["key"], "token": "t"}

    monkeypatch.setattr(ai_engine_client, "_post", _fake_post)
    result = await ai_engine_client.generate_key(name="cursor-conn")

    assert gateway._BASA_KEY_RE.fullmatch(result["plain_key"]) is not None
