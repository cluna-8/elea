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
import threading
import time
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
    """Sesión mínima: `audit_writable` ejecuta, `query` devuelve la config del guardián.

    `configs_por_tenant` permite tener filas de VARIOS tenants (para el test cross-tenant):
    el `filter` registra los criterios y sólo devuelve la fila del tenant pedido, que es
    justo lo que hace Postgres cuando el `WHERE tenant_id = …` está presente… y lo que NO
    hacía cuando faltaba."""

    def __init__(self, guardian_config=None, configs_por_tenant=None):
        self.guardian_config = guardian_config
        self.configs_por_tenant = configs_por_tenant
        self.consultas = 0
        self.filtros = []
        self.sentencias = 0          # `execute` = el SELECT 1 de escribibilidad

    def execute(self, _sentencia):
        self.sentencias += 1
        return None

    def get_bind(self):
        raise RuntimeError("sesión sin bind")

    def rollback(self):
        return None

    def query(self, *_args):
        self.consultas += 1
        sesion = self

        def _filter(*criterios, **_k):
            sesion.filtros.append(criterios)
            if sesion.configs_por_tenant is not None:
                # Emula el WHERE por tenant: se resuelve por el tenant que el caller pasó.
                tenant = sesion._tenant_del_filtro(criterios)
                cfg = sesion.configs_por_tenant.get(tenant)
            else:
                cfg = sesion.guardian_config
            # issue #104: el lector ahora encadena `.order_by(created_at, id).first()` para que
            # la postura sea determinista con dos `pii_masking` activos. El doble modela ese
            # `order_by` como no-op (una sola config de prueba) que devuelve el mismo resultado.
            resultado = SimpleNamespace(first=lambda: None if cfg is None else (cfg,))
            resultado.order_by = lambda *_a, **_k: resultado
            return resultado

        return SimpleNamespace(filter=_filter)

    @staticmethod
    def _tenant_del_filtro(criterios):
        """Extrae el valor comparado contra `Guardian.tenant_id` en el `filter(...)`."""
        for c in criterios:
            texto = str(getattr(c, "left", ""))
            if texto.endswith("tenant_id"):
                derecha = getattr(c, "right", None)
                return getattr(derecha, "value", None)
        return None


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


def _admin(tenant_id=None):
    return SimpleNamespace(role="admin", display_label=None, tenant_id=tenant_id)


@pytest.fixture(autouse=True)
def sin_cache_ni_env(monkeypatch):
    """El cache del probe es global del módulo: sin resetear, un test se lleva al siguiente.

    ⚠️ PUNTO CIEGO CONOCIDO (y por qué existe este aviso): al dejar el cache SIEMPRE en
    `None`, este fixture hace que todos los tests entren por el camino de "arranque en
    frío". El estado intermedio —**cache PRESENTE pero EXPIRADO**, o sea el worker normal a
    partir del segundo probe— no lo ejercitaba ningún test, y ahí vivía una regresión que se
    coló entera: un `Lock.acquire(blocking=False, timeout=...)` que CPython prohíbe y que
    devolvía 500 en cada `/health` de cualquier instalación con NLP configurado.

    Regla para quien agregue tests acá: si tocás `_nlp_alcanzable`, sembrá el cache a mano
    (ver `test_cache_expirado_refresca_sin_explotar`) en vez de confiar en este reset."""
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


def test_el_tier_anonimo_no_paga_una_consulta_POR_PROBE(redis_falso, sidecar):
    """El endpoint es público y martillable: el costo se acota AMORTIZADO, no a cero.

    Rationale original (issue #63): «redactar un motivo que no va a viajar no puede costar
    una consulta a `guardians` en cada probe». Sigue vigente — lo que cambió es que ahora SÍ
    hay un motivo que puede viajar: con el tier de enforcement en estricto, un
    `BASA_AUDIT_FAIL` que no sea `closed` es una incoherencia y `status: degraded` **sí** se
    publica al anónimo (spec 038 D3; opción A sellada por el manager el 26-ago — se descartó
    dársela sólo al admin porque quienes pollean `/health` anónimo, k8s y uptime checks, son
    exactamente los consumidores de esa señal).

    El pin nuevo es el amortizado: **≤1 resolución de tier por ventana de TTL, sin importar
    la tasa de probes**. Doce probes seguidos no pueden costar doce queries.
    """
    sidecar(vivo=False)
    db = _FakeSession({"nlp_fail_mode": "degrade"})
    cliente = _app(db)

    for _ in range(12):
        cliente.get(RUTA)

    # El pin subió de 1 a 2 con la spec 038 T006: la sonda de riesgo sin poblar es una
    # SEGUNDA señal pública (misma razón que el tier — quien pollea `/health` anónimo es el
    # consumidor de estas señales), con su propio cache de la misma forma. Lo que este test
    # defiende no es la constante sino el **amortizado**: doce probes no pueden costar doce
    # queries. Si mañana un tercer motivo suma una tercera, el número sube de nuevo; lo que
    # nunca puede pasar es que el conteo escale con la tasa de probes.
    assert db.consultas <= 2, (
        f"12 probes dentro del TTL costaron {db.consultas} queries: hay ≤1 por señal "
        "cacheada (tier + padrón de riesgo). Más que eso = un cache no está absorbiendo el "
        "martilleo y la superficie pública queda expuesta"
    )
    assert db.sentencias == 0, (
        "el probe de escribibilidad (SELECT 1) sigue en CERO fuera de `closed`: sólo el tier "
        "ganó su ≤1/TTL. Un assert genérico sobre 'la base' dejaría colar este SELECT 1"
    )


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


