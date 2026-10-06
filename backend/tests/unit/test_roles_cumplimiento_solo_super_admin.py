"""Alta y cambio de rol a `compliance_officer`/`super_admin`: SÓLO un `super_admin`.

Hasta acá `POST /users` y `PUT|PATCH /users/{id}` exigían sólo `require_role("admin")`, y
`effective_roles` expande `tenant_admin` a `admin`: el administrador de empresa podía crear
(o promover a) un `compliance_officer` —quien relaja la postura de residencia— o un
`super_admin`, o sea designarse a sí mismo a quien controla lo que él no puede tocar.

Unit tests puros, sin DB ni red: los handlers se llaman con un `Session` doble (las ramas
que se miden resuelven ANTES de cualquier escritura) y la puerta HTTP se ejerce con
`TestClient` sobre el router real, con `get_current_user`/`get_db` sustituidos. Lo que
necesita Postgres (alta completa con bcrypt y motor) lo cubre
`tests/integration/test_alta_roles_cumplimiento.py`.
"""
import asyncio
import uuid
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from src.api import users as users_api
from src.auth.rbac import exigir_super_admin_para_rol
from src.auth.session import get_current_user
from src.database import get_db
from src.models.user import ROLES_SOLO_SUPER_ADMIN, User, VALID_ROLES
from src.schemas.user import UserBase, UserCreate, UserPatch

PROTEGIDOS = ["compliance_officer", "super_admin"]
LIBRES = ["tenant_admin", "client", "lectura", "admin", "clinician", "developer"]


def _actor(role):
    return User(id=uuid.uuid4(), username=f"actor-{role}", email=f"{role}@t.example",
                password_hash="x", role=role)


def _db(*, existente=None):
    """`Session` doble: toda consulta devuelve `existente` (None = no hay duplicado/grupo)."""
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = existente
    return db


def _alta(role):
    return UserCreate(username="nuevo", email="nuevo@t.example", role=role,
                      password="ContraseñaValida2026!")


# ── La constante: el conjunto protegido es exactamente el pedido ────────────────────


def test_el_conjunto_protegido_son_los_dos_roles_de_cumplimiento():
    assert ROLES_SOLO_SUPER_ADMIN == frozenset(PROTEGIDOS)
    assert ROLES_SOLO_SUPER_ADMIN <= VALID_ROLES


# ── La guarda ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("rol", PROTEGIDOS)
def test_guarda_tenant_admin_recibe_403_con_mensaje_claro(rol):
    with pytest.raises(HTTPException) as exc:
        exigir_super_admin_para_rol(_actor("tenant_admin"), rol)
    assert exc.value.status_code == 403
    assert rol in exc.value.detail and "super_admin" in exc.value.detail


@pytest.mark.parametrize("rol", PROTEGIDOS)
def test_guarda_super_admin_pasa(rol):
    exigir_super_admin_para_rol(_actor("super_admin"), rol)


@pytest.mark.parametrize("rol", LIBRES)
@pytest.mark.parametrize("actor_rol", ["tenant_admin", "super_admin"])
def test_guarda_el_resto_de_los_roles_no_cambia(actor_rol, rol):
    exigir_super_admin_para_rol(_actor(actor_rol), rol)


@pytest.mark.parametrize("actor_rol", ["compliance_officer", "client", "lectura"])
def test_guarda_no_confunde_equivalencia_con_identidad(actor_rol):
    """La guarda mira el rol REAL del actor, no `effective_roles`: éste expande
    `tenant_admin` y `super_admin` a `admin` y no distinguiría a uno del otro."""
    with pytest.raises(HTTPException):
        exigir_super_admin_para_rol(_actor(actor_rol), "super_admin")


# ── Alta: `_validar_alta` (fase DB, corre antes del bcrypt) ─────────────────────────


@pytest.mark.parametrize("rol", PROTEGIDOS)
def test_alta_por_tenant_admin_da_403(rol):
    with pytest.raises(HTTPException) as exc:
        users_api._validar_alta(_db(), _alta(rol), _actor("tenant_admin"))
    assert exc.value.status_code == 403


@pytest.mark.parametrize("rol", PROTEGIDOS)
def test_alta_por_super_admin_pasa(rol):
    role, label = users_api._validar_alta(_db(), _alta(rol), _actor("super_admin"))
    assert (role, label) == (rol, None)


@pytest.mark.parametrize("rol,esperado", [
    ("tenant_admin", ("tenant_admin", None)),
    ("admin", ("tenant_admin", None)),
    ("lectura", ("lectura", None)),
    ("clinician", ("client", "clinician")),
])
def test_alta_del_resto_de_los_roles_sigue_igual_para_tenant_admin(rol, esperado,
                                                                    monkeypatch):
    # `clinician` normaliza a `client` y pasa por el gate de licencia: no es lo que se mide.
    monkeypatch.setattr(users_api, "enforce_seat_gate", lambda *a, **k: None)
    assert users_api._validar_alta(_db(), _alta(rol), _actor("tenant_admin")) == esperado


def test_alta_con_rol_invalido_sigue_dando_422_no_403():
    with pytest.raises(HTTPException) as exc:
        users_api._validar_alta(_db(), _alta("hacker"), _actor("tenant_admin"))
    assert exc.value.status_code == 422


# ── Alta por HTTP: la puerta real, sin Postgres (el 403 sale antes de tocar la DB) ──


