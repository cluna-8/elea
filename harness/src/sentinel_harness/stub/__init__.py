"""Proveedor simulado (stub) del harness ITV (spec 035, T015-T018).

Servicio FastAPI de un proceso que REEMPLAZA a los proveedores de IA durante los gates,
hablando dos wire-protocols (OpenAI y Anthropic), con el centinela de canarios que ES el
SLO de fuga de PII y una API de control por run con auto-headroom (drift + CPU). Cero
egress, coste $0, determinista donde importa. Contrato:
``specs/035-load-harness/contracts/stub-wire.md``.
"""
from __future__ import annotations

from .canary_sentinel import CanarySentinel, LeakEvidence, SpoolTruncatedError, sweep_spool
from .control import (
    CPU_THRESHOLD_PCT,
    DRIFT_P99_THRESHOLD_MS,
    AliasBehavior,
    StubState,
    register_control_routes,
)
from .server import create_app

__all__ = [
    "AliasBehavior",
    "CanarySentinel",
    "CPU_THRESHOLD_PCT",
    "DRIFT_P99_THRESHOLD_MS",
    "LeakEvidence",
    "SpoolTruncatedError",
    "StubState",
    "create_app",
    "register_control_routes",
    "sweep_spool",
]
