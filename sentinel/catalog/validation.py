"""Validación de los campos libres de la entrada del catálogo (069 T126; FR-051, FR-052; D28).

`limits`: solo claves conocidas, enteros ≥ 0. `advanced`: lista corta y explícita de claves y ningún
valor que parezca una credencial (las credenciales viven en el almacén cifrado, nunca en la entrada).
Los mensajes de error nunca repiten el valor rechazado.
"""
from __future__ import annotations

import re
from typing import Any, Optional

# `rpm`, `tpm` y `max_parallel_requests` son informativos; `timeout` y `num_retries` los aplica el guard.
LIMIT_KEYS = ("rpm", "tpm", "max_parallel_requests", "timeout", "num_retries")
ADVANCED_KEYS = ("extra_headers", "max_tokens", "stream_timeout", "temperature")
_SECRET_NAME = re.compile(r"auth|api[-_]?key|token|secret|password|passwd|cookie|credential", re.I)
_SECRET_VALUE = re.compile(r"^\s*(bearer|basic)\s+\S|sk-[A-Za-z0-9_-]{8,}|^eyJ[A-Za-z0-9_-]{10,}\.", re.I)
# Parámetros del pedido que la ficha puede declarar «no soportados» (se quitan antes del proveedor). Nunca los
# campos estructurales del pedido ni los de destino/credencial (quitarlos rompe el pedido o el anti-desvío), ni
# los que escribe el propio guard (costo y límites por pedido) ni los internos del motor: quitarlos anula el
# descuento del presupuesto de la llave o los topes de la ficha (H1 del QA del PR #78).
PROTECTED_PARAMS = ("model", "messages", "input", "prompt", "stream", "api_key", "api_base", "headers",
                    "extra_headers", "guardrails", "metadata",
                    "input_cost_per_token", "output_cost_per_token", "timeout", "num_retries",
                    "max_parallel_requests", "proxy_server_request", "litellm_params", "custom_llm_provider",
                    "mock_response")
PROTECTED_PARAM_PREFIXES = ("user_api_key",)    # user_api_key, user_api_key_hash, user_api_key_team_id…


def is_protected_param(name: str) -> bool:
    return name in PROTECTED_PARAMS or name.startswith(PROTECTED_PARAM_PREFIXES)


MAX_UNSUPPORTED_PARAMS = 32
_PARAM_NAME = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_TIER_KEYS = ("up_to_tokens", "input", "output", "cache_read", "cache_write")


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def check_limits(limits: Any) -> dict:
    if not isinstance(limits, dict):
        raise ValueError("limits debe ser un objeto")
    bad = sorted(set(limits) - set(LIMIT_KEYS))
    if bad:
        raise ValueError(f"límites desconocidos: {', '.join(map(str, bad))}")
    for k, v in limits.items():
        if not _is_int(v) or v < 0:
            raise ValueError(f"el límite {k} debe ser un entero mayor o igual a 0")
    return dict(limits)


def check_advanced(advanced: Any) -> dict:
    if not isinstance(advanced, dict):
        raise ValueError("advanced debe ser un objeto")
    bad = sorted(set(advanced) - set(ADVANCED_KEYS))
    if bad:
        raise ValueError(f"parámetros avanzados no admitidos: {', '.join(map(str, bad))}")
    for k, v in advanced.items():
        if k == "max_tokens" and not (_is_int(v) and v >= 1):
            raise ValueError("max_tokens debe ser un entero mayor o igual a 1")
        elif k == "temperature" and not (_is_num(v) and 0 <= v <= 2):
            raise ValueError("temperature debe estar entre 0 y 2")
        elif k == "stream_timeout" and not (_is_num(v) and v > 0):
            raise ValueError("stream_timeout debe ser un número mayor a 0")
        elif k == "extra_headers":
            if not isinstance(v, dict) or not all(isinstance(n, str) and isinstance(x, str) for n, x in v.items()):
                raise ValueError("extra_headers debe ser un objeto de texto a texto")
            for name, value in v.items():
                if _SECRET_NAME.search(name) or _SECRET_VALUE.search(value):
                    raise ValueError("extra_headers no admite credenciales: usá una credencial del catálogo")
    return dict(advanced)


def check_unsupported_params(params: Any) -> list:
    """Lista de nombres de parámetros del pedido que el modelo no acepta (p. ej. `temperature`, `top_p`).

    Solo nombres de primer nivel, en minúsculas; sin duplicados (se conserva el orden). Nunca los campos
    estructurales ni internos (`PROTECTED_PARAMS`). El mensaje no repite valores que no sean nombres válidos."""
    if not isinstance(params, list):
        raise ValueError("unsupported_params debe ser una lista de nombres")
    if len(params) > MAX_UNSUPPORTED_PARAMS:
        raise ValueError(f"unsupported_params admite hasta {MAX_UNSUPPORTED_PARAMS} parámetros")
    out: list = []
    for p in params:
        name = p.strip() if isinstance(p, str) else None
        if not name or not _PARAM_NAME.match(name):
            raise ValueError("cada parámetro es un nombre en minúsculas (letras, números y guion bajo)")
        if is_protected_param(name):
            raise ValueError(f"el parámetro {name} es parte del pedido y no se puede quitar")
        if name not in out:
            out.append(name)
    return out


def check_tiers(tiers: Any) -> Optional[list]:
    if tiers is None:
        return None
    if not isinstance(tiers, list):
        raise ValueError("price_tiers debe ser una lista de tramos")
    for t in tiers:
        if not isinstance(t, dict) or set(t) - set(_TIER_KEYS):
            raise ValueError("cada tramo lleva solo up_to_tokens, input, output, cache_read y cache_write")
        for k, v in t.items():
            if not _is_num(v) or v < 0 or (k == "up_to_tokens" and not (_is_int(v) and v >= 1)):
                raise ValueError(f"el valor de {k} en el tramo no es válido")
    return [dict(t) for t in tiers]
