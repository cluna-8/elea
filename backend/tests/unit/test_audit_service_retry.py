"""Spec 031 T002 — el escritor de auditoría deja de fallar en silencio.

Cubre el núcleo D5 del contrato (§Contador de pérdidas) sin tocar Postgres ni Redis:
sesión falsa que falla N veces + Redis falso, así que el test mide EXACTAMENTE la
política (cuántos intentos, cuánto backoff, qué se cuenta, qué se propaga) y no la
disponibilidad del stack.

Lo que se protege acá es la promesa central del producto —«logueamos TODO»—: antes,
cualquier fallo de escritura dropeaba la fila y devolvía `None` que ningún caller miraba
(ya costó la pérdida total del rastro byok en el ensayo del piloto).
"""
import logging
import uuid
from datetime import datetime

import pytest

from src.services import audit_service
from src.services.audit_service import (
    AUDIT_RETRY_BACKOFFS_SECONDS,
    AuditService,
    AuditUnavailableError,
    REDIS_KEY_AUDIT_LAST_FAIL,
    REDIS_KEY_AUDIT_LOST,
    audit_fail_mode,
    audit_writable,
)


class _DBCaida(Exception):
    """Lo que ve el escritor cuando la base no está: cualquier excepción del driver."""


class _FakeSession:
    """Sesión mínima: cuenta commits/rollbacks y falla los primeros ``fallos`` commits."""

    def __init__(self, fallos: int = 0, dialecto: str = "", refresh_roto: bool = False):
        self.fallos_restantes = fallos
        self.dialecto = dialecto
        self.refresh_roto = refresh_roto
        self.commits = 0
        self.rollbacks = 0
        self.added = []
        self.sentencias = []

    # — camino de escritura —
    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        self.commits += 1
        if self.fallos_restantes > 0:
            self.fallos_restantes -= 1
            raise _DBCaida("commit falló: base de auditoría no disponible")

    def refresh(self, obj):
        if self.refresh_roto:
            raise _DBCaida("la conexión murió justo después del commit")
        obj.id = uuid.uuid4()

    def rollback(self):
        self.rollbacks += 1

    # — camino del probe —
    def execute(self, sentencia):
        self.sentencias.append(str(sentencia))
        if self.fallos_restantes > 0:
            self.fallos_restantes -= 1
            raise _DBCaida("SELECT 1 falló")
        return None

    def get_bind(self):
        if not self.dialecto:
            raise RuntimeError("sesión sin bind")
        return _FakeBind(self.dialecto)


class _FakeBind:
    def __init__(self, nombre):
        self.dialect = type("_D", (), {"name": nombre})()


class _FakeRedis:
    def __init__(self):
        self.incrs = []
        self.sets = {}

    def incr(self, key):
        self.incrs.append(key)
        return len(self.incrs)

    def set(self, key, value):
        self.sets[key] = value


@pytest.fixture
def redis_falso(monkeypatch):
    r = _FakeRedis()
    monkeypatch.setattr(audit_service, "get_redis", lambda: r)
    return r


@pytest.fixture
def esperas(monkeypatch):
    """Captura el backoff sin pagarlo: el test verifica el presupuesto, no lo sufre."""
    registradas = []
    monkeypatch.setattr(audit_service, "_wait", registradas.append)
    return registradas


@pytest.fixture
def logs_de_auditoria():
    """Handler propio sobre el logger del servicio, en vez de `caplog`.

    `caplog` captura desde el logger RAÍZ y depende de la config global de logging, que en
    la suite completa ya la fijó `src.main` (basicConfig) antes de que corran estos tests:
    el mismo assert pasaba en solitario y fallaba dentro de `-k audit`. Un handler pegado
    al logger concreto mide lo que el test dice medir, corra solo o acompañado.
    """
    logger = logging.getLogger("basa-secure-gateway.audit")
    mensajes = []

    class _Captura(logging.Handler):
        def emit(self, record):
            mensajes.append(record.getMessage())

    handler = _Captura(level=logging.DEBUG)
    nivel_previo = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    try:
        yield mensajes
    finally:
        logger.removeHandler(handler)
        logger.setLevel(nivel_previo)


