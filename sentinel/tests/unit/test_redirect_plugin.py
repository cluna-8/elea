"""Plugin de pasarela (T038/T054/T055/T057–T059): lógica de los hooks sin la pasarela real."""
import json

import pytest

from sentinel.engine import redirect_guard as guard
from sentinel.redirect import authz
from sentinel.redirect.plugin import RedirectPlugin, STATE_KEY, hide_rdx
from sentinel.redirect.store import StoreUnavailable
from sentinel.tests import redirect_fixtures as fx


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setenv(authz.KEY_ENV, fx.INTERNAL_KEY)


def plugin(snap=None, **kw):
    return RedirectPlugin(store=fx.store(snap, **kw), ping_after=0.05)


# ── identidad y listados ──────────────────────────────────────────────────────

def test_models_filter_siempre_oculta_rdx():
    listing = {"data": [{"id": "a"}, {"id": "rdx-chatcompat/gpt-image"}, {"id": "b"}],
               "first_id": "a", "last_id": "b"}
    out = plugin().models_filter(fx.ctx(route="/v1/models", model=None), listing)
    assert [m["id"] for m in out["data"]] == ["a", "b"]
    assert hide_rdx({"object": "list", "data": [{"id": "x"}]}) == {"object": "list", "data": [{"id": "x"}]}


async def test_sin_filas_sale_temprano_y_no_toca_nada():
    p = plugin(None)
    c = fx.ctx()
    assert await p.pre_request(c) is None
    body = {"model": "pro", "messages": [], "api_base": "http://x"}
    assert p.pre_engine(c, dict(body), {"a": "1"}) == (body, {"a": "1"})
    it = object()
    assert p.wrap_stream(c, it) is it
    assert p.map_response(c, 200, b'{"model":"x"}') is None
    assert p.map_error(c, 500, b"{}") is None
    assert c.state == {} and c.routing_decision is None and c.governance_overrides == {}


async def test_politica_off_explicita_es_identidad():
    c = fx.ctx()
    assert await plugin(fx.snapshot("off")).pre_request(c) is None
    assert c.state == {}


async def test_modelo_no_publicado_sigue_su_camino():
    c = fx.ctx(model="modelo-de-la-base")
    assert await plugin(fx.snapshot("on")).pre_request(c) is None
    assert STATE_KEY not in c.state


# ── cara genérica ─────────────────────────────────────────────────────────────

async def test_on_reescribe_modelo_firma_y_quita_credenciales_del_cliente():
    p, c = plugin(fx.snapshot("on")), fx.ctx()
    assert await p.pre_request(c) is None
    body = {"model": "pro", "messages": [{"role": "user", "content": "hola"}],
            "api_base": "http://atacante", "api_key": "sk-del-cliente", "max_tokens": 99999}
    out, headers = p.pre_engine(c, body, {"Authorization": "Bearer sk-vk"})
    assert out["model"] == "rdx-chatcompat/qwen-destino"
    assert "api_base" not in out and "api_key" not in out and out["max_tokens"] == 8192
    grant = authz.verify(headers[authz.HEADER], expected_model=out["model"])
    assert grant.destination_id == "d-chat" and grant.credential == {"api_key": "sk-destino-chat"}
    assert grant.api_base == "http://destino.local/v1"
    red = c.routing_decision["extensions"]["redirect"]
    assert red["public_id"] == "pro" and red["destination_id"] == "d-chat" and red["shadow"] is False


async def test_el_guard_del_motor_acepta_la_autorizacion_de_la_pasarela():
    p, c = plugin(fx.snapshot("on")), fx.ctx()
    await p.pre_request(c)
    out, headers = p.pre_engine(c, {"model": "pro", "messages": []}, {})
    data = {**out, "proxy_server_request": {"headers": headers}, "metadata": {}}
    res = guard.apply_redirect(data, environ={})
    assert res["api_key"] == "sk-destino-chat" and res["api_base"] == "http://destino.local/v1"
    assert res["metadata"]["_internal_routing_decision"]["extensions"]["redirect"]["public_id"] == "pro"


async def test_map_response_y_map_error_con_id_publico_y_forma_de_cara():
    p, c = plugin(fx.snapshot("on")), fx.ctx()
    await p.pre_request(c)
    st, body, _ = p.map_response(c, 200, b'{"model":"qwen-destino","choices":[]}')
    assert st == 200 and json.loads(body)["model"] == "pro"
    st, body, headers = p.map_error(c, 429, b'{"error":"x"}')
    assert st == 429 and json.loads(body)["error"]["type"] == "rate_limit_error"
    assert "retry-after" in {k.lower() for k in headers}


