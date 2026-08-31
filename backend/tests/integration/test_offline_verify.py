"""Integration test OFFLINE de la verificación de licencia (spec 021, T009).

SC-001 / FR-004: con el egress de red bloqueado (guard sobre socket), la
verificación de un token válido se completa con 0 llamadas salientes y el
sistema opera normal. La única conexión permitida es la DB local del stack
(loopback / POSTGRES_HOST), que no es egress.
"""
import os
import socket

import pytest
from sqlalchemy.orm import sessionmaker

from license_fixtures import issue_files
from migration_harness import PG_HOST, fresh_db, owner_engine, require_postgres, run_alembic

require_postgres()

DB = "sentinel_test_license_offline"


@pytest.fixture(scope="module")
def factory():
    fresh_db(DB)
    run_alembic(DB, "upgrade", "head")
    engine = owner_engine(DB)
    yield sessionmaker(autocommit=False, autoflush=False, bind=engine)
    engine.dispose()


@pytest.fixture(autouse=True)
def _restore_entitlement():
    yield
    from src.licensing import entitlement
    entitlement.initialize(force=True, emit_audit=False)


@pytest.fixture()
def egress_guard(monkeypatch):
    """Bloquea toda conexión saliente que no sea la DB local del stack."""
    allowed = {"127.0.0.1", "::1", "localhost", PG_HOST,
               os.getenv("POSTGRES_HOST", "localhost")}
    attempts = []
    real_connect = socket.socket.connect

    def guarded_connect(self, address):
        host = address[0] if isinstance(address, tuple) else address
        if isinstance(host, (bytes, bytearray)):
            host = host.decode("utf-8", "replace")
        if isinstance(host, str) and host not in allowed:
            attempts.append(host)
            raise OSError(f"egress bloqueado por el test: {host}")
        return real_connect(self, address)

    real_getaddrinfo = socket.getaddrinfo

    def guarded_getaddrinfo(host, *args, **kwargs):
        if isinstance(host, str) and host not in allowed:
            attempts.append(host)
            raise OSError(f"DNS bloqueado por el test: {host}")
        return real_getaddrinfo(host, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket, "getaddrinfo", guarded_getaddrinfo)
    return attempts


def test_valid_token_verifies_with_zero_egress(monkeypatch, factory, tmp_path, egress_guard):
    from src.licensing import entitlement
    keyset_path, lic_path, _ = issue_files(tmp_path)
    monkeypatch.delenv("SENTINEL_LICENSE_TOKEN", raising=False)
    monkeypatch.setenv("SENTINEL_LICENSE_PUBLIC_KEYS_FILE", str(keyset_path))
    monkeypatch.setenv("SENTINEL_LICENSE_TOKEN_FILE", str(lic_path))

    state = entitlement.initialize(force=True, session_factory=factory)

    # Verificación completada y sistema operativo, sin un solo intento saliente.
    assert state.status == "active", f"esperaba active, obtuve {state.status} ({state.reason})"
    assert state.token is not None and state.token.max_seats == 500
    assert egress_guard == []
    assert entitlement.get_state().status == "active"
