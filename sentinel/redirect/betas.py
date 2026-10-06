"""Lista permitida de cabeceras `anthropic-beta` (T094 de Sentinel, FR-040, research R11).

Hacia un destino **nativo** solo viajan las betas de esta lista; hacia un traducido, ninguna. La lista
es un dato de la extensión: el default es acotado (funciones que no cambian facturación ni retención)
y la instalación lo reemplaza con `REDIRECT_BETA_ALLOWLIST` (valores separados por coma, leída en cada
pedido; vacía = ninguna). Las betas que suben el costo (`context-1m-*`), guardan archivos en el
proveedor (`files-api-*`), ejecutan código o usan la suscripción (`oauth-*`) no están en el default:
se habilitan a propósito.
"""
from __future__ import annotations

import os
import re
from typing import Iterable, Mapping, Optional

ENV = "REDIRECT_BETA_ALLOWLIST"
HEADER = "anthropic-beta"
DEFAULT_ALLOWLIST = (
    "claude-code-20250219",
    "interleaved-thinking-2025-05-14",
    "fine-grained-tool-streaming-2025-05-14",
    "context-management-2025-06-27",
    "effort-2025-11-24",
    "prompt-caching-scope-2026-01-05",
)
_NAME = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


def parse(value: Optional[str]) -> list:
    """Valores de una cabecera `anthropic-beta`, en orden y sin vacíos."""
    return [v for v in (p.strip() for p in (value or "").split(",")) if v]


def allowlist(environ: Optional[Mapping[str, str]] = None) -> frozenset:
    env = os.environ if environ is None else environ
    raw = env.get(ENV)
    if raw is None:
        return frozenset(DEFAULT_ALLOWLIST)
    return frozenset(v for v in parse(raw) if _NAME.match(v))


def split_allowed(received: Iterable[str], allowed: frozenset) -> tuple:
    """→ (las permitidas en su orden, cantidad de descartadas)."""
    received = list(received)
    kept = [b for b in received if b in allowed]
    return kept, len(received) - len(kept)
