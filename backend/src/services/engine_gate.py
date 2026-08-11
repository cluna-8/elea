"""Tope de ADMISIÓN hacia el motor de IA: rechazo rápido en vez de cola infinita (nodo C1).

El incidente que este módulo cierra (sede, 30-jul) no fue del motor: fue del PRODUCTO ENTERO.
La cadena, verificada:

1. Las generaciones largas del modelo local se **serializan** en ollama, que encola FIFO y
   **sin tope**. Un pico de chats no se sirve en paralelo: se apila.
2. Cada chat en vuelo **retiene su conexión Postgres** durante todo el `await` al motor —el
   único `commit` del endpoint está DESPUÉS de la llamada (`chat.py`, `log_transaction`)—,
   o sea hasta `BASA_ENGINE_TIMEOUT_SECONDS` (150 s en la sede) por pedido.
3. Con ~30 pedidos en vuelo por worker se agota el pool (`database.py`: `pool_size=10` +
   `max_overflow=20` = 30). El `acquire` de SQLAlchemy es **síncrono**: al agotarse, congela
   el event loop del worker.
4. A partir de ahí no contesta NADA —ni login, ni health, ni admin—, aunque lo único lento
   fuera el modelo. Y nadie rechazaba en admisión: todos entraban a esperar.

El fix es de admisión, no de motor: **un tope de pedidos en vuelo hacia el motor por
proceso, con timeout de adquisición**. El pedido 9.º espera un poco; si en
`BASA_ENGINE_QUEUE_TIMEOUT_SECONDS` no hay turno, se lo rechaza con un 503 honesto y
AUDITADO en vez de dejarlo aparcado consumiendo una conexión del pool. Se degrada el chat,
no el producto.

Por qué acá y no en el motor: el tope del motor (`litellm`) y el del runtime local van en su
propio PR de configuración; este módulo es la puerta del **backend**, que es quien tiene las
conexiones que se agotan. Los dos son necesarios y ninguno reemplaza al otro.

Alcance deliberado: gatea el camino al MOTOR (chat del backend + byok de `/gw`). El
passthrough de suscripción no se gatea — su upstream es cloud, escala solo y no es el lento.
"""
import asyncio
import logging
import math
import os
from typing import Optional

logger = logging.getLogger("basa-secure-gateway.engine_gate")


# `compliance_status` del rechazo por capacidad.
#
# NO empieza con `blocked` A PROPÓSITO. El filtro canónico de compliance —el que usan la
# vitrina, el dashboard y los tests de la 031— es `compliance_status LIKE 'blocked%'`
# (`chat.py`, docstring de `_registrar_bloqueo`), y significa **«el firewall impidió este
# pedido por política»**. Un rechazo por capacidad no es eso: no lo bloqueó ninguna capa, no
# hubo dato personal ni secreto ni práctica prohibida, y contarlo entre los bloqueos le
# mentiría al officer que audita cuántos intentos se impidieron. Es un `rejected_*`: el
# pedido no se sirvió, y el motivo es nuestro, no suyo.
STATUS_SATURATED = "rejected_saturated"

# Contrato de wire del rechazo por capacidad (acordado con el equipo del harness).
#
# `X-Basa-Rejected: saturated` viaja en TODO 503 de saturación, en los dos planos. Es lo que
# distingue **nuestro** rechazo de admisión de un 503 genérico de Caddy, del proxy de la sede o
# del propio motor: los tres se ven igual desde afuera, y el harness de carga no puede estar
# adivinando por el copy del body cuál es cuál. Un header y no sólo un campo del body porque el
# byok de `/gw` responde con la forma de error de Anthropic (que no tiene dónde meter un código
# nuestro sin romper el shape que parsean las coding tools) y porque un cliente que sólo mira
# cabeceras —o un stream ya abierto— igual lo ve.
HEADER_REJECTED = "X-Basa-Rejected"
HEADER_REJECTED_SATURATED = "saturated"


class EngineSaturatedError(Exception):
    """No hubo turno hacia el motor dentro del timeout de admisión.

    Excepción del módulo y no `HTTPException`: quién traduce esto a respuesta HTTP —y con qué
    copy, y con qué fila de auditoría— es decisión de cada plano (el chat responde JSON de
    FastAPI, `/gw` responde con la forma de error de Anthropic). Acá sólo se afirma el hecho.
    """


