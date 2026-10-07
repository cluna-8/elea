"""Habilitación explícita por datos (057 FR-029; research R14; data-model §2).

Una entrada del catálogo nace (o pasa a) `blocked_by_default = true` si **alguna regla aplicable** coincide con
su proveedor, con el host de su `api_base` o, para las reglas de jurisdicción, con la jurisdicción de inferencia,
de entidad **o de control** de su ficha. Las reglas son filas de `ext_catalog_enablement_rule`: ningún código
nombra un proveedor ni un país (Principio IV). Sin reglas, nada nace bloqueado.

- Una regla de **instalación** (`tenant_id` NULL) aplica a todas las entradas, de cualquier empresa.
- Una regla de **empresa** aplica a las entradas de esa empresa (la empresa solo endurece; las reglas de otra
  empresa no se ven ni se aplican).
- Cambiar el proveedor, el `api_base` o la ficha re-evalúa la entrada: si pasa a bloqueada se borra una
  habilitación previa, y una entrada que sigue bloqueada pero cambió de proveedor, host o jurisdicción también
  exige habilitarla de nuevo (lo habilitado era otro destino).
- Habilitar sigue siendo el flujo de la 068/069 (`POST /entries/{id}/enable`, con motivo y rol, en el registro de
  cambios) y **no** relaja la residencia: la postura se evalúa igual.

Carga del seed (`python -m sentinel.catalog.habilitacion <archivo>`): `providers`, `api_hosts` y `jurisdictions`
son listas; el seed de Eleia las deja vacías (D1) y el de paridad con Sentinel es `providers: [deepseek]`.
"""
from __future__ import annotations

import fnmatch
import re
from typing import Any, Iterable, Mapping, Optional
from urllib.parse import urlparse

from sentinel.redirect.residency import satisfies

from . import models as cm

KINDS = cm.RULE_KINDS
SEED_KEYS = {"providers": "provider", "api_hosts": "api_host", "jurisdictions": "jurisdiction"}
SEED_ROLE = "seed"
JURISDICTION_FIELDS = ("inference_jurisdiction", "entity_jurisdiction", "control_jurisdiction")
_LABEL = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")
_LABEL_FIRST = re.compile(r"^[a-z0-9*]([a-z0-9*-]*[a-z0-9*])?$")
_CODE = re.compile(r"^[A-Z][A-Z0-9_-]{0,15}$")


# ── valores de las reglas ─────────────────────────────────────────────────────────────────────

def normalize(kind: str, value: Any) -> str:
    """Valor canónico: proveedor y host en minúscula; jurisdicción en mayúscula."""
    v = str(value or "").strip()
    return v.upper() if kind == "jurisdiction" else v.lower()


def validate(kind: str, value: Any) -> str:
    """Devuelve el valor canónico o levanta `ValueError` con un mensaje para el administrador."""
    if kind not in KINDS:
        raise ValueError("tipo de regla desconocido (provider, api_host o jurisdiction)")
    v = normalize(kind, value)
    if not v:
        raise ValueError("la regla necesita un valor")
    if kind == "provider":
        if v not in cm.PROVIDERS:
            raise ValueError("proveedor desconocido")
    elif kind == "api_host":
        labels = v.split(".")
        if "/" in v or ":" in v or " " in v or len(labels) < 2:
            raise ValueError("api_host es un host (sin esquema, puerto ni ruta), p. ej. api.ejemplo.com")
        if any("*" in lab for lab in labels[1:]):
            raise ValueError("api_host: el comodín va solo en el primer nivel (p. ej. dashscope*.ejemplo.com)")
        if not _LABEL_FIRST.match(labels[0]) or not all(_LABEL.match(lab) for lab in labels[1:]):
            raise ValueError("api_host con caracteres inválidos")
        if "*" in labels[0] and len(labels) < 3:
            raise ValueError("api_host: el comodín necesita al menos dos niveles a su derecha (*.ejemplo.com)")
    else:  # jurisdiction
        if not _CODE.match(v):
            raise ValueError("jurisdicción inválida (código ISO de país o zona)")
    return v


def host_of(api_base: Optional[str]) -> Optional[str]:
    if not api_base:
        return None
    raw = api_base.strip()
    parsed = urlparse(raw if "://" in raw else f"//{raw}")
    return (parsed.hostname or "").lower() or None


def host_matches(pattern: str, host: Optional[str]) -> bool:
    """Host exacto o comodín de **un solo nivel**, a la izquierda: `dashscope*.ejemplo.com` cubre
    `dashscope-intl.ejemplo.com` pero no `a.dashscope.ejemplo.com` ni el dominio pelado."""
    if not host:
        return False
    p, h = pattern.strip().lower().split("."), host.strip().lower().split(".")
    if len(p) != len(h) or p[1:] != h[1:]:
        return False
    return fnmatch.fnmatchcase(h[0], p[0])


# ── evaluación ────────────────────────────────────────────────────────────────────────────────

def _codes(sheet) -> list:
    out = []
    for f in JURISDICTION_FIELDS:
        v = (getattr(sheet, f, None) if sheet is not None else None) or ""
        v = str(v).strip().upper()
        if v and v != "UNKNOWN":
            out.append(v)
    return out


def applicable(rules: Iterable[Any], tenant_id) -> list:
    """Reglas que rigen a una entrada: las de instalación y, si la entrada es de una empresa, las de esa empresa."""
    return [r for r in rules if r.tenant_id is None or (tenant_id is not None and r.tenant_id == tenant_id)]


def first_match(rules: Iterable[Any], *, provider: Optional[str], api_base: Optional[str], sheet=None):
    host, codes = host_of(api_base), _codes(sheet)
    for r in rules:
        if r.kind == "provider" and provider and r.value == provider.lower():
            return r
        if r.kind == "api_host" and host_matches(r.value, host):
            return r
        if r.kind == "jurisdiction" and any(satisfies(c, [r.value]) for c in codes):
            return r
    return None