def test_cache_expirado_refresca_sin_explotar(monkeypatch, redis_falso, sidecar):
    """Regresión del round 2, y el estado que NINGÚN test cubría: cache PRESENTE y EXPIRADO.

    Es el camino NORMAL de cualquier worker a partir del segundo probe —y por eso el bug era
    total, no un edge case—: con cache el `single-flight` resolvía `en_frio = False` y hacía
    `Lock.acquire(blocking=False, timeout=2.0)`, combinación que CPython PROHÍBE
    (`ValueError: can't specify a timeout for a non-blocking call`). Resultado: 500 permanente
    en `/api/v1/health` de toda instalación con `NLP_ANALYZER_URL`, el banner del panel muerto
    y la degradación otra vez silenciosa — el #63 renacido por su propio arreglo.

    Se siembra el cache con edad > TTL en vez de dejar que lo resetee el fixture autouse: ese
    reset es justo lo que escondía el agujero."""
    llamadas = sidecar(vivo=True)
    # Veredicto viejo (11 s > TTL de 10 s) y CONTRARIO al que devolverá el probe fresco, para
    # que el test también falle si se devolviera el cacheado sin refrescar.
    monkeypatch.setattr(health_api, "_nlp_probe_cache",
                        (time.monotonic() - 11.0, False), raising=False)

    alcanzable, fresco = health_api._nlp_alcanzable(ANALYZER)

    assert alcanzable is True, "no refrescó: devolvió el veredicto vencido"
    assert fresco is True, "el probe se ejecutó, así que tiene que declararse fresco"
    assert llamadas == [f"{ANALYZER}/health"]


def test_cache_expirado_por_el_endpoint_no_devuelve_500(monkeypatch, redis_falso, sidecar):
    """El mismo agujero visto desde afuera, que es como lo sufre el operador: el endpoint
    tiene que seguir contestando 200 con el bloque `nlp`, no un 500."""
    sidecar(vivo=True)
    monkeypatch.setattr(health_api, "_nlp_probe_cache",
                        (time.monotonic() - 11.0, False), raising=False)

    resp = _app(_FakeSession({}), usuario=_admin()).get(RUTA)

    assert resp.status_code == 200, resp.text
    assert resp.json()["nlp"]["status"] == "ok"


def test_cache_expirado_con_otro_hilo_probando_usa_el_valor_previo(monkeypatch, sidecar):
    """La contracara del fix: con cache expirado y el lock TOMADO por otro hilo, no se espera
    ni se explota — se contesta el último valor conocido, marcado como NO fresco (así no
    autoriza el borrado de la marca de degradación)."""
    llamadas = sidecar(vivo=True)
    monkeypatch.setattr(health_api, "_nlp_probe_cache",
                        (time.monotonic() - 11.0, True), raising=False)
    health_api._nlp_probe_lock.acquire()
    try:
        alcanzable, fresco = health_api._nlp_alcanzable(ANALYZER)
    finally:
        health_api._nlp_probe_lock.release()

    assert (alcanzable, fresco) == (True, False)
    assert llamadas == [], "no puede encolar un probe mientras otro hilo lo está haciendo"