# ── Envs con guardia de rango (mismo criterio sellado en el gate de #131) ──────────
#
# Los helpers son gemelos de `redis_client._env_float` y por la MISMA razón: un env ausente o
# vacío (`- VAR=` en compose) es "no seteado" y cae al default **en silencio**; un valor
# malformado, no finito o fuera de rango se loguea como warning y cae al default. Parsear no
# alcanza —`inf`, `nan` y `1e9` son floats legítimos para `float()`— y justamente esos son los
# valores que reinstalan el bug que el módulo vino a matar: un tope absurdo es no tener tope.
#
# El rango no se hereda de Redis: son dominios distintos y cada techo se justifica en su
# constante.


def _env_int(name: str, default: int, *, minimo: int, maximo: int) -> int:
    """Entero ACOTADO desde env: ausente/vacío → default silencioso; malformado o fuera de
    `[minimo, maximo]` → warning + default. Nunca levanta: un typo en un env no puede tumbar
    el import del plano entero."""
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        valor = int(raw.strip())
    except ValueError:
        logger.warning("%s=%r no es un entero válido; usando default %d", name, raw, default)
        return default
    if not minimo <= valor <= maximo:
        logger.warning("%s=%r fuera del rango válido (%d..%d); usando default %d",
                       name, raw, minimo, maximo, default)
        return default
    return valor


def _env_float(name: str, default: float, *, maximo: float) -> float:
    """Float ACOTADO desde env: ausente/vacío → default silencioso; malformado, no finito,
    ≤ 0 o > `maximo` → warning + default. Idéntico en forma y en porqué a
    `redis_client._env_float`; sólo cambia el techo, que es del dominio de cada valor."""
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        valor = float(raw)
    except ValueError:
        logger.warning("%s=%r no es un float válido; usando default %.3f", name, raw, default)
        return default
    if not math.isfinite(valor) or not 0 < valor <= maximo:
        logger.warning("%s=%r fuera del rango válido (finito, 0 < v <= %.1f); usando default %.3f",
                       name, raw, maximo, default)
        return default
    return valor


# Pedidos en vuelo hacia el motor POR PROCESO. El total de la instalación es
# `MAX_CONCURRENCY × WEB_CONCURRENCY` (los workers no comparten memoria, así que el semáforo
# tampoco).
#
# La aritmética del default (8), que es lo que lo hace defendible y no un número lindo:
#   * el modelo local drena 1-2 generaciones a la vez (ollama serializa), así que un tope de 8
#     ya deja cola de sobra para absorber ráfagas sin que nadie espere de más;
#   * cada pedido aparcado retiene UNA conexión del pool, y el pool son 30 por proceso
#     (`pool_size=10 + max_overflow=20`): con 8 aparcados quedan ~22 conexiones libres por
#     worker para login, admin, health y el resto del producto. Eso es exactamente lo que se
#     rompió en la sede — el chat lento se llevaba puesto todo lo demás.
# Techo 64: por encima de eso el tope deja de proteger el pool y vuelve a ser una cola.
ENGINE_MAX_CONCURRENCY = _env_int("BASA_ENGINE_MAX_CONCURRENCY", 8, minimo=1, maximo=64)

# Cuánto espera un pedido su turno antes de que se lo rechace. Corto a propósito: la promesa
# del fix es «te digo que no rápido», no «te hago esperar un poco menos». Techo 60 s para que
# nadie pueda reinstalar la cola infinita por env — un queue-timeout de 600 s es la cola de
# la sede con otro nombre.
ENGINE_QUEUE_TIMEOUT_SECONDS = _env_float("BASA_ENGINE_QUEUE_TIMEOUT_SECONDS", 5.0, maximo=60.0)

# `Retry-After` del 503. Segundos, como string porque va a una cabecera HTTP.
#
# DERIVADO del queue-timeout y no un "5" fijo (H9 del gate de #135): lo que el header promete es
# «en tanto puede haber turno», y el tiempo que de verdad tarda en decidirse un turno es el
# queue-timeout configurado. Con el default (5 s) da exactamente el mismo "5" de siempre, pero
# una instalación que suba la espera a 20 s deja de mandar a todos sus clientes a reintentar a
# los 5 —justo cuando el pico todavía está—, que es la estampida que el fix vino a evitar.
# `ceil` + piso de 1: el header es en segundos ENTEROS y un `Retry-After: 0` es "reintentá ya".
RETRY_AFTER_SATURATED = str(max(1, math.ceil(ENGINE_QUEUE_TIMEOUT_SECONDS)))

