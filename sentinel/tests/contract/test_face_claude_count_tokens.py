"""T093 de Sentinel (FR-041, research R12, QA M14/U2): `POST /gw/v1/messages/count_tokens`.

Nativo ⇒ reenvío; con enmascarado forzado vigente nunca se reenvía (ni a nativos ni en el camino de
suscripción: estimado local o 404); traducido ⇒ `{"input_tokens": N}` estimado SIN red; sin estimador ⇒ 404
`not_found_error`; `count_tokens_mode` en la auditoría.
"""
import hashlib
import json
import socket

import pytest

from sentinel.redirect import authz, token_estimate
from sentinel.tests import corpus_claude as corpus
from sentinel.tests import gw_harness as h
from sentinel.tests import redirect_fixtures as fx

FORZADO = [{"tenant_id": fx.TENANT, "scope_type": "tenant", "scope_value": "*",
            "mode": "offregion_masked", "jurisdictions": []}]
US = {"nlp": {"region": "us"}}


@pytest.fixture
def env(monkeypatch):
    # nada de lo que se mide acá puede salir a la red (QA M14): un intento falla el test
    def _sin_red(*a, **k):
        raise AssertionError("count_tokens intentó abrir una conexión de red")

    monkeypatch.setattr(socket.socket, "connect", _sin_red)
    monkeypatch.delenv("TIKTOKEN_CACHE_DIR", raising=False)
    monkeypatch.delenv("DATA_GYM_CACHE_DIR", raising=False)
    monkeypatch.setattr(token_estimate, "_encoder", None)
    e = h.gateway_env(monkeypatch)
    yield e
    h.close_env()


def _count(env, doc=None, *, model=None, extra=None, headers=None, query="?beta=true"):
    doc = doc or corpus.load("claude_code_count_tokens")
    body = {**doc["body"], **(extra or {})}
    if model:
        body["model"] = model
    return env.client.post("/gw/v1/messages/count_tokens" + query,
                           headers={"Authorization": f"Bearer {h.VK}", "anthropic-version": "2023-06-01",
                                    **(headers or {})}, json=body)


def _row(env):
    (args, kw), = env.audits
    return args, kw["routing_decision"]["extensions"]["redirect"]


# ── traducido: estimación local ────────────────────────────────────────────────

def test_traducido_responde_una_estimacion_local_sin_tocar_el_motor(env):
    env.register(fx.snapshot("on"))
    r = _count(env)
    assert r.status_code == 200 and set(r.json()) == {"input_tokens"} and r.json()["input_tokens"] > 0
    assert env.engine.sent == []


def test_traducido_se_estima_sobre_el_cuerpo_ya_normalizado(env):
    # `safeguards` y un campo desconocido enorme no llegan al destino: no cuentan en la estimación
    env.register(fx.snapshot("on"))
    base = _count(env).json()["input_tokens"]
    con_ruido = _count(env, extra={"safeguards": {"policy": "x" * 4000}, "otro": "y" * 4000}).json()["input_tokens"]
    assert con_ruido == base


def test_la_estimacion_crece_con_la_conversacion(env):
    env.register(fx.snapshot("on"))
    chico = _count(env).json()["input_tokens"]
    grande = _count(env, extra={"messages": [{"role": "user", "content": "palabra " * 4000}]}).json()["input_tokens"]
    assert grande > chico * 10


def test_traducido_auditado_con_count_tokens_mode_y_sin_texto(env):
    env.register(fx.snapshot("on"))
    secreto = "texto-privado-del-prompt-123"
    _count(env, extra={"messages": [{"role": "user", "content": secreto}]})
    args, red = _row(env)
    assert red["count_tokens_mode"] == "estimated" and red["public_id"] == "claude-sonnet-4-5"
    assert args[4] == "passed" and args[2] == 0 and args[3] == 0          # no se factura nada
    assert secreto not in json.dumps(env.audits, default=str)


# ── sin estimador ⇒ 404 ────────────────────────────────────────────────────────

