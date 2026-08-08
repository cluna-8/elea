"""Hardening del camino de degradación NLP contra un Redis lento/colgado (hallazgo #8 de #105).

El bug que estos tests fijan es de FIABILIDAD, no de política. Durante una caída del analyzer
NLP el camino de degradación corre en CADA request, y tenía dos problemas que se sumaban justo
cuando el sistema ya estaba tocado:

1. **Sin timeout de operación**: los clientes Redis (backend `get_redis`, y el motor en
   `_marcar_nlp_degradado`/`_contar_perdida`) no fijaban `socket_timeout` — el default de
   redis-py es infinito. Una marca de degradación contra un Redis colgado se quedaba pegada
   para siempre, colgando el worker que la servía.
2. **Redis SÍNCRONO en contexto async**: `record_nlp_degradation` se llamaba INLINE desde
   `evaluate_request_policy` (async), así que ese Redis síncrono bloqueaba el event loop del
   worker en cada request degradada.

Lo que se afirma acá es la ROBUSTEZ del cómo, nunca el comportamiento observable de la
degradación (que sigue igual de ruidosa: fila durable + marca en Redis + /health). En
concreto: (a) los clientes se construyen CON los dos timeouts acotados; (b) una marca que
timeoutea NO propaga excepción y se cuenta como pérdida reutilizando el contador existente;
(c) la escritura de la marca se despacha a un hilo y no corre inline en el event loop.

El doble de Redis sigue el estilo de `test_gateway_nlp_paridad.py` (`_RedisFalso`) y
`test_guardrail_block_audit.py` (doble de `redis.asyncio.Redis`).
"""
import sys
import threading
import types

import pytest
import redis


# ── Dobles de litellm para poder importar las extensiones del motor ─────────────────────
# (idéntico al de test_guardrail_block_audit.py / test_audit_logger_retry.py: litellm no está
# instalado en el backend y no hace falta que lo esté — lo que se prueba es NUESTRA lógica de
# Redis, no el SDK del motor). Se doblan las DOS bases: el guardrail y el logger de éxito.
def _instalar_dobles_litellm():
    litellm_mod = sys.modules.setdefault("litellm", types.ModuleType("litellm"))
    integrations = sys.modules.setdefault(
        "litellm.integrations", types.ModuleType("litellm.integrations"))
    litellm_mod.integrations = integrations

    if "litellm.integrations.custom_guardrail" not in sys.modules:
        class CustomGuardrail:
            def __init__(self, *args, **kwargs):
                pass

        modulo = types.ModuleType("litellm.integrations.custom_guardrail")
        modulo.CustomGuardrail = CustomGuardrail
        sys.modules["litellm.integrations.custom_guardrail"] = modulo
        integrations.custom_guardrail = modulo

    if "litellm.integrations.custom_logger" not in sys.modules:
        class CustomLogger:
            def __init__(self, *args, **kwargs):
                pass

        modulo = types.ModuleType("litellm.integrations.custom_logger")
        modulo.CustomLogger = CustomLogger
        sys.modules["litellm.integrations.custom_logger"] = modulo
        integrations.custom_logger = modulo


_instalar_dobles_litellm()

from extensions import basa_audit_logger, basa_guardrail  # noqa: E402
from src.services import audit_service, redis_client  # noqa: E402


def _es_timeout_acotado(valor) -> bool:
    """Un timeout válido para #8: presente, numérico y FINITO (nunca None/infinito)."""
    return isinstance(valor, (int, float)) and 0 < float(valor) <= 5


# ══════════════════════════════════════════════════════════════════════════════════════
# (a) Los clientes del camino de degradación se construyen CON los dos timeouts
# ══════════════════════════════════════════════════════════════════════════════════════


