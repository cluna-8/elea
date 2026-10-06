"""Autorización interna pasarela→motor (D14/D15; T031)."""
import base64
import json

import pytest

from sentinel.redirect import authz

KEY = "k" * 48
NOW = 1_800_000_000.0


def issue(**kw):
    args = dict(request_id="req-1", scope="t1/connection:k1", destination_id="d1",
                model="rdx-chatcompat/qwen", provider="openrouter",
                credential={"api_key": "sk-destino"}, api_base="https://openrouter.ai/api/v1",
                forced_masking=False, key=KEY, now=NOW)
    args.update(kw)
    return authz.issue(**args)


def test_roundtrip():
    tok = issue(decision={"public_id": "pro", "face": "openai_generic"})
    g = authz.verify(tok, expected_model="rdx-chatcompat/qwen", key=KEY, now=NOW + 1)
    assert g.request_id == "req-1" and g.scope == "t1/connection:k1" and g.destination_id == "d1"
    assert g.model == "rdx-chatcompat/qwen" and g.provider == "openrouter"
    assert g.credential == {"api_key": "sk-destino"}
    assert g.api_base == "https://openrouter.ai/api/v1" and g.forced_masking is False
    assert g.decision == {"public_id": "pro", "face": "openai_generic"}


def test_credential_not_in_clear():
    tok = issue()
    assert "sk-destino" not in tok
    payload = json.loads(base64.urlsafe_b64decode(tok.split(".")[1] + "=="))
    assert "sk-destino" not in json.dumps(payload)


def test_env_reference_travels_as_reference():
    tok = issue(credential={"api_key": "env:REDIRECT_CRED_OPENROUTER"})
    g = authz.verify(tok, key=KEY, now=NOW)
    assert g.credential == {"api_key": "env:REDIRECT_CRED_OPENROUTER"}


def test_expired():
    tok = issue(ttl=30)
    with pytest.raises(authz.AuthzExpired):
        authz.verify(tok, key=KEY, now=NOW + 31 + authz.CLOCK_SKEW)


def test_not_yet_valid():
    tok = issue()
    with pytest.raises(authz.AuthzExpired):
        authz.verify(tok, key=KEY, now=NOW - 60)


def test_ttl_bounds():
    with pytest.raises(ValueError):
        issue(ttl=0)
    with pytest.raises(ValueError):
        issue(ttl=authz.MAX_TTL + 1)


def test_model_mismatch():
    tok = issue()
    with pytest.raises(authz.AuthzModelMismatch):
        authz.verify(tok, expected_model="rdx-chatcompat/otro", key=KEY, now=NOW)


def test_wrong_key():
    tok = issue()
    with pytest.raises(authz.AuthzBadSignature):
        authz.verify(tok, key="z" * 48, now=NOW)


@pytest.mark.parametrize("field,value", [
    ("mdl", "rdx-chatcompat/otro"), ("dst", "d2"), ("fm", True), ("base", "https://evil"),
    ("scope", "t2/tenant:*"), ("rid", "req-2"),
])
def test_tampered_payload(field, value):
    tok = issue()
    v, body, mac = tok.split(".")
    payload = json.loads(base64.urlsafe_b64decode(body + "=="))
    payload[field] = value
    body2 = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    with pytest.raises(authz.AuthzBadSignature):
        authz.verify(f"{v}.{body2}.{mac}", key=KEY, now=NOW)


@pytest.mark.parametrize("tok", ["", "garbage", "v1.a", "v1.a.b.c", "v9.e30.AAAA", None, 42])
def test_malformed(tok):
    with pytest.raises(authz.AuthzError):
        authz.verify(tok, key=KEY, now=NOW)


def test_missing_key_env(monkeypatch):
    monkeypatch.delenv(authz.KEY_ENV, raising=False)
    with pytest.raises(authz.AuthzKeyMissing):
        authz.issue(request_id="r", scope="s", destination_id="d", model="rdx-openai/x",
                    provider="openai", credential={"api_key": "x"})


def test_short_key_rejected():
    with pytest.raises(authz.AuthzKeyMissing):
        issue(key="short")


def test_key_from_env(monkeypatch):
    monkeypatch.setenv(authz.KEY_ENV, KEY)
    tok = authz.issue(request_id="r", scope="s", destination_id="d", model="rdx-openai/x",
                      provider="openai", credential={"api_key": "x"}, now=NOW)
    assert authz.verify(tok, now=NOW).model == "rdx-openai/x"


def test_errors_are_brand_neutral():
    for cls in (authz.AuthzError, authz.AuthzExpired, authz.AuthzBadSignature, authz.AuthzModelMismatch,
                authz.AuthzMalformed, authz.AuthzKeyMissing):
        assert "sentinel" not in cls().public_message.lower()
