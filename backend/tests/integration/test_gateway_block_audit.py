"""Auditoría durable del plano `/gw` passthrough (spec 031, T006 — US1/US2).

El passthrough era el ÚNICO plano que ya escribía fila al bloquear
(`gateway.py`, camino `block_reason`)… y esa fila pasaba por un `except Exception` con
`logger.warning("audit log falló (no fatal)")`. O sea: con la base pestañeando, el único
registro durable de «se intentó y se impidió» desaparecía y nadie se enteraba. Lo que se
fija acá es el comportamiento nuevo, no la implementación:

1. **Un fallo transitorio de escritura NO cuesta la fila** (D5): el reintento acotado del
   escritor la absorbe, y deja UNA fila, no dos — para un producto de compliance una fila
   duplicada es tan mala como la que falta.
2. **`audit_fail=closed` corta ANTES del proveedor** (FR-005, literal): si la base de
   auditoría no responde, el pedido no sale del gateway — ni por passthrough ni por byok— y
   el cliente recibe un 503 honesto en vez de una respuesta que nadie va a poder registrar.
   Se verifica con un doble de `httpx` que CUENTA llamadas: cero.
3. **Un bloqueo que no se pudo registrar no se devuelve como bloqueo normal en `closed`**
   (US1 AC4): «se bloqueó y no quedó nada» deja de ser silencioso.
4. **En `open` el tráfico no se rompe** (default del piloto): el mismo fallo total de
   escritura devuelve el rechazo de siempre y la pérdida queda CONTADA una sola vez.

El proveedor y el motor se doblan a nivel del namespace de `gateway`: lo que se mide es
qué quedó escrito y a quién se llamó, no que haya un modelo levantado.
"""
import json
import sys
from pathlib import Path

import pytest
from sqlalchemy.exc import OperationalError

_TESTS = Path(__file__).resolve().parent.parent
for _dir in (_TESTS, _TESTS / "integration"):
    if str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))

from migration_harness import require_postgres  # noqa: E402
from seat_gate_harness import build_app_client  # noqa: E402

require_postgres()

DB = "basa_test_gateway_block_audit"
GW = "/api/v1/gw/v1/messages"

# Dispara `SECRET_PATTERNS["OpenAI API Key"]` (`sk-` + 10+ alfanuméricos) ⇒ bloqueo
# `blocked_secret` por la capa `secret_detection`, sin depender del analizador NLP ni de
# ninguna lista del demo: es regex pura de la librería compartida.
SECRETO = "sk-ABCdefghij0123456789"
CUERPO_BLOQUEADO = {"model": "claude-3-5-sonnet-20241022",
                    "messages": [{"role": "user", "content": f"la clave es {SECRETO}"}]}
CUERPO_LIMPIO = {"model": "claude-3-5-sonnet-20241022",
                 "messages": [{"role": "user", "content": "resumime esto en una línea"}]}


# ── Dobles ────────────────────────────────────────────────────────────────────────


class _RespuestaFalsa:
    status_code = 200
    headers = {"content-type": "application/json"}
    content = json.dumps({"content": [{"type": "text", "text": "ok"}],
                          "usage": {"input_tokens": 3, "output_tokens": 2}}).encode()

    def json(self):
        return json.loads(self.content)


class _ClienteFalso:
    def __init__(self, registro):
        self._registro = registro

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    async def post(self, url, **_kwargs):
        self._registro.append(url)
        return _RespuestaFalsa()


class _HttpxEspia:
    """Doble del módulo `httpx` que usa el gateway: cuenta a quién se llamó.

    Es el instrumento del invariante caro de la US2: en `closed` con la auditoría caída,
    `llamadas` tiene que quedar VACÍA — el sentido del modo es no gastar dinero en tráfico
    inauditable, y eso sólo se puede afirmar contando salidas, no leyendo el código.
    """

    def __init__(self):
        self.llamadas = []

    def AsyncClient(self, *_args, **_kwargs):  # noqa: N802 — espeja el nombre real
        return _ClienteFalso(self.llamadas)


class _SesionQueFallaAlCommitear:
    """Sesión real envuelta: falla los primeros N `commit()` y después delega todo.

    Simula el fallo REAL que motiva la spec (la base se cae en el momento de escribir),
    no un mock del escritor: el `add`, el `rollback` y el `commit` bueno son los de
    SQLAlchemy, así que el reintento se ejerce contra una sesión de verdad.
    """

    def __init__(self, real, estado):
        object.__setattr__(self, "_real", real)
        object.__setattr__(self, "_estado", estado)

    def commit(self):
        if self._estado["restantes"] > 0:
            self._estado["restantes"] -= 1
            self._estado["fallos"] += 1
            raise OperationalError("COMMIT", {},
                                   Exception("server closed the connection unexpectedly"))
        return self._real.commit()

    def __getattr__(self, nombre):
        return getattr(self._real, nombre)