def test_sin_estimador_responde_404_not_found_error_para_que_la_herramienta_estime(env):
    env.register(fx.snapshot("on"), estimator=lambda body: None)
    r = _count(env)
    assert r.status_code == 404 and r.json()["error"]["type"] == "not_found_error"
    assert env.engine.sent == []
    assert _row(env)[1]["count_tokens_mode"] == "not_found"


def test_un_estimador_que_revienta_tampoco_deja_pasar_el_cuerpo(env):
    def boom(body):
        raise RuntimeError("falla")

    env.register(fx.snapshot("on"), estimator=boom)
    r = _count(env)
    assert r.status_code == 404 and env.engine.sent == []


# ── nativo ─────────────────────────────────────────────────────────────────────

def test_nativo_sin_forzado_se_reenvia_al_destino(env, monkeypatch):
    monkeypatch.setattr(h.gateway, "_resolve_attribution", lambda _k: fx.ident(**US))
    env.register(fx.snapshot("on", claude_targets=("d-ant",)))
    r = _count(env)
    assert r.json() == {"input_tokens": h.COUNT_FROM_ENGINE}
    sent = env.engine.sent[-1]
    assert sent["url"].split("?")[0].endswith("/v1/messages/count_tokens")
    assert sent["body"]["model"] == "rdx-anthropic/claude-real"
    grant = authz.verify({k.lower(): v for k, v in sent["headers"].items()}[authz.HEADER],
                         expected_model="rdx-anthropic/claude-real")
    assert grant.destination_id == "d-ant" and grant.decision["count_tokens_mode"] == "forwarded"


def test_nativo_con_forzado_vigente_nunca_se_reenvia(env):
    env.register(fx.snapshot("on", postures=FORZADO, claude_targets=("d-ant",)))   # EE. UU. fuera de la región `eu`
    r = _count(env)
    assert r.status_code == 200 and r.json()["input_tokens"] != h.COUNT_FROM_ENGINE
    assert env.engine.sent == []
    assert _row(env)[1]["count_tokens_mode"] == "estimated"


def test_nativo_con_forzado_y_sin_estimador_es_404(env):
    env.register(fx.snapshot("on", postures=FORZADO, claude_targets=("d-ant",)), estimator=lambda b: None)
    assert _count(env).status_code == 404 and env.engine.sent == []


# ── camino de suscripción ──────────────────────────────────────────────────────

def test_suscripcion_con_forzado_vigente_no_reenvia_la_conversacion(env, monkeypatch):
    monkeypatch.setattr(h.gateway, "_detect_mode_and_key", lambda *a, **k: ("subscription", None))
    env.register(fx.snapshot("off", postures=FORZADO))
    r = env.client.post("/gw/v1/messages/count_tokens?beta=true",
                        headers={"Authorization": "Bearer sk-ant-oat-personal"},
                        json=corpus.load("claude_code_count_tokens")["body"])
    assert r.status_code == 200 and r.json()["input_tokens"] > 0
    assert env.engine.sent == [], "ni al motor ni al proveedor"


def test_suscripcion_sin_postura_se_reenvia_como_siempre(env, monkeypatch):
    monkeypatch.setattr(h.gateway, "_detect_mode_and_key", lambda *a, **k: ("subscription", None))
    env.register(fx.snapshot("off"))
    env.client.post("/gw/v1/messages/count_tokens", headers={"Authorization": "Bearer sk-ant-oat-personal"},
                    json=corpus.load("claude_code_count_tokens")["body"])
    assert len(env.engine.sent) == 1


# ── lo que no cambia ───────────────────────────────────────────────────────────

def test_un_id_no_publicado_sigue_su_camino_al_motor(env):
    env.register(fx.snapshot("on"))
    r = _count(env, model="modelo-base")
    assert r.json() == {"input_tokens": h.COUNT_FROM_ENGINE}
    assert env.engine.sent[-1]["body"]["model"] == "modelo-base" and env.audits == []


