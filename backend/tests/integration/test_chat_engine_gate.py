"""El chat rechaza en ADMISIÓN cuando el motor está a capacidad (nodo C1).

El incidente de la sede (30-jul) no fue "el chat lento": fue el producto entero colgado. Cada
chat en vuelo retiene su conexión Postgres durante todo el `await` al motor (el único commit
está DESPUÉS), así que con suficientes pedidos apilados detrás de un modelo local que serializa
generaciones se agota el pool (10+20) y el `acquire` síncrono congela el event loop del worker.
A partir de ahí no contesta ni el login. Nadie rechazaba: todos entraban a esperar.

Lo que se fija acá es el COMPORTAMIENTO observable del fix, no su implementación:

* con el tope lleno, el pedido que sobra recibe un **503 rápido** —muchísimo antes del timeout
  del motor—, y con el copy honesto (se dice que no se encoló, no se disfraza de error del
  modelo);
* el rechazo es **auditado**: UNA fila durable por pedido rechazado, escrita ANTES de responder;
* esa fila **NO cuenta como bloqueo de política** (`LIKE 'blocked%'`): ninguna capa lo impidió,
  y contarlo ahí le mentiría al officer sobre cuántos intentos se bloquearon;
* el evento de vitrina se publica igual (best-effort, junto a la fila);
* contrato de wire para el harness de carga: `X-Basa-Rejected: saturated` + `code` en el body;
* el turno se libera al terminar: el rechazo es transitorio, no una degradación permanente.

**Por qué httpx/ASGI y no `TestClient`**: la concurrencia es el sujeto del test. Un `TestClient`
sin entrar como context manager abre un portal —y un event loop— por request, así que dos
requests "concurrentes" correrían en loops distintos y el semáforo del proceso no vería
concurrencia ninguna. Con `ASGITransport` los dos pedidos viven en el MISMO loop, que es lo que
pasa de verdad en un worker uvicorn.
"""
import asyncio
import sys
from pathlib import Path

import httpx
import pytest

_TESTS = Path(__file__).resolve().parent.parent
for _dir in (_TESTS, _TESTS / "integration"):
    if str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))

from migration_harness import require_postgres  # noqa: E402
from seat_gate_harness import admin_headers, build_app_client  # noqa: E402

require_postgres()

DB = "basa_test_chat_engine_gate"
CHAT = "/api/v1/chat/completions"
MODELO = "ollama-qwen3-4b"
SIN_PII = "Resumime en una línea qué hace este servicio."

SATURADO = "rejected_saturated"
# Queue-timeout de la suite: corto para que el test no dure, pero MUY por encima del tiempo que
# tarda de verdad un rechazo — si el 503 tardara más que esto, el bug seguiría vivo.
QUEUE_TIMEOUT = 0.25


# ── Doble del motor: lento y controlado ───────────────────────────────────────────


class _MotorLento:
    """Se queda dentro del `await` hasta que el test lo suelta — el modelo local que tarda.

    `en_vuelo` es la evidencia del tope: con cap=1 nunca puede pasar de 1, pase lo que pase
    con los pedidos de afuera.
    """

    def __init__(self):
        self.primera = asyncio.Event()
        self.soltar = asyncio.Event()
        self.en_vuelo = 0
        self.max_en_vuelo = 0
        self.posts = []

    def httpx(self):
        motor = self

        class _Respuesta:
            status_code = 200
            text = "ok"
            headers = {"x-litellm-response-cost": "0.00012"}

            @staticmethod
            def json():
                return {"choices": [{"message": {"content": "listo"}}],
                        "usage": {"prompt_tokens": 12, "completion_tokens": 3}}

        class _Cliente:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_exc):
                return False

            async def post(self, url, *_args, **_kwargs):
                motor.posts.append(url)
                motor.en_vuelo += 1
                motor.max_en_vuelo = max(motor.max_en_vuelo, motor.en_vuelo)
                motor.primera.set()
                try:
                    await motor.soltar.wait()
                finally:
                    motor.en_vuelo -= 1
                return _Respuesta()

        class _Httpx:
            @staticmethod
            def AsyncClient(*_args, **_kwargs):  # noqa: N802 — espeja el nombre real
                return _Cliente()

        return _Httpx


# ── Fixtures ──────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def harness():
    client, factory, cleanup = build_app_client(DB)
    client.headers.update(admin_headers(client))
    yield client, factory
    cleanup()


@pytest.fixture
def motor(monkeypatch):
    from src.api import chat
    lento = _MotorLento()
    monkeypatch.setattr(chat, "httpx", lento.httpx())
    return lento


