"""Parser + validador de definiciones de gate (spec 035, T012; contract
``gate-definition.md``).

De acá sale la «validación en seco» de SC-008: que las 3 definiciones sean
interpretables y sus precondiciones de aprovisionamiento computables (población
declarada, mezcla suma 100, cadencias con rango válido, SLOs = los 4 canónicos, version
presente y semver). Un gate inválido devuelve errores ACCIONABLES (lista de strings,
mismo estilo que ``corpus/validate.py``), nunca una excepción opaca.

Además expone ``surface_arrival_rates`` — la «tasa de llegada por superficie» derivada
que documenta research.md R1: el puente al scenario k6 (``constant-arrival-rate`` con
``rate: N_s, timeUnit: T_s``). El reparto de población entre superficies usa el método
del resto mayor (Hamilton) sobre la mezcla — reproduce byte a byte la distribución de
R5 en los tres gates (125→75/31/13/6, 250→150/63/25/12, 500→300/125/50/25).

DETERMINISMO: lógica pura, sin reloj/uuid/random. Mismo YAML → mismo resultado.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Union

import yaml

# Directorio canónico de definiciones (harness/gates/).
GATES_DIR = Path(__file__).resolve().parents[3] / "gates"

# Los 4 SLO de oro (contract slo:); fijos, no configurables por run (FR-007).
CANONICAL_SLOS: tuple[str, ...] = (
    "audit_lost_events_delta_zero",
    "reconciliation_rows",
    "zero_raw_canaries",
    "blocked_rows_durable_100",
)

# Tipo de definición (opcional, default el gate oficial del tech tree). Un ``drill`` es un
# examen DIRIGIDO —p. ej. el drill de saturación C1, modo sede-lenta— que agrega criterios
# propios en ``drill.criteria`` SIN tocar ni relajar los 4 SLO de oro, que siguen siendo
# obligatorios en ``slo:``.
GATE_KINDS: frozenset = frozenset({"gate_oficial", "drill"})

# Criterios que un drill puede fijar. Cada uno: número > 0, o null = umbral sin fijar (se
# deriva del baseline medido, no se hornea en el YAML).
_DRILL_CRITERIA_KEYS: tuple[str, ...] = ("rejection_p95_max_ms", "admin_p95_budget_ms")

# Claves de stack_config_required que el gate oficial fija explícito (precondición
# del fingerprint — contract regla 2).
_REQUIRED_STACK_KEYS = (
    "masking", "nlp_analyzer", "nlp_analyzer_url", "nlp_fail_mode",
    "producto_incluye", "auto_router",
)
_NLP_FAIL_MODES = frozenset({"block", "degrade"})

_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")
_DURATION_RE = re.compile(r"^(\d+)(ms|s|m|h)$")
_DURATION_UNIT_S = {"ms": 0.001, "s": 1, "m": 60, "h": 3600}


class GateError(ValueError):
    """Se levanta al cargar un gate inválido; ``.errors`` lleva la lista accionable."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("gate inválido:\n  " + "\n  ".join(errors))


# ── Modelo ──────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Phase:
    name: str
    duration: str
    extra: dict = field(default_factory=dict)  # login_storm/peak: enters, arrival_factor…

    @property
    def duration_s(self) -> float:
        return _duration_seconds(self.duration)

    @property
    def arrival_factor(self) -> float:
        """Factor de escala de la tasa (peak=2). Sostenido/recovery = 1 por defecto."""
        return float(self.extra.get("arrival_factor", 1))


@dataclass
class Gate:
    gate: int
    version: str
    description: str
    phases: list[Phase]
    population_ref: str
    mix: dict
    cadence_s: dict
    pii_densities_per_mille: list
    stack_config_required: dict
    stub: dict
    slo: list
    repeatability_tolerance_pct: float
    budget_api_usd: float
    knee_search: Union[dict, None]
    raw: dict
    kind: str = "gate_oficial"
    drill: Union[dict, None] = None

    @property
    def total_population(self) -> int:
        """Población canónica del tech tree = el número del gate."""
        return self.gate

    @property
    def id(self) -> str:
        return f"g{self.gate}-v{self.version}"


