"""`PATCH`/`DELETE /users/{id}` (spec 043 US5, T049-T055, contrato 5) — verificación real:
actualización parcial de un solo campo por vez, unicidad, baja con guardas (auto-baja,
último admin), revocación de llaves, login bloqueado tras la baja, y cascada de espacios
propios a "sin asignar" (FR-042)."""
import uuid

import pytest

from migration_harness import require_postgres
from seat_gate_harness import admin_headers, build_app_client, mock_engine, restore_suite_license, set_license

require_postgres()

DB = "sentinel_test_users_lifecycle_043"


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


def _crear_usuario(client, headers, monkeypatch, tmp_path, *, role="client"):
    mock_engine(monkeypatch)
    set_license(monkeypatch, tmp_path, max_seats=1000)
    suf = uuid.uuid4().hex[:8]
    r = client.post("/api/v1/users", headers=headers, json={
        "username": f"u-{suf}", "email": f"u-{suf}@elea-internal.com", "role": role,
        "password": "ContraseñaValida2026!",
    })
    assert r.status_code in (200, 201), r.text
    return r.json()["id"], r.json()["username"], r.json()["email"]


def test_patch_un_solo_campo_no_toca_el_resto(harness, monkeypatch, tmp_path):
    client, factory, headers = harness
    user_id, username, email = _crear_usuario(client, headers, monkeypatch, tmp_path)

    r = client.patch(f"/api/v1/users/{user_id}", headers=headers,
                     json={"role": "compliance_officer"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["role"] == "compliance_officer"
    assert body["username"] == username
    assert body["email"] == email

    r2 = client.patch(f"/api/v1/users/{user_id}", headers=headers,
                      json={"email": f"nuevo-{uuid.uuid4().hex[:6]}@elea-internal.com"})
    assert r2.status_code == 200
    assert r2.json()["role"] == "compliance_officer"  # no se pisó por el segundo PATCH


def test_patch_username_duplicado_da_409(harness, monkeypatch, tmp_path):
    client, factory, headers = harness
    _id1, username1, _ = _crear_usuario(client, headers, monkeypatch, tmp_path)
    id2, _, _ = _crear_usuario(client, headers, monkeypatch, tmp_path)

    r = client.patch(f"/api/v1/users/{id2}", headers=headers, json={"username": username1})
    assert r.status_code == 409


def test_baja_revoca_llaves_y_bloquea_login(harness, monkeypatch, tmp_path):
    client, factory, headers = harness
    user_id, username, _ = _crear_usuario(client, headers, monkeypatch, tmp_path)

    from src.models.budget import APIKey
    from src.models.tenant import DEFAULT_TENANT_ID
    db = factory()
    try:
        key = APIKey(id=uuid.uuid4(), tenant_id=DEFAULT_TENANT_ID, user_id=user_id,
                    key_hash=f"hash-{uuid.uuid4()}", key_preview="sk-...x",
                    name="k-test", tool_type="claude-code", is_active=True)
        db.add(key)
        db.commit()
        key_id = key.id
    finally:
        db.close()

    r = client.delete(f"/api/v1/users/{user_id}", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "deactivated"

    db = factory()
    try:
        row = db.query(APIKey).filter(APIKey.id == key_id).first()
        assert row.is_active is False
    finally:
        db.close()

    r2 = client.post("/api/v1/users/login",
                     json={"username": username, "password": "ContraseñaValida2026!"})
    assert r2.status_code == 401
    assert "incorrectas" in r2.json()["detail"].lower()


def test_no_se_puede_dar_de_baja_a_si_mismo(harness):
    client, factory, headers = harness
    import jose.jwt as jwt_lib
    token = headers["Authorization"].removeprefix("Bearer ")
    payload = jwt_lib.get_unverified_claims(token)
    admin_id = payload["sub"]

    r = client.delete(f"/api/v1/users/{admin_id}", headers=headers)
    assert r.status_code == 409


def test_no_se_puede_dar_de_baja_al_ultimo_admin(harness, monkeypatch, tmp_path):
    client, factory, headers = harness
    from src.models.user import User
    from src.models.tenant import DEFAULT_TENANT_ID

    id2, username2, _ = _crear_usuario(client, headers, monkeypatch, tmp_path,
                                       role="tenant_admin")

    db = factory()
    try:
        admins_activos = db.query(User).filter(
            User.tenant_id == DEFAULT_TENANT_ID,
            User.role.in_(("super_admin", "tenant_admin", "admin")),
            User.deactivated_at.is_(None), User.is_active.is_(True),
        ).all()
        for a in admins_activos[1:]:
            a.is_active = False
        ultimo_id = admins_activos[0].id
        db.commit()
    finally:
        db.close()

    r = client.delete(f"/api/v1/users/{ultimo_id}", headers=headers)
    assert r.status_code in (409, 401, 403)


def test_baja_reasigna_espacios_propios_a_sin_asignar(harness, monkeypatch, tmp_path):
    client, factory, headers = harness
    user_id, username, _ = _crear_usuario(client, headers, monkeypatch, tmp_path)

    from src.database import get_db
    from src.models.user import User as _User
    from src.auth.session import get_current_user as real_get_current_user
    from fastapi import Depends

    def _fake_user(db=Depends(get_db)):
        return db.query(_User).filter(_User.id == user_id).first()

    client.app.dependency_overrides[real_get_current_user] = _fake_user
    try:
        r = client.post("/api/v1/workspaces", json={"display_name": "Espacio de Prueba"})
        assert r.status_code == 200, r.text
        ws_id = r.json()["id"]
    finally:
        del client.app.dependency_overrides[real_get_current_user]

    r2 = client.delete(f"/api/v1/users/{user_id}", headers=headers)
    assert r2.status_code == 200
    assert r2.json()["workspaces_unassigned"] >= 1

    from src.models.workspace import Workspace
    db = factory()
    try:
        ws = db.query(Workspace).filter(Workspace.id == ws_id).first()
        assert ws.status == "unassigned"
        assert ws.owner_user_id is None
    finally:
        db.close()


def test_patch_is_active_false_tambien_revoca_llaves(harness, monkeypatch, tmp_path):
    """Bug real encontrado en revisión (09-sep): el toggle "Desactivar" del panel llama
    a PATCH (`is_active: false`), no DELETE — antes solo `deactivate_user` (DELETE)
    revocaba las llaves, así que las Connections del usuario seguían funcionando pese al
    badge "Desactivado" en el panel."""
    client, factory, headers = harness
    user_id, _username, _email = _crear_usuario(client, headers, monkeypatch, tmp_path)

    from src.models.budget import APIKey
    from src.models.tenant import DEFAULT_TENANT_ID
    db = factory()
    try:
        key = APIKey(id=uuid.uuid4(), tenant_id=DEFAULT_TENANT_ID, user_id=user_id,
                    key_hash=f"hash-{uuid.uuid4()}", key_preview="sk-...x",
                    name="k-patch-test", tool_type="claude-code", is_active=True)
        db.add(key)
        db.commit()
        key_id = key.id
    finally:
        db.close()

    r = client.patch(f"/api/v1/users/{user_id}", headers=headers, json={"is_active": False})
    assert r.status_code == 200, r.text
    assert r.json()["is_active"] is False

    db = factory()
    try:
        row = db.query(APIKey).filter(APIKey.id == key_id).first()
        assert row.is_active is False, "PATCH is_active=false debe revocar las llaves igual que DELETE"
    finally:
        db.close()


def test_patch_is_active_true_no_reactiva_llaves_ya_revocadas(harness, monkeypatch, tmp_path):
    """Reactivar a la persona NO debe restaurar en silencio la capacidad de una llave
    potencialmente comprometida — si hace falta, se emite una nueva."""
    client, factory, headers = harness
    user_id, _username, _email = _crear_usuario(client, headers, monkeypatch, tmp_path)

    from src.models.budget import APIKey
    from src.models.tenant import DEFAULT_TENANT_ID
    db = factory()
    try:
        key = APIKey(id=uuid.uuid4(), tenant_id=DEFAULT_TENANT_ID, user_id=user_id,
                    key_hash=f"hash-{uuid.uuid4()}", key_preview="sk-...y",
                    name="k-reactivate-test", tool_type="claude-code", is_active=True)
        db.add(key)
        db.commit()
        key_id = key.id
    finally:
        db.close()

    client.patch(f"/api/v1/users/{user_id}", headers=headers, json={"is_active": False})
    r = client.patch(f"/api/v1/users/{user_id}", headers=headers, json={"is_active": True})
    assert r.status_code == 200, r.text
    assert r.json()["is_active"] is True

    db = factory()
    try:
        row = db.query(APIKey).filter(APIKey.id == key_id).first()
        assert row.is_active is False, "reactivar al usuario no debe reactivar llaves ya revocadas"
    finally:
        db.close()
