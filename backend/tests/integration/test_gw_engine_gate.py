"""El camino byok de `/gw` también rechaza en admisión (nodo C1), y el passthrough NO.

`/gw` byok va **al mismo motor** que el chat: comparte su cola y puede quedarse esperando una
generación local de minutos reteniendo recursos del worker. Así que se gatea con el mismo
semáforo por proceso. El passthrough de suscripción **no** se gatea: su upstream es cloud,
escala solo y no es el lento — gatearlo sería degradar Claude Code por un problema que no es
suyo. Esa asimetría es una postura, no un olvido, y por eso tiene test propio.

Lo que se fija:

* saturado ⇒ **503 con la forma de error de Anthropic** (las coding tools parsean
  `error.message`; un shape distinto lo muestran como "respuesta inesperada del proxy") más el
  header machine-readable `X-Sentinel-Rejected: saturated`, que es lo que distingue nuestro rechazo
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

import anyio
import pytest
from starlette.requests import Request

_TESTS = Path(__file__).resolve().parent.parent
for _dir in (_TESTS, _TESTS / "integration"):
    if str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))

from migration_harness import require_postgres  # noqa: E402
from seat_gate_harness import build_app_client  # noqa: E402

require_postgres()

DB = "sentinel_test_gw_engine_gate"
GW = "/api/v1/gw/v1/messages"
CLAVE = "sk-sentinel-carga-c1"
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
        # Testigo de N1: se prende cuando el generador del gateway pide el PRIMER chunk. Hace
        # falta porque un generador asíncrono que NUNCA arrancó no ejecuta su `finally` (PEP
        # 525), así que "no arrancó" y "arrancó y se murió" fugan el turno igual pero por
        # motivos distintos, y un test que no los distingue no prueba nada.
        self.arranco = False

    async def aiter_raw(self):
        self.arranco = True
        yield b"data: {}\n\n"
        await self._soltar.wait()
        yield b"data: [DONE]\n\n"

    async def aread(self):
        return b""

    async def aclose(self):
        # El `sleep(0)` NO es relleno: es lo que hace de este doble un cierre HONESTO. El
        # `aclose()` real habla con la red y por lo tanto SUSPENDE, y una suspensión dentro de
        # un scope cancelado vuelve a recibir la cancelación (anyio la re-entrega en cada
        # checkpoint hasta que el scope sale). Un doble que cierra sin suspender jamás nunca
        # reproduciría la fuga de turno de H1, y el test pasaría con el bug puesto.
        await asyncio.sleep(0)
        self.cerrado = True


class _MotorLento:
    """Doble del módulo `httpx` que ve el gateway: registra llamadas y se deja frenar."""

    def __init__(self):
        self.primera = asyncio.Event()
        self.soltar = asyncio.Event()
        self.llamadas = []
        self.kwargs_cliente = []
        self.streams = []
        # Los clientes creados, para poder afirmar que el `AsyncClient` TAMBIÉN se cierra y no
        # sólo la respuesta: en la ventana N1 el `finally` de `_StreamConTurno` es el único que
        # lo cierra, y un cliente que se filtra se lleva la conexión con el motor.
        self.clientes = []

    def _nuevo_cliente(self, *_args, **kwargs):
        motor = self
        motor.kwargs_cliente.append(kwargs)

        class _Cliente:
            def __init__(self):
                self.cerrado = False

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
                await asyncio.sleep(0)  # cerrar un cliente httpx real suspende; ver arriba
                self.cerrado = True

        cliente = _Cliente()
        motor.clientes.append(cliente)
        return cliente

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


def _scope_asgi():
    """`scope` HTTP mínimo para ejecutar la respuesta como ASGI DE VERDAD.

    Los tests de cancelación no pueden simular el corte con `body_iterator.aclose()`: ese atajo
    entra por `GeneratorExit`, y lo que rompe en producción es la cancelación del task group de
    `StreamingResponse.__call__`. Son caminos distintos y sólo el segundo reproduce las fugas.
    """
    return {"type": "http", "http_version": "1.1", "method": "POST",
            "path": "/gw/v1/messages", "headers": [], "query_string": b"",
            "scheme": "http", "server": ("test", 80), "client": ("test", 1), "root_path": ""}


def _aplanar(exc):
    """Aplana `BaseExceptionGroup` recursivamente.

    Los task groups de anyio 4 envuelven SIEMPRE lo que levanta una tarea hija, aunque sea una
    sola excepción. Comparar el tipo de arriba sería atarle el test a esa decisión de anyio: lo
    que se afirma es que la excepción del cliente llegó, no cómo la empaquetó la librería.
    """
    if isinstance(exc, BaseExceptionGroup):
        for hijo in exc.exceptions:
            yield from _aplanar(hijo)
    else:
        yield exc


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
    assert rechazo.headers.get("X-Sentinel-Rejected") == "saturated"
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
async def test_la_fila_del_rechazo_registra_el_modelo_ruteado_y_no_el_auto_del_body(
        harness, motor, gate_de_uno, eventos_de_vitrina, monkeypatch):
    """H7 del gate de #135: la fila decía `model="auto"`, que no es ningún modelo.

    «auto» es un pseudo-modelo: el router lo reescribe al default configurado ANTES de que el
    pedido salga hacia el motor. Si la fila del rechazo guarda el literal del body, el día que
    la sede pregunte «¿qué modelo estábamos rebotando el martes?» —que es LA pregunta de un
    incidente de capacidad— la respuesta es «auto», o sea nada. El chat ya escribe el modelo
    ruteado (`routed_model`); los dos planos tienen que contar la misma historia.

    Va por el endpoint y no por `_byok_proxy` porque la resolución del router vive ahí arriba.
    """
    import httpx as _httpx  # el REAL: `gateway.httpx` está doblado por la fixture `motor`

    from src.main import app
    from src.services import auto_router_service

    _, factory = harness
    borrar_filas(factory)
    monkeypatch.setattr(auto_router_service, "load_config",
                        lambda: {"default_model": "ollama-qwen3-4b"})

    turno = await gate_de_uno.adquirir_turno().adquirir()  # cap=1 ⇒ semáforo AGOTADO
    try:
        async with _httpx.AsyncClient(transport=_httpx.ASGITransport(app=app),
                                      base_url="http://test") as ac:
            respuesta = await ac.post(GW, json={**CUERPO, "model": "auto"},
                                      headers={"x-api-key": CLAVE,
                                               "user-agent": "claude-cli/1.0"})
    finally:
        turno.liberar()

    assert respuesta.status_code == 503, respuesta.text
    assert respuesta.headers.get("X-Sentinel-Rejected") == "saturated"

    rechazos = filas(factory, SATURADO)
    assert len(rechazos) == 1, f"una fila durable por rechazo, quedaron {len(rechazos)}"
    assert rechazos[0]["model"] == "ollama-qwen3-4b", (
        "la fila tiene que decir a qué modelo IBA el pedido, no el pseudo-modelo del body")
    assert [e["model"] for e in eventos_de_vitrina] == ["ollama-qwen3-4b"], (
        "la vitrina y la fila cuentan la misma historia o no sirve ninguna de las dos")
    assert not motor.llamadas, "el pedido rechazado no puede haber llegado al motor"


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
    assert rechazo.headers.get("X-Sentinel-Rejected") == "saturated"

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
    corre igual y el turno vuelve. Sin esto, cada cancelación se comería un turno para siempre.

    Cubre el camino `GeneratorExit` —el cierre explícito del iterador—, que NO es el mismo que
    la cancelación real de starlette: aquél entra por `aclose()` del generador y éste por la
    cancelación del task group. Los dos tienen test propio a propósito (H1 del gate de #135).
    """
    respuesta = await _byok(stream=True)
    await respuesta.body_iterator.__anext__()

    assert (await _byok()).status_code == 503
    await respuesta.body_iterator.aclose()

    motor.soltar.set()  # el siguiente pedido no tiene por qué esperar a nadie
    assert (await _byok()).status_code == 200