async def test_sin_destino_elegible_es_404_de_cara():
    snap = fx.snapshot("on", targets=("no-existe",))
    c = fx.ctx()
    r = await plugin(snap).pre_request(c)
    assert r.status_code == 404 and json.loads(r.body)["error"]["code"] == "model_not_found"
    assert c.routing_decision["extensions"]["redirect"]["unavailable"] == "no_eligible_target"


async def test_fr010a_lista_de_la_llave_sobre_el_id_publico():
    c = fx.ctx()
    r = await plugin(fx.snapshot("on"), key_models=["otro"]).pre_request(c)
    assert r.status_code == 404
    c2 = fx.ctx()
    assert await plugin(fx.snapshot("on"), key_models=["pro"]).pre_request(c2) is None
    assert c2.state[STATE_KEY].engine_model == "rdx-chatcompat/qwen-destino"


# ── postura por defecto del tráfico redirigido ───────────────────────────────

async def test_postura_por_defecto_redirigido_es_la_region_del_tenant():
    """Sin filas de postura, el tráfico REDIRIGIDO de un tenant `eu` solo va a destinos UE."""
    snap = fx.snapshot("on", targets=("d-ant", "d-chat"))   # d-ant (US) primero
    c = fx.ctx()
    await plugin(snap).pre_request(c)
    plan = c.state[STATE_KEY]
    assert plan.destination["id"] == "d-chat"
    assert c.routing_decision["extensions"]["redirect"]["substitution_reason"] == "residency"


async def test_region_us_ve_el_destino_us_y_solo_us_da_403_region():
    snap = fx.snapshot("on", targets=("d-ant",))
    c = fx.ctx(nlp={"region": "us"})
    assert await plugin(snap).pre_request(c) is None
    assert c.state[STATE_KEY].destination["id"] == "d-ant"
    r = await plugin(snap).pre_request(fx.ctx())             # tenant eu
    assert r.status_code == 403 and json.loads(r.body)["error"]["code"] == "region_not_allowed"


# ── cara Claude ───────────────────────────────────────────────────────────────

async def test_cara_claude_traducida_normaliza_y_rechaza_capacidad():
    p = RedirectPlugin(store=fx.store(fx.snapshot("on")), ping_after=0.05, audit=lambda *a, **k: True)
    c = fx.ctx(route="/v1/messages", model="claude-sonnet-4-5")
    await p.pre_request(c)
    body = {"model": "claude-sonnet-4-5", "max_tokens": 10, "context_management": {"x": 1},
            "messages": [{"role": "user", "content": [{"type": "text", "text": "hola",
                                                       "cache_control": {"type": "ephemeral"}}]}]}
    out, headers = p.pre_engine(c, body, {})
    assert out["model"] == "rdx-chatcompat/qwen-destino" and "context_management" not in out
    assert "cache_control" not in json.dumps(out) and authz.HEADER in headers
    c2 = fx.ctx(route="/v1/messages", model="claude-sonnet-4-5")
    await p.pre_request(c2)
    img = {"model": "claude-sonnet-4-5", "max_tokens": 10, "messages": [
        {"role": "user", "content": [{"type": "image", "source": {}}]}]}
    out, headers = p.pre_engine(c2, img, {})
    assert out["model"].startswith("rdx-rejected") and authz.HEADER not in headers
    st, body, _ = p.map_error(c2, 403, b"{}")
    err = json.loads(body)
    assert st == 400 and err["type"] == "error" and err["error"]["message"].startswith("capability_rejected: images")


async def test_cara_claude_nativa_reenvia_beta_y_no_normaliza():
    snap = fx.snapshot("on", claude_targets=("d-ant",))
    p = plugin(snap)
    c = fx.ctx(route="/v1/messages", model="claude-sonnet-4-5", nlp={"region": "us"})
    await p.pre_request(c)
    assert p.forward_headers_allowlist(c) == {"anthropic-beta"}
    body = {"model": "claude-sonnet-4-5", "max_tokens": 10, "context_management": {"x": 1},
            "messages": []}
    out, headers = p.pre_engine(c, body, {})
    assert out["model"] == "rdx-anthropic/claude-real" and out["context_management"] == {"x": 1}
    assert authz.verify(headers[authz.HEADER]).credential == {"api_key": "env:REDIRECT_CRED_ANT"}


