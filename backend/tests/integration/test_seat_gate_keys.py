"""Integration tests del gate de seats en POST /keys (spec 021, T014 — SC-003).

Con max_seats=N y N activas, la Connection N+1 se rechaza 402
license_seat_limit_exceeded SIN llamar a ai_engine_client.generate_key y con
audit; revocar una libera el asiento. Fail-closed sin entitlement (FR-010).
"""
import pytest

from migration_harness import require_postgres
from seat_gate_harness import (
    admin_headers,
    build_app_client,
    clear_license,
    license_audit_events,
    mock_engine,
    restore_suite_license,
    seed_active_seats,
    set_license,
)

require_postgres()

DB = "basa_test_seat_gate_keys"


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


def test_seat_limit_rejects_before_provisioning(harness, monkeypatch, tmp_path):
    client, factory, headers = harness
    recorder = mock_engine(monkeypatch)
    set_license(monkeypatch, tmp_path, max_seats=3)
    seed_active_seats(factory, 3, prefix="limit")

    resp = client.post("/api/v1/keys", headers=headers,
                       json={"name": "cuarta-connection"})

    assert resp.status_code == 402, resp.text
    assert "license_seat_limit_exceeded" in resp.json()["detail"]
    # FR-008: CERO provisioning en el motor para la request rechazada
    assert recorder.generate_key_calls == []
    # T021: el rechazo queda en el audit inmutable, metadata-only
    events = [e for e in license_audit_events(factory)
              if e["event_type"] == "license_seat_limit_exceeded"]
    assert events, "falta el evento de audit del rechazo"
    assert events[-1]["seats_used"] == 3
    assert events[-1]["max_seats"] == 3


def test_revoking_a_seat_frees_the_gate(harness, monkeypatch, tmp_path):
    client, factory, headers = harness
    recorder = mock_engine(monkeypatch)
    set_license(monkeypatch, tmp_path, max_seats=6)
    seed_active_seats(factory, 3, prefix="free")
    # ya hay 3 de 'limit' + 3 de 'free' = 6 → tope alcanzado
    resp = client.post("/api/v1/keys", headers=headers, json={"name": "bloqueada"})
    assert resp.status_code == 402

    # revocar una Connection por la API (baja a 5) → el POST pasa
    keys = client.get("/api/v1/keys", headers=headers).json()
    resp = client.delete(f"/api/v1/keys/{keys[0]['id']}", headers=headers)
    assert resp.status_code in (200, 204), resp.text

    resp = client.post("/api/v1/keys", headers=headers, json={"name": "liberada"})
    assert resp.status_code == 201, resp.text
    assert len(recorder.generate_key_calls) == 1


def test_failclosed_without_entitlement(harness, monkeypatch):
    """FR-010 / escenario 3: entitlement no cargado o inválido → bloqueo,
    NUNCA 'sin token = ilimitado'."""
    client, _factory, headers = harness
    recorder = mock_engine(monkeypatch)
    clear_license(monkeypatch)

    resp = client.post("/api/v1/keys", headers=headers, json={"name": "sin-licencia"})

    assert resp.status_code == 403, resp.text
    assert "license_creation_blocked" in resp.json()["detail"]
    assert recorder.generate_key_calls == []
