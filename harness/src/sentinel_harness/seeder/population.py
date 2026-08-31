"""Población/Seed del examen (spec 035, T020; data-model §Población/Seed, research R5).

Carga y valida ``populations/gate-<N>.yaml`` y la EXPANDE a un plan determinista de
miembros (cuentas admin + clients con su ``client_type``/``tool_type``/budget). El seeder
(``seed.py``) recorre ese plan contra la API REST real del producto; los tests lo
verifican con datos sintéticos y un cliente falso.

DETERMINISMO (restricción de scripts deterministas): las identidades y passwords se
derivan de la SEMILLA del run + índice vía HMAC-SHA256 — nunca ``uuid``/``time``/``random``.
Misma ``(semilla, gate)`` ⇒ mismos usernames y passwords, byte a byte. De ahí salen la
idempotencia del re-seed (identidades estables → la API rechaza duplicados y convergemos)
y la comparabilidad entre runs (US3). Un gate inválido devuelve errores ACCIONABLES
(lista de strings, mismo estilo que ``corpus/validate.py`` y ``reporting/gate_loader.py``),
nunca una excepción opaca.
"""
from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Union

import yaml

# Directorio canónico de poblaciones (junto a este módulo).
POPULATIONS_DIR = Path(__file__).resolve().parent / "populations"

# Roles canónicos que el seed siembra (enum verificado en backend/src/models/user.py:9;
# super_admin NO se siembra — se genera aparte, solo cloud).
SEED_ROLES: tuple[str, ...] = ("tenant_admin", "compliance_officer", "client")
# client_type válidos (CHECK ck_users_client_type en el modelo).
CLIENT_TYPES: frozenset[str] = frozenset({"base_url", "desktop", "chat_ui"})
# reset_period aceptado por el schema de budget (backend/src/schemas/budget.py:12).
RESET_PERIODS: frozenset[str] = frozenset({"daily", "weekly", "monthly", "never"})

# Abreviaturas de rol para las identidades (username legible para el pool de k6).
_ROLE_ABBR = {"tenant_admin": "adm", "compliance_officer": "cmp", "client": "cli"}

# Política de longitud mínima del backend (auth/passwords.py:28 — MIN_PASSWORD_LEN=12).
_MIN_PASSWORD_LEN = 12
# Prefijo fijo de las passwords DERIVADAS (no es un secreto: aporta la clase de
# caracteres que exige la política; el valor real sale del HMAC de la semilla).
_PASSWORD_PREFIX = "Itv-"