@pytest.mark.asyncio
async def test_la_cancelacion_real_de_starlette_no_se_come_el_turno(harness, motor, gate_de_uno):
    """H1 del gate de #135, por el camino de VERDAD: el cliente desconecta y starlette cancela.

    Este es el escenario de producción y no lo cubría ningún test. `StreamingResponse.__call__`
    corre dos tareas en un task group —drenar el cuerpo y escuchar `http.disconnect`— y al
    llegar la desconexión CANCELA el grupo. La cancelación se re-entrega en cada punto de
    suspensión hasta que el scope sale, así que un `finally` que empieza con `await
    up.aclose()` se lleva el `CancelledError` ahí mismo y nunca alcanza el `liberar()` de
    abajo. El turno queda tomado por nadie **para siempre**: con 8 cancelaciones (Ctrl-C en una
    coding tool es lo más normal del mundo) el worker rechaza 503 con el motor vacío.

    Por eso se ejecuta la respuesta como ASGI de verdad —`await respuesta(scope, receive,
    send)`— en vez de simular el corte con `body_iterator.aclose()`: ese atajo entra por
    `GeneratorExit`, que es otro camino y no reproduce nada.
    """
    respuesta = await _byok(stream=True)
    assert respuesta.status_code == 200

    semaforo = gate_de_uno._semaforo()
    assert semaforo._value == 0, "cap=1: el stream abierto tiene que tener el turno tomado"

    primer_chunk = asyncio.Event()
    enviados = []

    async def send(mensaje):
        enviados.append(mensaje["type"])
        if mensaje["type"] == "http.response.body" and mensaje.get("body"):
            primer_chunk.set()  # el cliente ya recibió tokens... y ahora se va

    async def receive():
        await primer_chunk.wait()
        return {"type": "http.disconnect"}

    scope = {"type": "http", "http_version": "1.1", "method": "POST",
             "path": "/gw/v1/messages", "headers": [], "query_string": b"",
             "scheme": "http", "server": ("test", 80), "client": ("test", 1), "root_path": ""}

    # El upstream NUNCA se suelta: el generador queda suspendido esperando el chunk siguiente,
    # que es exactamente donde lo agarra la cancelación.
    await asyncio.wait_for(respuesta(scope, receive, send), timeout=10)
    await asyncio.sleep(0)  # que corra el `finally` del generador cancelado

    assert "http.response.body" in enviados, "el escenario no llegó a mandar el primer chunk"
    assert semaforo._value == 1, (
        "la cancelación de starlette se comió el turno: el tope quedó encogido de forma "
        "permanente hasta reiniciar el worker")

    motor.soltar.set()
    assert (await _byok()).status_code == 200, "y el turno tiene que servir de verdad"


@pytest.mark.asyncio
async def test_el_turno_vuelve_aunque_el_cierre_del_upstream_reviente(
        harness, motor, gate_de_uno):
    """La mitad DETERMINISTA de H1: si un `await` del `finally` levanta, el turno ya se soltó.

    Sin depender de cómo entregue la cancelación la versión de anyio/starlette de turno: lo que
    se fija es el ORDEN. `liberar()` es sync e infalible y va PRIMERO; los `aclose()` son I/O y
    pueden fallar (un socket ya muerto, un bump de httpx que cambie el comportamiento) sin que
    eso le cueste un turno al worker.

    Tres vueltas y no una: con cap=1 una sola fuga ya cuelga la segunda, así que si el orden
    está mal esto falla en la vuelta 2 y no por casualidad.
    """
    class _CierreRoto(Exception):
        pass

    async def _aclose_que_revienta():
        raise _CierreRoto("el socket del upstream ya estaba muerto")

    for vuelta in range(3):
        motor.soltar.clear()
        respuesta = await _byok(stream=True)
        assert respuesta.status_code == 200, f"vuelta {vuelta}: el turno de la anterior se filtró"
        motor.streams[-1].aclose = _aclose_que_revienta

        motor.soltar.set()
        with pytest.raises(_CierreRoto):
            async for _ in respuesta.body_iterator:
                pass

    assert (await _byok()).status_code == 200, (
        "tres cierres rotos y el semáforo tiene que estar entero")


# ── N1/N2 del gate round 2 de #135 (issue #150): la ventana antes del primer chunk ─


