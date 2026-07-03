import os
import logging
import redis

logger = logging.getLogger("basa-secure-gateway.redis")

_client: redis.Redis | None = None


def get_redis() -> redis.Redis | None:
    global _client
    if _client is not None:
        return _client
    host = os.getenv("REDIS_HOST", "eu-redis")
    port = int(os.getenv("REDIS_PORT", "6379"))
    try:
        _client = redis.Redis(host=host, port=port, db=0, decode_responses=True, socket_connect_timeout=2)
        _client.ping()
        logger.info(f"Redis connected: {host}:{port}")
    except Exception as e:
        logger.warning(f"Redis unavailable ({host}:{port}): {e} — rate limiting disabled")
        _client = None
    return _client
