"""La cara OpenAI genérica de punta a punta en Eleia (057 T047; US5 esc. 2–4, FR-054, FR-056; contracts/cara-generica.md).

Pasarela REAL del backend → autorización firmada → guard REAL del motor (`redirect_guard.apply_redirect`, con el
`call_type` con el que el motor recibe `/chat/completions`) → motor falso. Lo que se prueba:

- alias → destino, `model` de la respuesta = alias (stream y no-stream) y cambio de destino sin tocar el cliente;
- `model_not_found` (404), `region_not_allowed` (403) y `masking_required` (403, enmascarado forzado de la postura por
  defecto `masked_all` con el analizador caído) con la forma de error de la pasarela y textos neutros;
- `max_tokens` ⇒ `max_completion_tokens` (con el piso de 16) hacia un gpt-5.x de Azure.

El motor falso es el de `gw_harness`, con el guard delante: un pedido que el guard rechaza vuelve como lo devuelve el motor
(403 con el código dentro del mensaje) y la pasarela lo traduce a la forma de la cara.
"""
import json
from pathlib import Path

import pytest

from sentinel.engine import redirect_guard as guard
from sentinel.redirect import authz
from sentinel.tests import gw_harness as h
from sentinel.tests import redirect_fixtures as fx
from sentinel.tests import residency_fixtures as rf

ROOT = Path(__file__).resolve().parents[3]
PROHIBIDOS = [ln.strip().lower() for ln in (ROOT / "deploy/release/checks/prohibited_names.txt").read_text(
    encoding="utf-8").splitlines() if ln.strip() and not ln.strip().startswith("#")]
AUTH = {"Authorization": f"Bearer {h.VK}"}
DNI = "30.123.456"
AZURE_KEY = "sk-azure-de-prueba-del-recurso"      # secret-scanner: allow (valor inventado de un fixture de test)
AMERICAS = {"nlp": {"region": "latam_ar"}}
REPORTE_OK = {"completed": True, "degraded": False, "detected": 1, "masked": 1, "unanalyzable": 0, "scope": "full"}
ANALIZADOR_CAIDO = {"completed": False, "degraded": True, "detected": 0, "masked": 0, "unanalyzable": 0, "scope": "full"}
MASKING_TEXT = "El pedido no pudo protegerse para este destino y fue bloqueado. Probá en una conversación nueva."

DEST_AZURE = {
    "id": "d-azure", "level": "tenant", "tenant_id": fx.TENANT, "name": "Gpt Azure", "provider": "azure",
    "real_model": "gpt-5.4-mini", "protocol_family": "openai_chat", "inference_jurisdiction": "US",
    "entity_jurisdiction": "US", "control_jurisdiction": "US", "blocked_by_default": False, "enabled_at": None,
    "has_credential": True, "api_base": "https://recurso.openai.azure.com", "provider_options": {},
    "capability_profile": {"tools": True, "images": True, "documents_pdf": False}, "context_window": 400000,
    "max_output": 128000, "status": "active",
}
DEST_OTRO = {**fx.DEST_CHAT, "id": "d-otro", "name": "Otro", "real_model": "otro-destino",
             "api_base": "http://otro.local/v1"}
CREDS = {"d-azure": json.dumps({"api_key": AZURE_KEY, "api_version": "2025-04-01-preview"}),
         "d-otro": json.dumps({"api_key": "sk-otro"})}


class GuardedEngine(h.Engine):
    """Motor falso con el guard real delante. `report` es lo que habría escrito el guardrail de la base."""
    report = None
    guarded: list = []

    @classmethod
    def reset(cls):
        h.Engine.reset()
        cls.report, cls.guarded = None, []

    def _reply(self, url, headers, content, stream=False):
        body = json.loads(content) if content else {}
        model = str(body.get("model", ""))
        if model.startswith("rdx-") and not model.startswith("rdx-rejected/"):
            data = {**body, "proxy_server_request": {"headers": dict(headers or {})}, "metadata": {}}
            if GuardedEngine.report is not None:
                data["metadata"]["masking_report"] = GuardedEngine.report
            try:
                out = guard.apply_redirect(data, key=fx.INTERNAL_KEY, call_type="acompletion", environ={})
            except guard.GuardRejection as e:
                h.Engine.sent.append({"url": url, "headers": dict(headers or {}), "body": body})
                msg = json.dumps({"error": {"message": str({"code": e.code, "message": e.message})}})
                return h._Resp(e.status, msg.encode())
            GuardedEngine.guarded.append(out)
        return super()._reply(url, headers, content, stream)


