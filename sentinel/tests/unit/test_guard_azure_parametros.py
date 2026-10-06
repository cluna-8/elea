"""Sondeo de arranque contra Azure (US1 esc. 8, FR-035; HANDOFF §2.2 pasos 7–8; research R9).

Claude Desktop sondea con `max_tokens: 1` y Azure (como OpenAI) rechaza menos de 16: el guard sube el límite a
16; y los modelos gpt-5.x de Azure por chat solo aceptan `max_completion_tokens`, así que `max_tokens` se
renombra. Ambos ajustes quedan en `adjusted_params` (solo los nombres). El guard copiado ya lo hace: acá se
prueba con un destino de Azure del catálogo de ejemplo, desde el pedido real del corpus y por la pasarela.
"""
import json

import pytest

from sentinel.engine import redirect_guard as guard
from sentinel.redirect import authz, credentials
from sentinel.redirect.plugin import RedirectPlugin
from sentinel.tests import corpus_claude as corpus
from sentinel.tests import redirect_fixtures as fx

AZURE_KEY = "sk-azure-de-prueba-del-recurso"      # secret-scanner: allow (valor inventado de un fixture de test)
DEST_AZURE = {
    "id": "d-azure", "level": "tenant", "tenant_id": fx.TENANT, "name": "gpt-5.4-mini", "provider": "azure",
    "real_model": "gpt-5.4-mini", "protocol_family": "openai_chat", "inference_jurisdiction": "US",
    "entity_jurisdiction": "US", "blocked_by_default": False, "enabled_at": None, "has_credential": True,
    "api_base": "https://recurso.openai.azure.com", "provider_options": {},
    "capability_profile": {"tools": True, "images": True, "documents_pdf": False}, "context_window": 400000,
    "max_output": 128000, "status": "active",
}
CREDS = {"d-azure": json.dumps({"api_key": AZURE_KEY, "api_version": "2025-04-01-preview"})}


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setenv(authz.KEY_ENV, fx.INTERNAL_KEY)


def _snapshot():
    snap = fx.snapshot("on", claude_targets=("d-azure",))
    return snap.__class__(**{**snap.__dict__, "destinations": {**snap.destinations, "d-azure": DEST_AZURE},
                             "credentials": {**snap.credentials, **CREDS}})


async def _al_motor(body, *, call_type="anthropic_messages", model="claude-haiku-4-5", inject=None):
    """Pasarela → autorización firmada → guard del motor, con el call_type con el que el motor recibe el pedido."""
    snap = _snapshot()
    snap = snap.__class__(**{**snap.__dict__, "published": snap.published + (
        {"id": "p-h", "tenant_id": fx.TENANT, "scope_type": "tenant", "scope_value": "*", "face": "claude",
         "public_id": "claude-haiku-4-5", "family_tier": "haiku", "is_family_default": True},),
        "rules": snap.rules + ({"id": "r-h", "tenant_id": fx.TENANT, "scope_type": "tenant", "scope_value": "*",
                                "published_model_id": "p-h", "targets": ["d-azure"]},)})
    p = RedirectPlugin(store=fx.store(snap), ping_after=0.05)
    c = fx.ctx(route="/v1/messages", model=model, nlp={"region": "us"})     # destino en EE. UU. dentro de la región
    assert await p.pre_request(c) is None
    out, headers = p.pre_engine(c, dict(body, model=model), {})
    data = {**out, **(inject or {}), "proxy_server_request": {"headers": {authz.HEADER: headers[authz.HEADER]}},
            "metadata": {}}
    data = guard.apply_redirect(data, key=fx.INTERNAL_KEY, call_type=call_type, environ={})
    home = data["litellm_metadata"] if call_type == "anthropic_messages" else data["metadata"]   # donde el motor lee la decisión
    return data, home["_internal_routing_decision"]["extensions"]["redirect"]


async def test_el_sondeo_de_claude_desktop_sube_a_16_y_queda_auditado():
    doc = corpus.load("claude_desktop_sondeo")
    data, red = await _al_motor(doc["body"])
    assert doc["body"]["max_tokens"] == 1 and data["max_tokens"] == 16
    assert red["adjusted_params"] == "max_tokens"


