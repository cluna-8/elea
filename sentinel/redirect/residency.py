"""Postura de residencia (data-model §0/§1/§1b; research D9/D17, R23, R24, R28, R30; FR-013…019a, 057 FR-021…031a).

Jurisdicciones como dato: zonas fijas (`EU`, `US`, `LATAM`) y zonas de datos (una región con `is_zone`, p. ej. el
nombre de la región de la instalación) más códigos ISO de país. Un país miembro satisface a su zona (`DE` ⊂ `EU`,
`AR` ⊂ `LATAM`); una zona no satisface a un país.

- La región del perfil sale de `sentinel_redirect_region` (empresa > instalación > respaldo fijo `region_codes`).
- Postura efectiva = la más estricta entre la **base** (filas de cumplimiento o super-admin; si no hay, el
  `default_posture` de la región o su respaldo en código) y las filas del **admin de empresa**, que solo restringen.
- **Piso de enmascarado**: `masked_all` y `masked_offregion` imponen el forzado aunque las filas no lo pidan; solo
  lo quita una relajación por región (cambiar `default_posture`) o por destino. El respaldo en código (sin fila de
  región) no lo relaja ninguna fila ni ninguna relajación y limita el alcance a las jurisdicciones de la región.
- Destino sin jurisdicción de inferencia ⇒ rechazado con cualquier postura, fila o relajación (FR-019a, FR-028).
- «En región» (FR-028a) exige inferencia, entidad **y control** dentro del conjunto.
- Entidad (o control) de otra jurisdicción, o sin cargar ⇒ solo con `accept_foreign_entity` bajo una allowlist.
"""
from __future__ import annotations

import os
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


def _loaded(code: Optional[str]) -> bool:
    """¿La ficha cargó esta jurisdicción? Vacía, ausente o `unknown` ⇒ no."""
    return bool(code) and str(code).strip().lower() not in ("", "unknown")


def _set(values: Optional[Iterable[str]]) -> frozenset:
    return frozenset(filter(None, map(_norm, values or ())))


def region_codes(region: Optional[str]) -> frozenset:
    """`eu`→{EU}, `us`→{US}, `latam`→{LATAM}, `latam_ar`→{LATAM, AR}. Desconocida ⇒ ∅.
    Es el **respaldo fijo** cuando ninguna fila de `sentinel_redirect_region` resuelve la región."""
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


def _covers(zone: str, code: str, zones: Mapping[str, frozenset], seen: frozenset = frozenset()) -> bool:
    """¿`code` es miembro de `zone`, directa o por una zona anidada? Sin ciclos."""
    if zone in seen:
        return False
    members = set(_ZONES.get(zone, ())) | set(zones.get(zone, ()))
    if code in members:
        return True
    return any(_covers(m, code, zones, seen | {zone}) for m in members if m in _ZONES or m in zones)


def satisfies(code: Optional[str], allowed: Iterable[str], zones: Optional[Mapping[str, frozenset]] = None) -> bool:
    """`zones`: las zonas de datos (nombre → miembros) de las regiones con `is_zone`; sin ellas, solo las fijas."""
    code = _norm(code)
    if code is None:
        return False
    allowed = _set(allowed)
    if code in allowed:
        return True
    zones = zones or {}
    return any(_covers(a, code, zones) for a in allowed)


def intersect(a: Iterable[str], b: Iterable[str], zones: Optional[Mapping[str, frozenset]] = None) -> frozenset:
    """Intersección jerárquica: conserva el código más específico cubierto por ambos lados."""
    a, b = _set(a), _set(b)
    return frozenset({x for x in a if satisfies(x, b, zones)} | {y for y in b if satisfies(y, a, zones)})


def _within(a: Iterable[str], b: Iterable[str], zones: Optional[Mapping[str, frozenset]] = None) -> bool:
    """¿Todo código de `a` está cubierto por `b`? (`a` ⊆ `b`, con la jerarquía de zonas)."""
    return all(satisfies(x, b, zones) for x in _set(a))