@dataclass(frozen=True)
class ArrivalRate:
    """Tasa de llegada derivada de una superficie (puente a k6, research.md R1)."""
    surface: str
    sessions: int          # N_s — el `rate` del executor constant-arrival-rate
    cadence_mean_s: float   # T_s — el `timeUnit` (media del rango de cadencia)

    @property
    def rate_per_s(self) -> float:
        """Llegadas por segundo (ley de Little, FR-001)."""
        return self.sessions / self.cadence_mean_s

    @property
    def k6(self) -> dict:
        """Mapeo directo al executor de modelo ABIERTO (R1): rate=N_s sobre timeUnit=T_s."""
        return {"executor": "constant-arrival-rate",
                "rate": self.sessions, "time_unit_s": self.cadence_mean_s}


# ── Helpers ─────────────────────────────────────────────────────────────────────────

def _duration_seconds(d: str) -> float:
    m = _DURATION_RE.match(str(d))
    if not m:
        raise ValueError(f"duración inválida: {d!r} (esperado <n>{{ms,s,m,h}})")
    return int(m.group(1)) * _DURATION_UNIT_S[m.group(2)]


def _read_yaml(path: Union[str, Path]) -> dict:
    text = Path(path).read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise GateError([f"{path}: el YAML no es un mapeo de gate"])
    return data


# ── Validación (SC-008) ─────────────────────────────────────────────────────────────

def validate_gate(data: object) -> list[str]:
    """Valida un dict de gate ya parseado. Devuelve errores accionables (vacío = válido).

    Cubre la «validación en seco» de SC-008: interpretabilidad + precondiciones de
    aprovisionamiento computables. No toca disco ni red.
    """
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["la definición de gate no es un mapeo"]

    tag = f"[gate {data.get('gate', '?')}]"

    # gate: entero positivo
    n = data.get("gate")
    if not isinstance(n, int) or isinstance(n, bool) or n <= 0:
        errors.append(f"{tag} 'gate' debe ser un entero positivo, es {n!r}")

    # version: presente + semver
    version = data.get("version")
    if version is None:
        errors.append(f"{tag} falta 'version' (semver obligatorio — lo cita todo Run)")
    elif not isinstance(version, str) or not _SEMVER_RE.match(version):
        errors.append(f"{tag} 'version' no es semver MAJOR.MINOR.PATCH: {version!r}")

    if not isinstance(data.get("description"), str) or not data.get("description"):
        errors.append(f"{tag} falta 'description' (string no vacío)")

    errors += _validate_kind(data.get("kind"), tag)
    errors += _validate_drill(data.get("drill"), tag)
    errors += _validate_kind_drill_coherencia(data.get("kind"), data.get("drill"), tag)
    errors += _validate_phases(data.get("phases"), tag)
    errors += _validate_population_ref(data.get("population_ref"), n, tag)
    errors += _validate_mix_cadence(data.get("mix"), data.get("cadence_s"), tag)
    errors += _validate_densities(data.get("pii_densities_per_mille"), tag)
    errors += _validate_stack_config(data.get("stack_config_required"), tag)
    errors += _validate_slo(data.get("slo"), tag)
    errors += _validate_stub(data.get("stub"), tag)

    tol = data.get("repeatability_tolerance_pct")
    if not isinstance(tol, (int, float)) or isinstance(tol, bool) or tol <= 0:
        errors.append(f"{tag} 'repeatability_tolerance_pct' debe ser un número > 0, es {tol!r}")

    budget = data.get("budget_api_usd")
    if not isinstance(budget, (int, float)) or isinstance(budget, bool) or budget < 0:
        errors.append(f"{tag} 'budget_api_usd' debe ser un número >= 0, es {budget!r}")

    ks = data.get("knee_search")
    if ks is not None and not isinstance(ks, dict):
        errors.append(f"{tag} 'knee_search' (opcional) debe ser un mapeo si está presente")

    return errors


def _validate_kind(kind: object, tag: str) -> list[str]:
    """``kind`` es OPCIONAL (ausente = ``gate_oficial``): un valor desconocido no se
    ignora en silencio — un typo cambiaría qué criterios se evalúan."""
    if kind is None:
        return []
    if not isinstance(kind, str) or kind not in GATE_KINDS:
        return [f"{tag} 'kind' desconocido: {kind!r} (esperado uno de {sorted(GATE_KINDS)})"]
    return []


