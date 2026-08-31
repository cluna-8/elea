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
def modo_default_sin_env(monkeypatch):
    """La env es global al proceso: cada test parte de un estado conocido (spec 038 D1:
    sin la env seteada el modo default ya no es `open`, es `policy`)."""
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
    """Spec 038 D1: sin `SENTINEL_AUDIT_FAIL` seteada el `/health` ahora publica `policy`, no
    `open` — consecuencia directa del default nuevo, no un bug de este test."""
    redis_falso({REDIS_KEY_AUDIT_LOST: "5", REDIS_KEY_AUDIT_LAST_FAIL: ISO})

    body = _app(_FakeSession(), usuario=_admin()).get(RUTA).json()

    assert body["audit"] == {"mode": "policy", "lost_events": 5, "last_failure_at": ISO}
    assert body["status"] == "healthy", "fuera de `closed` una pérdida NO degrada: el tráfico se sirve"


def test_sin_perdidas_es_cero_y_no_null(redis_falso):
    redis_falso({})  # la clave nunca se escribió

    body = _app(_FakeSession(), usuario=_admin()).get(RUTA).json()

    assert body["audit"]["lost_events"] == 0
    assert body["audit"]["last_failure_at"] is None


def test_redis_caido_devuelve_null_y_no_rompe(redis_falso):
    """`null` ≠ `0`: no se pudo mirar el contador, y decirlo es el punto de la spec.
    `mode` es `policy` (spec 038 D1, default sin la env seteada)."""
    redis_falso(ausente=True)

    resp = _app(_FakeSession(), usuario=_admin()).get(RUTA)

    assert resp.status_code == 200
    assert resp.json()["audit"] == {"mode": "policy", "lost_events": None,
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


def test_fuera_de_closed_no_paga_el_probe_de_escribibilidad(redis_falso):
    """Fuera de `closed` (acá: el default nuevo, `policy`) la caída de la auditoría no
    degrada el servicio, así que no hay razón para gastar un `SELECT 1` por cada probe
    (este endpoint es público)."""
    db = _FakeSession(caida=True)

    body = _app(db, usuario=_admin()).get(RUTA).json()

    assert body["status"] == "healthy"
    assert db.sentencias == [], "ni una consulta a la base fuera del camino `closed`"


# --------------------------------------------------------------------------- #
# 4. El health de licencia (021) sigue igual — SC-003 no se toca desde acá
# --------------------------------------------------------------------------- #
def test_el_health_de_licencia_no_cambio_de_ruta(redis_falso):
    resp = _app(_FakeSession()).get("/api/v1/health/license")

    assert resp.status_code == 200
    assert "status" in resp.json()


# --------------------------------------------------------------------------- #
# Coherencia tier × política de auditoría (spec 038 D3 / FR-006, T005)
# --------------------------------------------------------------------------- #
@pytest.fixture
def tier_espiado(monkeypatch):
    """Fija el tier y CUENTA cuántas veces se resolvió.

    Se parchea el nombre en `health_api`, no en el módulo de servicios: `health.py` hizo
    `from ..services.governance_resolution import instalacion_en_tier_estricto`, así que la
    referencia que ejecuta vive acá. Parchear el origen dejaría el espía sin usar y los
    tests pasarían por la razón equivocada.
    """
    llamadas = []

    def _instalar(estricto: bool):
        def _fake(db):
            llamadas.append(db)
            return estricto
        monkeypatch.setattr(health_api, "instalacion_en_tier_estricto", _fake)
        return llamadas

    # El cache vive en el módulo: sin esto, un test hereda el valor del anterior.
    health_api._tier_cache["vencimiento"] = 0.0
    return _instalar


def test_tier_estricto_con_open_explicito_degrada(redis_falso, monkeypatch, tier_espiado):
    """`open` + tier estricto = la instalación se contradice: exige registro y no lo garantiza."""
    tier_espiado(True)
    monkeypatch.setenv(AUDIT_FAIL_ENV, "open")

    body = _app(_FakeSession(), usuario=_admin()).get(RUTA).json()

    assert body["status"] == "degraded"
    assert "tier de enforcement es estricto" in body["reason"]
    assert "SENTINEL_AUDIT_FAIL=open" in body["reason"]


def test_tier_estricto_con_policy_default_degrada(redis_falso, tier_espiado):
    """Sin env seteada el modo es `policy` (D1) — la incoherencia con el tier es la misma."""
    tier_espiado(True)

    body = _app(_FakeSession(), usuario=_admin()).get(RUTA).json()

    assert body["status"] == "degraded"
    assert "SENTINEL_AUDIT_FAIL=policy" in body["reason"]


def test_tier_estandar_no_degrada(redis_falso, tier_espiado):
    """El tier estándar no asevera ninguna postura: `policy` no contradice nada."""
    tier_espiado(False)

    body = _app(_FakeSession(), usuario=_admin()).get(RUTA).json()

    assert body["status"] == "healthy"
    assert "reason" not in body or not body.get("reason")


def test_closed_no_paga_resolucion_de_gobernanza(redis_falso, monkeypatch, tier_espiado):
    """`closed` es coherente con CUALQUIER tier, así que el probe no consulta gobernanza.

    No es una micro-optimización: es la condición sellada para no meterle una query de
    governance a cada golpe de un orquestador.
    """
    llamadas = tier_espiado(True)
    monkeypatch.setenv(AUDIT_FAIL_ENV, "closed")

    body = _app(_FakeSession(), usuario=_admin()).get(RUTA).json()

    assert body["status"] == "healthy", "closed con auditoría escribible no degrada"
    assert llamadas == [], (
        "en `closed` no hay incoherencia posible: resolver el tier sería pagar una query "
        f"de gobernanza por probe sin ninguna decisión que tomar (se resolvió {len(llamadas)}x)"
    )


def test_el_cache_VENCE_y_el_cambio_de_tier_viaja(redis_falso, monkeypatch, tier_espiado):
    """Pasado el TTL se re-consulta Y el valor nuevo se refleja.

    El par del anti-martilleo: aquél prueba que el cache **absorbe**, éste que **vence**.
    Sin este pin, un bug que congele `vencimiento` deja el tier clavado para siempre —un
    admin activa el tier estricto y el health no degrada nunca, o al revés, una degradación
    fantasma que no se va— y toda la suite sigue verde. El «drift acotado al TTL» que se
    selló es una promesa de frescura, y una promesa sin testigo no es un invariante.

    Se manipula el RELOJ, no el cache: forzar `vencimiento` a mano haría pasar el test
    aunque el TTL fuera absurdo, que es justamente el bug que tiene que cazar.
    """
    reloj = {"t": 1_000.0}
    monkeypatch.setattr(health_api.time, "monotonic", lambda: reloj["t"])

    llamadas = tier_espiado(False)          # la instalación arranca en tier estándar
    cliente = _app(_FakeSession(), usuario=_admin())
    assert cliente.get(RUTA).json()["status"] == "healthy"

    tier_espiado(True)                      # un admin enciende el tier estricto
    reloj["t"] += health_api._TIER_CACHE_TTL_SEGUNDOS + 1

    body = cliente.get(RUTA).json()

    assert len(llamadas) == 2, (
        f"vencido el TTL hay que re-consultar; se resolvió {len(llamadas)} vez/veces"
    )
    assert body["status"] == "degraded", (
        "re-consultar no alcanza: el valor nuevo tiene que llegar al body, si no el cache "
        "vence pero sirve lo viejo igual"
    )


def test_el_TTL_esta_en_un_rango_sano(redis_falso):
    """Cota explícita sobre la constante: la frescura prometida tiene que ser creíble.

    El test de vencimiento avanza el reloj usando la propia constante, así que sobrevive a
    un cambio legítimo de TTL — pero por eso mismo no cazaría un valor absurdo. Este pin lo
    cubre: un TTL enorme es un cache que en la práctica no vence nunca, y uno de 0 es no
    cachear (el invariante amortizado se cae).
    """
    ttl = health_api._TIER_CACHE_TTL_SEGUNDOS

    assert 0 < ttl <= 300, (
        f"TTL={ttl}: fuera de rango la promesa de «drift acotado» deja de ser cierta — "
        "un valor enorme no vence nunca y uno nulo no absorbe el martilleo"
    )


def test_gobernanza_que_explota_no_rompe_el_health(redis_falso, monkeypatch, tier_espiado):
    """Si la query de gobernanza falla, el health responde igual y no degrada por tier.

    Un `/health` que devuelve 500 es peor que uno que no reporta la incoherencia: es LA
    superficie que mira ops justo cuando algo anda mal. Este caso lo encontraron los tests
    existentes del archivo, no el diseño: agregar la resolución de gobernanza metió una
    dependencia nueva en un camino que antes no tenía ninguna.
    """
    tier_espiado(True)

    def _explota(db):
        raise RuntimeError("governance_profiles no responde")

    monkeypatch.setattr(health_api, "instalacion_en_tier_estricto", _explota)

    resp = _app(_FakeSession(), usuario=_admin()).get(RUTA)

    assert resp.status_code == 200
    assert resp.json()["status"] == "healthy", (
        "no sabemos si hay incoherencia, así que no se inventa una degradación"
    )


def test_el_cache_de_tier_aguanta_el_MARTILLEO(redis_falso, tier_espiado):
    """N probes dentro del TTL ⇒ EXACTAMENTE una resolución, sin importar la tasa.

    Que el TTL absorba el *segundo* probe es la mitad del invariante; lo que protege una
    superficie pública es que absorba el duodécimo. El costo del health queda acotado por
    ventana de tiempo, no por número de callers (opción A sellada, 26-ago: el pin pasó de
    «cero queries» a «≤1 por ventana», conservando la intención original de #63 — que
    martillar el endpoint no se traduzca en carga proporcional sobre `guardians`).
    """
    llamadas = tier_espiado(True)
    db = _FakeSession()
    cliente = _app(db, usuario=_admin())

    for _ in range(12):
        cliente.get(RUTA)

    assert len(llamadas) == 1, (
        f"12 probes en la misma ventana costaron {len(llamadas)} resoluciones de tier: el "
        "cache no está acotando el costo y la superficie pública queda expuesta"
    )
    assert db.sentencias == [], (
        "el probe de escribibilidad (SELECT 1) sigue en CERO fuera de `closed`: sólo el "
        "tier ganó su ≤1/TTL, y los dos costos se cuentan por separado a propósito"
    )