async def test_cara_claude_stream_con_ping_y_modelo_publico():
    import asyncio
    p = plugin(fx.snapshot("on"))
    c = fx.ctx(route="/v1/messages", model="claude-sonnet-4-5")
    await p.pre_request(c)

    async def upstream():
        yield b'event: message_start\ndata: {"type":"message_start","message":{"model":"qwen-destino"}}\n\n'
        await asyncio.sleep(0.2)
        yield b'event: message_stop\ndata: {"type":"message_stop"}\n\n'

    chunks = [ch async for ch in p.wrap_stream(c, upstream())]
    joined = b"".join(chunks)
    assert b'"model":"claude-sonnet-4-5"' in joined and b"qwen-destino" not in joined
    assert b"event: ping" in joined
    assert joined.index(b"message_start") < joined.index(b"event: ping") < joined.index(b"message_stop")


async def test_vista_de_modelos_por_cabeceras():
    p = plugin(fx.snapshot("on"))
    c = fx.ctx(route="/v1/models", model=None, headers={"anthropic-version": "2023-06-01"})
    await p.pre_request(c)
    view = p.models_filter(c, {"data": [{"id": "base"}]})
    assert [m["id"] for m in view["data"]] == ["claude-sonnet-4-5"]
    assert view["data"][0]["display_name"] == "Sonnet · servido por Qwen UE · sin imágenes"
    assert view["data"][0]["max_input_tokens"] == 128000
    c2 = fx.ctx(route="/v1/models", model=None)
    await p.pre_request(c2)
    view = p.models_filter(c2, {"data": [{"id": "base"}]})
    assert view["object"] == "list" and [m["id"] for m in view["data"]] == ["pro"]


# ── sombra ────────────────────────────────────────────────────────────────────

async def test_sombra_no_cambia_el_pedido_y_firma_la_decision_para_el_mismo_modelo():
    p, c = plugin(fx.snapshot("shadow")), fx.ctx()
    assert await p.pre_request(c) is None
    body = {"model": "pro", "messages": [], "api_base": "http://cliente"}
    out, headers = p.pre_engine(c, dict(body), {"x": "1"})
    assert out == body
    grant = authz.verify(headers[authz.HEADER], expected_model="pro")
    assert grant.decision["shadow"] is True and grant.decision["shadow_destination_id"] == "d-chat"
    assert grant.credential == {}
    it = object()
    assert p.wrap_stream(c, it) is it and p.map_response(c, 200, b'{"model":"pro"}') is None
    data = {**out, "proxy_server_request": {"headers": headers}, "metadata": {}}
    res = guard.apply_redirect(data, environ={})
    assert res["metadata"]["_internal_routing_decision"]["extensions"]["redirect"]["shadow"] is True
    assert "api_key" not in res


async def test_sombra_sin_clave_interna_no_afecta(monkeypatch):
    monkeypatch.delenv(authz.KEY_ENV)
    p, c = plugin(fx.snapshot("shadow")), fx.ctx()
    await p.pre_request(c)
    out, headers = p.pre_engine(c, {"model": "pro"}, {})
    assert out == {"model": "pro"} and authz.HEADER not in headers


# ── fail-closed y suscripción ────────────────────────────────────────────────

async def test_store_caido_con_politica_on_conocida_es_503():
    snaps = {"n": 0}

    def loader(t):
        snaps["n"] += 1
        if snaps["n"] > 1:
            raise RuntimeError("db caída")
        return fx.snapshot("on")

    from sentinel.redirect.store import RedirectStore
    st = RedirectStore(loader=loader, ttl=0, key_models=lambda k: None, redis_factory=lambda: None,
                       decrypt=lambda b: json.loads(b))
    p = RedirectPlugin(store=st)
    assert await p.pre_request(fx.ctx()) is None
    r = await p.pre_request(fx.ctx())
    assert r.status_code == 503


async def test_store_caido_sin_conocimiento_previo_es_identidad():
    from sentinel.redirect.store import RedirectStore

    def loader(t):
        raise RuntimeError("db caída")

    st = RedirectStore(loader=loader, ttl=0, key_models=lambda k: None, redis_factory=lambda: None)
    assert await RedirectPlugin(store=st).pre_request(fx.ctx()) is None
    with pytest.raises(StoreUnavailable):
        st.snapshot(fx.TENANT)


async def test_tablas_ausentes_son_politica_apagada():
    from sentinel.redirect.store import EMPTY, RedirectStore

    def loader(t):
        raise RuntimeError('relation "sentinel_redirect_policy" does not exist')

    st = RedirectStore(loader=loader, ttl=0, key_models=lambda k: None, redis_factory=lambda: None)
    assert st.snapshot(fx.TENANT) is EMPTY