def _cliente(actor):
    app = FastAPI()
    app.include_router(users_api.router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = lambda: actor
    app.dependency_overrides[get_db] = lambda: _db()
    return TestClient(app)


@pytest.mark.parametrize("rol", PROTEGIDOS)
def test_post_users_por_tenant_admin_da_403_por_http(rol):
    r = _cliente(_actor("tenant_admin")).post("/api/v1/users", json={
        "username": "nuevo", "email": "nuevo@t.example", "role": rol,
        "password": "ContraseñaValida2026!"})
    assert r.status_code == 403, r.text
    assert "super_admin" in r.json()["detail"]


def test_post_users_sigue_exigiendo_admin_a_quien_no_lo_es():
    """La guarda nueva se SUMA a `require_role("admin")`, no lo reemplaza."""
    r = _cliente(_actor("client")).post("/api/v1/users", json={
        "username": "nuevo", "email": "nuevo@t.example", "role": "lectura",
        "password": "ContraseñaValida2026!"})
    assert r.status_code == 403
    assert "Acción no permitida para el rol 'client'" in r.json()["detail"]


def test_create_user_por_tenant_admin_no_llega_a_hashear_ni_al_motor(monkeypatch):
    """El 403 es de la fase DB: ni bcrypt ni el motor se tocan para un alta rechazada."""
    hash_mock = MagicMock()
    motor = MagicMock()
    monkeypatch.setattr(users_api, "hash_password_async", hash_mock)
    monkeypatch.setattr(users_api.ai_engine_client, "create_user", motor)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(users_api.create_user(_alta("super_admin"), actor=_actor("tenant_admin"),
                                          db=_db()))
    assert exc.value.status_code == 403
    hash_mock.assert_not_called()
    motor.assert_not_called()


# ── Cambio de rol: PUT y PATCH ──────────────────────────────────────────────────────


def _objetivo(role):
    return User(id=uuid.uuid4(), tenant_id=uuid.uuid4(), username="objetivo",
                email="objetivo@t.example", password_hash="x", role=role, is_active=True)


def _db_con(objetivo):
    """El 1.er `.first()` (el usuario objetivo) lo encuentra; los siguientes (chequeos de
    unicidad de PATCH) no encuentran duplicado."""
    db = MagicMock()
    db.query.return_value.filter.return_value.first.side_effect = [objetivo] + [None] * 5
    return db


def _put(role):
    return UserBase(username="objetivo", email="objetivo@t.example", role=role)


@pytest.fixture
def eventos(monkeypatch):
    emit = MagicMock()
    monkeypatch.setattr(users_api, "emit_auth_event", emit)
    return emit


@pytest.mark.parametrize("rol", PROTEGIDOS)
def test_put_a_rol_protegido_por_tenant_admin_da_403_sin_mutar(rol, eventos):
    objetivo, db = _objetivo("client"), None
    db = _db_con(objetivo)
    with pytest.raises(HTTPException) as exc:
        users_api.update_user(objetivo.id, _put(rol), actor=_actor("tenant_admin"), db=db)
    assert exc.value.status_code == 403
    assert objetivo.role == "client"
    db.commit.assert_not_called()
    eventos.assert_not_called()


@pytest.mark.parametrize("rol", PROTEGIDOS)
def test_patch_a_rol_protegido_por_tenant_admin_da_403_sin_mutar(rol, eventos):
    objetivo = _objetivo("client")
    db = _db_con(objetivo)
    with pytest.raises(HTTPException) as exc:
        users_api.patch_user(objetivo.id, UserPatch(role=rol), actor=_actor("tenant_admin"),
                             db=db)
    assert exc.value.status_code == 403
    assert objetivo.role == "client"
    db.commit.assert_not_called()
    eventos.assert_not_called()


@pytest.mark.parametrize("rol", PROTEGIDOS)
def test_put_y_patch_a_rol_protegido_por_super_admin_pasan_y_se_auditan(rol, eventos):
    for handler in ("put", "patch"):
        eventos.reset_mock()
        objetivo = _objetivo("client")
        db = _db_con(objetivo)
        actor = _actor("super_admin")
        if handler == "put":
            users_api.update_user(objetivo.id, _put(rol), actor=actor, db=db)
        else:
            users_api.patch_user(objetivo.id, UserPatch(role=rol), actor=actor, db=db)
        assert objetivo.role == rol
        db.commit.assert_called_once()
        eventos.assert_called_once()
        assert eventos.call_args.kwargs["new_role"] == rol


@pytest.mark.parametrize("rol", ["tenant_admin", "client", "lectura", "admin", "developer"])
def test_cambio_a_los_demas_roles_sigue_igual_para_tenant_admin(rol, eventos):
    for handler in ("put", "patch"):
        objetivo = _objetivo("lectura" if rol != "lectura" else "client")
        db = _db_con(objetivo)
        actor = _actor("tenant_admin")
        if handler == "put":
            users_api.update_user(objetivo.id, _put(rol), actor=actor, db=db)
        else:
            users_api.patch_user(objetivo.id, UserPatch(role=rol), actor=actor, db=db)
        db.commit.assert_called()


@pytest.mark.parametrize("rol", PROTEGIDOS)
def test_no_se_bloquea_lo_que_no_cambia_el_rol_de_usuarios_existentes(rol, eventos):
    """«No se tocan datos»: un usuario que YA es compliance_officer/super_admin se puede
    seguir editando (email, is_active…) por un tenant_admin. PUT re-manda el rol vigente
    (`role` es requerido en `UserBase`) y eso no es un cambio de rol."""
    objetivo = _objetivo(rol)
    db = _db_con(objetivo)
    users_api.update_user(objetivo.id, UserBase(username="objetivo", email="otro@t.example",
                                                role=rol),
                          actor=_actor("tenant_admin"), db=db)
    assert objetivo.email == "otro@t.example"
    eventos.assert_not_called()

    objetivo = _objetivo(rol)
    db = _db_con(objetivo)
    users_api.patch_user(objetivo.id, UserPatch(email="otro@t.example"),
                         actor=_actor("tenant_admin"), db=db)
    assert objetivo.email == "otro@t.example"
