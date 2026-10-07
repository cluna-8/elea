"""057: el esfuerzo de razonamiento se ajusta a lo que el destino acepta; nunca un 400 por esto.

Azure `gpt-5.1-chat` solo acepta `reasoning_effort: "medium"` (400 con `low`). El conjunto de esfuerzos que admite el
destino vive en su perfil de capacidades (`features.reasoning_efforts`, dato editable del catálogo); `gpt-5.1-chat`
trae `["medium"]` como valor conocido aunque la entrada no lo declare. Si el pedido trae otro valor, se mapea al más
cercano que el destino admite y el ajuste queda en `adjusted_params` (solo el nombre, nunca el valor). Sin conjunto
declarado ni conocido, el pedido pasa tal cual (como hasta hoy).
"""
import json

import pytest

from sentinel.catalog import models as cm
from sentinel.catalog.api import admin as catalog_admin
from sentinel.engine import redirect_guard as guard
from sentinel.redirect import authz, effort
from sentinel.redirect.plugin import RedirectPlugin
from sentinel.tests import redirect_fixtures as fx


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setenv(authz.KEY_ENV, fx.INTERNAL_KEY)


# ── la elección del más cercano ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("pedido,soportados,esperado", [
    ("low", ["medium"], "medium"),                      # el caso conocido de gpt-5.1-chat
    ("high", ["medium"], "medium"),
    ("minimal", ["medium"], "medium"),
    ("none", ["medium"], "medium"),
    ("xhigh", ["low", "medium", "high"], "high"),
    ("high", ["low", "medium"], "medium"),
    ("minimal", ["low", "high"], "low"),
    ("medium", ["low", "high"], "low"),                 # empate: el más bajo (más barato y más rápido)
    ("low", ["low", "medium", "high"], "low"),          # ya soportado: no se toca
    ("LOW", ["medium"], "medium"),                      # mayúsculas
])
def test_mapea_al_esfuerzo_mas_cercano_que_el_destino_admite(pedido, soportados, esperado):
    assert effort.nearest(pedido, soportados) == esperado


def test_un_valor_desconocido_no_se_toca():
    assert effort.nearest("auto", ["medium"]) == "auto"          # no hay escala para compararlo
    assert effort.nearest("low", []) == "low" and effort.nearest("low", None) == "low"


# ── de dónde sale el conjunto ─────────────────────────────────────────────────────────────

def _dest(real="x-modelo", features=None, provider="azure"):
    return {"provider": provider, "real_model": real, "capability_profile": features or {}}


def test_el_perfil_del_destino_manda():
    assert effort.supported_efforts(_dest(features={"reasoning_efforts": ["low", "high"]})) == ("low", "high")


def test_gpt_5_1_chat_solo_acepta_medium_aunque_la_entrada_no_lo_declare():
    assert effort.supported_efforts(_dest("gpt-5.1-chat")) == ("medium",)


def test_lo_declarado_en_la_entrada_gana_al_valor_conocido():
    assert effort.supported_efforts(_dest("gpt-5.1-chat", {"reasoning_efforts": ["low", "medium"]})) == ("low", "medium")


def test_sin_dato_no_hay_restriccion():
    assert effort.supported_efforts(_dest("gpt-5.4-mini")) is None
    assert effort.supported_efforts(_dest(features={"reasoning_efforts": []})) is None     # lista vacía = sin dato


# ── por la pasarela y el guard ────────────────────────────────────────────────────────────

def _destino(real="gpt-5.1-chat", features=None):
    return {"id": "d-az", "level": "tenant", "tenant_id": fx.TENANT, "name": "Azure chat", "provider": "azure",
            "real_model": real, "protocol_family": "openai_chat", "inference_jurisdiction": "US",
            "entity_jurisdiction": "US", "control_jurisdiction": "US", "blocked_by_default": False,
            "enabled_at": None, "has_credential": True, "api_base": "https://r.openai.azure.com",
            "capability_profile": {"thinking": True, "tools": True, **(features or {})},
            "context_window": 128000, "max_output": 16384, "status": "active"}


async def _al_motor(route, body, dest, *, model="pro"):
    snap = fx.snapshot("on", claude_targets=("d-az",), targets=("d-az",))
    snap = snap.__class__(**{**snap.__dict__, "destinations": {**snap.destinations, "d-az": dest},
                             "credentials": {**snap.credentials, "d-az": json.dumps({"api_key": "k", "api_version": "2025-04-01-preview"})}})
    p = RedirectPlugin(store=fx.store(snap), ping_after=0.05)
    c = fx.ctx(route=route, model=model, nlp={"region": "us"})
    assert await p.pre_request(c) is None
    out, _ = p.pre_engine(c, dict(body, model=model), {})
    return c, out


async def test_cara_generica_low_hacia_gpt_5_1_chat_sale_medium_y_queda_registrado():
    c, out = await _al_motor("/v1/chat/completions", {"messages": [{"role": "user", "content": "hola"}],
                                                      "reasoning_effort": "low"}, _destino())
    assert out["reasoning_effort"] == "medium"
    assert "reasoning_effort" in c.routing_decision["extensions"]["redirect"]["adjusted_params"].split(",")
    assert '"low"' not in json.dumps(c.routing_decision)                # solo el nombre, nunca el valor


