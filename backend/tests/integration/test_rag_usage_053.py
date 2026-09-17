"""`POST /chat/rag-usage` (spec 053) — el Hub reporta el consumo real de un turno de
chat que pasó por el motor de DOCUMENTOS (AnythingLLM), porque ese motor es de terceros
y nunca puede mandar `X-Guardian-Acting-User` (el header que usa el motor tabular, ver
`tabular/app/llm.py`). Verificado en vivo contra AnythingLLM real y el flujo completo del
Hub (17-sep) antes de escribir este test — acá se fija la regresión: identidad correcta,
grupo correcto, presupuesto descontado, sin depender de ningún header de terceros."""
import uuid
from datetime import datetime

import pytest

from migration_harness import require_postgres
from seat_gate_harness import build_app_client

require_postgres()

DB = "sentinel_test_rag_usage_053"


@pytest.fixture(scope="module")
def harness():
    client, factory, cleanup = build_app_client(DB)
    yield client, factory
    cleanup()


def test_reporta_costo_atribuido_al_usuario_y_su_grupo_real(harness):
    client, factory = harness
    from src.auth.session import create_session_token
    from src.models.tenant import DEFAULT_TENANT_ID
    from src.models.user import User, Group
    from src.models.budget import Budget
    from src.models.audit import AuditLog

    db = factory()
    try:
        suf = uuid.uuid4().hex[:6]
        grupo = Group(id=uuid.uuid4(), tenant_id=DEFAULT_TENANT_ID, name=f"celula-{suf}")
        db.add(grupo)
        db.flush()

        tomy = User(id=uuid.uuid4(), tenant_id=DEFAULT_TENANT_ID, username=f"tmcnally-{suf}",
                    email=f"tmcnally-{suf}@x.test", password_hash="!", role="client",
                    group_id=grupo.id)
        db.add(tomy)
        db.flush()

        presupuesto = Budget(id=uuid.uuid4(), tenant_id=DEFAULT_TENANT_ID, user_id=tomy.id,
                              max_spend_usd="10.0000", current_spend_usd=0,
                              max_tokens=1000000, current_tokens=0, reset_period="monthly")
        db.add(presupuesto)
        db.commit()

        tomy_id, grupo_id, grupo_nombre = tomy.id, grupo.id, grupo.name
        token = create_session_token(str(tomy_id), "client", tomy.username, str(DEFAULT_TENANT_ID))
    finally:
        db.close()

    r = client.post("/api/v1/chat/rag-usage",
                     json={"model": "azure-gpt-5.4-mini", "prompt_tokens": 1000,
                           "completion_tokens": 200, "latency_ms": 1500},
                     headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    costo_esperado = (1000 / 1_000_000) * 0.75 + (200 / 1_000_000) * 4.50
    assert r.json()["cost_usd"] == pytest.approx(costo_esperado, rel=1e-6)

    db = factory()
    try:
        fila = db.query(AuditLog).filter(AuditLog.user_id == tomy_id).order_by(
            AuditLog.timestamp.desc()).first()
        assert fila is not None, "el reporte de uso RAG debe dejar una fila de auditoría"
        assert fila.acted_for_user_id == tomy_id
        assert fila.user_group_id == grupo_id
        assert fila.surface == "rag"
        assert float(fila.cost_usd) == pytest.approx(costo_esperado, rel=1e-6)

        presupuesto_actualizado = db.query(Budget).filter(Budget.user_id == tomy_id).first()
        assert float(presupuesto_actualizado.current_spend_usd) == pytest.approx(
            costo_esperado, rel=1e-6), "el presupuesto de la persona debe descontarse"
    finally:
        db.close()

    # El panel de costos (mismo mecanismo que 043/053) debe verla atribuida a la persona
    # y a su grupo real, no a "sin usuario"/"sin grupo".
    r2 = client.post("/api/v1/chat/rag-usage",
                      json={"model": "azure-gpt-5.4-mini", "prompt_tokens": 500,
                            "completion_tokens": 100},
                      headers={"Authorization": f"Bearer {token}"})
    assert r2.status_code == 200, r2.text


def test_sin_sesion_valida_rechaza(harness):
    client, factory = harness
    r = client.post("/api/v1/chat/rag-usage",
                     json={"model": "azure-gpt-5.4-mini", "prompt_tokens": 10, "completion_tokens": 10})
    assert r.status_code == 401
