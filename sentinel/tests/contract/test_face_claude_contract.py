"""Contrato de la cara Claude en Eleia (contracts/cara-claude.md; T081/T082 de Sentinel).

Pasarela REAL del backend + motor falso. Cubre FR-016 (`allowed_models` de la llave sobre el id público),
FR-033/FR-034 (`/gw/v1/models`, `Bearer` y `x-api-key`, `?beta=true`, `HEAD /api/hello`), FR-018 (id sin destino,
destino sin credencial, fallback), FR-038 (529, 429, 503), FR-035 (función que el destino no tiene o exclusiva del
proveedor original ⇒ `capability_rejected`), FR-014/FR-050 (nada de internals en lo visible) y FR-047/SC-008 (la
fila de auditoría sin texto del pedido ni secretos).
"""
import json
import re
import time
from pathlib import Path

import pytest

from sentinel.engine import redirect_guard as guard
from sentinel.redirect import authz, resolver
from sentinel.redirect.faces import claude as face
from sentinel.tests import corpus_claude as corpus
from sentinel.tests import gw_harness as h
from sentinel.tests import redirect_fixtures as fx

ROOT = Path(__file__).resolve().parents[3]
PROHIBIDOS = [ln.strip().lower() for ln in (ROOT / "deploy/release/checks/prohibited_names.txt").read_text(
    encoding="utf-8").splitlines() if ln.strip() and not ln.strip().startswith("#")]
US = {"nlp": {"region": "us"}}


@pytest.fixture
def env(monkeypatch):
    e = h.gateway_env(monkeypatch)
    yield e
    h.close_env()


def _headers(**extra):
    return {"Authorization": f"Bearer {h.VK}", "anthropic-version": "2023-06-01", **extra}


def _post(env, body=None, *, headers=None, query="?beta=true", model="claude-sonnet-4-5"):
    body = body or {"model": model, "max_tokens": 64, "messages": [{"role": "user", "content": "hola"}]}
    return env.client.post("/gw/v1/messages" + query, headers=headers or _headers(), json=body)


def _snap(*, targets=("d-chat",), dests=None, creds=None, rules=None, **kw):
    snap = fx.snapshot("on", claude_targets=targets, **kw)
    changes = {}
    if dests:
        changes["destinations"] = {**snap.destinations, **dests}
    if creds is not None:
        changes["credentials"] = {**snap.credentials, **creds}
    if rules is not None:
        changes["rules"] = rules
    return snap.__class__(**{**snap.__dict__, **changes}) if changes else snap


def _redirect_row(env):
    """La decisión de un pedido CORTADO por la pasarela: su fila de auditoría."""
    return env.audits[-1][1]["routing_decision"]["extensions"]["redirect"]


def _decision(env):
    """La decisión de un pedido que SALIÓ al motor: viaja firmada en la autorización (el motor la audita)."""
    sent = env.engine.sent[-1]
    token = {k.lower(): v for k, v in sent["headers"].items()}[authz.HEADER]
    return authz.verify(token, expected_model=sent["body"]["model"]).decision


# ── autenticación y rutas auxiliares (FR-033) ───────────────────────────────────

@pytest.mark.parametrize("headers", [{"Authorization": f"Bearer {h.VK}"}, {"x-api-key": h.VK}],
                         ids=["bearer", "x-api-key"])
def test_la_llave_se_acepta_por_bearer_y_por_x_api_key(env, headers):
    env.register(fx.snapshot("on"))
    r = _post(env, headers={"anthropic-version": "2023-06-01", **headers})
    assert r.status_code == 200 and r.json()["model"] == "claude-sonnet-4-5"
    assert env.engine.sent[-1]["body"]["model"] == "rdx-chatcompat/qwen-destino"


@pytest.mark.parametrize("query", ["", "?beta=true"])
def test_el_sufijo_beta_true_se_ignora(env, query):
    env.register(fx.snapshot("on"))
    r = _post(env, query=query)
    assert r.status_code == 200 and env.engine.sent[-1]["url"].split("?")[0].endswith("/v1/messages")


def test_el_sondeo_de_calentamiento_head_api_hello_es_404_sin_cuerpo(env):
    env.register(fx.snapshot("on"))
    r = env.client.head("/api/hello")
    assert r.status_code == 404 and r.content == b""


# ── /gw/v1/models (FR-034) ─────────────────────────────────────────────────────

