"""057 T068/T073/T074 (FR-043, FR-045; research R18; T124/T132 de Sentinel): afinidad de sesión y referencia de conversación.

Con `x-claude-code-session-id` (y `x-claude-code-agent-id` en un subagente) la pasarela deriva, con la clave del servidor
(`MASKING_NONCE_KEY`), dos identificadores que NUNCA son el original ni llevan datos de la persona:

· `sentinel_conversation_ref = HMAC(clave, "conv" | empresa | sesión)`, que el guardrail del motor usa para el sufijo de los
  marcadores (S13): la pasarela la escribe y descarta la del cliente;
· el identificador de afinidad `HMAC(clave, "affinity" | empresa | sesión | agente)`, solo hacia un destino que declara
  `session_affinity`; viaja firmado en la autorización y el guard lo manda al destino (`session_id` en OpenRouter, `x-session-id`
  en los demás). Sin cabecera, sin la capacidad o sin la clave: nada."""
import hashlib
import hmac
import json

import pytest

from sentinel.engine import redirect_guard as guard
from sentinel.redirect import authz, session_ids
from sentinel.redirect.plugin import RedirectPlugin
from sentinel.tests import redirect_fixtures as fx

CLAVE = "n" * 48
SESION = "sess-0001"
AGENTE = "agent-9"
OR_DEST = {**fx.DEST_CHAT, "provider": "openrouter", "provider_options": {"providers_allowlist": ["acme-us"]},
           "capability_profile": {"thinking": False, "cache_control": False, "images": False, "session_affinity": True}}


@pytest.fixture(autouse=True)
def _entorno(monkeypatch):
    monkeypatch.setenv(authz.KEY_ENV, fx.INTERNAL_KEY)
    monkeypatch.setenv("MASKING_NONCE_KEY", CLAVE)


def _esperado(dominio, *partes, clave=CLAVE):
    return hmac.new(clave.encode(), b"\x00".join([dominio.encode(), *[p.encode() for p in partes]]),
                    hashlib.sha256).hexdigest()[:32]


def _snap(dest):
    snap = fx.snapshot("on")
    return snap.__class__(**{**snap.__dict__, "destinations": {**snap.destinations, "d-chat": dest}})


async def _plan(dest=OR_DEST, headers=None, tenant=None, route="/v1/messages", model="claude-sonnet-4-5", body=None):
    p = RedirectPlugin(store=fx.store(_snap(dest)), ping_after=0.05)
    c = fx.ctx(route=route, model=model, headers=headers or {}, **({"tenant_id": tenant} if tenant else {}))
    assert await p.pre_request(c) is None
    cuerpo = body or {"model": model, "max_tokens": 8, "messages": [{"role": "user", "content": "hola"}]}
    out, hdrs = p.pre_engine(c, cuerpo, {})
    return out, authz.verify(hdrs[authz.HEADER], key=fx.INTERNAL_KEY), c


# ── la derivación ──────────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_con_la_cabecera_y_la_capacidad_el_grant_lleva_la_afinidad_derivada_con_la_clave():
    _, grant, _ = await _plan(headers={"x-claude-code-session-id": SESION})
    assert grant.affinity == _esperado("affinity", fx.TENANT, SESION, "")
    assert grant.affinity != SESION and SESION not in json.dumps(grant.decision)


@pytest.mark.asyncio
async def test_es_estable_y_distinta_entre_empresas_sesiones_y_subagentes():
    h = {"x-claude-code-session-id": SESION}
    a, b = (await _plan(headers=h))[1].affinity, (await _plan(headers=h))[1].affinity
    assert a == b
    assert session_ids.affinity_id(fx.TENANT, SESION) != session_ids.affinity_id(fx.OTHER, SESION)
    assert session_ids.conversation_ref(fx.TENANT, SESION) != session_ids.conversation_ref(fx.OTHER, SESION)
    sub = (await _plan(headers={**h, "x-claude-code-agent-id": AGENTE}))[1].affinity
    otra_sesion = (await _plan(headers={"x-claude-code-session-id": "sess-0002"}))[1].affinity
    assert len({a, sub, otra_sesion}) == 3 and sub == _esperado("affinity", fx.TENANT, SESION, AGENTE)


@pytest.mark.asyncio
@pytest.mark.parametrize("caso", ["sin_cabecera", "sin_capacidad", "sin_clave", "clave_corta"])
async def test_sin_cabecera_capacidad_o_clave_no_hay_afinidad(monkeypatch, caso):
    dest, headers = OR_DEST, {"x-claude-code-session-id": SESION}
    if caso == "sin_cabecera":
        headers = {}
    elif caso == "sin_capacidad":
        dest = {**OR_DEST, "capability_profile": {"session_affinity": False}}
    elif caso == "sin_clave":
        monkeypatch.delenv("MASKING_NONCE_KEY")
    else:
        monkeypatch.setenv("MASKING_NONCE_KEY", "corta")
    _, grant, _ = await _plan(dest=dest, headers=headers)
    assert grant.affinity is None


@pytest.mark.asyncio
async def test_la_afinidad_va_firmada_una_autorizacion_manipulada_no_vale():
    body, _, _ = await _plan(headers={"x-claude-code-session-id": SESION})
    p = RedirectPlugin(store=fx.store(_snap(OR_DEST)), ping_after=0.05)
    c = fx.ctx(route="/v1/messages", model="claude-sonnet-4-5", headers={"x-claude-code-session-id": SESION})
    await p.pre_request(c)
    _, hdrs = p.pre_engine(c, {"model": "x", "max_tokens": 1, "messages": []}, {})
    token = hdrs[authz.HEADER]
    cabeza, cuerpo, firma = token.split(".")
    adulterado = ".".join([cabeza, cuerpo[:-2] + ("AA" if not cuerpo.endswith("AA") else "BB"), firma])
    with pytest.raises(authz.AuthzError):
        authz.verify(adulterado, key=fx.INTERNAL_KEY)
    del body