@pytest.mark.parametrize("vivo", [True, False])
def test_n_llamadas_concurrentes_pagan_UN_solo_probe(monkeypatch, vivo):
    """Single-flight (hallazgo del review adversarial). El cache por sí solo no alcanza: el
    endpoint es `def` síncrono —FastAPI lo corre en el THREADPOOL, o sea concurrencia real—,
    el cache se escribe DESPUÉS del probe, y sin lock los N pedidos que caen en la ventana
    disparan N probes. Consecuencia: martilleo al sidecar y N hilos del pool ocupados 1,5 s
    cada uno, todo disparable por callers ANÓNIMOS.

    Se ejercita `_nlp_alcanzable` directamente —es la unidad con el estado compartido— con un
    probe LENTO (la ventana existe de verdad) y N hilos entrando a la vez. Se prueban los dos
    veredictos: el estampido con el sidecar CAÍDO es el peor caso, porque ahí cada probe
    además agota su timeout.
    """
    monkeypatch.setattr(health_api, "_nlp_probe_cache", None, raising=False)
    llamadas = []
    cerrojo = threading.Lock()

    def _get_lento(url, timeout=None):
        with cerrojo:
            llamadas.append(url)
        time.sleep(0.3)  # ventana amplia: sin single-flight entran todos
        if not vivo:
            raise ConnectionError("name or service not known")
        return SimpleNamespace(status_code=200)

    monkeypatch.setattr(health_api.httpx, "get", _get_lento)

    n = 6
    barrera = threading.Barrier(n)
    resultados = []

    def _consultar():
        barrera.wait()
        resultados.append(health_api._nlp_alcanzable(ANALYZER))

    hilos = [threading.Thread(target=_consultar) for _ in range(n)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join(timeout=15)

    assert len(llamadas) == 1, (
        f"{len(llamadas)} probes para {n} llamadas concurrentes — el sidecar recibe el "
        "estampido entero y el threadpool se queda sin hilos")
    assert len(resultados) == n
    # Todos contestan el MISMO veredicto: en arranque en frío los perdedores esperan al
    # ganador en vez de inventar un `unreachable` que dispararía una alarma falsa.
    assert all(alcanzable is vivo for alcanzable, _fresco in resultados), resultados
    # Y exactamente uno lo marca como FRESCO: es el que puede autorizar el borrado de la
    # marca de degradación (ver los tests del `clear`).
    assert sum(1 for _a, fresco in resultados if fresco) == 1, resultados


# ── 3 bis) El reseteo de la marca no lo dispara cualquiera ni cualquier veredicto ──


def test_el_tier_anonimo_no_borra_la_marca(redis_falso, sidecar):
    """Hallazgo del review: el `clear` corría ANTES del corte por tier, o sea que era una
    escritura en Redis disparable SIN credenciales — y contradecía el docstring que promete
    que el tier anónimo no toca Redis."""
    r = redis_falso
    r.valores[audit_service.REDIS_KEY_NLP_DEGRADED_SINCE] = ISO
    sidecar(vivo=True)

    _app(_FakeSession({})).get(RUTA)  # sin usuario

    assert r.borrados == [], "un caller anónimo no puede borrar la constancia de degradación"
    assert audit_service.REDIS_KEY_NLP_DEGRADED_SINCE in r.valores


def test_un_veredicto_CACHEADO_no_borra_la_marca(redis_falso, sidecar):
    """El `clear` exige un probe FRESCO. Con un poller cada 5 s y un cache de 10 s, el
    veredicto "está vivo" puede tener 10 s de antigüedad: borrar con eso limpiaría marcas
    escritas DESPUÉS del probe, que es justo la evidencia de una oscilación del sidecar."""
    r = redis_falso
    sidecar(vivo=True)
    client = _app(_FakeSession({}), usuario=_admin())

    client.get(RUTA)                     # probe fresco → limpia (estado sano)
    assert r.borrados, "el camino fresco sí tiene que limpiar"
    r.borrados.clear()

    # Entre medio, el motor degrada y deja marca. El veredicto cacheado sigue diciendo "ok".
    r.valores[audit_service.REDIS_KEY_NLP_DEGRADED_SINCE] = ISO
    client.get(RUTA)

    assert r.borrados == [], "un veredicto cacheado no puede borrar una marca recién escrita"
    assert r.valores.get(audit_service.REDIS_KEY_NLP_DEGRADED_SINCE) == ISO


# ── 3 ter) La postura publicada es la del tenant que pregunta ─────────────────────


def test_el_fail_mode_no_se_lee_de_otro_tenant(redis_falso, sidecar):
    """Hallazgo del review: `_fail_mode_efectivo` filtraba por `guardian_type`/`is_active`
    pero NO por `tenant_id`, así que `.first()` devolvía la fila de cualquiera. En
    multi-tenant, un admin veía publicada la postura de otra organización — lectura
    cross-tenant, prohibida por Constitución III."""
    sidecar(vivo=False)
    mio, ajeno = "tenant-propio", "tenant-ajeno"
    db = _FakeSession(configs_por_tenant={
        ajeno: {"nlp_fail_mode": "degrade"},   # el de al lado relaja…
        mio: {"nlp_fail_mode": "block"},       # …y el mío no
    })

    body = _app(db, usuario=_admin(tenant_id=mio)).get(RUTA).json()

    assert body["nlp"]["fail_mode_efectivo"] == "block"
    assert "rechazando" in body["reason"], "el motivo también sale de la postura equivocada"
    assert any(any(str(getattr(c, "left", "")).endswith("tenant_id") for c in criterios)
               for criterios in db.filtros), "la consulta tiene que filtrar por tenant"


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
