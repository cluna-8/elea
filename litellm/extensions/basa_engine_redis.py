"""Construcción de clientes Redis async del motor con timeouts SIEMPRE puestos (#8 de #105).

Punto ÚNICO donde se fijan ``socket_timeout`` y ``socket_connect_timeout`` para los clientes
``redis.asyncio`` de las extensiones del motor. El default de ``redis.asyncio`` es SIN timeout
de operación: una escritura contra un Redis lento o colgado se queda esperando para siempre, y
en el camino de degradación NLP —que abre un cliente NUEVO por request— eso cuelga el worker.
Al pasar TODA construcción por acá, ningún cliente async del motor puede nacer sin timeouts: los
cuatro escritores (marca y contador del guardrail; contador de pérdidas y feed de la vitrina del
logger) usan este helper, así el próximo que se agregue tampoco puede olvidarlos.

El caller importa ``redis.asyncio`` él mismo —así su manejo de ``ImportError`` (redis es
opcional en la imagen) vive donde siempre vivió— y es dueño del ciclo de vida: abre acá, usa, y
cierra en ``finally``. El cierre NO se hace acá a propósito: un ``aclose()`` al final del
``try`` se saltaría cuando ``pipe.execute()`` timeoutea —el camino que estos timeouts vuelven
COMÚN— y filtraría el cliente. Cada escritor cierra en ``finally``.
"""
import os

# Mismos nombres de env que el backend (`services/redis_client.py`), y sub-segundo por default:
# holgado para un Redis sano (ops < 1 ms) y acota el peor caso a ~1 s en vez de infinito.
ENGINE_REDIS_CONNECT_TIMEOUT_SECONDS = float(os.getenv("REDIS_CONNECT_TIMEOUT_SECONDS", "1.0"))
ENGINE_REDIS_SOCKET_TIMEOUT_SECONDS = float(os.getenv("REDIS_SOCKET_TIMEOUT_SECONDS", "1.0"))


def async_redis_con_timeouts(redis_lib, host, port):
    """``redis_lib.Redis(host, port)`` con AMBOS timeouts acotados SIEMPRE (#8).

    ``redis_lib`` es el módulo ``redis.asyncio`` que el caller ya importó (mantiene ahí su
    propio manejo de ``ImportError``). Devuelve el cliente sin abrir conexión —redis.asyncio
    conecta perezosamente en la primera operación—, así que el caller sigue siendo quien lo
    cierra en ``finally``."""
    return redis_lib.Redis(
        host=host, port=port,
        socket_timeout=ENGINE_REDIS_SOCKET_TIMEOUT_SECONDS,
        socket_connect_timeout=ENGINE_REDIS_CONNECT_TIMEOUT_SECONDS,
    )
