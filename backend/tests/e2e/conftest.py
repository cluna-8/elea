"""Fixtures e2e (spec 019) — corren contra el STACK VIVO, no TestClient.

A diferencia de ``tests/integration`` (TestClient + httpx mockeado), esta suite cruza
procesos de verdad: ``gateway (backend:8000) → motor LiteLLM (litellm:4000) → Postgres
(db:5432) → custom_auth → BasaGuardrail``. Se corre desde un container efímero unido a
la red del compose::

    docker compose -p basa-guardian run --rm --no-deps backend pytest tests/e2e/ -v

El seed de la Connection (=``APIKey``) se inserta en la MISMA base ``basa_gateway`` vía
SQLAlchemy directo (``SessionLocal``), así el gateway y el motor la resuelven por HTTP.
``user_id=NULL`` evita colisión con el índice único ``(tenant_id, user_id, tool_type)``
(en Postgres los NULL son distintos entre sí). El GUC de RLS queda sin setear → aplica
la policy permisiva ``tenant_isolation_bootstrap``, la MISMA ventana pre-tenant que usa
el gateway para resolver keys (``_resolve_attribution`` abre ``SessionLocal`` sin
``tenant_context``). Cleanup SIEMPRE (teardown en ``finally``, aun si el test falla).
"""
import os
import urllib.error
import urllib.request
import uuid

import httpx
import pytest

# ``tests/conftest.py`` (parent, se importa antes que este) ya puso backend/ y backend/src
# en sys.path, así que estos imports de producción resuelven dentro del container.
from src.database import SessionLocal
from src.models.budget import APIKey
from src.models.tenant import DEFAULT_TENANT_ID
from src.services.key_material import hash_key, key_preview

# Puerta única del gateway sobre HTTP vivo. Override por env para correr fuera del
# compose (p.ej. contra el puerto publicado 8091), default = DNS interno de la red.
_BASE_URL = os.getenv("BASA_E2E_BASE_URL", "http://backend:8000/api/v1/gw")


@pytest.fixture(scope="session")
def base_url() -> str:
    return _BASE_URL


@pytest.fixture(scope="session", autouse=True)
def live_stack(base_url):
    """e2e = opcional: si el gateway no responde (CI sin stack), skip toda la suite en
    vez de fallar. Con el stack vivo, ``GET /gw`` devuelve 200 (gw_info) y los tests
    corren de verdad."""
    try:
        with urllib.request.urlopen(base_url, timeout=3) as resp:
            if resp.status != 200:
                pytest.skip(f"gateway respondió {resp.status} en {base_url}; e2e requiere stack vivo")
    except (urllib.error.URLError, OSError) as exc:
        pytest.skip(f"stack no vivo ({base_url}): {exc}; e2e opcional sin stack")


@pytest.fixture
def gw(base_url):
    """Cliente HTTP síncrono apuntado a la puerta única (timeout holgado: byok cruza
    hasta el motor)."""
    with httpx.Client(base_url=base_url, timeout=120.0) as client:
        yield client


@pytest.fixture
def seeded_byok_key():
    """Seedea una Connection byok activa (=``APIKey``) en la base compartida y devuelve
    su virtual key en claro. Teardown: borra la fila por id (``finally`` → siempre, aun
    si el test falla). ``user_id=NULL`` → sin colisión con el índice único parcial."""
    rand = uuid.uuid4().hex[:8]
    plain = f"sk-basa-e2e-{rand}"
    db = SessionLocal()
    row = APIKey(
        key_hash=hash_key(plain),
        tenant_id=DEFAULT_TENANT_ID,
        key_preview=key_preview(plain),
        name=f"e2e-conn-{rand}",
        tool_type="chat-ui",
        upstream_mode="byok",
        is_active=True,
        user_id=None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    key_id = row.id
    try:
        yield plain
    finally:
        obj = db.get(APIKey, key_id)
        if obj is not None:
            db.delete(obj)
            db.commit()
        db.close()
