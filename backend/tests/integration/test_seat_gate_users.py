"""Integration tests del gate de seats en POST /users role=client (spec 021,
T015 — FR-009). El mismo tope max_seats aplica a la creación de Clients; los
roles administrativos NO son seats y no se gatean. Fail-closed sin entitlement.

Cada test siembra su propio estado y fija max_seats relativo al conteo real:
independiente del orden de ejecución.
"""
import pytest

from migration_harness import require_postgres
from seat_gate_harness import (
    admin_headers,
    build_app_client,
    clear_license,
    current_seats,
    mock_engine,
    restore_suite_license,
    seed_active_seats,
    set_license,
)

require_postgres()

DB = "basa_test_seat_gate_users"


@pytest.fixture(scope="module")
def harness():
    client, factory, cleanup = build_app_client(DB)
    headers = admin_headers(client)
    yield client, factory, headers
    cleanup()


@pytest.fixture(autouse=True)
def _restore():
    yield
    restore_suite_license()


def _user_payload(name, role):
    return {"username": name, "email": f"{name}@basa.com.ar", "role": role, "password": "x"}


def test_client_creation_blocked_at_seat_limit(harness, monkeypatch, tmp_path):
    client, factory, headers = harness
    recorder = mock_engine(monkeypatch)
    seed_active_seats(factory, 2, prefix="ulimit")
    set_license(monkeypatch, tmp_path, max_seats=current_seats(factory))

    resp = client.post("/api/v1/users", headers=headers,
                       json=_user_payload("client-n1", "client"))

    assert resp.status_code == 402, resp.text
    assert "license_seat_limit_exceeded" in resp.json()["detail"]
    assert recorder.create_user_calls == []


def test_legacy_client_roles_also_gated(harness, monkeypatch, tmp_path):
    """'clinician'/'developer' normalizan a client (013) → mismo gate."""
    client, factory, headers = harness
    recorder = mock_engine(monkeypatch)
    seed_active_seats(factory, 1, prefix="legacy")
    set_license(monkeypatch, tmp_path, max_seats=current_seats(factory))

    resp = client.post("/api/v1/users", headers=headers,
                       json=_user_payload("clinician-n1", "clinician"))

    assert resp.status_code == 402, resp.text
    assert recorder.create_user_calls == []


def test_admin_roles_are_not_seats(harness, monkeypatch, tmp_path):
    """Un compliance_officer no consume licencia: pasa aun con el tope lleno.
    Precondición verificada EN el test: con este mismo tope, un client es
    rechazado (el gate está caliente) — sin eso el 201 del officer sería vacuo."""
    client, factory, headers = harness
    recorder = mock_engine(monkeypatch)
    seed_active_seats(factory, 1, prefix="officer-fill")
    set_license(monkeypatch, tmp_path, max_seats=current_seats(factory))

    blocked = client.post("/api/v1/users", headers=headers,
                          json=_user_payload("client-officer-probe", "client"))
    assert blocked.status_code == 402, "precondición: el tope debe estar lleno"

    resp = client.post("/api/v1/users", headers=headers,
                       json=_user_payload("officer-1", "compliance_officer"))

    assert resp.status_code == 201, resp.text
    assert len(recorder.create_user_calls) == 1


def test_client_creation_allowed_below_limit(harness, monkeypatch, tmp_path):
    client, factory, headers = harness
    recorder = mock_engine(monkeypatch)
    set_license(monkeypatch, tmp_path, max_seats=current_seats(factory) + 10)

    resp = client.post("/api/v1/users", headers=headers,
                       json=_user_payload("client-ok", "client"))

    assert resp.status_code == 201, resp.text
    assert len(recorder.create_user_calls) == 1


def test_failclosed_without_entitlement_users(harness, monkeypatch):
    """FR-010 en ESTE endpoint: sin entitlement, el POST de client devuelve
    403 antes de crear el User local y de tocar el motor."""
    client, factory, headers = harness
    recorder = mock_engine(monkeypatch)
    clear_license(monkeypatch)

    resp = client.post("/api/v1/users", headers=headers,
                       json=_user_payload("client-degradado", "client"))

    assert resp.status_code == 403, resp.text
    assert "license_creation_blocked" in resp.json()["detail"]
    assert recorder.create_user_calls == []
    # el User local tampoco se creó (el gate corre antes del INSERT)
    from src.models.user import User
    db = factory()
    try:
        assert db.query(User).filter(User.username == "client-degradado").first() is None
    finally:
        db.close()
