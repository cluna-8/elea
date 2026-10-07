"""Autorización interna pasarela→motor — API de la pasarela.

La implementación vive en `sentinel/engine/redirect_authz.py` porque el guard del motor la
necesita y ese directorio se copia plano al motor (S9); aquí solo se re-exporta.
"""
from sentinel.engine.redirect_authz import (  # noqa: F401
    CLOCK_SKEW,
    DEFAULT_TTL,
    HEADER,
    KEY_ENV,
    MAX_TTL,
    AuthzBadSignature,
    AuthzError,
    AuthzExpired,
    AuthzKeyMissing,
    AuthzMalformed,
    AuthzModelMismatch,
    Grant,
    issue,
    verify,
)