@pytest.fixture
def gate_de_uno(monkeypatch):
    """Tope 1 y espera corta: el escenario de la sede en miniatura.

    El semáforo se resetea para que se reconstruya con el tope parcheado **en el loop del
    test**; al salir se vuelve a resetear para no dejarle a nadie un semáforo de 1.
    """
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
    """Espía del serializador del evento efímero (el chat lo delega al plano gateway)."""
    from src.api import gateway
    capturados = []
    real = gateway._publish_monitor

    def _espia(ident, tool, model, estado, masked_entities, masked_preview, **kwargs):
        capturados.append({"status": estado, "preview": masked_preview})
        return real(ident, tool, model, estado, masked_entities, masked_preview, **kwargs)

    monkeypatch.setattr(gateway, "_publish_monitor", _espia)
    return capturados


# ── Helpers ───────────────────────────────────────────────────────────────────────


def _cliente_async(client):
    """Cliente HTTP async sobre la MISMA app (y el mismo override de `get_db`) que el
    `TestClient` del harness, para que los pedidos concurrentes compartan event loop."""
    from src.main import app
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                             base_url="http://test", headers=dict(client.headers))


def calentar_catalogo(client, motor):
    """Primer pedido, síncrono: siembra los 9 guardianes (el seed re-siembra si hay menos).
    El motor se suelta antes para que este pedido no espere a nadie."""
    motor.soltar.set()
    respuesta = client.post(CHAT, json={"message": SIN_PII, "model": MODELO})
    assert respuesta.status_code == 200, respuesta.text
    motor.soltar.clear()
    motor.primera.clear()
    motor.posts.clear()


def filas(factory, estado):
    from src.models.audit import AuditLog
    db = factory()
    try:
        return [{"compliance_status": f.compliance_status, "model": f.model,
                 "prompt_tokens": f.prompt_tokens, "completion_tokens": f.completion_tokens,
                 "cost_usd": float(f.cost_usd or 0), "user_id": f.user_id,
                 "tenant_id": f.tenant_id, "blocked_by_layer": f.blocked_by_layer,
                 "latency_ms": f.latency_ms}
                for f in db.query(AuditLog).filter(AuditLog.compliance_status == estado).all()]
    finally:
        db.close()


def filas_estilo_bloqueo(factory):
    """El filtro CANÓNICO de compliance. Un rechazo por capacidad NO puede aparecer acá."""
    from src.models.audit import AuditLog
    db = factory()
    try:
        return [f.compliance_status for f in db.query(AuditLog)
                .filter(AuditLog.compliance_status.like("blocked%")).all()]
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


# ── El test que resume el nodo C1 ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_con_el_motor_ocupado_el_segundo_pedido_recibe_503_rapido_y_auditado(
        harness, motor, gate_de_uno, eventos_de_vitrina):
    """El caso de la sede, con cap=1: uno adentro, el que sobra NO espera 150 s — rebota.

    Y rebota dejando rastro: fila durable primero, vitrina después, respuesta al final.
    """
    client, factory = harness
    calentar_catalogo(client, motor)
    borrar_filas(factory)

    async with _cliente_async(client) as ac:
        primera = asyncio.create_task(ac.post(CHAT, json={"message": SIN_PII, "model": MODELO}))
        # Sin esto habría carrera: el segundo pedido podría llegar antes que el primero tomara
        # su turno, y el test mediría otra cosa.
        await asyncio.wait_for(motor.primera.wait(), timeout=10)

        inicio = asyncio.get_running_loop().time()
        segunda = await ac.post(CHAT, json={"message": SIN_PII, "model": MODELO})
        tardanza = asyncio.get_running_loop().time() - inicio

        assert segunda.status_code == 503, segunda.text
        # "Rápido" con criterio: del orden del queue-timeout, no del timeout del motor (60 s de
        # default, 150 s en la sede). Ese es literalmente el punto del fix.
        assert tardanza < 5.0, f"el rechazo tardó {tardanza:.2f}s — tiene que ser inmediato"

        cuerpo = segunda.json()["detail"]
        assert cuerpo["code"] == SATURADO, cuerpo
        assert "capacidad" in cuerpo["message"].lower()
        assert "no se encoló" in cuerpo["message"], (
            "el copy tiene que decir la verdad: el pedido NO quedó en cola esperando")
        # Contrato de wire del harness: un 503 de Caddy/proxy se ve igual desde afuera.
        assert segunda.headers.get("X-Basa-Rejected") == "saturated"
        assert segunda.headers.get("Retry-After") == "5"

        # La fila durable ya existe ANTES de que el pedido de adentro termine: el registro no
        # espera a nadie.
        rechazos = filas(factory, SATURADO)
        assert len(rechazos) == 1, f"una fila por rechazo, quedaron {len(rechazos)}"
        assert rechazos[0]["model"] == MODELO, "la fila dice a qué modelo iba el pedido"
        assert rechazos[0]["prompt_tokens"] == 0 and rechazos[0]["completion_tokens"] == 0
        assert rechazos[0]["cost_usd"] == 0.0, "no se consumió proveedor"
        assert rechazos[0]["user_id"] is not None, "sin atribución el registro no sirve"
        assert rechazos[0]["tenant_id"] is not None
        assert rechazos[0]["blocked_by_layer"] is None, (
            "ninguna capa bloqueó nada — inventar una falsearía la atribución")

        motor.soltar.set()
        respuesta_ok = await asyncio.wait_for(primera, timeout=10)

    assert respuesta_ok.status_code == 200, respuesta_ok.text
    assert motor.max_en_vuelo == 1, (
        f"el tope no acotó nada: hubo {motor.max_en_vuelo} pedidos dentro del motor a la vez")
    assert len(motor.posts) == 1, "el pedido rechazado NO puede haber llegado al motor"
    # `in` y no `[-1]`: el pedido que sí se sirvió publica su evento DESPUÉS del rechazo (se
    # soltó al final), así que el último evento de la vitrina es el éxito.
    assert SATURADO in [e["status"] for e in eventos_de_vitrina], (
        "un rechazo invisible en la vitrina es un rechazo que el operador no puede diagnosticar")