def _validate_kind_drill_coherencia(kind: object, drill: object, tag: str) -> list[str]:
    """Cross-check BIDIRECCIONAL entre ``kind`` y el bloque ``drill``.

    Las dos incoherencias son silenciosas y caras si se dejan pasar:

    - bloque ``drill`` con ``kind`` de gate oficial ⇒ los criterios NO se evaluarían
      (el evaluador solo los mira en un run drill): un drill que parece medir y no mide;
    - ``kind: drill`` sin bloque ``drill`` ⇒ un drill sin ningún criterio propio, que
      «pasa» por no medir nada.

    Solo corre con un ``kind`` VÁLIDO: con un typo en ``kind`` manda el error de
    ``_validate_kind`` (agregar acá un segundo error apuntaría al bloque equivocado).
    """
    if kind is not None and (not isinstance(kind, str) or kind not in GATE_KINDS):
        return []
    efectivo = kind if isinstance(kind, str) else "gate_oficial"
    if drill is not None and efectivo != "drill":
        return [f"{tag} bloque 'drill' en una definición {efectivo}: o falta 'kind: drill' "
                "o sobra el bloque"]
    if efectivo == "drill" and drill is None:
        return [f"{tag} 'kind: drill' sin bloque 'drill' con 'criteria': un drill sin "
                "criterios propios no mide nada (los VALORES pueden ser null, la clave no)"]
    return []


def _validate_drill(drill: object, tag: str) -> list[str]:
    """``drill`` es OPCIONAL y solo tiene sentido en un ``kind: drill``. Claves
    desconocidas son ERROR: un criterio mal escrito se leería como «sin umbral» y el drill
    pasaría por no medir nada."""
    if drill is None:
        return []
    if not isinstance(drill, dict):
        return [f"{tag} 'drill' (opcional) debe ser un mapeo con la clave 'criteria'"]
    errors: list[str] = []
    desconocidas = sorted(k for k in drill if k != "criteria")
    if desconocidas:
        errors.append(f"{tag} clave(s) desconocida(s) en 'drill': {desconocidas} "
                      "(la única válida es 'criteria')")
    criteria = drill.get("criteria")
    if not isinstance(criteria, dict):
        errors.append(f"{tag} 'drill.criteria' debe ser un mapeo de criterios "
                      f"(válidos: {list(_DRILL_CRITERIA_KEYS)})")
        return errors
    desconocidos = sorted(k for k in criteria if k not in _DRILL_CRITERIA_KEYS)
    if desconocidos:
        errors.append(f"{tag} criterio(s) de drill desconocido(s): {desconocidos} "
                      f"(válidos: {list(_DRILL_CRITERIA_KEYS)})")
    for k in _DRILL_CRITERIA_KEYS:
        if k not in criteria or criteria[k] is None:
            continue      # null = umbral sin fijar: se deriva del baseline del mismo día
        v = criteria[k]
        # FINITUD explícita: YAML acepta `.inf`/`.nan` y ninguna comparación los delata
        # (`nan <= 0` es False, `.inf > 0` es True). Un umbral infinito nunca se supera —
        # el criterio quedaría PASS por construcción — y un NaN reprueba/aprueba al azar.
        if (not isinstance(v, (int, float)) or isinstance(v, bool)
                or not math.isfinite(v) or v <= 0):
            errors.append(f"{tag} drill.criteria.{k} debe ser un número FINITO > 0 o null, "
                          f"es {v!r}")
    return errors


def _validate_phases(phases: object, tag: str) -> list[str]:
    errors: list[str] = []
    if not isinstance(phases, list) or not phases:
        return [f"{tag} 'phases' debe ser una lista no vacía"]
    for i, ph in enumerate(phases):
        if not isinstance(ph, dict):
            errors.append(f"{tag} phases[{i}] no es un mapeo")
            continue
        if not isinstance(ph.get("name"), str) or not ph.get("name"):
            errors.append(f"{tag} phases[{i}] falta 'name'")
        try:
            _duration_seconds(ph.get("duration"))
        except (ValueError, TypeError):
            errors.append(f"{tag} phases[{i}] 'duration' inválida: {ph.get('duration')!r}")
    return errors


def _validate_population_ref(ref: object, n: object, tag: str) -> list[str]:
    if not isinstance(ref, str) or not ref:
        return [f"{tag} falta 'population_ref' (ruta a la población declarada)"]
    if "populations/" not in ref:
        return [f"{tag} 'population_ref' debería apuntar a populations/…: {ref!r}"]
    # Coherencia blanda con el número del gate (aviso accionable, no bloqueante duro).
    if isinstance(n, int) and f"gate-{n}" not in ref:
        return [f"{tag} 'population_ref' no menciona gate-{n}: {ref!r}"]
    return []


