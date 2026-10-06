"""No-regresión CON la extensión montada y la política apagada (057 T018; SC-001, US2 esc. 1–4; FR-001, FR-014).

Reusa la batería de T003 (`backend/tests/contract/test_gw_no_regresion_057.py`: casos, motor falso,
observación y JSON grabado) y la corre con la extensión montada por sus costuras reales:
`GATEWAY_PLUGINS=sentinel.redirect.plugin` (S2), `PLUGIN_PACKAGES=sentinel.redirect.api,sentinel.catalog.api`
(S1) y `ALEMBIC_EXTRA_VERSION_LOCATIONS` (S4), **sin ninguna fila de política ni de postura**. Las
respuestas, los pedidos que llegan al motor o al proveedor y las filas de auditoría y de monitor tienen
que ser exactamente los grabados SIN extensión: es la mitad de SC-001 que mide el paquete copiado.

Además, con la política **apagada** (sin filas, y con una fila `off` que sí publica ids):
- un id publicado solo para otro grupo da lo mismo que hoy (el pedido pasa tal cual y el motor contesta
  el error de modelo inexistente de siempre);
- los destinos de otra empresa no aparecen en `/gw/v1/models`;
- un `api_base`, una credencial o cabeceras de autenticación del cliente no cambian a dónde ni con
  qué credencial sale el pedido, y un `rdx-*` pedido directamente se rechaza (FR-014).

Sin Docker, sin Postgres y sin red: el motor es el doble de la batería.
"""
import copy
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))
pytest.importorskip("src.api.gateway", reason="requiere el venv del backend")

from src.api import gateway_plugins as gp  # noqa: E402
from src.plugins import mount_plugin_routers, plugin_packages  # noqa: E402

from sentinel.access import bridge  # noqa: E402
from sentinel.engine import redirect_guard as guard  # noqa: E402
from sentinel.redirect import authz  # noqa: E402
from sentinel.redirect import plugin as redirect_plugin  # noqa: E402
from sentinel.redirect.store import Snapshot  # noqa: E402
from sentinel.tests import redirect_fixtures as fx  # noqa: E402

# ── La batería de T003, importada por ruta (no es un paquete) ────────────────────────────────────
_BASE = ROOT / "backend" / "tests" / "contract" / "test_gw_no_regresion_057.py"
_spec = importlib.util.spec_from_file_location("gw_no_regresion_057", _BASE)
base = importlib.util.module_from_spec(_spec)
sys.modules["gw_no_regresion_057"] = base
_spec.loader.exec_module(base)

CASOS, observar, bateria = base.CASOS, base.observar, base.bateria   # `bateria`: fixture de T003

TENANT = base.TENANT                       # la empresa de la batería (la de la identidad de los casos)
GRUPO = base.IDENT_CON_LLAVE["group_id"]
OTRO_GRUPO = "g-otro-057"
OTRA_EMPRESA = fx.OTHER

PAQUETES = "sentinel.redirect.api,sentinel.catalog.api"
INTERNAL_KEY = "k" * 48


def _montar_extension(bat, monkeypatch, snapshots=None):
    """Monta la extensión sobre la pasarela de la batería, por las variables reales.

    `snapshots`: `{empresa: Snapshot}`; una empresa que no está tiene la instantánea vacía
    (ninguna fila de política ni postura)."""
    monkeypatch.setenv("GATEWAY_PLUGINS", "sentinel.redirect.plugin")
    monkeypatch.setenv("PLUGIN_PACKAGES", PAQUETES)
    monkeypatch.setenv("ALEMBIC_EXTRA_VERSION_LOCATIONS", str(ROOT / "sentinel" / "migrations"))
    monkeypatch.setenv(authz.KEY_ENV, INTERNAL_KEY)
    gp.clear_gateway_plugins()
    # el plugin que carga el entorno es `gateway_plugin`; solo se le cambia el almacén (la base no está)
    monkeypatch.setattr(redirect_plugin.gateway_plugin, "_store", _store_con(snapshots or {}))
    # acceso por perfil: ninguno cargado ⇒ el puente no filtra (no hay base a la que preguntar)
    monkeypatch.setattr(bridge, "RESOLVER", lambda tenant, **kw: None)
    monkeypatch.setattr(bridge, "RISK", lambda ident: (None, None))
    n = mount_plugin_routers(bat.cliente.app)
    assert n > 0, "los routers de la extensión no se montaron"
    assert gp.active(), "el plugin de pasarela no quedó registrado"
    assert [type(p).__name__ for p in gp.plugins()] == ["RedirectPlugin"]