def test_models_vista_anthropic_en_menos_de_1_s_con_etiqueta_y_ventana_reales(env):
    env.register(fx.snapshot("on"))
    t0 = time.perf_counter()
    r = env.client.get("/gw/v1/models?beta=true", headers=_headers())
    assert time.perf_counter() - t0 < 1.0
    (m,) = r.json()["data"]
    assert m["type"] == "model" and m["id"] == "claude-sonnet-4-5"
    assert m["display_name"].startswith("Sonnet · servido por Qwen UE") and m["max_input_tokens"] == 128000
    assert m["anthropic_family_tier"] == "sonnet" and r.json()["has_more"] is False


def test_models_anuncia_solo_ids_claude_para_que_la_herramienta_los_reconozca(env):
    # Claude Code descarta del lado del cliente lo que no conoce (`unrecognized_model`): lo publicado es claude-*
    env.register(fx.snapshot("on"))
    ids = [m["id"] for m in env.client.get("/gw/v1/models", headers=_headers()).json()["data"]]
    assert ids and all(i.startswith("claude-") for i in ids) and not any(i.startswith("rdx-") for i in ids)


def test_models_no_lista_destinos_ni_internos_y_sin_politica_es_la_lista_de_siempre(env):
    env.register(fx.snapshot("on"))
    ids = [m["id"] for m in env.client.get("/gw/v1/models", headers=_headers()).json()["data"]]
    assert "modelo-base" not in ids and "pro" not in ids
    env.register  # noqa: B018 — la política apagada se prueba abajo con otro registro
    h.close_env()
    env2 = h.gateway_env(pytest.MonkeyPatch())
    env2.register(fx.snapshot("off"))
    ids = [m["id"] for m in env2.client.get("/gw/v1/models", headers=_headers()).json()["data"]]
    assert ids == ["modelo-base"]                                # solo pierde `rdx-*`, como sin plugin
    h.close_env()


# ── FR-016: allowed_models de la llave sobre el id PÚBLICO ──────────────────────

def test_llave_con_lista_que_incluye_el_id_publico_sirve(env):
    env.register(fx.snapshot("on"), key_models=["claude-sonnet-4-5"])
    r = _post(env)
    assert r.status_code == 200 and env.engine.sent[-1]["body"]["model"].startswith("rdx-")


def test_el_id_interno_rdx_nunca_se_evalua_contra_la_lista_de_la_llave(env):
    # la lista solo tiene el id público; el destino interno (`rdx-…`) queda autorizado por la resolución (QA A2)
    env.register(fx.snapshot("on"), key_models=["claude-sonnet-4-5"])
    r = _post(env)
    assert r.status_code == 200 and "rdx-chatcompat/qwen-destino" not in ["claude-sonnet-4-5"]
    assert env.engine.sent[-1]["body"]["model"] == "rdx-chatcompat/qwen-destino"


def test_llave_con_lista_que_no_incluye_el_id_publico_se_rechaza_sin_llegar_al_motor(env):
    env.register(fx.snapshot("on"), key_models=["otro-modelo"])
    r = _post(env)
    assert r.status_code == 404 and r.json()["error"]["type"] == "not_found_error"
    assert r.json()["error"]["message"] == "Modelo no disponible para tu organización."
    assert env.engine.sent == [] and _redirect_row(env)["unavailable"] == "key_model_not_allowed"


def test_la_lista_con_el_id_interno_pero_sin_el_publico_no_sirve(env):
    env.register(fx.snapshot("on"), key_models=["rdx-chatcompat/qwen-destino"])
    assert _post(env).status_code == 404 and env.engine.sent == []


@pytest.mark.parametrize("lista", [[], None])
def test_lista_vacia_o_sin_lista_sirve(env, lista):
    env.register(fx.snapshot("on"), key_models=lista)
    assert _post(env).status_code == 200


# ── regla por tier, destino sin credencial, fallback (FR-018) ───────────────────

def test_regla_por_tier_sin_regla_por_id(env):
    snap = fx.snapshot("on")
    tier = {"id": "r-tier", "tenant_id": fx.TENANT, "scope_type": "tenant", "scope_value": "*",
            "published_model_id": None, "family_tier": "sonnet", "targets": ["d-chat"]}
    env.register(_snap(rules=tuple(r for r in snap.rules if r["id"] != "r-cl") + (tier,)))
    r = _post(env)
    assert r.status_code == 200 and env.engine.sent[-1]["body"]["model"] == "rdx-chatcompat/qwen-destino"


def test_destino_sin_credencial_pasa_al_fallback_y_queda_auditado(env):
    sin = {**fx.DEST_CHAT, "id": "d-sin", "name": "Sin credencial", "has_credential": False}
    env.register(_snap(targets=("d-sin", "d-chat"), dests={"d-sin": sin}))
    r = _post(env)
    assert r.status_code == 200 and env.engine.sent[-1]["body"]["model"] == "rdx-chatcompat/qwen-destino"
    assert _decision(env)["substitution_reason"] == "fallback_unavailable"


