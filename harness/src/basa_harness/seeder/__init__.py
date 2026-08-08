"""Seeder del harness (spec 035, T020): aprovisiona la población del examen vía la API
REST real del producto, de forma reproducible e idempotente (research R5).

Piezas:
- ``population`` — carga/valida ``populations/gate-<N>.yaml`` y la expande a un plan
  determinista de miembros (identidades/passwords derivadas de la semilla).
- ``client`` — cliente HTTP del backend (``BackendClient``) + ``Protocol`` ``SeedClient``.
- ``seed`` — orquestador (bootstrap → pre-check seats → users → keys → budgets) + CLI.
"""
from __future__ import annotations

from .client import API_PREFIX, BackendClient, BackendError, SeedClient
from .population import (
    Bucket,
    BudgetSpec,
    Member,
    Population,
    PopulationError,
    derive_password,
    derive_username,
    load_population,
    load_population_by_gate,
    plan_members,
    validate_population,
)
from .seed import DEFAULT_SEED, SeedError, SeedReport, precheck_seats, seed

__all__ = [
    "API_PREFIX",
    "BackendClient",
    "BackendError",
    "SeedClient",
    "Bucket",
    "BudgetSpec",
    "Member",
    "Population",
    "PopulationError",
    "derive_password",
    "derive_username",
    "load_population",
    "load_population_by_gate",
    "plan_members",
    "validate_population",
    "DEFAULT_SEED",
    "SeedError",
    "SeedReport",
    "precheck_seats",
    "seed",
]
