"""Acceso por perfil en los planos de la pasarela y la redirección (069 US2; T044/T050/T053).

Con un resolutor falso inyectado en `sentinel.access.bridge` (el real vive en `sentinel.access`).
Cubre: corte de modelos del catálogo con la redirección apagada, no-regresión sin política,
`/v1/models` filtrado, destino de la 068 no permitido ⇒ pasa al siguiente permitido, vista
previa, FR-013a y el límite documentado (un modelo fuera del catálogo no se gobierna)."""
import json
from dataclasses import replace

import pytest

from sentinel.access import bridge
from sentinel.redirect import authz, resolver
from sentinel.redirect.plugin import RedirectPlugin, STATE_KEY
from sentinel.redirect.scopes import RequestScope
from sentinel.tests import redirect_fixtures as fx

CATALOGO = {"gpt-x": {}, "local-y": {}, "qwen-ue": {}, "nativo": {}}


class Fake:
    """Resolutor falso: devuelve `permitidos` (None = ninguna política) y recuerda la llamada."""
    def __init__(self, permitidos):
        self.permitidos, self.calls = permitidos, []

    def __call__(self, tenant, **kw):
        self.calls.append((tenant, kw))
        return self.permitidos


@pytest.fixture(autouse=True)
def _bridge(monkeypatch):
    monkeypatch.setenv(authz.KEY_ENV, fx.INTERNAL_KEY)
    monkeypatch.setattr(bridge, "RISK", lambda ident: (None, None))
    monkeypatch.setattr(bridge, "CATALOG", lambda tenant: dict(CATALOGO))


def usar(monkeypatch, permitidos):
    fake = Fake(permitidos)
    monkeypatch.setattr(bridge, "RESOLVER", fake)
    return fake


def plugin(snap=None):
    return RedirectPlugin(store=fx.store(snap), ping_after=0.05)


# ── bridge ──────────────────────────────────────────────────────────────────────

def test_bridge_toma_los_ids_del_ident_y_devuelve_gobernados(monkeypatch):
    fake = usar(monkeypatch, frozenset({"local-y"}))
    monkeypatch.setattr(bridge, "RISK", lambda ident: ("minimal", "limited"))
    permitidos, governed = bridge.allowed_for_ident(
        fx.ident(group_id="g1"))
    assert permitidos == frozenset({"local-y"}) and governed == frozenset(CATALOGO)
    tenant, kw = fake.calls[0]
    assert tenant == fx.TENANT
    assert kw == {"user_id": fx.USER, "group_id": "g1", "key_id": fx.KEY_ID,
                  "user_risk": "minimal", "key_risk": "limited"}


def test_bridge_sin_politica_no_gobierna_nada(monkeypatch):
    usar(monkeypatch, None)
    assert bridge.allowed_for_ident(fx.ident()) == (None, frozenset())


def test_bridge_inactivo_sin_registro_ni_resolutor(monkeypatch):
    monkeypatch.setattr(bridge, "RESOLVER", None)
    monkeypatch.setattr(bridge, "_registered", False)
    assert bridge.allowed_for_ident(fx.ident()) == (None, frozenset())


def test_bridge_cachea_el_riesgo_unos_segundos(monkeypatch):
    usar(monkeypatch, None)
    llamadas = []
    def riesgo(ident):
        llamadas.append(1)
        return ("minimal", None)
    monkeypatch.setattr(bridge, "RISK", None)
    monkeypatch.setattr(bridge, "_risk_from_db", riesgo)
    t = [1000.0]
    monkeypatch.setattr(bridge, "CLOCK", lambda: t[0])
    bridge._risk_cache.clear()
    bridge.allowed_for_ident(fx.ident()); bridge.allowed_for_ident(fx.ident())
    assert len(llamadas) == 1
    t[0] += bridge.RISK_TTL + 1
    bridge.allowed_for_ident(fx.ident())
    assert len(llamadas) == 2


# ── pre_request: corte de modelos del catálogo (política de redirección apagada) ──

@pytest.mark.parametrize("route", ["/v1/messages", "/v1/chat/completions"])
async def test_corta_modelo_del_catalogo_no_permitido_con_redireccion_apagada(monkeypatch, route):
    usar(monkeypatch, frozenset({"local-y"}))
    c = fx.ctx(route=route, model="gpt-x")
    resp = await plugin(None).pre_request(c)               # sin filas: la 068 está apagada
    assert resp.status_code == 403
    assert c.routing_decision == {"extensions": {"access": {"blocked": "profile_not_allowed",
                                                            "requested": "gpt-x"}}}


async def test_corta_tambien_con_politica_off_explicita(monkeypatch):
    usar(monkeypatch, frozenset({"local-y"}))
    resp = await plugin(fx.snapshot("off")).pre_request(fx.ctx(model="gpt-x"))
    assert resp.status_code == 403


