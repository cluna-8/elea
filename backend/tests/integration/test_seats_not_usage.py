"""Integration test seats ≠ uso (spec 021, T017 — SC-008/FR-012).

Un seat rate-limited a 0 rpm (gobernanza de uso, spec 007) IGUAL cuenta para
max_seats: la licencia cuenta ASIENTOS, no tokens ni presupuesto.
"""
import pytest

from migration_harness import require_postgres
from seat_gate_harness import (
    admin_headers,
    build_app_client,
    mock_engine,
    restore_suite_license,
    seed_active_seats,
    set_license,
)

require_postgres()

DB = "basa_test_seats_not_usage"


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


def test_zero_rpm_seat_still_counts_for_license(harness, monkeypatch, tmp_path):
    client, factory, headers = harness
    recorder = mock_engine(monkeypatch)
    set_license(monkeypatch, tmp_path, max_seats=2)
    # 2 seats castigados a 0 rpm por gobernanza (007): siguen siendo asientos
    seed_active_seats(factory, 2, rpm_limit=0, prefix="zero-rpm")

    resp = client.post("/api/v1/keys", headers=headers, json={"name": "tercera"})

    assert resp.status_code == 402, resp.text
    assert "license_seat_limit_exceeded" in resp.json()["detail"]
    assert recorder.generate_key_calls == []