def test_get_redis_del_backend_fija_ambos_timeouts(monkeypatch):
    """`get_redis()` construye el cliente compartido con `socket_timeout` Y
    `socket_connect_timeout` acotados. Antes sólo fijaba el connect (2 s) y dejaba el de
    operación en infinito — el que cuelga el worker cuando Redis responde pero lento."""
    capturado = {}

    class _RedisDoble:
        def __init__(self, **kwargs):
            capturado.update(kwargs)

        def ping(self):
            return True

    # `_client` está cacheado a nivel módulo: sin resetear, `get_redis` devolvería el de otra
    # prueba y no construiría nada. monkeypatch lo restaura al terminar.
    monkeypatch.setattr(redis_client, "_client", None)
    monkeypatch.setattr(redis_client.redis, "Redis", _RedisDoble)

    cliente = redis_client.get_redis()

    assert cliente is not None, "el ping del doble no debería fallar"
    assert _es_timeout_acotado(capturado.get("socket_connect_timeout")), capturado
    assert _es_timeout_acotado(capturado.get("socket_timeout")), (
        "falta el timeout de OPERACIÓN — el que evita que una op contra un Redis lento "
        f"cuelgue el worker: {capturado}")


@pytest.mark.asyncio
async def test_marcar_nlp_degradado_del_motor_construye_redis_con_timeouts(monkeypatch):
    """El motor abre un cliente NUEVO por request degradada: si ese cliente no lleva timeouts,
    un Redis colgado deja la request pegada indefinidamente aunque sea async."""
    import redis.asyncio as redis_lib
    capturado = {}

    class _Pipe:
        def set(self, *a, **k):
            pass

        def incr(self, *a, **k):
            pass

        async def execute(self):
            return True

    class _RedisDoble:
        def __init__(self, **kwargs):
            capturado.update(kwargs)

        def pipeline(self):
            return _Pipe()

        async def aclose(self):
            pass

    monkeypatch.setattr(redis_lib, "Redis", _RedisDoble)

    await basa_guardrail._marcar_nlp_degradado()

    assert _es_timeout_acotado(capturado.get("socket_timeout")), capturado
    assert _es_timeout_acotado(capturado.get("socket_connect_timeout")), capturado


@pytest.mark.asyncio
async def test_contar_perdida_del_motor_construye_redis_con_timeouts(monkeypatch):
    """`_contar_perdida` arrastra el mismo patrón (abre un cliente por evento) y comparte los
    mismos timeouts acotados que la marca de degradación."""
    import redis.asyncio as redis_lib
    capturado = {}

    class _Pipe:
        def incr(self, *a, **k):
            pass

        def set(self, *a, **k):
            pass

        async def execute(self):
            return True

    class _RedisDoble:
        def __init__(self, **kwargs):
            capturado.update(kwargs)

        def pipeline(self):
            return _Pipe()

        async def aclose(self):
            pass

    monkeypatch.setattr(redis_lib, "Redis", _RedisDoble)

    await basa_guardrail._contar_perdida("motivo-de-prueba")

    assert _es_timeout_acotado(capturado.get("socket_timeout")), capturado
    assert _es_timeout_acotado(capturado.get("socket_connect_timeout")), capturado


# ══════════════════════════════════════════════════════════════════════════════════════
# (b) Una marca que TIMEOUTEA no propaga y se cuenta como pérdida (sin duplicar mecanismo)
# ══════════════════════════════════════════════════════════════════════════════════════


def test_record_nlp_degradation_backend_con_timeout_no_propaga_y_cuenta_perdida(monkeypatch):
    """La marca contra un Redis que timeoutea NO puede tumbar el request degradado: se traga
    la excepción (el piso es el `logger.error`) y la pérdida se cuenta REUTILIZANDO
    `record_audit_loss` (`basa:audit:lost` + /health), no un contador nuevo."""

    class _RedisColgado:
        def set(self, *a, **k):
            raise redis.exceptions.TimeoutError("Timeout reading from socket")

        def incr(self, *a, **k):
            raise redis.exceptions.TimeoutError("Timeout reading from socket")

    monkeypatch.setattr(audit_service, "get_redis", lambda: _RedisColgado())

    perdidas = []
    monkeypatch.setattr(audit_service, "record_audit_loss",
                        lambda reason="": perdidas.append(reason))

    # No propaga: si esto levantara, el request degradado se caería con 500.
    audit_service.record_nlp_degradation(reason="test/timeout")

    assert perdidas, "una marca que no responde tiene que contarse como pérdida"
    assert perdidas[0].startswith("nlp_degradation_mark/"), perdidas
    assert perdidas[0].endswith("test/timeout"), (
        "el motivo original tiene que viajar para que la pérdida sea rastreable")


