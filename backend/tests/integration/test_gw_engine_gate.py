"""El camino byok de `/gw` también rechaza en admisión (nodo C1), y el passthrough NO.

`/gw` byok va **al mismo motor** que el chat: comparte su cola y puede quedarse esperando una
generación local de minutos reteniendo recursos del worker. Así que se gatea con el mismo
semáforo por proceso. El passthrough de suscripción **no** se gatea: su upstream es cloud,
escala solo y no es el lento — gatearlo sería degradar Claude Code por un problema que no es
suyo. Esa asimetría es una postura, no un olvido, y por eso tiene test propio.

Lo que se fija:

* saturado ⇒ **503 con la forma de error de Anthropic** (las coding tools parsean
  `error.message`; un shape distinto lo muestran como "respuesta inesperada del proxy") más el
  header machine-readable `X-Basa-Rejected: saturated`, que es lo que distingue nuestro rechazo
  de un 503 de Caddy o del propio motor;
* el rechazo deja **una fila durable** con `rejected_saturated` y evento de vitrina;
* **el stream retiene el turno hasta que termina de drenar**. Es el invariante caro: si se
  liberara al devolver el `StreamingResponse`, el tope acotaría "pedidos hasta el primer byte"
  en vez de generaciones concurrentes reales, o sea que no acotaría nada;
* los dos timeouts nuevos están cableados donde tienen que estar.

Los tests del stream llaman a `_byok_proxy` **directamente** y no por HTTP: el transporte ASGI
de httpx bufferea la respuesta entera antes de devolverla, así que por HTTP es imposible tener
un stream abierto y sin drenar, que es exactamente el estado que hay que probar.
"""
import asyncio
import json
import sys
import time
from pathlib import Path

import pytest
from starlette.requests import Request

_TESTS = Path(__file__).resolve().parent.parent
for _dir in (_TESTS, _TESTS / "integration"):
    if str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))

from migration_harness import require_postgres  # noqa: E402
from seat_gate_harness import build_app_client  # noqa: E402

require_postgres()

DB = "basa_test_gw_engine_gate"
GW = "/api/v1/gw/v1/messages"
CLAVE = "sk-basa-carga-c1"
MODELO = "claude-3-5-sonnet-20241022"
CUERPO = {"model": MODELO, "messages": [{"role": "user", "content": "resumime esto"}]}
SATURADO = "rejected_saturated"
QUEUE_TIMEOUT = 0.25


# ── Dobles del motor ──────────────────────────────────────────────────────────────


class _Respuesta:
    status_code = 200
    headers = {"content-type": "application/json"}
    content = json.dumps({"content": [{"type": "text", "text": "ok"}],
                          "usage": {"input_tokens": 3, "output_tokens": 2}}).encode()

    def json(self):
        return json.loads(self.content)


class _RespuestaStream:
    """Upstream SSE que no termina hasta que el test lo suelta."""

    status_code = 200
    headers = {"content-type": "text/event-stream"}

    def __init__(self, soltar):
        self._soltar = soltar
        self.cerrado = False

    async def aiter_raw(self):
        yield b"data: {}\n\n"
        await self._soltar.wait()
        yield b"data: [DONE]\n\n"

    async def aread(self):
        return b""

    async def aclose(self):
        self.cerrado = True


class _MotorLento:
    """Doble del módulo `httpx` que ve el gateway: registra llamadas y se deja frenar."""

    def __init__(self):
        self.primera = asyncio.Event()
        self.soltar = asyncio.Event()
        self.llamadas = []
        self.kwargs_cliente = []
        self.streams = []

    def _nuevo_cliente(self, *_args, **kwargs):
        motor = self
        motor.kwargs_cliente.append(kwargs)

        class _Cliente:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_exc):
                return False

            async def post(self, url, **_kwargs):
                motor.llamadas.append(url)
                motor.primera.set()
                await motor.soltar.wait()
                return _Respuesta()

            def build_request(self, _metodo, url, **_kwargs):
                return {"url": url}

            async def send(self, req, stream=False):
                motor.llamadas.append(req["url"])
                motor.primera.set()
                respuesta = _RespuestaStream(motor.soltar)
                motor.streams.append(respuesta)
                return respuesta

            async def aclose(self):
                pass

        return _Cliente()

    def modulo(self):
        import httpx as _httpx_real
        import types
        return types.SimpleNamespace(AsyncClient=self._nuevo_cliente,
                                     Timeout=_httpx_real.Timeout)


# ── Fixtures ──────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def harness():
    client, factory, cleanup = build_app_client(DB)
    yield client, factory
    cleanup()


@pytest.fixture(autouse=True)
def sesion_del_gateway(harness, monkeypatch):
    """`gateway` abre sus PROPIAS sesiones (no la del override de `get_db`): sin esto los
    tests escribirían en la base del compose."""
    _, factory = harness
    from src.api import gateway
    monkeypatch.setattr(gateway, "SessionLocal", factory)
    return factory


@pytest.fixture
def motor(monkeypatch):
    from src.api import gateway
    lento = _MotorLento()
    monkeypatch.setattr(gateway, "httpx", lento.modulo())
    return lento