async def test_suscripcion_con_allowlist_ue_es_403_y_sin_postura_identidad():
    posture = [{"tenant_id": fx.TENANT, "scope_type": "tenant", "scope_value": "*",
                "mode": "allowlist", "jurisdictions": ["EU"]}]
    c = fx.ctx(route="/v1/messages", model="claude-x", mode="subscription")
    r = await plugin(fx.snapshot("off", postures=posture)).pre_request(c)
    assert r.status_code == 403 and json.loads(r.body)["error"]["type"] == "permission_error"
    c2 = fx.ctx(route="/v1/messages", model="claude-x", mode="subscription")
    assert await plugin(fx.snapshot("on")).pre_request(c2) is None


async def test_suscripcion_offregion_masked_fuerza_enmascarado():
    posture = [{"tenant_id": fx.TENANT, "scope_type": "tenant", "scope_value": "*",
                "mode": "offregion_masked", "jurisdictions": []}]
    c = fx.ctx(route="/v1/messages", model="claude-x", mode="subscription")
    assert await plugin(fx.snapshot("off", postures=posture)).pre_request(c) is None
    assert c.governance_overrides == {"pii_masking": True, "nlp_fail_mode": "block", "masking_scope": "full"}


async def test_cache_se_invalida_con_bump():
    calls = []

    def loader(t):
        calls.append(t)
        return fx.snapshot("on")

    from sentinel.redirect.store import RedirectStore
    st = RedirectStore(loader=loader, ttl=60, key_models=lambda k: None, redis_factory=lambda: None)
    st.snapshot(fx.TENANT)
    st.snapshot(fx.TENANT)
    assert len(calls) == 1
    st.bump(fx.TENANT)
    st.snapshot(fx.TENANT)
    assert len(calls) == 2
    st.bump(None)
    st.snapshot(fx.TENANT)
    assert len(calls) == 3



async def test_el_precio_del_destino_viaja_en_la_autorizacion():
    snap = fx.snapshot("on")
    snap.destinations["d-chat"] = {**fx.DEST_CHAT, "price_override": {"input_per_mtok": 0.29, "output_per_mtok": 1.14}}
    p, c = plugin(snap), fx.ctx()
    assert await p.pre_request(c) is None
    out, headers = p.pre_engine(c, {"model": "pro", "messages": [{"role": "user", "content": "hola"}]}, {})
    assert authz.verify(headers[authz.HEADER], expected_model=out["model"]).price == \
        {"input_per_mtok": 0.29, "output_per_mtok": 1.14}


async def test_captura_del_agente_se_omite_y_queda_en_routing_decision():
    """F5 del 29-sep: la captura de Cowork (imagen en un `tool_result` del turno actual) ya no
    corta la tarea con un destino sin visión; lo omitido queda auditado en la decisión, tanto la
    de la pasarela como la firmada que registra el motor."""
    p = plugin(fx.snapshot("on"))
    c = fx.ctx(route="/v1/messages", model="claude-sonnet-4-5")
    await p.pre_request(c)
    img = {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "iVBOR"}}
    body = {"model": "claude-sonnet-4-5", "max_tokens": 10, "messages": [
        {"role": "user", "content": [img, {"type": "text", "text": "¿qué ves?"}]},
        {"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "name": "shot", "input": {}}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": [img]}]}]}
    out, headers = p.pre_engine(c, body, {})
    assert out["model"] == "rdx-chatcompat/qwen-destino" and authz.HEADER in headers
    assert '"type": "image"' not in json.dumps(out)
    red = c.routing_decision["extensions"]["redirect"]
    assert set(red["omitted"].split(",")) == {"images_in_history", "images_in_tool_result"}
    data = {**out, "proxy_server_request": {"headers": headers}, "metadata": {}}
    res = guard.apply_redirect(data, environ={})
    signed = res["metadata"]["_internal_routing_decision"]["extensions"]["redirect"]
    assert signed["omitted"] == red["omitted"]


async def test_sin_nada_omitido_la_decision_no_trae_omitted():
    p = plugin(fx.snapshot("on"))
    c = fx.ctx(route="/v1/messages", model="claude-sonnet-4-5")
    await p.pre_request(c)
    p.pre_engine(c, {"model": "claude-sonnet-4-5", "max_tokens": 10,
                     "messages": [{"role": "user", "content": "hola"}]}, {})
    assert "omitted" not in c.routing_decision["extensions"]["redirect"]


