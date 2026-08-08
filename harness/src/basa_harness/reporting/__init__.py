"""Bloque reporting del harness ITV (spec 035).

Definiciones de gate (parser+validador+dry-run SC-008), fingerprint (captura y
comparación FR-009/US3) y — en bloques posteriores — evaluador de SLO, reporte y
comparador de runs. Contratos: ``specs/035-load-harness/contracts/gate-definition.md``
y ``contracts/run-report.md``.
"""
from __future__ import annotations

from .evaluator import (
    SLOResult,
    Verdict,
    compute_overhead,
    eval_audit,
    eval_blocked_durable,
    eval_canaries,
    eval_instrument,
    eval_reconciliation,
    evaluate,
)
from .fingerprint import (
    ComparisonResult,
    FieldDiff,
    Fingerprint,
    capture,
    compare,
)
from .gate_loader import (
    ArrivalRate,
    CANONICAL_SLOS,
    Gate,
    GateError,
    Phase,
    dry_run,
    load_gate,
    load_gate_by_number,
    surface_arrival_rates,
    surface_populations,
    validate_gate,
)
from .report import render_report
from .compare_runs import RunComparison, compare_runs

__all__ = [
    # compare_runs
    "RunComparison",
    "compare_runs",
    # gate_loader
    "ArrivalRate",
    "CANONICAL_SLOS",
    "Gate",
    "GateError",
    "Phase",
    "dry_run",
    "load_gate",
    "load_gate_by_number",
    "surface_arrival_rates",
    "surface_populations",
    "validate_gate",
    # fingerprint
    "ComparisonResult",
    "FieldDiff",
    "Fingerprint",
    "capture",
    "compare",
    # evaluator
    "SLOResult",
    "Verdict",
    "evaluate",
    "eval_audit",
    "eval_reconciliation",
    "eval_canaries",
    "eval_blocked_durable",
    "eval_instrument",
    "compute_overhead",
    # report
    "render_report",
]
