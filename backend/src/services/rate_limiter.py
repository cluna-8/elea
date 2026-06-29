import logging
from typing import Optional
from uuid import UUID

from .redis_client import get_redis

logger = logging.getLogger("basa-secure-gateway.rate_limiter")

WINDOW_SECONDS = 60


class RateLimitExceeded(Exception):
    def __init__(self, message: str, retry_after: int = WINDOW_SECONDS):
        self.message = message
        self.retry_after = retry_after
        super().__init__(message)


def _incr_with_expire(r, redis_key: str, amount: int = 1) -> int:
    val = r.incrby(redis_key, amount)
    if val == amount:
        r.expire(redis_key, WINDOW_SECONDS)
    return val


def check_rpm(key_id: UUID, rpm_limit: int) -> int:
    """
    Increment and validate RPM counter. Returns remaining requests.
    Call before the LLM request. Raises RateLimitExceeded if over limit.
    Fail-open if Redis unavailable.
    """
    if rpm_limit <= 0:
        return 999
    r = get_redis()
    if r is None:
        return rpm_limit
    kid = str(key_id)
    rpm_key = f"ratelimit:key:{kid}:rpm"
    try:
        val = _incr_with_expire(r, rpm_key)
        if val > rpm_limit:
            ttl = r.ttl(rpm_key)
            raise RateLimitExceeded(
                "Límite de solicitudes por minuto superado. Inténtelo de nuevo en breve.",
                retry_after=ttl if ttl > 0 else WINDOW_SECONDS,
            )
        return max(0, rpm_limit - val)
    except RateLimitExceeded:
        raise
    except Exception as e:
        logger.warning(f"RPM check failed for key {kid}: {e} — skipping")
        return rpm_limit


def check_tpm(key_id: UUID, tpm_limit: int, tokens_used: int) -> int:
    """
    Increment TPM counter by tokens_used. Returns remaining tokens.
    Call after the LLM response. Raises RateLimitExceeded if over limit.
    Fail-open if Redis unavailable.
    """
    if tpm_limit <= 0 or tokens_used <= 0:
        return tpm_limit
    r = get_redis()
    if r is None:
        return tpm_limit
    kid = str(key_id)
    tpm_key = f"ratelimit:key:{kid}:tpm"
    try:
        val = _incr_with_expire(r, tpm_key, tokens_used)
        if val > tpm_limit:
            ttl = r.ttl(tpm_key)
            raise RateLimitExceeded(
                "Límite de tokens por minuto superado. Inténtelo de nuevo en breve.",
                retry_after=ttl if ttl > 0 else WINDOW_SECONDS,
            )
        return max(0, tpm_limit - val)
    except RateLimitExceeded:
        raise
    except Exception as e:
        logger.warning(f"TPM check failed for key {kid}: {e} — skipping")
        return tpm_limit
