"""Spec 031 T009 — el logger de auditoría del motor deja de perder eventos en silencio.

Qué se protege acá: `basa_audit_logger` es el que registra TODO el tráfico byok que el
motor sirve (herramientas de coding: la superficie principal del producto). Hasta esta
spec, cada uno de sus caminos de error terminaba en un `print` "no fatal" — y por eso la
pérdida TOTAL del rastro byok del ensayo del piloto estuvo semanas invisible: la fila
fallaba, el motor imprimía en stdout y nadie miraba stdout. El contrato ahora es:

1. un fallo transitorio del plano interno se **absorbe** con reintento acotado, sin ruido
   ni pérdida (SC-002 §3);
2. un fallo que agota el presupuesto **cuenta** la pérdida en Redis (`basa:audit:lost` +
   `basa:audit:last_fail`) y la loguea con nivel error — nunca un `print`;
3. lo que NO se puede reintentar sin duplicar la fila (y el cargo al presupuesto: el POST
   mueve el gasto del cliente, issue #76) no se reintenta, pero se cuenta igual.

La extensión se importa como la importa el motor (`from extensions import
basa_audit_logger`, vía el `sys.path` que arma conftest) con dobles de
`litellm.integrations.custom_logger` y de `redis.asyncio` en `sys.modules`: ni litellm ni
un Redis vivo hacen falta para medir NUESTRA política.
"""
import logging
import sys
import types
from datetime import datetime
from pathlib import Path

import httpx
import pytest


# ── Doble de litellm.integrations.custom_logger (el módulo real no está acá) ────────────
def _instalar_doble_litellm():
    if "litellm.integrations.custom_logger" in sys.modules:
        return

    class CustomLogger:
        """Base vacía: el hook no usa nada del SDK, solo hereda de él."""
        def __init__(self, *args, **kwargs):
            pass

    litellm_mod = sys.modules.setdefault("litellm", types.ModuleType("litellm"))
    integrations = sys.modules.setdefault(
        "litellm.integrations", types.ModuleType("litellm.integrations"))
    modulo = types.ModuleType("litellm.integrations.custom_logger")
    modulo.CustomLogger = CustomLogger
    sys.modules["litellm.integrations.custom_logger"] = modulo
    litellm_mod.integrations = integrations
    integrations.custom_logger = modulo


_instalar_doble_litellm()

from extensions import basa_audit_logger as logger_mod  # noqa: E402

AUDIT_URL = "http://backend:8000/api/v1/internal/audit"
SECRETO = "master-key-de-prueba"

FILA = {"tenant_id": "33333333-3333-3333-3333-333333333333", "model": "gpt-4o-mini",
        "compliance_status": "passed", "prompt_tokens": 10, "completion_tokens": 2}


# ── Dobles ─────────────────────────────────────────────────────────────────────────────

class _Respuesta:
    def __init__(self, status_code: int):
        self.status_code = status_code


class _PlanoInterno:
    """Doble del plano interno: registra los POST y responde un guion.

    El guion es una lista de status codes o excepciones; se consume de a uno y el último
    elemento se repite (así `[503, 200]` significa "falla una vez y después anda").
    """

    def __init__(self, guion=None):
        self.posts: list = []
        self._guion = list(guion or [200])

    def instalar(self, monkeypatch):
        plano = self

        class _Cliente:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def post(self, url, json=None, headers=None):
                plano.posts.append({"url": url, "json": json, "headers": headers or {}})
                item = plano._guion.pop(0) if len(plano._guion) > 1 else plano._guion[0]
                if isinstance(item, Exception):
                    raise item
                return _Respuesta(item)

        monkeypatch.setattr(httpx, "AsyncClient", _Cliente)
        return self


class _PipeFalso:
    def __init__(self, registro):
        self.registro = registro

    def incr(self, key):
        self.registro["incrs"].append(key)

    def set(self, key, valor):
        self.registro["sets"][key] = valor

    async def execute(self):
        if self.registro.get("explota"):
            raise ConnectionError("redis: connection refused")
        return [1, True]


