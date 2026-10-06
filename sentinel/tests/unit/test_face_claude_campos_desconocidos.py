"""T139 de Sentinel (FR-035, research R10): hacia un destino traducido solo pasan los campos de la
lista permitida; `safeguards` y cualquier campo desconocido se quitan sin error y sus NOMBRES quedan
en `dropped_fields`. Hacia un nativo no se filtra."""
import json

import pytest

from sentinel.engine import redirect_guard as guard
from sentinel.redirect import authz
from sentinel.redirect.faces import claude as face
from sentinel.redirect.plugin import RedirectPlugin
from sentinel.tests import corpus_claude as corpus
from sentinel.tests import redirect_fixtures as fx

# contracts/cara-claude.md §1: la lista permitida de primer nivel
CONTRATO = {"model", "messages", "system", "max_tokens", "stop_sequences", "stream", "temperature",
            "top_p", "top_k", "tools", "tool_choice", "metadata"}
ADAPTADOS = {"thinking", "output_config", "context_management"}   # los adapta el normalizador
PROFILE_FULL = {"thinking": True, "cache_control": True, "images": True, "documents_pdf": True,
                "mid_system_messages": True}
PROFILE_MIN = {"thinking": False, "cache_control": False}


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setenv(authz.KEY_ENV, fx.INTERNAL_KEY)


def test_la_lista_permitida_es_la_del_contrato():
    assert set(face.FIELD_ALLOWLIST) == CONTRATO


@pytest.mark.parametrize("profile", [PROFILE_MIN, PROFILE_FULL])
def test_safeguards_y_desconocidos_se_quitan_y_quedan_sus_nombres(profile):
    body = corpus.load("claude_code_messages_beta")["body"]
    out, removed = face.normalize_for_translated(body, profile, max_output=8192)
    assert "safeguards" not in out and "campo_futuro_de_la_herramienta" not in out
    assert set(out) <= CONTRATO | {"thinking", "reasoning_effort"}
    assert face.dropped_field_names(removed) == ["campo_futuro_de_la_herramienta", "safeguards"]
    for r in removed:                                   # nunca valores
        assert "enforce" not in r and "default" not in r


def test_los_campos_de_la_lista_pasan_intactos():
    body = {"model": "m", "messages": [{"role": "user", "content": "hola"}], "system": "s", "max_tokens": 10,
            "stop_sequences": ["x"], "stream": True, "temperature": 0.2, "top_p": 0.9, "top_k": 5,
            "tools": [{"name": "t", "input_schema": {"type": "object"}}], "tool_choice": {"type": "auto"},
            "metadata": {"user_id": "u"}}
    out, removed = face.normalize_for_translated(body, PROFILE_MIN, max_output=0)
    assert out == body and face.dropped_field_names(removed) == []


def test_los_campos_que_adapta_el_normalizador_no_cuentan_como_desconocidos():
    body = {"model": "m", "messages": [], "thinking": {"type": "adaptive"}, "output_config": {"effort": "low"},
            "context_management": {"edits": []}}
    out, removed = face.normalize_for_translated(body, PROFILE_FULL, max_output=0)
    assert out["reasoning_effort"] == "low"
    assert face.dropped_field_names(removed) == []


def test_nunca_se_responde_error_por_un_campo_desconocido():
    out, _ = face.normalize_for_translated({"model": "m", "messages": [], "service_tier": "auto",
                                            "container": "c", "mcp_servers": [], "x" * 90: 1},
                                           PROFILE_MIN, max_output=0)
    assert set(out) == {"model", "messages"}


def test_los_nombres_se_acotan_para_la_auditoria():
    # un nombre largo o con caracteres raros no entra tal cual a la auditoría; cantidad acotada
    body = {"model": "m", "messages": [], "x" * 90: 1, "con espacios y datos": 2,
            **{f"campo_{i}": i for i in range(40)}}
    _, removed = face.normalize_for_translated(body, PROFILE_MIN, max_output=0)
    names = face.dropped_field_names(removed)
    assert all(len(n) <= 64 and " " not in n for n in names) and len(names) <= face.MAX_DROPPED_NAMES


def test_la_entrada_no_se_muta():
    body = corpus.load("claude_code_messages_beta")["body"]
    before = json.dumps(body, sort_keys=True)
    face.normalize_for_translated(body, PROFILE_FULL, max_output=10)
    assert json.dumps(body, sort_keys=True) == before


# ── a través del plugin: la auditoría lleva los nombres, nunca los valores ────────────────────