async def test_corta_en_modo_sombra_porque_el_pedido_sale_con_el_modelo_original(monkeypatch):
    usar(monkeypatch, frozenset({"local-y"}))
    resp = await plugin(fx.snapshot("shadow")).pre_request(fx.ctx(model="gpt-x"))
    assert resp.status_code == 403


async def test_modelo_permitido_sigue_su_camino(monkeypatch):
    usar(monkeypatch, frozenset({"local-y"}))
    c = fx.ctx(model="local-y")
    assert await plugin(None).pre_request(c) is None
    assert c.routing_decision is None


async def test_sin_politica_comportamiento_identico_al_actual(monkeypatch):
    usar(monkeypatch, None)
    c = fx.ctx(model="gpt-x")
    assert await plugin(None).pre_request(c) is None
    assert c.state == {} or STATE_KEY not in c.state
    assert c.routing_decision is None and c.governance_overrides == {}


async def test_modelo_fuera_del_catalogo_no_se_gobierna(monkeypatch):
    """Límite documentado: un modelo que el catálogo no conoce (p. ej. uno heredado del archivo de
    configuración del motor) no entra en `governed` y sigue su camino (no-regresión)."""
    usar(monkeypatch, frozenset({"local-y"}))
    assert await plugin(None).pre_request(fx.ctx(model="heredado-del-config")) is None


async def test_resolutor_caido_corta_503_fail_closed(monkeypatch):
    def boom(tenant, **kw):
        raise RuntimeError("x")
    monkeypatch.setattr(bridge, "RESOLVER", boom)
    resp = await plugin(None).pre_request(fx.ctx(model="gpt-x"))
    assert resp.status_code == 503


async def test_count_tokens_y_otras_rutas_no_se_tocan(monkeypatch):
    fake = usar(monkeypatch, frozenset())
    c = fx.ctx(route="/v1/messages/count_tokens", model="gpt-x")
    assert await plugin(None).pre_request(c) is None and not fake.calls


# ── FR-013a: lo que declare el cliente no cambia nada ────────────────────────────

async def test_cabeceras_de_perfil_o_riesgo_no_cambian_nada(monkeypatch):
    fake = usar(monkeypatch, frozenset({"local-y"}))
    declaradas = {"x-sentinel-profile": "admin", "x-risk-level": "minimal",
                  "x-guardian-acting-user": "otro", "x-access-profile": "todo"}
    c = fx.ctx(model="gpt-x", headers=declaradas)
    resp = await plugin(None).pre_request(c)
    assert resp.status_code == 403
    sin = fx.ctx(model="gpt-x")
    await plugin(None).pre_request(sin)
    assert fake.calls[0] == fake.calls[1]                    # el resolutor recibe lo mismo


# ── /v1/models filtrado ──────────────────────────────────────────────────────────

def test_models_filter_oculta_modelos_del_catalogo_no_permitidos(monkeypatch):
    usar(monkeypatch, frozenset({"local-y"}))
    p, c = plugin(None), fx.ctx(route="/v1/models", model=None)
    import asyncio
    assert asyncio.run(p.pre_request(c)) is None
    listing = {"object": "list", "data": [{"id": "gpt-x"}, {"id": "local-y"}, {"id": "heredado"}]}
    assert [m["id"] for m in p.models_filter(c, listing)["data"]] == ["local-y", "heredado"]


async def test_models_filter_sin_politica_no_toca(monkeypatch):
    usar(monkeypatch, None)
    p, c = plugin(None), fx.ctx(route="/v1/models", model=None)
    await p.pre_request(c)
    listing = {"data": [{"id": "gpt-x"}, {"id": "local-y"}]}
    assert p.models_filter(c, listing) == listing


async def test_models_con_resolutor_caido_es_503(monkeypatch):
    def boom(tenant, **kw):
        raise RuntimeError("x")
    monkeypatch.setattr(bridge, "RESOLVER", boom)
    resp = await plugin(None).pre_request(fx.ctx(route="/v1/models", model=None))
    assert resp.status_code == 503


async def test_vista_de_ids_publicados_solo_con_destino_permitido(monkeypatch):
    # "pro" (genérica) → d-chat (public_id qwen-ue); permitidos no lo incluye ⇒ no se muestra
    usar(monkeypatch, frozenset({"local-y"}))
    snap = con_ids(fx.snapshot("on"))
    p, c = plugin(snap), fx.ctx(route="/v1/models", model=None)
    assert await p.pre_request(c) is None
    assert c.state[STATE_KEY + ".models_view"]["data"] == []
    # permitido ⇒ aparece
    usar(monkeypatch, frozenset({"qwen-ue"}))
    p, c = plugin(snap), fx.ctx(route="/v1/models", model=None)
    await p.pre_request(c)
    assert [m["id"] for m in c.state[STATE_KEY + ".models_view"]["data"]] == ["pro"]


# ── 068: destino no permitido se salta al siguiente permitido ────────────────────