# ── el guard la aplica ─────────────────────────────────────────────────────────────────────────────

def _al_guard(provider="openrouter", affinity="a" * 32, extra=None):
    family = guard.credentials.PROVIDER_FAMILY[provider]
    model = family + "/m"
    tok = authz.issue(request_id="r", scope=f"{fx.TENANT}/connection:k", destination_id="d", model=model,
                      provider=provider, credential={"api_key": "sk-d"}, api_base="http://d.local/v1",
                      provider_options={"providers_allowlist": ["acme-us"]}, affinity=affinity,
                      decision={"public_id": "pro", "face": "openai_generic"}, key=fx.INTERNAL_KEY)
    data = {"model": model, "messages": [{"role": "user", "content": "hola"}],
            "proxy_server_request": {"headers": {authz.HEADER: tok}}, "metadata": {}, **(extra or {})}
    return guard.apply_redirect(data, key=fx.INTERNAL_KEY, call_type="completion", environ={})


def test_el_guard_manda_session_id_a_openrouter_y_lo_audita_sin_el_valor():
    out = _al_guard()
    assert out["extra_body"]["session_id"] == "a" * 32
    rd = out["metadata"]["_internal_routing_decision"]["extensions"]["redirect"]
    assert rd["session_affinity"] is True and "a" * 32 not in json.dumps(rd)


def test_el_identificador_que_mande_el_cliente_se_descarta():
    out = _al_guard(extra={"extra_body": {"session_id": "del-cliente", "otro": 1}})
    assert out["extra_body"]["session_id"] == "a" * 32 and out["extra_body"]["otro"] == 1
    sin = _al_guard(affinity=None, extra={"extra_body": {"session_id": "del-cliente"}})
    assert "session_id" not in sin["extra_body"]


def test_hacia_otro_proveedor_con_la_capacidad_va_como_cabecera():
    out = _al_guard(provider="openai_compatible")
    assert out["extra_headers"]["x-session-id"] == "a" * 32 and "session_id" not in (out.get("extra_body") or {})


def test_sin_afinidad_el_guard_no_agrega_nada():
    out = _al_guard(provider="openai_compatible", affinity=None)
    assert "x-session-id" not in (out.get("extra_headers") or {})
    rd = out["metadata"]["_internal_routing_decision"]["extensions"]["redirect"]
    assert "session_affinity" not in rd


# ── la referencia de conversación (T073) ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_la_pasarela_escribe_la_referencia_de_conversacion_derivada_con_la_clave():
    out, _, _ = await _plan(headers={"x-claude-code-session-id": SESION})
    ref = out["litellm_metadata"]["sentinel_conversation_ref"]
    assert ref == _esperado("conv", fx.TENANT, SESION) and ref != SESION
    assert SESION not in json.dumps(out)


@pytest.mark.asyncio
async def test_la_referencia_no_lleva_el_agente_la_conversacion_es_la_misma_entre_subagentes():
    a, _, _ = await _plan(headers={"x-claude-code-session-id": SESION})
    b, _, _ = await _plan(headers={"x-claude-code-session-id": SESION, "x-claude-code-agent-id": AGENTE})
    assert a["litellm_metadata"]["sentinel_conversation_ref"] == b["litellm_metadata"]["sentinel_conversation_ref"]


@pytest.mark.asyncio
async def test_la_cara_generica_la_escribe_en_metadata():
    out, _, _ = await _plan(route="/v1/chat/completions", model="pro",
                            headers={"x-claude-code-session-id": SESION},
                            body={"model": "pro", "messages": [{"role": "user", "content": "hola"}]})
    assert out["metadata"]["sentinel_conversation_ref"] == _esperado("conv", fx.TENANT, SESION)


@pytest.mark.asyncio
async def test_la_que_manda_el_cliente_se_reemplaza_o_se_quita():
    cuerpo = {"model": "claude-sonnet-4-5", "max_tokens": 8, "messages": [{"role": "user", "content": "hola"}],
              "litellm_metadata": {"sentinel_conversation_ref": "del-cliente"}}
    out, _, _ = await _plan(headers={"x-claude-code-session-id": SESION}, body=cuerpo)
    assert out["litellm_metadata"]["sentinel_conversation_ref"] == _esperado("conv", fx.TENANT, SESION)
    cuerpo2 = {"model": "claude-sonnet-4-5", "max_tokens": 8, "messages": [{"role": "user", "content": "hola"}],
               "litellm_metadata": {"sentinel_conversation_ref": "del-cliente"}}
    sin, _, _ = await _plan(headers={}, body=cuerpo2)
    assert "sentinel_conversation_ref" not in json.dumps(sin)


@pytest.mark.asyncio
async def test_sin_la_clave_no_hay_referencia(monkeypatch):
    monkeypatch.delenv("MASKING_NONCE_KEY")
    out, _, _ = await _plan(headers={"x-claude-code-session-id": SESION})
    assert "sentinel_conversation_ref" not in json.dumps(out)


@pytest.mark.asyncio
async def test_la_sesion_tambien_se_toma_del_user_id_de_la_herramienta():
    cuerpo = {"model": "claude-sonnet-4-5", "max_tokens": 8, "messages": [{"role": "user", "content": "hola"}],
              "metadata": {"user_id": "user_" + "a" * 64 + "_account_" + "b" * 8 + "-1111_session_" + SESION}}
    out, _, _ = await _plan(headers={}, body=cuerpo)
    assert out["litellm_metadata"]["sentinel_conversation_ref"] == _esperado("conv", fx.TENANT, SESION)
