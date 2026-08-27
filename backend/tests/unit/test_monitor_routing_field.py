"""Campo OPCIONAL ``routing`` del evento de vitrina + edge «auto» por /gw (spec 030, T008/T017).

Dos cosas distintas que comparten el mismo hecho —«auto» es un pseudo-modelo del plano
chat— y por eso viven juntas:

1. **La vitrina aprende un campo sin romper a los que no lo mandan.** El evento de
   ``basa:gw:events`` tiene tres productores (gateway, plano chat, logger del motor) y sólo
   uno emite ``routing``. Se verifica lo que hace que eso sea seguro: con el campo, el
   evento lo lleva **proyectado al subset del contrato** (sin ``requested``/``reason``, que
   son del Debugger y de la columna durable); sin el campo, el evento sale **idéntico** a
   como salía antes —la clave ausente, no en ``null``—; y ``GET /gw/events`` devuelve ambos
   intactos, porque no valida esquema.

2. **Por /gw, «auto» se reescribe al default del router y no se clasifica** (research R9).
   El motor no conoce ningún modelo «auto», así que sin esta reescritura el pedido se lleva
   un 400 suyo. Y si la config no se puede leer o no declara default, el body pasa
   **verbatim**: el error honesto del motor es mejor que un 4xx inventado acá o que elegir
   un destino que nadie configuró.

El servicio del router (``auto_router_service``, T003) se inyecta como módulo falso en
``sys.modules``: estos tests describen el CONTRATO del gateway con él —qué hace el gateway
cuando ``load_config`` responde, cuando revienta y cuando devuelve un default vacío— y no
deben depender de la implementación real ni de que ya exista.
"""
import json
import sys
import types

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import gateway, monitor

# Nombre absoluto del módulo del router TAL COMO lo resuelve el import perezoso relativo de
# gateway.py (``from ..services.auto_router_service import load_config``). Se deriva del
# paquete real en vez de hardcodearse: si el árbol cambia de nombre, el test sigue apuntando
# al mismo sitio que el código.
_ROUTER_MOD = gateway.__name__.rsplit(".", 2)[0] + ".services.auto_router_service"

ENGINE = "http://engine:4000"

# Objeto decisión COMPLETO (data-model §2). La vitrina sólo debe ver cuatro de sus claves.
DECISION = {
    "requested": "auto",
    "route": "Código y análisis",
    "score": 0.61,
    "model_selected": "gpt-4o",
    "degraded": False,
    "reason": None,
}
IDENT = {"tool_type": "chat-ui", "client_username": "ana", "tenant_slug": "camara"}


# ── ring falso: el gateway escribe por pipeline(), el monitor lee por lrange() ────────

class _FakePipe:
    def __init__(self, ring):
        self.ring = ring

    def lpush(self, key, payload):
        self.ring.insert(0, payload)

    def ltrim(self, *a):
        pass

    def expire(self, *a):
        pass

    def execute(self):
        pass


class _FakeRedis:
    def __init__(self):
        self.ring = []

    def pipeline(self):
        return _FakePipe(self.ring)

    def lrange(self, key, start, end):
        return self.ring[start:end + 1]


@pytest.fixture
def feed(monkeypatch):
    """Ring compartido por los dos extremos: el productor real (``_publish_monitor``) y el
    consumidor real (``GET /gw/events``). Nada de armar el JSON a mano — lo que se prueba es
    justamente que el campo sobreviva el viaje entre los dos."""
    fake = _FakeRedis()
    monkeypatch.setattr(gateway, "get_redis", lambda: fake)
    monkeypatch.setattr(monitor, "get_redis", lambda: fake)
    app = FastAPI()
    app.include_router(monitor.router, prefix="/api/v1")
    # La sesión del feed ya tiene sus propios tests (027); acá estorba.
    app.dependency_overrides[monitor._SESION[0].dependency] = lambda: None
    return fake, TestClient(app)


