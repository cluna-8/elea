"""Scheduler de la purga de retención (spec 018, FR-001 — T011).

Cuerpo de T011 escrito. El startup lo arranca: `main.py:89` llama
`retention_scheduler.start_scheduler()` (y `:94` lo para en el shutdown).

Por qué un thread daemon y no cron/celery: es el patrón que el producto ya tiene
(`licensing/reconcile.py::start_scheduler`, `:268-297`, con el `_loop` en `:285` y el
`threading.Thread(..., daemon=True)` en `:294`; el trío start/stop/running llega hasta `:309`
— único scheduler del proceso) y no suma dependencia nueva
— la caja se instala air-gap, donde cada dependencia extra es una negociación con el IT del
cliente. `Event.wait` no bloquea el event loop de FastAPI.

Por qué vive AFUERA de `services/retention/`: quién decide CUÁNDO se corre es una
preocupación distinta de QUÉ se borra. El purgador tiene que poder invocarse a mano
(`run_now`) sin arrastrar un thread, y los tests del purgador no deberían tener que apagar
un scheduler para correr.

**El tick no es la purga.** `SENTINEL_PURGE_INTERVAL_SECONDS` (default 3600) es cada cuánto se
DESPIERTA a mirar; si el momento cae fuera de `SENTINEL_PURGE_WINDOW` no hace nada y se vuelve a
dormir. Bajar el intervalo no purga más rápido: solo engancha la ventana antes.

`SENTINEL_PURGE_ENABLED` es el interruptor maestro: en `false` el thread ni arranca. Viene
APAGADO —también acá, en `DEFAULT_ENABLED`, no sólo en el `.env.example`— porque un job que
hace DELETE retroactivo no se enciende con un pull de imagen: la primera imagen nueva se
encontraría con el backlog de toda la vida de la caja y se lo llevaría de una, y lo borrado
no vuelve. La tensión con el Art. 5.1.e es real y está aceptada: una retención que todavía
no purga se arregla con un `true`; una purga que se encendió sola y borró de más no se
arregla con nada. Ya en operación se apaga además para un legal hold en curso.

Gotcha heredado del precedente (vale la pena leerlo antes de escribir T011): la suite apaga
la reconciliación con `SENTINEL_LICENSE_RECONCILE_INTERVAL_SECONDS=0` en `tests/conftest.py`
porque los tests que abren `TestClient(app)` disparan el lifespan y el job real correría
contra `SessionLocal` — la DB VIVA del compose, no la DB de test del override de `get_db`.
Acá el estropicio sería peor que contaminar un registry en memoria: este job BORRA FILAS. Por
eso la suite lo deja apagado con `SENTINEL_PURGE_ENABLED=false` y los tests que lo ejercitan lo
arrancan ellos, con intervalo y factory explícitos.
"""
import logging
import os
import threading
from typing import Optional

from .retention.purger import run_once

logger = logging.getLogger(__name__)

# Perillas propias del scheduler (tabla del plan, `.env.example`). Las de la corrida en sí
# —ventana, tamaño de lote, pausa— viven en `retention/purger.py`, con su consumidor.
ENV_ENABLED = "SENTINEL_PURGE_ENABLED"
ENV_INTERVAL_SECONDS = "SENTINEL_PURGE_INTERVAL_SECONDS"

# Apagado por default, igual que el `.env.example` y los dos composes. Este valor es el que
# manda en TODO arranque que no pase por esos composes —un `uvicorn` a mano, un manifiesto
# k8s/Zarf que no declare la variable, un test que instancie el scheduler—: si acá dijera
# `True`, el seguro viviría sólo en configuración y bastaría con olvidarse de una línea de
# env para que la purga se encienda sola. El encendido es un acto explícito del operador.
DEFAULT_ENABLED = False
DEFAULT_INTERVAL_SECONDS = 3600.0

# Estado del thread daemon, igual que `licensing/reconcile.py:72-73`: uno por proceso. Con
# `WEB_CONCURRENCY` workers ya hay un purgador por proceso; `start_scheduler` es idempotente
# para no multiplicarlo DENTRO del mismo proceso.
_thread: Optional[threading.Thread] = None
_stop = threading.Event()