class _SesionSinBase:
    """Sesión cuyo `execute` revienta: es lo que ve `audit_writable` con la base caída.

    `query()` sigue funcionando a propósito — la atribución del gateway abre su propia
    sesión con la misma factory y no tiene por qué participar del escenario.
    """

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
    """`gateway` abre sus PROPIAS sesiones (`SessionLocal`), no la del override de
    `get_db`: este plano se autentica con el OAuth del cliente, no con una sesión de
    request. Sin este patch los tests escribirían en la base del compose."""
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
def proveedor(monkeypatch):
    from src.api import gateway
    espia = _HttpxEspia()
    monkeypatch.setattr(gateway, "httpx", espia)
    return espia


@pytest.fixture
def perdidas(monkeypatch):
    """Espía del contador de pérdidas en SUS DOS puntos de llamada (el escritor y el
    envoltorio del gateway). Que sea el mismo espía es parte del test: una pérdida tiene
    que contarse UNA vez, no una por capa que la vea pasar."""
    from src.api import gateway
    from src.services import audit_service
    registro = []
    monkeypatch.setattr(audit_service, "record_audit_loss",
                        lambda reason="": registro.append(reason))
    monkeypatch.setattr(gateway, "record_audit_loss",
                        lambda reason="": registro.append(reason))
    return registro


@pytest.fixture
def limpiar_filas(harness):
    """Cada test cuenta filas propias: el módulo comparte base."""
    _, factory = harness
    from src.models.audit import AuditLog
    db = factory()
    try:
        db.query(AuditLog).delete()
        db.commit()
    finally:
        db.close()
    yield


# ── Helpers ───────────────────────────────────────────────────────────────────────


def filas_de_bloqueo(factory):
    from src.models.audit import AuditLog
    db = factory()
    try:
        return [{"compliance_status": f.compliance_status,
                 "blocked_by_layer": f.blocked_by_layer,
                 "model": f.model,
                 "prompt_tokens": f.prompt_tokens,
                 "completion_tokens": f.completion_tokens,
                 "masked_entities": f.masked_entities}
                for f in db.query(AuditLog)
                .filter(AuditLog.compliance_status.like("blocked%")).all()]
    finally:
        db.close()


def con_fallos(factory, veces):
    """Factory que devuelve sesiones que fallan `veces` commits."""
    estado = {"restantes": veces, "fallos": 0}
    return (lambda: _SesionQueFallaAlCommitear(factory(), estado)), estado


# ── 1) El transitorio no cuesta la fila ───────────────────────────────────────────


def test_bloqueo_con_un_fallo_transitorio_deja_la_fila_igual(harness, monkeypatch,
                                                             limpiar_filas):
    """Un `commit` que falla y a la segunda anda ⇒ la fila de bloqueo existe. Antes, el
    primer fallo era definitivo: `logger.warning("no fatal")` y a otra cosa."""
    client, factory = harness
    from src.api import gateway
    fallona, estado = con_fallos(factory, 1)
    monkeypatch.setattr(gateway, "SessionLocal", fallona)

    respuesta = client.post(GW, json=CUERPO_BLOQUEADO)

    assert respuesta.status_code == 400, respuesta.text
    assert estado["fallos"] == 1, "el escenario no llegó a inyectar el fallo"
    filas = filas_de_bloqueo(factory)
    assert len(filas) == 1, f"el reintento tenía que dejar UNA fila, quedaron {len(filas)}"
    assert filas[0]["compliance_status"] == "blocked_secret"
    assert filas[0]["blocked_by_layer"] == "secret_detection"
    # Contrato §Fila de bloqueo: el intento impedido no consumió tokens.
    assert filas[0]["prompt_tokens"] == 0 and filas[0]["completion_tokens"] == 0
    # C1: ni rastro del secreto en la fila (el bloqueo ocurre con el body todavía crudo).
    assert SECRETO not in json.dumps(filas[0], default=str)


def test_bloqueo_sin_fallos_sigue_dejando_una_sola_fila(harness, limpiar_filas):
    """Contracara: el camino sano no gana filas por el reintento nuevo."""
    client, factory = harness
    assert client.post(GW, json=CUERPO_BLOQUEADO).status_code == 400
    assert len(filas_de_bloqueo(factory)) == 1


# ── 2) `closed` corta ANTES del proveedor ─────────────────────────────────────────