async def test_cara_claude_effort_low_hacia_gpt_5_1_chat_sale_medium():
    body = {"max_tokens": 100, "messages": [{"role": "user", "content": "hola"}],
            "thinking": {"type": "adaptive"}, "output_config": {"effort": "low"}}
    c, out = await _al_motor("/v1/messages", body, _destino(), model="claude-sonnet-4-5")
    assert out["reasoning_effort"] == "medium"
    assert "reasoning_effort" in c.routing_decision["extensions"]["redirect"]["adjusted_params"].split(",")


async def test_responses_reasoning_effort_anidado_tambien_se_ajusta():
    c, out = await _al_motor("/v1/chat/completions", {"messages": [{"role": "user", "content": "hola"}],
                                                      "reasoning": {"effort": "high", "summary": "auto"}}, _destino())
    assert out["reasoning"] == {"effort": "medium", "summary": "auto"}


async def test_un_esfuerzo_soportado_pasa_sin_ajuste():
    c, out = await _al_motor("/v1/chat/completions", {"messages": [{"role": "user", "content": "hola"}],
                                                      "reasoning_effort": "medium"}, _destino())
    assert out["reasoning_effort"] == "medium"
    assert "adjusted_params" not in c.routing_decision["extensions"]["redirect"]


async def test_destino_sin_conjunto_conocido_pasa_el_pedido_tal_cual():
    c, out = await _al_motor("/v1/chat/completions", {"messages": [{"role": "user", "content": "hola"}],
                                                      "reasoning_effort": "low"}, _destino("gpt-5.4-mini"))
    assert out["reasoning_effort"] == "low"
    assert "adjusted_params" not in c.routing_decision["extensions"]["redirect"]


async def test_sin_reasoning_effort_en_el_pedido_no_se_agrega_ninguno():
    c, out = await _al_motor("/v1/chat/completions", {"messages": [{"role": "user", "content": "hola"}]}, _destino())
    assert "reasoning_effort" not in out and "reasoning" not in out


async def test_el_conjunto_de_la_ficha_se_respeta_en_la_pasarela():
    c, out = await _al_motor("/v1/chat/completions", {"messages": [{"role": "user", "content": "hola"}],
                                                      "reasoning_effort": "minimal"},
                             _destino("gpt-5.4-mini", {"reasoning_efforts": ["low", "high"]}))
    assert out["reasoning_effort"] == "low"


async def test_el_guard_conserva_el_ajuste_de_la_pasarela_y_suma_los_suyos():
    snap = fx.snapshot("on", claude_targets=("d-az",), targets=("d-az",))
    dest = _destino()
    snap = snap.__class__(**{**snap.__dict__, "destinations": {**snap.destinations, "d-az": dest},
                             "credentials": {**snap.credentials, "d-az": json.dumps({"api_key": "k", "api_version": "2025-04-01-preview"})}})
    p = RedirectPlugin(store=fx.store(snap), ping_after=0.05)
    c = fx.ctx(route="/v1/chat/completions", model="pro", nlp={"region": "us"})
    assert await p.pre_request(c) is None
    out, headers = p.pre_engine(c, {"model": "pro", "messages": [{"role": "user", "content": "hola"}],
                                    "reasoning_effort": "low", "max_tokens": 5}, {})
    data = {**out, "proxy_server_request": {"headers": {authz.HEADER: headers[authz.HEADER]}}, "metadata": {}}
    data = guard.apply_redirect(data, key=fx.INTERNAL_KEY, call_type="acompletion", environ={})
    ajustes = data["metadata"]["_internal_routing_decision"]["extensions"]["redirect"]["adjusted_params"].split(",")
    assert "reasoning_effort" in ajustes and "max_tokens->max_completion_tokens" in ajustes
    assert data["reasoning_effort"] == "medium"


# ── la ficha del catálogo acepta el conjunto ──────────────────────────────────────────────

def test_la_api_del_catalogo_acepta_reasoning_efforts_en_features():
    catalog_admin._check_vocab(features={"thinking": True, "reasoning_efforts": ["low", "medium"]})


@pytest.mark.parametrize("features", [
    {"reasoning_efforts": "medium"},                    # no es lista
    {"reasoning_efforts": ["extremo"]},                 # valor fuera de la escala
    {"reasoning_efforts": [1]},
    {"reasoning_efforts": ["low", "low"]},              # duplicados
    {"thinking": "si"},                                 # el resto de las claves siguen siendo booleanas
])
def test_la_api_del_catalogo_rechaza_valores_invalidos(features):
    with pytest.raises(Exception) as e:
        catalog_admin._check_vocab(features=features)
    assert getattr(e.value, "status_code", 422) == 422


def test_reasoning_efforts_es_una_clave_conocida_del_catalogo():
    assert "reasoning_efforts" in cm.FEATURE_LISTS


def test_el_seed_de_azure_declara_que_gpt_5_1_chat_solo_acepta_medium():
    import yaml
    from pathlib import Path
    seed = yaml.safe_load((Path(__file__).resolve().parents[3] / "deploy" / "redirect-seeds"
                           / "catalog-seed.azure-demo.yaml").read_text(encoding="utf-8"))
    por = {e["name"]: e for e in seed["entries"]}
    assert por["gpt-5.1-chat"]["features"]["reasoning_efforts"] == ["medium"]
    assert effort.supported_efforts({"real_model": "gpt-5.1-chat",
                                     "capability_profile": por["gpt-5.1-chat"]["features"]}) == ("medium",)