@pytest.fixture
def gate_de_uno(monkeypatch):
    from src.services import engine_gate
    monkeypatch.setattr(engine_gate, "ENGINE_MAX_CONCURRENCY", 1)
    monkeypatch.setattr(engine_gate, "ENGINE_QUEUE_TIMEOUT_SECONDS", QUEUE_TIMEOUT)
    engine_gate._semaforo_actual = None
    engine_gate._loop_del_semaforo = None
    yield engine_gate
    engine_gate._semaforo_actual = None
    engine_gate._loop_del_semaforo = None


@pytest.fixture
def eventos_de_vitrina(monkeypatch):
    from src.api import gateway
    capturados = []
    monkeypatch.setattr(gateway, "_publish_monitor",
                        lambda ident, tool, model, estado, *a, **k: capturados.append(
                            {"status": estado, "model": model}))
    return capturados


# ── Helpers ───────────────────────────────────────────────────────────────────────


def _peticion(stream=False):
    """`Request` mínimo con la forma que consumen `_byok_headers` / `_with_query` / la
    detección de herramienta."""
    return Request({
        "type": "http", "http_version": "1.1", "method": "POST",
        "path": "/gw/v1/messages", "raw_path": b"/gw/v1/messages", "query_string": b"",
        "root_path": "", "scheme": "http", "server": ("test", 80), "client": ("test", 1),
        "headers": [(b"user-agent", b"claude-cli/1.0"), (b"x-api-key", CLAVE.encode())],
    })


async def _byok(stream=False):
    """`start` es `time.time()` —el mismo reloj que usa el plano para calcular la latencia—,
    no el del event loop: mezclarlos daría una latencia absurda en la fila."""
    from src.api import gateway
    return await gateway._byok_proxy(
        _peticion(), json.dumps({**CUERPO, "stream": stream}).encode(), CLAVE, stream,
        model=MODELO, start=time.time())


def filas(factory, estado):
    from src.models.audit import AuditLog
    db = factory()
    try:
        return [{"compliance_status": f.compliance_status, "model": f.model,
                 "prompt_tokens": f.prompt_tokens, "completion_tokens": f.completion_tokens,
                 "blocked_by_layer": f.blocked_by_layer, "applied_layers": f.applied_layers}
                for f in db.query(AuditLog).filter(AuditLog.compliance_status == estado).all()]
    finally:
        db.close()


def borrar_filas(factory):
    from src.models.audit import AuditLog
    db = factory()
    try:
        db.query(AuditLog).delete()
        db.commit()
    finally:
        db.close()


# ── byok saturado: 503 con shape Anthropic + header + fila ────────────────────────


@pytest.mark.asyncio
async def test_byok_saturado_responde_503_con_shape_anthropic_y_header(
        harness, motor, gate_de_uno, eventos_de_vitrina):
    _, factory = harness
    borrar_filas(factory)

    primera = asyncio.create_task(_byok())
    await asyncio.wait_for(motor.primera.wait(), timeout=10)

    rechazo = await _byok()

    assert rechazo.status_code == 503
    cuerpo = json.loads(bytes(rechazo.body))
    # Shape de Anthropic: las coding tools parsean `error.message`. Cambiarlo por un JSON
    # nuestro convierte un rechazo legible en "respuesta inesperada del proxy".
    assert cuerpo["type"] == "error"
    assert cuerpo["error"]["type"] == "invalid_request_error"
    assert "capacidad" in cuerpo["error"]["message"].lower()
    assert "no se encoló" in cuerpo["error"]["message"]
    # El body mantiene el shape ajeno, así que el código machine-readable va en la cabecera.
    assert rechazo.headers.get("X-Basa-Rejected") == "saturated"
    assert rechazo.headers.get("Retry-After") == "5"

    rechazos = filas(factory, SATURADO)
    assert len(rechazos) == 1, f"una fila durable por rechazo, quedaron {len(rechazos)}"
    assert rechazos[0]["model"] == MODELO
    assert rechazos[0]["prompt_tokens"] == 0 and rechazos[0]["completion_tokens"] == 0
    # En byok la política corre en el MOTOR: este plano no tiene capas propias que atribuir, y
    # fabricar una sería inventar evidencia de gobernanza.
    assert rechazos[0]["blocked_by_layer"] is None
    assert rechazos[0]["applied_layers"] is None
    assert [e["status"] for e in eventos_de_vitrina] == [SATURADO]

    assert len(motor.llamadas) == 1, "el pedido rechazado no puede haber llegado al motor"

    motor.soltar.set()
    assert (await asyncio.wait_for(primera, timeout=10)).status_code == 200


@pytest.mark.asyncio
async def test_el_turno_del_byok_no_stream_se_devuelve_al_responder(harness, motor, gate_de_uno):
    """Un turno filtrado bajaría el tope de forma permanente hasta reiniciar el worker."""
    motor.soltar.set()
    for _ in range(3):
        assert (await _byok()).status_code == 200
    assert len(motor.llamadas) == 3


# ── El invariante caro: el stream retiene el turno mientras drena ─────────────────