# ── región del perfil como dato (data-model §1; research R13, R28) ───────────────────────────────────

REGION_ENV = "SENTINEL_ENTITY_REGION"
DEFAULT_POSTURES = ("reject_offregion", "masked_offregion", "masked_all", "allow")
CODE_FALLBACK = "code_fallback"
STATUS_OK, STATUS_ROW_MISSING, STATUS_UNRESOLVED = "ok", "region_row_missing", "region_unresolved"
ADMIN_ROLES = frozenset({"tenant_admin", "admin"})       # sus filas solo restringen (FR-023, R30)


def resolve_profile(identity_region: Optional[str] = None, environ: Optional[Mapping[str, str]] = None) -> Optional[str]:
    """Perfil de región del pedido: el de la identidad (empresa) o el de la instalación. **Sin caída a un valor de
    otra línea**: si ninguno lo trae, `None` (región sin resolver, FR-031; research R28). Es la única función que
    usan el plugin, `list_postures` y la prueba de fidelidad."""
    environ = os.environ if environ is None else environ
    for raw in (identity_region, environ.get(REGION_ENV)):
        value = (str(raw).strip().lower() if raw is not None else "")
        if value:
            return value
    return None


@dataclass(frozen=True)
class Region:
    """Región efectiva de un pedido: la fila que resuelve el perfil o, sin fila, el respaldo fijo."""
    profile: Optional[str]
    name: Optional[str] = None
    codes: frozenset = frozenset()
    default_posture: Optional[str] = None       # `None` ⇔ sin fila (rige el respaldo en código)
    level: Optional[str] = None
    zones: tuple = ()                           # ((nombre, miembros), ...) de las filas `is_zone` visibles

    @property
    def row_found(self) -> bool:
        return self.default_posture is not None

    @property
    def status(self) -> str:
        if self.row_found:
            return STATUS_OK
        return STATUS_ROW_MISSING if self.profile else STATUS_UNRESOLVED

    @property
    def zones_map(self) -> dict:
        return dict(self.zones)


def _visible(row: Mapping[str, Any], tenant_id: Optional[str]) -> bool:
    tenant = row.get("tenant_id")
    return tenant in (None, "*") or (tenant_id is not None and str(tenant) == str(tenant_id))


def resolve_region(profile: Optional[str], regions: Iterable[Mapping[str, Any]], tenant_id: Optional[str]) -> Region:
    """Fila que contiene `profile` en `region_profiles` (empresa > instalación; las de otra empresa no se ven) →
    sus jurisdicciones y su `default_posture`. Sin fila: `region_codes(profile)` y `default_posture = None`.
    Sin perfil: región sin resolver (ninguna jurisdicción, nunca `eu`)."""
    profile = (str(profile).strip().lower() if profile else "") or None
    rows = [r for r in regions if _visible(r, tenant_id)]
    zones = {}
    for r in sorted(rows, key=lambda r: r.get("tenant_id") not in (None, "*")):    # la de la empresa pisa a la de instalación
        if r.get("is_zone") and r.get("name"):
            zones[_norm(r["name"])] = _set(r.get("jurisdictions"))
    zones_t = tuple(sorted(zones.items()))
    if profile is None:
        return Region(profile=None, zones=zones_t)
    matching = [r for r in rows if profile in {str(p).strip().lower() for p in (r.get("region_profiles") or ())}]
    matching.sort(key=lambda r: r.get("tenant_id") in (None, "*"))                 # empresa primero
    if matching:
        r = matching[0]
        posture_value = r.get("default_posture")
        if posture_value not in DEFAULT_POSTURES:
            raise ValueError(f"default_posture desconocido: {posture_value!r}")
        return Region(profile=profile, name=r.get("name"), codes=_set(r.get("jurisdictions")),
                      default_posture=posture_value, level=r.get("level"), zones=zones_t)
    return Region(profile=profile, codes=region_codes(profile), zones=zones_t)