def _publicar(routing=None, **kw):
    args = dict(ident=IDENT, tool="chat-ui", model="gpt-4o", status="passed",
                masked_entities=[], masked_preview="hola")
    args.update(kw)
    if routing is not None:
        args["routing"] = routing
    gateway._publish_monitor(**args)


# ── 1) Proyección al subset del contrato ─────────────────────────────────────────────

def test_evento_con_routing_lleva_solo_el_subset_de_la_vitrina(feed):
    fake, _ = feed
    _publicar(routing=DECISION)
    event = json.loads(fake.ring[0])
    assert event["routing"] == {"route": "Código y análisis", "score": 0.61,
                                "model_selected": "gpt-4o", "degraded": False}
    # `requested` y `reason` NO son de la vitrina: van al Debugger y a la columna durable.
    assert "requested" not in event["routing"]
    assert "reason" not in event["routing"]


def test_routing_degradado_viaja_como_tal(feed):
    # FR-004: la degradación jamás es silenciosa — si el router no pudo decidir, la vitrina
    # tiene que poder decirlo (el chip amarillo de monitor.py cuelga de este booleano).
    fake, _ = feed
    _publicar(routing={"route": None, "score": 0.0, "model_selected": "camara-local",
                       "degraded": True, "reason": "embed_timeout"})
    event = json.loads(fake.ring[0])
    assert event["routing"]["degraded"] is True
    assert event["routing"]["route"] is None      # sin ruta ganadora ≠ sin dato de ruteo


def test_routing_basura_no_ensucia_el_evento(feed):
    # Un valor que no es dict, o un dict sin ninguna clave del contrato, no debe inventar
    # un campo vacío que el render lea como "hubo ruteo".
    fake, _ = feed
    _publicar(routing="gpt-4o")            # type: ignore[arg-type]
    _publicar(routing={"reason": "switch_off"})
    for raw in fake.ring:
        assert "routing" not in json.loads(raw)


# ── 2) Retrocompatibilidad: los otros dos productores no cambian ─────────────────────

def test_evento_sin_routing_sale_igual_que_antes(feed):
    fake, _ = feed
    _publicar()
    event = json.loads(fake.ring[0])
    # Clave AUSENTE, no `null`: presente = "hubo decisión de ruteo", ausente = "este plano
    # no rutea". Con `null` el consumidor no podría distinguirlas.
    assert "routing" not in event
    # Y el resto del contrato del evento intacto (§8).
    assert event["applied_layers"] is None and event["blocked_by_layer"] is None
    assert event["compliance_status"] == "passed" and event["tool"] == "chat-ui"


# ── 3) GET /gw/events reexpone el campo intacto (y la ausencia también) ──────────────

def test_gw_events_reexpone_routing_intacto_y_sin_routing_igual(feed):
    fake, client = feed
    _publicar()                        # productor sin ruteo (gateway/motor)
    _publicar(routing=DECISION)        # productor con ruteo (plano chat, request «auto»)

    r = client.get("/api/v1/gw/events")
    assert r.status_code == 200
    events = r.json()["events"]
    assert len(events) == 2

    con_ruteo, sin_ruteo = events[0], events[1]   # lpush → el más nuevo primero
    assert con_ruteo["routing"] == {"route": "Código y análisis", "score": 0.61,
                                    "model_selected": "gpt-4o", "degraded": False}
    assert "routing" not in sin_ruteo


# ── 4) Edge /gw: «auto» → default del router, sin clasificar (T017 / R9) ────────────

def _instalar_router(monkeypatch, load_config):
    mod = types.ModuleType(_ROUTER_MOD)
    mod.load_config = load_config
    monkeypatch.setitem(sys.modules, _ROUTER_MOD, mod)


