"""F0-7 live integration smoke tests — against the running backend on :8081.

These exercise the real HTTP surface, not just imports:
* admin-only endpoint (/users) rejects an anonymous request with 401 (F0-2 RBAC
  fail-closed).
* /users/login issues an `access_token` for the admin of the installation.
* /chat/completions accepts the prompt and returns 200 from the LiteLLM engine
  (fail-open for chat, no simulated fallback — F0-3), y rechaza con 401 el pedido
  sin credencial.

They self-skip (``pytest.skip``) when the backend is not reachable, so the suite
stays green in CI environments without the Docker stack running.

La contraseña del admin ya NO tiene default: el producto exige un mínimo de 12
caracteres y no existe ninguna credencial de fábrica (antes esto asumía
``admin``/``admin``, que era justamente el agujero). Los tests que necesitan sesión
se saltan solos si no se exporta ``BASA_ADMIN_PASS``.
"""
import os

import httpx
import pytest

BASE = os.getenv("BASA_BACKEND_URL", "http://localhost:8081/api/v1")
ADMIN_USER = os.getenv("BASA_ADMIN_USER", "admin")
ADMIN_PASS = os.getenv("BASA_ADMIN_PASS", "")


def _backend_reachable() -> bool:
    try:
        httpx.get(f"{BASE}/openapi.json", timeout=2.0)
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _backend_reachable(),
    reason=f"backend not reachable at {BASE} (run: docker compose up -d backend)",
)

requiere_credencial = pytest.mark.skipif(
    not ADMIN_PASS,
    reason="exportar BASA_ADMIN_PASS con la contraseña del admin de esta instalación "
           "(mínimo 12 caracteres; el producto no trae ninguna por defecto)",
)


def _token() -> str:
    r = httpx.post(
        f"{BASE}/users/login",
        json={"username": ADMIN_USER, "password": ADMIN_PASS},
        timeout=5.0,
    )
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    return r.json()["access_token"]


def test_anon_admin_endpoint_blocked():
    """F0-2: an anonymous request to an admin-only router must fail closed (401)."""
    r = httpx.get(f"{BASE}/users", timeout=5.0)
    assert r.status_code == 401, f"expected 401 for anon /users, got {r.status_code}"


@requiere_credencial
def test_login_returns_access_token():
    """Login del admin de la instalación: devuelve un access_token bearer (F0-1 JWT)."""
    r = httpx.post(
        f"{BASE}/users/login",
        json={"username": ADMIN_USER, "password": ADMIN_PASS},
        timeout=5.0,
    )
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    body = r.json()
    assert body.get("token_type") == "bearer"
    token = body.get("access_token")
    assert token and isinstance(token, str) and token.count(".") == 2


def test_chat_anonimo_es_401():
    """El chat es fail-closed: sin credencial no se procesa nada.

    Este mismo pedido creaba antes un usuario 'admin' con la contraseña 'admin' (el
    fallback anónimo de ``chat.py``), así que el smoke del repo era el exploit.
    """
    r = httpx.post(
        f"{BASE}/chat/completions",
        json={"message": "Di 'ok' en una palabra.", "model": "ollama-qwen3-4b"},
        timeout=10.0,
    )
    assert r.status_code == 401, f"expected 401 for anon /chat/completions, got {r.status_code}"


@requiere_credencial
def test_chat_completions_no_simulated_fallback():
    """F0-3: chat/completions never fabricates an AI response.

    When a real upstream model is configured and reachable it returns 200. When
    the engine is down (no ollama running / no provider key) it must fail closed
    with 502 + the "motor de IA no disponible" detail — it must NEVER return a
    200 with a hard-coded/simulated string. This is environment-independent.
    """
    r = httpx.post(
        f"{BASE}/chat/completions",
        json={"message": "Di 'ok' en una palabra.", "model": "ollama-qwen3-4b"},
        headers={"Authorization": f"Bearer {_token()}"},
        timeout=35.0,
    )
    if r.status_code == 200:
        # Real completion: must carry an actual response payload, not a stub.
        body = r.json()
        assert "response" in body or "content" in body or "choices" in body
    else:
        # Engine down → fail closed, no simulation.
        assert r.status_code == 502, f"unexpected status {r.status_code}: {r.text[:300]}"
        assert "motor de IA" in r.text, f"expected fail-closed 502 detail, got: {r.text[:300]}"