@pytest.mark.asyncio
async def test_el_disconnect_antes_del_primer_chunk_no_se_come_el_turno(
        harness, motor, gate_de_uno):
    """N1: entre el traspaso del turno y el primer `__anext__` del generador no hay NADIE.

    `_byok_proxy` marca `turno_traspasado = True` y devuelve el `StreamingResponse` confiando en
    que el `finally` del generador va a soltar el turno. Pero el generador recién arranca
    después de que `stream_response` mande `http.response.start`, y ESE send puede quedarse
    esperando drain: es write-backpressure, o sea el cliente que no lee y el buffer del socket
    lleno — el caso normal de una coding tool que se quedó pensando. Si el `http.disconnect`
    entra en esa ventana, starlette cancela el task group con el generador todavía sin arrancar,
    y un generador asíncrono que NUNCA arrancó no ejecuta su `finally` (PEP 525). Nadie llama a
    `liberar()`: el turno queda tomado por un pedido que ya no existe, y no vuelve hasta que se
    reinicia el worker. Con el tope de la sede en 8, ocho desconexiones desafortunadas dejan el
    producto rechazando 503 con el motor vacío.

    No hacen falta sockets para reproducirlo: la backpressure es un `send` colgado de un `Event`
    que no se prende nunca, que es exactamente lo que hace un write que no drena.
    """
    respuesta = await _byok(stream=True)
    assert respuesta.status_code == 200

    semaforo = gate_de_uno._semaforo()
    assert semaforo._value == 0, "cap=1: el stream ya devuelto tiene que tener el turno tomado"

    enviados = []
    primer_send = asyncio.Event()
    el_socket_nunca_drena = asyncio.Event()  # se prende JAMÁS: ese es el escenario

    async def send(mensaje):
        enviados.append(mensaje["type"])
        primer_send.set()
        await el_socket_nunca_drena.wait()

    async def receive():
        await primer_send.wait()  # el cliente se va justo mientras esperamos el drain
        return {"type": "http.disconnect"}

    await asyncio.wait_for(respuesta(_scope_asgi(), receive, send), timeout=10)
    await asyncio.sleep(0)

    assert enviados == ["http.response.start"], (
        "el escenario tiene que morir en el PRIMER send; si llegó un chunk esto ya no es N1")
    assert motor.streams[0].arranco is False, (
        "el generador arrancó: entonces esto prueba otra cosa y no la ventana de N1")
    assert semaforo._value == 1, (
        "el turno se fugó en la ventana previa al primer chunk: el generador nunca arrancó, su "
        "`finally` no existe (PEP 525) y el tope quedó encogido para siempre")

    motor.soltar.set()
    assert (await _byok()).status_code == 200, "y el turno tiene que servir de verdad"


@pytest.mark.asyncio
async def test_el_send_que_levanta_por_desconexion_tampoco_se_come_el_turno(
        harness, motor, gate_de_uno):
    """La segunda variante de la MISMA ventana, por si la primera se tapa a medias.

    Un servidor ASGI puede no colgarse en el `send()` posterior a la desconexión sino LEVANTAR.
    Uvicorn 0.30 —el de esta imagen— lo hace hoy sólo en el plano websocket (`ClientDisconnected`
    vive en `websockets_impl`/`wsproto_impl`; el camino HTTP de `h11_impl` hace `if
    self.disconnected: return`, un no-op silencioso), pero hypercorn/granian y cualquier cambio
    futuro de ese camino pueden levantar acá. Misma ventana, mismo generador sin arrancar, mismo
    turno fugado, pero por un camino distinto — y esa diferencia es la que descarta arreglar esto
    con un `BackgroundTask`: cuando la excepción se escapa del task group, starlette nunca llega
    a la línea que lo corre (verificado en el fuente de `StreamingResponse.__call__`: el `await
    self.background()` está DESPUÉS del `async with create_task_group()`). La liberación tiene
    que estar en un `finally` que envuelva al `__call__` entero.

    El doble es una excepción nuestra y no la de ningún servidor a propósito: lo que se prueba es
    que CUALQUIER excepción del transporte devuelve el turno, no que sepamos importar una clase.
    """
    class _ClienteSeFue(Exception):
        """Doble de `uvicorn.protocols.utils.ClientDisconnected`."""

    respuesta = await _byok(stream=True)
    semaforo = gate_de_uno._semaforo()
    assert semaforo._value == 0

    enviados = []

    async def send(mensaje):
        enviados.append(mensaje["type"])
        raise _ClienteSeFue("el socket ya estaba cerrado cuando quisimos escribir")

    async def receive():
        await asyncio.Event().wait()  # no vuelve nunca: lo corta la cancelación del grupo

    with pytest.raises((_ClienteSeFue, BaseExceptionGroup)) as capturado:
        await asyncio.wait_for(respuesta(_scope_asgi(), receive, send), timeout=10)
    await asyncio.sleep(0)

    assert any(isinstance(e, _ClienteSeFue) for e in _aplanar(capturado.value)), (
        f"el test tenía que morir por la desconexión y murió por otra cosa: {capturado.value!r}")
    assert enviados == ["http.response.start"], "la excepción va en el primer send o no es N1"
    assert motor.streams[0].arranco is False
    assert semaforo._value == 1, (
        "el turno se fugó por la variante `ClientDisconnected`: la excepción se escapa del task "
        "group, así que nada que cuelgue DESPUÉS del `__call__` —un `BackgroundTask`, por "
        "ejemplo— alcanza a devolverlo")

    motor.soltar.set()
    assert (await _byok()).status_code == 200


@pytest.mark.asyncio
async def test_la_cancelacion_del_cliente_igual_tiene_que_cerrar_el_upstream(
        harness, motor, gate_de_uno):
    """N2: hoy el turno vuelve pero la conexión con el motor queda ABIERTA.

    El `finally` del generador libera primero y cierra después (H1), y eso está bien; el costo
    es que ese `finally` corre con el generador ya cancelado y sus `aclose()` no llegan a
    completarse: el socket contra el motor no lo cierra nadie hasta que lo junte el GC o venza
    un timeout. Cada cancelación deja una conexión colgando y el motor sigue GENERANDO para un
    cliente que ya se fue — o sea que el turno vuelve al semáforo pero el trabajo real no baja,
    que es la mitad del incidente de la sede. Lo que fija este test es que el cierre igual
    ocurre, porque el `finally` de la RESPUESTA lo hace por su cuenta.

    OJO con el alcance: este test NO custodia el `shield=True`. Acá la cancelación nace ADENTRO
    del `StreamingResponse` y su propio task group se la come al salir del `async with`, así que
    para cuando corre el `finally` de la respuesta ya no hay cancelación pendiente y los
    `aclose()` andan con escudo o sin él (verificado: sacando el escudo este test sigue verde).
    El que muere sin escudo es el hermano de abajo, con la cancelación viniendo de AFUERA.
    """
    respuesta = await _byok(stream=True)
    assert respuesta.status_code == 200

    primer_chunk = asyncio.Event()
    enviados = []

    async def send(mensaje):
        enviados.append(mensaje["type"])
        if mensaje["type"] == "http.response.body" and mensaje.get("body"):
            primer_chunk.set()  # el cliente ya recibió tokens... y ahora se va

    async def receive():
        await primer_chunk.wait()
        return {"type": "http.disconnect"}

    # El upstream NUNCA se suelta: el generador queda suspendido esperando el chunk siguiente,
    # que es exactamente donde lo agarra la cancelación.
    await asyncio.wait_for(respuesta(_scope_asgi(), receive, send), timeout=10)
    await asyncio.sleep(0)

    assert "http.response.body" in enviados, "el escenario no llegó a mandar el primer chunk"
    assert motor.streams[0].cerrado is True, (
        "la cancelación del cliente dejó abierta la conexión con el motor: el semáforo miente, "
        "porque el turno volvió pero la generación sigue consumiendo el motor de verdad")
    assert motor.clientes[-1].cerrado is True, (
        "cerraron la respuesta pero NO el `AsyncClient`: el pool de conexiones del cliente "
        "queda vivo con el socket contra el motor, y ese cliente ya no lo cierra nadie")


