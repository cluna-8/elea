"""Smoke de regresión de la APP contra el esquema migrado (SC-002, spec 013).

Hallazgo de review: SC-002 ("0 queries de la app rompen") no tenía cobertura
automatizada a nivel endpoint. Acá se monta la app FastAPI real con `get_db`
overrideado a la DB de test migrada (009 + seed legacy → head) y se ejercitan los
flujos heredados clave: bootstrap de login, listado de usuarios gateado por el shim
RBAC, creación de usuario con rol legacy, y listado de keys.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from migration_harness import migrated_legacy_db, require_postgres

require_postgres()

DB = "basa_test_app_smoke"


ADMIN_PASSWORD = "smoke-pass-12345"


@pytest.fixture(scope="module")
def factory():
    engine = migrated_legacy_db(DB)
    yield sessionmaker(autocommit=False, autoflush=False, bind=engine)
    engine.dispose()


@pytest.fixture(scope="module")
def client(factory):
    from src.main import app
    from src.database import get_db

    def override_get_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as tc:
        yield tc
    app.dependency_overrides.clear()


@pytest.fixture(scope="module")
def admin_token(client, factory):
    """El admin se siembra por DB, NO por el bootstrap del login.

    El bootstrap sólo corre sobre una instalación virgen y esta base arranca con el seed
    legacy: que el login de un 'admin' inexistente ya no se cree un tenant_admin sobre una
    tabla poblada es exactamente el agujero que se cerró. El seed trae 'legacy-admin', pero
    con ``password_hash='x'``, que no verifica en ningún formato.
    """
    from src.api.users import hash_password
    from src.models.user import User

    db = factory()
    try:
        db.add(User(username="admin", email="admin@basa.com.ar",
                    password_hash=hash_password(ADMIN_PASSWORD),
                    role="tenant_admin", is_active=True))
        db.commit()
    finally:
        db.close()

    resp = client.post("/api/v1/users/login",
                       json={"username": "admin", "password": ADMIN_PASSWORD})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["user"]["role"] == "tenant_admin"
    return body["access_token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_admin_login_and_role_canonical(admin_token):
    assert admin_token


def test_list_users_via_legacy_admin_gate(client, admin_token):
    """require_role('admin') debe aceptar al tenant_admin migrado (shim RBAC)."""
    resp = client.get("/api/v1/users", headers=_auth(admin_token))
    assert resp.status_code == 200, resp.text
    usernames = {u["username"] for u in resp.json()}
    assert {"legacy-admin", "legacy-officer", "legacy-clinician"}.issubset(usernames)


def test_list_keys_via_legacy_admin_gate(client, admin_token):
    resp = client.get("/api/v1/keys", headers=_auth(admin_token))
    assert resp.status_code == 200, resp.text
    assert len(resp.json()) == 3  # linked + dup(desactivada) + huérfana


def test_create_user_accepts_legacy_role_payload(client, admin_token):
    """El frontend heredado manda role='clinician': el borde lo normaliza al enum
    canónico conservando la etiqueta (no 500 por ck_users_role)."""
    resp = client.post("/api/v1/users", headers=_auth(admin_token), json={
        "username": "smoke-clinician",
        "email": "smoke-clinician@basa.com.ar",
        "role": "clinician",
        "password": "clave-de-alta-valida",
    })
    # 503 si el motor no está accesible desde el test runner: el INSERT local ya
    # se validó antes de llamar al motor; lo que NO puede pasar es un 500 por CHECK.
    assert resp.status_code in (201, 503), resp.text
    if resp.status_code == 201:
        assert resp.json()["role"] == "client"


def test_create_user_rejects_unknown_role_with_422(client, admin_token):
    resp = client.post("/api/v1/users", headers=_auth(admin_token), json={
        "username": "smoke-bad", "email": "smoke-bad@basa.com.ar",
        "role": "hacker", "password": "clave-de-alta-valida",
    })
    assert resp.status_code == 422


def test_update_user_normalizes_legacy_role(client, admin_token):
    users = client.get("/api/v1/users", headers=_auth(admin_token)).json()
    officer = next(u for u in users if u["username"] == "legacy-officer")
    resp = client.put(f"/api/v1/users/{officer['id']}", headers=_auth(admin_token), json={
        "username": "legacy-officer", "email": "legacy-officer@legacy.basa.com.ar",
        "role": "developer",
    })
    assert resp.status_code == 200, resp.text
    assert resp.json()["role"] == "client"