@pytest.mark.asyncio
async def test_el_rechazo_por_capacidad_no_cuenta_como_bloqueo_de_politica(
        harness, motor, gate_de_uno):
    """`rejected_saturated` no matchea `LIKE 'blocked%'`, y eso es load-bearing.

    Ese filtro es el canon de compliance (la vitrina, el dashboard y los tests de la 031 lo
    usan) y significa «el firewall impidió esto por política». Un rechazo por capacidad no lo
    impidió ninguna capa: contarlo ahí infla los bloqueos con incidentes de capacidad y le
    miente al officer sobre qué pasó en su instalación.
    """
    client, factory = harness
    calentar_catalogo(client, motor)
    borrar_filas(factory)

    async with _cliente_async(client) as ac:
        primera = asyncio.create_task(ac.post(CHAT, json={"message": SIN_PII, "model": MODELO}))
        await asyncio.wait_for(motor.primera.wait(), timeout=10)
        assert (await ac.post(CHAT, json={"message": SIN_PII, "model": MODELO})).status_code == 503
        motor.soltar.set()
        await asyncio.wait_for(primera, timeout=10)

    assert filas(factory, SATURADO), "el escenario no llegó a escribir la fila del rechazo"
    assert filas_estilo_bloqueo(factory) == [], (
        "el rechazo por capacidad entró al filtro canónico de bloqueos de política")


@pytest.mark.asyncio
async def test_el_turno_se_devuelve_y_el_siguiente_pedido_pasa(harness, motor, gate_de_uno):
    """La saturación es transitoria. Si el turno se filtrara en algún camino, el tope bajaría
    solo hasta reiniciar el worker: el chat quedaría muerto para siempre después de un pico."""
    client, _ = harness
    calentar_catalogo(client, motor)

    async with _cliente_async(client) as ac:
        primera = asyncio.create_task(ac.post(CHAT, json={"message": SIN_PII, "model": MODELO}))
        await asyncio.wait_for(motor.primera.wait(), timeout=10)
        assert (await ac.post(CHAT, json={"message": SIN_PII, "model": MODELO})).status_code == 503
        motor.soltar.set()
        assert (await asyncio.wait_for(primera, timeout=10)).status_code == 200

        # El motor ya está libre: el siguiente pedido tiene que entrar como si nada.
        tercera = await ac.post(CHAT, json={"message": SIN_PII, "model": MODELO})

    assert tercera.status_code == 200, tercera.text


@pytest.mark.asyncio
async def test_sin_saturacion_el_chat_no_cambia_en_nada(harness, motor, gate_de_uno):
    """Contracara obligatoria: el tope no puede cobrarle nada al camino feliz. Con el motor
    libre, un pedido normal responde 200 y NO deja fila de rechazo."""
    client, factory = harness
    calentar_catalogo(client, motor)
    borrar_filas(factory)
    motor.soltar.set()

    async with _cliente_async(client) as ac:
        respuesta = await ac.post(CHAT, json={"message": SIN_PII, "model": MODELO})

    assert respuesta.status_code == 200, respuesta.text
    assert filas(factory, SATURADO) == []