# ── postura ─────────────────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Posture:
    mode: str = "off"
    jurisdictions: frozenset = frozenset()     # allowlist
    accept_foreign_entity: bool = False
    home: frozenset = frozenset()              # «en región» para offregion_masked
    explicit: bool = True
    # ── 057 (todo opcional: una postura armada a mano sigue valiendo como en la 068) ─────────────────
    redirected: bool = False                   # pedido redirigido: exige jurisdicción de inferencia (FR-028)
    forcers: tuple = ()                        # casas (conjuntos): forzado si el destino NO está dentro de alguna
    floor: Optional[frozenset] = None          # piso de `default_posture` (∅ = todo destino; None = sin piso)
    cap: Optional[frozenset] = None            # alcance del respaldo en código (allowlist adicional)
    blocked: bool = False                      # región sin resolver: todo lo redirigido se rechaza
    code_fallback: bool = False                # respaldo en código vigente: ninguna relajación lo quita
    region_status: str = STATUS_OK
    region_name: Optional[str] = None
    region_codes: frozenset = frozenset()      # «mi región» (para `in_region`)
    region_default: Optional[str] = None       # `default_posture` de la fila de región, si hay
    default_applied: Optional[str] = None      # valor de `default_posture` o `code_fallback` (auditoría)
    relaxed: frozenset = frozenset()           # ids de entradas con relajación por destino vigente
    zones: tuple = ()

    def __post_init__(self):
        if self.mode not in MODES:
            raise ValueError(f"postura desconocida: {self.mode!r}")

    @property
    def zones_map(self) -> dict:
        return dict(self.zones)


@dataclass(frozen=True)
class ResidencyDecision:
    allowed: bool
    forced_masking: bool = False
    reason: Optional[str] = None               # residency | foreign_entity
    jurisdiction_served: Optional[str] = None
    mode: str = "off"
    in_region: Optional[bool] = None           # FR-028a (sin nombres de entidad)
    masking_relaxation: Optional[str] = None   # region | destination | None (R24)


def _rows_posture(rows: list, home_default: frozenset, zones: Mapping) -> Optional[Posture]:
    """Postura de las filas de la 068: la más estricta; varias allowlists ⇒ intersección. `None` sin filas."""
    if not rows:
        return None
    for r in rows:
        if r.get("mode") not in MODES:
            raise ValueError(f"postura desconocida: {r.get('mode')!r}")
    mode = max((r["mode"] for r in rows), key=_STRICTNESS.__getitem__)
    winners = [r for r in rows if r["mode"] == mode]
    if mode == "allowlist":
        juris = None
        for r in winners:
            j = _set(r.get("jurisdictions"))
            juris = j if juris is None else intersect(juris, j, zones)
        accept = all(bool(r.get("accept_foreign_entity")) for r in winners)
        return Posture(mode=mode, jurisdictions=juris or frozenset(), accept_foreign_entity=accept, home=home_default)
    if mode == "offregion_masked":
        home = None
        for r in winners:
            j = _set(r.get("jurisdictions"))
            if j:
                home = j if home is None else intersect(home, j, zones)
        return Posture(mode=mode, home=home if home is not None else home_default)
    return Posture(mode="off")


def _combine(base: Posture, admin: Optional[Posture], zones: Mapping) -> Posture:
    """La más estricta entre la base y las filas del admin (solo restringen: una `off` suya no tiene efecto)."""
    if admin is None:
        return base
    if _STRICTNESS[admin.mode] > _STRICTNESS[base.mode]:
        return admin
    if _STRICTNESS[admin.mode] < _STRICTNESS[base.mode]:
        return base
    if base.mode == "allowlist":
        return Posture(mode="allowlist", jurisdictions=intersect(base.jurisdictions, admin.jurisdictions, zones),
                       accept_foreign_entity=base.accept_foreign_entity and admin.accept_foreign_entity,
                       home=base.home)
    if base.mode == "offregion_masked":
        return Posture(mode="offregion_masked", home=intersect(base.home, admin.home, zones))
    return base