@pytest.fixture
def env(monkeypatch):
    e = h.gateway_env(monkeypatch, ident=fx.ident(**AMERICAS))
    GuardedEngine.reset()
    monkeypatch.setattr(h.gateway.httpx, "AsyncClient", GuardedEngine)
    monkeypatch.setenv("SENTINEL_ENTITY_REGION", "latam_ar")
    e.guard = GuardedEngine
    yield e
    h.close_env()


def _snap(*, region="masked_all", targets=("d-azure",), destinos=None, state="on"):
    snap = fx.snapshot(state, regions=[rf.region_row(region)], targets=targets, offers=())
    dests = {**snap.destinations, "d-azure": DEST_AZURE, "d-otro": DEST_OTRO, **(destinos or {})}
    return snap.__class__(**{**snap.__dict__, "destinations": dests, "credentials": {**snap.credentials, **CREDS}})


def _chat(env, *, model="pro", stream=False, **extra):
    return env.client.post("/gw/v1/chat/completions", headers=AUTH, json={
        "model": model, "stream": stream, "messages": [{"role": "user", "content": f"hola {DNI}"}], **extra})


def _sin_internos(texto):
    t = texto.lower()
    for malo in ("d-azure", "d-otro", "azure", "gpt-5", "recurso", "rdx-", "americas", "latam", AZURE_KEY, DNI):
        assert malo.lower() not in t, malo
    assert not [n for n in PROHIBIDOS if n in t], "nombres de componentes internos"


# ── alias → destino, `model` = alias (FR-054) ─────────────────────────────────────────────────────

def test_el_alias_se_reescribe_al_destino_y_la_respuesta_vuelve_con_el_alias(env):
    env.register(_snap(region="allow"))
    r = _chat(env)
    sent = env.engine.sent[-1]
    assert sent["url"].endswith("/v1/chat/completions") and sent["body"]["model"] == "rdx-azure/gpt-5.4-mini"
    assert r.status_code == 200 and r.json()["model"] == "pro"
    assert "gpt-5.4-mini" not in r.text and "rdx-" not in r.text


def test_en_stream_cada_chunk_vuelve_con_el_alias(env):
    env.register(_snap(region="allow"))
    env.engine.stream_chunks = (
        b'data: {"id":"c1","model":"gpt-5.4-mini","choices":[{"delta":{"content":"ho"}}]}\n\n',
        b'data: {"id":"c1","model":"gpt-5.4-mini","choices":[{"delta":{"content":"la"},"finish_reason":"stop"}]}\n\n',
        b"data: [DONE]\n\n")
    r = _chat(env, stream=True)
    assert r.status_code == 200
    assert r.content.count(b'"model":"pro"') == 2 and b"gpt-5.4-mini" not in r.content
    assert r.content.rstrip().endswith(b"data: [DONE]")


def test_con_herramientas_el_pedido_llega_entero_y_sin_credenciales_del_cliente(env):
    env.register(_snap(region="allow"))
    tools = [{"type": "function", "function": {"name": "leer", "parameters": {"type": "object", "properties": {}}}}]
    _chat(env, tools=tools, tool_choice="auto", api_key="sk-del-cliente", api_base="http://atacante")
    body = env.guard.guarded[-1]
    assert body["tools"] == tools and body["tool_choice"] == "auto"
    assert body["api_key"] == AZURE_KEY and body["api_base"] == "https://recurso.openai.azure.com"
    assert "sk-del-cliente" not in json.dumps(body, default=str) and "atacante" not in json.dumps(body, default=str)


def test_cambiar_el_destino_de_la_regla_no_toca_al_cliente(env):
    pedido = {"model": "pro", "messages": [{"role": "user", "content": "hola"}]}
    env.register(_snap(region="allow", targets=("d-azure",)))
    antes = env.client.post("/gw/v1/chat/completions", headers=AUTH, json=pedido)
    assert env.engine.sent[-1]["body"]["model"] == "rdx-azure/gpt-5.4-mini"
    h.close_env()
    env.register(_snap(region="allow", targets=("d-otro",)))
    despues = env.client.post("/gw/v1/chat/completions", headers=AUTH, json=pedido)
    assert env.engine.sent[-1]["body"]["model"] == "rdx-chatcompat/otro-destino"
    assert antes.json()["model"] == despues.json()["model"] == "pro"


