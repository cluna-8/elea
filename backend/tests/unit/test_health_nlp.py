"""El health dice la verdad sobre la detección NLP (issue #63, bloque `nlp`).

Hasta el fix, `GET /api/v1/health` podía contestar `healthy` mientras el motor de detección
de datos personales estaba caído y el tráfico se servía con patrones de desarrollo. Un
producto de compliance cuyo probe de salud no distingue "protegiendo" de "medio protegiendo"
no es auditable.

Tres estados, tres significados que NO se colapsan:
  * `not_configured` — no hay sidecar cableado. Es el modo de desarrollo: se informa y NO
    degrada, porque no hay avería, hay una decisión de despliegue.
  * `ok` — configurado y respondiendo.
  * `unreachable` — configurado y caído. Degrada SIEMPRE, con `block` y con `degrade`: en un
    caso el tráfico se rechaza y en el otro sale con media protección, y las dos cosas son
    algo que el operador tiene que ver.

Sin Postgres ni Redis reales: se mide la política del endpoint, no el stack.
"""
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import health as health_api
from src.api.health import router as health_router
from src.auth.session import get_current_user
from src.database import get_db
from src.services import audit_service

RUTA = "/api/v1/health"
ANALYZER = "http://nlp-analyzer:3000"
ISO = "2026-08-07T09:00:00+00:00"


class _FakeSession:
    """Sesión mínima: `audit_writable` ejecuta, `query` devuelve la config del guardián."""

    def __init__(self, guardian_config=None):
        self.guardian_config = guardian_config
        self.consultas = 0

    def execute(self, _sentencia):
        return None

    def get_bind(self):
        raise RuntimeError("sesión sin bind")

    def rollback(self):
        return None

    def query(self, *_args):
        self.consultas += 1
        cfg = self.guardian_config
        return SimpleNamespace(filter=lambda *a, **k: SimpleNamespace(
            first=lambda: None if cfg is None else (cfg,)))


class _FakeRedis:
    def __init__(self, valores=None):
        self.valores = valores or {}
        self.borrados = []

    def get(self, key):
        return self.valores.get(key)

    def delete(self, *keys):
        self.borrados.extend(keys)
        for k in keys:
            self.valores.pop(k, None)


def _app(db, usuario=None) -> TestClient:
    app = FastAPI()
    app.include_router(health_router, prefix="/api/v1")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: usuario
    return TestClient(app)


def _admin():
    return SimpleNamespace(role="admin", display_label=None)


@pytest.fixture(autouse=True)
def sin_cache_ni_env(monkeypatch):
    """El cache del probe es global del módulo: sin resetear, un test se lleva al siguiente."""
    monkeypatch.setattr(health_api, "_nlp_probe_cache", None, raising=False)
    monkeypatch.delenv("NLP_ANALYZER_URL", raising=False)
    monkeypatch.delenv(audit_service.AUDIT_FAIL_ENV, raising=False)


@pytest.fixture
def redis_falso(monkeypatch):
    def _instalar(valores=None):
        r = _FakeRedis(valores)
        monkeypatch.setattr(audit_service, "get_redis", lambda: r)
        # El health lee el contador de auditoría por su propio `get_redis`.
        monkeypatch.setattr(health_api, "get_redis", lambda: r)
        return r
    return _instalar({})


@pytest.fixture
def sidecar(monkeypatch):
    """Doble del `GET {analyzer}/health`. Devuelve la lista de URLs consultadas."""
    llamadas = []

    def _instalar(vivo: bool):
        monkeypatch.setenv("NLP_ANALYZER_URL", ANALYZER)

        def _get(url, timeout=None):
            llamadas.append(url)
            if not vivo:
                raise ConnectionError("name or service not known")
            return SimpleNamespace(status_code=200)

        monkeypatch.setattr(health_api.httpx, "get", _get)
        return llamadas

    return _instalar


# ── 1) Los tres estados ───────────────────────────────────────────────────────────


def test_sin_url_configurada_reporta_not_configured_y_no_degrada(redis_falso):
    """El modo regex de desarrollo se DICE, pero no es una avería: un piloto sin sidecar no
    puede reportarse `degraded` para siempre, o el estado deja de significar nada."""
    body = _app(_FakeSession(), usuario=_admin()).get(RUTA).json()

    assert body["nlp"]["configured"] is False
    assert body["nlp"]["status"] == "not_configured"
    assert body["nlp"]["fail_mode_efectivo"] is None, (
        "sin motor NLP no hay política ante su caída que anunciar")
    assert body["status"] == "healthy"


def test_sidecar_vivo_reporta_ok_y_limpia_la_marca(redis_falso, sidecar):
    """Confirmar que el analyzer volvió es el ÚNICO punto de reseteo del estado: las claves
    no tienen TTL a propósito (son constancia, no métrica) y el camino caliente sólo escribe."""
    r = redis_falso
    r.valores[audit_service.REDIS_KEY_NLP_DEGRADED_SINCE] = ISO
    r.valores[audit_service.REDIS_KEY_NLP_DEGRADED_COUNT] = "12"
    llamadas = sidecar(vivo=True)

    body = _app(_FakeSession({"nlp_fail_mode": "degrade"}), usuario=_admin()).get(RUTA).json()

    assert body["nlp"]["status"] == "ok"
    assert body["status"] == "healthy"
    assert llamadas == [f"{ANALYZER}/health"]
    assert audit_service.REDIS_KEY_NLP_DEGRADED_SINCE in r.borrados, (
        "sin limpiar, el panel seguiría alarmando después de que el motor volvió")


