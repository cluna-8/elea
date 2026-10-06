"""El acceso por perfil resuelve la llave con la clase REAL de la base (057 T017; HANDOFF §1(b)).

`sentinel/access/api/admin.py` importaba `ApiKey` desde `src.models.budget`, una clase que no existe en
ninguna de las dos líneas (se llama `APIKey`): el import perezoso fallaba recién al usar el camino por
defecto de `_key_exists` y `_default_actor`. Sin Postgres: una sesión falsa que solo contesta `get`.
"""
import uuid
from types import SimpleNamespace

import pytest

pytest.importorskip("src.models.budget", reason="requiere el venv del backend")

from src.models.budget import APIKey  # noqa: E402

from sentinel.access.api import admin  # noqa: E402

TENANT = uuid.UUID("11111111-1111-1111-1111-111111111111")
OTRO = uuid.UUID("22222222-2222-2222-2222-222222222222")


class _Db:
    """`get(modelo, id)` solo contesta para la clase de llaves de la base."""

    def __init__(self, llave):
        self.llave, self.pedidos = llave, []

    def get(self, modelo, ident):
        self.pedidos.append(modelo)
        return self.llave if modelo is APIKey else None


@pytest.fixture(autouse=True)
def _sin_inyecciones(monkeypatch):
    # el camino por defecto, no el de los tests que inyectan KEY_EXISTS / ACTOR
    monkeypatch.setattr(admin, "KEY_EXISTS", None)
    monkeypatch.setattr(admin, "ACTOR", None)


def _llave(tenant=TENANT):
    return SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant, user_id=None, group_id=None)


def test_key_exists_usa_la_clase_de_llaves_de_la_base():
    k = _llave()
    db = _Db(k)
    assert admin._key_exists(db, SimpleNamespace(tenant_id=TENANT), k.id) is True
    assert db.pedidos == [APIKey]


def test_key_exists_no_ve_la_llave_de_otra_empresa():
    k = _llave(tenant=OTRO)
    assert admin._key_exists(_Db(k), SimpleNamespace(tenant_id=TENANT), k.id) is False


def test_key_exists_con_llave_inexistente():
    assert admin._key_exists(_Db(None), SimpleNamespace(tenant_id=TENANT), uuid.uuid4()) is False


def test_actor_por_defecto_resuelve_la_llave(monkeypatch):
    k = _llave()
    monkeypatch.setattr(admin.rt, "effective_risk", lambda db, **kw: ("low", "low"))
    out = admin._default_actor(_Db(k), TENANT, None, None, str(k.id))
    assert out["key_id"] == str(k.id)
    assert out["user_risk"] == "low" and out["key_risk"] == "low"
