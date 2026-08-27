"""`audit_fail=policy` en el **streaming** de `/gw` (spec 038, T007) — dónde se decide el corte.

`test_gateway_audit_policy.py` fija la matriz por riesgo en el camino no-stream. Este archivo
fija lo que el gate cross-familia de #334 marcó como restricción de diseño para T007, y que es
lo ÚNICO que distingue a este plano del chat: **`gateway.py` CONSTRUYE respuestas de streaming
—2, medidas por AST: las dos `_StreamConTurno` (subclase de `StreamingResponse`), la del
passthrough y la del byok— y `chat.py` construye 0**, así que una `HTTPException` posterior al
primer chunk no rinde un 503 — corta la conexión a mitad con la generación del proveedor ya
pagada.

El número decía **6** hasta `36c3db0` y era un `grep` de la PALABRA: contaba el import, la línea
de la clase y los comentarios que hablan de ella. La conclusión no cambia (2 ≠ 0 igual que 6 ≠ 0)
y por eso sobrevivió a dos barridos: **un conteo que no altera la decisión es el que menos se
audita**. Este docstring fue el último lector vivo del número viejo — se escribió ANTES de la
corrección, que es exactamente lo que un barrido "por los lugares que me acuerdo" no encuentra.

Las dos mitades del invariante, una por test:

1. **Riesgo alto ⇒ se corta ANTES de abrir el stream.** No hay respuesta parcial que rendir
   porque no se llegó a contactar al proveedor. Es el mismo pre-check de FR-005, ahora
   gobernado por la matriz.
2. **Riesgo bajo ⇒ el stream se entrega ENTERO aunque la fila final falle.** Ésta es la
   anti-regresión de verdad: el día que alguien "unifique" este plano con el patrón del chat y
   envuelva la auditoría post-stream en un `raise HTTPException(503)`, este test rompe. Hoy la
   fila diferida corre en el `finally` de `_StreamConTurno.__call__` —después de que starlette
   entregó los bytes—, así que ahí no hay 503 posible: sólo absorber y contar.

**Por qué cada test espía `audit_exige_registro` en vez de confiar en el 503/200 solo.** El
tráfico anónimo de `/gw` resuelve riesgo `None` **por construcción** y `None` también corta: un
test de riesgo alto que rompiera la atribución pasaría igual, por el motivo equivocado. El espía
—que envuelve la función real, no la reemplaza— afirma **qué nivel concreto** llegó a la matriz,
que es lo que prueba que la cascada `llave → usuario → equipo` produjo el dato de verdad.
"""
import asyncio
import json
import sys
from pathlib import Path

import pytest
from sqlalchemy.exc import OperationalError
from starlette.requests import Request

_TESTS = Path(__file__).resolve().parent.parent
for _dir in (_TESTS, _TESTS / "integration"):
    if str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))

from migration_harness import require_postgres  # noqa: E402
from seat_gate_harness import build_app_client  # noqa: E402

require_postgres()

DB = "basa_test_gateway_audit_stream"

CLAVE = "sk-basa-test-038-t007-stream"
CUERPO = {"model": "claude-3-5-sonnet-20241022",
          "messages": [{"role": "user", "content": "resumime esto en una línea"}]}


# ── Dobles del upstream en modo stream ────────────────────────────────────────────


class _RespuestaStream:
    """Upstream SSE que drena entero y sin esperas. Mismo shape que el de
    `test_gw_engine_gate.py`: `status_code`/`headers`/`aiter_raw`/`aread`/`aclose`."""

    status_code = 200
    headers = {"content-type": "text/event-stream"}

    def __init__(self):
        self.cerrado = False
        self.arranco = False

    async def aiter_raw(self):
        self.arranco = True
        yield b"data: {\"type\":\"message_start\"}\n\n"
        yield b"data: {\"type\":\"message_stop\"}\n\n"

    async def aread(self):
        return b""

    async def aclose(self):
        self.cerrado = True


class _ClienteStream:
    def __init__(self, registro):
        self._registro = registro
        self.cerrado = False

    def build_request(self, *_args, **_kwargs):
        return object()

    async def send(self, _req, **_kwargs):
        up = _RespuestaStream()
        self._registro.append(up)
        return up

    async def aclose(self):
        self.cerrado = True