class _RedisFalso:
    def __init__(self, registro):
        self.registro = registro

    def pipeline(self):
        return _PipeFalso(self.registro)

    async def aclose(self):
        self.registro["cerrado"] = True


@pytest.fixture
def contador(monkeypatch):
    """Doble de `redis.asyncio` con el que la extensión escribe el contador de pérdidas.

    Se pisan las DOS puertas de `import redis.asyncio as x`: la entrada de `sys.modules` y
    el atributo del paquete padre (si el `redis` real ya está importado —lo está, el
    backend lo usa— `getattr(redis, "asyncio")` ganaría y devolvería el módulo de verdad).
    """
    registro = {"incrs": [], "sets": {}, "cerrado": False, "explota": False}
    modulo = types.ModuleType("redis.asyncio")
    # **kwargs: desde #105 #8 el cliente se construye con socket_timeout/socket_connect_timeout
    # (vía basa_engine_redis) — el doble tiene que aceptarlos sin romper.
    modulo.Redis = lambda host=None, port=None, **kwargs: _RedisFalso(registro)
    padre = sys.modules.setdefault("redis", types.ModuleType("redis"))
    monkeypatch.setitem(sys.modules, "redis.asyncio", modulo)
    monkeypatch.setattr(padre, "asyncio", modulo, raising=False)
    return registro


@pytest.fixture
def esperas(monkeypatch):
    """Captura el backoff sin pagarlo: el test verifica el presupuesto, no lo sufre."""
    registradas = []

    async def _fake(segundos):
        registradas.append(segundos)

    monkeypatch.setattr(logger_mod, "_esperar", _fake)
    return registradas


@pytest.fixture
def logs():
    """Handler propio sobre el logger de la extensión (no `caplog`, que depende de la
    config global de logging que `src.main` ya fijó cuando corre la suite completa)."""
    log = logging.getLogger("basa-audit")
    mensajes = []

    class _Captura(logging.Handler):
        def emit(self, record):
            mensajes.append(record.getMessage())

    handler = _Captura(level=logging.DEBUG)
    nivel_previo = log.level
    log.addHandler(handler)
    log.setLevel(logging.DEBUG)
    try:
        yield mensajes
    finally:
        log.removeHandler(handler)
        log.setLevel(nivel_previo)


@pytest.fixture(autouse=True)
def entorno(monkeypatch):
    monkeypatch.setenv("LITELLM_MASTER_KEY", SECRETO)
    monkeypatch.delenv("BASA_AUDIT_FAIL", raising=False)


# --------------------------------------------------------------------------- #
# 1. Fallo transitorio absorbido: la fila se escribe y NO hay pérdida que contar
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_dos_fallos_y_el_tercer_intento_escribe_sin_perdida(monkeypatch, contador,
                                                                  esperas):
    plano = _PlanoInterno([httpx.ConnectError("connection refused"),
                           httpx.ConnectError("connection refused"),
                           200]).instalar(monkeypatch)

    assert await logger_mod._postear_al_plano_interno(AUDIT_URL, FILA) is True

    assert len(plano.posts) == 3, "1 intento + 2 reintentos"
    assert contador["incrs"] == [], "un transitorio absorbido NO es una pérdida"
    assert esperas == list(logger_mod._AUDIT_RETRY_BACKOFFS_SECONDS)
    assert sum(esperas) < 1.5, "presupuesto acotado: el reintento no puede ser un DoS interno"


@pytest.mark.asyncio
async def test_camino_feliz_no_reintenta_ni_espera(monkeypatch, contador, esperas):
    plano = _PlanoInterno([200]).instalar(monkeypatch)

    assert await logger_mod._postear_al_plano_interno(AUDIT_URL, FILA) is True

    assert len(plano.posts) == 1
    assert esperas == []
    assert contador["incrs"] == []
    # El plano interno exige el secreto compartido: sin cabecera responde 404 a todo.
    assert plano.posts[0]["headers"]["X-Basa-Internal"] == SECRETO
    assert plano.posts[0]["json"] == FILA