@pytest.fixture(autouse=True)
def modo_open_por_defecto(monkeypatch):
    """La env es global al proceso: cada test parte de un estado conocido."""
    monkeypatch.delenv(audit_service.AUDIT_FAIL_ENV, raising=False)


def _escribir(db, **extra):
    """Llamada mínima con la firma pública intacta (los callers previos no cambian)."""
    kwargs = dict(
        db=db,
        model="gpt-4o",
        prompt_tokens=0,
        completion_tokens=0,
        cost_usd=0.0,
        pii_detected=False,
        masked_entities=[],
        compliance_status="blocked_prohibited",
        latency_ms=12,
    )
    kwargs.update(extra)
    return AuditService.log_transaction(**kwargs)


# --------------------------------------------------------------------------- #
# 1. Fallo transitorio absorbido: la fila se escribe y NO hay pérdida que contar
# --------------------------------------------------------------------------- #
def test_fallo_transitorio_se_absorbe_sin_perdida(redis_falso, esperas):
    db = _FakeSession(fallos=1)

    fila = _escribir(db)

    assert fila is not None, "el reintento tiene que absorber un fallo transitorio"
    assert db.commits == 2 and db.rollbacks == 1
    # Ni contador ni timestamp: un transitorio absorbido no es una pérdida.
    assert redis_falso.incrs == []
    assert redis_falso.sets == {}
    # Sólo se pagó el primer backoff.
    assert esperas == [AUDIT_RETRY_BACKOFFS_SECONDS[0]]


def test_camino_feliz_no_reintenta_ni_espera(redis_falso, esperas):
    db = _FakeSession(fallos=0)

    fila = _escribir(db)

    assert fila is not None
    assert db.commits == 1 and db.rollbacks == 0
    assert esperas == []
    assert redis_falso.incrs == []


def test_refresh_roto_tras_commit_no_duplica_la_fila(redis_falso, esperas):
    """Si la conexión muere DESPUÉS del commit, la fila ya es durable: reintentar
    escribiría un segundo registro del mismo evento. Auditoría duplicada es tan
    inaceptable como auditoría faltante — el conteo de bloqueos dejaría de ser un conteo."""
    db = _FakeSession(fallos=0, refresh_roto=True)

    fila = _escribir(db)

    assert fila is not None
    assert db.commits == 1, "un commit y sólo uno"
    assert len(db.added) == 1
    assert redis_falso.incrs == []  # no es una pérdida: la fila está


# --------------------------------------------------------------------------- #
# 2. Agotamiento del presupuesto: contador + timestamp (nunca silencio)
# --------------------------------------------------------------------------- #
def test_agotar_reintentos_cuenta_la_perdida_y_sella_el_timestamp(redis_falso, esperas):
    db = _FakeSession(fallos=99)  # la base no vuelve

    fila = _escribir(db)

    # `open` (default): el tráfico se sirve igual → el caller recibe None como siempre…
    assert fila is None
    # …pero la pérdida QUEDA REGISTRADA, que es lo que esta spec compra.
    assert redis_falso.incrs == [REDIS_KEY_AUDIT_LOST]
    marca = redis_falso.sets[REDIS_KEY_AUDIT_LAST_FAIL]
    assert datetime.fromisoformat(marca).tzinfo is not None, "el timestamp va en ISO con tz"

    # 3 intentos (1 + 2 reintentos) y un rollback por intento fallido.
    assert db.commits == 3 and db.rollbacks == 3


def test_presupuesto_de_reintentos_es_acotado_y_menor_a_1500ms(redis_falso, esperas):
    db = _FakeSession(fallos=99)

    _escribir(db)

    assert esperas == list(AUDIT_RETRY_BACKOFFS_SECONDS)
    assert sum(esperas) < 1.5, "el escritor no puede volverse un DoS interno (edge case anti-avalancha)"


def test_error_de_escritura_se_loguea_con_nivel_error(redis_falso, esperas, logs_de_auditoria):
    db = _FakeSession(fallos=99)

    _escribir(db)

    assert any("EVENTO NO REGISTRADO" in m for m in logs_de_auditoria)