def _validate_mix_cadence(mix: object, cadence: object, tag: str) -> list[str]:
    errors: list[str] = []
    if not isinstance(mix, dict) or not mix:
        errors.append(f"{tag} 'mix' debe ser un mapeo superficie→% no vacío")
        mix = {}
    else:
        total = 0
        for s, pct in mix.items():
            if not isinstance(pct, (int, float)) or isinstance(pct, bool) or pct < 0:
                errors.append(f"{tag} mix[{s}] no es un porcentaje válido: {pct!r}")
            else:
                total += pct
        if mix and round(total, 6) != 100:
            errors.append(f"{tag} la mezcla no suma 100 (suma {total})")

    if not isinstance(cadence, dict) or not cadence:
        errors.append(f"{tag} 'cadence_s' debe ser un mapeo superficie→[min,max] no vacío")
        cadence = {}
    else:
        for s, rng in cadence.items():
            if (not isinstance(rng, (list, tuple)) or len(rng) != 2
                    or not all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in rng)):
                errors.append(f"{tag} cadence_s[{s}] no es un rango [min,max] numérico: {rng!r}")
                continue
            lo, hi = rng
            if lo <= 0 or hi <= 0 or lo >= hi:
                errors.append(f"{tag} cadence_s[{s}] rango inválido: [{lo},{hi}] (0<min<max)")

    # Toda superficie de la mezcla debe tener cadencia y viceversa.
    if isinstance(mix, dict) and isinstance(cadence, dict):
        for s in mix:
            if s not in cadence:
                errors.append(f"{tag} superficie {s!r} en 'mix' sin cadencia en 'cadence_s'")
        for s in cadence:
            if s not in mix:
                errors.append(f"{tag} superficie {s!r} en 'cadence_s' sin peso en 'mix'")
    return errors


def _validate_densities(dens: object, tag: str) -> list[str]:
    if not isinstance(dens, list) or not dens:
        return [f"{tag} 'pii_densities_per_mille' debe ser una lista no vacía"]
    if not all(isinstance(x, int) and not isinstance(x, bool) and x >= 0 for x in dens):
        return [f"{tag} 'pii_densities_per_mille' debe ser enteros >= 0: {dens!r}"]
    return []


def _validate_stack_config(cfg: object, tag: str) -> list[str]:
    errors: list[str] = []
    if not isinstance(cfg, dict):
        return [f"{tag} falta 'stack_config_required' (precondición del fingerprint)"]
    for k in _REQUIRED_STACK_KEYS:
        if k not in cfg:
            errors.append(f"{tag} stack_config_required falta la clave {k!r}")
    masking = cfg.get("masking")
    if isinstance(masking, dict):
        default = masking.get("default")
        # pyyaml parsea `on` (sin comillas) como True; el gate oficial exige ON.
        if default not in (True, "on"):
            errors.append(f"{tag} masking.default del gate oficial debe ser ON, es {default!r}")
    elif "masking" in cfg:
        errors.append(f"{tag} stack_config_required.masking debe ser un mapeo con 'default'")
    fail_mode = cfg.get("nlp_fail_mode")
    if "nlp_fail_mode" in cfg and fail_mode not in _NLP_FAIL_MODES:
        errors.append(f"{tag} nlp_fail_mode desconocido: {fail_mode!r} "
                      f"(esperado {sorted(_NLP_FAIL_MODES)})")
    return errors


def _validate_slo(slo: object, tag: str) -> list[str]:
    if not isinstance(slo, list):
        return [f"{tag} 'slo' debe ser la lista de los 4 SLO de oro"]
    unknown = [s for s in slo if s not in CANONICAL_SLOS]
    if unknown:
        return [f"{tag} SLO desconocido(s): {unknown} (canónicos: {list(CANONICAL_SLOS)})"]
    if set(slo) != set(CANONICAL_SLOS):
        faltan = [s for s in CANONICAL_SLOS if s not in slo]
        return [f"{tag} 'slo' no son los 4 canónicos; faltan {faltan}"]
    return []


def _validate_stub(stub: object, tag: str) -> list[str]:
    if not isinstance(stub, dict):
        return [f"{tag} falta 'stub' (config del proveedor simulado por run)"]
    errors: list[str] = []
    rate = stub.get("token_rate_tps")
    if not isinstance(rate, (int, float)) or isinstance(rate, bool) or rate <= 0:
        errors.append(f"{tag} stub.token_rate_tps debe ser un número > 0, es {rate!r}")
    return errors