# ── auditoría de los rechazos por capacidad (069 FR-008c) ─────────────────────────────
# El rechazo se decide en pre_engine y el motor lo corta antes de llamar a nadie: el logger del
# motor solo corre en éxito y el gateway byok no audita los errores del motor. Sin esto, el
# rechazo no dejaba ninguna fila (verificado en nix el 29-sep).

class _Auditor:
    def __init__(self, falla=False):
        self.filas, self.falla = [], falla

    def __call__(self, ident, model, in_tok, out_tok, status, masked, latency, attribution=None, **kw):
        if self.falla:
            raise RuntimeError("base caída")
        self.filas.append({"ident": ident, "model": model, "status": status, "latency": latency,
                           "tokens": (in_tok, out_tok), **kw})
        return True


IMG_BODY = {"model": "claude-sonnet-4-5", "max_tokens": 10, "messages": [
    {"role": "user", "content": [{"type": "image", "source": {}}, {"type": "text", "text": "¿qué es?"}]}]}


async def _rechazado(auditor):
    p = RedirectPlugin(store=fx.store(fx.snapshot("on")), ping_after=0.05, audit=auditor)
    c = fx.ctx(route="/v1/messages", model="claude-sonnet-4-5")
    await p.pre_request(c)
    p.pre_engine(c, json.loads(json.dumps(IMG_BODY)), {})
    return p, c


async def test_el_rechazo_por_capacidad_deja_fila_con_motivo_modelo_y_destino():
    aud = _Auditor()
    p, c = await _rechazado(aud)
    st, body, _ = p.map_error(c, 403, b'{"code": "authz_missing"}')
    assert st == 400 and b"capability_rejected: images" in body        # la respuesta no cambia
    assert len(aud.filas) == 1
    fila = aud.filas[0]
    assert fila["model"] == "claude-sonnet-4-5" and fila["status"] == "blocked_by_policy"
    assert fila["tokens"] == (0, 0) and fila["ident"]["tenant_id"] == fx.TENANT
    red = fila["routing_decision"]["extensions"]["redirect"]
    assert red["rejected"] == "images" and red["destination_id"] == "d-chat"
    assert red["destination_name"] == "Qwen UE" and red["public_id"] == "claude-sonnet-4-5"


async def test_la_fila_del_rechazo_no_lleva_contenido():
    aud = _Auditor()
    p, c = await _rechazado(aud)
    p.map_error(c, 403, b"{}")
    assert "qué es" not in json.dumps(aud.filas[0], default=str)


async def test_si_la_auditoria_falla_el_rechazo_sale_igual():
    p, c = await _rechazado(_Auditor(falla=True))
    st, body, _ = p.map_error(c, 403, b"{}")
    assert st == 400 and b"capability_rejected: images" in body


async def test_los_errores_que_no_son_rechazo_propio_no_agregan_fila():
    aud = _Auditor()
    p = RedirectPlugin(store=fx.store(fx.snapshot("on")), ping_after=0.05, audit=aud)
    c = fx.ctx(route="/v1/messages", model="claude-sonnet-4-5")
    await p.pre_request(c)
    p.pre_engine(c, {"model": "claude-sonnet-4-5", "max_tokens": 10,
                     "messages": [{"role": "user", "content": "hola"}]}, {})
    p.map_error(c, 429, b'{"error":"x"}')
    assert aud.filas == []


async def test_el_rechazo_se_audita_una_sola_vez_aunque_map_error_se_repita():
    aud = _Auditor()
    p, c = await _rechazado(aud)
    p.map_error(c, 403, b"{}")
    p.map_error(c, 403, b"{}")
    assert len(aud.filas) == 1


async def test_sin_escritor_inyectado_usa_el_audit_de_la_pasarela(monkeypatch):
    """En producción el escritor es `gateway._audit` del backend (import perezoso)."""
    from src.api import gateway
    aud = _Auditor()
    monkeypatch.setattr(gateway, "_audit", aud)
    p = RedirectPlugin(store=fx.store(fx.snapshot("on")), ping_after=0.05)
    c = fx.ctx(route="/v1/messages", model="claude-sonnet-4-5")
    await p.pre_request(c)
    p.pre_engine(c, json.loads(json.dumps(IMG_BODY)), {})
    p.map_error(c, 403, b"{}")
    assert len(aud.filas) == 1 and aud.filas[0]["status"] == "blocked_by_policy"
