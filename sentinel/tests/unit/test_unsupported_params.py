"""Parámetros no soportados por modelo (069 enmienda T162–T169).

La ficha del catálogo declara qué parámetros del pedido el modelo no acepta (p. ej. `temperature`) y
Sentinel los quita ANTES de que lleguen al proveedor, en todas las caras: consola/playground (la
autorización firmada), `/gw` OpenAI y cara Anthropic (plugin de la pasarela + guard), clientes que le
hablan directo al motor (catálogo servido) y el destino que elige el auto-router (es un `public_id`
del catálogo que entra por el chat). La auditoría guarda SOLO los nombres.
"""
import json
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))

from sentinel.catalog import validation as cv  # noqa: E402
from sentinel.engine import redirect_catalog as rcat  # noqa: E402
from sentinel.engine import redirect_guard as g  # noqa: E402
from sentinel.redirect import authz  # noqa: E402
from sentinel.redirect.plugin import RedirectPlugin  # noqa: E402
from sentinel.tests import redirect_fixtures as fx  # noqa: E402

KEY = "k" * 48
NOW = 1_800_000_000.0
MODEL = "rdx-openai/gpt-6.1-sol"


# ── validación de la lista (la ficha) ─────────────────────────────────────────

def test_la_lista_se_normaliza_sin_duplicados_ni_espacios():
    assert cv.check_unsupported_params([" temperature ", "top_p", "temperature"]) == ["temperature", "top_p"]
    assert cv.check_unsupported_params([]) == []


@pytest.mark.parametrize("bad", ["temperature", {"temperature": True}, [1], [""], ["Temperature"],
                                 ["temp erature"], ["a" * 65], [f"p{i}" for i in range(33)]])
def test_formas_invalidas_se_rechazan(bad):
    with pytest.raises(ValueError):
        cv.check_unsupported_params(bad)


@pytest.mark.parametrize("name", ["model", "messages", "input", "prompt", "stream", "api_key", "api_base"])
def test_los_campos_estructurales_no_se_pueden_quitar(name):
    with pytest.raises(ValueError) as exc:
        cv.check_unsupported_params([name])
    assert name in str(exc.value)


# H1 del QA del PR #78: los campos que escribe el propio guard y los internos del motor tampoco se quitan.
@pytest.mark.parametrize("name", [
    "input_cost_per_token", "output_cost_per_token", "timeout", "num_retries", "max_parallel_requests",
    "proxy_server_request", "litellm_params", "custom_llm_provider", "mock_response", "metadata",
    "user_api_key", "user_api_key_hash", "user_api_key_team_id"])
def test_los_campos_del_guard_y_los_internos_del_motor_no_se_pueden_quitar(name):
    with pytest.raises(ValueError) as exc:
        cv.check_unsupported_params([name])
    assert name in str(exc.value)


def test_un_nombre_parecido_pero_no_protegido_sigue_valiendo():
    assert cv.check_unsupported_params(["user_api", "timeout_ms", "top_p"]) == ["user_api", "timeout_ms", "top_p"]


# ── la autorización firmada lleva la lista ─────────────────────────────────────

def _token(**kw):
    args = dict(request_id="r1", scope="t1/user:u1", destination_id="d1", model=MODEL, provider="openai",
                credential={"api_key": "sk-x"}, decision={"public_id": "gpt-6.1-sol"}, key=KEY, now=NOW)
    args.update(kw)
    return authz.issue(**args)


def test_la_autorizacion_viaja_la_lista_firmada():
    grant = authz.verify(_token(drop_params=["temperature", "top_p"]), expected_model=MODEL, key=KEY, now=NOW)
    assert grant.drop_params == ("temperature", "top_p")


def test_una_autorizacion_sin_lista_sigue_valiendo():
    assert authz.verify(_token(), expected_model=MODEL, key=KEY, now=NOW).drop_params == ()


# ── guard del motor: consola/playground y plugin firman, el guard quita ───────

def _request(tok, **extra):
    hdrs = {"x-redirect-authz": tok}
    data = {"model": MODEL, "messages": [{"role": "user", "content": "hola"}],
            "proxy_server_request": {"headers": dict(hdrs)}, "metadata": {"headers": dict(hdrs)}}
    data.update(extra)
    return data


def _decision(data):
    return data["metadata"]["_internal_routing_decision"]["extensions"]["redirect"]


def test_guard_quita_temperature_si_la_autorizacion_la_declara():
    data = g.apply_redirect(_request(_token(drop_params=["temperature"]), temperature=0.3, max_tokens=50),
                            key=KEY, now=NOW, environ={})
    assert "temperature" not in data and data["max_completion_tokens"] == 50
    assert _decision(data)["dropped_params"] == "temperature"


