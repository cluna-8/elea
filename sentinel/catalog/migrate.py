"""Migración de una vez a un catálogo único (069 T030; FR-040, FR-041, FR-043).

Los destinos de la 068 pasan a ser entradas del catálogo CON EL MISMO ID (así las reglas, ofertas
y autorizaciones existentes siguen apuntando bien) y conservan su credencial (el blob cifrado se
copia tal cual: nunca se descifra aquí). Nacen **sin clasificar** (FR-039/041): la clasificación
es trabajo humano con el DPA en la mano.

`mirror_destination` es idempotente y es lo que la API de la 068 llama tras cada escritura mientras
la tabla `sentinel_redirect_destination` convive con el catálogo; `migrate_all` recorre todo (CLI:
`python -m sentinel.catalog.migrate`). Una ficha que alguien ya editó en la consola NUNCA se pisa.

La migración de los modelos de consola de `config.yaml` (`migrated_yaml`) vive en
`sentinel/catalog/migrate_yaml.py`.
"""
from __future__ import annotations

import uuid
from typing import Optional

from sentinel.redirect import models as rm

from . import models as cm

_NS = uuid.UUID("5a1f0e69-0069-4c0d-9a77-6f0b8d3c2e11")
_STATUS_TO_ENTRY = {"active": "active", "inactive": "inactive", "revoked": "archived"}
_MACHINE_VERSIONS = ("migrated_068", "console:0")      # fichas que ningún humano editó


def credential_id_for(dest_id) -> uuid.UUID:
    """Id estable de la credencial migrada de un destino: la migración es idempotente."""
    return uuid.uuid5(_NS, f"cred:{dest_id}")


def _price(po: Optional[dict], key: str):
    if not isinstance(po, dict) or po.get(key) is None:
        return None
    return float(po[key]) / 1e6


def _mirror_credential(db, d: rm.RedirectDestination, entry: cm.CatalogEntry) -> None:
    cid = credential_id_for(d.id)
    row = db.get(cm.Credential, cid)
    if d.status == "revoked" or not d.credential_encrypted:
        if row is not None and row.status == "active":
            row.status, row.ciphertext = "revoked", None
        entry.credential_id = None
        return
    if row is None:
        row = cm.Credential(id=cid, level=d.level, tenant_id=d.tenant_id, name=_free_name(db, d),
                            kind="secret", ciphertext=d.credential_encrypted, fingerprint=_fp(d),
                            created_by=d.created_by)
        db.add(row)
    elif row.ciphertext != d.credential_encrypted or row.status != "active":
        row.ciphertext, row.status, row.fingerprint = d.credential_encrypted, "active", _fp(d)
    db.flush()
    entry.credential_id = row.id


def _free_name(db, d) -> str:
    base, n = f"{d.name} (destino)", 0
    while db.query(cm.Credential).filter(cm.Credential.tenant_id == d.tenant_id,
                                         cm.Credential.name == (base if not n else f"{base} {n}"),
                                         cm.Credential.status == "active").first():
        n += 1
    return base if not n else f"{base} {n}"


def _fp(d) -> str:
    """Huella de la credencial migrada: del blob (no del secreto), solo para identificarla."""
    import hashlib
    return hashlib.sha256((d.credential_encrypted or "").encode()).hexdigest()[-4:]


def free_public_id(db, tenant_id, name: str) -> str:
    """Slug del nombre, desambiguado dentro de su alcance (organización o instalación)."""
    base = cm.slugify(name) or "modelo"
    taken = {r[0] for r in db.query(cm.CatalogEntry.public_id).filter(
        cm.CatalogEntry.tenant_id == tenant_id, cm.CatalogEntry.status != "archived")}
    cand, n = base, 1
    while cand in taken:
        n += 1
        cand = f"{base}-{n}"
    return cand


def mirror_destination(db, d: rm.RedirectDestination) -> cm.CatalogEntry:
    entry = db.get(cm.CatalogEntry, d.id)
    new = entry is None
    if new:
        entry = cm.CatalogEntry(id=d.id, source="migrated_068", created_by=d.created_by,
                                is_aggregator=d.provider == "openrouter",
                                public_id=free_public_id(db, d.tenant_id, d.name))
        db.add(entry)
    entry.level, entry.tenant_id, entry.name = d.level, d.tenant_id, d.name
    entry.provider, entry.real_model, entry.protocol_family = d.provider, d.real_model, d.protocol_family
    entry.api_base, entry.provider_options = d.api_base, dict(d.provider_options or {})
    entry.features = dict(d.capability_profile or {})
    entry.context_window, entry.max_output = d.context_window, d.max_output
    po = d.price_override
    entry.price_input, entry.price_output = _price(po, "input_per_mtok"), _price(po, "output_per_mtok")
    entry.blocked_by_default = bool(d.blocked_by_default)
    entry.enabled_at, entry.enabled_by, entry.enable_reason = d.enabled_at, d.enabled_by, d.enable_reason
    entry.status = _STATUS_TO_ENTRY.get(d.status, "active")
    if entry.status == "archived" and not entry.archived_reason:
        entry.archived_reason = "revocado (política de redirección)"
    entry.updated_by = d.updated_by
    db.flush()
    _mirror_credential(db, d, entry)

    sheet = db.get(cm.ComplianceSheet, entry.id)
    if sheet is None:
        sheet = cm.ComplianceSheet(entry_id=entry.id, classification_version="migrated_068")
        db.add(sheet)
    if sheet.classification_version in _MACHINE_VERSIONS:    # nunca pisar una ficha editada
        sheet.inference_jurisdiction = (d.inference_jurisdiction or "unknown")
        sheet.entity_jurisdiction = d.entity_jurisdiction
    db.flush()
    mirror_offers(db, d.id)
    return entry


def mirror_offers(db, dest_id) -> None:
    """Las ofertas del destino en la 068 → ofertas de la entrada (misma clave natural)."""
    want = {o.tenant_id: o for o in db.query(rm.RedirectOffer).filter(rm.RedirectOffer.destination_id == dest_id)}
    have = {o.tenant_id: o for o in db.query(cm.CatalogOffer).filter(cm.CatalogOffer.entry_id == dest_id)}
    for t, o in have.items():
        if t not in want:
            db.delete(o)
    for t, o in want.items():
        row = have.get(t)
        if row is None:
            row = cm.CatalogOffer(id=uuid.uuid4(), entry_id=dest_id, tenant_id=t, created_by=o.created_by)
            db.add(row)
        row.enabled_at, row.enabled_by, row.enable_reason = o.enabled_at, o.enabled_by, o.enable_reason
    db.flush()


def migrate_all(db) -> int:
    """Recorre todos los destinos de la 068 (sesión con bypass). Devuelve cuántos migró."""
    n = 0
    for d in db.query(rm.RedirectDestination).order_by(rm.RedirectDestination.created_at):
        mirror_destination(db, d)
        n += 1
    return n


def main() -> int:  # pragma: no cover — usa la base real
    from src.database import SessionLocal, tenant_context
    with tenant_context(None, bypass=True):
        db = SessionLocal()
        try:
            n = migrate_all(db)
            db.commit()
        finally:
            db.close()
    print(f"catálogo: {n} destino(s) de la 068 migrados (idempotente)")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