def test_politica_apagada_es_identidad(env):
    env.register(fx.snapshot("off"))
    r = _count(env)
    assert r.json() == {"input_tokens": h.COUNT_FROM_ENGINE}
    assert env.engine.sent[-1]["body"]["model"] == "claude-sonnet-4-5" and env.audits == []


def test_llave_con_allowed_models_que_no_incluye_el_id_no_cuenta(env):
    # FR-016 también en el conteo: el id público se evalúa contra la lista de la llave
    env.register(fx.snapshot("on"), key_models=["otro-id"])
    r = _count(env)
    assert r.status_code == 404 and r.json()["error"]["type"] == "not_found_error"
    assert env.engine.sent == []


# ── el estimador (sin red, vocabulario horneado o caracteres/4) ────────────────

def test_sin_vocabulario_usa_caracteres_sobre_cuatro_y_no_descarga_nada(monkeypatch, tmp_path):
    import tiktoken
    monkeypatch.setenv("TIKTOKEN_CACHE_DIR", str(tmp_path))                    # vacío: no está horneado
    monkeypatch.setattr(token_estimate, "_encoder", None)
    monkeypatch.setattr(tiktoken, "get_encoding",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("intentó descargar el vocabulario")))
    body = {"model": "m", "messages": [{"role": "user", "content": "a" * 400}]}
    assert token_estimate.estimate(body) == 100
    assert token_estimate.mode() == "chars_over_4"


def test_con_el_vocabulario_horneado_usa_cl100k_base(monkeypatch, tmp_path):
    import tiktoken
    blob = "https://openaipublic.blob.core.windows.net/encodings/cl100k_base.tiktoken"
    (tmp_path / hashlib.sha1(blob.encode()).hexdigest()).write_bytes(b"vocabulario de prueba")
    monkeypatch.setenv("TIKTOKEN_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(token_estimate, "_EXPECTED_SHA256", hashlib.sha256(b"vocabulario de prueba").hexdigest())
    monkeypatch.setattr(token_estimate, "_encoder", None)

    class Enc:
        def encode(self, text, **kw):
            return text.split()

    pedidos = []
    monkeypatch.setattr(tiktoken, "get_encoding", lambda name: pedidos.append(name) or Enc())
    body = {"model": "m", "messages": [{"role": "user", "content": "uno dos tres cuatro"}]}
    assert token_estimate.estimate(body) == 4 and pedidos == ["cl100k_base"]
    assert token_estimate.mode() == "cl100k_base"


def test_un_vocabulario_corrupto_no_se_usa(monkeypatch, tmp_path):
    import tiktoken
    blob = "https://openaipublic.blob.core.windows.net/encodings/cl100k_base.tiktoken"
    (tmp_path / hashlib.sha1(blob.encode()).hexdigest()).write_bytes(b"corrupto")
    monkeypatch.setenv("TIKTOKEN_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(token_estimate, "_encoder", None)
    monkeypatch.setattr(tiktoken, "get_encoding",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("la librería lo re-descargaría")))
    assert token_estimate.estimate({"messages": [{"role": "user", "content": "x" * 40}]}) == 10


def test_el_texto_estimado_incluye_system_herramientas_resultados_y_razonamiento_pero_no_firmas(monkeypatch, tmp_path):
    monkeypatch.setenv("TIKTOKEN_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(token_estimate, "_encoder", None)
    texto, media = token_estimate.extract_text(corpus.load("cowork_multiturno")["body"])
    assert "Sos un asistente de escritorio" in texto and "Captura de pantalla" in texto
    assert "Primero busco las notas de ejemplo." in texto and "FIRMA-AJENA" not in texto
    assert media == 1
    assert token_estimate.extract_text({"messages": "no es lista"}) == ("", 0)


def test_cuerpo_que_no_es_un_objeto_no_tiene_estimacion():
    assert token_estimate.estimate(None) is None and token_estimate.estimate([1]) is None
