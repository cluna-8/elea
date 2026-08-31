"""Integration test de coexistencia de guardas (spec 021, T016 — SC-004/FR-011).

El 402 (licencia) y el 409 (duplicado por herramienta, índice parcial
uq_api_keys_tenant_user_tool) son guardas INDEPENDIENTES: un caso dispara sólo
el 409, otro sólo el 402, y un tercero podría disparar ambos (acá el gate de
licencia corre primero). En los tres: cero provisioning al motor.

Cada test siembra su propio estado y fija max_seats relativo al conteo real:
independiente del orden de ejecución.
"""
import uuid

import pytest

from migration_harness import require_postgres
from seat_gate_harness import (
    admin_headers,
    build_app_client,
    current_seats,
    mock_engine,
    restore_suite_license,
    set_license,
)

require_postgres()

DB = "sentinel_test_gate_coexist"


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


def _seed_client_with_key(factory, username):
    """Client con engine_user_id + una Connection ACTIVA claude-code (el
    escenario del duplicado). Suma 1 al conteo de seats."""
    from src.models.budget import APIKey
    from src.models.user import User
    db = factory()
    try:
        user = User(username=username, email=f"{username}@sentinel.com.ar",
                    password_hash="x", role="client",
                    engine_user_id=f"eng-{uuid.uuid4().hex[:8]}")
        db.add(user)
        db.flush()
        db.add(APIKey(name=f"key-{username}", key_hash=f"hash-{uuid.uuid4()}",
                      key_preview="sk-...c", tool_type="claude-code",
                      user_id=user.id))
        db.commit()
        return str(user.id)
    finally:
        db.close()


def test_duplicate_fires_only_409_below_seat_limit(harness, monkeypatch, tmp_path):
    """Caso A: hay licencia de sobra pero el user ya tiene Connection activa
    para la tool → 409, no 402."""
    client, factory, headers = harness
    recorder = mock_engine(monkeypatch)
    user_id = _seed_client_with_key(factory, "dup-user")
    set_license(monkeypatch, tmp_path, max_seats=current_seats(factory) + 50)

    resp = client.post("/api/v1/keys", headers=headers, json={
        "name": "duplicada", "user_id": user_id, "tool_type": "claude-code"})

    assert resp.status_code == 409, resp.text
    assert recorder.generate_key_calls == []


def test_seat_limit_fires_only_402_without_duplicate(harness, monkeypatch, tmp_path):
    """Caso B: user/tool nuevos (sin duplicado posible) pero tope lleno → 402."""
    client, factory, headers = harness
    recorder = mock_engine(monkeypatch)
    set_license(monkeypatch, tmp_path, max_seats=current_seats(factory))

    resp = client.post("/api/v1/keys", headers=headers, json={"name": "sin-dup"})

    assert resp.status_code == 402, resp.text
    assert "license_seat_limit_exceeded" in resp.json()["detail"]
    assert recorder.generate_key_calls == []


def test_both_conditions_gate_first_still_no_provisioning(harness, monkeypatch, tmp_path):
    """Caso C: duplicado Y tope lleno a la vez. Acá el gate de licencia corre
    primero (402 pineado abajo), pero lo invariante del contrato es: se
    rechaza y CERO provisioning; el `in (402, 409)` deja el texto de la
    respuesta como diagnóstico si el endpoint regresara a otro código."""
    client, factory, headers = harness
    recorder = mock_engine(monkeypatch)
    user_id = _seed_client_with_key(factory, "dup-user-2")
    set_license(monkeypatch, tmp_path, max_seats=current_seats(factory))

    resp = client.post("/api/v1/keys", headers=headers, json={
        "name": "dup-y-tope", "user_id": user_id, "tool_type": "claude-code"})

    assert resp.status_code in (402, 409), resp.text
    assert resp.status_code == 402  # orden documentado: licencia primero
    assert recorder.generate_key_calls == []