# --------------------------------------------------------------------------- #
# 3. Redis caído: el contador es best-effort, el request NO se rompe
# --------------------------------------------------------------------------- #
def test_redis_no_disponible_no_rompe_el_request(monkeypatch, esperas, logs_de_auditoria):
    monkeypatch.setattr(audit_service, "get_redis", lambda: None)
    db = _FakeSession(fallos=99)

    fila = _escribir(db)

    assert fila is None  # degradación, no excepción
    assert any("Redis no disponible" in m for m in logs_de_auditoria), \
        "sin contador, el logger es el piso: la pérdida nunca puede ser silenciosa"


def test_redis_que_explota_no_rompe_el_request(monkeypatch, esperas):
    def _redis_roto():
        raise ConnectionError("redis: connection refused")

    monkeypatch.setattr(audit_service, "get_redis", _redis_roto)
    db = _FakeSession(fallos=99)

    assert _escribir(db) is None


# --------------------------------------------------------------------------- #
# 4. Modo closed: excepción TIPADA (los planos la vuelven 503) — y la pérdida igual cuenta
# --------------------------------------------------------------------------- #
def test_closed_propaga_excepcion_tipada(monkeypatch, redis_falso, esperas):
    monkeypatch.setenv(audit_service.AUDIT_FAIL_ENV, "closed")
    db = _FakeSession(fallos=99)

    with pytest.raises(AuditUnavailableError):
        _escribir(db)

    # Se rechaza Y se cuenta: el health tiene que poder mostrar el agujero.
    assert redis_falso.incrs == [REDIS_KEY_AUDIT_LOST]


def test_closed_no_afecta_el_camino_feliz(monkeypatch, redis_falso, esperas):
    monkeypatch.setenv(audit_service.AUDIT_FAIL_ENV, "closed")
    db = _FakeSession(fallos=0)

    assert _escribir(db) is not None
    assert redis_falso.incrs == []


def test_open_es_compatible_con_los_callers_previos(redis_falso, esperas):
    """Regresión de contrato: en `open` (default) el fallo sigue devolviendo None y NO
    lanza — ni chat.py ni gateway.py cambian de comportamiento por esta spec."""
    db = _FakeSession(fallos=99)
    assert _escribir(db) is None


# --------------------------------------------------------------------------- #
# 5. Helper único de lectura de la env (T001)
# --------------------------------------------------------------------------- #
def test_modo_default_es_open_sin_env():
    assert audit_fail_mode() == "open"


def test_modo_closed_explicito(monkeypatch):
    monkeypatch.setenv(audit_service.AUDIT_FAIL_ENV, "closed")
    assert audit_fail_mode() == "closed"
    monkeypatch.setenv(audit_service.AUDIT_FAIL_ENV, "  CLOSED  ")
    assert audit_fail_mode() == "closed"


@pytest.mark.parametrize("valor", ["", "   ", "cerrado", "true", "openn"])
def test_valor_ilegible_degrada_a_open(monkeypatch, valor):
    """Un typo en la env JAMÁS puede convertirse en un corte de servicio silencioso."""
    monkeypatch.setenv(audit_service.AUDIT_FAIL_ENV, valor)
    assert audit_fail_mode() == "open"


# --------------------------------------------------------------------------- #
# 6. audit_writable(): el pre-check del modo closed
# --------------------------------------------------------------------------- #
def test_audit_writable_true_con_base_sana():
    db = _FakeSession(fallos=0)

    assert audit_writable(db) is True
    assert "SELECT 1" in db.sentencias
    # Cierra su propia transacción: no deja el statement_timeout pegado al request.
    assert db.rollbacks == 1


def test_audit_writable_false_con_base_caida():
    db = _FakeSession(fallos=99)

    assert audit_writable(db) is False
    assert db.rollbacks == 1, "deja la sesión utilizable para responder 503"


def test_audit_writable_pone_timeout_corto_en_postgres():
    db = _FakeSession(fallos=0, dialecto="postgresql")

    assert audit_writable(db) is True
    assert any("statement_timeout" in s for s in db.sentencias)


def test_audit_writable_sin_bind_no_intenta_el_timeout():
    """Sesión sin dialecto conocido (o fake): el probe corre igual, sin SET LOCAL — un
    `SET` fallido dejaría la transacción abortada y convertiría un probe sano en 503."""
    db = _FakeSession(fallos=0)

    assert audit_writable(db) is True
    assert not any("statement_timeout" in s for s in db.sentencias)
