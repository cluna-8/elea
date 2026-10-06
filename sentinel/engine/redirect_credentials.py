"""Credenciales de destino por proveedor y parámetros del motor (data-model §2; research D14, R13).

Vive en `sentinel/engine/` porque lo usa el guard dentro del motor (se copia plano al directorio
de extensiones por S9); la pasarela lo importa vía `sentinel.redirect.credentials`.
Solo stdlib: sin dependencias del paquete ni de la base.

Una credencial es un dict con la forma de su proveedor. Cada valor puede ser el secreto (que
la pasarela descifra del almacén y re-cifra en la autorización interna) o, **solo para
destinos de instalación**, una referencia `env:<NOMBRE>` que se resuelve únicamente del lado del
motor desde su entorno: el valor nunca viaja por la red.
Las referencias de los destinos de la política llevan el prefijo `REDIRECT_CRED_`; las credenciales
del catálogo adoptadas del archivo de config (069, fuente única) pueden usar cualquier nombre de
variable fuera de la **lista negra común** (`ENV_DENYLIST`/`ENV_DENY_FRAGMENTS`, una sola definición
que reutiliza `sentinel/catalog/credentials.py`): así una referencia no lee la llave maestra, las
claves de cifrado ni la base y las manda a una base elegida por quien carga el destino.
"""
from __future__ import annotations

import json
import re
from typing import Any, Mapping, Optional

# familia estable (entrada comodín del fragmento de perfil) → prefijo de proveedor del motor
FAMILIES = {
    "rdx-openai": "openai",            # OpenAI real (tiene API Responses)
    "rdx-azure": "azure",
    "rdx-azure-ai": "azure_ai",
    "rdx-anthropic": "anthropic",
    "rdx-bedrock": "bedrock",
    "rdx-vertex": "vertex_ai",
    "rdx-deepseek": "deepseek",
    "rdx-gemini": "gemini",
    "rdx-groq": "groq",
    "rdx-zai": "zai",                  # 069 (spike S1): GLM
    "rdx-nvidia": "nvidia_nim",        # 069 (spike S1): Nemotron
    "rdx-mistral": "mistral",          # 069 (spike S1)
    "rdx-chatcompat": "hosted_vllm",   # compatibles-OpenAI solo-chat (R13 corrección 2)
}

PROVIDER_FAMILY = {
    "openai": "rdx-openai",
    "azure": "rdx-azure",
    "azure_ai": "rdx-azure-ai",
    "anthropic": "rdx-anthropic",
    "bedrock": "rdx-bedrock",
    "vertex_ai": "rdx-vertex",
    "deepseek": "rdx-deepseek",
    "gemini": "rdx-gemini",
    "groq": "rdx-groq",
    "openrouter": "rdx-chatcompat",
    "ollama": "rdx-chatcompat",
    "hosted_vllm": "rdx-chatcompat",
    "zai": "rdx-zai",
    "nvidia_nim": "rdx-nvidia",
    "mistral": "rdx-mistral",
    "openai_compatible": "rdx-chatcompat",
}

_API_KEY = ({"api_key"}, set())
SHAPES = {  # provider → (campos requeridos, opcionales)
    "openai": _API_KEY, "anthropic": _API_KEY, "openai_compatible": _API_KEY,
    "deepseek": _API_KEY, "openrouter": _API_KEY, "azure_ai": _API_KEY,
    "gemini": _API_KEY, "groq": _API_KEY,
    "zai": _API_KEY, "nvidia_nim": _API_KEY, "mistral": _API_KEY,
    "azure": ({"api_key", "api_version"}, set()),
    "bedrock": ({"aws_access_key_id", "aws_secret_access_key", "aws_region_name"}, {"aws_session_token"}),
    "vertex_ai": ({"vertex_credentials", "vertex_project", "vertex_location"}, set()),
    "ollama": (set(), {"api_key"}),
    "hosted_vllm": (set(), {"api_key"}),
}
REQUIRES_API_BASE = frozenset({"azure", "azure_ai", "ollama", "openai_compatible", "hosted_vllm"})
DEFAULT_API_BASE = {"openrouter": "https://openrouter.ai/api/v1"}
# hosted_vllm sin api_key cae al entorno del motor; un placeholder fijo lo evita
_NO_SECRET_PLACEHOLDER = "no-key"

