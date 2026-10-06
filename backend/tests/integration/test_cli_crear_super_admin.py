"""`python -m src.cli crear-super-admin` contra Postgres real y la app completa.

Contraparte de `tests/unit/test_cli_crear_super_admin.py`: acá el esquema (UNIQUE, CHECK de
rol, RLS), el login real con la contraseña que imprime el comando, la fila de auditoría y
la cadena completa «el primer super_admin da de alta al compliance_officer».
"""
import pytest

from migration_harness import require_postgres
from seat_gate_harness import build_app_client, mock_engine

require_postgres()

DB = "sentinel_test_cli_crear_super_admin"
USUARIO = "owner"
EMAIL = "owner@example.com"


@pytest.fixture(scope="module")
def harness():
    client, factory, cleanup = build_app_client(DB)
    yield client, factory
    cleanup()


@pytest.fixture(autouse=True)
def _motor(monkeypatch):
    return mock_engine(monkeypatch)


def _crear(factory, **kw):
    from src import cli
    db = factory()
    try:
        return cli.crear_super_admin(db, **{"usuario": USUARIO, "email": EMAIL, **kw})
    finally:
        db.close()


def test_crea_el_primero_y_es_idempotente(harness):
    client, factory = harness

    password = _crear(factory)
    assert password
    assert _crear(factory, usuario="otro", email="otro@example.com") is None

    from src.models.user import User
    db = factory()
    try:
        assert db.query(User).filter(User.role == "super_admin").count() == 1
        fila = db.query(User).filter(User.username == USUARIO).one()
        assert fila.must_change_password is True and fila.is_active is True
        assert password not in fila.password_hash
    finally:
        db.close()

    login = client.post("/api/v1/users/login", json={"username": USUARIO, "password": password})
    assert login.status_code == 200, login.text
    assert login.json()["user"]["role"] == "super_admin"
    assert login.json()["user"]["must_change_password"] is True


def test_deja_una_fila_de_auditoria_metadata_only(harness):
    _, factory = harness
    from src.models.audit import AuditLog
    db = factory()
    try:
        eventos = [r.guardian_events[0] for r in db.query(AuditLog).filter(AuditLog.model == "auth")]
    finally:
        db.close()
    boot = [e for e in eventos if e["event_type"] == "auth_bootstrap_super_admin"]
    assert len(boot) == 1
    assert boot[0]["new_role"] == "super_admin" and boot[0]["actor_user_id"] is None
    assert USUARIO not in str(boot[0]) and EMAIL not in str(boot[0])


def test_el_primer_super_admin_da_de_alta_a_un_compliance_officer(harness):
    """El hueco que cierra el comando: sin super_admin nadie puede crear este rol."""
    client, factory = harness
    from src.auth.passwords import hash_password
    from src.models.user import User
    db = factory()
    try:  # el comando ya corrió: dejamos una contraseña conocida para loguear por HTTP
        db.query(User).filter(User.username == USUARIO).update(
            {"password_hash": hash_password("contraseña-de-prueba-2026")})
        db.commit()
    finally:
        db.close()
    login = client.post("/api/v1/users/login",
                        json={"username": USUARIO, "password": "contraseña-de-prueba-2026"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    r = client.post("/api/v1/users", headers=headers, json={
        "username": "auditor", "email": "auditor@example.com", "role": "compliance_officer",
        "password": "ContraseñaValida2026!"})
    assert r.status_code == 201, r.text


def test_un_usuario_existente_no_se_asciende(harness):
    """Aun sin super_admin en el tenant, un username ocupado se rechaza, no se promueve."""
    _, factory = harness
    from src import cli
    from src.models.user import User
    db = factory()
    try:
        db.query(User).filter(User.role == "super_admin").update({"role": "tenant_admin"})
        db.commit()
        with pytest.raises(cli.AltaRechazada):
            cli.crear_super_admin(db, usuario=USUARIO, email="distinto@example.com")
        assert db.query(User).filter(User.role == "super_admin").count() == 0
    finally:
        db.close()
