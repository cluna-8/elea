"""Alta y cambio de rol a `compliance_officer`/`super_admin` por HTTP real: SÓLO `super_admin`.

Contraparte con Postgres de `tests/unit/test_roles_cumplimiento_solo_super_admin.py`: acá
corre la app completa (sesión JWT real, `require_role`, migraciones a head, auditoría).
Cubre el alta (`POST`), el cambio de rol (`PUT`/`PATCH`), que el resto de los roles no
cambie, que la fila de auditoría del cambio exista y que el bootstrap del primer admin siga
igual.
"""
import uuid

import pytest

from migration_harness import require_postgres
from seat_gate_harness import (admin_headers, build_app_client, headers_for_role,
                               mock_engine)
from src.auth.matrix import Rol

require_postgres()

DB = "sentinel_test_alta_roles_cumplimiento"
CLAVE = "ContraseñaValida2026!"
PROTEGIDOS = ["compliance_officer", "super_admin"]


@pytest.fixture(scope="module")
def harness():
    client, factory, cleanup = build_app_client(DB)
    admin = admin_headers(client)  # bootstrap: el primer admin es tenant_admin
    super_admin = headers_for_role(client, factory, Rol.SUPER_ADMIN)
    yield client, factory, admin, super_admin
    cleanup()


@pytest.fixture(autouse=True)
def _motor(monkeypatch):
    return mock_engine(monkeypatch)


def _payload(role):
    nombre = f"u-{uuid.uuid4().hex[:8]}"
    return {"username": nombre, "email": f"{nombre}@sentinel.com.ar", "role": role,
            "password": CLAVE}


def _existe(factory, username):
    from src.models.user import User
    db = factory()
    try:
        return db.query(User).filter(User.username == username).count() == 1
    finally:
        db.close()


@pytest.mark.parametrize("rol", PROTEGIDOS)
def test_alta_por_tenant_admin_da_403_y_no_crea_el_usuario(harness, rol):
    client, factory, admin, _ = harness
    body = _payload(rol)
    r = client.post("/api/v1/users", headers=admin, json=body)
    assert r.status_code == 403, r.text
    assert "super_admin" in r.json()["detail"]
    assert not _existe(factory, body["username"])


@pytest.mark.parametrize("rol", PROTEGIDOS)
def test_alta_por_super_admin_da_201(harness, rol):
    client, _, _, super_admin = harness
    r = client.post("/api/v1/users", headers=super_admin, json=_payload(rol))
    assert r.status_code == 201, r.text
    assert r.json()["role"] == rol


@pytest.mark.parametrize("rol", ["tenant_admin", "admin", "lectura"])
def test_alta_del_resto_de_los_roles_por_tenant_admin_sigue_igual(harness, rol):
    client, _, admin, _ = harness
    r = client.post("/api/v1/users", headers=admin, json=_payload(rol))
    assert r.status_code == 201, r.text


def _crear_lectura(client, super_admin):
    body = _payload("lectura")
    r = client.post("/api/v1/users", headers=super_admin, json=body)
    assert r.status_code == 201, r.text
    return r.json()["id"], body


@pytest.mark.parametrize("rol", PROTEGIDOS)
def test_patch_a_rol_protegido_por_tenant_admin_da_403_y_no_cambia_el_rol(harness, rol):
    client, _, admin, super_admin = harness
    uid, _ = _crear_lectura(client, super_admin)
    r = client.patch(f"/api/v1/users/{uid}", headers=admin, json={"role": rol})
    assert r.status_code == 403, r.text
    assert client.get(f"/api/v1/users/{uid}", headers=admin).json()["role"] == "lectura"


@pytest.mark.parametrize("rol", PROTEGIDOS)
def test_put_a_rol_protegido_por_tenant_admin_da_403_y_no_cambia_el_rol(harness, rol):
    client, _, admin, super_admin = harness
    uid, body = _crear_lectura(client, super_admin)
    r = client.put(f"/api/v1/users/{uid}", headers=admin, json={
        "username": body["username"], "email": body["email"], "role": rol})
    assert r.status_code == 403, r.text
    assert client.get(f"/api/v1/users/{uid}", headers=admin).json()["role"] == "lectura"


@pytest.mark.parametrize("rol", PROTEGIDOS)
def test_patch_y_put_por_super_admin_dan_200(harness, rol):
    client, _, _, super_admin = harness
    uid, body = _crear_lectura(client, super_admin)
    r = client.patch(f"/api/v1/users/{uid}", headers=super_admin, json={"role": rol})
    assert r.status_code == 200, r.text
    assert r.json()["role"] == rol
    r = client.put(f"/api/v1/users/{uid}", headers=super_admin, json={
        "username": body["username"], "email": body["email"], "role": "lectura"})
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "lectura"


def test_el_cambio_de_rol_por_tenant_admin_a_los_demas_roles_sigue_igual(harness):
    client, _, admin, super_admin = harness
    uid, _ = _crear_lectura(client, super_admin)
    r = client.patch(f"/api/v1/users/{uid}", headers=admin, json={"role": "client"})
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "client"


def test_editar_otro_campo_de_quien_ya_es_auditor_no_se_bloquea(harness):
    """«No se tocan datos»: el rol vigente no se re-asigna, así que no cae en la guarda."""
    client, _, admin, super_admin = harness
    body = _payload("compliance_officer")
    uid = client.post("/api/v1/users", headers=super_admin, json=body).json()["id"]
    r = client.put(f"/api/v1/users/{uid}", headers=admin, json={
        "username": body["username"], "email": body["email"],
        "role": "compliance_officer", "is_active": True})
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "compliance_officer"


def test_el_cambio_por_super_admin_deja_el_evento_de_auditoria(harness):
    from src.models.audit import AuditLog
    client, factory, _, super_admin = harness
    uid, _ = _crear_lectura(client, super_admin)
    assert client.patch(f"/api/v1/users/{uid}", headers=super_admin,
                        json={"role": "compliance_officer"}).status_code == 200
    db = factory()
    try:
        eventos = [r.guardian_events[0] for r in
                   db.query(AuditLog).filter(AuditLog.model == "auth").all()]
    finally:
        db.close()
    assert any(e["event_type"] == "auth_role_changed" and e["target_user_id"] == uid
               and e["new_role"] == "compliance_officer" for e in eventos)


def test_el_bootstrap_del_primer_admin_sigue_igual():
    """La guarda vive en `POST|PUT|PATCH /users`: el login que crea al primer admin sobre
    una instalación sin dueño no pasa por ahí y sigue dando `tenant_admin`."""
    client, _, cleanup = build_app_client("sentinel_test_alta_roles_bootstrap")
    try:
        r = client.post("/api/v1/users/login",
                        json={"username": "admin", "password": "gate-pass-12345"})
        assert r.status_code == 200, r.text
        assert r.json()["user"]["role"] == "tenant_admin"
    finally:
        cleanup()