class PopulationError(ValueError):
    """Se levanta al cargar una población inválida; ``.errors`` lleva la lista accionable."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("población inválida:\n  " + "\n  ".join(errors))


# ── Modelo ──────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class BudgetSpec:
    """Presupuesto a crear vía ``POST /budgets`` (user XOR group; acá siempre por user)."""
    max_spend_usd: float
    max_tokens: int
    reset_period: str
    kind: str  # "default" | "cohort_402"


@dataclass(frozen=True)
class Bucket:
    """Un cubo de clients por superficie: ``client_type`` (cómo consume) + ``tool_type``
    (la herramienta de la Connection = el seat)."""
    client_type: str
    tool_type: str
    count: int


@dataclass(frozen=True)
class Member:
    """Una fila a aprovisionar. Los clients son seats (llevan ``tool_type`` y presupuesto);
    las cuentas admin no consumen seat y no llevan key ni budget."""
    role: str
    username: str
    email: str
    password: str
    client_type: Optional[str] = None
    tool_type: Optional[str] = None
    budget: Optional[BudgetSpec] = None

    @property
    def is_seat(self) -> bool:
        return self.role == "client"


@dataclass
class Population:
    gate: int
    tenant: str
    seed_prefix: str
    email_domain: str
    expected_max_seats: int
    admin_username: str
    tenant_admins: int
    compliance_officers: int
    buckets: list[Bucket]
    budget_default: BudgetSpec
    budget_cohort_402: Optional[BudgetSpec]
    cohort_402_pct: float
    raw: dict = field(default_factory=dict)

    @property
    def total_clients(self) -> int:
        return sum(b.count for b in self.buckets)

    @property
    def planned_seats(self) -> int:
        """Seats planificados = clients = llaves (seat = Connection activa, seat_counter.py)."""
        return self.total_clients

    @property
    def total_population(self) -> int:
        return self.tenant_admins + self.compliance_officers + self.total_clients

    @property
    def cohort_402_size(self) -> int:
        """Cuántos clients reciben el budget ínfimo (redondeo half-up determinista)."""
        if self.budget_cohort_402 is None or self.cohort_402_pct <= 0:
            return 0
        return int(self.total_clients * self.cohort_402_pct / 100 + 0.5)

    def role_counts(self) -> dict:
        return {
            "tenant_admin": self.tenant_admins,
            "compliance_officer": self.compliance_officers,
            "client": self.total_clients,
        }


# ── Derivación determinista de identidades ────────────────────────────────────────────

def derive_username(prefix: str, gate: int, role: str, idx: int) -> str:
    """``<prefijo>-g<gate>-<abbr>-<idx:04d>`` — estable e independiente de la semilla.

    Que NO dependa de la semilla es deliberado: hace idempotente el re-seed (mismas
    identidades → la API responde 400/409 y convergemos) y deja los usernames legibles
    para el pool de credenciales que k6 carga en un ``SharedArray`` (R1)."""
    return f"{prefix}-g{gate}-{_ROLE_ABBR.get(role, role)}-{idx:04d}"


def derive_password(seed: Union[int, str], username: str) -> str:
    """Password determinista de ``(semilla, username)`` vía HMAC-SHA256.

    Cumple la política del backend (≥12 chars, auth/passwords.py) y es reproducible en
    cualquier máquina sin ``random``/``uuid``/``time``: misma semilla → misma password
    (imprescindible para el login storm del gate 250 y el JWT del chat — R5)."""
    digest = hmac.new(str(seed).encode("utf-8"), username.encode("utf-8"),
                      hashlib.sha256).hexdigest()
    # NO es un secreto hardcodeado: es una DERIVACIÓN determinista (no hay valor fijo).
    # El prefijo aporta mayúscula/minúscula/guion; los 16 hex aportan dígitos → 20 chars.
    derived = "".join((_PASSWORD_PREFIX, digest[:16]))  # ggignore: derivación, no secreto
    assert len(derived) >= _MIN_PASSWORD_LEN  # invariante de la política de longitud
    return derived


def derive_email(username: str, domain: str) -> str:
    return f"{username}@{domain}"


# ── Validación (SC-008: precondiciones de aprovisionamiento computables en seco) ──────

def validate_population(data: object) -> list[str]:
    """Valida un dict de población ya parseado. Devuelve errores accionables (vacío = ok).

    No toca disco ni red: comprueba que la población es interpretable y que su aritmética
    cierra (suma == gate, seats ≤ licencia esperada), que son las precondiciones que el
    seeder necesita antes de tocar el stack."""
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["la definición de población no es un mapeo"]

    tag = f"[población gate {data.get('gate', '?')}]"

    n = data.get("gate")
    if not isinstance(n, int) or isinstance(n, bool) or n <= 0:
        errors.append(f"{tag} 'gate' debe ser un entero positivo, es {n!r}")

    if not isinstance(data.get("tenant"), str) or not data.get("tenant"):
        errors.append(f"{tag} falta 'tenant' (string no vacío)")

    for key in ("seed_prefix", "email_domain"):
        if not isinstance(data.get(key), str) or not data.get(key):
            errors.append(f"{tag} falta '{key}' (string no vacío)")

    lic = data.get("license")
    max_seats = None
    if not isinstance(lic, dict) or not isinstance(lic.get("expected_max_seats"), int) \
            or isinstance(lic.get("expected_max_seats"), bool) or lic.get("expected_max_seats") <= 0:
        errors.append(f"{tag} falta 'license.expected_max_seats' (entero > 0)")
    else:
        max_seats = lic["expected_max_seats"]

    boot = data.get("admin_bootstrap")
    if not isinstance(boot, dict) or not isinstance(boot.get("username"), str) or not boot.get("username"):
        errors.append(f"{tag} falta 'admin_bootstrap.username' (el primer admin del bootstrap)")

    roles = data.get("roles")
    n_admins = n_comp = 0
    clients_total = 0
    if not isinstance(roles, dict):
        errors.append(f"{tag} falta 'roles' (mapeo con tenant_admin/compliance_officer/client)")
    else:
        n_admins = _int_count(roles.get("tenant_admin"), f"{tag} roles.tenant_admin", errors)
        n_comp = _int_count(roles.get("compliance_officer"), f"{tag} roles.compliance_officer", errors)
        if n_comp == 0 and "compliance_officer" in roles:
            errors.append(f"{tag} el lector de SLO necesita ≥1 compliance_officer (R5)")
        clients_total = _validate_buckets(roles.get("client"), tag, errors)

    errors += _validate_budgets(data.get("budgets"), tag)

    # Aritmética dura de R5: la suma cierra con el gate y los seats entran en la licencia.
    if isinstance(n, int) and not isinstance(n, bool):
        total = n_admins + n_comp + clients_total
        if total != n:
            errors.append(f"{tag} la población suma {total}, no {n} "
                          f"({n_admins} admin + {n_comp} compliance + {clients_total} client)")
    if max_seats is not None and clients_total > max_seats:
        errors.append(f"{tag} seats planificados ({clients_total}) > licencia esperada "
                      f"({max_seats}) — no hay headroom; ampliá la licencia o bajá la población")

    return errors


def _int_count(v: object, label: str, errors: list[str]) -> int:
    if isinstance(v, dict):
        v = v.get("count")
    if not isinstance(v, int) or isinstance(v, bool) or v < 0:
        errors.append(f"{label}.count debe ser un entero >= 0, es {v!r}")
        return 0
    return v


def _validate_buckets(client: object, tag: str, errors: list[str]) -> int:
    if not isinstance(client, dict):
        errors.append(f"{tag} falta 'roles.client' (mapeo con 'buckets')")
        return 0
    buckets = client.get("buckets")
    if not isinstance(buckets, list) or not buckets:
        errors.append(f"{tag} 'roles.client.buckets' debe ser una lista no vacía")
        return 0
    total = 0
    seen: set[str] = set()
    for i, b in enumerate(buckets):
        if not isinstance(b, dict):
            errors.append(f"{tag} buckets[{i}] no es un mapeo")
            continue
        ct = b.get("client_type")
        if ct not in CLIENT_TYPES:
            errors.append(f"{tag} buckets[{i}] client_type inválido: {ct!r} "
                          f"(válidos {sorted(CLIENT_TYPES)})")
        elif ct in seen:
            errors.append(f"{tag} buckets[{i}] client_type {ct!r} duplicado")
        else:
            seen.add(ct)
        if not isinstance(b.get("tool_type"), str) or not b.get("tool_type"):
            errors.append(f"{tag} buckets[{i}] falta 'tool_type' (la herramienta de la Connection)")
        total += _int_count(b.get("count"), f"{tag} buckets[{i}]", errors)
    return total


def _validate_budget_spec(spec: object, label: str, errors: list[str]) -> None:
    if not isinstance(spec, dict):
        errors.append(f"{label} debe ser un mapeo con max_spend_usd/max_tokens/reset_period")
        return
    if not isinstance(spec.get("max_spend_usd"), (int, float)) or isinstance(spec.get("max_spend_usd"), bool) \
            or spec.get("max_spend_usd") < 0:
        errors.append(f"{label}.max_spend_usd debe ser un número >= 0")
    if not isinstance(spec.get("max_tokens"), int) or isinstance(spec.get("max_tokens"), bool) \
            or spec.get("max_tokens") < 0:
        errors.append(f"{label}.max_tokens debe ser un entero >= 0")
    if spec.get("reset_period") not in RESET_PERIODS:
        errors.append(f"{label}.reset_period inválido: {spec.get('reset_period')!r} "
                      f"(válidos {sorted(RESET_PERIODS)})")


def _validate_budgets(budgets: object, tag: str) -> list[str]:
    errors: list[str] = []
    if not isinstance(budgets, dict):
        return [f"{tag} falta 'budgets' (default + cohorte 402)"]
    _validate_budget_spec(budgets.get("default"), f"{tag} budgets.default", errors)
    pct = budgets.get("cohort_402_pct", 0)
    if not isinstance(pct, (int, float)) or isinstance(pct, bool) or not (0 <= pct <= 100):
        errors.append(f"{tag} budgets.cohort_402_pct debe estar en [0,100], es {pct!r}")
    if pct and budgets.get("cohort_402") is None:
        errors.append(f"{tag} cohort_402_pct > 0 pero falta budgets.cohort_402")
    if budgets.get("cohort_402") is not None:
        _validate_budget_spec(budgets.get("cohort_402"), f"{tag} budgets.cohort_402", errors)
    return errors


# ── Carga ─────────────────────────────────────────────────────────────────────────────

def _budget_from(spec: dict, kind: str) -> BudgetSpec:
    return BudgetSpec(max_spend_usd=float(spec["max_spend_usd"]),
                      max_tokens=int(spec["max_tokens"]),
                      reset_period=str(spec["reset_period"]), kind=kind)


def _build_population(data: dict) -> Population:
    roles = data["roles"]
    budgets = data["budgets"]
    cohort = budgets.get("cohort_402")
    return Population(
        gate=data["gate"],
        tenant=data["tenant"],
        seed_prefix=data["seed_prefix"],
        email_domain=data["email_domain"],
        expected_max_seats=data["license"]["expected_max_seats"],
        admin_username=data["admin_bootstrap"]["username"],
        tenant_admins=roles["tenant_admin"]["count"],
        compliance_officers=roles["compliance_officer"]["count"],
        buckets=[Bucket(client_type=b["client_type"], tool_type=b["tool_type"], count=b["count"])
                 for b in roles["client"]["buckets"]],
        budget_default=_budget_from(budgets["default"], "default"),
        budget_cohort_402=_budget_from(cohort, "cohort_402") if cohort is not None else None,
        cohort_402_pct=float(budgets.get("cohort_402_pct", 0)),
        raw=data,
    )


def load_population(path: Union[str, Path]) -> Population:
    """Carga y VALIDA una población. Levanta ``PopulationError`` si es inválida."""
    text = Path(path).read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise PopulationError([f"{path}: el YAML no es un mapeo de población"])
    errors = validate_population(data)
    if errors:
        raise PopulationError(errors)
    return _build_population(data)


def load_population_by_gate(n: int) -> Population:
    """Carga ``populations/gate-<n>.yaml``."""
    return load_population(POPULATIONS_DIR / f"gate-{n}.yaml")


# ── Expansión determinista al plan de miembros ────────────────────────────────────────

def plan_members(pop: Population, seed: Union[int, str]) -> list[Member]:
    """Expande la población a la lista ORDENADA de miembros a aprovisionar.

    Orden: primero las cuentas admin (tenant_admin, compliance_officer) y después los
    clients por superficie en el orden declarado de ``buckets``. Ese orden importa: el
    seeder crea TODOS los users antes que las keys (el seat gate corre en ambos, R5), y
    la cohorte 402 se aplica a los primeros ``cohort_402_size`` clients por índice global
    (determinista). Todo se deriva de ``(seed, gate, idx)`` — sin reloj ni azar."""
    members: list[Member] = []

    def make(role: str, idx: int, **extra) -> Member:
        username = derive_username(pop.seed_prefix, pop.gate, role, idx)
        return Member(role=role, username=username,
                      email=derive_email(username, pop.email_domain),
                      password=derive_password(seed, username), **extra)

    for i in range(pop.tenant_admins):
        members.append(make("tenant_admin", i))
    for i in range(pop.compliance_officers):
        members.append(make("compliance_officer", i))

    cohort_n = pop.cohort_402_size
    client_idx = 0
    for bucket in pop.buckets:
        for _ in range(bucket.count):
            budget = (pop.budget_cohort_402 if client_idx < cohort_n and pop.budget_cohort_402
                      else pop.budget_default)
            members.append(make("client", client_idx,
                                client_type=bucket.client_type,
                                tool_type=bucket.tool_type,
                                budget=budget))
            client_idx += 1

    return members