def test_destino_sin_credencial_y_sin_fallback_es_un_error_claro_nunca_otro_modelo(env):
    sin = {**fx.DEST_CHAT, "id": "d-sin", "name": "Sin credencial", "has_credential": False}
    env.register(_snap(targets=("d-sin",), dests={"d-sin": sin}))
    r = _post(env)
    assert r.status_code == 404 and r.json()["error"]["type"] == "not_found_error" and env.engine.sent == []
    assert _redirect_row(env)["unavailable"] == "no_eligible_target"


def test_id_publicado_sin_regla_es_404_neutro_y_auditado(env):
    env.register(_snap(rules=()))
    r = _post(env)
    assert r.status_code == 404 and r.json()["error"]["message"] == "Modelo no disponible para tu organización."
    assert env.engine.sent == [] and len(env.audits) == 1


# ── internos y credenciales del cliente ────────────────────────────────────────

def test_api_base_y_credenciales_del_cliente_se_ignoran(env):
    env.register(fx.snapshot("on"))
    body = {"model": "claude-sonnet-4-5", "max_tokens": 64, "messages": [{"role": "user", "content": "hola"}],
            "api_base": "http://atacante", "api_key": "sk-del-cliente", "base_url": "http://x", "extra_headers": {"a": "b"}}
    _post(env, body)
    sent = env.engine.sent[-1]["body"]
    assert sent["model"] == "rdx-chatcompat/qwen-destino" and not {"api_base", "api_key", "base_url", "extra_headers"} & set(sent)


def test_un_rdx_pedido_por_el_cliente_no_obtiene_autorizacion_y_el_guard_lo_rechaza(env):
    env.register(fx.snapshot("on"))
    _post(env, {"model": "rdx-anthropic/claude-real", "max_tokens": 5, "messages": []})
    sent = env.engine.sent[-1]
    assert authz.HEADER not in {k.lower() for k in sent["headers"]}
    data = {**sent["body"], "proxy_server_request": {"headers": sent["headers"]}, "metadata": {}}
    with pytest.raises(guard.GuardRejection) as e:
        guard.apply_redirect(data, environ={})
    assert e.value.status == 403


# ── errores de la cara (FR-038) ────────────────────────────────────────────────

def test_saturacion_del_destino_es_529_overloaded_reintentable(env):
    env.register(fx.snapshot("on"))
    env.engine.status = 503
    r = _post(env)
    assert r.status_code == 529 and r.json()["error"]["type"] == "overloaded_error"
    assert r.headers["x-should-retry"] == "true"


def test_limite_de_tasa_es_429_con_retry_after_de_a_lo_sumo_60(env):
    env.register(fx.snapshot("on"))
    env.engine.status, env.engine.error_headers = 429, {"retry-after": "600"}
    r = _post(env)
    assert r.status_code == 429 and r.json()["error"]["type"] == "rate_limit_error"
    assert 1 <= int(r.headers["retry-after"]) <= 60


def test_si_falla_la_resolucion_es_503_reintentable_y_no_sale_nada(env, monkeypatch):
    env.register(fx.snapshot("on"))

    def boom(**kw):
        raise RuntimeError("falla de la resolución")

    monkeypatch.setattr(resolver, "resolve", boom)
    r = _post(env)
    assert r.status_code == 503 and r.json()["error"]["type"] == "api_error" and r.headers["x-should-retry"] == "true"
    assert env.engine.sent == []


def test_error_de_autenticacion_del_destino_no_se_presenta_como_error_del_usuario(env):
    env.register(fx.snapshot("on"))
    env.engine.status = 401
    r = _post(env)
    assert r.status_code == 502 and r.json()["error"]["type"] == "api_error"


# ── funciones que el destino no tiene (FR-035) ─────────────────────────────────