def _default_base(region: Region, redirected: bool) -> tuple:
    """`(postura base, piso, alcance, bloqueado, respaldo)` cuando no hay filas de cumplimiento."""
    if not redirected:
        return Posture(mode="off", explicit=False), None, None, False, False
    if not region.row_found:
        if region.profile is None:
            return Posture(mode="allowlist", explicit=False), frozenset(), None, True, True
        return (Posture(mode="offregion_masked", home=frozenset(), explicit=False), frozenset(),
                region.codes, False, True)
    dp = region.default_posture
    if dp == "reject_offregion":
        return Posture(mode="allowlist", jurisdictions=region.codes, home=region.codes, explicit=False), None, None, False, False
    if dp == "masked_offregion":
        return Posture(mode="offregion_masked", home=region.codes, explicit=False), None, None, False, False
    if dp == "masked_all":
        return Posture(mode="offregion_masked", home=frozenset(), explicit=False), None, None, False, False
    return Posture(mode="off", explicit=False), None, None, False, False        # allow


def _floor_of(region: Region, redirected: bool) -> Optional[frozenset]:
    """Piso de enmascarado que las filas no quitan (R23): `masked_all` ⇒ ∅ (todo destino), `masked_offregion` ⇒ la
    región, respaldo en código ⇒ ∅."""
    if not redirected:
        return None
    if not region.row_found:
        return frozenset() if region.profile is not None else None
    if region.default_posture == "masked_all":
        return frozenset()
    if region.default_posture == "masked_offregion":
        return region.codes
    return None


def effective_posture(rows: Iterable[Mapping[str, Any]], scope: RequestScope, *,
                      redirected: bool, tenant_region: Optional[str],
                      regions: Iterable[Mapping[str, Any]] = (),
                      relaxations: Iterable[Mapping[str, Any]] = ()) -> Posture:
    """`tenant_region` = `resolve_profile` (empresa > instalación), lo resuelve el llamador; `regions` son las
    filas de `sentinel_redirect_region` de la instantánea y `relaxations` las relajaciones por destino vigentes
    (la instantánea ya descartó las que su ficha no cumple)."""
    region = resolve_region(tenant_region, list(regions), scope.tenant_id)
    zones = region.zones_map
    rows = applicable(rows, scope)
    for r in rows:
        if r.get("mode") not in MODES:
            raise ValueError(f"postura desconocida: {r.get('mode')!r}")
    base_rows = [r for r in rows if r.get("created_by_role") not in ADMIN_ROLES]
    admin_rows = [r for r in rows if r.get("created_by_role") in ADMIN_ROLES]
    home_default = region.codes
    default_base, floor, cap, blocked, fallback = _default_base(region, redirected)
    if base_rows:
        base = _rows_posture(base_rows, home_default, zones)
        floor = _floor_of(region, redirected)                         # el piso no lo quitan las filas
        default_applied = None
    else:
        base = default_base
        default_applied = (CODE_FALLBACK if fallback else region.default_posture) if redirected else None
    admin = _rows_posture(admin_rows, home_default, zones)
    eff = _combine(base, admin, zones)
    forcers = []
    if base.mode == "offregion_masked":
        forcers.append(base.home)
    if admin is not None and admin.mode == "offregion_masked":
        forcers.append(admin.home)
    if floor is not None:
        forcers.append(floor)
    relaxed = frozenset(str(x["entry_id"]) for x in relaxations
                        if not x.get("revoked_at") and _visible(x, scope.tenant_id))
    return Posture(
        mode=eff.mode, jurisdictions=eff.jurisdictions, accept_foreign_entity=eff.accept_foreign_entity,
        home=eff.home, explicit=bool(rows), redirected=redirected, forcers=tuple(forcers), floor=floor, cap=cap,
        blocked=blocked, code_fallback=fallback, region_status=region.status if redirected else STATUS_OK,
        region_name=region.name, region_codes=region.codes, region_default=region.default_posture,
        default_applied=default_applied, relaxed=relaxed, zones=region.zones)


