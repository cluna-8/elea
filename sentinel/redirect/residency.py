"""Postura de residencia (data-model §0/§1b; research D9/D17; FR-013…019a).

Jurisdicciones como dato: zonas (`EU`, `US`, `LATAM`) y códigos ISO de país. Un país miembro
satisface a su zona (`DE` ⊂ `EU`, `AR` ⊂ `LATAM`); una zona no satisface a un país.

- Postura efectiva: la más restrictiva entre todas las filas que aplican
  (`off` < `offregion_masked` < `allowlist`); varias allowlists ⇒ intersección.
- Sin filas: `off` para tráfico no redirigido; `allowlist[región del tenant]` para redirigido.
- Destino sin jurisdicción de inferencia ⇒ fuera de toda allowlist (FR-019a).
- Entidad de otra jurisdicción (o desconocida) ⇒ solo con `accept_foreign_entity` (FR-018).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Optional

from .scopes import RequestScope, applicable

MODES = ("off", "offregion_masked", "allowlist")
_STRICTNESS = {m: i for i, m in enumerate(MODES)}

EU_MEMBERS = frozenset(
    "AT BE BG HR CY CZ DK EE FI FR DE GR IE IT LV LT LU MT NL PL PT RO SK SI ES SE".split())
LATAM_COUNTRIES = frozenset(
    "AR BO BR CL CO CR CU DO EC SV GT HN MX NI PA PY PE PR UY VE".split())
_ZONES = {"EU": EU_MEMBERS, "LATAM": LATAM_COUNTRIES, "US": frozenset()}
_REGION_PREFIX = {"eu": "EU", "us": "US", "latam": "LATAM"}


def _norm(code: Optional[str]) -> Optional[str]:
    if code is None:
        return None
    code = str(code).strip().upper()
    return code or None


def region_codes(region: Optional[str]) -> frozenset:
    """`eu`→{EU}, `us`→{US}, `latam`→{LATAM}, `latam_ar`→{LATAM, AR}. Desconocida ⇒ ∅."""
    if not region:
        return frozenset()
    parts = str(region).strip().lower().split("_", 1)
    zone = _REGION_PREFIX.get(parts[0])
    if zone is None:
        return frozenset()
    codes = {zone}
    if len(parts) == 2 and len(parts[1]) == 2 and parts[1].isalpha():
        codes.add(parts[1].upper())
    return frozenset(codes)


def satisfies(code: Optional[str], allowed: Iterable[str]) -> bool:
    code = _norm(code)
    if code is None:
        return False
    allowed = {_norm(a) for a in allowed} - {None}
    if code in allowed:
        return True
    return any(code in _ZONES.get(a, ()) for a in allowed)


def intersect(a: Iterable[str], b: Iterable[str]) -> frozenset:
    """Intersección jerárquica: conserva el código más específico cubierto por ambos lados."""
    a = frozenset(filter(None, map(_norm, a)))
    b = frozenset(filter(None, map(_norm, b)))
    return frozenset({x for x in a if satisfies(x, b)} | {y for y in b if satisfies(y, a)})


@dataclass(frozen=True)
class Posture:
    mode: str = "off"
    jurisdictions: frozenset = frozenset()     # allowlist
    accept_foreign_entity: bool = False
    home: frozenset = frozenset()              # «en región» para offregion_masked
    explicit: bool = True

    def __post_init__(self):
        if self.mode not in MODES:
            raise ValueError(f"postura desconocida: {self.mode!r}")


@dataclass(frozen=True)
class ResidencyDecision:
    allowed: bool
    forced_masking: bool = False
    reason: Optional[str] = None               # residency | foreign_entity
    jurisdiction_served: Optional[str] = None
    mode: str = "off"


def effective_posture(rows: Iterable[Mapping[str, Any]], scope: RequestScope, *,
                      redirected: bool, tenant_region: Optional[str]) -> Posture:
    """`tenant_region` = `policy.resolve_region` (tenant > instalación), lo resuelve el llamador."""
    rows = applicable(rows, scope)
    home_default = region_codes(tenant_region)
    if not rows:
        if not redirected:
            return Posture(mode="off", explicit=False)
        return Posture(mode="allowlist", jurisdictions=home_default, home=home_default, explicit=False)
    for r in rows:
        if r.get("mode") not in MODES:
            raise ValueError(f"postura desconocida: {r.get('mode')!r}")
    mode = max((r["mode"] for r in rows), key=_STRICTNESS.__getitem__)
    winners = [r for r in rows if r["mode"] == mode]
    if mode == "allowlist":
        juris = None
        for r in winners:
            j = frozenset(filter(None, map(_norm, r.get("jurisdictions") or ())))
            juris = j if juris is None else intersect(juris, j)
        accept = all(bool(r.get("accept_foreign_entity")) for r in winners)
        return Posture(mode=mode, jurisdictions=juris or frozenset(), accept_foreign_entity=accept,
                       home=home_default)
    if mode == "offregion_masked":
        home = None
        for r in winners:
            j = frozenset(filter(None, map(_norm, r.get("jurisdictions") or ())))
            if j:
                home = j if home is None else intersect(home, j)
        return Posture(mode=mode, home=home if home is not None else home_default)
    return Posture(mode="off")


def evaluate(posture: Posture, destination: Mapping[str, Any]) -> ResidencyDecision:
    inf = _norm(destination.get("inference_jurisdiction"))
    ent = _norm(destination.get("entity_jurisdiction"))
    if posture.mode == "off":
        return ResidencyDecision(True, False, None, inf, "off")
    if posture.mode == "allowlist":
        if not satisfies(inf, posture.jurisdictions):
            return ResidencyDecision(False, False, "residency", None, "allowlist")
        if not satisfies(ent, posture.jurisdictions) and not posture.accept_foreign_entity:
            return ResidencyDecision(False, False, "foreign_entity", None, "allowlist")
        return ResidencyDecision(True, False, None, inf, "allowlist")
    # offregion_masked: todo sale, pero fuera de región (o entidad ajena) exige enmascarado
    inside = satisfies(inf, posture.home) and satisfies(ent, posture.home)
    return ResidencyDecision(True, not inside, None, inf, "offregion_masked")