@pytest.mark.asyncio
async def test_5xx_transitorio_se_reintenta(monkeypatch, contador, esperas):
    """El endpoint commitea antes de responder: un 5xx significa que el INSERT no se
    ejecutó, así que reintentar es seguro (y absorbe un backend que está arrancando)."""
    plano = _PlanoInterno([503, 200]).instalar(monkeypatch)

    assert await logger_mod._postear_al_plano_interno(AUDIT_URL, FILA) is True

    assert len(plano.posts) == 2
    assert contador["incrs"] == []


# --------------------------------------------------------------------------- #
# 2. Agotamiento: contador + timestamp + nivel error (nunca silencio, nunca print)
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_agotar_reintentos_cuenta_la_perdida_y_sella_el_timestamp(monkeypatch,
                                                                       contador, esperas,
                                                                       logs):
    plano = _PlanoInterno([httpx.ConnectError("backend caído")]).instalar(monkeypatch)

    assert await logger_mod._postear_al_plano_interno(AUDIT_URL, FILA) is False

    assert len(plano.posts) == 3
    assert contador["incrs"] == [logger_mod._REDIS_KEY_AUDIT_LOST]
    marca = contador["sets"][logger_mod._REDIS_KEY_AUDIT_LAST_FAIL]
    assert datetime.fromisoformat(marca).tzinfo is not None, "timestamp ISO con tz"
    assert any("EVENTO NO REGISTRADO" in m for m in logs)
    assert contador["cerrado"] is True, "el cliente Redis se cierra (no se filtran conexiones)"


@pytest.mark.asyncio
async def test_4xx_no_gasta_el_presupuesto_pero_cuenta(monkeypatch, contador, esperas, logs):
    """Un 404 (secreto mal) o un 422 (esquema rechazado) no mejora reintentándolo: se
    pierde ya, ruidosamente, sin castigar al backend con tres pedidos."""
    plano = _PlanoInterno([404]).instalar(monkeypatch)

    assert await logger_mod._postear_al_plano_interno(AUDIT_URL, FILA) is False

    assert len(plano.posts) == 1
    assert esperas == []
    assert contador["incrs"] == [logger_mod._REDIS_KEY_AUDIT_LOST]
    assert any("RECHAZÓ" in m for m in logs)


@pytest.mark.asyncio
async def test_resultado_ambiguo_no_se_reintenta_para_no_duplicar(monkeypatch, contador,
                                                                  esperas, logs):
    """`ReadTimeout` = el pedido SE MANDÓ y no sabemos si se ejecutó. Reintentarlo puede
    duplicar la fila Y cobrar dos veces el mismo consumo (el POST mueve el presupuesto,
    issue #76). Para un producto de auditoría una fila duplicada miente igual que una que
    falta: no se reintenta, y se cuenta para que alguien lo mire."""
    plano = _PlanoInterno([httpx.ReadTimeout("timeout leyendo la respuesta")]).instalar(
        monkeypatch)

    assert await logger_mod._postear_al_plano_interno(AUDIT_URL, FILA) is False

    assert len(plano.posts) == 1, "un solo envío: el riesgo es duplicar, no perder"
    assert contador["incrs"] == [logger_mod._REDIS_KEY_AUDIT_LOST]
    assert any("DESCONOCIDO" in m for m in logs)


# --------------------------------------------------------------------------- #
# 3. Redis caído: el contador es best-effort, el log es el piso
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_redis_caido_no_rompe_y_deja_el_error_en_el_log(monkeypatch, contador,
                                                              esperas, logs):
    contador["explota"] = True
    _PlanoInterno([httpx.ConnectError("backend caído")]).instalar(monkeypatch)

    assert await logger_mod._postear_al_plano_interno(AUDIT_URL, FILA) is False

    assert any("el contador falló" in m for m in logs), \
        "sin contador el logger es el piso: la pérdida nunca puede ser silenciosa"