def load_rules(db) -> list:
    """Todas las reglas que ve la sesión (la RLS acota por empresa en Postgres; acá se vuelve a filtrar al aplicar)."""
    return list(db.query(cm.EnablementRule))


def is_blocked(db, tenant_id, *, provider: str, api_base: Optional[str], sheet=None) -> bool:
    return first_match(applicable(load_rules(db), tenant_id), provider=provider, api_base=api_base,
                       sheet=sheet) is not None


def _clear_enablement(db, entry) -> None:
    entry.enabled_at = entry.enabled_by = entry.enable_reason = None
    if entry.tenant_id is None:                       # entrada de instalación: también las habilitaciones por oferta
        for o in db.query(cm.CatalogOffer).filter(cm.CatalogOffer.entry_id == entry.id):
            o.enabled_at = o.enabled_by = o.enable_reason = None


def reapply(db, entry, rules: Iterable[Any], *, sheet=None, identity_changed: bool = False) -> Optional[str]:
    """Re-evalúa una entrada contra `rules` y deja `blocked_by_default` al día.

    → `"block"` (pasó a bloqueada, o sigue bloqueada pero cambió el destino y exige habilitar de nuevo),
    `"unblock"` (ya no coincide ninguna regla) o `None` (sin cambio). Una habilitación previa se borra al bloquear."""
    hit = first_match(applicable(rules, entry.tenant_id), provider=entry.provider, api_base=entry.api_base,
                      sheet=sheet)
    if hit is not None and not entry.blocked_by_default:
        entry.blocked_by_default = True
        _clear_enablement(db, entry)
        return "block"
    if hit is None and entry.blocked_by_default:
        entry.blocked_by_default = False
        return "unblock"
    if hit is not None and identity_changed and (entry.enabled_at is not None or _offer_enabled(db, entry)):
        _clear_enablement(db, entry)
        return "block"
    return None


def _offer_enabled(db, entry) -> bool:
    return entry.tenant_id is None and db.query(cm.CatalogOffer).filter(
        cm.CatalogOffer.entry_id == entry.id, cm.CatalogOffer.enabled_at.isnot(None)).first() is not None


def reevaluate(db, *, tenant_id=None, only_tenant: bool = False, rules: Optional[list] = None) -> list:
    """Re-evalúa las entradas que una regla puede afectar y devuelve `[(entry, "block"|"unblock"), ...]`.

    `only_tenant=True`: solo las entradas de `tenant_id` (regla de empresa); si no, todas (regla de instalación o seed).
    No hace commit ni registra: quien llama audita y sube la versión de la caché."""
    rules = load_rules(db) if rules is None else rules
    q = db.query(cm.CatalogEntry).filter(cm.CatalogEntry.status != "archived")
    if only_tenant:
        q = q.filter(cm.CatalogEntry.tenant_id == tenant_id)
    changed = []
    for e in q:
        what = reapply(db, e, rules, sheet=db.get(cm.ComplianceSheet, e.id))
        if what:
            changed.append((e, what))
    db.flush()
    return changed


# ── seed ──────────────────────────────────────────────────────────────────────────────────────

def _check_seed(data: Any) -> list:
    """`[(kind, value), ...]` validado entero antes de tocar nada (todo o nada)."""
    if not isinstance(data, Mapping):
        raise ValueError("el seed de habilitación debe ser un mapa con providers, api_hosts y jurisdictions")
    unknown = set(data) - set(SEED_KEYS)
    if unknown:
        raise ValueError(f"claves desconocidas en el seed de habilitación: {', '.join(sorted(map(str, unknown)))}")
    out = []
    for key, kind in SEED_KEYS.items():
        vals = data.get(key)
        if vals is None:
            continue
        if not isinstance(vals, (list, tuple)):
            raise ValueError(f"{key} debe ser una lista")
        for v in vals:
            out.append((kind, validate(kind, v)))
    return out


def seed_rules(db, data: Any, *, reason: str = "seed de la instalación") -> dict:
    """Carga idempotente de reglas de **instalación**. No re-evalúa entradas (lo hace `main`)."""
    wanted = _check_seed(data)
    created = skipped = 0
    for kind, value in dict.fromkeys(wanted):
        exists = db.query(cm.EnablementRule).filter(
            cm.EnablementRule.tenant_id.is_(None), cm.EnablementRule.kind == kind,
            cm.EnablementRule.value == value).first()
        if exists is not None:
            skipped += 1
            continue
        db.add(cm.EnablementRule(level="installation", tenant_id=None, kind=kind, value=value,
                                 reason=reason, created_by_role=SEED_ROLE))
        created += 1
    db.flush()
    return {"created": created, "skipped": skipped}


def load_seed_file(path) -> Any:
    import yaml
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return {} if data is None else data


def main(argv=None) -> int:  # pragma: no cover — usa la base real
    import sys
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 1:
        print("uso: python -m sentinel.catalog.habilitacion <habilitacion-explicita.yaml>", file=sys.stderr)
        return 2
    from src.database import SessionLocal, tenant_context
    data = load_seed_file(argv[0])
    with tenant_context(None, bypass=True):
        db = SessionLocal()
        try:
            r = seed_rules(db, data, reason=f"seed: {argv[0].rsplit('/', 1)[-1]}")
            changed = reevaluate(db)
            db.commit()
        finally:
            db.close()
    print(f"habilitación: {r['created']} reglas sembradas, {r['skipped']} ya existían, "
          f"{len(changed)} entradas re-evaluadas con cambio")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