def con_ids(snap):
    dests = {k: {**v, "public_id": pid} for (k, v), pid in
             zip(snap.destinations.items(), ("qwen-ue", "nativo"))}
    return replace(snap, destinations=dests)


def dos_destinos():
    snap = con_ids(fx.snapshot("on", targets=("d-chat", "d-chat2")))
    d2 = {**snap.destinations["d-chat"], "id": "d-chat2", "name": "Otro UE", "public_id": "otro-ue",
          "real_model": "otro-real"}
    return replace(snap, destinations={**snap.destinations, "d-chat2": d2},
                   credentials={**snap.credentials, "d-chat2": json.dumps({"api_key": "sk-2"})})


async def test_destino_no_permitido_se_salta_al_siguiente(monkeypatch):
    usar(monkeypatch, frozenset({"otro-ue"}))
    p, c = plugin(dos_destinos()), fx.ctx()
    assert await p.pre_request(c) is None
    out, _ = p.pre_engine(c, {"model": "pro", "messages": []}, {})
    assert out["model"] == "rdx-chatcompat/otro-real"
    assert c.routing_decision["extensions"]["redirect"]["destination_id"] == "d-chat2"
    assert c.routing_decision["extensions"]["redirect"]["substitution_reason"] == "fallback_unavailable"


async def test_si_ningun_destino_esta_permitido_es_403_model_not_allowed(monkeypatch):
    usar(monkeypatch, frozenset({"local-y"}))
    c = fx.ctx()
    resp = await plugin(dos_destinos()).pre_request(c)
    assert resp.status_code == 403
    assert json.loads(resp.body)["error"]["code"] == "model_not_allowed"
    assert c.routing_decision["extensions"]["access"]["blocked"] == "profile_not_allowed"


async def test_redireccion_sin_politica_de_acceso_es_identica(monkeypatch):
    usar(monkeypatch, None)
    p, c = plugin(dos_destinos()), fx.ctx()
    assert await p.pre_request(c) is None
    out, _ = p.pre_engine(c, {"model": "pro", "messages": []}, {})
    assert out["model"] == "rdx-chatcompat/qwen-destino"


# ── resolver puro ────────────────────────────────────────────────────────────────

def _resolver_call(snap, permitidos):
    scope = RequestScope(tenant_id=fx.TENANT)
    from sentinel.redirect import residency
    posture = residency.effective_posture(snap.postures, scope, redirected=True, tenant_region="eu",
                                          regions=snap.regions)
    return resolver.resolve(scope=scope, face="openai_generic", public_id="pro", request_class=None,
                            published_rows=snap.published, rules=snap.rules,
                            destinations=snap.destinations, offers=snap.offers, posture=posture,
                            permitidos=permitidos)


def test_resolver_none_es_sin_restriccion():
    res = _resolver_call(dos_destinos(), None)
    assert isinstance(res, resolver.Resolved) and res.destination["id"] == "d-chat"


def test_resolver_salta_por_perfil_y_registra_el_motivo():
    res = _resolver_call(dos_destinos(), frozenset({"otro-ue"}))
    assert res.destination["id"] == "d-chat2"
    assert res.skipped == (("d-chat", "profile_not_allowed"),)


def test_resolver_todos_por_perfil_es_not_allowed():
    res = _resolver_call(dos_destinos(), frozenset())
    assert isinstance(res, resolver.Unavailable) and res.error_class == "not_allowed"
    assert {r for _, r in res.skipped} == {"profile_not_allowed"}


def test_resolver_destino_sin_public_id_no_se_permite_si_hay_politica():
    snap = fx.snapshot("on")          # destinos sin public_id
    res = _resolver_call(snap, frozenset({"lo-que-sea"}))
    assert isinstance(res, resolver.Unavailable) and res.error_class == "not_allowed"


# ── vista previa (api/admin.resolve_preview) ─────────────────────────────────────

def test_vista_previa_devuelve_origen_y_motivo(monkeypatch):
    from types import SimpleNamespace
    from sentinel.redirect.api import admin
    usar(monkeypatch, frozenset({"local-y"}))
    monkeypatch.setattr(admin, "_db", lambda user: __import__("contextlib").nullcontext(None))
    monkeypatch.setattr(admin, "load_from_session", lambda db, tenant: dos_destinos())
    user = SimpleNamespace(tenant_id=fx.TENANT)
    body = admin.PreviewIn(face="openai_generic", public_id="pro")
    out = admin.resolve_preview(body, user=user)
    assert out["permitidos_origen"] == "perfil"
    assert out["result"] == "unavailable" and out["error_class"] == "not_allowed"
    assert {s["reason"] for s in out["skipped"]} == {"profile_not_allowed"}
    usar(monkeypatch, None)
    out = admin.resolve_preview(body, user=user)
    assert out["permitidos_origen"] is None and out["result"] == "resolved"
