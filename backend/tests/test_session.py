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
    token = mod.create_session_token("user-123", "admin", "admin", "tenant-abc")
    payload = mod.decode_session_token(token)
    assert payload is not None
    assert payload["sub"] == "user-123"
    assert payload["role"] == "admin"
    assert payload["username"] == "admin"
    assert payload["tenant"] == "tenant-abc"


def test_fail_closed_when_secret_missing(monkeypatch):
    mod = _reload_session(monkeypatch, "")
    with pytest.raises(RuntimeError):
        mod.create_session_token("user-123", "admin", "admin", "tenant-abc")
    # decode of any token also returns None (does not raise to caller) when no secret
    assert mod.decode_session_token("some.token.here") is None


def test_fail_closed_when_secret_too_short(monkeypatch):
    mod = _reload_session(monkeypatch, "short")
    with pytest.raises(RuntimeError):
        mod.create_session_token("user-123", "admin", "admin", "tenant-abc")


def test_decode_rejects_tampered_token(monkeypatch):
    mod = _reload_session(monkeypatch, "a" * 48)
    token = mod.create_session_token("user-123", "admin", "admin", "tenant-abc")
    # Flip a character in the payload section to tamper
    tampered = token[:-2] + ("AA" if token[-2:] != "AA" else "BB")
    assert mod.decode_session_token(tampered) is None


def test_new_token_carries_tenant_and_session_tenant_reads_it(monkeypatch):
    """T005/FR-011: la sesión nueva lleva el claim `tenant` y session_tenant lo devuelve tal cual."""
    mod = _reload_session(monkeypatch, "a" * 48)
    token = mod.create_session_token("user-123", "admin", "admin", "tenant-xyz")
    payload = mod.decode_session_token(token)
    assert payload["tenant"] == "tenant-xyz"
    assert mod.session_tenant(payload) == "tenant-xyz"


def test_session_tenant_defaults_for_legacy_token(monkeypatch):
    """Rotación: un token pre-T005 (emitido SIN el claim `tenant`) sigue siendo válido durante
    su ventana ≤24 h; session_tenant tolera la ausencia devolviendo el tenant default en lugar
    de romper el path que lee el tenant. Tras la ventana, todo token vivo ya trae el claim."""
    from datetime import datetime, timedelta
    mod = _reload_session(monkeypatch, "a" * 48)
    # Payload EXACTO de antes de T005 (sin `tenant`), mismo secreto/exp que un token legítimo.
    legacy_payload = {
        "sub": "user-123",
        "role": "admin",
        "username": "admin",
        "exp": datetime.utcnow() + timedelta(hours=1),
    }
    legacy = mod.jwt.encode(legacy_payload, mod._ensure_secret(), algorithm=mod.ALGORITHM)
    decoded = mod.decode_session_token(legacy)
    assert decoded is not None            # el token viejo sigue decodificando dentro de su ventana
    assert "tenant" not in decoded
    assert mod.session_tenant(decoded) == str(mod.DEFAULT_TENANT_ID)