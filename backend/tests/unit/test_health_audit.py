"""Spec 031 T009 — el health dice la verdad sobre la auditoría (contrato §health).

Sin Postgres ni Redis reales: sesión falsa + Redis falso, así el test mide EXACTAMENTE la
política del endpoint (qué se publica, a quién, y cuándo el estado global es `degraded`) y
no la disponibilidad del stack.

Tres cosas que se juegan acá:

1. **`lost_events` distingue "cero pérdidas" de "no pude mirar"**: `0` vs `null`. Publicar
   `0` con Redis caído sería la misma mentira cómoda que la spec vino a borrar.
2. **Los números son de operación**: viajan a admin/compliance_officer (los mismos roles
   que pueden abrir Logs de Auditoría), no a un caller anónimo de internet.
3. **`closed` + auditoría caída ⇒ `degraded`**: el edge case explícito de la spec ("sin
   healthy mentiroso"). Y en `open` el probe NI SIQUIERA se paga: una auditoría caída no
   degrada un servicio que por diseño se sigue sirviendo.
"""
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import health as health_api
from src.api.health import router as health_router
from src.auth.session import get_current_user
from src.database import get_db
from src.services.audit_service import (
    AUDIT_FAIL_ENV,
    REDIS_KEY_AUDIT_LAST_FAIL,
    REDIS_KEY_AUDIT_LOST,
)

RUTA = "/api/v1/health"
ISO = "2026-07-28T10:15:00+00:00"


class _DBCaida(Exception):
    """Lo que ve el probe cuando la base no está."""


class _FakeSession:
    """Sesión mínima para `audit_writable`: registra lo que se ejecutó y puede fallar."""

    def __init__(self, caida: bool = False):
        self.caida = caida
        self.sentencias = []
        self.rollbacks = 0

    def execute(self, sentencia):
        self.sentencias.append(str(sentencia))
        if self.caida:
            raise _DBCaida("la base de auditoría no responde")
        return None

    def get_bind(self):
        raise RuntimeError("sesión sin bind")  # sin dialecto ⇒ sin SET LOCAL

    def rollback(self):
        self.rollbacks += 1


class _FakeRedis:
    """Sólo `get`: el health lee, nunca escribe el contador."""

    def __init__(self, valores=None, explota=False):
        self.valores = valores or {}
        self.explota = explota

    def get(self, key):
        if self.explota:
            raise ConnectionError("redis: connection refused")
        return self.valores.get(key)


def _app(db: _FakeSession, usuario=None) -> TestClient:
    app = FastAPI()
    app.include_router(health_router, prefix="/api/v1")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: usuario
    return TestClient(app)


def _admin():
    return SimpleNamespace(role="admin", display_label=None)


@pytest.fixture
def redis_falso(monkeypatch):
    """Por defecto: Redis vivo y sin pérdidas registradas."""
    def _instalar(valores=None, explota=False, ausente=False):
        r = None if ausente else _FakeRedis(valores, explota)
        monkeypatch.setattr(health_api, "get_redis", lambda: r)
        return r
    _instalar()
    return _instalar


@pytest.fixture(autouse=True)
def modo_open_por_defecto(monkeypatch):
    """La env es global al proceso: cada test parte de un estado conocido."""
    monkeypatch.delenv(AUDIT_FAIL_ENV, raising=False)


# --------------------------------------------------------------------------- #
# 1. Tier anónimo: estado sí, números no
# --------------------------------------------------------------------------- #
def test_anonimo_recibe_estado_sin_numeros(redis_falso):
    redis_falso({REDIS_KEY_AUDIT_LOST: "7", REDIS_KEY_AUDIT_LAST_FAIL: ISO})

    body = _app(_FakeSession()).get(RUTA).json()

    assert body["status"] == "healthy"
    assert "audit" not in body, (
        "un caller anónimo no tiene por qué saber cuántos eventos se perdieron: es "
        "decirle a quien quiera fugar datos cuál es el mejor momento"
    )
    assert set(body) == {"status", "service", "version"}


def test_rol_sin_permiso_de_auditoria_tampoco_ve_los_numeros(redis_falso):
    cliente = SimpleNamespace(role="client", display_label="developer")

    body = _app(_FakeSession(), usuario=cliente).get(RUTA).json()

    assert "audit" not in body