def test_resolve_auto_model_reescribe_al_default(monkeypatch):
    _instalar_router(monkeypatch, lambda: {"enabled": True, "default_model": "camara-local"})
    body = {"model": "auto", "messages": [{"role": "user", "content": "hola"}]}
    out = json.loads(gateway._resolve_auto_model(body, b"{}"))
    assert out["model"] == "camara-local"
    assert out["messages"] == body["messages"]     # el resto del body, verbatim


def test_resolve_auto_model_no_toca_un_modelo_explicito(monkeypatch):
    llamadas = []

    def _load():
        llamadas.append(1)
        return {"default_model": "camara-local"}

    _instalar_router(monkeypatch, _load)
    raw = b'{"model":"claude-3-5-sonnet"}'
    assert gateway._resolve_auto_model({"model": "claude-3-5-sonnet"}, raw) is raw
    assert llamadas == []      # ni se lee la config: el 99,9% del tráfico no paga nada


def test_resolve_auto_model_config_rota_deja_pasar_verbatim(monkeypatch):
    def _explota():
        raise RuntimeError("auto_router.json corrupto")

    _instalar_router(monkeypatch, _explota)
    raw = b'{"model":"auto"}'
    # Verbatim: contesta el motor con SU error, en vez de que el gateway invente uno.
    assert gateway._resolve_auto_model({"model": "auto"}, raw) is raw


def test_resolve_auto_model_sin_default_deja_pasar_verbatim(monkeypatch):
    _instalar_router(monkeypatch, lambda: {"enabled": True, "default_model": "   "})
    raw = b'{"model":"auto"}'
    assert gateway._resolve_auto_model({"model": "auto"}, raw) is raw


def test_resolve_auto_model_servicio_ausente_deja_pasar_verbatim(monkeypatch):
    # El servicio del router puede no estar (despliegue viejo, módulo no instalado): el
    # gateway degrada al body verbatim, nunca a un 500.
    monkeypatch.setitem(sys.modules, _ROUTER_MOD, types.ModuleType(_ROUTER_MOD))
    raw = b'{"model":"auto"}'
    assert gateway._resolve_auto_model({"model": "auto"}, raw) is raw


# ── 5) …y el body reescrito es el que sale de verdad hacia el motor ─────────────────

class _Resp:
    status_code = 200
    headers = {"content-type": "application/json"}
    content = b'{"content":[{"type":"text","text":"ok"}]}'


class _FakeHttpx:
    """Captura la última llamada al upstream (URL + body) para afirmar qué se mandó."""
    last: dict = {}

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, headers=None, content=None):
        _FakeHttpx.last = {"url": url, "content": content}
        return _Resp()


@pytest.fixture
def gw(monkeypatch):
    _FakeHttpx.last = {}
    monkeypatch.setattr(gateway.httpx, "AsyncClient", _FakeHttpx)
    app = FastAPI()
    app.include_router(gateway.router)
    return TestClient(app)


def test_byok_manda_al_motor_el_modelo_default_no_auto(gw, monkeypatch):
    _instalar_router(monkeypatch, lambda: {"default_model": "camara-local"})
    r = gw.post("/gw/v1/messages",
                json={"model": "auto", "messages": [{"role": "user", "content": "hola"}]},
                headers={"x-api-key": "sk-basa-copilot123"})
    assert r.status_code == 200
    assert _FakeHttpx.last["url"].startswith(ENGINE)          # fue por byok
    enviado = json.loads(_FakeHttpx.last["content"])
    assert enviado["model"] == "camara-local"                 # el motor jamás ve «auto»
    assert enviado["messages"][0]["content"] == "hola"        # sin tocar el contenido


def test_byok_con_config_rota_manda_el_body_verbatim(gw, monkeypatch):
    def _explota():
        raise RuntimeError("sin config")

    _instalar_router(monkeypatch, _explota)
    original = {"model": "auto", "messages": [{"role": "user", "content": "hola"}]}
    gw.post("/gw/v1/messages", json=original, headers={"x-api-key": "sk-basa-copilot123"})
    assert json.loads(_FakeHttpx.last["content"]) == original