def _plugin(snap):
    return RedirectPlugin(store=fx.store(snap), ping_after=0.05)


async def _pre_engine(snap, body, **ctx_kw):
    p = _plugin(snap)
    c = fx.ctx(route="/v1/messages", model=body["model"], **ctx_kw)
    assert await p.pre_request(c) is None
    out, headers = p.pre_engine(c, body, {})
    return c, out, headers


async def test_traducido_el_pedido_de_claude_code_sale_sin_safeguards_y_se_audita_el_nombre():
    doc = corpus.load("claude_code_messages_beta")
    c, out, headers = await _pre_engine(fx.snapshot("on"), doc["body"])
    assert out["model"] == "rdx-chatcompat/qwen-destino"
    assert "safeguards" not in out and "campo_futuro_de_la_herramienta" not in out
    red = c.routing_decision["extensions"]["redirect"]
    assert red["dropped_fields"] == "campo_futuro_de_la_herramienta,safeguards"
    assert "enforce" not in json.dumps(c.routing_decision)
    # la decisión que firma la pasarela para el guard lleva lo mismo
    grant = authz.verify(headers[authz.HEADER], expected_model=out["model"])
    assert grant.decision["dropped_fields"] == "campo_futuro_de_la_herramienta,safeguards"


async def test_sin_campos_desconocidos_no_hay_dropped_fields():
    c, _, _ = await _pre_engine(fx.snapshot("on"), {"model": "claude-sonnet-4-5", "max_tokens": 5,
                                                   "messages": [{"role": "user", "content": "hola"}]})
    assert "dropped_fields" not in c.routing_decision["extensions"]["redirect"]


async def test_nativo_no_se_filtra():
    doc = corpus.load("claude_code_messages_beta")
    snap = fx.snapshot("on", claude_targets=("d-ant",))
    c, out, _ = await _pre_engine(snap, doc["body"], nlp={"region": "us"})
    assert out["model"] == "rdx-anthropic/claude-real"
    assert out["safeguards"] == doc["body"]["safeguards"]
    assert out["campo_futuro_de_la_herramienta"] == {"x": 1}
    assert "dropped_fields" not in c.routing_decision["extensions"]["redirect"]


async def test_el_guard_del_motor_recibe_el_pedido_sin_safeguards():
    doc = corpus.load("claude_code_messages_beta")
    _, out, headers = await _pre_engine(fx.snapshot("on"), doc["body"])
    data = {**out, "proxy_server_request": {"headers": headers}, "metadata": {}}
    res = guard.apply_redirect(data, environ={})
    assert "safeguards" not in res


async def test_el_valor_auditado_cabe_en_el_limite_del_plano_interno():
    body = {"model": "claude-sonnet-4-5", "max_tokens": 5, "messages": [{"role": "user", "content": "hola"}],
            **{f"campo_desconocido_numero_{i:02d}": i for i in range(15)}}
    c, _, headers = await _pre_engine(fx.snapshot("on"), body)
    value = c.routing_decision["extensions"]["redirect"]["dropped_fields"]
    assert len(value) <= 128 and value.rsplit(",", 1)[-1].startswith("otros_")
    names = value.split(",")[:-1]
    assert names == sorted(names) and all(n.startswith("campo_desconocido_numero_") for n in names)


async def test_tras_una_sustitucion_por_capacidad_la_auditoria_sigue_viendo_lo_nuevo():
    # el destino elegido no ve imágenes: pasa al siguiente (sustitución) y el dict de la decisión no se desdobla
    dest_vision = {**fx.DEST_CHAT, "id": "d-vision", "name": "Con visión",
                   "capability_profile": {**fx.DEST_CHAT["capability_profile"], "images": True}}
    snap = fx.snapshot("on", claude_targets=("d-chat", "d-vision"))
    snap = snap.__class__(**{**snap.__dict__, "destinations": {**snap.destinations, "d-vision": dest_vision},
                             "credentials": {**snap.credentials, "d-vision": fx.CREDS["d-chat"]}})
    body = {"model": "claude-sonnet-4-5", "max_tokens": 5, "safeguards": {"a": 1},
            "messages": [{"role": "user", "content": [{"type": "image", "source": {"type": "base64"}}]}]}
    c, out, _ = await _pre_engine(snap, body)
    red = c.routing_decision["extensions"]["redirect"]
    assert red["destination_id"] == "d-vision" and red["substitution_reason"] == "capability"
    assert red["dropped_fields"] == "safeguards" and "safeguards" not in out