ENV_PREFIX = "env:"
ENV_NAME_RE = re.compile(r"^REDIRECT_CRED_[A-Z0-9_]*[A-Z0-9]$")
# Cualquier otro nombre admitido (credenciales adoptadas): mayúsculas, dígitos y guion bajo
ENV_ANY_RE = re.compile(r"^[A-Z][A-Z0-9_]*[A-Z0-9]$")
# Variables que NUNCA se referencian como credencial de un modelo (lista negra común, 069 T142)
ENV_DENYLIST = frozenset({"LITELLM_MASTER_KEY", "SENTINEL_ENGINE_MASTER_KEY", "FERNET_SECRET_KEY",
                          "FERNET_PREVIOUS_KEYS", "JWT_SECRET_KEY", "DATABASE_URL", "POSTGRES_PASSWORD",
                          "REDIRECT_INTERNAL_KEY", "MASKING_NONCE_KEY"})
ENV_DENY_FRAGMENTS = ("MASTER_KEY", "PASSWORD", "DATABASE", "FERNET", "JWT", "POSTGRES", "INTERNAL_KEY",
                      "NONCE_KEY")


def env_name_allowed(name: Any) -> bool:
    """¿Puede una credencial de modelo referenciar esta variable? Formato válido y fuera de la lista negra."""
    return (isinstance(name, str) and bool(ENV_ANY_RE.match(name)) and name not in ENV_DENYLIST
            and not any(f in name for f in ENV_DENY_FRAGMENTS))

# lo que un cliente podría mandar para desviar a dónde o con qué credencial sale el pedido
CLIENT_CREDENTIAL_FIELDS = (
    "api_key", "api_base", "base_url", "api_version", "extra_headers",
    "organization", "azure_ad_token", "azure_ad_token_provider", "azure_username", "azure_password",
    "aws_access_key_id", "aws_secret_access_key", "aws_session_token", "aws_region_name",
    "aws_profile_name", "aws_role_name", "aws_web_identity_token", "aws_bedrock_runtime_endpoint",
    "vertex_credentials", "vertex_project", "vertex_location", "vertex_ai_project",
    "vertex_ai_location", "litellm_credential_name", "custom_llm_provider", "user_config",
    # preferencias de enrutamiento del proveedor (OpenRouter `provider`): las fija el guard (057 FR-032)
    "provider",
) + (
    # precio: lo fija el guard desde el destino o el mapa del motor; un cliente que manda precio 0
    # esquivaría el presupuesto (D23 de la 069)
    "input_cost_per_token", "output_cost_per_token", "input_cost_per_second", "output_cost_per_second",
    "cache_read_input_token_cost", "cache_creation_input_token_cost",
)

# prefijo con el que el mapa de precios del motor nombra al modelo real de cada proveedor
PRICE_MAP_PREFIX = {"openrouter": "openrouter", "deepseek": "deepseek", "anthropic": "anthropic",
                    "openai": "openai", "gemini": "gemini", "groq": "groq", "azure_ai": "azure_ai",
                    "bedrock": "bedrock", "vertex_ai": "vertex_ai"}
PRICE_FIELDS = ("input_per_mtok", "output_per_mtok")
# Precio de caché del destino (057 FR-046; opcional): lectura y escritura, USD por millón de tokens. Traducen a los parámetros
# de precio por pedido que el motor honra al calcular el costo con los tokens de caché que informa el destino.
CACHE_PRICE_PARAMS = {"cache_read_per_mtok": "cache_read_input_token_cost",
                      "cache_write_per_mtok": "cache_creation_input_token_cost"}


def validate_price(price: Any) -> None:
    """Precio del destino en USD por millón de tokens: entrada y salida (obligatorios) y, opcionales, lectura y escritura
    de caché; números ≥ 0, nada más."""
    if not isinstance(price, Mapping) or not set(PRICE_FIELDS) <= set(price) \
            or set(price) - set(PRICE_FIELDS) - set(CACHE_PRICE_PARAMS):
        raise ValueError("el precio lleva input_per_mtok y output_per_mtok (y opcionalmente cache_read_per_mtok y "
                         "cache_write_per_mtok)")
    for k in price:
        v = price[k]
        if isinstance(v, bool) or not isinstance(v, (int, float)) or v < 0:
            raise ValueError(f"{k} debe ser un número mayor o igual a 0")


