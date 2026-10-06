"""T094 de Sentinel y FR-040/FR-042 (research R11): cabeceras `anthropic-beta` por lista permitida hacia
nativos, todas descartadas hacia traducidos (`betas_dropped`); una credencial de suscripción personal
hacia un destino de otro proveedor ⇒ 401 `authentication_error`."""
import pytest

from sentinel.redirect import authz, betas
from sentinel.redirect.plugin import RedirectPlugin, STATE_KEY
from sentinel.tests import corpus_claude as corpus
from sentinel.tests import redirect_fixtures as fx

US = {"nlp": {"region": "us"}}


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv(authz.KEY_ENV, fx.INTERNAL_KEY)
    monkeypatch.delenv(betas.ENV, raising=False)


def _headers(value):
    return {"anthropic-version": "2023-06-01", "anthropic-beta": value, "x-app": "cli"}


async def _run(snap, beta_value, *, mode="byok", **ident_kw):
    """Lo que hace la pasarela: pre_request → allowlist de cabeceras (copia las que nombra) → pre_engine."""
    p = RedirectPlugin(store=fx.store(snap), ping_after=0.05)
    c = fx.ctx(route="/v1/messages", model="claude-sonnet-4-5", mode=mode, headers=_headers(beta_value), **ident_kw)
    cut = await p.pre_request(c)
    if cut is not None:
        return c, cut, None, None
    sent = {k: v for k, v in c.request_headers.items() if k.lower() in p.forward_headers_allowlist(c)}
    out, headers = p.pre_engine(c, {"model": "claude-sonnet-4-5", "max_tokens": 5,
                                    "messages": [{"role": "user", "content": "hola"}]}, sent)
    return c, None, out, headers


def _beta_of(headers):
    return next((v for k, v in headers.items() if k.lower() == "anthropic-beta"), None)


# ── la lista permitida es un dato de la extensión ───────────────────────────────

def test_el_default_es_acotado_y_no_incluye_betas_de_retencion_o_facturacion():
    allowed = betas.allowlist()
    assert "interleaved-thinking-2025-05-14" in allowed and "claude-code-20250219" in allowed
    for riesgosa in ("files-api-2025-04-14", "code-execution-2025-05-22", "context-1m-2025-08-07",
                     "oauth-2025-04-20"):
        assert riesgosa not in allowed


def test_el_override_por_entorno_reemplaza_el_default(monkeypatch):
    monkeypatch.setenv(betas.ENV, "una-beta-2026-01-01, otra-beta-2026-02-02,,   ")
    assert betas.allowlist() == frozenset({"una-beta-2026-01-01", "otra-beta-2026-02-02"})
    monkeypatch.setenv(betas.ENV, "none")                   # ninguna, a propósito
    assert betas.allowlist() == frozenset()
    for en_blanco in ("", "  "):                            # lo que deja `.env.example` sin tocar: el default
        monkeypatch.setenv(betas.ENV, en_blanco)
        assert betas.allowlist() == frozenset(betas.DEFAULT_ALLOWLIST)
    monkeypatch.setenv(betas.ENV, "ok-2026-01-01,con espacios,x" + "y" * 80)   # inválidas se ignoran
    assert betas.allowlist() == frozenset({"ok-2026-01-01"})


def test_parse_y_filtro():
    assert betas.parse(" a-1 ,b-2,,a-1") == ["a-1", "b-2", "a-1"]
    assert betas.parse(None) == [] and betas.parse("") == []
    assert betas.split_allowed(["a-1", "b-2", "a-1"], frozenset({"a-1"})) == (["a-1", "a-1"], 1)


# ── nativos: lista permitida ───────────────────────────────────────────────────

async def test_nativo_reenvia_solo_las_betas_de_la_lista():
    doc = corpus.load("claude_code_messages_beta")
    pedido = doc["headers"]["anthropic-beta"] + ",files-api-2025-04-14,context-1m-2025-08-07"
    c, cut, out, headers = await _run(fx.snapshot("on", claude_targets=("d-ant",)), pedido, **US)
    assert cut is None and out["model"] == "rdx-anthropic/claude-real"
    enviadas = _beta_of(headers).split(",")
    assert "files-api-2025-04-14" not in enviadas and "context-1m-2025-08-07" not in enviadas
    assert "claude-code-20250219" in enviadas and "interleaved-thinking-2025-05-14" in enviadas
    assert c.routing_decision["extensions"]["redirect"]["betas_dropped"] == 2


async def test_nativo_con_todas_en_la_lista_no_audita_betas_dropped():
    c, _, _, headers = await _run(fx.snapshot("on", claude_targets=("d-ant",)),
                                  "interleaved-thinking-2025-05-14", **US)
    assert _beta_of(headers) == "interleaved-thinking-2025-05-14"
    assert "betas_dropped" not in c.routing_decision["extensions"]["redirect"]


