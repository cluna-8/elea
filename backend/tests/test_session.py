"""F0-7 smoke tests — JWT session (F0-1).

Verifies the dedicated-JWT-secret contract: round-trip works when a >=32 char secret
is set, and the module fails closed (refuses to issue/decode) when the secret is
missing or too short — never falling back to a hard-coded key.
"""
import importlib

import pytest


def _reload_session(monkeypatch, secret):
    """Reload the session module with a given JWT_SECRET_KEY env value."""
    monkeypatch.setenv("JWT_SECRET_KEY", secret)
    import src.auth.session as session_mod
    importlib.reload(session_mod)
    return session_mod


def test_jwt_roundtrip(monkeypatch):
    mod = _reload_session(monkeypatch, "a" * 48)
    token = mod.create_session_token("user-123", "admin", "admin")
    payload = mod.decode_session_token(token)
    assert payload is not None
    assert payload["sub"] == "user-123"
    assert payload["role"] == "admin"
    assert payload["username"] == "admin"


def test_fail_closed_when_secret_missing(monkeypatch):
    mod = _reload_session(monkeypatch, "")
    with pytest.raises(RuntimeError):
        mod.create_session_token("user-123", "admin", "admin")
    # decode of any token also returns None (does not raise to caller) when no secret
    assert mod.decode_session_token("some.token.here") is None


def test_fail_closed_when_secret_too_short(monkeypatch):
    mod = _reload_session(monkeypatch, "short")
    with pytest.raises(RuntimeError):
        mod.create_session_token("user-123", "admin", "admin")


def test_decode_rejects_tampered_token(monkeypatch):
    mod = _reload_session(monkeypatch, "a" * 48)
    token = mod.create_session_token("user-123", "admin", "admin")
    # Flip a character in the payload section to tamper
    tampered = token[:-2] + ("AA" if token[-2:] != "AA" else "BB")
    assert mod.decode_session_token(tampered) is None