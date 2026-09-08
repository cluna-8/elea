"""`GET /users` excluye cuentas de servicio por default (spec 043 US4, T045, contrato 4) —
verificación real: sin `include_service`, no aparecen `svc.*`; con `?include_service=true`,
aparecen con `purpose`."""
import uuid

import pytest

from migration_harness import require_postgres
from seat_gate_harness import admin_headers, build_app_client

require_postgres()

DB = "sentinel_test_users_service_filter_043"


@pytest.fixture(scope="module")
def harness():
    client, factory, cleanup = build_app_client(DB)
    headers = admin_headers(client)
    yield client, factory, headers
    cleanup()


def _seed_service_account(factory, username):
    from src.models.tenant import DEFAULT_TENANT_ID
    from src.models.user import User
    db = factory()
    try:
        u = User(id=uuid.uuid4(), tenant_id=DEFAULT_TENANT_ID, username=username,
                email=f"{uuid.uuid4().hex[:6]}@elea-internal.com", password_hash="!", role="client",
                account_type="service")
        db.add(u)
        db.commit()
    finally:
        db.close()


def test_por_default_no_aparecen_cuentas_de_servicio(harness):
    client, factory, headers = harness
    _seed_service_account(factory, f"svc.rag-masking-{uuid.uuid4().hex[:6]}")

    r = client.get("/api/v1/users", headers=headers)
    assert r.status_code == 200, r.text
    assert all(not u["username"].startswith("svc.") for u in r.json())


def test_con_include_service_apareces_con_purpose(harness):
    client, factory, headers = harness
    username = f"svc.rag-masking-{uuid.uuid4().hex[:6]}"
    _seed_service_account(factory, username)

    r = client.get("/api/v1/users", params={"include_service": "true"}, headers=headers)
    assert r.status_code == 200, r.text
    fila = next(u for u in r.json() if u["username"] == username)
    assert fila["account_type"] == "service"
    assert "purpose" in fila and fila["purpose"]


def test_usuario_persona_normal_no_lleva_purpose(harness):
    client, factory, headers = harness
    r = client.get("/api/v1/users", params={"include_service": "true"}, headers=headers)
    assert r.status_code == 200
    admin_row = next(u for u in r.json() if u["role"] in ("tenant_admin", "admin"))
    assert admin_row.get("account_type", "person") == "person"
    assert "purpose" not in admin_row