def _interval_from_env() -> float:
    """`SENTINEL_PURGE_INTERVAL_SECONDS` → segundos; mismo criterio tolerante que reconcile
    (`_interval_from_env`, `:256-265`): valor ilegible ⇒ warning + default, nunca explota."""
    raw = os.getenv(ENV_INTERVAL_SECONDS, "")
    if not raw.strip():
        return DEFAULT_INTERVAL_SECONDS
    try:
        return float(raw)
    except ValueError:
        logger.warning("purga: %s=%r inválido, uso el default %ss",
                       ENV_INTERVAL_SECONDS, raw, DEFAULT_INTERVAL_SECONDS)
        return DEFAULT_INTERVAL_SECONDS


def _enabled_from_env() -> bool:
    """`SENTINEL_PURGE_ENABLED` → bool. La asimetría es la misma de `purger._dry_run_de_env`
    (`:425-443`) pero espejada: acá la perilla se llama en positivo (`ENABLED=true` = encendé)
    y el lado seguro es APAGADO, así que sólo un «sí» explícito enciende. Un typo (`ture`,
    `on `, `1x`) deja la purga apagada, que es el lado que no dispara un DELETE retroactivo.
    Vacío ⇒ `DEFAULT_ENABLED` (False), que manda en todo arranque sin la variable."""
    crudo = os.getenv(ENV_ENABLED, "")
    if not crudo.strip():
        return DEFAULT_ENABLED
    return crudo.strip().casefold() in {"true", "1", "yes", "on"}


def start_scheduler(interval_seconds: Optional[float] = None,
                    session_factory=None) -> Optional[threading.Thread]:
    """Arranca el thread daemon de purga; devuelve `None` si queda desactivado.

    Desactivado = `SENTINEL_PURGE_ENABLED` en false o intervalo <= 0 (mismo criterio que
    `reconcile.start_scheduler`, para que un operador no tenga que aprender dos vocabularios
    de apagado). Idempotente: si el thread ya está vivo, se devuelve ese y no se arranca otro
    — con `WEB_CONCURRENCY` workers ya hay un purgador por proceso, y duplicarlo dentro del
    mismo proceso solo multiplica la competencia por la tabla.

    Una corrida que explota NUNCA mata al thread: se loguea y se reintenta en el próximo
    tick (precedente `reconcile.py`). Un scheduler que muere en silencio es retención que
    dejó de existir sin que nadie se entere.
    """
    global _thread
    if interval_seconds is None:
        interval_seconds = _interval_from_env()
    # Doble compuerta (frente a la única de reconcile): el master switch se suma al intervalo
    # porque un job que hace DELETE retroactivo no se enciende con un pull de imagen. Cualquiera
    # de las dos en «apagado» deja el thread sin arrancar.
    enabled = _enabled_from_env()
    if not enabled or interval_seconds <= 0:
        logger.info("purga: scheduler DESACTIVADO (%s=%s, intervalo=%ss)",
                    ENV_ENABLED, "on" if enabled else "off", interval_seconds)
        return None
    if _thread is not None and _thread.is_alive():
        return _thread
    _stop.clear()

    def _loop():
        while not _stop.is_set():
            try:
                run_once(session_factory=session_factory)
            except Exception:  # noqa: BLE001 — el job jamás muere: la próxima corrida reintenta
                logger.exception("purga: corrida fallida, reintento en %ss", interval_seconds)
            _stop.wait(interval_seconds)

    _thread = threading.Thread(target=_loop, name="sentinel-retention-purge", daemon=True)
    _thread.start()
    logger.info("purga: scheduler activo cada %ss (100%% local)", interval_seconds)
    return _thread


def stop_scheduler() -> None:
    """Corta el thread y espera a que termine (shutdown del backend y tests)."""
    global _thread
    _stop.set()
    if _thread is not None:
        _thread.join(timeout=5)
    _thread = None


def scheduler_running() -> bool:
    """¿Hay un thread de purga vivo?

    Consumidor de producción: `main.py:161` lo expone en `/health` como
    `purge_scheduler_running` (booleano, sin I/O). El wiring del startup está en
    `main.py:89` (`start_scheduler()`).
    """
    return _thread is not None and _thread.is_alive()


def reset_for_tests() -> None:
    """Deja el módulo sin thread vivo (para el teardown de los tests, como reconcile)."""
    stop_scheduler()