# --------------------------------------------------------------------------- #
# 4. El hook de éxito, extremo a extremo (la ruta que corre en producción)
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_el_hook_de_exito_emite_la_fila_al_plano_interno(monkeypatch, contador,
                                                               esperas):
    monkeypatch.setenv("BASA_AUDIT_URL", AUDIT_URL)
    plano = _PlanoInterno([200]).instalar(monkeypatch)
    inicio = datetime(2026, 7, 28, 10, 0, 0)
    fin = datetime(2026, 7, 28, 10, 0, 1)
    kwargs = {
        "model": "gpt-4o-mini",
        "litellm_params": {},
        "metadata": {"user_api_key_metadata": {"basa": {
            "tenant_id": "33333333-3333-3333-3333-333333333333",
            "client_id": "22222222-2222-2222-2222-222222222222",
            "key_id": "11111111-1111-1111-1111-111111111111",
        }}},
        "response_cost": 0.0021,
    }
    respuesta = type("_R", (), {"usage": {"prompt_tokens": 10, "completion_tokens": 4}})()

    await logger_mod.basa_audit_logger_instance.async_log_success_event(
        kwargs, respuesta, inicio, fin)

    assert len(plano.posts) == 1
    fila = plano.posts[0]["json"]
    assert fila["tenant_id"] == "33333333-3333-3333-3333-333333333333"
    assert fila["prompt_tokens"] == 10 and fila["completion_tokens"] == 4
    assert fila["latency_ms"] == 1000
    assert contador["incrs"] == []


@pytest.mark.asyncio
async def test_sin_identidad_de_connection_no_se_registra(monkeypatch, contador, esperas):
    """Llamada INTERNA con la master key (chat de la consola, generación de frases del
    router, embeddings): NO lleva identidad Basa y su plano de origen ya escribe la fila
    canónica. Registrarla acá también duplicaba cada petición del Playground en Logs
    (hallazgo JF 29-jul: 2 llamadas → 3 filas, costo contado dos veces). Cero POST, cero
    pérdida contada: no es un fallo, es tráfico que no le pertenece a este plano."""
    monkeypatch.setenv("BASA_AUDIT_URL", AUDIT_URL)
    plano = _PlanoInterno([200]).instalar(monkeypatch)
    inicio = datetime(2026, 7, 28, 10, 0, 0)
    fin = datetime(2026, 7, 28, 10, 0, 1)
    kwargs = {
        "model": "camara-comercio-local",
        "litellm_params": {},
        "metadata": {},
        "response_cost": 0.0,
    }
    respuesta = type("_R", (), {"usage": {"prompt_tokens": 23, "completion_tokens": 1972}})()

    await logger_mod.basa_audit_logger_instance.async_log_success_event(
        kwargs, respuesta, inicio, fin)

    assert plano.posts == []
    assert contador["incrs"] == []


@pytest.mark.asyncio
async def test_una_excepcion_inesperada_del_hook_tambien_cuenta(monkeypatch, contador, logs):
    """El hook nunca voltea la respuesta al cliente, pero si revienta el pedido NO quedó
    registrado — y eso se cuenta igual que un POST agotado."""
    monkeypatch.setenv("BASA_AUDIT_URL", AUDIT_URL)

    async def _explota(*args, **kwargs):
        raise RuntimeError("payload imposible de armar")

    monkeypatch.setattr(logger_mod.BasaAuditLogger, "_log", _explota)

    # No propaga: la respuesta del cliente ya se sirvió y no se puede des-servir.
    await logger_mod.basa_audit_logger_instance.async_log_success_event({}, None, None, None)

    assert contador["incrs"] == [logger_mod._REDIS_KEY_AUDIT_LOST]
    assert any("NO quedó registrado" in m for m in logs)


