"""Cargador idempotente de regiones del perfil (057 FR-030, FR-031; research R13, R23; data-model §1) [BASE].

    python -m sentinel.redirect.regions_seed <archivo.yaml>

El archivo es un mapa `regions: [...]`; cada región lleva `name` (mayúsculas, sin espacios), `level: installation`,
`jurisdictions` (códigos ISO o zonas; no vacía), `region_profiles`, `default_posture`
(`reject_offregion` | `masked_offregion` | `masked_all` | `allow`) e `is_zone`.

- **Crea, no pisa**: si la fila (o un perfil que ya resuelve otra de instalación) existe, se salta. Una edición del
  panel o de la API —una relajación por región, por ejemplo— no se revierte al reiniciar.
- **Todo o nada**: se valida el archivo entero antes de escribir; un valor desconocido de `default_posture` es un error.
- Cada alta queda en el registro de cambios (`entity = region`, rol `seed`, con motivo).

Es dato de la instalación, no código: la región de cada cliente (Eleia: `deploy/redirect-seeds/regions.americas.yaml`)
se carga con este mismo cargador. Ningún texto de este módulo nombra una región, un país ni una marca."""
from __future__ import annotations

import logging
import re
from typing import Any, Mapping

from . import models as m
from .residency import DEFAULT_POSTURES

logger = logging.getLogger("sentinel.redirect.regions_seed")

SEED_ROLE = "seed"
_KEYS = {"name", "level", "is_zone", "region_profiles", "default_posture", "jurisdictions"}
_NAME = re.compile(r"^[A-Z][A-Z0-9_-]{0,63}$")
_CODE = re.compile(r"^[A-Z][A-Z0-9_-]{0,15}$")

# Inyectable para tests y para el arranque: `() -> Session`. Sin él, `src.database.SessionLocal` con bypass de RLS.
SESSION_FACTORY = None


def _list_of_str(value: Any, what: str) -> list:
    if not isinstance(value, (list, tuple)) or not all(isinstance(v, str) for v in value):
        raise ValueError(f"{what} debe ser una lista de textos")
    return list(value)


def check_seed(data: Any) -> list:
    """Valida el documento entero y devuelve `[dict normalizado, ...]`. Levanta `ValueError` con el motivo."""
    if not isinstance(data, Mapping):
        raise ValueError("el seed de regiones debe ser un mapa con la clave `regions`")
    unknown = set(data) - {"regions"}
    if unknown:
        raise ValueError(f"claves desconocidas en el seed de regiones: {', '.join(sorted(map(str, unknown)))}")
    regions = data.get("regions")
    if not isinstance(regions, (list, tuple)):
        raise ValueError("`regions` debe ser una lista")
    out, names = [], set()
    for i, raw in enumerate(regions):
        where = f"regions[{i}]"
        if not isinstance(raw, Mapping):
            raise ValueError(f"{where} debe ser un mapa")
        extra = set(raw) - _KEYS
        if extra:
            raise ValueError(f"{where}: claves desconocidas: {', '.join(sorted(map(str, extra)))}")
        name = raw.get("name")
        if not isinstance(name, str) or not _NAME.match(name):
            raise ValueError(f"{where}: `name` va en mayúsculas, sin espacios")
        if raw.get("level", "installation") != "installation":
            raise ValueError(f"{where}: el seed solo siembra regiones de nivel instalación")
        posture = raw.get("default_posture")
        if posture not in DEFAULT_POSTURES:
            raise ValueError(f"{where}: `default_posture` desconocido: {posture!r} (válidos: {', '.join(DEFAULT_POSTURES)})")
        juris = []
        for code in _list_of_str(raw.get("jurisdictions"), f"{where}: `jurisdictions`"):
            code = code.strip().upper()
            if not code:
                continue
            if not _CODE.match(code):
                raise ValueError(f"{where}: jurisdicción inválida: {code!r}")
            if code not in juris:
                juris.append(code)
        if not juris:
            raise ValueError(f"{where}: `jurisdictions` no puede quedar vacía")
        profiles = []
        for p in _list_of_str(raw.get("region_profiles", []), f"{where}: `region_profiles`"):
            p = p.strip().lower()
            if p and p not in profiles:
                profiles.append(p)
        is_zone = raw.get("is_zone", False)
        if not isinstance(is_zone, bool):
            raise ValueError(f"{where}: `is_zone` es verdadero o falso")
        if name in names:
            raise ValueError(f"{where}: el nombre {name} se repite en el archivo")
        names.add(name)
        out.append({"name": name, "jurisdictions": juris, "region_profiles": profiles,
                    "default_posture": posture, "is_zone": is_zone})
    return out


def seed_regions(db, data: Any, *, reason: str = "seed de la instalación") -> dict:
    """Carga idempotente de regiones de **instalación**: crea las que faltan y no toca las que existen."""
    wanted = check_seed(data)
    created = skipped = 0
    for r in wanted:
        existing = db.query(m.RedirectRegion).filter(m.RedirectRegion.tenant_id.is_(None)).all()
        if any(e.name == r["name"] for e in existing):
            skipped += 1
            continue
        taken = {str(p).strip().lower() for e in existing for p in (e.region_profiles or ())} & set(r["region_profiles"])
        if taken:
            logger.warning("regiones: %s no se siembra, un perfil ya resuelve a otra región de la instalación", r["name"])
            skipped += 1
            continue
        row = m.RedirectRegion(level="installation", tenant_id=None, **r)
        db.add(row)
        db.flush()
        db.add(m.RedirectConfigAudit(
            tenant_id=None, entity="region", entity_id=str(row.id), action="create", before=None,
            after={"name": row.name, "default_posture": row.default_posture, "level": "installation"},
            actor_id=None, actor_role=SEED_ROLE, reason=reason))
        created += 1
    db.flush()
    return {"created": created, "skipped": skipped}


def load_seed_file(path) -> Any:
    import yaml
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return {"regions": []} if data is None else data


def _open_session():
    if SESSION_FACTORY is not None:
        return SESSION_FACTORY(), None
    from src.database import SessionLocal, tenant_context
    ctx = tenant_context(None, bypass=True)
    ctx.__enter__()
    return SessionLocal(), ctx


def main(argv=None) -> int:
    import sys
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 1:
        print("uso: python -m sentinel.redirect.regions_seed <regiones.yaml>", file=sys.stderr)
        return 2
    try:
        data = load_seed_file(argv[0])
        check_seed(data)
    except (ValueError, OSError) as exc:
        print(f"regiones: {exc}", file=sys.stderr)
        return 1
    db, ctx = _open_session()
    try:
        result = seed_regions(db, data, reason=f"seed: {str(argv[0]).rsplit('/', 1)[-1]}")
        db.commit()
    finally:
        db.close()
        if ctx is not None:
            ctx.__exit__(None, None, None)
    print(f"regiones: {result['created']} sembradas, {result['skipped']} ya existían")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
