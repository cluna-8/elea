"""`X-Guardian-Acting-User` en el plano del motor (spec 043 US2, contrato 2, T026/T027).

Mismo harness que `test_custom_auth_budget.py` (doble de `litellm.proxy._types`, sin red ni
base real). Ancla: la cabecera nunca se acepta a ciegas — `_verify_acting_user` corta en
cualquier caso ambiguo (sin header, sin privilegio, verificación no disponible) devolviendo
``None``, y solo un `True` explícito del backend hace que `user_api_key_auth` propague
`acted_for_user_id` en `sentinel_identity`.
"""
import sys
import types

import pytest


def _instalar_doble_litellm():
    if "litellm.proxy._types" in sys.modules:
        return

    class UserAPIKeyAuth:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class LitellmUserRoles:
        PROXY_ADMIN = "proxy_admin"

    litellm_mod = sys.modules.setdefault("litellm", types.ModuleType("litellm"))
    proxy_mod = sys.modules.setdefault("litellm.proxy", types.ModuleType("litellm.proxy"))
    types_mod = types.ModuleType("litellm.proxy._types")
    types_mod.UserAPIKeyAuth = UserAPIKeyAuth
    types_mod.LitellmUserRoles = LitellmUserRoles
    sys.modules["litellm.proxy._types"] = types_mod
    litellm_mod.proxy = proxy_mod
    proxy_mod._types = types_mod


_instalar_doble_litellm()

from extensions import custom_auth  # noqa: E402

CLAVE = "sk-sentinel-de-prueba"


class _Request:
    def __init__(self, **headers):
        self.headers = headers


def _identidad(**extra):
    fila = {
        "key_id": "11111111-1111-1111-1111-111111111111",
        "tenant_id": "00000000-0000-0000-0000-000000000001",
        "user_id": "22222222-2222-2222-2222-222222222222",
        "username": "svc-rag-masking",
        "group_id": None,
        "tool_type": "servicio",
        "upstream_mode": "byok",
        "is_active": True,
        "can_act_on_behalf": False,
    }
    fila.update(extra)
    return fila


@pytest.fixture
def identidad(monkeypatch):
    def _set(fila):
        async def _fake_lookup(key_hash):
            return fila
        monkeypatch.setattr(custom_auth, "_lookup_identity", _fake_lookup)
        custom_auth._cache.clear()
    return _set


# ── _verify_acting_user: los cortes tempranos (sin I/O) ─────────────────────────────────

@pytest.mark.asyncio
async def test_sin_header_no_verifica_nada():
    assert await custom_auth._verify_acting_user(_identidad(), None) is None


@pytest.mark.asyncio
async def test_sin_privilegio_ignora_la_cabecera_aunque_el_uuid_sea_valido():
    fila = _identidad(can_act_on_behalf=False)
    assert await custom_auth._verify_acting_user(
        fila, "33333333-3333-3333-3333-333333333333") is None


@pytest.mark.asyncio
async def test_sin_tenant_resuelto_no_verifica():
    fila = _identidad(can_act_on_behalf=True, tenant_id=None)
    assert await custom_auth._verify_acting_user(
        fila, "33333333-3333-3333-3333-333333333333") is None


@pytest.mark.asyncio
async def test_sin_identity_url_configurada_y_sin_prisma_disponible_degrada_a_none():
    """Camino dev-fallback sin `litellm.proxy.proxy_server` real disponible (no está en
    este entorno de test) — debe fallar de forma NO bloqueante, nunca romper el pedido."""
    fila = _identidad(can_act_on_behalf=True)
    assert await custom_auth._verify_acting_user(
        fila, "33333333-3333-3333-3333-333333333333") is None


# ── Propagación real en user_api_key_auth (vía _verify_acting_user monkeypatcheado) ──────

@pytest.mark.asyncio
async def test_acted_for_user_id_se_propaga_cuando_la_verificacion_aprueba(identidad, monkeypatch):
    identidad(_identidad(can_act_on_behalf=True))

    async def _fake_verify(row, header_value):
        assert header_value == "33333333-3333-3333-3333-333333333333"
        return header_value

    monkeypatch.setattr(custom_auth, "_verify_acting_user", _fake_verify)

    auth = await custom_auth.user_api_key_auth(
        _Request(**{"x-guardian-acting-user": "33333333-3333-3333-3333-333333333333"}),
        CLAVE,
    )
    assert auth.metadata["sentinel"]["acted_for_user_id"] == \
        "33333333-3333-3333-3333-333333333333"


@pytest.mark.asyncio
async def test_acted_for_user_id_es_none_por_default_sin_verificacion(identidad):
    """Sin monkeypatchear `_verify_acting_user`, el camino real (sin `SENTINEL_IDENTITY_URL`
    ni prisma real en este entorno) degrada a `None` — comportamiento seguro por default,
    ninguna llave existente gana la capacidad por accidente."""
    identidad(_identidad(can_act_on_behalf=True))

    auth = await custom_auth.user_api_key_auth(
        _Request(**{"x-guardian-acting-user": "33333333-3333-3333-3333-333333333333"}), CLAVE,
    )
    assert auth.metadata["sentinel"]["acted_for_user_id"] is None


@pytest.mark.asyncio
async def test_sin_cabecera_acted_for_user_id_es_none(identidad):
    identidad(_identidad(can_act_on_behalf=True))
    auth = await custom_auth.user_api_key_auth(_Request(), CLAVE)
    assert auth.metadata["sentinel"]["acted_for_user_id"] is None