async def test_nativo_sin_ninguna_permitida_no_manda_la_cabecera():
    c, _, _, headers = await _run(fx.snapshot("on", claude_targets=("d-ant",)), "files-api-2025-04-14", **US)
    assert _beta_of(headers) is None
    assert c.routing_decision["extensions"]["redirect"]["betas_dropped"] == 1


async def test_el_override_del_entorno_se_lee_por_pedido(monkeypatch):
    snap = fx.snapshot("on", claude_targets=("d-ant",))
    monkeypatch.setenv(betas.ENV, "files-api-2025-04-14")
    _, _, _, headers = await _run(snap, "files-api-2025-04-14,claude-code-20250219", **US)
    assert _beta_of(headers) == "files-api-2025-04-14"


# ── traducidos: todas descartadas ──────────────────────────────────────────────

async def test_traducido_descarta_todas_y_cuenta():
    doc = corpus.load("claude_code_messages_beta")
    c, cut, out, headers = await _run(fx.snapshot("on"), doc["headers"]["anthropic-beta"])
    assert cut is None and out["model"] == "rdx-chatcompat/qwen-destino"
    assert _beta_of(headers) is None
    n = len(doc["headers"]["anthropic-beta"].split(","))
    assert c.routing_decision["extensions"]["redirect"]["betas_dropped"] == n


async def test_traducido_sin_cabecera_no_audita_nada():
    p = RedirectPlugin(store=fx.store(fx.snapshot("on")), ping_after=0.05)
    c = fx.ctx(route="/v1/messages", model="claude-sonnet-4-5")
    await p.pre_request(c)
    p.pre_engine(c, {"model": "claude-sonnet-4-5", "messages": []}, {})
    assert "betas_dropped" not in c.routing_decision["extensions"]["redirect"]


async def test_la_cabecera_se_quita_aunque_la_pasarela_la_haya_reenviado():
    # la lista de cabeceras de la pasarela se calcula antes de una posible sustitución por capacidad: el
    # destino final manda; un traducido nunca recibe betas
    p = RedirectPlugin(store=fx.store(fx.snapshot("on")), ping_after=0.05)
    c = fx.ctx(route="/v1/messages", model="claude-sonnet-4-5", headers=_headers("claude-code-20250219"))
    await p.pre_request(c)
    _, headers = p.pre_engine(c, {"model": "claude-sonnet-4-5", "messages": []},
                              {"Anthropic-Beta": "claude-code-20250219", "x-otra": "1"})
    assert _beta_of(headers) is None and headers["x-otra"] == "1"


def test_forward_headers_allowlist_solo_para_nativos():
    p = RedirectPlugin(store=fx.store(fx.snapshot("on")), ping_after=0.05)
    c = fx.ctx(route="/v1/messages")
    assert p.forward_headers_allowlist(c) == set()
    c.state[STATE_KEY] = type("P", (), {"shadow": False, "face": "claude", "destination": fx.DEST_ANTHROPIC})()
    assert p.forward_headers_allowlist(c) == {"anthropic-beta"}
    c.state[STATE_KEY] = type("P", (), {"shadow": False, "face": "claude", "destination": fx.DEST_CHAT})()
    assert p.forward_headers_allowlist(c) == set()


# ── FR-042: suscripción personal hacia un destino de otro proveedor ─────────────

def _err(resp):
    import json
    return resp.status_code, json.loads(resp.body)


async def test_suscripcion_personal_hacia_destino_de_otro_proveedor_es_401():
    c, cut, _, _ = await _run(fx.snapshot("on"), "claude-code-20250219", mode="subscription")
    status, body = _err(cut)
    assert status == 401 and body["error"]["type"] == "authentication_error"
    assert body == {"type": "error", "error": {"type": "authentication_error",
                                               "message": "Credencial no válida para este modelo."}}
    red = c.routing_decision["extensions"]["redirect"]
    assert red["path"] == "subscription" and red["rejected"] == "subscription_credential"
    assert "Qwen" not in cut.body.decode() and "d-chat" not in cut.body.decode()   # no revela el destino


async def test_suscripcion_hacia_un_destino_del_mismo_proveedor_sigue_su_camino():
    _, cut, _, _ = await _run(fx.snapshot("on", claude_targets=("d-ant",)), "claude-code-20250219",
                              mode="subscription", **US)
    assert cut is None


async def test_suscripcion_con_politica_apagada_o_en_sombra_no_cambia():
    for state in ("off", "shadow"):
        _, cut, _, _ = await _run(fx.snapshot(state), "claude-code-20250219", mode="subscription")
        assert cut is None, state


async def test_suscripcion_con_un_modelo_no_publicado_no_se_toca():
    p = RedirectPlugin(store=fx.store(fx.snapshot("on")), ping_after=0.05)
    c = fx.ctx(route="/v1/messages", model="claude-3-5-haiku-latest", mode="subscription")
    assert await p.pre_request(c) is None


async def test_byok_hacia_traducido_no_es_401():
    _, cut, out, _ = await _run(fx.snapshot("on"), "claude-code-20250219", mode="byok")
    assert cut is None and out["model"] == "rdx-chatcompat/qwen-destino"
