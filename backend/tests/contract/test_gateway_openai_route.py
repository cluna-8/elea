"""Contract test de la puerta del formato de chat estándar (spec 045 US3, FR-008/009/011).

Fija tres cosas, en orden de importancia:

1. **La ruta no lleva política propia.** Es un preámbulo delgado sobre el proxy byok que ya
   existía: sanea el modelo, exige virtual key, y delega. La política la aplica el motor,
   igual que en la ruta de mensajes. Si alguien empieza a decidir sobre el contenido acá,
   estos tests no lo ven — pero el test de delegación sí ve que dejó de delegar.
2. **La forma del error es la que el cliente sabe renderizar** (FR-009). Sin esto una
   herramienta de terceros muestra "error de red" en vez del motivo real del bloqueo, que es
   justo lo que el producto tiene que lucir.
3. **Sin virtual key resoluble, 401 honesto** (FR-011): el passthrough de suscripción no
   habla este formato y no se intenta.

Y una cuarta, defensiva: los defaults de `_byok_proxy` dejan la ruta de mensajes EXACTAMENTE
como estaba. El parámetro nuevo no puede haber movido la ruta vieja.
"""
import json

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from src.api import gateway, gateway_openai

RUTA = "/gw/v1/chat/completions"
KEY = "sk-sentinel-demo-chatui-2026"


def _body(texto="hola", **extra):
    b = {"model": "nix-us-fast", "messages": [{"role": "user", "content": texto}]}
    b.update(extra)
    return b


@pytest.fixture
def espia(monkeypatch):
    """Reemplaza el proxy byok por un espía: lo que se fija es QUÉ le llega."""
    visto = {}

    async def _fake_proxy(request, raw, sentinel_key, is_stream, **kw):
        visto.update(raw=raw, sentinel_key=sentinel_key, is_stream=is_stream, **kw)
        return {"ok": True}

    monkeypatch.setattr(gateway, "_byok_proxy", _fake_proxy)
    monkeypatch.setattr(gateway, "_audit_precheck_ok", lambda *a, **k: True)
    return visto


@pytest.fixture
def client(espia):
    app = FastAPI()
    app.include_router(gateway_openai.router)
    return TestClient(app), espia


# ── 1. delega en el proxy que ya existe, con la ruta del motor correcta ──

def test_delega_en_el_proxy_byok_con_la_ruta_del_formato_estandar(client):
    c, visto = client
    r = c.post(RUTA, json=_body(), headers={"Authorization": f"Bearer {KEY}"})
    assert r.status_code == 200
    assert visto["ruta_motor"] == "/v1/chat/completions"
    assert visto["sentinel_key"] == KEY
    assert visto["error_fn"] is gateway_openai._openai_error


def test_el_cuerpo_viaja_verbatim(client):
    """No se reescribe nada salvo el caso «auto». Si esto rompe, alguien metió política acá."""
    c, visto = client
    cuerpo = _body("texto con un correo ana@ejemplo.es")
    c.post(RUTA, json=cuerpo, headers={"Authorization": f"Bearer {KEY}"})
    assert json.loads(visto["raw"]) == cuerpo


def test_stream_se_propaga(client):
    c, visto = client
    c.post(RUTA, json=_body(stream=True), headers={"Authorization": f"Bearer {KEY}"})
    assert visto["is_stream"] is True


# ── 2. forma del error (FR-009) ──

@pytest.mark.parametrize("cuerpo,desc", [
    ("no soy json", "cuerpo no-JSON"),
    ('"soy un string"', "JSON que no es objeto"),
    ('{"messages": "no soy lista"}', "messages con tipo equivocado"),
])
def test_cuerpo_malformado_es_400_con_forma_de_cliente(client, cuerpo, desc):
    c, _ = client
    r = c.post(RUTA, data=cuerpo, headers={"content-type": "application/json",
                                           "Authorization": f"Bearer {KEY}"})
    assert r.status_code == 400, desc
    err = r.json()["error"]
    assert isinstance(err.get("message"), str) and err.get("type")
    # La forma del OTRO formato no puede colarse acá: el cliente no la sabe renderizar.
    assert "type" not in r.json() or r.json().get("type") != "error"