# ── Carga ───────────────────────────────────────────────────────────────────────────

def _build_gate(data: dict) -> Gate:
    phases = [
        Phase(name=p["name"], duration=str(p["duration"]),
              extra={k: v for k, v in p.items() if k not in ("name", "duration")})
        for p in data["phases"]
    ]
    return Gate(
        gate=data["gate"],
        version=data["version"],
        description=data["description"],
        phases=phases,
        population_ref=data["population_ref"],
        mix=dict(data["mix"]),
        cadence_s={s: list(r) for s, r in data["cadence_s"].items()},
        pii_densities_per_mille=list(data["pii_densities_per_mille"]),
        stack_config_required=data["stack_config_required"],
        stub=data["stub"],
        slo=list(data["slo"]),
        repeatability_tolerance_pct=data["repeatability_tolerance_pct"],
        budget_api_usd=data["budget_api_usd"],
        knee_search=data.get("knee_search"),
        raw=data,
        kind=data.get("kind", "gate_oficial"),
        drill=data.get("drill"),
    )


def load_gate(path: Union[str, Path]) -> Gate:
    """Carga y VALIDA una definición de gate. Levanta ``GateError`` si es inválida."""
    data = _read_yaml(path)
    errors = validate_gate(data)
    if errors:
        raise GateError(errors)
    return _build_gate(data)


def load_gate_by_number(n: int) -> Gate:
    """Carga ``harness/gates/gate-<n>.yaml``."""
    return load_gate(GATES_DIR / f"gate-{n}.yaml")


# ── Tasa de llegada por superficie (puente a k6, research.md R1) ─────────────────────

def _largest_remainder(total: int, weights: dict) -> dict:
    """Reparte ``total`` entero entre superficies según ``weights`` (%), método Hamilton.

    Garantiza que la suma de los enteros == ``total``. Desempate de restos por orden de
    declaración de la mezcla (la superficie que aparece antes gana el asiento). Reproduce
    la distribución de R5: 125→75/31/13/6, 250→150/63/25/12, 500→300/125/50/25.
    """
    order = list(weights)
    s = sum(weights.values())
    if s <= 0:
        return {k: 0 for k in order}
    exact = {k: total * weights[k] / s for k in order}
    floors = {k: int(math.floor(exact[k])) for k in order}
    remainder = total - sum(floors.values())
    # Mayor resto primero; empate → menor índice de declaración.
    ranked = sorted(order, key=lambda k: (-(exact[k] - floors[k]), order.index(k)))
    for k in ranked[:remainder]:
        floors[k] += 1
    return floors


def surface_populations(gate: Gate) -> dict:
    """Sesiones activas por superficie (reparto entero de la población por la mezcla)."""
    return _largest_remainder(gate.total_population, gate.mix)


def surface_arrival_rates(gate: Gate) -> dict:
    """Tasa de llegada derivada por superficie (N_s / cadencia_media).

    El puente al scenario k6 documentado en research.md R1: cada superficie se corre
    como ``constant-arrival-rate`` con ``rate=N_s`` sobre ``timeUnit=cadencia_media``.
    Consumible por el bloque de escenarios y por el dry-run.
    """
    pops = surface_populations(gate)
    rates: dict = {}
    for s, rng in gate.cadence_s.items():
        lo, hi = rng
        rates[s] = ArrivalRate(surface=s, sessions=pops.get(s, 0),
                               cadence_mean_s=(lo + hi) / 2)
    return rates


# ── Dry-run (SC-008) ────────────────────────────────────────────────────────────────

def dry_run(path: Union[str, Path]) -> list[str]:
    """Validación en seco de SC-008: carga + validación + tasas de llegada computables.

    Devuelve la lista de errores accionables (vacía = el gate es aprovisionable). No
    genera carga ni toca el stack — solo comprueba que la definición es interpretable.
    """
    try:
        data = _read_yaml(path)
    except (OSError, yaml.YAMLError) as e:
        return [f"{path}: no se pudo leer/parsear: {e}"]
    except GateError as e:
        return e.errors
    errors = validate_gate(data)
    if errors:
        return errors
    gate = _build_gate(data)
    for s, ar in surface_arrival_rates(gate).items():
        if ar.cadence_mean_s <= 0:
            errors.append(f"[gate {gate.gate}] cadencia media no positiva en {s}")
        if ar.sessions < 0:
            errors.append(f"[gate {gate.gate}] población negativa en {s}")
    return errors