def _store_con(snapshots: dict):
    from sentinel.redirect.store import EMPTY, RedirectStore
    return RedirectStore(loader=lambda t: snapshots.get(t, EMPTY), ttl=0,
                         key_models=lambda k: None, redis_factory=lambda: None,
                         decrypt=lambda blob: json.loads(blob) if blob else {})


@pytest.fixture
def bateria_con_extension(bateria, monkeypatch):
    _montar_extension(bateria, monkeypatch)
    yield bateria
    gp.clear_gateway_plugins()


# ── 1. La misma batería de T003, con la extensión montada ────────────────────────────────────────
def test_la_extension_esta_montada_por_las_variables_reales(bateria_con_extension):
    assert plugin_packages() == PAQUETES.split(",")
    rutas = {getattr(r, "path", "") for r in bateria_con_extension.cliente.app.routes}
    assert any(p.startswith("/api/v1/redirect") for p in rutas), sorted(rutas)
    assert any(p.startswith("/api/v1/catalog") for p in rutas), sorted(rutas)


@pytest.mark.parametrize("caso", CASOS, ids=[c["nombre"] for c in CASOS])
def test_la_pasarela_no_cambia_con_la_extension_montada(bateria_con_extension, caso):
    observado = json.loads(json.dumps(observar(bateria_con_extension, caso), ensure_ascii=False))
    grabado = json.loads(base.GOLDEN.read_text(encoding="utf-8"))
    assert caso["nombre"] in grabado, f"caso sin grabar en la batería de T003: {caso['nombre']}"
    assert observado == grabado[caso["nombre"]]


# ── 2/3. Lo que se compara contra «sin extensión» en el mismo arnés ──────────────────────────────
def _caso(nombre):
    return copy.deepcopy(next(c for c in CASOS if c["nombre"] == nombre))


def _distinto(nombre, **cambios):
    caso = _caso(nombre)
    caso.update(cambios)
    caso["nombre"] = f"{nombre}+"
    return caso


def _snapshot(estado, *, empresa=TENANT, scope_type="group", scope_value=OTRO_GRUPO, publicados=None,
              claude_public="claude-sonnet-4-5"):
    """Una instantánea con ids publicados para un alcance, con la política en `estado`."""
    published = publicados or (
        {"id": "p-cl", "tenant_id": empresa, "scope_type": scope_type, "scope_value": scope_value,
         "face": "claude", "public_id": claude_public, "family_tier": "sonnet",
         "is_family_default": True, "label_mode": "destination"},
        {"id": "p-gen", "tenant_id": empresa, "scope_type": scope_type, "scope_value": scope_value,
         "face": "openai_generic", "public_id": "pro"},
    )
    rules = (
        {"id": "r-cl", "tenant_id": empresa, "scope_type": scope_type, "scope_value": scope_value,
         "published_model_id": "p-cl", "targets": ["d-chat"]},
        {"id": "r-gen", "tenant_id": empresa, "scope_type": scope_type, "scope_value": scope_value,
         "published_model_id": "p-gen", "targets": ["d-chat"]},
    )
    policy = ({"tenant_id": empresa, "scope_type": scope_type, "scope_value": scope_value,
               "state": estado},) if estado else ()
    dest = {**fx.DEST_CHAT, "tenant_id": empresa}
    return Snapshot(policy=policy, postures=(), published=published, rules=rules,
                    destinations={"d-chat": dest, "d-ant": fx.DEST_ANTHROPIC},
                    offers=({"destination_id": "d-ant", "tenant_id": "*", "enabled_at": None},),
                    credentials=dict(fx.CREDS))