def test_closed_con_auditoria_caida_rechaza_sin_llamar_al_proveedor(
        harness, monkeypatch, proveedor):
    """SC-002, mitad `closed`: 503 honesto y CERO llamadas al proveedor."""
    client, factory = harness
    from src.api import gateway
    monkeypatch.setenv("BASA_AUDIT_FAIL", "closed")
    monkeypatch.setattr(gateway, "SessionLocal", lambda: _SesionSinBase(factory()))

    respuesta = client.post(GW, json=CUERPO_LIMPIO)

    assert respuesta.status_code == 503, respuesta.text
    assert "audit_fail=closed" in respuesta.json()["error"]["message"]
    assert proveedor.llamadas == [], "en `closed` no se gasta dinero en tráfico inauditable"


def test_closed_con_auditoria_caida_no_reenvia_al_motor_en_byok(
        harness, monkeypatch, proveedor):
    """Mismo corte por la ruta byok: el pedido no llega ni al motor (que además lo
    auditaría por el plano interno, contra la misma base que acaba de no responder)."""
    client, factory = harness
    from src.api import gateway
    monkeypatch.setenv("BASA_AUDIT_FAIL", "closed")
    monkeypatch.setattr(gateway, "SessionLocal", lambda: _SesionSinBase(factory()))

    respuesta = client.post(GW, json=CUERPO_LIMPIO,
                            headers={"X-Basa-Upstream": "byok",
                                     "X-Basa-Key": "sk-basa-inexistente-pero-con-forma"})

    assert respuesta.status_code == 503, respuesta.text
    assert proveedor.llamadas == []


def test_open_con_la_escritura_rota_sigue_sirviendo_y_cuenta(harness, monkeypatch,
                                                             proveedor, perdidas,
                                                             limpiar_filas):
    """SC-002, mitad `open` (default del piloto): con la escritura rota el tráfico NO se
    rompe —la petición se sirve— pero la pérdida queda contada. Continuidad y silencio no
    son la misma cosa: esto es lo primero y la 031 existe por lo segundo."""
    client, factory = harness
    from src.api import gateway
    monkeypatch.setenv("BASA_AUDIT_FAIL", "open")
    fallona, _estado = con_fallos(factory, 99)
    monkeypatch.setattr(gateway, "SessionLocal", fallona)

    respuesta = client.post(GW, json=CUERPO_LIMPIO)

    assert respuesta.status_code == 200, respuesta.text
    assert len(proveedor.llamadas) == 1, "en `open` el pre-check no puede cortar el tráfico"
    assert len(perdidas) == 1


# ── 3) Un bloqueo no registrado no se disfraza de bloqueo normal (closed) ─────────


def test_closed_bloqueo_que_no_pudo_registrarse_responde_503(harness, monkeypatch,
                                                             perdidas, limpiar_filas):
    """US1 AC4: con la base caída, «se bloqueó y no quedó nada» no puede salir como el 400
    de siempre — el cliente (y el operador) se enteran."""
    client, factory = harness
    from src.api import gateway
    monkeypatch.setenv("BASA_AUDIT_FAIL", "closed")
    fallona, estado = con_fallos(factory, 99)   # el escritor agota su presupuesto
    monkeypatch.setattr(gateway, "SessionLocal", fallona)

    respuesta = client.post(GW, json=CUERPO_BLOQUEADO)

    assert respuesta.status_code == 503, respuesta.text
    assert "audit_fail=closed" in respuesta.json()["error"]["message"]
    assert estado["fallos"] == 3, "presupuesto D5: 1 intento + 2 reintentos"
    assert filas_de_bloqueo(factory) == []
    assert len(perdidas) == 1, f"la pérdida se cuenta UNA vez, no una por capa: {perdidas}"


# ── 4) `open`: continuidad, con la pérdida contada ────────────────────────────────


def test_open_bloqueo_que_no_pudo_registrarse_responde_el_bloqueo_y_cuenta_la_perdida(
        harness, monkeypatch, perdidas, limpiar_filas):
    """El default del piloto: el rechazo llega igual (el bloqueo SÍ ocurrió) y la pérdida
    queda contada para el health y el banner de Logs. Nunca las dos cosas en silencio."""
    client, factory = harness
    from src.api import gateway
    monkeypatch.setenv("BASA_AUDIT_FAIL", "open")
    fallona, _estado = con_fallos(factory, 99)
    monkeypatch.setattr(gateway, "SessionLocal", fallona)

    respuesta = client.post(GW, json=CUERPO_BLOQUEADO)

    assert respuesta.status_code == 400, respuesta.text
    assert "material secreto" in respuesta.json()["error"]["message"]
    assert filas_de_bloqueo(factory) == []
    assert len(perdidas) == 1
