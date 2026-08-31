"""Auditoría de eventos de auth con actor (spec 017/US1, T011, FR-016 parcial).

Dos eventos de identidad que hoy ocurrían sin rastro quedan en el canal append-only
existente (``AuditLog`` ``model='auth'``, metadata-only, SIN hash-chain):

- **bootstrap del primer admin**: el primer login de ``admin`` en una instalación
  virgen crea el dueño y deja UNA fila ``auth_bootstrap_admin`` con ``target`` = ese
  admin (``actor`` None: nadie estaba logueado, es el dueño naciendo).
- **cambio de rol**: ``PUT /users/{id}`` que cambia el rol deja UNA fila
  ``auth_role_changed`` con el ``actor`` (QUIÉN lo cambió, FR-004) y ``old``/``new``.

C1 (metadata-only): la fila lleva SÓLO ids y literales de rol — jamás password ni
texto libre. Se afirma explícitamente porque es el mismo canal que audita PII y una
fuga acá sería una regresión silenciosa del contrato de retención.

El motor se mockea (el alta provisiona al motor): lo que se mide es la auditoría, no
la disponibilidad del stack.
"""
import sys
import uuid
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent.parent
for _dir in (_TESTS, _TESTS / "integration"):
    if str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))

from migration_harness import require_postgres  # noqa: E402
from seat_gate_harness import admin_headers, build_app_client, mock_engine  # noqa: E402

require_postgres()

DB = "sentinel_test_auth_events"

# La password que `admin_headers` usa para bootstrapear el admin (dato del harness): la
# nombramos acá para poder afirmar en C1 que NO se filtró a ninguna fila auth.
ADMIN_PASS = "gate-pass-12345"
USER_PASS = "auth-events-user-98765"


def _auth_events(factory, event_type=None):
    """Las entradas ``model='auth'`` (guardian_events[0]), ordenadas por timestamp;
    filtradas por ``event_type`` si se pide. Espeja ``license_audit_events`` del harness."""
    from src.models.audit import AuditLog
    db = factory()
    try:
        rows = (db.query(AuditLog)
                .filter(AuditLog.model == "auth")
                .order_by(AuditLog.timestamp).all())
        entries = [r.guardian_events[0] for r in rows]
        if event_type is not None:
            entries = [e for e in entries if e["event_type"] == event_type]
        return entries
    finally:
        db.close()


def _admin_id(factory):
    from src.models.user import User
    db = factory()
    try:
        return str(db.query(User).filter(User.username == "admin").one().id)
    finally:
        db.close()


def _crear_usuario(client, headers, rol):
    """Alta por la misma vía que la consola. Rol NO-client a propósito: no consume seat,
    así el alta no depende del gate de licencia (spec 021 US2). Devuelve (id, username,
    email): el PUT los re-manda porque ``UserBase`` los exige (username/email/role
    required — el update es 'reemplazá con estos campos', no un PATCH parcial)."""
    nombre = f"u-{uuid.uuid4().hex[:8]}"
    email = f"{nombre}@sentinel.com.ar"
    resp = client.post("/api/v1/users", headers=headers, json={
        "username": nombre, "email": email, "role": rol, "password": USER_PASS,
    })
    assert resp.status_code == 201, resp.text
    return resp.json()["id"], nombre, email


# ── Fixtures ──────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def harness():
    client, factory, cleanup = build_app_client(DB)
    yield client, factory
    cleanup()


@pytest.fixture(autouse=True)
def motor(monkeypatch):
    """Sin esto el POST /users sería 503 (el alta provisiona al motor)."""
    return mock_engine(monkeypatch)


@pytest.fixture(scope="module")
def admin(harness):
    """El primer login de ``admin`` sobre la DB fresca: dispara el bootstrap del dueño."""
    client, _ = harness
    return admin_headers(client)


# ── Bootstrap del primer admin ────────────────────────────────────────────────────