def test_record_nlp_degradation_backend_camino_sano_no_cuenta_perdida(monkeypatch):
    """Sin regresión de comportamiento observable (#105): con Redis sano la marca se ESCRIBE y
    NO se cuenta ninguna pérdida — la degradación es exactamente igual de ruidosa que antes,
    ni más ni menos. Sólo cambia la robustez del camino de fallo."""

    class _RedisSano:
        def __init__(self):
            self.datos = {}

        def set(self, key, value, nx=False):
            if nx and key in self.datos:
                return False
            self.datos[key] = value
            return True

        def incr(self, key):
            self.datos[key] = int(self.datos.get(key, 0)) + 1
            return self.datos[key]

    sano = _RedisSano()
    monkeypatch.setattr(audit_service, "get_redis", lambda: sano)
    perdidas = []
    monkeypatch.setattr(audit_service, "record_audit_loss",
                        lambda reason="": perdidas.append(reason))

    audit_service.record_nlp_degradation(reason="test/sano")

    assert sano.datos.get(audit_service.REDIS_KEY_NLP_DEGRADED_SINCE), "la marca no se escribió"
    assert int(sano.datos[audit_service.REDIS_KEY_NLP_DEGRADED_COUNT]) == 1
    assert perdidas == [], "con Redis sano no hay pérdida que contar (comportamiento sin cambio)"


@pytest.mark.asyncio
async def test_marcar_nlp_degradado_motor_con_timeout_no_propaga_y_cuenta_perdida(monkeypatch):
    """Espejo del anterior en el plano motor: una marca que timeoutea no tumba el request y la
    pérdida se cuenta reutilizando `_contar_perdida` (mismo `basa:audit:lost`)."""
    import redis.asyncio as redis_lib

    class _Pipe:
        def set(self, *a, **k):
            pass

        def incr(self, *a, **k):
            pass

        async def execute(self):
            raise redis.exceptions.TimeoutError("Timeout reading from socket")

    class _RedisColgado:
        def __init__(self, **kwargs):
            pass

        def pipeline(self):
            return _Pipe()

        async def aclose(self):
            pass

    monkeypatch.setattr(redis_lib, "Redis", _RedisColgado)

    perdidas = []

    async def _spy(motivo):
        perdidas.append(motivo)

    monkeypatch.setattr(basa_guardrail, "_contar_perdida", _spy)

    # No propaga.
    await basa_guardrail._marcar_nlp_degradado()

    assert perdidas == ["nlp_degrade_mark"], (
        "la marca que no responde tiene que contarse reutilizando el contador de pérdidas")


