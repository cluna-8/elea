"""Modelos chinos y económicos en Claude Desktop y Claude Code (057 T024; requisito del owner; research R17).

Con upstream falso (sin red, sin Docker, sin Postgres): se dan de alta en el catálogo DeepSeek (`deepseek`), Qwen y Kimi
(`openai_compatible` con su `api_base`), GLM (`zai`) y los mismos modelos vía OpenRouter; se publican detrás de un id de
Claude con reglas, y se pide por la pasarela real con el plugin real:

- el pedido sale al motor con la familia correcta (`rdx-deepseek`, `rdx-chatcompat`, `rdx-zai`) y una autorización firmada;
- el guard del motor, con esa autorización, fija la credencial y la base **del destino** (nunca las del cliente);
- una regla con estrategia `cheapest` elige el destino de menor precio del catálogo y el costo que se registra es el del
  destino realmente elegido;
- con las listas de habilitación vacías (D1) ninguno nace bloqueado: alta, publicación y pedido funcionan.

La residencia se fija con una postura explícita de prueba (`off`): el default de Eleia es de T-E (research R32).
"""
import json
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))
gateway = pytest.importorskip("src.api.gateway", reason="requiere el venv del backend")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from src.api import gateway_plugins as gp  # noqa: E402

from sentinel.engine import redirect_guard as guard  # noqa: E402
from sentinel.redirect import authz  # noqa: E402
from sentinel.redirect import models as rm  # noqa: E402
from sentinel.redirect.plugin import RedirectPlugin  # noqa: E402
from sentinel.redirect.store import RedirectStore, load_from_session  # noqa: E402
from sentinel.tests import redirect_fixtures as fx  # noqa: E402
from sentinel.tests.catalog_fixtures import T1, create_entry, make_api  # noqa: E402
from sentinel.tests.integration.test_redirect_gateway_e2e import Engine  # noqa: E402

VK = "sk-sentinel-chinos-0001"
PUBLICO = "claude-sonnet-4-5"
INTERNAL_KEY = "k" * 48
OPENROUTER = "https://openrouter.ai/api/v1"