def _sin_y_con_extension(bat, monkeypatch, caso, snapshots):
    """Observa el caso sin plugin y, después, con la extensión montada con `snapshots`."""
    gp.clear_gateway_plugins()
    sin = json.loads(json.dumps(observar(bat, caso), ensure_ascii=False))
    _montar_extension(bat, monkeypatch, snapshots)
    con = json.loads(json.dumps(observar(bat, caso), ensure_ascii=False))
    return sin, con


def _crudas(bat) -> set:
    """Nombres (en minúscula) de TODAS las cabeceras que llegaron al upstream en la última observación;
    la observación de T003 guarda solo las del contrato, y acá hace falta ver también las internas."""
    return {k.lower() for c in bat.upstream.llamadas for k in c["headers"]}


NO_ENCONTRADO = base._Respuesta(404, {"type": "error", "error": {
    "type": "not_found_error", "message": "model: claude-sonnet-4-5 no existe"}})


@pytest.mark.parametrize("estado", [None, "off", "on"], ids=["sin-filas", "politica-off", "on-otro-grupo"])
def test_un_id_publicado_solo_para_otro_grupo_da_el_mismo_error_que_hoy(bateria, monkeypatch, estado):
    """El id existe para `g-otro-057`; el pedido es de `g-057`: para él no existe y el motor contesta
    lo de siempre, sin reescritura ni autorización firmada (US2 esc. 3; FR-006)."""
    caso = _distinto("byok_mensajes_no_stream", cuerpo={**base.BENIGNO, "model": "claude-sonnet-4-5"},
                     guion={base._MENSAJES_MOTOR: NO_ENCONTRADO})
    sin, con = _sin_y_con_extension(bateria, monkeypatch, caso,
                                    {TENANT: _snapshot(estado)} if estado else {})
    assert sin["estado"] == 404
    assert con == sin
    (llamada,) = con["upstream"]
    assert llamada["cuerpo"]["model"] == "claude-sonnet-4-5"          # sin reescribir a `rdx-*`
    assert authz.HEADER not in _crudas(bateria)


# ── 4. Otra empresa ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("vista", ["claude", "generica"])
@pytest.mark.parametrize("estado", ["on", "off"])
def test_los_destinos_de_otra_empresa_no_aparecen_en_el_listado(bateria, monkeypatch, vista, estado):
    otra = _snapshot(estado, empresa=OTRA_EMPRESA, scope_type="tenant", scope_value="*",
                     claude_public="claude-de-la-otra-empresa")
    headers = dict(base._BYOK)
    if vista == "generica":
        headers.pop("anthropic-version")
    caso = _distinto("models_byok", headers=headers)
    sin, con = _sin_y_con_extension(bateria, monkeypatch, caso, {OTRA_EMPRESA: otra})
    assert con == sin
    ids = [m["id"] for m in con["cuerpo"]["data"]]
    assert ids == [m["id"] for m in base.MODELOS["data"]]               # ni suma ni pierde nada
    texto = json.dumps(con["cuerpo"])
    for ajeno in ("claude-de-la-otra-empresa", fx.DEST_CHAT["name"], "rdx-"):
        assert ajeno not in texto, ajeno


def test_el_listado_no_pierde_ni_suma_nada_para_la_empresa_sin_filas(bateria_con_extension):
    r = observar(bateria_con_extension, _caso("models_byok"))
    assert [m["id"] for m in r["cuerpo"]["data"]] == [m["id"] for m in base.MODELOS["data"]]


# ── 5. Política apagada: el cliente no manda dónde ni con qué credencial ─────────────────────────
CLAVE_DEL_CLIENTE = "valor-inventado-del-cliente-NO-USAR"
DESVIO = {"api_base": "http://atacante.example/v1", "base_url": "http://atacante.example",
          "api_key": CLAVE_DEL_CLIENTE, "extra_headers": {"Authorization": "Bearer del-cliente"},
          "aws_secret_access_key": "no-usar"}