def test_guard_conserva_temperature_si_la_ficha_no_la_marca():
    data = g.apply_redirect(_request(_token(), temperature=0.3), key=KEY, now=NOW, environ={})
    assert data["temperature"] == 0.3
    assert "dropped_params" not in _decision(data)


def test_guard_no_audita_lo_que_el_pedido_no_traia():
    data = g.apply_redirect(_request(_token(drop_params=["temperature", "top_p"]), top_p=0.9),
                            key=KEY, now=NOW, environ={})
    assert "top_p" not in data and _decision(data)["dropped_params"] == "top_p"


def test_guard_sin_nada_que_quitar_no_escribe_la_clave():
    data = g.apply_redirect(_request(_token(drop_params=["temperature"])), key=KEY, now=NOW, environ={})
    assert "dropped_params" not in _decision(data)


def test_la_auditoria_lleva_solo_los_nombres_nunca_el_valor():
    data = g.apply_redirect(_request(_token(drop_params=["temperature"]), temperature=0.31337),
                            key=KEY, now=NOW, environ={})
    assert "0.31337" not in json.dumps(data["metadata"], default=str)


def test_cara_anthropic_del_motor_se_limpia_igual():
    """`/v1/messages` llega al motor como `anthropic_messages`: el campo está en la raíz del cuerpo."""
    data = g.apply_redirect(_request(_token(drop_params=["temperature", "top_p"]), temperature=1, top_p=1,
                                     system="s", max_tokens=100),
                            key=KEY, now=NOW, environ={}, call_type="anthropic_messages")
    assert "temperature" not in data and "top_p" not in data and data["max_tokens"] == 100


PROTEGIDOS_DEL_GUARD = ["input_cost_per_token", "output_cost_per_token", "timeout", "num_retries"]


def test_guard_conserva_el_precio_aunque_la_lista_nombre_sus_campos():
    """H1: una lista (vieja o manipulada) con los campos de costo no anula el descuento del presupuesto."""
    tok = _token(drop_params=PROTEGIDOS_DEL_GUARD + ["temperature"], price={"input_per_mtok": 2, "output_per_mtok": 8})
    data = g.apply_redirect(_request(tok, temperature=0.3), key=KEY, now=NOW, environ={})
    assert data["input_cost_per_token"] == 2e-06 and data["output_cost_per_token"] == 8e-06
    assert "temperature" not in data
    assert _decision(data)["pricing"] == "destination"


def test_guard_el_caso_normal_sigue_quitando_temperature_con_precio():
    tok = _token(drop_params=["temperature"], price={"input_per_mtok": 2, "output_per_mtok": 8})
    data = g.apply_redirect(_request(tok, temperature=0.3), key=KEY, now=NOW, environ={})
    assert "temperature" not in data and data["input_cost_per_token"] == 2e-06
    assert _decision(data)["dropped_params"] == "temperature"


def test_lo_que_ya_quito_la_pasarela_se_suma_en_la_auditoria():
    tok = _token(drop_params=["temperature", "top_p"],
                 decision={"public_id": "gpt-6.1-sol", "dropped_params": "temperature"})
    data = g.apply_redirect(_request(tok, top_p=0.5), key=KEY, now=NOW, environ={})
    assert _decision(data)["dropped_params"] == "temperature,top_p"


# ── clientes que le hablan directo al motor (catálogo servido) ─────────────────

T1 = "11111111-1111-1111-1111-111111111111"
ENTRY = {"entry_id": "e1", "name": "GPT 6.1 sol", "provider": "openai", "real_model": "gpt-6.1-sol",
         "api_base": None, "protocol_family": "openai_responses", "level": "tenant",
         "semaforo": {"estado": "standard", "motivos": []}, "jurisdiccion": "unknown",
         "price": {"input": None, "output": None}}


class Backend:
    def __init__(self, entry):
        self.entry = entry

    async def __call__(self, path, params):
        if path.endswith("model-access"):
            return 200, {"restringe": False, "permitidos": []}
        if path.endswith("model-catalog"):
            return 200, {"version": "v1", "direct": True, "entries": {"gpt-6.1-sol": self.entry}}
        return 200, {"credential": {"api_key": "sk-x"}}


async def _direct(entry, **extra):
    data = {"model": "gpt-6.1-sol", "messages": [{"role": "user", "content": "hola"}], **extra}
    user = SimpleNamespace(metadata={"sentinel": {"tenant_id": T1}})
    ok = await rcat.CatalogDirect(fetch=Backend(entry), environ={}).apply(data, user, call_type="acompletion")
    assert ok
    return data