@pytest.mark.asyncio
async def test_el_cierre_del_upstream_sobrevive_a_una_cancelacion_de_afuera(
        harness, motor, gate_de_uno):
    """El escudo de N2: acá el que corta NO es el cliente, es el que ejecuta la respuesta.

    En el test hermano la cancelación nace ADENTRO del `StreamingResponse` y su propio task
    group se la come, así que para cuando corre el `finally` de la respuesta el scope ya está
    limpio y los `aclose()` andan con escudo o sin él. La que duele es la de afuera —un cancel
    scope que envuelve al pedido: shutdown del worker, un middleware con timeout, cualquier
    task group por encima—: ahí el `finally` corre DENTRO de un scope cancelado y anyio
    re-entrega la cancelación en cada suspensión, así que el primer `await` del cierre se la
    lleva y el socket contra el motor queda colgando con el modelo generando para nadie.

    Por eso el cierre va en un `move_on_after(..., shield=True)` y no en un `try` pelado. Este
    test es el único que muere si alguien saca el escudo. Razón de diseño de por qué el corte va
    con un cancel scope de anyio y no con `Task.cancel()` crudo: por semántica de asyncio la
    cancelación cruda se entrega una sola vez, así que el cierre zafaría y el escenario no
    distinguiría el escudo puesto del sacado. Eso NO se midió acá; lo que sí está medido es que
    con el task group de anyio, sacando el `shield`, este test se pone rojo.
    """
    respuesta = await _byok(stream=True)
    assert respuesta.status_code == 200

    primer_chunk = asyncio.Event()

    async def send(mensaje):
        if mensaje["type"] == "http.response.body" and mensaje.get("body"):
            primer_chunk.set()

    async def receive():
        await asyncio.Event().wait()  # el cliente NO se va: el corte viene de arriba

    async with anyio.create_task_group() as tg:
        tg.start_soon(respuesta, _scope_asgi(), receive, send)
        await asyncio.wait_for(primer_chunk.wait(), timeout=10)
        tg.cancel_scope.cancel()

    assert motor.streams[0].cerrado is True, (
        "la cancelación de afuera dejó abierta la conexión con el motor: sin `shield=True` los "
        "`aclose()` del `finally` se comen la cancelación re-entregada y el motor sigue "
        "generando para un pedido que ya no existe")
    assert motor.clientes[-1].cerrado is True, (
        "el `AsyncClient` quedó abierto: el escudo alcanzó para la respuesta pero el cliente "
        "—que es el dueño del pool— se filtra igual")
    assert gate_de_uno._semaforo()._value == 1, (
        "los cierres corrieron pero el turno no volvió: con cap=1 el próximo pedido come 503 "
        "con el motor vacío")


@pytest.mark.asyncio
async def test_cuando_corren_los_cierres_de_la_respuesta_el_turno_YA_volvio(
        harness, motor, gate_de_uno):
    """El ORDEN dentro del `finally` de la respuesta: `liberar()` va PRIMERO, cierres después.

    Mismo criterio que en el generador (H1 del gate de #135): `liberar()` es sync e infalible y
    los `aclose()` son I/O. Los cierres de acá van envueltos en un `try/except Exception`, así
    que un cierre que revienta ya no saltea el `liberar()` — pero ese `except` NO atrapa
    `BaseException`, y un `CancelledError` crudo cayendo dentro de un `aclose()` con el orden
    invertido se llevaría el turno para siempre (un turno filtrado no vuelve hasta reiniciar el
    worker). El orden es la garantía barata contra esa clase entera de fallas.

    El ASSERT no depende de tiempos: el doble del upstream anota el valor del semáforo en el
    momento exacto en que lo cierran, así que lo que se compara es un orden observado desde
    adentro del `aclose()` y no una carrera. (El escenario sí usa un `wait_for` como red de
    seguridad para que un cuelgue falle en vez de colgar la suite, pero el veredicto no sale
    de ahí.)

    Va por el camino de N1 (el generador NUNCA arranca) a propósito: es el único donde el
    `finally` de la respuesta corre solo. En cualquier otro el del generador ya liberó antes y
    el test no vería el orden que quiere fijar.
    """
    respuesta = await _byok(stream=True)
    semaforo = gate_de_uno._semaforo()
    assert semaforo._value == 0, "cap=1: el stream ya devuelto tiene que tener el turno tomado"

    upstream = motor.streams[0]
    visto = []

    async def _aclose_que_mira_el_semaforo():
        visto.append(semaforo._value)
        await asyncio.sleep(0)  # cerrar de verdad suspende; ver `_RespuestaStream.aclose`
        upstream.cerrado = True

    upstream.aclose = _aclose_que_mira_el_semaforo

    primer_send = asyncio.Event()
    el_socket_nunca_drena = asyncio.Event()  # se prende JAMÁS: la ventana de N1

    async def send(_mensaje):
        primer_send.set()
        await el_socket_nunca_drena.wait()

    async def receive():
        await primer_send.wait()
        return {"type": "http.disconnect"}

    await asyncio.wait_for(respuesta(_scope_asgi(), receive, send), timeout=10)

    assert upstream.arranco is False, (
        "el generador arrancó: su `finally` ya liberó por su cuenta y esto dejó de medir el "
        "orden del `finally` de la respuesta")
    assert visto == [1], (
        f"el cierre del upstream corrió con el turno TODAVÍA tomado (semáforo en {visto}): con "
        "ese orden, una `BaseException` dentro de un `aclose()` —la que el `except Exception` "
        "no atrapa— se lleva el turno para siempre")