# --------------------------------------------------------------------------- #
# 2. Tier de operación: el bloque del contrato, con la semántica de cada valor
# --------------------------------------------------------------------------- #
def test_contador_sembrado_se_publica_tal_cual(redis_falso):
    redis_falso({REDIS_KEY_AUDIT_LOST: "5", REDIS_KEY_AUDIT_LAST_FAIL: ISO})

    body = _app(_FakeSession(), usuario=_admin()).get(RUTA).json()

    assert body["audit"] == {"mode": "open", "lost_events": 5, "last_failure_at": ISO}
    assert body["status"] == "healthy", "en `open` una pérdida NO degrada: el tráfico se sirve"


def test_sin_perdidas_es_cero_y_no_null(redis_falso):
    redis_falso({})  # la clave nunca se escribió

    body = _app(_FakeSession(), usuario=_admin()).get(RUTA).json()

    assert body["audit"]["lost_events"] == 0
    assert body["audit"]["last_failure_at"] is None


def test_redis_caido_devuelve_null_y_no_rompe(redis_falso):
    """`null` ≠ `0`: no se pudo mirar el contador, y decirlo es el punto de la spec."""
    redis_falso(ausente=True)

    resp = _app(_FakeSession(), usuario=_admin()).get(RUTA)

    assert resp.status_code == 200
    assert resp.json()["audit"] == {"mode": "open", "lost_events": None,
                                    "last_failure_at": None}


def test_redis_que_explota_tampoco_rompe_el_health(redis_falso):
    redis_falso({REDIS_KEY_AUDIT_LOST: "3"}, explota=True)

    resp = _app(_FakeSession(), usuario=_admin()).get(RUTA)

    assert resp.status_code == 200
    assert resp.json()["audit"]["lost_events"] is None


def test_valor_ilegible_no_se_inventa_un_numero(redis_falso):
    redis_falso({REDIS_KEY_AUDIT_LOST: "no-es-un-numero"})

    assert _app(_FakeSession(), usuario=_admin()).get(RUTA).json()["audit"]["lost_events"] is None


def test_valores_en_bytes_se_normalizan(redis_falso):
    """Un cliente Redis sin `decode_responses` devuelve bytes: el contrato del bloque
    sigue siendo int|None y str|None, no `b'5'` serializado como basura."""
    redis_falso({REDIS_KEY_AUDIT_LOST: b"9", REDIS_KEY_AUDIT_LAST_FAIL: ISO.encode()})

    audit = _app(_FakeSession(), usuario=_admin()).get(RUTA).json()["audit"]

    assert audit["lost_events"] == 9
    assert audit["last_failure_at"] == ISO


# --------------------------------------------------------------------------- #
# 3. Degradado: sólo en `closed` con la auditoría caída (edge case de la spec)
# --------------------------------------------------------------------------- #
def test_closed_con_auditoria_caida_degrada_el_health(monkeypatch, redis_falso):
    monkeypatch.setenv(AUDIT_FAIL_ENV, "closed")
    db = _FakeSession(caida=True)

    body = _app(db, usuario=_admin()).get(RUTA).json()

    assert body["status"] == "degraded"
    assert "audit_fail=closed" in body["reason"]
    assert body["audit"]["mode"] == "closed"


def test_closed_con_auditoria_sana_sigue_healthy(monkeypatch, redis_falso):
    monkeypatch.setenv(AUDIT_FAIL_ENV, "closed")
    db = _FakeSession()

    body = _app(db, usuario=_admin()).get(RUTA).json()

    assert body["status"] == "healthy"
    assert body["reason"] is None
    assert any("SELECT 1" in s for s in db.sentencias)


def test_anonimo_tambien_ve_el_degradado(monkeypatch, redis_falso):
    """El estado global es público —un probe de ops sin credenciales tiene que poder
    preguntar "¿esto está sano?"—; el MOTIVO y los números, no."""
    monkeypatch.setenv(AUDIT_FAIL_ENV, "closed")

    body = _app(_FakeSession(caida=True)).get(RUTA).json()

    assert body["status"] == "degraded"
    assert "reason" not in body


def test_open_no_paga_el_probe_de_escribibilidad(redis_falso):
    """En `open` la caída de la auditoría no degrada el servicio, así que no hay razón
    para gastar un `SELECT 1` por cada probe (este endpoint es público)."""
    db = _FakeSession(caida=True)

    body = _app(db, usuario=_admin()).get(RUTA).json()

    assert body["status"] == "healthy"
    assert db.sentencias == [], "ni una consulta a la base en el camino `open`"


# --------------------------------------------------------------------------- #
# 4. El health de licencia (021) sigue igual — SC-003 no se toca desde acá
# --------------------------------------------------------------------------- #
def test_el_health_de_licencia_no_cambio_de_ruta(redis_falso):
    resp = _app(_FakeSession()).get("/api/v1/health/license")

    assert resp.status_code == 200
    assert "status" in resp.json()
