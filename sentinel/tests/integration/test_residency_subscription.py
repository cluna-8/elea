"""T059 (057 FR-025, FR-041; US3 esc. 6; T069 de Sentinel): camino de suscripción y postura.

Con la credencial personal de la suscripción (el pedido va tal cual al proveedor original) **la redirección no
aplica y la postura sí**, con la jurisdicción del proveedor original (inferencia, entidad y control en EE. UU.): una
allowlist que no la incluye ⇒ 403; una `offregion_masked` con casa fuera de EE. UU. fuerza el enmascarado (se
enciende en la pasarela, con `nlp_fail_mode = block`); `count_tokens` con el forzado vigente no se reenvía (se
responde local). Sin ninguna fila el tráfico no redirigido sigue en `off`, aun con `masked_all` por defecto: la
postura por defecto es solo del tráfico redirigido (FR-007, FR-031)."""
import json

import pytest

from sentinel.redirect import authz
from sentinel.redirect.plugin import RedirectPlugin
from sentinel.tests import redirect_fixtures as fx
from sentinel.tests import residency_fixtures as rf


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv(authz.KEY_ENV, fx.INTERNAL_KEY)
    monkeypatch.setenv("SENTINEL_ENTITY_REGION", "latam_ar")


def fila(mode, jur=(), **kw):
    return {**rf.row(mode, jur, **kw), "tenant_id": fx.TENANT, "id": f"p-{mode}"}


def plugin(default="masked_all", postures=(), **kw):
    snap = fx.snapshot("on", regions=[rf.region_row(default)], postures=postures, **kw)
    return RedirectPlugin(store=fx.store(snap), ping_after=0.05)


def ctx(route="/v1/messages", model="claude-x"):
    return fx.ctx(route=route, model=model, mode="subscription", nlp={"region": "latam_ar"})


async def test_sin_filas_el_trafico_de_suscripcion_sigue_igual_aun_con_masked_all_por_defecto():
    c = ctx()
    assert await plugin("masked_all").pre_request(c) is None
    assert c.governance_overrides == {}                       # la postura por defecto es del tráfico redirigido


async def test_la_redireccion_no_aplica_a_la_suscripcion_aunque_el_id_este_publicado():
    c = ctx(model="claude-sonnet-4-5")                         # id publicado con destino del mismo proveedor
    p = plugin("masked_all", [fila("offregion_masked", ["US"])], claude_targets=("d-ant",))
    assert await p.pre_request(c) is None
    assert "destination_id" not in (c.routing_decision or {}).get("extensions", {}).get("redirect", {})


async def test_con_un_destino_de_otro_proveedor_la_suscripcion_personal_no_sirve_401():
    """FR-042 (ya en la 068): la credencial de suscripción no se cambia por la del destino; la postura no lo altera."""
    c = ctx(model="claude-sonnet-4-5")                         # su regla apunta a un destino traducido
    resp = await plugin("masked_all", [fila("offregion_masked", ["US"])]).pre_request(c)
    assert resp is not None and resp.status_code == 401


async def test_una_allowlist_sin_la_jurisdiccion_del_proveedor_original_es_403():
    c = ctx()
    resp = await plugin("masked_all", [fila("allowlist", ["AR"])]).pre_request(c)
    assert resp is not None and resp.status_code == 403


async def test_una_allowlist_con_la_jurisdiccion_del_proveedor_original_pasa_y_lo_audita():
    c = ctx()
    assert await plugin("masked_all", [fila("allowlist", ["US"])]).pre_request(c) is None
    red = c.routing_decision["extensions"]["redirect"]
    assert red["path"] == "subscription" and red["jurisdiction_served"] == "US" and red["residency_mode"] == "allowlist"


async def test_la_zona_de_datos_tambien_vale_para_el_proveedor_original():
    c = ctx()
    assert await plugin("masked_all", [fila("allowlist", ["AMERICAS"])]).pre_request(c) is None


async def test_una_offregion_masked_con_casa_fuera_de_eeuu_fuerza_el_enmascarado_de_la_pasarela():
    c = ctx()
    assert await plugin("masked_all", [fila("offregion_masked", ["AR"])]).pre_request(c) is None
    assert c.governance_overrides == {"pii_masking": True, "nlp_fail_mode": "block", "masking_scope": "full"}
    red = c.routing_decision["extensions"]["redirect"]
    assert red["forced_masking"] is True and red["masking_scope"] == "full"


async def test_con_la_casa_en_eeuu_no_se_fuerza():
    c = ctx()
    await plugin("masked_all", [fila("offregion_masked", ["US"])]).pre_request(c)
    assert c.governance_overrides == {}


async def test_el_piso_de_masked_all_se_aplica_si_hay_alguna_fila_explicita():
    """Con una fila (aquí `off`), el tráfico no redirigido toma la postura de las filas, y el piso de enmascarado
    es del redirigido: la suscripción no queda forzada por él."""
    c = ctx()
    assert await plugin("masked_all", [fila("off")]).pre_request(c) is None
    assert c.governance_overrides == {}


async def test_count_tokens_con_forzado_vigente_no_se_reenvia_se_responde_local():
    p = plugin("masked_all", [fila("offregion_masked", ["AR"])])
    c = ctx(route="/v1/messages/count_tokens")
    c.body = {"model": "claude-x", "messages": [{"role": "user", "content": "hola " * 50}]}
    resp = await p.pre_request(c)
    assert resp is not None and resp.status_code == 200
    assert json.loads(resp.body)["input_tokens"] > 0
    assert c.routing_decision["extensions"]["redirect"]["count_tokens_mode"] == "estimated"


async def test_count_tokens_sin_forzado_sigue_su_camino():
    c = ctx(route="/v1/messages/count_tokens")
    c.body = {"model": "claude-x", "messages": []}
    assert await plugin("masked_all", [fila("allowlist", ["US"])]).pre_request(c) is None
