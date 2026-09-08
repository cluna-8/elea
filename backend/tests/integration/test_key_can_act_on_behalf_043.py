"""`POST /keys` acepta y persiste `can_act_on_behalf` (spec 043 US2, T032, contrato 2) —
verificación real contra la API completa: el flag por default es `False` (ninguna llave
existente lo gana por accidente), y una llave creada con `can_act_on_behalf: true` lo
conserva en la fila real y en la respuesta de `GET /keys`."""
import pytest

from migration_harness import require_postgres
from seat_gate_harness import (
    admin_headers, build_app_client, mock_engine, restore_suite_license, set_license,
)

require_postgres()

DB = "sentinel_test_key_can_act_on_behalf_043"


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


def test_default_false(harness, monkeypatch, tmp_path):
    client, factory, headers = harness
    mock_engine(monkeypatch)
    set_license(monkeypatch, tmp_path, max_seats=1000)
    r = client.post("/api/v1/keys", headers=headers,
                    json={"name": "conexion-default", "tool_type": "claude-code"})
    assert r.status_code == 201, r.text
    key_id = r.json()["id"]

    r2 = client.get("/api/v1/keys", headers=headers)
    row = next(k for k in r2.json() if k["id"] == key_id)
    assert row["can_act_on_behalf"] is False


def test_true_explicito_se_persiste(harness, monkeypatch, tmp_path):
    client, factory, headers = harness
    mock_engine(monkeypatch)
    set_license(monkeypatch, tmp_path, max_seats=1000)
    r = client.post("/api/v1/keys", headers=headers,
                    json={"name": "conexion-servicio", "tool_type": "servicio",
                          "can_act_on_behalf": True})
    assert r.status_code == 201, r.text
    key_id = r.json()["id"]

    r2 = client.get("/api/v1/keys", headers=headers)
    row = next(k for k in r2.json() if k["id"] == key_id)
    assert row["can_act_on_behalf"] is True
    assert row["tool_type"] == "servicio"