# Timeout de la llamada AL MOTOR del plano CHAT. Reemplaza al parser propio de `chat.py`
# (`_resolve_engine_timeout`, sin guardia de rango: un `1e9` pasaba crudo y dejaba la llamada
# efectivamente sin timeout). Mismo nombre de env que antes: las instalaciones que ya lo setean
# no cambian nada.
# Techo 600 y no 60 como en Redis: son dominios distintos. Una generación local legítima puede
# tardar minutos; una operación de Redis sana tarda menos de un milisegundo.
ENGINE_TIMEOUT_SECONDS = _env_float("BASA_ENGINE_TIMEOUT_SECONDS", 60.0, maximo=600.0)

# Timeout TOTAL del byok no-stream de `/gw`. Env PROPIA y no la del chat (H3 del gate de #135):
# compartirlas parecía economía y era una regresión silenciosa —este camino tenía `120.0`
# hardcodeado y pasaba a heredar el default 60 del chat—, o sea que un byok legítimo que antes
# se servía empezaba a cortarse solo a la mitad.
#
# Default 150 s por la misma regla que fija el read del stream: el que ESPERA tiene que aguantar
# más que el que TRABAJA. El router del motor en el perfil prod espera 120 s por generación, así
# que cualquier techo nuestro por debajo de eso convierte una respuesta lenta pero buena en un
# error nuestro, y encima con el trabajo del modelo ya pagado.
#
# Los dos planos siguen siendo configurables por separado a propósito: el chat es una UI con una
# persona esperando (60 s es una eternidad ahí) y el byok es una coding tool que tolera —y
# necesita— generaciones largas.
GW_BYOK_TIMEOUT_SECONDS = _env_float("BASA_GW_BYOK_TIMEOUT_SECONDS", 150.0, maximo=600.0)

# Read timeout ENTRE CHUNKS del stream byok de `/gw`. Antes eran 60 s hardcodeados, heredados
# del passthrough de suscripción (donde Anthropic manda `ping` SSE periódicos y 60 s es
# holgado). El motor local no manda pings: entre el primer byte y el siguiente puede pasar
# tanto como tarde el modelo en generar, y a los 60 s la conexión se cortaba sola.
# Default 150 s por la misma regla que el perfil prod aplica al router del motor: el timeout de
# quien espera tiene que SUPERAR al de quien trabaja (allí, 120 s), o el que espera aborta
# primero y convierte una respuesta lenta en un error.
GW_BYOK_READ_TIMEOUT_SECONDS = _env_float("BASA_GW_BYOK_READ_TIMEOUT_SECONDS", 150.0, maximo=600.0)


# ── El semáforo del proceso ───────────────────────────────────────────────────────

_semaforo_actual: Optional[asyncio.BoundedSemaphore] = None
_loop_del_semaforo = None


def _semaforo() -> asyncio.BoundedSemaphore:
    """Semáforo del proceso, creado PEREZOSAMENTE sobre el loop que corre.

    Perezoso y no a nivel módulo porque una primitiva de asyncio se ata al event loop en el que
    se usa: construirla al importar (cuando todavía no hay loop, o hay uno que uvicorn va a
    descartar) la deja atada a un loop muerto, y a partir de ahí CADA pedido se lleva un
    `RuntimeError` — el fix contra un cuelgue convertido en una caída total.

    Por eso se recuerda también el loop: si el loop cambia (reinicio del worker, un test que
    monta la app en un loop nuevo), se reconstruye. Un semáforo atado a un loop que ya no
    existe no gatea nada; rebindear es lo honesto. En producción esto pasa UNA vez por worker:
    uvicorn tiene un solo loop por proceso y el semáforo vive lo que vive el worker.

    `BoundedSemaphore` y no `Semaphore`: un `release()` de más es un bug de contabilidad que
    silenciosamente sube el tope, y prefiero que reviente en el test a que la sede descubra que
    el tope creció solo.
    """
    global _semaforo_actual, _loop_del_semaforo
    loop = asyncio.get_running_loop()
    if _semaforo_actual is None or _loop_del_semaforo is not loop:
        _semaforo_actual = asyncio.BoundedSemaphore(ENGINE_MAX_CONCURRENCY)
        _loop_del_semaforo = loop
        logger.info("engine_gate: tope de admisión al motor = %d en vuelo por proceso "
                    "(queue_timeout=%.1fs)", ENGINE_MAX_CONCURRENCY,
                    ENGINE_QUEUE_TIMEOUT_SECONDS)
    return _semaforo_actual


