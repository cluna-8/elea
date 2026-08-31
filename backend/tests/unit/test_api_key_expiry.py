"""US8a (spec 028, T024): una virtual key VENCIDA no autentica la superficie browser.

Antes del fix, ``_resolve_attribution`` filtraba sólo ``is_active`` — una key con
``is_active=True`` y ``expires_at`` en el pasado seguía resolviendo (login + atribución
válidos), mientras la MISMA key era excluida del conteo de seats
(``seat_counter.count_active_seats``): dos definiciones de "activa" en desacuerdo. Sumar
``expires_at IS NULL OR expires_at > now()`` cierra el hueco y hace que una key vencida caiga
al mismo fallback anónimo que una inexistente → el ``whoami`` responde un **401
indistinguible** (sin oráculo que revele "vencida").

``_resolve_attribution`` abre su propia sesión con ``gateway.SessionLocal`` (no el ``get_db``
inyectado), así que el harness monkeypatchea ``SessionLocal`` a la DB de test migrada a head.
Los márgenes de expiración son de días para que el resultado no dependa de la zona horaria de
la sesión Postgres. ``migration_harness`` es importable directo: su directorio (``tests/``)
está en el path por el conftest de la suite.
"""
import uuid
from datetime import datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from migration_harness import fresh_db, owner_engine, require_postgres, run_alembic

require_postgres()

DB = "sentinel_test_api_key_expiry"


@pytest.fixture(scope="module")
def factory():
    fresh_db(DB)
    run_alembic(DB, "upgrade", "head")
    engine = owner_engine(DB)
    yield sessionmaker(autocommit=False, autoflush=False, bind=engine)
    engine.dispose()


@pytest.fixture
def resolve(factory, monkeypatch):
    """``_resolve_attribution`` apuntando a la DB de test (usa ``SessionLocal`` propia)."""
    from src.api import gateway
    monkeypatch.setattr(gateway, "SessionLocal", factory)
    return gateway._resolve_attribution


def seed_key(factory, plain, *, is_active=True, expires_at=None, tool_type="chatgpt"):
    """Inserta una APIKey con el hash real del plano, y devuelve su id (str)."""
    from src.models.budget import APIKey
    from src.services.key_material import hash_key, key_preview
    db = factory()
    try:
        row = APIKey(
            name=f"k-{uuid.uuid4().hex[:8]}",
            key_hash=hash_key(plain),
            key_preview=key_preview(plain),
            tool_type=tool_type,
            is_active=is_active,
            expires_at=expires_at,
        )
        db.add(row)
        db.commit()
        return str(row.id)
    finally:
        db.close()


def _plain():
    return f"sk-sentinel-{uuid.uuid4().hex}"


# ── Repro: el hueco que el fix cierra (rojo antes del fix) ────────────────────────


def test_key_activa_pero_vencida_cae_a_anonimo(factory, resolve):
    """``is_active=True`` + ``expires_at`` en el pasado ⇒ ``api_key_id is None``.
    Antes del fix devolvía el id (aceptada): este assert es el que fallaba en rojo."""
    plain = _plain()
    seed_key(factory, plain, expires_at=datetime.utcnow() - timedelta(days=1))

    ident = resolve(plain)

    assert ident["api_key_id"] is None
    assert ident["client_username"] is None   # ni identidad ni atribución filtradas


# ── Regresión: lo que debe SEGUIR resolviendo ────────────────────────────────────


def test_key_sin_expiracion_resuelve(factory, resolve):
    plain = _plain()
    key_id = seed_key(factory, plain, expires_at=None)

    assert resolve(plain)["api_key_id"] == key_id


def test_key_con_expiracion_futura_resuelve(factory, resolve):
    plain = _plain()
    key_id = seed_key(factory, plain, expires_at=datetime.utcnow() + timedelta(days=1))

    assert resolve(plain)["api_key_id"] == key_id


# ── Indistinguibilidad: whoami vencida == whoami inexistente ──────────────────────


def test_whoami_vencida_indistinguible_de_inexistente(factory, monkeypatch):
    """Sin oráculo: el 401 de una key vencida es byte a byte el de una que no existe.

    App mínima con sólo ``inspect.router`` (mismo harness que ``test_gw_inspect``) para que
    el ``_resolve_attribution`` REAL corra contra el filtro REAL en Postgres, sin el
    middleware del app completo de por medio."""
    from src.api import gateway, inspect

    monkeypatch.setattr(gateway, "SessionLocal", factory)
    app = FastAPI()
    app.include_router(inspect.router)
    client = TestClient(app)

    plain = _plain()
    seed_key(factory, plain, expires_at=datetime.utcnow() - timedelta(days=1))

    r_vencida = client.get("/gw/whoami", headers={"X-Sentinel-Key": plain})
    r_inexistente = client.get("/gw/whoami", headers={"X-Sentinel-Key": _plain()})

    assert r_vencida.status_code == 401
    assert r_inexistente.status_code == 401
    assert r_vencida.json() == r_inexistente.json()