# ══════════════════════════════════════════════════════════════════════════════════════
# (c) La marca síncrona NO corre inline en el event loop — se despacha a un hilo
# ══════════════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_la_marca_de_degradacion_no_bloquea_el_event_loop(monkeypatch):
    """`record_nlp_degradation` usa el cliente Redis SÍNCRONO; en el plano async `/gw` tiene
    que despacharse a un hilo para no frenar el event loop del worker en cada request
    degradada. Se mide por comportamiento: el `threading.get_ident()` con el que corre la
    marca tiene que ser DISTINTO al del event loop — si corriera inline, sería el mismo."""
    from src.api import gateway

    hilo_del_loop = threading.get_ident()
    capturado = {}

    def _spy_marca(reason=""):
        capturado["hilo"] = threading.get_ident()
        capturado["reason"] = reason

    monkeypatch.setattr(gateway, "record_nlp_degradation", _spy_marca)

    # `mask_body` cae la PRIMERA vez (analyzer abajo) y anda la segunda (fallback regex): es
    # justo lo que dispara la rama `degrade` de `evaluate_request_policy`.
    llamadas = {"n": 0}

    async def _mask_body(body, analyze, pmap):
        llamadas["n"] += 1
        if llamadas["n"] == 1:
            raise gateway.policy.NlpUnavailableError("sidecar caído")
        return None, {}

    monkeypatch.setattr(gateway.policy, "mask_body", _mask_body)

    body = {"model": "claude-3-5-sonnet-20241022",
            "messages": [{"role": "user", "content": "hola, escribile a a@b.es"}]}

    # profile=None ⇒ postura de producto por defecto (masking ON); nlp con `degrade` para que
    # la caída del analyzer se sirva con regex en vez de bloquear.
    await gateway.evaluate_request_policy(body, None, {"nlp_fail_mode": "degrade"})

    assert capturado.get("hilo") is not None, "la marca de degradación no llegó a ejecutarse"
    assert capturado["reason"] == "gateway/mask_body"
    assert capturado["hilo"] != hilo_del_loop, (
        "la marca corrió INLINE en el event loop — un Redis lento bloquearía el worker (#8). "
        "Tiene que despacharse a un hilo (asyncio.to_thread).")


# ══════════════════════════════════════════════════════════════════════════════════════
# Round 2 (a) — los OTROS 2 clientes async del motor (basa_audit_logger) también con timeouts
# ══════════════════════════════════════════════════════════════════════════════════════
# El contador de pérdidas de la fila DURABLE y el feed de la vitrina abrían `redis.asyncio`
# SIN timeouts. El feed corre en CADA request exitosa (incluidas las degradadas), así que el
# mismo Redis colgado que motiva el PR seguía colgando ese `pipe.execute()` para siempre.


class _PipeSano:
    def __getattr__(self, _name):  # incr/set/lpush/ltrim/expire → no-op
        return lambda *a, **k: None

    async def execute(self):
        return True


class _RedisCapturaKwargs:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def pipeline(self):
        return _PipeSano()

    async def aclose(self):
        pass


@pytest.mark.asyncio
async def test_registrar_perdida_del_logger_construye_redis_con_timeouts(monkeypatch):
    import redis.asyncio as redis_lib
    capturado = {}
    monkeypatch.setattr(redis_lib, "Redis",
                        lambda **kw: capturado.update(kw) or _RedisCapturaKwargs(**kw))

    await basa_audit_logger._registrar_perdida("motivo-de-prueba")

    assert _es_timeout_acotado(capturado.get("socket_timeout")), capturado
    assert _es_timeout_acotado(capturado.get("socket_connect_timeout")), capturado


@pytest.mark.asyncio
async def test_publish_monitor_event_del_logger_construye_redis_con_timeouts(monkeypatch):
    import redis.asyncio as redis_lib
    capturado = {}
    monkeypatch.setattr(redis_lib, "Redis",
                        lambda **kw: capturado.update(kw) or _RedisCapturaKwargs(**kw))

    await basa_audit_logger.basa_audit_logger_instance._publish_monitor_event(
        {}, [], "passed", {"messages": [{"role": "user", "content": "hola"}], "model": "m"})

    assert _es_timeout_acotado(capturado.get("socket_timeout")), capturado
    assert _es_timeout_acotado(capturado.get("socket_connect_timeout")), capturado


# ══════════════════════════════════════════════════════════════════════════════════════
# Round 2 (b) — el cliente se CIERRA aunque `pipe.execute()` timeoutee (no leak, aclose en finally)
# ══════════════════════════════════════════════════════════════════════════════════════
# Con `socket_timeout`, un execute que timeoutea es el camino COMÚN. Si `aclose()` fuera la
# última sentencia del `try`, se lo saltaría y el cliente quedaría sin cerrar (hasta 2 por
# request bajo NLP-down + Redis-lento). Tiene que cerrarse en `finally`.