@pytest.mark.asyncio
async def test_un_cierre_que_revienta_en_la_respuesta_no_se_lleva_al_que_sigue(
        harness, motor, gate_de_uno):
    """El `try/except Exception` de cada cierre del `finally` de `_StreamConTurno`.

    `cierres` es una TUPLA (la respuesta del upstream y el `AsyncClient` que la sostiene) y se
    recorre en un `for`. Sin el `except`, la excepción del primer `aclose()` aborta el bucle y el
    SEGUNDO cierre no corre nunca: el turno vuelve igual —`liberar()` va antes— pero el
    `AsyncClient` queda vivo con el socket contra el motor, que es la otra mitad del incidente de
    la sede. Además la excepción se escaparía del `__call__` hacia el servidor ASGI, y a esa
    altura el pedido ya terminó: sólo cambiaría un socket colgado por un 500 en los logs.

    Va por el camino de N1 (el generador NUNCA arranca) igual que el test del orden: es el único
    donde el `finally` de la respuesta corre solo, sin que el del generador haya cerrado antes.

    OJO con el alcance: esto NO contradice a
    `test_el_turno_vuelve_aunque_el_cierre_del_upstream_reviente`. Ahí el que revienta es el
    `finally` del GENERADOR, y ahí la excepción TIENE que seguir propagando. El tragado con log
    va sólo en el `finally` de `__call__`.
    """
    class _CierreRoto(Exception):
        pass

    respuesta = await _byok(stream=True)
    semaforo = gate_de_uno._semaforo()
    assert semaforo._value == 0, "cap=1: el stream ya devuelto tiene que tener el turno tomado"

    upstream = motor.streams[0]
    cliente = motor.clientes[-1]
    visto = []

    async def _aclose_que_revienta():
        visto.append(semaforo._value)
        raise _CierreRoto("el socket del upstream ya estaba muerto")

    upstream.aclose = _aclose_que_revienta

    primer_send = asyncio.Event()
    el_socket_nunca_drena = asyncio.Event()  # se prende JAMÁS: la ventana de N1

    async def send(_mensaje):
        primer_send.set()
        await el_socket_nunca_drena.wait()

    async def receive():
        await primer_send.wait()
        return {"type": "http.disconnect"}

    # (c) la excepción NO se escapa del `__call__`: si se escapara, esto reventaría acá.
    await asyncio.wait_for(respuesta(_scope_asgi(), receive, send), timeout=10)

    assert upstream.arranco is False, (
        "el generador arrancó: su `finally` ya cerró por su cuenta y esto dejó de medir el "
        "`finally` de la respuesta")
    assert visto == [1], (
        f"el cierre roto no corrió, o corrió con el turno todavía tomado (semáforo en {visto})")
    # (a) el segundo cierre corrió igual: el `except` no abortó el bucle.
    assert cliente.cerrado is True, (
        "el primer cierre reventó y se llevó puesto al segundo: el `AsyncClient` —dueño del "
        "pool— quedó abierto con el socket contra el motor")
    # (b) el turno ya había vuelto (`visto`) y sigue entero.
    assert semaforo._value == 1
    motor.soltar.set()  # el no-stream de abajo espera al motor; sin esto se cuelga
    assert (await _byok()).status_code == 200, "y el turno tiene que servir de verdad"


@pytest.mark.asyncio
async def test_el_camino_feliz_libera_el_turno_dos_veces_sin_inflar_el_semaforo(
        harness, motor, gate_de_uno):
    """Guardia de la doble liberación: el `finally` del generador y el de la respuesta suman.

    El fix de N1 no le saca el `finally` al generador —lo necesita para soltar el turno TEMPRANO
    (apenas termina de drenar) y no recién cuando el ASGI se desarma—, así que en el camino
    feliz `liberar()` corre DOS veces sobre el mismo turno. Eso es sano sólo mientras
    `TurnoDelMotor.liberar()` sea idempotente: si alguien la simplifica a un `release()` pelado,
    el `BoundedSemaphore` levanta `ValueError` en la segunda —y no se le come nada al tope, que
    para eso está acotado y no es un `Semaphore` común—. Este test no se pone rojo por la fuga,
    se pone rojo si el arreglo de la fuga rompe la contabilidad.
    """
    respuesta = await _byok(stream=True)
    semaforo = gate_de_uno._semaforo()
    assert semaforo._value == 0

    motor.soltar.set()  # el upstream termina solo: camino feliz completo, sin cancelaciones
    enviados = []

    async def send(mensaje):
        enviados.append(mensaje["type"])

    async def receive():
        await asyncio.Event().wait()  # el cliente aguanta hasta el final; lo corta starlette

    await asyncio.wait_for(respuesta(_scope_asgi(), receive, send), timeout=10)

    assert enviados[0] == "http.response.start"
    assert enviados.count("http.response.body") == 3, (
        f"dos chunks más el cierre del body; llegaron {enviados}")
    assert motor.streams[0].cerrado is True, "el camino feliz cierra el upstream siempre"
    assert semaforo._value == 1, (
        "el turno no volvió entero: con cap=1 el semáforo tiene que quedar en 1, ni 0 (fuga) "
        "ni 2 (permiso regalado)")
    assert (await _byok()).status_code == 200


# ── H2: el rechazo no puede congelar el worker ────────────────────────────────────


