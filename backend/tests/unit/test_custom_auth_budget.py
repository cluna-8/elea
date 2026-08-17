"""Enforcement de presupuesto en el plano MOTOR (issue #76, decisión A de JF).

Hasta este fix, `/gw` no tenía enforcement NINGUNO: el tope sólo cortaba en el Playground
(`chat.py:646`) y el `max_budget` por-llave viajaba a un provisionador del motor que en
selfhosted no existe. O sea: una herramienta con virtual key gastaba sin techo — el
hallazgo que JF marcó como CLAVE ("IMPORTANTE QUE FUNCIONE EL CONTROLADOR DE PRESUPUESTO").

Qué se ancla acá, y por qué cada cosa:

1. **El corte es un 402 y no un 401.** El proxy preserva el status de las `HTTPException`
   y aplasta cualquier otra excepción a 401 (`litellm/proxy/auth/auth_exception_handler.py`:
   `code=getattr(e, "status_code", 401)`), así que si el rechazo saliera como `Exception`
   pelada —el mecanismo que este módulo usa para "clave desconocida"— la herramienta leería
   "credencial inválida" y mandaría al usuario a re-loguearse en vez de a pedir tope.
2. **Rechaza ANTES del proveedor.** El corte vive en la auth: cuando se lanza, el pedido
   todavía no salió. Es la única forma de que un tráfico sin presupuesto no cueste dinero.
3. **Sin presupuesto configurado NO se corta.** El plano interno ELIMINA las columnas NULL
   del JSON, así que "sin tope" llega como clave AUSENTE. Un `.get(...) or 0` mal puesto
   convertiría eso en tope 0 = todo el mundo frenado; el test negativo lo cubre.

La extensión se importa como la importa el motor (`extensions.custom_auth`, vía el
`sys.path` que arma conftest) con un doble de `litellm.proxy._types` en `sys.modules`:
`litellm` no está instalado en el backend y no hace falta que lo esté — lo que se prueba es
NUESTRA lógica de auth, no el SDK del motor.
"""
import sys
import types

import pytest


# ── Doble de litellm.proxy._types (el módulo real no está instalado acá) ────────────────
def _instalar_doble_litellm():
    if "litellm.proxy._types" in sys.modules:
        return

    class UserAPIKeyAuth:
        """Sólo necesita guardar lo que le pasan: los asserts miran metadata/identidad."""
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

from fastapi import HTTPException  # noqa: E402
from extensions import custom_auth  # noqa: E402

CLAVE = "sk-basa-de-prueba"
HASH = "a" * 64


class _Request:
    """Lo único que `user_api_key_auth` toca del Request son las cabeceras."""
    def __init__(self, **headers):
        self.headers = headers


def _identidad(**extra):
    """Fila del plano interno. Ojo: las columnas NULL NO viajan — por eso los campos de
    presupuesto se AGREGAN sólo cuando el test los quiere."""
    fila = {
        "key_id": "11111111-1111-1111-1111-111111111111",
        "tenant_id": "00000000-0000-0000-0000-000000000001",
        "user_id": "22222222-2222-2222-2222-222222222222",
        "username": "cliente-demo",
        "group_id": None,
        "tool_type": "claude-code",
        "upstream_mode": "byok",
        "is_active": True,
    }
    fila.update(extra)
    return fila


@pytest.fixture
def identidad(monkeypatch):
    """Inyecta la fila que devolvería el plano interno, sin red ni base."""
    def _set(fila):
        async def _fake_lookup(key_hash):
            return fila
        monkeypatch.setattr(custom_auth, "_lookup_identity", _fake_lookup)
        custom_auth._cache.clear()
    return _set


async def _auth(request=None):
    return await custom_auth.user_api_key_auth(request or _Request(), CLAVE)


# ── El corte ───────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_presupuesto_agotado_devuelve_402_y_no_401(identidad):
    """Gastado == tope ya es "agotado" (>=, no >): con el tope alcanzado, el pedido
    siguiente sólo puede pasarse de largo."""
    identidad(_identidad(max_budget_usd=5.0, spend_usd=5.0))

    with pytest.raises(HTTPException) as exc:
        await _auth()

    assert exc.value.status_code == 402, "un 401 mandaría a la herramienta a re-loguear"
    assert "presupuesto agotado" in exc.value.detail.lower()
    # El mensaje tiene que ser accionable para el usuario de la herramienta, que no ve la UI
    assert "administrador" in exc.value.detail.lower()


