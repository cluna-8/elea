"""057 R40 — una regla mueve `claude-sonnet-4-6` de Azure a Kimi K3 (OpenRouter) sin tocar el cliente.

Catálogo real (API) con dos destinos dados de alta: un despliegue de Azure OpenAI y `moonshotai/kimi-k3` por OpenRouter
(el id real de la lista pública de OpenRouter), pasarela real con el plugin real y el guard real del motor, upstream
falso (sin red, sin Docker, sin Postgres). El cliente (Claude Desktop) manda SIEMPRE el mismo pedido: lo único que
cambia entre las dos mitades del test es el destino de la regla, que es lo que edita el administrador en el panel.

Fija: (a) el pedido sale por la familia y con la credencial y la base de CADA destino, y el de OpenRouter lleva cero
retención y la lista de proveedores permitidos; (b) el cliente ve el mismo id, la misma etiqueta y el mismo `model` en la
respuesta antes y después (ni el nombre ni el modelo real del destino se filtran); (c) la auditoría dice el destino real
de cada pedido; (d) el costo es el del destino elegido.
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))
gateway = pytest.importorskip("src.api.gateway", reason="requiere el venv del backend")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from src.api import gateway_plugins as gp  # noqa: E402

from sentinel.catalog import models as cm  # noqa: E402
from sentinel.catalog.api import admin as catalog_admin  # noqa: E402
from sentinel.engine import redirect_guard as guard  # noqa: E402
from sentinel.redirect import authz, credentials  # noqa: E402
from sentinel.redirect import models as rm  # noqa: E402
from sentinel.redirect.plugin import RedirectPlugin  # noqa: E402
from sentinel.redirect.store import RedirectStore, load_from_session  # noqa: E402
from sentinel.tests import redirect_fixtures as fx  # noqa: E402
from sentinel.tests.catalog_fixtures import T1, create_entry, make_api  # noqa: E402
from sentinel.tests.integration.test_redirect_gateway_e2e import Engine  # noqa: E402

VK = "sk-sentinel-sonnet-0001"
PUBLICO = "claude-sonnet-4-6"
INTERNAL_KEY = "k" * 48
KIMI_K3 = "moonshotai/kimi-k3"                      # id real en la lista pública de OpenRouter (2026-10-07)
OPENROUTER = "https://openrouter.ai/api/v1"
AZURE_BASE = "https://recurso.openai.azure.com"
SECRETO_AZURE, SECRETO_OR = "valor-inventado-azure", "valor-inventado-openrouter"
NOMBRE_KIMI = "Kimi K3 por OpenRouter"
PRECIO_AZURE, PRECIO_KIMI = (1.25, 10.0), (0.62, 15.0)         # USD por millón (entrada, salida)


def armar_mundo(monkeypatch, publicar=None, quien=None):
    """Catálogo real + pasarela real + plugin real + motor falso, con los dos destinos dados de alta. `publicar(s, azure,
    kimi)` carga los ids publicados y las reglas (por defecto: `claude-sonnet-4-6` → Azure) y devuelve el id de la regla que
    mueve `mover_regla_a`. `quien`: dict mutable `{"group": ...}` con el grupo de quien pide (la atribución de la llave)."""
    api = make_api(monkeypatch)
    monkeypatch.setattr(catalog_admin, "DEPLOYMENT_PROBE", lambda e, cred: {"status": "ok"})
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
    quien = quien if quien is not None else {}
    monkeypatch.setattr(gateway, "_resolve_attribution", lambda _k: fx.ident(group_id=quien.get("group")))
    from sentinel.access import bridge
    monkeypatch.setattr(bridge, "RESOLVER", lambda tenant, **kw: None)
    monkeypatch.setattr(bridge, "RISK", lambda ident: (None, None))

    azure = create_entry(api, "tenant_admin", T1, name="GPT en Azure", provider="azure", real_model="gpt-5.1-chat",
                         api_base=AZURE_BASE, protocol_family="openai_chat", price_input=PRECIO_AZURE[0] / 1e6,
                         price_output=PRECIO_AZURE[1] / 1e6,
                         credential={"new": {"name": "c-azure", "value": {"api_key": SECRETO_AZURE,
                                                                          "api_version": "2025-04-01-preview"}}})
    kimi = create_entry(api, "tenant_admin", T1, name=NOMBRE_KIMI, provider="openrouter", real_model=KIMI_K3,
                        api_base=OPENROUTER, protocol_family="openai_chat", context_window=1048576,
                        max_output=943718, features={"images": True, "tools": True},
                        price_input=PRECIO_KIMI[0] / 1e6, price_output=PRECIO_KIMI[1] / 1e6,
                        provider_options={"providers_allowlist": ["fireworks"]},
                        credential={"new": {"name": "c-or", "value": SECRETO_OR}})
    with api.Session() as s:
        fx.seed_regions(s, [fx.ALLOW_EU_REGION])
        for ficha in s.query(cm.ComplianceSheet):               # FR-028: sin jurisdicción de inferencia no se sirve
            ficha.inference_jurisdiction = ficha.entity_jurisdiction = ficha.control_jurisdiction = "US"
        s.add_all([rm.RedirectPolicy(tenant_id=T1, scope_type="tenant", scope_value="*", state="on"),
                   rm.RedirectPosture(tenant_id=T1, scope_type="tenant", scope_value="*", mode="off",
                                      reason="postura de prueba", created_by_role="compliance_officer")])
        s.flush()
        regla_id = (publicar or _publicar_sonnet)(s, azure, kimi)
        s.commit()

    def mover_regla_a(entrada):
        """Lo que hace el administrador en el panel: cambiar el destino de la regla del tier."""
        with api.Session() as s:
            s.get(rm.RedirectRule, regla_id).targets = [entrada["id"]]
            s.commit()

    db = api.Session()
    store = RedirectStore(loader=lambda t: load_from_session(db, t, always=True), ttl=0,
                          key_models=lambda k: None, redis_factory=lambda: None,
                          decrypt=lambda blob: json.loads(blob[len("cifrado:"):][::-1]) if blob else {})
    gp.register_gateway_plugin(RedirectPlugin(store=store, ping_after=0.05))
    app = FastAPI()
    app.include_router(gateway.router)
    cliente = TestClient(app)
    cabeceras = {"Authorization": f"Bearer {VK}", "anthropic-version": "2023-06-01"}

    def pedir():
        return cliente.post("/gw/v1/messages", headers=cabeceras, json={
            "model": PUBLICO, "max_tokens": 64, "messages": [{"role": "user", "content": "hola"}]})

    def modelos():
        return cliente.get("/gw/v1/models", headers=cabeceras)

    def al_guard(enviado):
        data = {**enviado["body"], "proxy_server_request": {"headers": enviado["headers"]}, "metadata": {}}
        return guard.apply_redirect(data, environ={})

    return type("Mundo", (), dict(azure=azure, kimi=kimi, mover_regla_a=mover_regla_a, pedir=pedir, modelos=modelos,
                                  al_guard=al_guard, audits=audits, api=api, cliente=cliente, cabeceras=cabeceras,
                                  quien=quien))


def _publicar_sonnet(s, azure, kimi):
    pub = rm.RedirectPublishedModel(tenant_id=T1, face="claude", public_id=PUBLICO, family_tier="sonnet",
                                    is_family_default=True, scope_type="tenant", scope_value="*")   # label_mode: el default
    s.add(pub)
    s.flush()
    regla = rm.RedirectRule(tenant_id=T1, published_model_id=pub.id, scope_type="tenant", scope_value="*",
                            targets=[azure["id"]])
    s.add(regla)
    s.flush()
    return regla.id


@pytest.fixture
def mundo(monkeypatch):
    yield armar_mundo(monkeypatch)
    gp.clear_gateway_plugins()


def test_el_alta_de_kimi_k3_por_openrouter_nace_agregador_sin_bloqueo_y_sin_filtrar_la_credencial(mundo):
    k = mundo.kimi
    assert k["real_model"] == KIMI_K3 and k["is_aggregator"] is True and k["blocked_by_default"] is False
    assert k["status"] == "active" and k["has_credential"] is True and SECRETO_OR not in json.dumps(k)


def test_una_regla_mueve_sonnet_de_azure_a_kimi_sin_tocar_el_cliente(mundo):
    # ── antes: Azure ──
    antes = mundo.pedir()
    assert antes.status_code == 200, antes.text
    enviado_azure = Engine.sent[-1]
    assert enviado_azure["body"]["model"] == f"{credentials.PROVIDER_FAMILY['azure']}/gpt-5.1-chat"
    g_azure = mundo.al_guard(enviado_azure)
    assert g_azure["api_key"] == SECRETO_AZURE and g_azure["api_base"] == AZURE_BASE
    assert g_azure["input_cost_per_token"] == pytest.approx(PRECIO_AZURE[0] / 1e6)
    modelos_antes = mundo.modelos().json()

    # ── el administrador cambia el destino de la regla; el cliente no cambia nada ──
    mundo.mover_regla_a(mundo.kimi)
    despues = mundo.pedir()
    assert despues.status_code == 200, despues.text
    enviado_kimi = Engine.sent[-1]
    assert enviado_kimi["body"]["model"] == f"{credentials.PROVIDER_FAMILY['openrouter']}/{KIMI_K3}"
    g_kimi = mundo.al_guard(enviado_kimi)
    assert g_kimi["api_key"] == SECRETO_OR and g_kimi["api_base"] == OPENROUTER      # credencial y base del destino nuevo
    assert SECRETO_AZURE not in json.dumps(g_kimi, default=str)                       # nada del destino anterior
    assert g_kimi["input_cost_per_token"] == pytest.approx(PRECIO_KIMI[0] / 1e6)      # el costo es el del elegido
    assert g_kimi["output_cost_per_token"] == pytest.approx(PRECIO_KIMI[1] / 1e6)
    prefs = g_kimi["extra_body"]["provider"]                                          # FR-032: cero retención
    assert prefs == {"only": ["fireworks"], "data_collection": "deny", "zdr": True}

    # ── lo que ve el cliente es idéntico ──
    assert antes.json()["model"] == despues.json()["model"] == PUBLICO
    modelos_despues = mundo.modelos().json()
    solo_ventana = lambda lista: [{k: v for k, v in m.items() if k not in ("description", "max_input_tokens", "supports_1m")}
                                  for m in lista["data"]]
    # el id y la etiqueta no cambian; la ventana de contexto SÍ es la del destino (de ella depende cuándo compacta el
    # cliente) y es el único dato que se mueve
    assert solo_ventana(modelos_despues) == solo_ventana(modelos_antes)
    assert modelos_despues["data"][0]["max_input_tokens"] == 1048576 and modelos_antes["data"][0].get("max_input_tokens") == 128000
    visible = antes.text + despues.text + json.dumps(modelos_antes)
    for filtrado in (KIMI_K3, "kimi", "openrouter", NOMBRE_KIMI, "gpt-5.1-chat", "GPT en Azure", "azure"):
        assert filtrado.lower() not in visible.lower(), f"el cliente vio {filtrado!r}"

    # ── la auditoría sí dice el destino real de cada pedido ──
    d_azure = g_azure["metadata"]["_internal_routing_decision"]["extensions"]["redirect"]
    d_kimi = g_kimi["metadata"]["_internal_routing_decision"]["extensions"]["redirect"]
    assert d_azure["destination_id"] == mundo.azure["id"] and d_kimi["destination_id"] == mundo.kimi["id"]
    assert d_azure["public_id"] == d_kimi["public_id"] == PUBLICO


def test_el_selector_muestra_el_id_pedido_con_la_etiqueta_por_defecto(mundo):
    datos = mundo.modelos().json()["data"]
    assert [m["id"] for m in datos] == [PUBLICO] and datos[0]["display_name"] == PUBLICO