def test_bootstrap_admin_deja_una_fila_con_target(harness, admin):
    """El primer login de ``admin`` en una instalación virgen crea el dueño y deja UNA
    fila ``auth_bootstrap_admin`` cuyo target es ese admin. Sin actor: nadie estaba
    autenticado cuando el dueño nació."""
    _, factory = harness
    eventos = _auth_events(factory, "auth_bootstrap_admin")

    assert len(eventos) == 1, f"esperaba UNA fila de bootstrap, hubo {len(eventos)}"
    ev = eventos[0]
    assert ev["target_user_id"] == _admin_id(factory)
    assert ev["actor_user_id"] is None
    assert ev["old_role"] is None
    assert ev["new_role"] is None


# ── Cambio de rol con actor ────────────────────────────────────────────────────────


def test_cambio_de_rol_deja_una_fila_con_actor_y_old_new(harness, admin):
    """``PUT /users/{id}`` que cambia el rol deja EXACTAMENTE una fila
    ``auth_role_changed`` con el actor (el admin que hizo el PUT) y old/new correctos.
    El ``new_role`` es el canónico (``admin`` legacy → ``tenant_admin``)."""
    client, factory = harness
    uid, uname, email = _crear_usuario(client, admin, "compliance_officer")
    antes = len(_auth_events(factory, "auth_role_changed"))

    resp = client.put(f"/api/v1/users/{uid}", headers=admin,
                      json={"username": uname, "email": email, "role": "admin"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["role"] == "tenant_admin"

    eventos = _auth_events(factory, "auth_role_changed")
    assert len(eventos) == antes + 1, "el cambio de rol debe dejar UNA sola fila"
    ev = eventos[-1]
    assert ev["target_user_id"] == uid
    assert ev["actor_user_id"] == _admin_id(factory)
    assert ev["old_role"] == "compliance_officer"
    assert ev["new_role"] == "tenant_admin"


def test_put_sin_cambio_de_rol_no_audita(harness, admin):
    """El emit está detrás del guard ``nuevo != anterior``: un PUT que toca otro campo
    (o repite el mismo rol) NO debe dejar rastro de ``auth_role_changed``. Sin esto, la
    bitácora se llenaría de cambios que no ocurrieron."""
    client, factory = harness
    uid, uname, email = _crear_usuario(client, admin, "compliance_officer")
    antes = len(_auth_events(factory, "auth_role_changed"))

    base = {"username": uname, "email": email, "role": "compliance_officer"}
    # Cambia is_active con el MISMO rol (role es required en UserBase): no audita.
    r1 = client.put(f"/api/v1/users/{uid}", headers=admin, json={**base, "is_active": False})
    assert r1.status_code == 200, r1.text
    # Reafirma otra vez el MISMO rol (canónico == anterior): tampoco audita.
    r2 = client.put(f"/api/v1/users/{uid}", headers=admin, json=base)
    assert r2.status_code == 200, r2.text

    assert len(_auth_events(factory, "auth_role_changed")) == antes, \
        "un PUT que no cambia el rol no debe emitir auth_role_changed"


# ── C1: metadata-only ──────────────────────────────────────────────────────────────


def test_c1_las_filas_auth_solo_llevan_ids_y_roles(harness, admin):
    """C1: cada fila auth lleva EXACTAMENTE {event_type, actor_user_id, target_user_id,
    old_role, new_role, ts} — sólo ids/literales — y ninguna password que pasó por el
    flujo aparece en ningún valor. El canal es el mismo que audita PII: una fuga acá es
    regresión silenciosa."""
    client, factory = harness
    # Aseguramos ambos tipos presentes (bootstrap ya ocurrió; forzamos un role-change).
    uid, uname, email = _crear_usuario(client, admin, "compliance_officer")
    client.put(f"/api/v1/users/{uid}", headers=admin,
               json={"username": uname, "email": email, "role": "admin"})

    claves = {"event_type", "actor_user_id", "target_user_id", "old_role", "new_role", "ts"}
    secretos = {ADMIN_PASS, USER_PASS}
    eventos = _auth_events(factory)
    assert eventos, "esperaba al menos un evento de auth"
    for ev in eventos:
        assert set(ev) == claves, f"clave inesperada en la fila auth: {set(ev) ^ claves}"
        for campo, valor in ev.items():
            assert valor is None or isinstance(valor, str), \
                f"{campo} no es id/literal: {valor!r}"
            for secreto in secretos:
                assert not (isinstance(valor, str) and secreto in valor), \
                    f"fuga de password en {campo}: {valor!r}"