@pytest.mark.asyncio
async def test_un_stream_abierto_sin_drenar_retiene_el_turno_y_al_cerrarse_lo_libera(
        harness, motor, gate_de_uno):
    """El pedido en stream ocupa un turno hasta que TERMINA de generar, no hasta el primer byte.

    Es la diferencia entre acotar generaciones concurrentes (lo que hay que hacer) y acotar
    "pedidos que ya recibieron cabeceras" (lo que no sirve para nada: el motor sigue trabajando
    para todos ellos a la vez).
    """
    respuesta = await _byok(stream=True)
    assert respuesta.status_code == 200

    # Se consume el PRIMER chunk y nada más: el stream queda abierto, como un cliente que está
    # recibiendo tokens.
    iterador = respuesta.body_iterator
    assert await iterador.__anext__() == b"data: {}\n\n"

    rechazo = await _byok()
    assert rechazo.status_code == 503, (
        "con un stream abierto el turno tiene que seguir tomado; si no, el tope no acota nada")
    assert rechazo.headers.get("X-Basa-Rejected") == "saturated"

    # El stream termina y devuelve el turno.
    motor.soltar.set()
    async for _ in iterador:
        pass

    assert motor.streams[0].cerrado, "el upstream tiene que cerrarse al terminar el stream"
    siguiente = await _byok()
    assert siguiente.status_code == 200, (
        "cerrado el stream, el turno tiene que estar de vuelta en el semáforo")


@pytest.mark.asyncio
async def test_un_stream_abandonado_por_el_cliente_tambien_devuelve_el_turno(
        harness, motor, gate_de_uno):
    """Un cliente que corta a mitad (Ctrl-C en la coding tool) cierra el generador: el `finally`
    corre igual y el turno vuelve. Sin esto, cada cancelación se comería un turno para siempre."""
    respuesta = await _byok(stream=True)
    await respuesta.body_iterator.__anext__()

    assert (await _byok()).status_code == 503
    await respuesta.body_iterator.aclose()

    motor.soltar.set()  # el siguiente pedido no tiene por qué esperar a nadie
    assert (await _byok()).status_code == 200


# ── El passthrough de suscripción NO se gatea (postura deliberada) ────────────────


@pytest.mark.asyncio
async def test_el_passthrough_de_suscripcion_pasa_aunque_el_semaforo_este_lleno(
        harness, motor, gate_de_uno, eventos_de_vitrina, monkeypatch):
    """Con el tope AGOTADO, un pedido de suscripción se sirve igual.

    Su upstream es `api.anthropic.com`: escala solo, no comparte cola con el modelo local y no
    es lo que colgó la sede. Gatearlo sería degradar Claude Code por un problema ajeno.
    """
    import httpx

    from src.api import gateway
    from src.main import app

    motor.soltar.set()  # el upstream cloud contesta al toque; el lento es el motor local
    turno = await gate_de_uno.adquirir_turno().adquirir()  # cap=1 ⇒ semáforo AGOTADO
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                     base_url="http://test") as ac:
            respuesta = await ac.post(GW, json=CUERPO,
                                      headers={"Authorization": "Bearer oauth-de-suscripcion"})
    finally:
        turno.liberar()

    assert respuesta.status_code == 200, respuesta.text
    assert motor.llamadas and motor.llamadas[0].startswith(gateway._ANTHROPIC_UPSTREAM), (
        "el pedido tenía que ir al upstream cloud, no al motor")
    assert SATURADO not in [e["status"] for e in eventos_de_vitrina]


# ── Wiring de los dos timeouts nuevos ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_el_byok_no_stream_usa_el_timeout_compartido_del_motor(harness, motor):
    """Antes: `120.0` hardcodeado en este plano y otro parser en `chat.py`. Ahora, un solo
    `BASA_ENGINE_TIMEOUT_SECONDS` acotado para los dos caminos que van al motor."""
    from src.services import engine_gate
    motor.soltar.set()

    assert (await _byok()).status_code == 200

    # Igualdad con la constante COMPARTIDA: si alguien reinstala un literal (`120.0`) o un
    # parser propio, este assert cae — que es justo lo que hay que impedir.
    assert motor.kwargs_cliente[0]["timeout"] == engine_gate.ENGINE_TIMEOUT_SECONDS


@pytest.mark.asyncio
async def test_el_stream_byok_usa_el_read_timeout_propio_y_no_el_del_passthrough(harness, motor):
    """El read entre-chunks del byok es el suyo (150 s de default), no los 60 s heredados del
    passthrough: aquellos asumen los `ping` SSE periódicos de Anthropic, y el motor local no
    manda pings — con 60 s una generación lenta se cortaba sola a mitad de respuesta."""
    from src.services import engine_gate
    motor.soltar.set()

    respuesta = await _byok(stream=True)
    async for _ in respuesta.body_iterator:
        pass

    timeout = motor.kwargs_cliente[0]["timeout"]
    assert timeout.read == engine_gate.GW_BYOK_READ_TIMEOUT_SECONDS
    assert timeout.read > 60.0, "el default tiene que superar el techo viejo del passthrough"
    assert timeout.connect == 10.0, "el connect acotado no se toca"