@pytest.mark.asyncio
async def test_sin_destino_de_auditoria_la_perdida_es_ruidosa(monkeypatch, contador, logs):
    """Motor sin `BASA_AUDIT_URL` y sin cliente de base: antes se descartaba TODA la
    auditoría con un `return` mudo; ahora se cuenta y se dice."""
    monkeypatch.delenv("BASA_AUDIT_URL", raising=False)
    proxy_server = types.ModuleType("litellm.proxy.proxy_server")
    proxy_server.prisma_client = None
    sys.modules.setdefault("litellm.proxy", types.ModuleType("litellm.proxy"))
    monkeypatch.setitem(sys.modules, "litellm.proxy.proxy_server", proxy_server)

    await logger_mod.basa_audit_logger_instance._insertar_por_prisma(FILA, [], None, None)

    assert contador["incrs"] == [logger_mod._REDIS_KEY_AUDIT_LOST]
    assert any("NO deja rastro durable" in m for m in logs)


@pytest.mark.asyncio
async def test_emitir_fila_durable_enruta_por_env(monkeypatch):
    """Punto ÚNICO de emisión (#176): con `BASA_AUDIT_URL` la fila va al plano interno; sin
    ella, al prisma de desarrollo. Cada rama ya está cubierta arriba; acá se ancla el ENRUTADO,
    que es lo que reusa el rechazo por presupuesto del motor (`custom_auth`) para no duplicar la
    lógica de emisión."""
    llamadas = []

    async def _fake_post(url, entry):
        llamadas.append(("post", url))
        return True

    async def _fake_prisma(entry, masked, applied_layers=None, blocked_by_layer=None):
        llamadas.append(("prisma", masked))

    monkeypatch.setattr(logger_mod, "_postear_al_plano_interno", _fake_post)
    monkeypatch.setattr(logger_mod.basa_audit_logger_instance, "_insertar_por_prisma", _fake_prisma)

    entry = {"compliance_status": "rejected_budget", "tenant_id": FILA["tenant_id"]}

    monkeypatch.setenv("BASA_AUDIT_URL", AUDIT_URL)
    await logger_mod.emitir_fila_durable(entry, [])
    assert llamadas[-1] == ("post", AUDIT_URL)

    monkeypatch.delenv("BASA_AUDIT_URL", raising=False)
    await logger_mod.emitir_fila_durable(entry, [])
    assert llamadas[-1][0] == "prisma"


# --------------------------------------------------------------------------- #
# 5. Gate de la spec (T009/T015): cero `print(` en las extensiones del motor
# --------------------------------------------------------------------------- #
# Los dos scripts de diagnóstico quedan fuera: NO los carga el motor (tienen
# `if __name__ == "__main__"` y se corren a mano con `docker compose exec`), y ahí el
# `print` no es un fallo tragado sino la salida del comando.
_CHECKS_CLI = {"contract_checks.py", "integration_checks.py"}


def test_ninguna_extension_del_motor_usa_print():
    """FR-004: «los `print` de las extensiones MUST desaparecer en favor de logging real».

    Equivalente en test del grep del gate:
        grep -n "print(" litellm/extensions/*.py
    """
    # Se resuelve desde el módulo YA importado y no por ruta relativa al test: dentro del
    # contenedor las extensiones viven en /app/litellm_config/extensions (montadas), y en
    # el repo en litellm/extensions — así el gate mira el directorio real en ambos.
    extensiones = Path(logger_mod.__file__).resolve().parent
    assert extensiones.is_dir(), f"no encuentro las extensiones en {extensiones}"

    culpables = []
    for fichero in sorted(extensiones.glob("*.py")):
        if fichero.name in _CHECKS_CLI:
            continue
        for numero, linea in enumerate(fichero.read_text(encoding="utf-8").splitlines(), 1):
            if "print(" in linea and not linea.lstrip().startswith("#"):
                culpables.append(f"{fichero.name}:{numero}: {linea.strip()}")

    assert not culpables, (
        "un `print` en una extensión del motor es un fallo que nadie va a leer "
        "(así estuvo invisible la pérdida byok del ensayo):\n" + "\n".join(culpables))