class _HttpxStream:
    """Doble del módulo `httpx` que usa el gateway, en su camino de streaming.

    `streams` es el instrumento del test 1: si el corte ocurrió ANTES del primer chunk, esta
    lista queda VACÍA — el proveedor no se contactó y no hay generación que pagar. Eso no se
    puede afirmar leyendo el código, sólo contando salidas.
    """

    def __init__(self):
        self.streams = []
        self.clientes = []

    def AsyncClient(self, *_args, **_kwargs):  # noqa: N802 — espeja el nombre real
        cliente = _ClienteStream(self.streams)
        self.clientes.append(cliente)
        return cliente

    class Timeout:  # `httpx.Timeout(...)` se construye en el camino de stream
        def __init__(self, *_args, **_kwargs):
            pass


class _SesionQueNoCommitea:
    """Sesión real envuelta cuyo `commit()` falla SIEMPRE: es la base que se cae justo cuando
    hay que escribir. El `add`, el `rollback` y las queries son los de SQLAlchemy, así que el
    reintento acotado del escritor se ejerce contra una sesión de verdad."""

    def __init__(self, real):
        object.__setattr__(self, "_real", real)

    def commit(self):
        raise OperationalError("COMMIT", {},
                               Exception("server closed the connection unexpectedly"))

    def __getattr__(self, nombre):
        return getattr(self._real, nombre)


class _SesionSinBase:
    """Sesión cuyo `execute` revienta: es lo que ve `audit_writable` con la base caída."""

    def __init__(self, real):
        object.__setattr__(self, "_real", real)

    def execute(self, *_args, **_kwargs):
        raise OperationalError("SELECT 1", {}, Exception("could not connect to server"))

    def __getattr__(self, nombre):
        return getattr(self._real, nombre)


# ── Fixtures ──────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def harness():
    client, factory, cleanup = build_app_client(DB)
    yield client, factory
    cleanup()


@pytest.fixture(autouse=True)
def sesion_del_gateway(harness, monkeypatch):
    """`gateway` abre sus PROPIAS sesiones (`SessionLocal`), no la del override de `get_db`:
    este plano se autentica con el OAuth del cliente, no con una sesión de request."""
    _, factory = harness
    from src.api import gateway
    monkeypatch.setattr(gateway, "SessionLocal", factory)
    return factory


@pytest.fixture(autouse=True)
def sin_esperas(monkeypatch):
    """El backoff del escritor (0,2 s + 0,5 s) es presupuesto de producción, no de suite."""
    from src.services import audit_service
    monkeypatch.setattr(audit_service, "_wait", lambda _s: None)


@pytest.fixture(autouse=True)
def modo_policy_por_defecto(monkeypatch):
    """Env AUSENTE — el modo efectivo desde D1 es `policy`, el default de la 038."""
    from src.services import audit_service
    monkeypatch.delenv(audit_service.AUDIT_FAIL_ENV, raising=False)


@pytest.fixture(autouse=True)
def proveedor(monkeypatch):
    from src.api import gateway
    espia = _HttpxStream()
    monkeypatch.setattr(gateway, "httpx", espia)
    return espia


@pytest.fixture
def perdidas(monkeypatch):
    """Espía del contador de pérdidas en SUS DOS puntos de llamada (el escritor y el
    envoltorio del gateway). Que sea el mismo espía es parte del test: una pérdida se cuenta
    UNA vez, no una por capa que la vea pasar."""
    from src.api import gateway
    from src.services import audit_service
    registro = []
    monkeypatch.setattr(audit_service, "record_audit_loss",
                        lambda reason="": registro.append(reason))
    monkeypatch.setattr(gateway, "record_audit_loss",
                        lambda reason="": registro.append(reason))
    return registro


@pytest.fixture
def riesgo_visto(monkeypatch):
    """Envuelve —no reemplaza— `audit_exige_registro` y anota QUÉ nivel le llegó.

    Es el brazo que impide el falso positivo de este archivo: en `/gw` el riesgo `None` del
    tráfico anónimo corta igual que `annex3`, así que un 503 por sí solo no distingue «la
    matriz recibió un riesgo alto» de «la atribución se rompió y quedó anónimo». Envolver la
    función real y no mockearla mantiene la decisión de producción intacta."""
    from src.api import gateway
    real = gateway.audit_exige_registro
    vistos = []

    def _espia(risk_level):
        vistos.append(risk_level)
        return real(risk_level)

    monkeypatch.setattr(gateway, "audit_exige_registro", _espia)
    return vistos


