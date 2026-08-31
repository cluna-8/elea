"""Integration tests del health de licencia (spec 021 US5, T034 — FR-027).

Dos tiers: anónimo = solo {status, clock_rollback_suspected} (probe de ops sin
dimensionamiento); rol de operación (admin/compliance) = metadata completa,
incluida la génesis EFECTIVA de la cadena (lo que el onboarding registra).
Nunca el token crudo ni claves.
"""
import pytest

from migration_harness import require_postgres
from seat_gate_harness import (
    admin_headers,
    build_app_client,
    restore_suite_license,
    set_license,
)

require_postgres()

DB = "sentinel_test_health_license"

ANON_KEYS = {"status", "clock_rollback_suspected"}


@pytest.fixture(scope="module")
def harness():
    client, factory, cleanup = build_app_client(DB)
    headers = admin_headers(client)
    yield client, factory, headers
    cleanup()


@pytest.fixture(autouse=True)
def _restore():
    from src.licensing import reconcile
    yield
    reconcile.reset_for_tests()
    restore_suite_license()


def test_anonymous_gets_status_only(harness, monkeypatch, tmp_path):
    client, _factory, _headers = harness
    set_license(monkeypatch, tmp_path)
    resp = client.get("/api/v1/health/license")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == ANON_KEYS  # sin seats/expiry/reason para anónimos
    assert body["status"] == "active"


def test_admin_gets_full_metadata_without_secrets(harness, monkeypatch, tmp_path):
    import json

    client, factory, headers = harness
    set_license(monkeypatch, tmp_path, max_seats=7)
    from src.licensing import reconcile
    reconcile.run_once(session_factory=factory)

    resp = client.get("/api/v1/health/license", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "active"
    assert body["max_seats"] == 7
    assert isinstance(body["seats_used"], int)
    assert body["chain"]["genesis_license_id"]  # la génesis efectiva, para el onboarding
    assert body["reconcile"]["tenant_status"] == "ok"
    # Metadata-only: jamás material sensible en el health.
    dumped = json.dumps(body)
    assert "BEGIN" not in dumped and "sig" not in body
