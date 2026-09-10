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


def test_sin_acted_for_user_id_la_cuenta_de_servicio_no_aparece(harness):
    """Bug real encontrado en verificación en vivo (10-sep): cuando el gasto NO se pudo
    atribuir a la persona real (limitación arquitectónica conocida del chat RAG — ver
    CHANGELOG de la 044 §13), `by_user` caía a `a.user_id`, que ES la cuenta de servicio
    que habló con el motor — y esta tabla, pensada para gasto de PERSONAS, terminaba
    listando `svc.anythingllm-provider2` como si fuera un usuario más."""
    client, factory, headers = harness
    from src.models.tenant import DEFAULT_TENANT_ID
    from src.models.user import User
    from src.models.audit import AuditLog

    db = factory()
    try:
        suf = uuid.uuid4().hex[:6]
        svc = User(id=uuid.uuid4(), tenant_id=DEFAULT_TENANT_ID,
                  username=f"svc.anythingllm-provider-{suf}", email=f"svc2-{suf}@x.test",
                  password_hash="!", role="client", account_type="service")
        db.add(svc)
        db.flush()
        svc_username = svc.username

        # Sin acted_for_user_id: exactamente el caso RAG sin atribuir.
        db.add(AuditLog(
            id=uuid.uuid4(), tenant_id=DEFAULT_TENANT_ID, timestamp=datetime.utcnow(),
            user_id=svc.id, acted_for_user_id=None, model="azure-gpt-4o-mini",
            prompt_tokens=100, completion_tokens=50, cost_usd=0.05, pii_detected=False,
            masked_entities=[], compliance_status="passed", latency_ms=100,
        ))
        db.commit()
    finally:
        db.close()

    r = client.get("/api/v1/costs/summary", params={"range": "day"}, headers=headers)
    assert r.status_code == 200, r.text
    by_user_names = {row["name"] for row in r.json()["by_user"]}
    assert svc_username not in by_user_names, \
        "una cuenta de servicio nunca debe aparecer en 'Gasto por usuario', aun sin acted_for_user_id"
