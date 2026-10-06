"""Modo sombra (T046; FR-003, SC-011): el pedido sale IGUAL que con la política apagada, la decisión
hipotética viaja firmada y el motor solo la registra; una falla en sombra no afecta al pedido; y el costo
añadido (pasarela + guard) es ≤ 5 ms en el percentil 95.

Pasarela y guard reales, sin red ni base (`RedirectStore` con loader en memoria): corre con cualquier
venv que tenga `sentinel` y el motor de política (el del backend sirve).
"""
import statistics
import time

import pytest

from sentinel.engine import redirect_guard as guard
from sentinel.redirect import authz, resolver
from sentinel.redirect.plugin import RedirectPlugin, STATE_KEY
from sentinel.redirect.store import RedirectStore, StoreUnavailable
from sentinel.tests import redirect_fixtures as fx

BODY = {"model": "pro", "messages": [{"role": "user", "content": "hola"}], "temperature": 0.2,
        "max_tokens": 256, "stream": False}
CLIENT_HEADERS = {"Authorization": "Bearer sk-vk", "x-request-class": "interactive"}


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setenv(authz.KEY_ENV, fx.INTERNAL_KEY)


def plugin(snap, *, ttl=60):
    """Store con caché local (como en producción tras el primer pedido) y sin Redis."""
    snaps = {fx.TENANT: snap}
    store = RedirectStore(loader=lambda t: snaps[t], ttl=ttl, key_models=lambda k: None,
                          redis_factory=lambda: None, decrypt=lambda blob: {})
    return RedirectPlugin(store=store)


async def through_gateway(p, body=BODY, headers=CLIENT_HEADERS):
    c = fx.ctx()
    early = await p.pre_request(c)
    assert early is None
    out, hdrs = p.pre_engine(c, dict(body), dict(headers))
    return c, out, hdrs


# ── pedido idéntico ───────────────────────────────────────────────────────────

async def test_el_pedido_de_sombra_sale_igual_que_con_la_politica_apagada():
    _, off_body, off_headers = await through_gateway(plugin(fx.snapshot("off")))
    c, sh_body, sh_headers = await through_gateway(plugin(fx.snapshot("shadow")))
    assert sh_body == off_body == BODY                      # ni modelo, ni parámetros, ni credenciales tocados
    assert {k: v for k, v in sh_headers.items() if k != authz.HEADER} == off_headers
    assert set(sh_headers) - set(off_headers) == {authz.HEADER}
    assert c.routing_decision is None or "unavailable" not in c.routing_decision.get("extensions", {}).get(
        "redirect", {})


async def test_sombra_no_toca_la_respuesta_ni_el_stream():
    p = plugin(fx.snapshot("shadow"))
    c, _, _ = await through_gateway(p)
    it = object()
    assert p.wrap_stream(c, it) is it
    assert p.map_response(c, 200, b'{"model":"pro"}') is None
    assert p.map_error(c, 500, b"{}") is None


# ── fila hipotética ───────────────────────────────────────────────────────────

async def test_la_decision_hipotetica_se_registra_sin_destino_real():
    _, out, headers = await through_gateway(plugin(fx.snapshot("shadow")))
    grant = authz.verify(headers[authz.HEADER], expected_model="pro")
    assert grant.credential == {} and grant.provider == "shadow"
    data = {**out, "proxy_server_request": {"headers": dict(headers)}, "metadata": {}}
    res = guard.apply_redirect(data, environ={})
    assert {k: v for k, v in res.items() if k not in ("proxy_server_request", "metadata")} == BODY
    row = res["metadata"]["_internal_routing_decision"]["extensions"]["redirect"]
    assert row["shadow"] is True and row["shadow_destination_id"] == "d-chat"
    assert "destination_id" not in row                      # no se sirvió por ahí: el destino real es el de siempre
    assert row["public_id"] == "pro" and row["rule_id"] == "r-gen"
    assert "cache" not in res                               # sombra = identidad también para la caché del motor


# ── una falla en sombra no afecta ─────────────────────────────────────────────

async def test_falla_del_resolver_en_sombra_deja_pasar_el_pedido(monkeypatch):
    def boom(**kw):
        raise RuntimeError("bug del resolver")
    monkeypatch.setattr(resolver, "resolve", boom)
    p = plugin(fx.snapshot("shadow"))
    c = fx.ctx()
    assert await p.pre_request(c) is None and STATE_KEY not in c.state
    out, headers = p.pre_engine(c, dict(BODY), dict(CLIENT_HEADERS))
    assert out == BODY and headers == CLIENT_HEADERS


async def test_store_caido_con_sombra_conocida_deja_pasar_el_pedido():
    calls = {"n": 0}

    def loader(t):
        calls["n"] += 1
        if calls["n"] > 1:
            raise RuntimeError("db caída")
        return fx.snapshot("shadow")
    store = RedirectStore(loader=loader, ttl=0, key_models=lambda k: None, redis_factory=lambda: None)
    p = RedirectPlugin(store=store)
    await through_gateway(p)                                # el primero carga y deja el último snapshot bueno
    c = fx.ctx()
    assert await p.pre_request(c) is None                   # sombra no es fail-closed
    with pytest.raises(StoreUnavailable):
        store.snapshot(fx.TENANT)


async def test_sin_clave_interna_la_sombra_sale_sin_firma_y_sin_error(monkeypatch):
    monkeypatch.delenv(authz.KEY_ENV)
    _, out, headers = await through_gateway(plugin(fx.snapshot("shadow")))
    assert out == BODY and authz.HEADER not in headers


def test_autorizacion_de_sombra_invalida_en_el_motor_se_ignora():
    data = {"model": "pro", "messages": [], "proxy_server_request": {"headers": {authz.HEADER: "v1.mal.formado"}},
            "metadata": {}}
    res = guard.apply_redirect(data, environ={})
    assert "_internal_routing_decision" not in res["metadata"] and "api_key" not in res


# ── ≤ 5 ms p95 ────────────────────────────────────────────────────────────────

def _p95(samples):
    return statistics.quantiles(samples, n=100, method="inclusive")[94]


async def test_el_costo_de_la_sombra_es_de_a_lo_sumo_5_ms_p95():
    """Pasarela (`pre_request` + `pre_engine`, con la política ya cacheada) + guard del motor sobre el
    mismo pedido. El tiempo del destino y de la red no cuentan: son los del pedido sin sombra."""
    p = plugin(fx.snapshot("shadow"))
    for _ in range(20):                                     # calentamiento: caché de la política, imports, HKDF
        _, out, headers = await through_gateway(p)
    samples = []
    for _ in range(400):
        t0 = time.perf_counter()
        c = fx.ctx()
        await p.pre_request(c)
        out, headers = p.pre_engine(c, dict(BODY), dict(CLIENT_HEADERS))
        guard.apply_redirect({**out, "proxy_server_request": {"headers": dict(headers)}, "metadata": {}},
                             environ={})
        samples.append((time.perf_counter() - t0) * 1000)
    p95 = _p95(samples)
    assert p95 <= 5.0, f"sombra: p95 = {p95:.2f} ms (> 5 ms); mediana {statistics.median(samples):.2f} ms"