class TurnoDelMotor:
    """Un turno de admisión hacia el motor. Se usa de dos formas, y las dos hacen falta:

    * **como context manager** (`async with adquirir_turno(): ...`) — el caso normal, para
      llamadas que empiezan y terminan dentro del mismo bloque (chat, byok no-stream);
    * **manual** (`await turno.adquirir()` … `turno.liberar()`) — para el streaming, donde el
      turno tiene que sobrevivir a la función que lo pidió y liberarse recién cuando el
      generador termina de drenar. Si se liberara al devolver el `StreamingResponse`, el tope
      no acotaría generaciones concurrentes REALES —que es justo lo que hay que acotar— sino
      el tiempo hasta el primer byte.

    `liberar()` es idempotente y sólo libera si se adquirió: un `release()` sobre un turno que
    nunca entró le regalaría un permiso al semáforo (con `BoundedSemaphore`, un `ValueError`).
    """

    __slots__ = ("_adquirido", "_semaforo_propio")

    def __init__(self) -> None:
        self._adquirido = False
        # Semáforo que dio el permiso. Se guarda al adquirir y se suelta sobre ÉL —nunca sobre
        # el que `_semaforo()` devuelva al liberar—: entre las dos cosas puede haber un rebind
        # (loop nuevo del worker, un test que monta la app en otro loop) y entonces el permiso
        # se devolvería a un semáforo que jamás lo entregó. Eso es doble daño: el nuevo se
        # infla (o revienta con `ValueError`, que es lo que hace `BoundedSemaphore`) y el viejo
        # se queda encogido para siempre. Ver H5 del gate de #135.
        self._semaforo_propio: Optional[asyncio.BoundedSemaphore] = None

    @property
    def adquirido(self) -> bool:
        return self._adquirido

    async def adquirir(self) -> "TurnoDelMotor":
        """Espera turno hasta `ENGINE_QUEUE_TIMEOUT_SECONDS`. Al expirar: `EngineSaturatedError`.

        `wait_for` cancela el `acquire()` pendiente al vencer, así que el pedido rechazado deja
        de ser un waiter: no hereda un permiso que llegue tarde ni queda en la cola del
        semáforo. Eso es lo que hace que el rechazo sea de verdad "no entrás" y no "entrás
        después".
        """
        sem = _semaforo()
        try:
            await asyncio.wait_for(sem.acquire(), timeout=ENGINE_QUEUE_TIMEOUT_SECONDS)
        except asyncio.TimeoutError as exc:
            raise EngineSaturatedError(
                f"sin turno hacia el motor tras {ENGINE_QUEUE_TIMEOUT_SECONDS:.1f}s "
                f"(tope={ENGINE_MAX_CONCURRENCY} en vuelo por proceso)") from exc
        self._adquirido = True
        self._semaforo_propio = sem
        return self

    def liberar(self) -> None:
        """Devuelve el permiso AL semáforo que lo dio. Sync e idempotente a propósito: es lo
        que permite llamarla como PRIMERA sentencia de un `finally`, donde una cancelación en
        vuelo hace que cualquier `await` posterior no llegue a ejecutarse nunca."""
        if not self._adquirido:
            return
        self._adquirido = False
        sem, self._semaforo_propio = self._semaforo_propio, None
        if sem is not None:
            sem.release()

    async def __aenter__(self) -> "TurnoDelMotor":
        return await self.adquirir()

    async def __aexit__(self, *_exc) -> bool:
        # Liberación garantizada pase lo que pase en el cuerpo —incluido un timeout del motor o
        # una `HTTPException`—, pero SÓLO si se llegó a adquirir. No se traga la excepción.
        self.liberar()
        return False


def adquirir_turno() -> TurnoDelMotor:
    """Turno de admisión hacia el motor. Ver `TurnoDelMotor` para las dos formas de uso."""
    return TurnoDelMotor()
