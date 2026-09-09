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


def test_crear_usuario_svc_via_api_queda_marcado_como_cuenta_de_servicio(harness, monkeypatch, tmp_path):
    """Bug real encontrado en una prueba de punta a punta en vivo (09-sep): la migración
    018 solo hace backfill de `account_type='service'` para usuarios `svc.%` que YA
    existían al migrar — cualquier cuenta de servicio creada DESPUÉS (cada instalación
    fresca de `install.sh` crea las suyas en su primer arranque) quedaba con
    `account_type='person'` por default, así que reaparecía en la tabla principal de
    personas — el bug original que reportó Tomás Mc Nally, de vuelta en instalaciones
    nuevas. `POST /users` ahora detecta el prefijo `svc.` y lo marca en la creación."""
    from seat_gate_harness import mock_engine, set_license
    client, factory, headers = harness
    mock_engine(monkeypatch)
    set_license(monkeypatch, tmp_path, max_seats=1000)

    suf = uuid.uuid4().hex[:8]
    r = client.post("/api/v1/users", headers=headers, json={
        "username": f"svc.verificacion-{suf}", "email": f"svc.verificacion-{suf}@elea-internal.com",
        "role": "client", "password": "ContraseñaValida2026!",
    })
    assert r.status_code in (200, 201), r.text
    user_id = r.json()["id"]

    db = factory()
    try:
        from src.models.user import User
        u = db.query(User).filter(User.id == user_id).first()
        assert u.account_type == "service"
    finally:
        db.close()

    # Y por lo tanto no aparece en la tabla principal (sin include_service).
    r2 = client.get("/api/v1/users", headers=headers)
    assert r2.status_code == 200
    assert not any(row["username"] == f"svc.verificacion-{suf}" for row in r2.json())