# nombre, proveedor, modelo real, api_base, familia esperada, USD por millón (entrada, salida)
DESTINOS = [
    ("DeepSeek V3", "deepseek", "deepseek-chat", None, "rdx-deepseek", (0.28, 0.42)),
    ("Qwen3 Max", "openai_compatible", "qwen3-max", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1", "rdx-chatcompat", (1.2, 6.0)),
    ("Kimi K2", "openai_compatible", "kimi-k2", "https://api.moonshot.ai/v1", "rdx-chatcompat", (0.6, 2.5)),
    ("GLM 4.6", "zai", "glm-4.6", None, "rdx-zai", (0.6, 2.2)),
    ("DeepSeek por OpenRouter", "openrouter", "deepseek/deepseek-chat", OPENROUTER, "rdx-chatcompat", (0.3, 0.45)),
    ("Qwen por OpenRouter", "openrouter", "qwen/qwen3-max", OPENROUTER, "rdx-chatcompat", (1.3, 6.2)),
    ("Kimi por OpenRouter", "openrouter", "moonshotai/kimi-k2", OPENROUTER, "rdx-chatcompat", (0.55, 2.3)),
    ("GLM por OpenRouter", "openrouter", "z-ai/glm-4.6", OPENROUTER, "rdx-chatcompat", (0.5, 2.0)),
]
IDS = [d[0] for d in DESTINOS]


def _secreto(nombre):
    return f"valor-inventado-{nombre.split()[0].lower()}"


@pytest.fixture
def mundo(monkeypatch):
    """Catálogo real (API) + política encendida + pasarela real con el plugin real + motor falso."""
    api = make_api(monkeypatch)
    monkeypatch.setenv(authz.KEY_ENV, INTERNAL_KEY)
    Engine.sent, Engine.status, Engine.stream_delay = [], 200, 0.0
    gp.clear_gateway_plugins()
    monkeypatch.delenv(gp.PLUGINS_ENV, raising=False)
    monkeypatch.setattr("src.services.auto_router_service.load_config", lambda: {})
    monkeypatch.setattr(gateway.httpx, "AsyncClient", Engine)
    audits = []
    monkeypatch.setattr(gateway, "_audit", lambda *a, **k: audits.append((a, k)) or True)
    monkeypatch.setattr(gateway, "_publish_monitor", lambda *a, **k: None)
    monkeypatch.setattr(gateway, "_audit_precheck_ok", lambda *_a: True)
    monkeypatch.setattr(gateway, "_resolve_attribution", lambda _k: fx.ident())
    from sentinel.access import bridge
    monkeypatch.setattr(bridge, "RESOLVER", lambda tenant, **kw: None)
    monkeypatch.setattr(bridge, "RISK", lambda ident: (None, None))

    entradas = {}
    for nombre, provider, real, base, _fam, (pin, pout) in DESTINOS:
        entradas[nombre] = create_entry(
            api, "tenant_admin", T1, name=nombre, provider=provider, real_model=real, api_base=base,
            protocol_family="openai_chat", price_input=pin / 1e6, price_output=pout / 1e6,
            credential={"new": {"name": f"c-{nombre}", "value": _secreto(nombre)}})

    def publicar(nombres, estrategia="order"):
        with api.Session() as s:
            pub = rm.RedirectPublishedModel(
                tenant_id=T1, face="claude", public_id=PUBLICO, family_tier="sonnet", is_family_default=True,
                label_mode="destination", scope_type="tenant", scope_value="*")
            s.add_all([
                pub,
                rm.RedirectPolicy(tenant_id=T1, scope_type="tenant", scope_value="*", state="on"),
                # postura explícita de prueba: sin ella rige el default de la región (T-E, research R32)
                rm.RedirectPosture(tenant_id=T1, scope_type="tenant", scope_value="*", mode="off",
                                   reason="postura de prueba", created_by_role="compliance_officer"),
            ])
            s.flush()
            s.add(rm.RedirectRule(tenant_id=T1, published_model_id=pub.id, scope_type="tenant", scope_value="*",
                                  targets=[entradas[n]["id"] for n in nombres], strategy=estrategia))
            s.commit()
        db = api.Session()
        store = RedirectStore(loader=lambda t: load_from_session(db, t, always=True), ttl=0,
                              key_models=lambda k: None, redis_factory=lambda: None,
                              decrypt=lambda blob: json.loads(blob[len("cifrado:"):][::-1]) if blob else {})
        gp.register_gateway_plugin(RedirectPlugin(store=store, ping_after=0.05))

    app = FastAPI()
    app.include_router(gateway.router)
    cliente = TestClient(app)

    def pedir(model=PUBLICO, stream=False, **extra):
        return cliente.post("/gw/v1/messages", headers={"Authorization": f"Bearer {VK}", "anthropic-version": "2023-06-01"},
                            json={"model": model, "max_tokens": 64, "stream": stream, **extra,
                                  "messages": [{"role": "user", "content": "hola"}]})

    def al_guard(enviado, environ=None):
        """Lo que el motor haría con ese pedido: el guard con la autorización que firmó la pasarela."""
        data = {**enviado["body"], "proxy_server_request": {"headers": enviado["headers"]}, "metadata": {}}
        return guard.apply_redirect(data, environ=environ or {})

    yield type("Mundo", (), dict(api=api, entradas=entradas, publicar=publicar, pedir=pedir, al_guard=al_guard, audits=audits))
    gp.clear_gateway_plugins()


# ── alta: nada nace bloqueado con las listas vacías (D1) ──────────────────────────────────────────

@pytest.mark.parametrize("nombre", IDS)
def test_el_alta_de_cada_modelo_funciona_y_nace_sin_bloqueo(mundo, nombre):
    e = mundo.entradas[nombre]
    assert e["status"] == "active" and e["blocked_by_default"] is False and e["has_credential"] is True
    assert _secreto(nombre) not in json.dumps(e)                       # el secreto nunca vuelve


def test_openrouter_se_declara_agregador_y_los_directos_no(mundo):
    assert all(mundo.entradas[n]["is_aggregator"] is ("OpenRouter" in n) for n in IDS)


# ── el guard los manda a la familia correcta, con la credencial y la base del destino ─────────────

@pytest.mark.parametrize("nombre,provider,real,base,familia,precio", DESTINOS, ids=IDS)
def test_cada_destino_va_a_su_familia_con_su_credencial_y_su_base(mundo, nombre, provider, real, base, familia, precio):
    mundo.publicar([nombre])
    r = mundo.pedir(api_base="http://atacante.example", api_key="valor-del-cliente-NO-USAR")
    assert r.status_code == 200, r.text
    enviado = Engine.sent[-1]
    assert enviado["url"].endswith("/v1/messages") and enviado["body"]["model"] == f"{familia}/{real}"
    assert "api_base" not in enviado["body"] and "api_key" not in enviado["body"]        # nada del cliente
    assert authz.HEADER in {k.lower() for k in enviado["headers"]}

    salida = mundo.al_guard(enviado)
    assert salida["model"] == f"{familia}/{real}"
    assert salida["api_key"] == _secreto(nombre)                                       # la credencial del destino
    esperada = base or ({"openrouter": OPENROUTER}.get(provider))
    if esperada:
        assert salida["api_base"] == esperada                                          # la base del destino
    else:
        assert "api_base" not in salida                                                # el motor usa la suya
    assert "atacante" not in json.dumps(salida, default=str)


@pytest.mark.parametrize("nombre,provider,real,base,familia,precio", DESTINOS, ids=IDS)
def test_el_costo_que_registra_el_guard_es_el_del_destino(mundo, nombre, provider, real, base, familia, precio):
    mundo.publicar([nombre])
    mundo.pedir()
    salida = mundo.al_guard(Engine.sent[-1])
    assert salida["input_cost_per_token"] == pytest.approx(precio[0] / 1e6)
    assert salida["output_cost_per_token"] == pytest.approx(precio[1] / 1e6)


def test_la_respuesta_vuelve_con_el_id_publico_y_la_auditoria_dice_el_destino_real(mundo):
    mundo.publicar(["GLM 4.6"])
    r = mundo.pedir()
    assert r.json()["model"] == PUBLICO and "glm-4.6" not in r.text
    entrada = mundo.entradas["GLM 4.6"]
    decision = mundo.al_guard(Engine.sent[-1])["metadata"]["_internal_routing_decision"]["extensions"]["redirect"]
    assert decision["destination_id"] == entrada["id"] and decision["public_id"] == PUBLICO


def test_el_stream_tambien_va_a_la_familia_correcta(mundo):
    mundo.publicar(["Kimi K2"])
    r = mundo.pedir(stream=True)
    assert r.status_code == 200 and b"qwen-destino" not in r.content           # el modelo real no se filtra
    assert Engine.sent[-1]["body"]["model"] == "rdx-chatcompat/kimi-k2"


# ── cheapest: el de menor precio del catálogo, y el costo es el del destino elegido ───────────────

def _mas_barato(nombres):
    return min(nombres, key=lambda n: sum(next(d[5] for d in DESTINOS if d[0] == n)))


def test_cheapest_elige_el_destino_de_menor_precio_entre_todos(mundo):
    mundo.publicar(IDS, "cheapest")
    r = mundo.pedir()
    assert r.status_code == 200, r.text
    barato = _mas_barato(IDS)
    assert barato == "DeepSeek V3"
    _, _, real, _, familia, precio = next(d for d in DESTINOS if d[0] == barato)
    assert Engine.sent[-1]["body"]["model"] == f"{familia}/{real}"
    salida = mundo.al_guard(Engine.sent[-1])
    assert salida["input_cost_per_token"] == pytest.approx(precio[0] / 1e6)          # costo del destino REAL
    assert salida["output_cost_per_token"] == pytest.approx(precio[1] / 1e6)
    assert salida["api_key"] == _secreto(barato)
    decision = salida["metadata"]["_internal_routing_decision"]["extensions"]["redirect"]
    assert decision["strategy"] == "cheapest" and decision["destination_id"] == mundo.entradas[barato]["id"]


def test_con_order_manda_el_primero_aunque_no_sea_el_mas_barato(mundo):
    mundo.publicar(["Qwen3 Max", "Kimi K2", "DeepSeek V3"], "order")
    mundo.pedir()
    assert Engine.sent[-1]["body"]["model"] == "rdx-chatcompat/qwen3-max"
    salida = mundo.al_guard(Engine.sent[-1])
    assert salida["input_cost_per_token"] == pytest.approx(1.2 / 1e6)            # y el costo es el de ese, no el del barato


def test_cheapest_con_el_mas_barato_apagado_elige_el_siguiente(mundo):
    mundo.publicar(IDS, "cheapest")
    barato = mundo.entradas["DeepSeek V3"]
    assert mundo.api.call("PATCH", f"/entries/{barato['id']}", "tenant_admin", json={"status": "inactive"}).status_code == 200
    mundo.pedir()
    siguiente = _mas_barato([n for n in IDS if n != "DeepSeek V3"])
    _, _, real, _, familia, _ = next(d for d in DESTINOS if d[0] == siguiente)
    assert Engine.sent[-1]["body"]["model"] == f"{familia}/{real}"


def test_cheapest_deja_al_final_lo_que_no_tiene_precio(mundo):
    api = mundo.api
    sin_precio = create_entry(api, "tenant_admin", T1, name="Sin precio", provider="zai", real_model="glm-4.5",
                              protocol_family="openai_chat",
                              credential={"new": {"name": "c-sp", "value": "valor-inventado-sinprecio"}})
    mundo.entradas["Sin precio"] = sin_precio
    mundo.publicar(["Sin precio", "Qwen3 Max"], "cheapest")
    mundo.pedir()
    assert Engine.sent[-1]["body"]["model"] == "rdx-chatcompat/qwen3-max"       # el que tiene precio, aunque sea más caro


def test_el_precio_cambiado_en_el_catalogo_cambia_la_eleccion_sin_reiniciar(mundo):
    mundo.publicar(["Qwen3 Max", "Kimi K2"], "cheapest")
    mundo.pedir()
    assert Engine.sent[-1]["body"]["model"] == "rdx-chatcompat/kimi-k2"
    qwen = mundo.entradas["Qwen3 Max"]
    assert mundo.api.call("PATCH", f"/entries/{qwen['id']}", "tenant_admin",
                          json={"price_input": 0.01 / 1e6, "price_output": 0.01 / 1e6}).status_code == 200
    mundo.pedir()
    assert Engine.sent[-1]["body"]["model"] == "rdx-chatcompat/qwen3-max"
    assert mundo.al_guard(Engine.sent[-1])["input_cost_per_token"] == pytest.approx(0.01 / 1e6)


# ── el guard no se deja desviar ───────────────────────────────────────────────────────────────────

def test_el_guard_rechaza_la_autorizacion_de_un_destino_usada_con_el_modelo_de_otro(mundo):
    mundo.publicar(["GLM 4.6"])
    mundo.pedir()
    enviado = Engine.sent[-1]
    distinto = {**enviado, "body": {**enviado["body"], "model": "rdx-zai/glm-4.5"}}
    with pytest.raises(guard.GuardRejection) as e:
        mundo.al_guard(distinto)
    assert e.value.status == 403