def test_pdf_hacia_un_destino_sin_vision_de_documentos_es_400_capability_rejected(env):
    env.register(fx.snapshot("on"))
    body = {"model": "claude-sonnet-4-5", "max_tokens": 64, "messages": [{"role": "user", "content": [
        {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": "JVBERi0="}}]}]}
    r = _post(env, body)
    assert r.status_code == 400 and r.json()["error"]["message"].startswith("capability_rejected: documents_pdf")


@pytest.mark.parametrize("tool,capability", [
    ({"type": "web_search_20250305", "name": "web_search"}, "web_search"),
    ({"type": "web_fetch_20250910", "name": "web_fetch"}, "web_fetch"),
    ({"type": "code_execution_20250522", "name": "code_execution"}, "code_execution"),
])
def test_funcion_exclusiva_del_proveedor_original_hacia_un_traducido_es_400_nunca_ignorada(env, tool, capability):
    env.register(fx.snapshot("on"))
    r = _post(env, {"model": "claude-sonnet-4-5", "max_tokens": 64, "tools": [tool],
                    "messages": [{"role": "user", "content": "buscá algo"}]})
    assert r.status_code == 400 and r.json()["error"]["type"] == "invalid_request_error"
    assert r.json()["error"]["message"].startswith(f"capability_rejected: {capability}")
    assert len(env.audits) == 1 and env.audits[0][0][4] == "blocked_by_policy"          # el rechazo deja fila


def test_la_misma_funcion_hacia_un_nativo_no_se_toca(env, monkeypatch):
    monkeypatch.setattr(h.gateway, "_resolve_attribution", lambda _k: fx.ident(**US))
    env.register(fx.snapshot("on", claude_targets=("d-ant",)))
    r = _post(env, {"model": "claude-sonnet-4-5", "max_tokens": 64, "tools": [{"type": "web_search_20250305", "name": "web_search"}],
                    "messages": [{"role": "user", "content": "buscá algo"}]})
    assert r.status_code == 200 and env.engine.sent[-1]["body"]["tools"][0]["type"] == "web_search_20250305"


# ── marca neutra y auditoría sin contenido (FR-014, FR-047, FR-050, SC-008) ──────

def _sin_nombres_prohibidos(texto: str):
    bajo = texto.lower()
    for nombre in PROHIBIDOS:
        assert nombre not in bajo, nombre


def test_ningun_texto_de_la_cara_nombra_internals():
    for kind in face._ERRORS:
        _, _, body = face.error_response(kind, capability="web_search")
        _sin_nombres_prohibidos(json.dumps(body, ensure_ascii=False))
        _sin_nombres_prohibidos(face.error_event(kind, capability="web_search").decode())
    for cap, msg in face.CAPABILITY_MESSAGES.items():
        _sin_nombres_prohibidos(msg)


def test_las_respuestas_del_contrato_no_nombran_internals(env):
    env.register(fx.snapshot("on"))
    textos = [env.client.get("/gw/v1/models", headers=_headers()).text, _post(env).text]
    env.engine.status = 503
    textos.append(_post(env).text)
    env.engine.status = 200
    textos.append(_post(env, model="claude-opus-no-publicado-con-regla-rota").text)
    for t in textos:
        _sin_nombres_prohibidos(t)


def test_la_decision_y_las_filas_de_auditoria_no_llevan_texto_del_pedido_ni_secretos(env):
    env.register(fx.snapshot("on"))
    prompt = "mi clave es 4111-1111-1111-1111 y el documento 20-12345678-9"
    doc = corpus.load("claude_code_messages_beta")
    doc["body"]["messages"][0]["content"] = [{"type": "text", "text": prompt}]
    assert _post(env, doc["body"]).status_code == 200
    red = _decision(env)                                  # lo que el motor registra de este pedido
    assert red["public_id"] == "claude-sonnet-4-5" and red["destination_id"] == "d-chat" and red["face"] == "claude"
    assert red["dropped_fields"] == "campo_futuro_de_la_herramienta,safeguards"
    assert all(isinstance(v, (str, int, float, bool, type(None))) for v in red.values())
    # y una fila escrita por la propia pasarela (un corte), con el mismo pedido
    h.close_env()
    e2 = h.gateway_env(pytest.MonkeyPatch())
    e2.register(fx.snapshot("on"), key_models=["otro"])
    assert _post(e2, doc["body"]).status_code == 404
    for texto in (json.dumps(red), json.dumps(e2.audits, default=str)):
        for secreto in (prompt, "4111", "20-12345678-9", "sk-destino-chat", fx.INTERNAL_KEY, h.VK, "enforce"):          # `safeguards`: el nombre sí, el valor no
            assert secreto not in texto, secreto
    h.close_env()


# ── id NO publicado: regla por tier inferido del nombre (US1 esc. 4, FR-015, FR-018; decisión del coordinador) ──

def _con_regla_por_tier(tier="sonnet", targets=("d-chat",)):
    snap = fx.snapshot("on")
    regla = {"id": f"r-tier-{tier}", "tenant_id": fx.TENANT, "scope_type": "tenant", "scope_value": "*",
             "published_model_id": None, "family_tier": tier, "targets": list(targets)}
    return snap.__class__(**{**snap.__dict__, "rules": snap.rules + (regla,)})


@pytest.mark.parametrize("pedido,tier", [
    ("claude-sonnet-4-5-20250929", "sonnet"), ("claude-3-5-sonnet-20241022", "sonnet"),
    ("claude-opus-4-1-20250805", "opus"), ("claude-3-5-haiku-latest", "haiku"), ("Claude-Sonnet-9", "sonnet")])
def test_un_id_con_fecha_no_publicado_cae_a_la_regla_por_tier(env, pedido, tier):
    env.register(_con_regla_por_tier(tier))
    r = _post(env, model=pedido)
    assert r.status_code == 200 and r.json()["model"] == pedido                       # el id pedido, no el interno
    assert env.engine.sent[-1]["body"]["model"] == "rdx-chatcompat/qwen-destino"
    red = _decision(env)
    assert red["public_id"] == pedido and red["tier_inferred"] == tier.lower() and red["destination_id"] == "d-chat"


def test_un_id_con_tier_pero_sin_regla_por_tier_es_404_neutro_y_auditado(env):
    env.register(_con_regla_por_tier("sonnet"))
    r = _post(env, model="claude-haiku-4-5-20251001")
    assert r.status_code == 404 and r.json()["error"]["message"] == "Modelo no disponible para tu organización."
    assert env.engine.sent == [] and len(env.audits) == 1


@pytest.mark.parametrize("pedido", ["claude-instant-1", "claude-sonnet-opus-1", "claude"])
def test_un_id_claude_sin_tier_claro_es_404_neutro(env, pedido):
    env.register(_con_regla_por_tier("sonnet"))
    r = _post(env, model=pedido)
    assert r.status_code == 404 and env.engine.sent == []


def test_un_id_que_no_empieza_con_claude_sigue_su_camino_sin_cambios(env):
    env.register(_con_regla_por_tier("sonnet"))
    r = _post(env, model="modelo-de-la-base-sonnet")
    assert r.status_code == 200 and env.engine.sent[-1]["body"]["model"] == "modelo-de-la-base-sonnet"
    assert authz.HEADER not in {k.lower() for k in env.engine.sent[-1]["headers"]} and env.audits == []


def test_el_id_publicado_exacto_manda_sobre_la_inferencia(env):
    env.register(_con_regla_por_tier("sonnet", targets=("d-ant",)))
    r = _post(env, model="claude-sonnet-4-5")                                            # publicado: su propia regla
    assert env.engine.sent[-1]["body"]["model"] == "rdx-chatcompat/qwen-destino" and "tier_inferred" not in _decision(env)


def test_la_lista_de_la_llave_se_evalua_tambien_sobre_el_id_inferido(env):
    env.register(_con_regla_por_tier("sonnet"), key_models=["claude-sonnet-4-5"])
    assert _post(env, model="claude-sonnet-4-5-20250929").status_code == 404 and env.engine.sent == []


def test_la_suscripcion_personal_con_un_id_con_fecha_sigue_su_camino(env, monkeypatch):
    monkeypatch.setattr(h.gateway, "_detect_mode_and_key", lambda *a, **k: ("subscription", None))
    env.register(_con_regla_por_tier("sonnet"))
    r = _post(env, model="claude-sonnet-4-5-20250929", headers={"Authorization": "Bearer sk-ant-oat-personal"})
    assert r.status_code == 200 and env.engine.sent[-1]["body"]["model"] == "claude-sonnet-4-5-20250929"


def test_en_sombra_o_apagada_un_id_no_publicado_no_se_toca(env):
    snap = _con_regla_por_tier("sonnet")
    for estado in ("off", "shadow"):
        h.close_env()
        e = h.gateway_env(pytest.MonkeyPatch())
        pol = tuple({**p, "state": estado} for p in snap.policy)
        e.register(snap.__class__(**{**snap.__dict__, "policy": pol}))
        r = _post(e, model="claude-sonnet-4-5-20250929")
        assert r.status_code == 200 and e.engine.sent[-1]["body"]["model"] == "claude-sonnet-4-5-20250929", estado
    h.close_env()


def test_count_tokens_tambien_resuelve_por_tier(env):
    env.register(_con_regla_por_tier("sonnet"))
    r = env.client.post("/gw/v1/messages/count_tokens?beta=true", headers=_headers(),
                        json={"model": "claude-sonnet-4-5-20250929", "messages": [{"role": "user", "content": "hola"}]})
    assert r.status_code == 200 and r.json()["input_tokens"] > 0 and env.engine.sent == []