class _RedisTimeoutEnExecute:
    """Doble cuyo `pipe.execute()` timeoutea; cuenta cuántas veces se cerró el cliente."""

    def __init__(self, cerrado, **kwargs):
        self._cerrado = cerrado

    def pipeline(self):
        cerrado = self._cerrado

        class _Pipe:
            def __getattr__(self, _name):
                return lambda *a, **k: None

            async def execute(self):
                raise redis.exceptions.TimeoutError("Timeout reading from socket")

        return _Pipe()

    async def aclose(self):
        self._cerrado["n"] += 1


@pytest.mark.asyncio
async def test_marcar_nlp_degradado_cierra_el_cliente_aunque_execute_timeoutee(monkeypatch):
    import redis.asyncio as redis_lib
    cerrado = {"n": 0}
    monkeypatch.setattr(redis_lib, "Redis", lambda **kw: _RedisTimeoutEnExecute(cerrado, **kw))

    # Que el conteo de pérdida (que abre OTRO cliente) no interfiera con la cuenta de cierres.
    async def _noop(_motivo):
        pass

    monkeypatch.setattr(basa_guardrail, "_contar_perdida", _noop)

    await basa_guardrail._marcar_nlp_degradado()

    assert cerrado["n"] == 1, (
        "el cliente tiene que cerrarse en `finally` aunque `pipe.execute()` timeoutee — si no, "
        "se filtra una conexión por cada request degradada bajo Redis lento (#8)")


@pytest.mark.asyncio
async def test_contar_perdida_cierra_el_cliente_aunque_execute_timeoutee(monkeypatch):
    import redis.asyncio as redis_lib
    cerrado = {"n": 0}
    monkeypatch.setattr(redis_lib, "Redis", lambda **kw: _RedisTimeoutEnExecute(cerrado, **kw))

    await basa_guardrail._contar_perdida("motivo-de-prueba")

    assert cerrado["n"] == 1, "no leak: `aclose()` en `finally` aunque el execute timeoutee (#8)"


@pytest.mark.asyncio
async def test_publish_monitor_event_cierra_el_cliente_aunque_execute_timeoutee(monkeypatch):
    # #124: el 3er escritor async del motor (feed de la vitrina, corre en CADA request exitosa)
    # también tiene que cerrar en `finally` — le faltaba el test simétrico de los otros dos.
    import redis.asyncio as redis_lib
    cerrado = {"n": 0}
    monkeypatch.setattr(redis_lib, "Redis", lambda **kw: _RedisTimeoutEnExecute(cerrado, **kw))

    await basa_audit_logger.basa_audit_logger_instance._publish_monitor_event(
        {}, [], "passed", {"messages": [{"role": "user", "content": "hola"}], "model": "m"})

    assert cerrado["n"] == 1, (
        "el feed de la vitrina tiene que cerrar el cliente en `finally` aunque `pipe.execute()` "
        "timeoutee — si no, filtra una conexión por cada request exitosa bajo Redis lento (#8)")