@pytest.mark.asyncio
async def test_el_rechazo_por_capacidad_no_bloquea_el_event_loop(
        harness, motor, gate_de_uno, eventos_de_vitrina, monkeypatch):
    """H2 del gate de #135: el 503 "rápido" congelaba el worker justo cuando había saturación.

    `_rechazo_por_capacidad` abre dos sesiones Postgres NUEVAS (este plano no tiene `get_db`), y
    el `acquire` del pool de SQLAlchemy es SÍNCRONO: con el pool agotado —que es el estado
    normal durante un pico— espera `pool_timeout` desde el event loop y ahí se termina el
    producto entero. Medido en el gate: 503 en **120,9 s con el loop bloqueado 120,7 s**. El
    camino que existe para no degradar el producto era el que lo tumbaba.

    El test no mide Postgres: stubbea la escritura durable con un `time.sleep` (I/O bloqueante
    de laboratorio) y mide el HUECO máximo entre iteraciones de un latido del loop. Si el
    registro corre en el loop, el latido se para medio segundo; si corre en un hilo, no lo nota.
    """
    from src.api import gateway

    ESPERA_DE_LA_BASE = 0.5

    def _audit_lento(*_a, **_k):
        time.sleep(ESPERA_DE_LA_BASE)  # el `acquire` síncrono del pool, en miniatura
        return True

    monkeypatch.setattr(gateway, "_audit", _audit_lento)

    hueco_maximo = 0.0
    latiendo = True

    async def latido():
        nonlocal hueco_maximo
        loop = asyncio.get_running_loop()
        anterior = loop.time()
        while latiendo:
            await asyncio.sleep(0.005)
            ahora = loop.time()
            hueco_maximo = max(hueco_maximo, ahora - anterior)
            anterior = ahora

    corazon = asyncio.create_task(latido())
    await asyncio.sleep(0.05)  # unas cuantas iteraciones sanas de referencia

    turno = await gate_de_uno.adquirir_turno().adquirir()  # cap=1 ⇒ el próximo rebota
    try:
        inicio = asyncio.get_running_loop().time()
        rechazo = await _byok()
        tardanza = asyncio.get_running_loop().time() - inicio
    finally:
        turno.liberar()
        latiendo = False
        await corazon

    assert rechazo.status_code == 503
    assert rechazo.headers.get("X-Sentinel-Rejected") == "saturated"
    # La fila SIGUE escribiéndose antes de responder (registrar → rechazar): lo que cambia es
    # DÓNDE corre, no cuándo. Por eso el pedido tarda lo que tarda la base...
    assert tardanza >= ESPERA_DE_LA_BASE, (
        "el rechazo contestó sin esperar el registro — eso sería la fila diferida, que es otra "
        "decisión (y es de JF)")
    # ...pero el resto del producto no se entera.
    assert hueco_maximo < 0.05, (
        f"el event loop quedó bloqueado {hueco_maximo:.3f}s escribiendo la fila del rechazo: "
        "con el pool bajo presión eso es el worker entero congelado")


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
async def test_el_byok_no_stream_usa_su_propio_timeout_y_no_el_del_chat(harness, motor):
    """Antes: `120.0` hardcodeado acá y otro parser en `chat.py`; en el round 1 los dos caminos
    compartieron `SENTINEL_ENGINE_TIMEOUT_SECONDS` y eso REGRESÓ este camino de 120 a 60 s (H3 del
    gate). Ahora cada plano tiene su env acotada, y la de acá arranca en 150 s.

    Igualdad con la constante propia: si alguien reinstala un literal o vuelve a cablear la del
    chat, este assert cae — que es justo lo que hay que impedir.
    """
    from src.services import engine_gate
    motor.soltar.set()

    assert (await _byok()).status_code == 200

    assert motor.kwargs_cliente[0]["timeout"] == engine_gate.GW_BYOK_TIMEOUT_SECONDS
    assert engine_gate.GW_BYOK_TIMEOUT_SECONDS > 120.0, (
        "el byok tiene que aguantar más que los 120 s que el router del perfil prod espera por "
        "generación, o convierte una respuesta lenta pero buena en un error nuestro")


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


# ── #158: el passthrough de suscripción tiene la MISMA anatomía de fuga que el byok ──
#
# El passthrough NO gatea admisión (no hay turno, #134-③), así que acá NO se mira el semáforo.
# Lo que se fija es la OTRA mitad del incidente: la conexión con el upstream y —promesa core,
# "loguear TODO"— la fila de auditoría. En la ventana pre-primer-paso el `finally` del generador
# no existe (PEP 525), así que sin el fix un passthrough cancelado deja el socket colgando Y no
# escribe fila. Igual que el byok, la respuesta (`_StreamConTurno`) es la dueña del cierre; a
# diferencia del byok, además es dueña de la auditoría diferida (el byok la audita en el motor).
#
# Se ejecuta la respuesta como ASGI DE VERDAD —`await respuesta(scope, receive, send)`— por lo
# mismo que los tests del byok: el corte que rompe en producción es la cancelación del task group
# de `StreamingResponse.__call__`, no un `body_iterator.aclose()` (que entra por `GeneratorExit`).


def _peticion_passthrough():
    """`Request` de passthrough de suscripción: sin virtual key (→ NO byok) y con el body
    resoluble por `request.body()`. El `Authorization: Bearer` es el OAuth de la suscripción, que
    no lleva `sk-sentinel-…`, así que `_detect_mode_and_key` resuelve subscription-passthrough."""
    cuerpo = json.dumps({**CUERPO, "stream": True}).encode()

    async def receive():
        return {"type": "http.request", "body": cuerpo, "more_body": False}

    return Request({
        "type": "http", "http_version": "1.1", "method": "POST",
        "path": "/gw/v1/messages", "raw_path": b"/gw/v1/messages", "query_string": b"",
        "root_path": "", "scheme": "http", "server": ("test", 80), "client": ("test", 1),
        "headers": [(b"user-agent", b"claude-cli/1.0"),
                    (b"authorization", b"Bearer oauth-de-suscripcion")],
    }, receive)


async def _passthrough():
    """Invoca el endpoint DIRECTO (no por HTTP) para poder tener el stream abierto y sin drenar:
    el transporte ASGI de httpx bufferea la respuesta entera, así que por HTTP ese estado —el que
    hay que cancelar— es imposible. Los `Header(...)` se pasan explícitos porque llamando la
    función a mano el default es el objeto `Header`, no `None`."""
    from src.api import gateway
    return await gateway.gw_messages(
        _peticion_passthrough(), x_sentinel_key=None, x_sentinel_redact=None, x_sentinel_upstream=None)


@pytest.mark.asyncio
async def test_el_passthrough_cancelado_antes_del_primer_chunk_cierra_upstream_y_deja_fila(
        harness, motor, eventos_de_vitrina):
    """La ventana de #158: el cliente corta ANTES del primer `__anext__` del generador.

    El generador nunca arranca, así que su `finally` no corre (PEP 525) — exactamente donde el
    código viejo hacía los `aclose()` y escribía la fila. El fix mueve las dos cosas al `finally`
    de la RESPUESTA (que starlette ejecuta siempre), así que acá se afirma que (a) el upstream y el
    `AsyncClient` se cerraron y (b) quedó UNA fila durable de `passthrough_cancelled`. Sin el fix
    las dos fallan: socket colgado hasta el GC + hueco de auditoría."""
    from src.api import gateway
    _, factory = harness
    borrar_filas(factory)

    respuesta = await _passthrough()
    assert respuesta.status_code == 200

    enviados = []
    primer_send = asyncio.Event()
    el_socket_nunca_drena = asyncio.Event()  # se prende JAMÁS: la ventana pre-primer-paso

    async def send(mensaje):
        enviados.append(mensaje["type"])
        primer_send.set()
        await el_socket_nunca_drena.wait()

    async def receive():
        await primer_send.wait()  # el cliente se va justo mientras esperamos el drain del start
        return {"type": "http.disconnect"}

    await asyncio.wait_for(respuesta(_scope_asgi(), receive, send), timeout=10)
    await asyncio.sleep(0)

    assert enviados == ["http.response.start"], (
        "el escenario tiene que morir en el PRIMER send; si llegó un chunk ya no es pre-primer-paso")
    assert motor.streams[0].arranco is False, (
        "el generador arrancó: entonces esto prueba otra cosa y no la ventana de #158")
    # (a) los `aclose()` corrieron aunque el generador NUNCA arrancó — los hace la respuesta.
    assert motor.streams[0].cerrado is True, (
        "el upstream quedó abierto: la conexión con Anthropic se fuga hasta el GC (#158)")
    assert motor.clientes[-1].cerrado is True, (
        "el `AsyncClient` —dueño del pool— quedó abierto con el socket contra el upstream")
    # (b) quedó fila durable de "cancelado": "loguear TODO" también para el pedido cortado.
    canceladas = filas(factory, gateway.STATUS_PASSTHROUGH_CANCELADO)
    assert len(canceladas) == 1, (
        f"un passthrough cancelado deja UNA fila durable, quedaron {len(canceladas)} (#158)")
    assert canceladas[0]["model"] == MODELO
    assert canceladas[0]["prompt_tokens"] == 0 and canceladas[0]["completion_tokens"] == 0, (
        "el generador nunca arrancó: no se vio ni un token, la fila tiene que decir 0/0")
    assert [e["status"] for e in eventos_de_vitrina] == [gateway.STATUS_PASSTHROUGH_CANCELADO]