async def test_directo_quita_lo_marcado_y_lo_audita():
    d = await _direct(dict(ENTRY, unsupported_params=["temperature", "top_p"]), temperature=0.3, top_p=1, max_tokens=50)
    assert "temperature" not in d and "top_p" not in d and d["max_completion_tokens"] == 50
    assert d["metadata"]["_internal_routing_decision"]["extensions"]["redirect"]["dropped_params"] == "temperature,top_p"


async def test_directo_chat_con_tools_y_razonamiento_va_por_responses():
    """T193: la ruta directa del catálogo aplica el mismo puente que la redirección."""
    tools = [{"type": "function", "function": {"name": "f"}}]
    d = await _direct(ENTRY, tools=tools, reasoning_effort="high")
    assert d["model"] == "openai/responses/gpt-6.1-sol" or d["model"].endswith("/responses/gpt-6.1-sol")
    assert "chat->responses" in d["metadata"]["_internal_routing_decision"]["extensions"]["redirect"]["adjusted_params"]


async def test_directo_sin_razonamiento_no_se_puentea():
    d = await _direct(ENTRY, tools=[{"type": "function"}])
    assert "responses/" not in d["model"]


async def test_directo_conserva_precio_y_limites_aunque_la_lista_nombre_sus_campos():
    """H1: ni el costo del catálogo ni `timeout`/`num_retries` de la ficha se pueden quitar por la lista."""
    entry = dict(ENTRY, unsupported_params=PROTEGIDOS_DEL_GUARD + ["temperature"],
                 price={"input": 2e-6, "output": 8e-6}, limits={"timeout": 30, "num_retries": 2})
    d = await _direct(entry, temperature=0.3)
    assert d["input_cost_per_token"] == pytest.approx(2e-6) and d["output_cost_per_token"] == pytest.approx(8e-6)
    assert d["timeout"] == 30 and d["num_retries"] == 2
    assert "temperature" not in d
    assert d["metadata"]["_internal_routing_decision"]["extensions"]["redirect"]["dropped_params"] == "temperature"


async def test_directo_sin_marca_conserva_temperature():
    d = await _direct(dict(ENTRY, unsupported_params=[]), temperature=0.3)
    assert d["temperature"] == 0.3
    assert "dropped_params" not in d["metadata"]["_internal_routing_decision"]["extensions"]["redirect"]


async def test_directo_con_catalogo_viejo_sin_la_clave_conserva_temperature():
    d = await _direct(dict(ENTRY), temperature=0.3)
    assert d["temperature"] == 0.3


# ── consola/playground y auto-router: el chat firma con la lista de la entrada ──

pytest.importorskip("src.services.model_route_hook", reason="requiere el venv del backend")
from sentinel.catalog import chat_route as cr  # noqa: E402

EID = str(uuid.uuid4())
CHAT_ENTRY = {"entry_id": EID, "name": "GPT", "provider": "openai", "real_model": "gpt-6.1-sol", "api_base": None,
              "role": "text", "level": "tenant", "semaforo": {"estado": "eu_ok", "motivos": []},
              "price": {"input": 2e-6, "output": 1e-5}, "limits": {}, "unsupported_params": ["temperature"]}
USER = SimpleNamespace(id=uuid.uuid4(), group_id=None, tenant_id=T1)


@pytest.fixture
def chat(monkeypatch):
    monkeypatch.setenv(authz.KEY_ENV, KEY)
    monkeypatch.setattr(cr, "CATALOG", lambda tenant: {"gpt-6.1-sol": CHAT_ENTRY,
                                                       "otro": dict(CHAT_ENTRY, unsupported_params=[])})
    monkeypatch.setattr(cr, "CREDENTIAL", lambda tenant, entry_id: {"api_key": "sk-secreta"})


def _chat_grant(model):
    r = cr.route(T1, USER, model)
    return authz.verify(r.headers[authz.HEADER], expected_model=r.engine_model, key=KEY), r


def test_chat_firma_la_lista_y_el_guard_limpia_el_temperature_fijo_de_la_consola(chat):
    grant, routed = _chat_grant("gpt-6.1-sol")
    assert grant.drop_params == ("temperature",)
    # el cuerpo que arma la consola lleva `temperature: 0.3` fijo (chat.py:1573)
    body = {"model": routed.engine_model, "messages": [{"role": "user", "content": "hola"}], "temperature": 0.3}
    hdrs = dict(routed.headers)
    data = g.apply_redirect({**body, "proxy_server_request": {"headers": hdrs}, "metadata": {}},
                            key=KEY, environ={})
    assert "temperature" not in data