@pytest.mark.asyncio
async def test_presupuesto_excedido_tambien_corta(identidad):
    identidad(_identidad(max_budget_usd=5.0, spend_usd=7.25))

    with pytest.raises(HTTPException) as exc:
        await _auth()

    assert exc.value.status_code == 402
    # Los números que ve el usuario son los reales, no un texto genérico
    assert "7.25" in exc.value.detail and "5.00" in exc.value.detail


@pytest.mark.asyncio
async def test_numeros_como_texto_del_driver_igual_cortan(identidad):
    """El prisma del camino de desarrollo devuelve `Decimal`/`str` para los `numeric`. Si el
    consumidor los comparara sin normalizar, `"5.0" >= "5.0"` sería comparación de strings
    (o un TypeError) y el corte dependería del driver."""
    identidad(_identidad(max_budget_usd="5.0", spend_usd="5.5"))

    with pytest.raises(HTTPException) as exc:
        await _auth()
    assert exc.value.status_code == 402


# ── Lo que NO se corta ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sin_presupuesto_configurado_pasa(identidad):
    """Caso más común de la instalación: la clave del tope AUSENTE (el plano interno filtra
    los NULL). Ausencia = sin límite, jamás límite 0."""
    identidad(_identidad(spend_usd=0.0))

    auth = await _auth()
    assert auth.metadata["basa"]["identity"] == "connection"


@pytest.mark.asyncio
async def test_con_credito_disponible_pasa(identidad):
    identidad(_identidad(max_budget_usd=10.0, spend_usd=9.99999))

    auth = await _auth()
    assert auth.metadata["basa"]["key_id"] == "11111111-1111-1111-1111-111111111111"


@pytest.mark.asyncio
async def test_gasto_ausente_con_tope_configurado_pasa(identidad):
    """Presupuesto recién creado: `spend_usd` puede no venir. Sin gasto no hay agotamiento
    (y el default tiene que ser 0, no el tope)."""
    identidad(_identidad(max_budget_usd=5.0))

    auth = await _auth()
    assert auth.metadata["basa"]["identity"] == "connection"


@pytest.mark.asyncio
async def test_la_master_key_no_pasa_por_el_presupuesto(identidad, monkeypatch):
    """La master key es ops del proxy (y el camino por el que el Playground llama al motor):
    frenarla por presupuesto cortaría la administración del sistema junto con el tráfico."""
    monkeypatch.setenv("LITELLM_MASTER_KEY", "sk-master-de-prueba")
    identidad(_identidad(max_budget_usd=1.0, spend_usd=999.0))

    auth = await custom_auth.user_api_key_auth(_Request(), "sk-master-de-prueba")
    assert auth.metadata["basa"]["identity"] == "master"


@pytest.mark.asyncio
async def test_la_connection_revocada_sigue_cortando_antes_que_el_presupuesto(identidad):
    """Orden de las guardas: una llave revocada es 401 aunque tenga crédito de sobra."""
    identidad(_identidad(is_active=False, max_budget_usd=100.0, spend_usd=0.0))

    with pytest.raises(Exception) as exc:
        await _auth()
    assert not isinstance(exc.value, HTTPException)
    assert "revocada" in str(exc.value)


# ── La cache no puede volver eterno el crédito ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_la_fila_con_presupuesto_se_cachea_menos_tiempo(identidad, monkeypatch):
    """El gasto sólo sube: cachear 60 s una llave con presupuesto le regala un minuto de
    pedidos después de agotarse. Con presupuesto, la ventana es la corta."""
    con = {"max_budget_usd": 5.0, "spend_usd": 1.0}
    sin = {"spend_usd": 0.0}

    assert custom_auth._ttl_para(con) == custom_auth._CACHE_TTL_BUDGET_S
    assert custom_auth._ttl_para(sin) == custom_auth._CACHE_TTL_S
    assert custom_auth._CACHE_TTL_BUDGET_S < custom_auth._CACHE_TTL_S
    # `None` (la key no existe) usa el TTL largo: es una respuesta estable, no un contador
    assert custom_auth._ttl_para(None) == custom_auth._CACHE_TTL_S


# ── #176: la fila durable del rechazo por presupuesto del plano MOTOR ──────────────────
# Gemela de la del #157 (plano consola). El corte por tope vive en la auth, ANTES del
# guardrail y del post-call hook, así que `basa_audit_logger` (que sólo corre en el success
# hook) nunca ve este pedido: sin la emisión de acá, el rechazo del tráfico de coding
# tools/byok no dejaría rastro durable, y el officer vería los 402 de la consola pero no los
# del motor — peor que ninguno, porque parece completo y no lo está.


