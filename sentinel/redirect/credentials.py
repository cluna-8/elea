"""Credenciales de destino — API de la pasarela.

La implementación vive en `sentinel/engine/redirect_credentials.py` (la usa el guard dentro
del motor, copiado plano por S9); aquí solo se re-exporta. `resolve_env_refs` es exclusivo
del motor: la pasarela nunca resuelve `env:` (manda la referencia en la autorización).
"""
from sentinel.engine.redirect_credentials import (  # noqa: F401
    CLIENT_CREDENTIAL_FIELDS,
    DEFAULT_API_BASE,
    ENV_DENY_FRAGMENTS,
    ENV_DENYLIST,
    ENV_PREFIX,
    FAMILIES,
    FORWARDABLE_HEADERS,
    PROVIDER_FAMILY,
    REQUIRES_API_BASE,
    SHAPES,
    PRICE_FIELDS,
    CredentialError,
    validate_price,
    engine_model_for,
    env_name_allowed,
    family_for,
    family_model,
    filter_forward_headers,
    is_env_ref,
    redacted,
    requires_api_base,
    requires_secret,
    resolve_env_refs,
    split_family_model,
    strip_client_credentials,
    to_litellm_params,
    validate_credential,
)