@pytest.mark.asyncio
async def test_la_auditoria_del_passthrough_cancelado_no_bloquea_el_event_loop(
        harness, motor, eventos_de_vitrina, monkeypatch):
    """H2 para el passthrough: la fila del cancelado se escribe en un HILO, no en el event loop.

    `_audit` abre una sesión Postgres NUEVA (este plano no tiene `get_db`) y el `acquire` del pool
    es SÍNCRONO: escribirla desde el loop congela el worker `pool_timeout` segundos bajo presión.
    El test stubbea la escritura con un `time.sleep` (I/O bloqueante de laboratorio) y mide el
    HUECO máximo entre latidos del loop mientras corre el `finally` de la respuesta cancelada. Si
    la fila corre en el loop el latido se para medio segundo; si corre en un hilo, no lo nota."""
    from src.api import gateway
    _, factory = harness
    borrar_filas(factory)

    ESPERA_DE_LA_BASE = 0.5

    def _audit_lento(*_a, **_k):
        time.sleep(ESPERA_DE_LA_BASE)  # el `acquire` síncrono del pool, en miniatura
        return True

    monkeypatch.setattr(gateway, "_audit", _audit_lento)

    hueco_maximo = 0.0
    latiendo = True

    async def latido():
        nonlocal hueco_maximo
        loop = asyncio.get_running_loop()
        anterior = loop.time()
        while latiendo:
            await asyncio.sleep(0.005)
            ahora = loop.time()
            hueco_maximo = max(hueco_maximo, ahora - anterior)
            anterior = ahora

    respuesta = await _passthrough()
    primer_send = asyncio.Event()
    el_socket_nunca_drena = asyncio.Event()

    async def send(_mensaje):
        primer_send.set()
        await el_socket_nunca_drena.wait()

    async def receive():
        await primer_send.wait()
        return {"type": "http.disconnect"}

    corazon = asyncio.create_task(latido())
    await asyncio.sleep(0.05)  # unas cuantas iteraciones sanas de referencia
    try:
        await asyncio.wait_for(respuesta(_scope_asgi(), receive, send), timeout=10)
    finally:
        latiendo = False
        await corazon

    # La fila SIGUE escribiéndose (el stub devolvió True y la vitrina capturó el evento): lo que
    # cambia es DÓNDE corre, no si corre.
    assert [e["status"] for e in eventos_de_vitrina] == [gateway.STATUS_PASSTHROUGH_CANCELADO]
    assert hueco_maximo < 0.05, (
        f"el event loop quedó bloqueado {hueco_maximo:.3f}s escribiendo la fila del passthrough "
        "cancelado: con el pool bajo presión eso es el worker entero congelado (H2)")


@pytest.mark.asyncio
async def test_el_passthrough_que_drena_entero_audita_una_sola_vez_con_el_estado_de_politica(
        harness, motor, eventos_de_vitrina):
    """Regresión + idempotencia: el camino feliz sigue escribiendo UNA fila con el veredicto de
    política (no `cancelled`), y la auditoría diferida no la duplica.

    El `finally` de la respuesta corre la misma clausura de auditoría también acá; que quede UNA
    sola fila y UN solo evento de vitrina es lo que fija la idempotencia por diseño (#158)."""
    from src.api import gateway
    _, factory = harness
    borrar_filas(factory)

    motor.soltar.set()  # el upstream cloud drena entero, sin cancelaciones
    respuesta = await _passthrough()

    enviados = []

    async def send(mensaje):
        enviados.append(mensaje["type"])

    async def receive():
        await asyncio.Event().wait()  # el cliente aguanta hasta el final; lo corta starlette

    await asyncio.wait_for(respuesta(_scope_asgi(), receive, send), timeout=10)

    assert enviados[0] == "http.response.start"
    assert motor.streams[0].arranco is True and motor.streams[0].cerrado is True, (
        "el camino feliz drena y cierra el upstream")
    assert motor.clientes[-1].cerrado is True, "y también el `AsyncClient`"
    # UNA sola escritura: un evento de vitrina, una fila, y el estado NO es `cancelled`.
    assert len(eventos_de_vitrina) == 1, (
        f"el camino feliz audita UNA sola vez, hubo {len(eventos_de_vitrina)} (¿fila duplicada?)")
    estado_feliz = eventos_de_vitrina[0]["status"]
    assert estado_feliz != gateway.STATUS_PASSTHROUGH_CANCELADO, (
        "un passthrough que drenó entero se audita con el veredicto de política, no como cancelado")
    assert len(filas(factory, estado_feliz)) == 1, "una fila durable por pedido"
    assert len(filas(factory, gateway.STATUS_PASSTHROUGH_CANCELADO)) == 0, (
        "el camino feliz no puede dejar una fila de cancelado")


# ── gate #224 P2: distinguir «el destino falló» de «el cliente cortó» ──
#
# Los dos caminos incompletos (el generador no llega a `completo=True`) NO son el mismo evento:
# si el cliente corta, la fila es `passthrough_cancelled`; si el UPSTREAM revienta a mitad de
# stream, es `upstream_error`. La diferencia se decide por el TIPO de lo que sube por el
# generador —la cancelación del cliente entra como BaseException (`CancelledError`/`GeneratorExit`,
# absorbida por el scope de `StreamingResponse`), el fallo del destino como `Exception` de httpx—,
# no por una heurística. Estos dos tests clavan cada rama (hallazgos 8 y 6 del gate).