@pytest.mark.parametrize("estado", [None, "off"], ids=["sin-filas", "politica-off"])
def test_con_la_politica_apagada_el_pedido_sale_donde_y_con_lo_que_sale_hoy(bateria, monkeypatch, estado):
    caso = _distinto("byok_mensajes_no_stream", cuerpo={**base.BENIGNO, **DESVIO},
                     headers={**base._BYOK, "X-Api-Key": CLAVE_DEL_CLIENTE,
                              "api-key": CLAVE_DEL_CLIENTE},
                     guion={base._MENSAJES_MOTOR: base._Respuesta(200, base.RESP_OK)})
    sin, con = _sin_y_con_extension(
        bateria, monkeypatch, caso, {TENANT: _snapshot(estado, scope_type="tenant", scope_value="*")}
        if estado else {})
    assert con == sin, "la extensión cambió el pedido o la respuesta con la política apagada"
    (llamada,) = con["upstream"]
    assert llamada["url"].startswith(base.MOTOR + "/")                  # al motor de siempre, no a `api_base`
    # destino y credenciales = URL y cabeceras (el cuerpo del cliente pasa verbatim al motor, hoy y con la
    # extensión; qué hace el motor con él lo mide el spike D14, T019)
    assert all("atacante" not in c["url"] and "atacante" not in json.dumps(c["headers"], default=str)
               and "del-cliente" not in c["headers"].get("Authorization", "")
               for c in bateria.upstream.llamadas)
    assert authz.HEADER not in _crudas(bateria)                        # la extensión no firma nada


def test_con_la_politica_apagada_las_cabeceras_de_autenticacion_no_se_tocan(bateria, monkeypatch):
    caso = _distinto("suscripcion_no_stream", headers={**base._SUSCRIPCION, "x-api-key": CLAVE_DEL_CLIENTE},
                     guion={base._MENSAJES_PROVEEDOR: base._Respuesta(200, base.RESP_OK)})
    sin, con = _sin_y_con_extension(bateria, monkeypatch, caso, {})
    assert con == sin
    (llamada,) = con["upstream"]
    assert llamada["url"].startswith(base.PROVEEDOR)
    assert llamada["headers"]["authorization"] == base.OAUTH


# ── 6. Un rdx-* pedido directamente se rechaza (FR-014) ─────────────────────────────────────────
RDX = "rdx-chatcompat/gpt-5.1"


@pytest.mark.parametrize("estado", [None, "off"], ids=["sin-filas", "politica-off"])
def test_un_rdx_pedido_directamente_no_lleva_autorizacion_y_el_guard_lo_rechaza(bateria, monkeypatch, estado):
    caso = _distinto("byok_mensajes_no_stream", cuerpo={**base.BENIGNO, "model": RDX},
                     guion={base._MENSAJES_MOTOR: base._Respuesta(403, {"type": "error", "error": {
                         "type": "permission_error", "message": "authz_missing"}})})
    sin, con = _sin_y_con_extension(
        bateria, monkeypatch, caso, {TENANT: _snapshot(estado, scope_type="tenant", scope_value="*")}
        if estado else {})
    assert con == sin
    (llamada,) = con["upstream"]
    # la pasarela no inventa una autorización para un modelo interno que eligió el cliente…
    assert llamada["cuerpo"]["model"] == RDX and authz.HEADER not in _crudas(bateria)
    # …y el guard del motor, sin autorización firmada, lo corta siempre
    data = {"model": RDX, "messages": [{"role": "user", "content": "hola"}],
            "proxy_server_request": {"headers": {}}, "metadata": {"headers": {}}}
    with pytest.raises(guard.GuardRejection) as e:
        guard.apply_redirect(data, key=INTERNAL_KEY, now=1_800_000_000.0, environ={})
    assert e.value.status == 403 and e.value.code == "authz_missing"