def is_less_strict(candidate: Mapping[str, Any], effective: Posture, *,
                   region_codes: Optional[frozenset] = None) -> bool:
    """¿Una fila (`mode`, `jurisdictions`) del admin de empresa es **menos estricta** que la postura efectiva de
    su alcance? (data-model §1; QA A8). Entre modos, el de la 068 (`off` < `offregion_masked` < `allowlist`);
    dentro del mismo modo, por inclusión de jurisdicciones (allowlist) o de la casa **resuelta** (offregion_masked,
    vacía ⇒ la región). Dos listas que se solapan sin inclusión no son comparables: se tratan como menos estrictas."""
    mode = candidate.get("mode")
    if mode not in MODES:
        raise ValueError(f"postura desconocida: {mode!r}")
    zones = effective.zones_map
    if _STRICTNESS[mode] != _STRICTNESS[effective.mode]:
        return _STRICTNESS[mode] < _STRICTNESS[effective.mode]
    if mode == "allowlist":
        return not _within(candidate.get("jurisdictions"), effective.jurisdictions, zones)
    if mode == "offregion_masked":
        home = _set(candidate.get("jurisdictions")) or (effective.region_codes if region_codes is None else _set(region_codes))
        return not _within(home, effective.home, zones)
    return False


def _inside(destination: Mapping[str, Any], codes: frozenset, zones: Mapping) -> bool:
    """Dentro de `codes` solo si inferencia, entidad **y control** están cargadas y lo satisfacen (FR-028a)."""
    return all(_loaded(destination.get(f)) and satisfies(destination.get(f), codes, zones)
               for f in ("inference_jurisdiction", "entity_jurisdiction", "control_jurisdiction"))


def evaluate(posture: Posture, destination: Mapping[str, Any]) -> ResidencyDecision:
    inf = _norm(destination.get("inference_jurisdiction")) if _loaded(destination.get("inference_jurisdiction")) else None
    ent = destination.get("entity_jurisdiction")
    ctrl = destination.get("control_jurisdiction")
    zones = posture.zones_map
    if posture.blocked:
        return ResidencyDecision(False, False, "residency", None, posture.mode)
    if posture.redirected and inf is None:
        return ResidencyDecision(False, False, "residency", None, posture.mode)          # FR-028
    in_region = _inside(destination, posture.region_codes, zones) if posture.region_codes else None
    if posture.mode == "allowlist":
        if not satisfies(inf, posture.jurisdictions, zones):
            return ResidencyDecision(False, False, "residency", None, "allowlist")
        if not (_loaded(ent) and satisfies(ent, posture.jurisdictions, zones)
                and _loaded(ctrl) and satisfies(ctrl, posture.jurisdictions, zones)) \
                and not posture.accept_foreign_entity:
            return ResidencyDecision(False, False, "foreign_entity", None, "allowlist")
    if posture.cap is not None:                                    # respaldo en código: alcance de la región
        if not satisfies(inf, posture.cap, zones):
            return ResidencyDecision(False, False, "residency", None, posture.mode)
        if not (_loaded(ent) and satisfies(ent, posture.cap, zones) and _loaded(ctrl) and satisfies(ctrl, posture.cap, zones)):
            return ResidencyDecision(False, False, "foreign_entity", None, posture.mode)
    forced = any(not _inside(destination, h, zones) for h in posture.forcers)
    if posture.mode == "offregion_masked" and not _inside(destination, posture.home, zones):
        forced = True
    relaxation = None
    if forced and not posture.code_fallback and str(destination.get("id")) in posture.relaxed:
        forced, relaxation = False, "destination"
    elif posture.region_default == "masked_offregion" and in_region and not posture.code_fallback:
        relaxation = "region"
    return ResidencyDecision(True, forced, None, inf, posture.mode, in_region, relaxation)