@pytest.fixture
def emisor_espia(monkeypatch):
    """Doble de `basa_audit_logger.emitir_fila_durable`: captura la entry sin motor ni red.
    `custom_auth` lo importa PEREZOSO dentro del rechazo, así que basta sembrar el módulo en
    `sys.modules` (el real arrastra litellm/redis, que no están instalados acá)."""
    capturadas = []
    mod = types.ModuleType("basa_audit_logger")

    async def _fake_emitir(entry, masked, applied_layers=None, blocked_by_layer=None):
        capturadas.append(entry)

    mod.emitir_fila_durable = _fake_emitir
    monkeypatch.setitem(sys.modules, "basa_audit_logger", mod)
    return capturadas


@pytest.mark.asyncio
async def test_rechazo_presupuesto_emite_fila_durable_rejected_budget(identidad, emisor_espia):
    """El 402 del plano motor deja UNA fila durable con el MISMO literal que el #157, la
    identidad de la Connection y sin tokens/costo (no hubo consumo)."""
    identidad(_identidad(key_id="k-176", tenant_id="t-176", user_id="u-176",
                         group_id="g-176", max_budget_usd=5.0, spend_usd=5.0))

    with pytest.raises(HTTPException) as exc:
        await _auth()
    assert exc.value.status_code == 402

    assert len(emisor_espia) == 1, "una sola fila por rechazo"
    fila = emisor_espia[0]
    assert fila["compliance_status"] == "rejected_budget"
    assert fila["api_key_id"] == "k-176"
    assert fila["tenant_id"] == "t-176"
    assert fila["user_id"] == "u-176"
    assert fila["user_group_id"] == "g-176"
    # 0/0/0: el receptor (`internal._acumular_gasto`) NO mueve presupuesto con esto — la fila
    # es metadata del rechazo, no un consumo que cobrar dos veces sobre un tope ya agotado.
    assert fila["prompt_tokens"] == 0 and fila["completion_tokens"] == 0
    assert fila["cost_usd"] == 0.0
    # Sin atribución del plano motor (T025): SQL NULL, no `[]` (que mentiría "ninguna capa corrió").
    assert fila["applied_layers"] is None and fila["blocked_by_layer"] is None


@pytest.mark.asyncio
async def test_rechazo_presupuesto_registra_antes_de_responder(identidad, monkeypatch):
    """Registrar → responder (#157): la fila se emite ANTES de que salga el 402, no después,
    para que negar servicio nunca preceda al rastro."""
    orden = []
    mod = types.ModuleType("basa_audit_logger")

    async def _fake_emitir(entry, masked, applied_layers=None, blocked_by_layer=None):
        orden.append("fila")

    mod.emitir_fila_durable = _fake_emitir
    monkeypatch.setitem(sys.modules, "basa_audit_logger", mod)

    identidad(_identidad(max_budget_usd=1.0, spend_usd=2.0))
    with pytest.raises(HTTPException):
        await _auth()
    orden.append("402")
    assert orden == ["fila", "402"]


@pytest.mark.asyncio
async def test_fila_perdida_no_convierte_el_402_en_401(identidad, monkeypatch):
    """Fail-closed del rechazo: si el emisor revienta (import roto, un fallo que escape su
    propio guardado), el cliente sigue viendo 402 — jamás 401, que lo mandaría a re-loguear.
    La pérdida se traga acá; el conteo vive dentro del emisor real."""
    mod = types.ModuleType("basa_audit_logger")

    async def _emisor_que_revienta(entry, masked, applied_layers=None, blocked_by_layer=None):
        raise RuntimeError("plano interno caído")

    mod.emitir_fila_durable = _emisor_que_revienta
    monkeypatch.setitem(sys.modules, "basa_audit_logger", mod)

    identidad(_identidad(max_budget_usd=1.0, spend_usd=2.0))
    with pytest.raises(HTTPException) as exc:
        await _auth()
    assert exc.value.status_code == 402


@pytest.mark.asyncio
async def test_con_credito_no_emite_fila(identidad, emisor_espia):
    """Sin rechazo no hay fila: el camino feliz de la auth no toca la auditoría del rechazo."""
    identidad(_identidad(max_budget_usd=10.0, spend_usd=1.0))
    await _auth()
    assert emisor_espia == []
