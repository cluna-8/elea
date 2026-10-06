"""Siembra del catálogo desde el perfil de instalación (069 T031; FR-007; research D4, D5).

El deploy es dueño de la plantilla y del fragmento; la consola, de las tablas. Esta siembra solo
**inserta lo que falta**: una entrada existente (mismo nombre, nivel instalación) no se toca y su
ficha tampoco, aunque la semilla cambie (nunca pisa lo que alguien editó). Sin credenciales: las carga
el operador desde la consola. Todo o nada: una semilla inválida falla fuerte y no siembra nada.

Uso: `python -m sentinel.catalog.seed <catalog-seed.yaml>` (idempotente).
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from . import habilitacion as hb
from . import models as cm
from .store import SHEET_FIELDS

_ENTRY_KEYS = {"name", "public_id", "provider", "real_model", "protocol_family", "api_base", "aggregator", "role",
               "capability", "features", "context_window", "max_output", "price_input_per_mtok",
               "price_output_per_mtok", "price_source", "sheet"}


def load_seed_file(path) -> dict:
    import yaml
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return data or {}


def _validate(seed: Mapping[str, Any]) -> list[dict]:
    entries = seed.get("entries")
    if not isinstance(entries, list):
        raise ValueError("la semilla debe traer `entries`")
    names = set()
    for i, e in enumerate(entries):
        where = f"entries[{i}]"
        if not isinstance(e, Mapping) or not e.get("name"):
            raise ValueError(f"{where}: falta el nombre")
        unknown = set(e) - _ENTRY_KEYS
        if unknown:           # p. ej. `credential`: la semilla jamás carga secretos
            raise ValueError(f"{where}: campos no admitidos: {', '.join(sorted(unknown))}")
        if e.get("provider") not in cm.PROVIDERS:
            raise ValueError(f"{where}: proveedor desconocido")
        if e.get("protocol_family") not in cm.PROTOCOL_FAMILIES:
            raise ValueError(f"{where}: familia de protocolo desconocida")
        if not e.get("real_model"):
            raise ValueError(f"{where}: falta el modelo real")
        if e.get("name") in names:
            raise ValueError(f"{where}: nombre repetido")
        names.add(e["name"])
        bad = set(e.get("sheet") or {}) - set(SHEET_FIELDS)
        if bad:
            raise ValueError(f"{where}.sheet: campos no admitidos: {', '.join(sorted(bad))}")
    return entries


def _version(e: Mapping[str, Any]) -> str:
    canon = json.dumps(e.get("sheet") or {}, sort_keys=True, default=str)
    return "seed:" + hashlib.sha256(canon.encode()).hexdigest()[:8]


def seed_catalog(db, seed: Mapping[str, Any]) -> dict:
    entries = _validate(seed)
    created, skipped = [], []
    now = datetime.now(timezone.utc)
    for e in entries:
        row = db.query(cm.CatalogEntry).filter(cm.CatalogEntry.level == "installation",
                                               cm.CatalogEntry.name == e["name"]).first()
        if row is None:
            ppm_in, ppm_out = e.get("price_input_per_mtok"), e.get("price_output_per_mtok")
            from .migrate import free_public_id
            row = cm.CatalogEntry(
                level="installation", tenant_id=None, name=e["name"],
                public_id=e.get("public_id") or free_public_id(db, None, e["name"]),
                provider=e["provider"],
                real_model=e["real_model"], protocol_family=e["protocol_family"],
                api_base=e.get("api_base"),
                is_aggregator=bool(e.get("aggregator", e["provider"] == "openrouter")),
                role=e.get("role", "text"), capability=e.get("capability", "standard"),
                features=dict(e.get("features") or {}), context_window=e.get("context_window"),
                max_output=e.get("max_output"),
                price_input=None if ppm_in is None else float(ppm_in) / 1e6,
                price_output=None if ppm_out is None else float(ppm_out) / 1e6,
                price_source=e.get("price_source"),
                blocked_by_default=hb.is_blocked(db, None, provider=e["provider"], api_base=e.get("api_base")),
                source="seed", status="active")
            db.add(row)
            db.flush()
            created.append(e["name"])
        else:
            skipped.append(e["name"])
        if db.get(cm.ComplianceSheet, row.id) is None and e.get("sheet"):
            s = cm.ComplianceSheet(entry_id=row.id, classification_version=_version(e),
                                   classified_at=now)
            for k, v in e["sheet"].items():
                if v is not None or k in ("zero_data_retention", "trains_on_data",
                                          "eu_region_contracted"):
                    setattr(s, k, v)
            db.add(s)
        elif db.get(cm.ComplianceSheet, row.id) is None:
            db.add(cm.ComplianceSheet(entry_id=row.id))
        db.flush()
    return {"created": created, "skipped": skipped}


def main(argv=None) -> int:  # pragma: no cover — usa la base real
    import sys
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 1:
        print("uso: python -m sentinel.catalog.seed <catalog-seed.yaml>", file=sys.stderr)
        return 2
    from src.database import SessionLocal, tenant_context
    seed = load_seed_file(argv[0])
    with tenant_context(None, bypass=True):
        db = SessionLocal()
        try:
            r = seed_catalog(db, seed)
            db.commit()
        finally:
            db.close()
    print(f"catálogo: {len(r['created'])} sembradas, {len(r['skipped'])} ya existían")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
