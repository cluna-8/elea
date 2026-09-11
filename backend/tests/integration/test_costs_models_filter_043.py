"""`GET /costs/summary` (top_models) y `GET /analytics/summary` (desglose por modelo) no
devuelven `license` ni superficies (spec 043 US4, T044/T047, contrato 4) — verificación
real: solo modelos reales, cero rastro de `license`/`chat-ui`/`servicio` en la lista."""
from datetime import datetime

import pytest

from migration_harness import require_postgres
from seat_gate_harness import admin_headers, build_app_client

require_postgres()

DB = "sentinel_test_costs_models_filter_043"


@pytest.fixture(scope="module")
def harness():
    client, factory, cleanup = build_app_client(DB)
    headers = admin_headers(client)
    yield client, factory, headers
    cleanup()


def _seed_mixed_audit_rows(factory):
    import uuid
    from src.models.tenant import DEFAULT_TENANT_ID
    from src.models.audit import AuditLog

    db = factory()
    try:
        now = datetime.utcnow()
        rows = [
            # Modelo real — DEBE aparecer
            AuditLog(id=uuid.uuid4(), tenant_id=DEFAULT_TENANT_ID, timestamp=now,
                    model="azure-gpt-4o-mini", prompt_tokens=100, completion_tokens=50,
                    cost_usd=0.05, pii_detected=False, masked_entities=[],
                    compliance_status="passed", latency_ms=100, event_type="traffic"),
            # Evidencia de licencia — NO debe aparecer
            AuditLog(id=uuid.uuid4(), tenant_id=DEFAULT_TENANT_ID, timestamp=now,
                    model="license", prompt_tokens=0, completion_tokens=0, cost_usd=0.0,
                    pii_detected=False, masked_entities=[], compliance_status="passed",
                    latency_ms=0, event_type="license_evidence"),
            # Superficie de enmascarado — NO debe aparecer
            AuditLog(id=uuid.uuid4(), tenant_id=DEFAULT_TENANT_ID, timestamp=now,
                    model="servicio", surface="servicio", prompt_tokens=0,
                    completion_tokens=0, cost_usd=0.0, pii_detected=False,
                    masked_entities=[], compliance_status="passed", latency_ms=0,
                    event_type="traffic"),
        ]
        db.add_all(rows)
        db.commit()
    finally:
        db.close()


def test_costs_top_models_sin_license_ni_superficies(harness):
    client, factory, headers = harness
    _seed_mixed_audit_rows(factory)

    r = client.get("/api/v1/costs/summary", params={"range": "day"}, headers=headers)
    assert r.status_code == 200, r.text
    modelos = [m["model"] for m in r.json()["top_models"]]
    assert "azure-gpt-4o-mini" in modelos
    assert "license" not in modelos
    assert "servicio" not in modelos


def test_analytics_desglose_por_modelo_sin_license_ni_superficies(harness):
    client, factory, headers = harness
    r = client.get("/api/v1/analytics/summary", params={"range": "day"}, headers=headers)
    assert r.status_code == 200, r.text
    modelos = [m["model"] for m in r.json()["models"]]
    assert "azure-gpt-4o-mini" in modelos
    assert "license" not in modelos
    assert "servicio" not in modelos