@pytest.fixture
def identidad(harness):
    """Connection + usuario con `risk_level`, en la base del harness.

    `upstream_mode="byok"` sólo para ATRIBUIR: el ruteo lo decide `_detect_mode_and_key`
    mirando headers y URL, y `X-Basa-Key` está **excluido de ese scan a propósito**
    (`gateway.py`, docstring de esa función), así que el pedido sigue yendo por passthrough —
    que es el único camino de este plano con `StreamingResponse`. Una fila
    `subscription-passthrough` exigiría `oauth_credential_ref` (CHECK
    `ck_api_keys_subscription_oauth`) y acá no hay credencial que custodiar.
    """
    _, factory = harness
    from src.models.budget import APIKey
    from src.models.tenant import DEFAULT_TENANT_ID
    from src.models.user import User
    from src.services.key_material import hash_key

    def _alta(risk_level):
        db = factory()
        try:
            db.query(APIKey).filter(APIKey.key_hash == hash_key(CLAVE)).delete()
            db.query(User).filter(User.username == "usuario-038-t007").delete()
            db.commit()
            # `password_hash` (no `hashed_password`) y `role` NOT NULL con CHECK
            # `ck_users_role`: los nombres salen de `src/models/user.py`, no de la memoria.
            # `client_type` se deja en NULL a propósito — el CHECK
            # `ck_users_client_type_role` sólo lo permite con `role='client'` y acá no
            # aporta nada.
            usuario = User(username="usuario-038-t007",
                           email="usuario-038-t007@example.test",
                           password_hash="x", role="client", is_active=True,
                           tenant_id=DEFAULT_TENANT_ID, risk_level=risk_level)
            db.add(usuario)
            db.commit()
            db.refresh(usuario)
            db.add(APIKey(tenant_id=DEFAULT_TENANT_ID, key_hash=hash_key(CLAVE),
                          key_preview="sk-basa-…t007", name="conexión 038 T007",
                          is_active=True, tool_type="claude-code", upstream_mode="byok",
                          user_id=usuario.id))
            db.commit()
            # Releer: en #334 un UPDATE por sesión cruda "pasó" sin tocar ninguna fila bajo
            # RLS. Lo que vale es lo que la base devuelve, no lo que el ORM creyó escribir.
            releido = db.query(User).filter(User.username == "usuario-038-t007").first()
            assert releido is not None and releido.risk_level == risk_level, (
                f"el alta no persistió el riesgo: quedó {releido and releido.risk_level!r}")
        finally:
            db.close()

    return _alta


# ── Helpers ───────────────────────────────────────────────────────────────────────


def _peticion_stream():
    """`Request` de passthrough de suscripción CON `X-Basa-Key` y `stream: true`.

    El `Authorization: Bearer` es el OAuth de la suscripción (no lleva `sk-basa-…`), así que
    `_detect_mode_and_key` resuelve subscription-passthrough y no byok."""
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


async def _pedido_stream():
    """Invoca el endpoint DIRECTO (no por HTTP): el transporte ASGI de httpx bufferea la
    respuesta entera, así que por HTTP no se puede observar qué se entregó chunk a chunk —que
    es exactamente lo que este archivo mide."""
    from src.api import gateway
    return await gateway.gw_messages(
        _peticion_stream(), x_basa_key=CLAVE, x_basa_redact=None, x_basa_upstream=None)


def _scope_asgi():
    return {"type": "http", "http_version": "1.1", "method": "POST",
            "path": "/gw/v1/messages", "headers": []}


async def _drenar(respuesta):
    """Corre la respuesta ASGI hasta el final y devuelve los mensajes enviados al cliente.

    **`receive()` NO puede devolver `http.request` en loop**: `StreamingResponse` corre en
    paralelo un `listen_for_disconnect` que hace `await receive()` hasta ver un
    `http.disconnect`, así que un `receive` que contesta al toque lo deja girando para
    siempre y la corrida se cuelga (me pasó: 7 minutos hasta que la mató el reloj). El
    contrato real es el de un cliente que se va cuando la respuesta terminó: se espera al
    último `http.response.body` —el que viene sin `more_body`— y recién ahí se emite el
    `http.disconnect`.
    """
    enviados = []
    cuerpo_completo = asyncio.Event()

    async def send(mensaje):
        enviados.append(mensaje)
        if mensaje["type"] == "http.response.body" and not mensaje.get("more_body", False):
            cuerpo_completo.set()

    async def receive():
        await cuerpo_completo.wait()
        return {"type": "http.disconnect"}

    await asyncio.wait_for(respuesta(_scope_asgi(), receive, send), timeout=15)
    return enviados


def filas(factory):
    from src.models.audit import AuditLog
    db = factory()
    try:
        return db.query(AuditLog).count()
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


# ── 1) Riesgo alto: se corta ANTES de abrir el stream ─────────────────────────────


