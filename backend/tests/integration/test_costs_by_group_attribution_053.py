"""`GET /costs/summary` → `by_group` resuelve el grupo a través del usuario real
(spec 053, mail Tomás Mc Nally 16-sep: "mi usuario está en un grupo y ese grupo no
aparece: solo incrementa el sin grupo") — verificación real: el gasto que una cuenta de
servicio hace "en nombre de" una persona con grupo asignado cuenta para ESE grupo, no
para "sin grupo", aun cuando la fila de auditoría no trae `user_group_id` (el caso real:
`user_group_id` es el grupo de la Connection/llave de servicio, casi siempre NULL)."""
import uuid
from datetime import datetime

import pytest

from migration_harness import require_postgres
from seat_gate_harness import admin_headers, build_app_client

require_postgres()

DB = "sentinel_test_costs_by_group_053"


@pytest.fixture(scope="module")
def harness():
    client, factory, cleanup = build_app_client(DB)
    headers = admin_headers(client)
    yield client, factory, headers
    cleanup()


def test_gasto_en_nombre_de_cuenta_cuenta_para_el_grupo_de_la_persona_real(harness):
    client, factory, headers = harness
    from src.models.tenant import DEFAULT_TENANT_ID
    from src.models.user import User, Group
    from src.models.audit import AuditLog

    db = factory()
    try:
        suf = uuid.uuid4().hex[:6]
        grupo = Group(id=uuid.uuid4(), tenant_id=DEFAULT_TENANT_ID, name=f"analistas-{suf}")
        db.add(grupo)
        db.flush()

        tomy = User(id=uuid.uuid4(), tenant_id=DEFAULT_TENANT_ID, username=f"tmcnally-{suf}",
                    email=f"tmcnally-{suf}@x.test", password_hash="!", role="client",
                    group_id=grupo.id)
        svc = User(id=uuid.uuid4(), tenant_id=DEFAULT_TENANT_ID,
                   username=f"svc.rag-masking-{suf}", email=f"svc-{suf}@x.test",
                   password_hash="!", role="client", account_type="service")
        db.add_all([tomy, svc])
        db.flush()
        tomy_id, grupo_nombre = tomy.id, grupo.name

        # svc.rag-masking autentica (fila SIN user_group_id — el caso real reportado:
        # el grupo crudo de la Connection es NULL), pero actúa EN NOMBRE de Tomás, que sí
        # tiene grupo.
        db.add(AuditLog(
            id=uuid.uuid4(), tenant_id=DEFAULT_TENANT_ID, timestamp=datetime.utcnow(),
            user_id=svc.id, acted_for_user_id=tomy_id, user_group_id=None,
            model="azure-gpt-5.1-chat", prompt_tokens=100, completion_tokens=50,
            cost_usd=0.05, pii_detected=False, masked_entities=[],
            compliance_status="passed", latency_ms=100,
        ))
        db.commit()
    finally:
        db.close()

    r = client.get("/api/v1/costs/summary", params={"range": "day"}, headers=headers)
    assert r.status_code == 200, r.text
    by_group = {row["name"]: row for row in r.json()["by_group"]}

    assert grupo_nombre in by_group, (
        "el gasto en nombre de un usuario con grupo debe aparecer bajo su grupo real, "
        "no perderse en 'sin grupo'"
    )
    assert by_group[grupo_nombre]["cost_usd"] == pytest.approx(0.05)