@pytest.mark.parametrize("modname", ["src.services.redis_client", "basa_engine_redis"])
def test_env_float_robusto_no_revienta_por_env_vacio_o_malformado(monkeypatch, modname):
    # #124: un env vacío (`- VAR=` en compose) o malformado NO puede reventar el import del plano
    # (float("") → ValueError tumbaría todo). `_env_float` cae al default. Mismo criterio en los
    # dos sitios (backend `redis_client` + motor `basa_engine_redis`).
    import importlib
    _env_float = importlib.import_module(modname)._env_float
    monkeypatch.delenv("X_TIMEOUT_TEST_124", raising=False)
    assert _env_float("X_TIMEOUT_TEST_124", 1.0) == 1.0          # ausente → default
    monkeypatch.setenv("X_TIMEOUT_TEST_124", "")
    assert _env_float("X_TIMEOUT_TEST_124", 1.0) == 1.0          # vacío → default
    monkeypatch.setenv("X_TIMEOUT_TEST_124", "   ")
    assert _env_float("X_TIMEOUT_TEST_124", 1.0) == 1.0          # whitespace → default
    monkeypatch.setenv("X_TIMEOUT_TEST_124", "no-soy-float")
    assert _env_float("X_TIMEOUT_TEST_124", 1.0) == 1.0          # malformado → default (no ValueError)
    monkeypatch.setenv("X_TIMEOUT_TEST_124", "2.5")
    assert _env_float("X_TIMEOUT_TEST_124", 1.0) == 2.5          # válido → parseado

    # Round 2 (H1): parsear NO alcanza. Estos valores son floats legítimos para `float()` pero
    # dejan al cliente Redis SIN timeout efectivo (o con uno imposible), que es exactamente el
    # cuelgue que #105 mató ("nunca infinito"). Tienen que caer al default como el malformado.
    for absurdo in ("inf", "nan", "Infinity", "1e400", "-1", "0", "1e9"):
        monkeypatch.setenv("X_TIMEOUT_TEST_124", absurdo)
        assert _env_float("X_TIMEOUT_TEST_124", 1.0) == 1.0, (
            f"{absurdo!r} pasó crudo al cliente Redis — un timeout no finito, ≤0 o absurdamente "
            "grande equivale a no tener timeout")


@pytest.mark.parametrize("modname,constantes", [
    ("src.services.redis_client",
     ("REDIS_CONNECT_TIMEOUT_SECONDS", "REDIS_SOCKET_TIMEOUT_SECONDS")),
    ("basa_engine_redis",
     ("ENGINE_REDIS_CONNECT_TIMEOUT_SECONDS", "ENGINE_REDIS_SOCKET_TIMEOUT_SECONDS")),
])
@pytest.mark.parametrize("valor_env", ["", "1e9"], ids=["vacio", "fuera-de-rango"])
def test_las_constantes_de_timeout_estan_cableadas_a_env_float(
        monkeypatch, modname, constantes, valor_env):
    """Round 2 (H2): el test de arriba ejercita `_env_float` con un env SINTÉTICO, así que
    pasaría igual si las constantes reales volvieran a `float(os.getenv(...))` — la mutación
    que reinstala el bug. Acá se prueba el CABLEADO con las envs REALES, en sus DOS propiedades:
    con la env vacía el import sobrevive y cae al default (sin `_env_float`, `float("")`
    levanta ValueError y el reload revienta); con `"1e9"` (parsea, pero equivale a no tener
    timeout) la GUARDIA DE RANGO se aplica sobre las constantes — un wiring "simplificado" tipo
    `float(os.getenv(...) or 1.0)` sobrevive el caso vacío pero deja pasar el 1e9 crudo.

    El módulo del motor se importa por su nombre PELADO (`basa_engine_redis`), que es como lo
    importan las extensiones en producción."""
    import importlib
    modulo = importlib.import_module(modname)
    try:
        with monkeypatch.context() as m:
            m.setenv("REDIS_SOCKET_TIMEOUT_SECONDS", valor_env)
            m.setenv("REDIS_CONNECT_TIMEOUT_SECONDS", valor_env)
            recargado = importlib.reload(modulo)
            for nombre in constantes:
                assert getattr(recargado, nombre) == 1.0, (
                    f"{modname}.{nombre} no pasa por `_env_float` completo — con la env "
                    f"{valor_env!r} tendría que caer al default de 1.0")
    finally:
        # Restauración OBLIGATORIA: el reload de arriba dejó el módulo con las envs de prueba
        # (y, en el backend, con el singleton `_client` en None). Con el monkeypatch ya
        # deshecho, un reload final devuelve el estado real y no envenena a los otros tests.
        importlib.reload(modulo)