def price_per_mtok(view: Any) -> Optional[dict]:
    """ÚNICA conversión del precio de una entrada del catálogo (USD por token: `input`, `output`, `cache_read`,
    `cache_write`) al precio por millón de tokens que firma la autorización (FR-049). `None` sin entrada y salida."""
    if not isinstance(view, Mapping) or view.get("input") is None or view.get("output") is None:
        return None
    out = {"input_per_mtok": float(view["input"]) * 1e6, "output_per_mtok": float(view["output"]) * 1e6}
    for key, name in (("cache_read", "cache_read_per_mtok"), ("cache_write", "cache_write_per_mtok")):
        if view.get(key) is not None:
            out[name] = float(view[key]) * 1e6
    return out


def cost_params(price: Optional[Mapping[str, Any]], provider: str, real_model: str,
                cost_map: Mapping[str, Any]) -> tuple:
    """Parámetros de precio por pedido y su fuente: el del destino, el del mapa del motor o ninguno.

    Con precio de caché del destino (o del mapa) suma `cache_read_input_token_cost` y `cache_creation_input_token_cost`; sin
    ellos el motor cobra la caché a precio de entrada y el guard lo marca (`price_cache_missing`).
    Sin precio el motor registra costo 0 para lo servido por comodín y el presupuesto no se
    descuenta (spike S1 de la 069)."""
    if price:
        params = {"input_cost_per_token": float(price["input_per_mtok"]) / 1e6,
                  "output_cost_per_token": float(price["output_per_mtok"]) / 1e6}
        for name, param in CACHE_PRICE_PARAMS.items():
            if price.get(name) is not None:
                params[param] = float(price[name]) / 1e6
        return params, "destination"
    prefix = PRICE_MAP_PREFIX.get(provider)
    candidates = ([f"{prefix}/{real_model}"] if prefix else []) + ([real_model] if prefix else [])
    for name in candidates:
        entry = cost_map.get(name) if hasattr(cost_map, "get") else None
        if isinstance(entry, Mapping) and entry.get("input_cost_per_token") is not None \
                and entry.get("output_cost_per_token") is not None:
            params = {"input_cost_per_token": float(entry["input_cost_per_token"]),
                      "output_cost_per_token": float(entry["output_cost_per_token"])}
            for param in CACHE_PRICE_PARAMS.values():
                if entry.get(param) is not None:
                    params[param] = float(entry[param])
            return params, "engine_map"
    return {}, "none"


# cabeceras de cliente que pueden seguir hacia un destino (nativo Anthropic, contrato cara Claude);
# todo lo demás de `headers` (reenvío de cabeceras del motor) se descarta en pedidos redirigidos
FORWARDABLE_HEADERS = frozenset({"anthropic-beta", "anthropic-version"})


def filter_forward_headers(headers):
    if not isinstance(headers, Mapping):
        return {}
    return {k: v for k, v in headers.items() if str(k).lower() in FORWARDABLE_HEADERS}


class CredentialError(ValueError):
    """Credencial con forma inválida o referencia no resoluble. Mensaje sin secretos."""


def family_for(provider: str) -> str:
    try:
        return PROVIDER_FAMILY[provider]
    except KeyError:
        raise CredentialError(f"proveedor desconocido: {provider!r}") from None


def family_model(provider: str, real_model: str) -> str:
    """Nombre que la pasarela manda al motor: `rdx-<familia>/<modelo real>`."""
    if not real_model:
        raise CredentialError("modelo real vacío")
    return f"{family_for(provider)}/{real_model}"


def split_family_model(model: str) -> Optional[tuple]:
    if not isinstance(model, str) or "/" not in model:
        return None
    fam, real = model.split("/", 1)
    if fam not in FAMILIES or not real:
        return None
    return fam, real


def engine_model_for(model: str) -> Optional[str]:
    """`rdx-chatcompat/qwen` → `hosted_vllm/qwen` (lo que resuelve la entrada comodín)."""
    parts = split_family_model(model)
    if parts is None:
        return None
    return f"{FAMILIES[parts[0]]}/{parts[1]}"