def test_chat_de_un_modelo_sin_marca_conserva_temperature(chat):
    grant, routed = _chat_grant("otro")
    assert grant.drop_params == ()
    data = g.apply_redirect({"model": routed.engine_model, "messages": [], "temperature": 0.3,
                             "proxy_server_request": {"headers": dict(routed.headers)}, "metadata": {}},
                            key=KEY, environ={})
    assert data["temperature"] == 0.3


def test_la_ruta_del_chat_lleva_la_lista_para_la_fila_de_auditoria(chat):
    """El backend no ve lo que el guard quita en el motor: la costura devuelve la lista de la ficha para que la
    fila de la consola liste los nombres (misma lista que va firmada en `drp`)."""
    _, routed = _chat_grant("gpt-6.1-sol")
    assert routed.unsupported_params == ("temperature",)
    _, routed = _chat_grant("otro")
    assert routed.unsupported_params == ()


def test_el_destino_que_elige_el_auto_router_se_trata_igual(chat):
    """El auto-router solo reasigna `request.model` a un `public_id` del catálogo (chat.py:1114-1140) y
    el pedido pasa DESPUÉS por `route_model` (chat.py:1564): el destino elegido firma su propia lista."""
    chosen = "gpt-6.1-sol"          # lo que devuelve `auto_router_service.route(...)["model_selected"]`
    grant, _ = _chat_grant(chosen)
    assert grant.drop_params == ("temperature",)


# ── plugin de la pasarela: /gw OpenAI y cara Anthropic ────────────────────────

@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setenv(authz.KEY_ENV, fx.INTERNAL_KEY)


def _plugin(dest_extra, face_targets):
    snap = fx.snapshot("on", **face_targets)
    snap.destinations["d-chat"] = dict(fx.DEST_CHAT, **dest_extra)
    snap.destinations["d-ant"] = dict(fx.DEST_ANTHROPIC, **dest_extra)
    return RedirectPlugin(store=fx.store(snap), ping_after=0.05)


async def test_gw_openai_sale_sin_temperature_y_lo_audita():
    p, c = _plugin({"unsupported_params": ["temperature"]}, {}), fx.ctx()
    await p.pre_request(c)
    out, headers = p.pre_engine(c, {"model": "pro", "messages": [{"role": "user", "content": "hola"}],
                                    "temperature": 0.3, "top_p": 0.9}, {})
    assert "temperature" not in out and out["top_p"] == 0.9
    assert c.routing_decision["extensions"]["redirect"]["dropped_params"] == "temperature"
    assert authz.verify(headers[authz.HEADER], expected_model=out["model"]).drop_params == ("temperature",)


async def test_cara_anthropic_traducida_sale_sin_temperature_ni_top_p():
    p = _plugin({"unsupported_params": ["temperature", "top_p"]}, {})
    c = fx.ctx(route="/v1/messages", model="claude-sonnet-4-5")
    await p.pre_request(c)
    out, headers = p.pre_engine(c, {"model": "claude-sonnet-4-5", "max_tokens": 100, "temperature": 1.0,
                                    "top_p": 0.9, "messages": [{"role": "user", "content": "hola"}]}, {})
    assert "temperature" not in out and "top_p" not in out
    assert c.routing_decision["extensions"]["redirect"]["dropped_params"] == "temperature,top_p"
    assert authz.verify(headers[authz.HEADER], expected_model=out["model"]).drop_params == ("temperature", "top_p")


async def test_cara_anthropic_nativa_tambien():
    p = _plugin({"unsupported_params": ["temperature"]}, {"claude_targets": ("d-ant",)})
    c = fx.ctx(route="/v1/messages", model="claude-sonnet-4-5", nlp={"region": "us"})
    assert await p.pre_request(c) is None
    out, _ = p.pre_engine(c, {"model": "claude-sonnet-4-5", "max_tokens": 100, "temperature": 0.2,
                              "messages": [{"role": "user", "content": "hola"}]}, {})
    assert "temperature" not in out


async def test_gw_sin_marca_conserva_temperature_y_no_audita_nada():
    p, c = _plugin({}, {}), fx.ctx()
    await p.pre_request(c)
    out, _ = p.pre_engine(c, {"model": "pro", "messages": [], "temperature": 0.3}, {})
    assert out["temperature"] == 0.3
    assert "dropped_params" not in c.routing_decision["extensions"]["redirect"]