@pytest.mark.asyncio
async def test_el_upstream_que_revienta_a_mitad_audita_upstream_error_y_no_cancelado(
        harness, motor, eventos_de_vitrina):
    """Hallazgo 8: un `ReadError` de `up.aiter_raw()` a mitad de stream = el destino falló, NO el
    cliente. Antes la fila salía `passthrough_cancelled` («el cliente cortó») porque el generador
    se interrumpía sin `completo=True` y el `finally` de la respuesta no sabía por qué. Fix: el
    `except Exception` del generador —que NO atrapa la cancelación del cliente (BaseException)—
    marca `upstream_error` y re-levanta; la fila sale `upstream_error` con los tokens vistos."""
    import httpx
    from src.api import gateway
    _, factory = harness
    borrar_filas(factory)

    respuesta = await _passthrough()
    assert respuesta.status_code == 200
    up = motor.streams[0]

    async def _revienta_a_mitad():
        # Un frame de usage ANTES de reventar: la fila del fallo tiene que llevar los tokens que se
        # alcanzaron a ver, no 0. `raise` de httpx = fallo del destino, no cancelación del cliente.
        up.arranco = True
        yield (b'event: message_start\n'
               b'data: {"type":"message_start","message":{"usage":{"input_tokens":11}}}\n\n')
        raise httpx.ReadError("el upstream cortó la conexión a mitad de stream")

    up.aiter_raw = _revienta_a_mitad

    enviados = []

    async def send(mensaje):
        enviados.append(mensaje["type"])

    async def receive():
        await asyncio.Event().wait()  # el cliente NO se va: el que rompe es el destino

    # La excepción del upstream se PROPAGA (no es una cancelación que el scope absorba): el stream
    # se corta igual que hoy. Lo único que cambia por el fix es la ETIQUETA de la fila.
    with pytest.raises(BaseException) as ei:
        await asyncio.wait_for(respuesta(_scope_asgi(), receive, send), timeout=10)
    assert any(isinstance(e, httpx.ReadError) for e in _aplanar(ei.value)), (
        "la ReadError del upstream tiene que llegar arriba, no tragarse en silencio")

    assert enviados[0] == "http.response.start"
    assert up.arranco is True, "corte a MITAD (el generador arrancó), no pre-primer-paso"
    # El cierre corre igual —lo hace el `finally` de la respuesta— aunque el generador reventara.
    assert up.cerrado is True and motor.clientes[-1].cerrado is True, (
        "el upstream y el `AsyncClient` se cierran aunque el stream reviente")
    # La fila dice `upstream_error`, NO `passthrough_cancelled`, y con los tokens vistos.
    errores = filas(factory, "upstream_error")
    assert len(errores) == 1, (
        f"un upstream que revienta deja UNA fila `upstream_error`, quedaron {len(errores)}")
    assert errores[0]["prompt_tokens"] == 11 and errores[0]["completion_tokens"] == 0, (
        "la fila del fallo lleva los tokens vistos hasta el corte")
    assert len(filas(factory, gateway.STATUS_PASSTHROUGH_CANCELADO)) == 0, (
        "un fallo del destino NO puede etiquetarse como cancelación del cliente (hallazgo 8)")
    assert [e["status"] for e in eventos_de_vitrina] == ["upstream_error"]


@pytest.mark.asyncio
async def test_el_passthrough_cancelado_a_mitad_deja_una_fila_con_los_tokens_vistos(
        harness, motor, eventos_de_vitrina):
    """Hallazgo 6: el «bonus» del PR —cancelar a MITAD del stream, no antes del primer chunk—
    quedó sin test que lo clavara. Se entregan dos frames de usage (in=11, out=7), el cliente se
    desconecta con el stream aún abierto, y se afirma UNA fila `passthrough_cancelled` con esos
    tokens (no 0/0 como el caso pre-primer-paso, y no `upstream_error`: acá cortó el cliente)."""
    from src.api import gateway
    _, factory = harness
    borrar_filas(factory)

    respuesta = await _passthrough()
    up = motor.streams[0]
    tokens_vistos = asyncio.Event()  # se prende cuando los dos frames ya se espejaron en la fila

    async def _dos_frames_y_se_cuelga():
        up.arranco = True
        # Un solo chunk con los dos frames: el generador los procesa y espeja SIN puntos de
        # suspensión entre medio, así que para cuando `tokens_vistos` se prende la fila ya tiene
        # in=11/out=7 — la desconexión no puede colarse a mitad y volver el test flaky.
        yield (b'event: message_start\n'
               b'data: {"type":"message_start","message":{"usage":{"input_tokens":11}}}\n\n'
               b'event: message_delta\n'
               b'data: {"type":"message_delta","usage":{"output_tokens":7}}\n\n')
        tokens_vistos.set()
        await asyncio.Event().wait()  # el upstream sigue "generando"; el cliente corta acá

    up.aiter_raw = _dos_frames_y_se_cuelga

    enviados = []

    async def send(mensaje):
        enviados.append(mensaje["type"])

    async def receive():
        await tokens_vistos.wait()  # el cliente se va con los tokens YA vistos y el stream abierto
        return {"type": "http.disconnect"}

    await asyncio.wait_for(respuesta(_scope_asgi(), receive, send), timeout=10)

    assert enviados[0] == "http.response.start"
    assert up.arranco is True, "cancelación a MITAD: el generador tiene que haber arrancado"
    assert up.cerrado is True and motor.clientes[-1].cerrado is True, (
        "el upstream y el `AsyncClient` se cierran también cuando el cliente corta a mitad")
    # UNA fila de cancelado, con los tokens vistos hasta el corte (no 0/0, no `upstream_error`).
    canceladas = filas(factory, gateway.STATUS_PASSTHROUGH_CANCELADO)
    assert len(canceladas) == 1, (
        f"cortar a mitad deja UNA fila `passthrough_cancelled`, quedaron {len(canceladas)}")
    assert canceladas[0]["prompt_tokens"] == 11 and canceladas[0]["completion_tokens"] == 7, (
        "la fila del cancelado a mitad lleva los tokens vistos hasta el corte, no 0/0")
    assert len(filas(factory, "upstream_error")) == 0, (
        "cortó el cliente, no el destino: NO puede salir `upstream_error`")
    assert [e["status"] for e in eventos_de_vitrina] == [gateway.STATUS_PASSTHROUGH_CANCELADO]