def test_el_error_no_filtra_el_identificador_interno_de_capa(client):
    c, _ = client
    r = c.post(RUTA, data="no soy json", headers={"content-type": "application/json",
                                                  "Authorization": f"Bearer {KEY}"})
    texto = json.dumps(r.json())
    for interno in ("blocked_by_layer", "secret_detection", "pii_masking", "ai_act_evaluation"):
        assert interno not in texto


# ── 3. sin virtual key resoluble → 401 honesto (FR-011) ──

def test_sin_credencial_es_401_y_no_llega_al_motor(client):
    c, visto = client
    r = c.post(RUTA, json=_body())
    assert r.status_code == 401
    assert r.json()["error"]["type"] == "authentication_error"
    assert not visto, "no puede haber llegado nada al proxy"


def test_credencial_de_suscripcion_no_se_intenta_traducir(client):
    """Un OAuth de suscripción NO habla este formato: 401, no un passthrough inventado."""
    c, visto = client
    r = c.post(RUTA, json=_body(), headers={"Authorization": "Bearer sk-ant-oat01-loquesea"})
    assert r.status_code == 401
    assert not visto


# ── 4. la ruta vieja no se movió ──

def test_los_defaults_dejan_la_ruta_de_mensajes_como_estaba():
    import inspect
    p = inspect.signature(gateway._byok_proxy).parameters
    assert p["ruta_motor"].default == "/v1/messages"
    assert p["error_fn"].default is None


# ── 5. cableado de los hooks de plugins de pasarela (costura S2, spec 068 T016/T017) ──

@pytest.fixture
def sin_plugins():
    from src.api import gateway_plugins as gp
    gp.clear_gateway_plugins()
    yield gp
    gp.clear_gateway_plugins()


def test_sin_plugins_el_proxy_no_recibe_contexto(client, sin_plugins):
    """Sin plugins, la llamada al proxy es exactamente la de antes: ni `ctx` ni identidad."""
    c, visto = client
    c.post(RUTA, json=_body(), headers={"Authorization": f"Bearer {KEY}"})
    assert "ctx" not in visto


def test_con_plugin_el_proxy_recibe_el_contexto_con_la_identidad(client, sin_plugins, monkeypatch):
    gp = sin_plugins
    monkeypatch.setattr(gateway, "_resolve_attribution", lambda k: {"tenant_id": "t1", "k": k})

    class P:
        def pre_request(self, ctx):
            ctx.state["visto"] = (ctx.route, ctx.mode, ctx.model)

    gp.register_gateway_plugin(P())
    c, visto = client
    c.post(RUTA, json=_body(), headers={"Authorization": f"Bearer {KEY}"})
    ctx = visto["ctx"]
    assert ctx.state["visto"] == ("/v1/chat/completions", "byok", "nix-us-fast")
    assert ctx.ident == {"tenant_id": "t1", "k": KEY}


def test_con_plugin_el_corte_de_pre_request_se_registra_y_no_llega_al_proxy(client, sin_plugins,
                                                                            monkeypatch):
    gp = sin_plugins
    filas = []
    monkeypatch.setattr(gateway, "_resolve_attribution", lambda k: {"tenant_id": "t1"})
    monkeypatch.setattr(gateway, "_audit", lambda *a, **k: filas.append((a, k)) or True)

    class P:
        def pre_request(self, ctx):
            ctx.routing_decision = {"extensions": {"x": {"y": 1}}}
            return JSONResponse(status_code=404, content={"error": {"code": "model_not_found"}})

    gp.register_gateway_plugin(P())
    c, visto = client
    r = c.post(RUTA, json=_body(), headers={"Authorization": f"Bearer {KEY}"})
    assert r.status_code == 404 and r.json()["error"]["code"] == "model_not_found"
    assert not visto
    (args, kw), = filas
    assert args[4] == gp.STATUS_PLUGIN_BLOCK
    assert kw["routing_decision"] == {"extensions": {"x": {"y": 1}}}
