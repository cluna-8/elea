"""`GET /costs/summary` → `by_user` agrupa por `COALESCE(acted_for_user_id, user_id)`
(spec 043 US2, T033, contrato 2) — verificación real: el gasto que la cuenta de servicio
hizo "en nombre de" una persona cuenta para esa persona, no para la cuenta de servicio."""
import uuid
from datetime import datetime

import pytest

from migration_harness import require_postgres
from seat_gate_harness import admin_headers, build_app_client

require_postgres()

DB = "sentinel_test_costs_by_user_043"


@pytest.fixture(scope="module")
def harness():
    client, factory, cleanup = build_app_client(DB)
    headers = admin_headers(client)
    yield client, factory, headers
    cleanup()


def test_gasto_en_nombre_de_cuenta_para_la_persona_no_para_el_servicio(harness):
    client, factory, headers = harness
    from src.models.tenant import DEFAULT_TENANT_ID
    from src.models.user import User
    from src.models.audit import AuditLog

    db = factory()
    try:
        suf = uuid.uuid4().hex[:6]
        ana = User(id=uuid.uuid4(), tenant_id=DEFAULT_TENANT_ID, username=f"ana-{suf}",
                  email=f"ana-{suf}@x.test", password_hash="!", role="client")
        svc = User(id=uuid.uuid4(), tenant_id=DEFAULT_TENANT_ID,
                  username=f"svc.rag-masking-{suf}", email=f"svc-{suf}@x.test",
                  password_hash="!", role="client", account_type="service")
        db.add_all([ana, svc])
        db.flush()
        ana_id, ana_username, svc_username = ana.id, ana.username, svc.username

        # svc.rag-masking autentica, pero actúa EN NOMBRE de Ana
        db.add(AuditLog(
            id=uuid.uuid4(), tenant_id=DEFAULT_TENANT_ID, timestamp=datetime.utcnow(),
            user_id=svc.id, acted_for_user_id=ana_id, model="azure-gpt-4o-mini",
            prompt_tokens=100, completion_tokens=50, cost_usd=0.05, pii_detected=False,
            masked_entities=[], compliance_status="passed", latency_ms=100,
            surface="servicio",
        ))
        db.commit()
    finally:
        db.close()

    r = client.get("/api/v1/costs/summary", params={"range": "day"}, headers=headers)
    assert r.status_code == 200, r.text
    by_user = {row["name"]: row for row in r.json()["by_user"]}

    assert ana_username in by_user
    assert by_user[ana_username]["cost_usd"] == pytest.approx(0.05)
    assert svc_username not in by_user
