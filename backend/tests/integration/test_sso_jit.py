"""JIT por email del camino SSO (spec 017 US2, T016, FR-008).

Los tres caminos que nombra la spec (:78-79) más el cuarto que NO nombra y que este
módulo cierra fail-closed:

1. **centinela** (``!seeded-client-no-login``) → se ACTIVA esa misma fila, sin duplicar
   y **sin consumir seat**.
2. **nuevo** → alta ``role='client'`` por el camino actual, **seat gate incluido**.
3. **activo** → sólo login; la fila no se toca.
4. **inactivo NO centinela** → rechazo (una baja administrativa no se revierte por SSO).

Y por encima de los cuatro, el invariante que manda: **jamás se re-asigna rol ni
tenant** (spec:121). Ese es el test que importa: si se rompe, el IdP se vuelve una vía
de escalada de privilegios sobre usuarios que ya existen.

El seat gate se mide contra el gate REAL (``licensing.gate``) con licencias efímeras,
no contra un doble: lo que se afirma es que el camino SSO consume licencia igual que
el alta por UI, y eso sólo vale medido contra el gate de verdad.
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
from seat_gate_harness import (  # noqa: E402
    build_app_client, restore_suite_license, seed_active_seats, set_license,
)

require_postgres()

DB = "basa_test_sso_jit"

SENTINEL = "!seeded-client-no-login"


@pytest.fixture(scope="module")
def entorno():
    client, factory, cleanup = build_app_client(DB)
    yield client, factory
    cleanup()


@pytest.fixture(autouse=True)
def _licencia_limpia():
    """Cada test parte de la licencia dev de la suite (max_seats alto)."""
    restore_suite_license()
    yield
    restore_suite_license()


def _tenant_default():
    from src.models.tenant import DEFAULT_TENANT_ID
    return DEFAULT_TENANT_ID


def _sembrar(factory, *, email, role="client", is_active=True, password_hash=SENTINEL,
             tenant_id=None, username=None):
    from src.models.user import User
    db = factory()
    try:
        user = User(
            tenant_id=tenant_id or _tenant_default(),
            username=username or email,
            email=email,
            password_hash=password_hash,
            role=role,
            is_active=is_active,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user.id
    finally:
        db.close()


def _leer(factory, user_id):
    from src.models.user import User
    db = factory()
    try:
        u = db.query(User).filter(User.id == user_id).first()
        return {
            "id": u.id, "role": u.role, "is_active": u.is_active, "email": u.email,
            "tenant_id": u.tenant_id, "password_hash": u.password_hash,
            "username": u.username,
        }
    finally:
        db.close()


def _contar_por_email(factory, email):
    from src.models.user import User
    db = factory()
    try:
        return db.query(User).filter(User.email == email).count()
    finally:
        db.close()


def _resolver(factory, email, display_name="Nombre Del IdP", tenant_id=None):
    """Ejecuta el JIT como lo hace el callback: buscar → existente|nuevo, en UNA tx."""
    from src.sso.jit import buscar_por_email, crear_jit, resolver_existente
    tenant_id = tenant_id or _tenant_default()
    db = factory()
    try:
        existente = buscar_por_email(db, email, tenant_id)
        if existente is not None:
            user = resolver_existente(db, existente)
        else:
            user = crear_jit(db, email=email, display_name=display_name, tenant_id=tenant_id)
        snap = {"id": user.id, "role": user.role, "is_active": user.is_active}
        db.commit()
        return snap
    finally:
        db.close()


# ── Camino 1: centinela ────────────────────────────────────────────────────────────

def test_centinela_se_activa_sin_duplicar(entorno):
    _, factory = entorno
    email = "centinela-activa@basa.test"
    uid = _sembrar(factory, email=email, is_active=False, password_hash=SENTINEL)

    snap = _resolver(factory, email)

    assert snap["id"] == uid, "debe activar ESA fila, no crear otra"
    assert _contar_por_email(factory, email) == 1, "no duplica"
    assert _leer(factory, uid)["is_active"] is True, "el centinela queda activo"


def test_centinela_activado_sigue_sin_poder_loguear_con_password(entorno):
    """Activar NO le da una credencial local: la identidad la custodia el IdP."""
    from src.auth.passwords import verify_password
    _, factory = entorno
    email = "centinela-sin-password@basa.test"
    uid = _sembrar(factory, email=email, is_active=False, password_hash=SENTINEL)

    _resolver(factory, email)

    fila = _leer(factory, uid)
    assert fila["password_hash"] == SENTINEL, "el hash centinela no se reemplaza"
    assert verify_password(SENTINEL, fila["password_hash"]) is False


def test_centinela_no_consume_seat_aunque_la_licencia_este_agotada(entorno, monkeypatch, tmp_path):
    """«No consume seat por existir» (FR-008) medido contra el gate REAL: con la
    licencia en su tope, el alta nueva sería 402 — el centinela pasa igual."""
    _, factory = entorno
    email = "centinela-sin-seat@basa.test"
    uid = _sembrar(factory, email=email, is_active=False, password_hash=SENTINEL)

    seed_active_seats(factory, 2, prefix="jit-cent")
    set_license(monkeypatch, tmp_path, max_seats=1)

    snap = _resolver(factory, email)  # no debe levantar 402

    assert snap["id"] == uid
    assert _leer(factory, uid)["is_active"] is True


# ── Camino 2: identidad nueva ──────────────────────────────────────────────────────

def test_identidad_nueva_se_crea_como_client(entorno):
    _, factory = entorno
    email = "nuevo-jit@basa.test"

    snap = _resolver(factory, email, display_name="Persona Nueva")

    fila = _leer(factory, snap["id"])
    assert fila["role"] == "client", "el rol de alta JIT es client, jamás uno del IdP"
    assert fila["is_active"] is True
    assert fila["email"] == email


def test_identidad_nueva_nace_sin_password_util(entorno):
    """El alta JIT no puede quedar con una credencial local adivinable ni vacía."""
    from src.auth.passwords import verify_password
    from src.sso.jit import SSO_PASSWORD_SENTINEL
    _, factory = entorno
    email = "nuevo-sin-password@basa.test"

    snap = _resolver(factory, email)

    fila = _leer(factory, snap["id"])
    assert fila["password_hash"] == SSO_PASSWORD_SENTINEL
    for intento in (SSO_PASSWORD_SENTINEL, "", "password", fila["email"]):
        assert verify_password(intento, fila["password_hash"]) is False


def test_alta_nueva_pasa_por_el_seat_gate(entorno, monkeypatch, tmp_path):
    """Con la licencia en su tope, la identidad NUEVA se rechaza y NO deja fila."""
    from fastapi import HTTPException
    _, factory = entorno
    email = "nuevo-sin-licencia@basa.test"

    seed_active_seats(factory, 2, prefix="jit-tope")
    set_license(monkeypatch, tmp_path, max_seats=1)

    with pytest.raises(HTTPException) as exc:
        _resolver(factory, email)

    assert exc.value.status_code in (402, 403), f"esperaba veredicto de licencia, dio {exc.value.status_code}"
    assert _contar_por_email(factory, email) == 0, "una identidad rechazada no deja fila"


# ── Camino 3: usuario activo ───────────────────────────────────────────────────────

def test_usuario_activo_solo_loguea(entorno):
    _, factory = entorno
    email = "ya-activo@basa.test"
    uid = _sembrar(factory, email=email, role="tenant_admin", is_active=True,
                   password_hash="$2b$12$abcdefghijklmnopqrstuv")
    antes = _leer(factory, uid)

    snap = _resolver(factory, email)

    assert snap["id"] == uid
    assert _leer(factory, uid) == antes, "la fila de un usuario activo no se toca"


# ── Camino 4: inactivo NO centinela (fail-closed, no nombrado por la spec) ─────────

def test_inactivo_no_centinela_es_rechazado(entorno):
    """Una baja administrativa NO se revierte entrando por el IdP."""
    from fastapi import HTTPException
    _, factory = entorno
    email = "dado-de-baja@basa.test"
    uid = _sembrar(factory, email=email, is_active=False,
                   password_hash="$2b$12$abcdefghijklmnopqrstuv")

    with pytest.raises(HTTPException) as exc:
        _resolver(factory, email)

    assert exc.value.status_code == 403
    assert _leer(factory, uid)["is_active"] is False, "sigue dado de baja"


# ── El invariante que manda: jamás re-asignar rol ni tenant ────────────────────────

@pytest.mark.parametrize("rol_local", ["lectura", "client", "compliance_officer", "tenant_admin"])
def test_jamas_reasigna_rol(entorno, rol_local):
    """Entrar por SSO no cambia el rol que puso el admin local — en NINGÚN rol.

    Es el test de escalada de privilegios: si el JIT escribiera ``role``, un claim del
    IdP (o el default ``client``) podría degradar o promover a alguien existente.
    """
    _, factory = entorno
    email = f"rol-{rol_local}@basa.test"
    uid = _sembrar(factory, email=email, role=rol_local, is_active=True,
                   password_hash="$2b$12$abcdefghijklmnopqrstuv")

    _resolver(factory, email)

    assert _leer(factory, uid)["role"] == rol_local


def test_centinela_conserva_su_rol_al_activarse(entorno):
    """Ni siquiera el camino que SÍ escribe (activación) toca el rol."""
    _, factory = entorno
    email = "centinela-officer@basa.test"
    uid = _sembrar(factory, email=email, role="compliance_officer", is_active=False,
                   password_hash=SENTINEL)

    _resolver(factory, email)

    fila = _leer(factory, uid)
    assert fila["role"] == "compliance_officer", "activar no re-asigna rol"
    assert fila["is_active"] is True


def test_matching_por_email_es_por_tenant(entorno):
    """El email es único POR tenant: un match sin filtrar tenant devolvería fila ajena
    y el SSO del tenant A emitiría sesión sobre el User de B."""
    from src.sso.jit import buscar_por_email
    from src.models.tenant import Tenant
    _, factory = entorno
    email = "mismo-email@basa.test"

    db = factory()
    try:
        otro = Tenant(id=uuid.uuid4(), slug=f"otro-{uuid.uuid4().hex[:8]}", name="Otro")
        db.add(otro)
        db.commit()
        otro_id = otro.id
    finally:
        db.close()

    uid_default = _sembrar(factory, email=email, role="client",
                           password_hash="$2b$12$abcdefghijklmnopqrstuv")
    uid_otro = _sembrar(factory, email=email, role="tenant_admin", tenant_id=otro_id,
                        username=f"{email}-otro", password_hash="$2b$12$abcdefghijklmnopqrstuv")

    db = factory()
    try:
        hallado_default = buscar_por_email(db, email, _tenant_default())
        hallado_otro = buscar_por_email(db, email, otro_id)
    finally:
        db.close()

    assert hallado_default.id == uid_default
    assert hallado_otro.id == uid_otro
    assert uid_default != uid_otro