def test_sidecar_caido_reporta_unreachable_y_degrada(redis_falso, sidecar):
    sidecar(vivo=False)

    body = _app(_FakeSession({"nlp_fail_mode": "block"}), usuario=_admin()).get(RUTA).json()

    assert body["nlp"]["configured"] is True
    assert body["nlp"]["status"] == "unreachable"
    assert body["nlp"]["fail_mode_efectivo"] == "block"
    assert body["status"] == "degraded"
    assert "rechazando" in body["reason"], "el operador tiene que saber qué está pasando YA"


def test_caido_con_degrade_dice_que_la_cobertura_es_menor(redis_falso, sidecar):
    """El motivo cambia con la política porque la CONSECUENCIA cambia: con `degrade` no hay
    corte de servicio, hay pérdida de protección — y esa es la que se puede pasar por alto."""
    redis_falso.valores[audit_service.REDIS_KEY_NLP_DEGRADED_SINCE] = ISO
    redis_falso.valores[audit_service.REDIS_KEY_NLP_DEGRADED_COUNT] = "7"
    sidecar(vivo=False)

    body = _app(_FakeSession({"nlp_fail_mode": "degrade"}), usuario=_admin()).get(RUTA).json()

    assert body["nlp"]["fail_mode_efectivo"] == "degrade"
    assert body["nlp"]["degraded_since"] == ISO
    assert body["nlp"]["degraded_requests"] == 7
    assert body["status"] == "degraded"
    assert "REDUCIDA" in body["reason"]


def test_sin_clave_en_la_config_el_fail_mode_efectivo_es_block(redis_falso, sidecar):
    """Lo que se publica es lo que REALMENTE aplicaría, resuelto por la misma función que
    usan los planos de tráfico — no lo que esté escrito en la fila."""
    sidecar(vivo=False)

    body = _app(_FakeSession({}), usuario=_admin()).get(RUTA).json()

    assert body["nlp"]["fail_mode_efectivo"] == "block"


# ── 2) Tiers: el estado es público, el detalle no ─────────────────────────────────


def test_el_anonimo_ve_degraded_pero_no_el_bloque_nlp(redis_falso, sidecar):
    """«El detector de datos personales está caído ahora mismo» es exactamente el dato que le
    diría a quien quiera fugar información cuál es el mejor momento. El `degraded` sí es
    público: por sí solo no dice QUÉ se cayó."""
    sidecar(vivo=False)

    body = _app(_FakeSession({"nlp_fail_mode": "degrade"})).get(RUTA).json()

    assert body["status"] == "degraded"
    assert "nlp" not in body
    assert "reason" not in body


def test_el_tier_anonimo_no_consulta_la_base_por_el_fail_mode(redis_falso, sidecar):
    """Este endpoint es público: redactar un motivo que no va a viajar no puede costar una
    consulta a `guardians` en cada probe."""
    sidecar(vivo=False)
    db = _FakeSession({"nlp_fail_mode": "degrade"})

    _app(db).get(RUTA)

    assert db.consultas == 0


def test_un_rol_sin_permiso_de_auditoria_tampoco_ve_el_bloque(redis_falso, sidecar):
    sidecar(vivo=False)
    cliente = SimpleNamespace(role="client", display_label="developer")

    body = _app(_FakeSession({}), usuario=cliente).get(RUTA).json()

    assert "nlp" not in body


# ── 3) El probe no puede volverse el problema ─────────────────────────────────────


def test_el_probe_se_cachea_entre_llamadas(redis_falso, sidecar):
    """Sin cache, un bucle de monitorización convierte el health en un DoS contra el mismo
    sidecar que atiende el tráfico real."""
    llamadas = sidecar(vivo=True)
    client = _app(_FakeSession({}), usuario=_admin())

    client.get(RUTA)
    client.get(RUTA)
    client.get(RUTA)

    assert len(llamadas) == 1, f"el probe se pagó {len(llamadas)} veces"


def test_redis_caido_no_rompe_el_health_ni_inventa_un_cero(monkeypatch, sidecar):
    """`degraded_requests: null` ≠ `0`: no se pudo mirar el contador. Decir "cero" sin haber
    mirado es la misma mentira cómoda que el resto del producto ya borró."""
    monkeypatch.setattr(audit_service, "get_redis", lambda: None)
    monkeypatch.setattr(health_api, "get_redis", lambda: None)
    sidecar(vivo=False)

    resp = _app(_FakeSession({}), usuario=_admin()).get(RUTA)

    assert resp.status_code == 200
    assert resp.json()["nlp"]["degraded_requests"] is None


def test_el_guardian_ilegible_no_rompe_el_health(redis_falso, sidecar, monkeypatch):
    """Fail-closed también acá: si la config no se puede leer, se reporta `block` (lo que de
    verdad aplicaría), no un error 500 en el probe de salud."""
    sidecar(vivo=False)

    class _DBRota(_FakeSession):
        def query(self, *_a):
            raise RuntimeError("la base no responde")

    body = _app(_DBRota(), usuario=_admin()).get(RUTA).json()

    assert body["nlp"]["fail_mode_efectivo"] == "block"


# ── 4) Los dos motivos conviven ───────────────────────────────────────────────────


def test_auditoria_y_nlp_degradados_reportan_los_dos_motivos(redis_falso, sidecar,
                                                             monkeypatch):
    """Si el stack está roto por dos razones, esconder una haría que el operador arreglara la
    que ve y creyera que terminó."""
    monkeypatch.setenv(audit_service.AUDIT_FAIL_ENV, "closed")
    sidecar(vivo=False)

    class _DBSinAuditoria(_FakeSession):
        def execute(self, _s):
            raise RuntimeError("la base de auditoría no responde")

    body = _app(_DBSinAuditoria({}), usuario=_admin()).get(RUTA).json()

    assert body["status"] == "degraded"
    assert "audit_fail=closed" in body["reason"]
    assert "detección de datos personales" in body["reason"]
