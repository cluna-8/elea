"""T058 (057 FR-032; research R19): OpenRouter con cero retención en cada pedido.

Todo pedido a un destino `openrouter` sale con cero retención (`zdr`), sin recolección de datos
(`data_collection = deny`) y solo a la lista de proveedores permitidos de la entrada; las preferencias de proveedor
que mande el cliente se ignoran; sin lista el guard no sirve el pedido (el alta ya da 422: `contract/
test_catalog_openrouter_zdr.py`); `openrouter_zdr: true` en la auditoría.

Referencia de la API de OpenRouter, «Provider Routing» (https://openrouter.ai/docs/features/provider-routing,
consultada el 2026-10-06): el objeto `provider` de la solicitud admite `only` (lista de slugs de proveedor),
`order`, `allow_fallbacks` (booleano), `ignore`, `require_parameters`, `data_collection` (`"allow"` | `"deny"`) y
`zdr` (booleano: «restringir el enrutamiento a endpoints de retención cero»). LiteLLM los pasa por `extra_body`."""
import json

import pytest

from sentinel.engine import redirect_guard as guard
from sentinel.redirect import authz
from sentinel.redirect.plugin import RedirectPlugin
from sentinel.tests import redirect_fixtures as fx

OR_KEY = "sk-or-de-prueba-del-destino"      # secret-scanner: allow (valor inventado de un fixture de test)
LISTA = ["acme-us", "otro-us"]


def destino(**opts):
    return {"id": "d-or", "level": "tenant", "tenant_id": fx.TENANT, "name": "Qwen por OpenRouter",
            "provider": "openrouter", "real_model": "qwen/qwen3-max", "protocol_family": "openai_chat",
            "inference_jurisdiction": "US", "entity_jurisdiction": "US", "control_jurisdiction": "US",
            "blocked_by_default": False, "enabled_at": None, "has_credential": True, "api_base": None,
            "is_aggregator": True, "provider_options": opts, "capability_profile": {"tools": True},
            "context_window": 128000, "max_output": 8192, "status": "active"}


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setenv(authz.KEY_ENV, fx.INTERNAL_KEY)


async def _al_motor(dest, body=None, *, inject=None, call_type="acompletion"):
    snap = fx.snapshot("on", claude_targets=("d-or",), targets=("d-or",))
    snap = snap.__class__(**{**snap.__dict__, "destinations": {**snap.destinations, "d-or": dest},
                             "credentials": {**snap.credentials, "d-or": json.dumps({"api_key": OR_KEY})}})
    p = RedirectPlugin(store=fx.store(snap), ping_after=0.05)
    c = fx.ctx(route="/v1/chat/completions", model="pro", nlp={"region": "us"})
    assert await p.pre_request(c) is None
    out, headers = p.pre_engine(c, dict(body or {"messages": [{"role": "user", "content": "hola"}]}, model="pro"), {})
    data = {**out, **(inject or {}), "proxy_server_request": {"headers": {authz.HEADER: headers[authz.HEADER]}},
            "metadata": {}}
    data = guard.apply_redirect(data, key=fx.INTERNAL_KEY, call_type=call_type, environ={})
    return data, data["metadata"]["_internal_routing_decision"]["extensions"]["redirect"]


async def test_todo_pedido_sale_con_cero_retencion_sin_recoleccion_y_solo_a_la_lista():
    data, red = await _al_motor(destino(providers_allowlist=LISTA))
    prov = data["extra_body"]["provider"]
    assert prov["zdr"] is True and prov["data_collection"] == "deny"
    assert prov["only"] == LISTA
    assert red["openrouter_zdr"] is True


async def test_sin_fallbacks_fuera_de_la_lista():
    data, _ = await _al_motor(destino(providers_allowlist=LISTA))
    prov = data["extra_body"]["provider"]
    # `only` limita el enrutamiento (y sus reintentos) a esos proveedores: ninguno fuera de la lista
    assert set(prov["only"]) == set(LISTA) and "order" not in prov and "ignore" not in prov


async def test_las_preferencias_de_proveedor_del_cliente_se_ignoran():
    cliente = {"order": ["malo"], "only": ["malo"], "zdr": False, "data_collection": "allow", "allow_fallbacks": True}
    data, _ = await _al_motor(destino(providers_allowlist=LISTA),
                              inject={"provider": cliente, "extra_body": {"provider": cliente, "route": "fallback",
                                                                         "models": ["x/y"], "otra": 1}})
    assert "provider" not in data                                       # el campo de primer nivel del cliente se descarta
    prov = data["extra_body"]["provider"]
    assert prov["only"] == LISTA and prov["zdr"] is True and prov["data_collection"] == "deny"
    assert "malo" not in json.dumps(prov)
    assert "route" not in data["extra_body"] and "models" not in data["extra_body"]
    assert data["extra_body"]["otra"] == 1                              # lo demás del cliente no se toca


async def test_sin_lista_el_guard_no_sirve_el_pedido():
    with pytest.raises(guard.GuardRejection) as e:
        await _al_motor(destino())
    assert e.value.status == 503 and e.value.code == "destination_misconfigured"
    with pytest.raises(guard.GuardRejection):
        await _al_motor(destino(providers_allowlist=[]))


async def test_la_credencial_y_la_base_siguen_siendo_las_del_destino():
    data, _ = await _al_motor(destino(providers_allowlist=LISTA))
    assert data["api_key"] == OR_KEY and data["model"] == "rdx-chatcompat/qwen/qwen3-max"


async def test_un_destino_que_no_es_openrouter_no_lleva_preferencias_ni_marca():
    d = {**destino(providers_allowlist=LISTA), "provider": "openai_compatible", "real_model": "m",
         "api_base": "https://api.ejemplo.com/v1", "is_aggregator": False}
    data, red = await _al_motor(d)
    assert "extra_body" not in data and "openrouter_zdr" not in red


async def test_la_lista_viaja_firmada_en_la_autorizacion():
    snap = fx.snapshot("on", targets=("d-or",))
    snap = snap.__class__(**{**snap.__dict__, "destinations": {**snap.destinations, "d-or": destino(providers_allowlist=LISTA)},
                             "credentials": {**snap.credentials, "d-or": json.dumps({"api_key": OR_KEY})}})
    p = RedirectPlugin(store=fx.store(snap), ping_after=0.05)
    c = fx.ctx(route="/v1/chat/completions", model="pro", nlp={"region": "us"})
    await p.pre_request(c)
    _, headers = p.pre_engine(c, {"model": "pro", "messages": []}, {})
    grant = authz.verify(headers[authz.HEADER], key=fx.INTERNAL_KEY)
    assert grant.provider_options == {"providers_allowlist": LISTA}
    # una autorización manipulada no vale: la firma cubre la lista
    token = headers[authz.HEADER].split(".")
    token[1] = token[1][:-2] + ("AA" if token[1][-2:] != "AA" else "BB")
    with pytest.raises(authz.AuthzError):
        authz.verify(".".join(token), key=fx.INTERNAL_KEY)


async def test_la_auditoria_no_lleva_los_nombres_de_proveedores_ni_secretos():
    _, red = await _al_motor(destino(providers_allowlist=LISTA))
    texto = json.dumps(red)
    assert "acme-us" not in texto and OR_KEY not in texto