@pytest.mark.asyncio
async def test_el_stream_de_riesgo_alto_corta_antes_de_contactar_al_proveedor(
        harness, monkeypatch, proveedor, identidad, riesgo_visto):
    """`policy` + `high_risk_annex3` + base de auditoría caída + `stream: true` ⇒ 503 y CERO
    salidas al proveedor.

    Lo que fija: el punto de decisión de este plano es el pre-check, ANTES del primer byte. No
    es una preferencia de estilo — más adelante en el pedido ya no existe la opción de
    responder 503, sólo la de cortar una conexión a mitad."""
    from src.api import gateway
    _, factory = harness
    identidad("high_risk_annex3")
    monkeypatch.setattr(gateway, "SessionLocal", lambda: _SesionSinBase(factory()))

    respuesta = await _pedido_stream()

    assert riesgo_visto == ["high_risk_annex3"], (
        "la matriz tiene que haber recibido el riesgo RESUELTO; si vino `None` este test está "
        f"midiendo el corte del tráfico anónimo y no la cascada (vio: {riesgo_visto})")
    assert respuesta.status_code == 503, "el pedido de riesgo alto tiene que cortar"
    assert proveedor.streams == [], (
        "se abrió un stream contra el proveedor: el corte llegó DESPUÉS de empezar a gastar, "
        "que es justo lo que el pre-check existe para evitar (FR-005)")
    cuerpo = json.loads(bytes(respuesta.body))
    detalle = cuerpo["error"]["message"]
    assert "(audit_fail=policy)" in detalle, f"copy equivocado para el modo vigente: {detalle}"
    assert "(audit_fail=closed)" not in detalle, (
        "el copy de `closed` en una instalación que nunca seteó esa env manda al operador a "
        "buscar una variable que no existe")


# ── 2) Riesgo bajo: el stream se entrega ENTERO aunque la fila final falle ─────────


@pytest.mark.asyncio
async def test_la_fila_final_perdida_no_corta_el_stream_de_riesgo_bajo(
        harness, monkeypatch, proveedor, identidad, riesgo_visto, perdidas):
    """`policy` + `minimal` + escritor caído + `stream: true` ⇒ 200, el stream COMPLETO llega
    al cliente, cero filas, y la pérdida contada UNA vez.

    **Ésta es la anti-regresión del hallazgo que el gate de #334 anticipó para `/gw`.** La fila
    diferida corre en el `finally` de `_StreamConTurno.__call__`, o sea DESPUÉS de que
    starlette entregó los bytes: un `raise` ahí no rinde un 503, aborta la respuesta a mitad.
    Si alguien alinea este plano con el patrón del chat y envuelve esa escritura en una
    `HTTPException`, el `await` de `_drenar` levanta y este test rompe — que es exactamente el
    trabajo que tiene que hacer.

    El brazo del riesgo importa tanto como el del fallo: con `minimal` la instalación decidió
    que servir vale más que la fila (D2), así que el 200 es el comportamiento correcto y no una
    tolerancia accidental."""
    from src.api import gateway
    _, factory = harness
    identidad("minimal")
    borrar_filas(factory)
    monkeypatch.setattr(gateway, "SessionLocal", lambda: _SesionQueNoCommitea(factory()))

    respuesta = await _pedido_stream()
    assert riesgo_visto == ["minimal"], (
        f"la matriz tiene que haber recibido `minimal` resuelto por la cascada (vio: {riesgo_visto})")
    assert respuesta.status_code == 200, (
        "riesgo bajo con la auditoría caída se SIRVE: cortarlo sería aplicar la política de "
        "`closed` a una instalación que eligió `policy` (D2)")

    enviados = await _drenar(respuesta)

    tipos = [m["type"] for m in enviados]
    assert tipos[0] == "http.response.start", tipos
    cuerpos = [m for m in enviados if m["type"] == "http.response.body"]
    assert cuerpos, "no se entregó un solo byte al cliente"
    entregado = b"".join(m.get("body", b"") for m in cuerpos)
    assert b"message_start" in entregado and b"message_stop" in entregado, (
        "el stream llegó TRUNCADO: el fallo de la fila final cortó la respuesta a mitad — que "
        f"es exactamente lo que este plano no puede hacer. Entregado: {entregado!r}")
    assert proveedor.streams and proveedor.streams[0].arranco is True, (
        "el generador nunca arrancó: este test no está midiendo el camino post-stream")

    assert filas(factory) == 0, "el escenario es la fila que NO se pudo escribir"
    assert len(perdidas) == 1, (
        f"la pérdida se cuenta UNA vez, no una por capa que la vea pasar: {perdidas}")