# ── silencio del destino en stream: `: keep-alive` (FR-056) ───────────────────────────────────────

def test_el_silencio_del_destino_se_cubre_con_comentarios_keep_alive_entre_chunks(env):
    env.register(_snap(region="allow"))
    env.engine.stream_chunks = (
        0.3, b'data: {"id":"c1","model":"gpt-5.4-mini","choices":[{"delta":{"content":"ho"}}]}\n\n',
        0.3, b'data: {"id":"c1","model":"gpt-5.4-mini","choices":[{"delta":{"content":"la"},"finish_reason":"stop"}]}\n\n',
        b"data: [DONE]\n\n")
    r = _chat(env, stream=True)
    assert r.status_code == 200
    cuerpo = r.content
    assert cuerpo.count(b": keep-alive\n\n") >= 2, "uno por cada silencio (ping_after de la prueba = 50 ms)"
    # el comentario va ENTRE tramas completas: ni parte un `data:` ni cambia lo que el cliente lee
    assert cuerpo.index(b": keep-alive") < cuerpo.index(b'"model":"pro"')
    eventos = [json.loads(b[5:]) for b in cuerpo.decode().split("\n\n") if b.startswith("data:") and "[DONE]" not in b]
    assert "".join(e["choices"][0]["delta"]["content"] for e in eventos) == "hola"
    assert {e["model"] for e in eventos} == {"pro"} and cuerpo.rstrip().endswith(b"data: [DONE]")


def test_el_keep_alive_por_defecto_es_de_15_s_o_menos():
    from sentinel.redirect import stream
    from sentinel.redirect.plugin import RedirectPlugin
    assert stream.DEFAULT_PING_AFTER <= 15.0 and stream.OPENAI_KEEPALIVE == b": keep-alive\n\n"
    assert RedirectPlugin(store=fx.store(_snap())).ping_after == stream.DEFAULT_PING_AFTER


# ── model_not_found (404) ─────────────────────────────────────────────────────────────────────────

def test_alias_sin_destino_elegible_es_404_model_not_found_y_no_llega_al_motor(env):
    env.register(_snap(region="allow", targets=("no-existe",)))
    n = len(env.engine.sent)
    r = _chat(env)
    assert r.status_code == 404 and len(env.engine.sent) == n
    assert r.json() == {"error": {"message": "Modelo no disponible para tu organización.",
                                  "type": "invalid_request_error", "param": None, "code": "model_not_found"}}
    _sin_internos(r.text)
    (args, kw), = env.audits
    assert "hola" not in json.dumps(kw, default=str) and DNI not in json.dumps(kw, default=str)


# ── region_not_allowed (403) ──────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("region,destinos", [
    ("reject_offregion", {"d-azure": {**DEST_AZURE, "inference_jurisdiction": "DE", "entity_jurisdiction": "DE",
                                     "control_jurisdiction": "DE"}}),            # fuera de la región del perfil
    ("masked_all", {"d-azure": {**DEST_AZURE, "inference_jurisdiction": None}}),  # sin jurisdicción de inferencia
], ids=["fuera-de-region-con-reject_offregion", "sin-jurisdiccion-de-inferencia"])
@pytest.mark.parametrize("stream", [False, True], ids=["no-stream", "stream"])
def test_destino_no_apto_es_403_region_not_allowed_sin_nombrar_nada(env, region, destinos, stream):
    env.register(_snap(region=region, destinos=destinos))
    n = len(env.engine.sent)
    r = _chat(env, stream=stream)
    assert r.status_code == 403 and len(env.engine.sent) == n, "no llega al motor"
    assert r.json() == {"error": {"message": "Modelo no disponible para tu región.",
                                  "type": "permission_error", "param": None, "code": "region_not_allowed"}}
    _sin_internos(r.text)
    (args, kw), = env.audits
    assert DNI not in json.dumps(kw, default=str) and "hola" not in json.dumps(kw, default=str)


# ── masking_required (403): enmascarado forzado con el analizador caído ───────────────────────────