async def test_un_limite_normal_por_la_cara_claude_no_se_toca():
    data, red = await _al_motor({"max_tokens": 4096, "messages": [{"role": "user", "content": "hola"}]})
    assert data["max_tokens"] == 4096 and "adjusted_params" not in red


async def test_por_chat_el_sondeo_sale_como_max_completion_tokens_16():
    # el mismo destino atendido por /chat/completions (cara genérica o ruta directa del motor)
    data, red = await _al_motor({"max_tokens": 1, "messages": [{"role": "user", "content": "hi"}]}, call_type="acompletion")
    assert data["max_completion_tokens"] == 16 and "max_tokens" not in data
    assert red["adjusted_params"] == "max_tokens->max_completion_tokens,max_completion_tokens"


async def test_por_chat_un_limite_normal_solo_cambia_de_nombre():
    data, red = await _al_motor({"max_tokens": 1000, "messages": [{"role": "user", "content": "hi"}]}, call_type="acompletion")
    assert data["max_completion_tokens"] == 1000 and "max_tokens" not in data
    assert red["adjusted_params"] == "max_tokens->max_completion_tokens"


async def test_con_los_dos_limites_manda_el_valido_y_se_quita_el_viejo():
    # la cara Claude no deja pasar `max_completion_tokens` (no es de la Messages API); por la ruta directa sí
    data, red = await _al_motor({"max_tokens": 5, "messages": [{"role": "user", "content": "hi"}]},
                                call_type="acompletion", inject={"max_completion_tokens": 500})
    assert data["max_completion_tokens"] == 500 and "max_tokens" not in data and red["adjusted_params"] == "max_tokens"


async def test_el_pedido_llega_a_azure_con_el_despliegue_la_credencial_y_la_version():
    data, _ = await _al_motor(corpus.load("claude_desktop_sondeo")["body"])
    assert data["model"] == credentials.family_model("azure", "gpt-5.4-mini") == "rdx-azure/gpt-5.4-mini"
    assert data["api_key"] == AZURE_KEY and data["api_version"] == "2025-04-01-preview"
    assert data["api_base"] == "https://recurso.openai.azure.com"


async def test_la_auditoria_lleva_nombres_nunca_valores_ni_secretos():
    data, red = await _al_motor(corpus.load("claude_desktop_sondeo")["body"])
    meta = json.dumps([data.get("metadata"), data.get("litellm_metadata")], default=str)
    assert AZURE_KEY not in meta and '"hi"' not in meta
    assert set(red["adjusted_params"].split(",")) <= {"max_tokens", "max_completion_tokens", "max_tokens->max_completion_tokens"}


async def test_un_destino_que_no_es_de_openai_o_azure_no_se_ajusta():
    # el sondeo hacia otro proveedor (p. ej. un compatible con OpenAI) sale tal cual
    dest = {**DEST_AZURE, "provider": "openai_compatible", "api_base": "http://destino/v1"}
    snap = fx.snapshot("on", claude_targets=("d-azure",))
    snap = snap.__class__(**{**snap.__dict__, "destinations": {**snap.destinations, "d-azure": dest},
                             "credentials": {**snap.credentials, "d-azure": json.dumps({"api_key": "k"})}})
    p = RedirectPlugin(store=fx.store(snap), ping_after=0.05)
    c = fx.ctx(route="/v1/messages", model="claude-sonnet-4-5", nlp={"region": "us"})
    assert await p.pre_request(c) is None
    out, headers = p.pre_engine(c, {"model": "claude-sonnet-4-5", "max_tokens": 1,
                                    "messages": [{"role": "user", "content": "hi"}]}, {})
    data = {**out, "proxy_server_request": {"headers": {authz.HEADER: headers[authz.HEADER]}}, "metadata": {}}
    data = guard.apply_redirect(data, key=fx.INTERNAL_KEY, call_type="anthropic_messages", environ={})
    assert data["max_tokens"] == 1
