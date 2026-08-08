import math
import os
import logging
import redis

logger = logging.getLogger("basa-secure-gateway.redis")

_client: redis.Redis | None = None

# Timeouts ACOTADOS del cliente Redis compartido (hallazgo #8 de #105). El default de
# redis-py es SIN timeout de operación: una lectura/escritura contra un Redis lento o colgado
# se queda pegada para siempre. En el camino de degradación NLP —que corre en CADA request
# mientras el analyzer está caído— eso bloquea un worker de forma indefinida justo cuando el
# sistema ya está tocado. Con timeouts, una marca de degradación que no responde falla RÁPIDO
# (el caller la cuenta como pérdida y sigue) en vez de colgar el pedido. Nunca infinito.
#   * socket_connect_timeout: techo del handshake TCP (antes era 2 s; se acota).
#   * socket_timeout: techo de CADA operación una vez conectado (el que faltaba).
# Env-tuneables, pero con default sub-segundo: para un Redis sano (ops < 1 ms) es holgado.
# Techo duro de cualquier timeout tuneable por env. Un valor absurdo (`inf`, `1e9`) equivale a
# NO tener timeout y reinstala el cuelgue que este módulo existe para evitar; 60 s ya es
# holgadísimo para cualquier op de Redis sana.
_MAX_TIMEOUT_SECONDS = 60.0


def _env_float(name: str, default: float) -> float:
    """Float ACOTADO desde env: ausente/vacío/malformado/fuera de rango → `default`. Un
    `float("")` reventaría el import (ValueError) y tumbaría el plano ENTERO por un env vacío
    (`- VAR=` en compose) o un typo — desproporcionado para un timeout. Vacío se trata como
    'no seteado' (silencioso); un valor no-float se loguea como warning y cae al default.
    Además del parse se valida el RANGO (finito, > 0 y ≤ `_MAX_TIMEOUT_SECONDS`): `inf`,
    `nan` y `1e400` parsean SIN error pero dejan al cliente Redis sin timeout efectivo, que
    es exactamente el cuelgue que "nunca infinito" vino a matar."""
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        valor = float(raw)
    except ValueError:
        logger.warning("%s=%r no es un float válido; usando default %.3f", name, raw, default)
        return default
    if not math.isfinite(valor) or not 0 < valor <= _MAX_TIMEOUT_SECONDS:
        logger.warning(
            "%s=%r fuera del rango válido (finito, 0 < v <= %.1f s); usando default %.3f",
            name, raw, _MAX_TIMEOUT_SECONDS, default)
        return default
    return valor


REDIS_CONNECT_TIMEOUT_SECONDS = _env_float("REDIS_CONNECT_TIMEOUT_SECONDS", 1.0)
REDIS_SOCKET_TIMEOUT_SECONDS = _env_float("REDIS_SOCKET_TIMEOUT_SECONDS", 1.0)


def get_redis() -> redis.Redis | None:
    global _client
    if _client is not None:
        return _client
    host = os.getenv("REDIS_HOST", "eu-redis")
    port = int(os.getenv("REDIS_PORT", "6379"))
    try:
        _client = redis.Redis(
            host=host, port=port, db=0, decode_responses=True,
            socket_connect_timeout=REDIS_CONNECT_TIMEOUT_SECONDS,
            socket_timeout=REDIS_SOCKET_TIMEOUT_SECONDS,
        )
        _client.ping()
        logger.info(f"Redis connected: {host}:{port}")
    except Exception as e:
        logger.warning(f"Redis unavailable ({host}:{port}): {e} — rate limiting disabled")
        _client = None
    return _client