@pytest.mark.parametrize("stream", [False, True], ids=["no-stream", "stream"])
@pytest.mark.parametrize("informe", [ANALIZADOR_CAIDO, None,
                                     {**REPORTE_OK, "unanalyzable": 1},
                                     {k: v for k, v in REPORTE_OK.items() if k != "scope"}],
                         ids=["analizador-caido", "sin-informe", "no-analizable", "informe-sin-alcance"])
def test_masked_all_con_el_analizador_caido_bloquea_con_masking_required(env, stream, informe):
    env.register(_snap(region="masked_all"))
    env.guard.report = informe
    r = _chat(env, stream=stream)
    assert r.status_code == 403 and not env.guard.guarded, "el guard cortó antes del proveedor"
    assert r.json() == {"error": {"message": MASKING_TEXT, "type": "permission_error", "param": None,
                                  "code": "masking_required"}}
    assert "retry-after" not in {k.lower() for k in r.headers}, "rechazo definitivo, nunca reintentable"
    _sin_internos(r.text)


def test_con_el_informe_completo_el_forzado_deja_pasar_y_firma_el_alcance(env):
    env.register(_snap(region="masked_all"))
    env.guard.report = REPORTE_OK
    r = _chat(env)
    assert r.status_code == 200 and r.json()["model"] == "pro"
    red = env.guard.guarded[-1]["metadata"]["_internal_routing_decision"]["extensions"]["redirect"]
    assert red["forced_masking"] is True and red["masking_verified"] is True and red["masking_scope"] == "full"
    assert red["default_posture_applied"] == "masked_all"


def test_un_pedido_forzado_no_se_degrada_si_el_cliente_pide_otra_cosa(env):
    env.register(_snap(region="masked_all"))
    env.guard.report = ANALIZADOR_CAIDO
    r = env.client.post("/gw/v1/chat/completions", headers={**AUTH, "x-sentinel-redact": "off"},
                        json={"model": "pro", "messages": [{"role": "user", "content": f"hola {DNI}"}],
                              "governance_overrides": {"pii_masking": False}, "forced_masking": False})
    assert r.status_code == 403 and r.json()["error"]["code"] == "masking_required"


# ── max_tokens ⇒ max_completion_tokens hacia gpt-5.x de Azure (HANDOFF §A.5) ──────────────────────

def test_hacia_un_gpt_5_de_azure_max_tokens_sale_como_max_completion_tokens(env):
    env.register(_snap(region="allow"))
    r = _chat(env, max_tokens=1000)
    assert r.status_code == 200
    out = env.guard.guarded[-1]
    assert out["max_completion_tokens"] == 1000 and "max_tokens" not in out
    red = out["metadata"]["_internal_routing_decision"]["extensions"]["redirect"]
    assert red["adjusted_params"] == "max_tokens->max_completion_tokens"


def test_el_piso_de_16_se_aplica_al_limite_renombrado(env):
    env.register(_snap(region="allow"))
    _chat(env, max_tokens=1)
    out = env.guard.guarded[-1]
    assert out["max_completion_tokens"] == 16 and "max_tokens" not in out


def test_si_el_cliente_ya_manda_max_completion_tokens_manda_ese(env):
    env.register(_snap(region="allow"))
    _chat(env, max_tokens=5, max_completion_tokens=500)
    out = env.guard.guarded[-1]
    assert out["max_completion_tokens"] == 500 and "max_tokens" not in out


def test_hacia_un_compatible_con_openai_max_tokens_queda_como_esta(env):
    env.register(_snap(region="allow", targets=("d-otro",)))
    _chat(env, max_tokens=300)
    out = env.guard.guarded[-1]
    assert out["max_tokens"] == 300 and "max_completion_tokens" not in out


def test_la_auditoria_de_los_ajustes_lleva_nombres_nunca_valores_ni_secretos(env):
    env.register(_snap(region="allow"))
    _chat(env, max_tokens=7)
    out = env.guard.guarded[-1]
    texto = json.dumps(out["metadata"], default=str)
    assert AZURE_KEY not in texto and DNI not in texto and "hola" not in texto
    assert out["metadata"]["_internal_routing_decision"]["extensions"]["redirect"]["adjusted_params"] \
        == "max_tokens->max_completion_tokens,max_completion_tokens"


def test_el_header_interno_no_llega_al_cliente(env):
    env.register(_snap(region="allow"))
    r = _chat(env)
    assert authz.HEADER not in {k.lower() for k in r.headers}