def requires_secret(provider: str) -> bool:
    return bool(SHAPES.get(provider, (set(), set()))[0])


def requires_api_base(provider: str) -> bool:
    return provider in REQUIRES_API_BASE


def is_env_ref(value: Any) -> bool:
    return isinstance(value, str) and value.startswith(ENV_PREFIX)


def _env_name(value: str, *, any_name: bool = True) -> str:
    """`any_name=False`: solo `REDIRECT_CRED_*` (destinos de la política); `True`: también cualquier
    nombre fuera de la lista negra (lo que resuelve el motor para credenciales adoptadas)."""
    name = value[len(ENV_PREFIX):]
    if ENV_NAME_RE.match(name) or (any_name and env_name_allowed(name)):
        return name
    raise CredentialError("referencia de entorno no permitida" if any_name
                          else "referencia de entorno no permitida (prefijo REDIRECT_CRED_ requerido)")


def validate_credential(provider: str, cred: Any, *, level: str, allow_any_env: bool = False) -> None:
    if provider not in SHAPES:
        raise CredentialError(f"proveedor desconocido: {provider!r}")
    if not isinstance(cred, Mapping):
        raise CredentialError("la credencial debe ser un objeto con los campos del proveedor")
    required, optional = SHAPES[provider]
    keys = set(cred)
    missing = required - keys
    if missing:
        raise CredentialError(f"faltan campos: {', '.join(sorted(missing))}")
    extra = keys - required - optional
    if extra:
        raise CredentialError(f"campos no admitidos: {', '.join(sorted(extra))}")
    for k, v in cred.items():
        if v is None or v == "" or v == {}:
            raise CredentialError(f"campo vacío: {k}")
        if is_env_ref(v):
            if level != "installation":
                raise CredentialError("referencias de entorno solo en destinos de instalación")
            _env_name(v, any_name=allow_any_env)


def resolve_env_refs(cred: Mapping[str, Any], environ: Mapping[str, str]) -> dict:
    """Solo del lado del motor. Nunca se llama en la pasarela."""
    out = {}
    for k, v in cred.items():
        if is_env_ref(v):
            name = _env_name(v)
            val = environ.get(name)
            if not val:
                raise CredentialError(f"variable de entorno sin valor para el campo {k}")
            out[k] = val
        else:
            out[k] = v
    return out


def to_litellm_params(provider: str, cred: Mapping[str, Any], api_base: Optional[str]) -> dict:
    """Parámetros por pedido para el motor. `api_base` sale del destino, nunca del pedido."""
    if provider not in SHAPES:
        raise CredentialError(f"proveedor desconocido: {provider!r}")
    for k, v in cred.items():
        if is_env_ref(v):
            raise CredentialError(f"referencia de entorno sin resolver en {k}")
    base = api_base or DEFAULT_API_BASE.get(provider)
    if requires_api_base(provider) and not base:
        raise CredentialError("el destino requiere dirección base")
    params: dict = {}
    if provider == "bedrock":
        for k in ("aws_access_key_id", "aws_secret_access_key", "aws_region_name", "aws_session_token"):
            if cred.get(k):
                params[k] = cred[k]
    elif provider == "vertex_ai":
        vc = cred["vertex_credentials"]
        params["vertex_credentials"] = vc if isinstance(vc, str) else json.dumps(vc)
        params["vertex_project"] = cred["vertex_project"]
        params["vertex_location"] = cred["vertex_location"]
    elif provider == "azure":
        params["api_key"] = cred["api_key"]
        params["api_version"] = cred["api_version"]
    elif provider in ("ollama", "hosted_vllm"):
        params["api_key"] = cred.get("api_key") or _NO_SECRET_PLACEHOLDER
    else:
        params["api_key"] = cred["api_key"]
    if base:
        params["api_base"] = base
    return params


def redacted(cred: Mapping[str, Any]) -> dict:
    """Vista para API/logs/kits: solo nombres de campo (FR-006)."""
    return {k: "***" for k in cred}


def strip_client_credentials(body: Mapping[str, Any]):
    """Anti-desvío (FR-006a): quita del cuerpo todo campo de credencial o destino del cliente."""
    out = dict(body)
    removed = [k for k in CLIENT_CREDENTIAL_FIELDS if k in out]
    for k in removed:
        out.pop(k)
    return out, removed
