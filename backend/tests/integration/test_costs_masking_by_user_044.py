"""`GET /costs/summary` → `masking_by_user` (spec 044 US2, T025): cuenta DOCUMENTOS
distintos por persona (`document_group_id`, contrato 3 de la 043) para el tráfico de
enmascarado (`surface='servicio'`), separado del gasto real en `by_user` — varios chunks
del MISMO documento cuentan una sola vez."""
import uuid
from datetime import datetime

import pytest

from migration_harness import require_postgres
from seat_gate_harness import admin_headers, build_app_client

require_postgres()

DB = "sentinel_test_costs_masking_by_user_044"


@pytest.fixture(scope="module")
def harness():
    client, factory, cleanup = build_app_client(DB)
    headers = admin_headers(client)
    yield client, factory, headers
    cleanup()


def test_un_documento_con_varios_chunks_cuenta_una_sola_vez(harness):
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
        ana_id, ana_username = ana.id, ana.username
        doc_id = uuid.uuid4()

        # 3 chunks del MISMO documento (mismo document_group_id) — el enmascarado nunca
        # tiene costo real (0, 0), pero el `document_group_id` es lo que hace que cuenten
        # como UN documento, no tres filas sueltas.
        for _ in range(3):
            db.add(AuditLog(
                id=uuid.uuid4(), tenant_id=DEFAULT_TENANT_ID, timestamp=datetime.utcnow(),
                user_id=svc.id, acted_for_user_id=ana_id, model="servicio",
                prompt_tokens=0, completion_tokens=0, cost_usd=0.0, pii_detected=True,
                masked_entities=[], compliance_status="passed", latency_ms=10,
                surface="servicio", event_type="traffic", document_group_id=doc_id,
            ))
        # Un segundo documento, distinto, de la MISMA persona.
        db.add(AuditLog(
            id=uuid.uuid4(), tenant_id=DEFAULT_TENANT_ID, timestamp=datetime.utcnow(),
            user_id=svc.id, acted_for_user_id=ana_id, model="servicio",
            prompt_tokens=0, completion_tokens=0, cost_usd=0.0, pii_detected=True,
            masked_entities=[], compliance_status="passed", latency_ms=10,
            surface="servicio", event_type="traffic", document_group_id=uuid.uuid4(),
        ))
        db.commit()
    finally:
        db.close()

    r = client.get("/api/v1/costs/summary", params={"range": "day"}, headers=headers)
    assert r.status_code == 200, r.text
    masking_by_user = {row["name"]: row for row in r.json()["masking_by_user"]}

    assert ana_username in masking_by_user
    assert masking_by_user[ana_username]["documents"] == 2


def test_las_preguntas_con_costo_no_aparecen_en_masking_by_user(harness):
    client, factory, headers = harness
    from src.models.tenant import DEFAULT_TENANT_ID
    from src.models.user import User
    from src.models.audit import AuditLog

    db = factory()
    try:
        suf = uuid.uuid4().hex[:6]
        luis = User(id=uuid.uuid4(), tenant_id=DEFAULT_TENANT_ID, username=f"luis-{suf}",
                   email=f"luis-{suf}@x.test", password_hash="!", role="client")
        db.add(luis)
        db.flush()
        luis_username = luis.username

        db.add(AuditLog(
            id=uuid.uuid4(), tenant_id=DEFAULT_TENANT_ID, timestamp=datetime.utcnow(),
            user_id=luis.id, model="azure-gpt-4o-mini",
            prompt_tokens=100, completion_tokens=50, cost_usd=0.05, pii_detected=False,
            masked_entities=[], compliance_status="passed", latency_ms=100,
            event_type="traffic",
        ))
        db.commit()
    finally:
        db.close()

    r = client.get("/api/v1/costs/summary", params={"range": "day"}, headers=headers)
    assert r.status_code == 200, r.text
    masking_by_user = {row["name"]: row for row in r.json()["masking_by_user"]}
    assert luis_username not in masking_by_user
