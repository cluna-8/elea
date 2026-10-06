"""Lecturas del catálogo y vistas derivadas (069 T027; FR-001a, FR-003a).

Una sola puerta para «qué ve cada organización»: sus entradas propias más las de instalación que le
ofrecieron. La API de administración, la instantánea del plano de datos y `/internal/model-catalog`
construyen sus vistas con `entry_view`, así el semáforo es idéntico en todas (FR-003a).

Nunca devuelve credenciales: `has_credential` y, solo para quien es dueño de la entrada, la huella.
"""
from __future__ import annotations

import uuid
from datetime import date
from typing import Any, Callable, Iterable, Mapping, Optional

from sentinel.redirect.residency import satisfies

from . import models as cm
from .semaforo import semaforo

STALE = "stale"
SHEET_FIELDS = ("provider_legal_entity", "entity_jurisdiction", "inference_jurisdiction",
                "logs_jurisdiction", "zero_data_retention", "trains_on_data", "transfer_mechanism",
                "dpa_registry_id", "eu_region_contracted", "notes")

DpaLookup = Callable[[Any, Any, Any], Optional[Mapping[str, Any]]]


def _s(v) -> Optional[str]:
    return None if v is None else str(v)


def _iso(v) -> Optional[str]:
    return v.isoformat() if hasattr(v, "isoformat") else _s(v)


def sheet_view(sheet: Optional[cm.ComplianceSheet]) -> dict:
    if sheet is None:
        return {f: None for f in SHEET_FIELDS} | {
            "inference_jurisdiction": "unknown", "logs_jurisdiction": "unknown",
            "transfer_mechanism": "unknown", "classification_version": "console:0",
            "classified_by": None, "classified_at": None}
    out = {f: getattr(sheet, f) for f in SHEET_FIELDS}
    out["dpa_registry_id"] = _s(sheet.dpa_registry_id)
    out.update(classification_version=sheet.classification_version,
               classified_by=_s(sheet.classified_by), classified_at=_iso(sheet.classified_at))
    return out


def semaforo_of(entry: cm.CatalogEntry, sheet: Optional[cm.ComplianceSheet],
                dpa: Optional[Mapping[str, Any]], today: date) -> dict:
    """La regla única (FR-003a): misma función para pantalla, residencia, perfiles y motor."""
    return semaforo(sheet_view(sheet), dpa, es_agregador=bool(entry.is_aggregator), hoy=today,
                    desactualizada=bool(sheet and sheet.classification_version == STALE))


def region_ue(sheet: Optional[cm.ComplianceSheet]) -> Optional[bool]:
    """Marca «Región UE» (FR-053; D28): derivada, nunca almacenada, distinta del semáforo.

    `true` si la jurisdicción de inferencia de la ficha está en la UE (`EU` o un país miembro, según
    `residency.satisfies(code, {"EU"})`); `false` si es una jurisdicción conocida fuera de la UE;
    `null` si no se sabe: sin ficha, `unknown` o vacía. La inferencia **local** (infraestructura propia)
    no dice dónde está la máquina: es `null`, salvo que la ficha declare una entidad (`entity_jurisdiction`)
    de la UE, caso en que es `true`."""
    code = None if sheet is None else (sheet.inference_jurisdiction or "").strip()
    if not code or code.lower() == "unknown":
        return None
    if code.lower() == "local":
        return True if satisfies(sheet.entity_jurisdiction, {"EU"}) else None
    return satisfies(code, {"EU"})


def entry_view(entry: cm.CatalogEntry, sheet: Optional[cm.ComplianceSheet],
               credential: Optional[cm.Credential], dpa: Optional[Mapping[str, Any]], today: date,
               *, owner: bool) -> dict:
    """Vista de una entrada. `owner`: quien la administra (ve la huella de la credencial)."""
    out = {
        "id": _s(entry.id), "level": entry.level, "tenant_id": _s(entry.tenant_id), "name": entry.name,
        "public_id": entry.public_id, "provider": entry.provider, "real_model": entry.real_model,
        "protocol_family": entry.protocol_family, "api_base": entry.api_base,
        "is_aggregator": bool(entry.is_aggregator), "role": entry.role,
        "capability": entry.capability, "features": dict(entry.features or {}),
        "context_window": entry.context_window, "max_output": entry.max_output,
        "price": {"input": None if entry.price_input is None else float(entry.price_input),
                  "output": None if entry.price_output is None else float(entry.price_output),
                  "cache_read": None if entry.price_cache_read is None else float(entry.price_cache_read),
                  "cache_write": None if entry.price_cache_write is None else float(entry.price_cache_write),
                  "tiers": entry.price_tiers,
                  "source": entry.price_source, "at": _iso(entry.price_at)},
        "limits": dict(entry.limits or {}), "base_model": entry.base_model,
        "advanced": dict(entry.advanced or {}), "unsupported_params": list(entry.unsupported_params or []),
        "region_ue": region_ue(sheet),
        "blocked_by_default": bool(entry.blocked_by_default), "enabled_at": _iso(entry.enabled_at),
        "status": entry.status, "source": entry.source,
        "has_credential": entry.credential_id is not None and credential is not None
        and credential.status == "active",
        "sheet": sheet_view(sheet), "semaforo": semaforo_of(entry, sheet, dpa, today),
        # solo lo que el semáforo necesita ver del DPA (vigencia y región), nunca el documento
        "dpa": None if dpa is None else {
            "expiration_date": _iso(dpa.get("expiration_date")),
            "processing_region": dpa.get("processing_region"), "is_active": bool(dpa.get("is_active", True))},
    }
    if owner and credential is not None:
        out["credential"] = {"id": _s(credential.id), "name": credential.name,
                             "kind": credential.kind, "fingerprint": credential.fingerprint}
    return out


def visible_entries(db, tenant_id, *, operator: bool, include_archived: bool = False) -> list:
    """Entradas propias + de instalación ofrecidas a `tenant_id`; el operador ve toda la instalación.

    Defensa en profundidad además de la RLS (que en Postgres hace lo mismo desde la base)."""
    tid = uuid.UUID(str(tenant_id))
    offered = {o.entry_id for o in db.query(cm.CatalogOffer).filter(
        (cm.CatalogOffer.tenant_id == tid) | (cm.CatalogOffer.tenant_id.is_(None)))}
    rows = []
    for e in db.query(cm.CatalogEntry):
        if not include_archived and e.status == "archived":
            continue
        if e.tenant_id == tid or (e.tenant_id is None and (operator or e.id in offered)):
            rows.append(e)
    return sorted(rows, key=lambda e: (e.level, e.name))


def sheet_of(db, entry_id) -> Optional[cm.ComplianceSheet]:
    return db.get(cm.ComplianceSheet, entry_id)


def credential_of(db, entry: cm.CatalogEntry) -> Optional[cm.Credential]:
    return db.get(cm.Credential, entry.credential_id) if entry.credential_id else None


def offered_tenants(db, entry_id) -> list:
    return sorted("*" if o.tenant_id is None else str(o.tenant_id)
                  for o in db.query(cm.CatalogOffer).filter(cm.CatalogOffer.entry_id == entry_id))


# ── puente con la 068: el catálogo es la fuente de los «destinos» ───────────────────

_STATUS_TO_DESTINATION = {"active": "active", "inactive": "inactive", "archived": "revoked"}
ENV_BLOB_PREFIX = "env_ref:"


def _jur(v: Optional[str]) -> Optional[str]:
    return None if v in (None, "", "unknown") else v


def _price_override(entry: cm.CatalogEntry) -> Optional[dict]:
    """USD por millón de tokens (forma de la 068); en el catálogo se guarda por token."""
    if entry.price_input is None and entry.price_output is None:
        return None
    return {"input_per_mtok": round(float(entry.price_input or 0) * 1e6, 6),
            "output_per_mtok": round(float(entry.price_output or 0) * 1e6, 6)}


def entry_to_destination(entry: cm.CatalogEntry, sheet: Optional[cm.ComplianceSheet],
                         credential: Optional[cm.Credential]) -> dict:
    """Entrada del catálogo → dict de destino que consumen el resolver y la pasarela (sin credencial)."""
    return {
        "id": _s(entry.id), "public_id": entry.public_id, "level": entry.level,
        "tenant_id": _s(entry.tenant_id), "name": entry.name,
        "provider": entry.provider, "real_model": entry.real_model,
        "protocol_family": entry.protocol_family, "role": entry.role,
        "inference_jurisdiction": _jur(sheet.inference_jurisdiction if sheet else None),
        "entity_jurisdiction": _jur(sheet.entity_jurisdiction if sheet else None),
        "blocked_by_default": bool(entry.blocked_by_default), "enabled_at": _iso(entry.enabled_at),
        "enable_reason": entry.enable_reason,
        "has_credential": credential is not None and credential.status == "active",
        "api_base": entry.api_base, "provider_options": dict(entry.provider_options or {}),
        "capability_profile": dict(entry.features or {}),
        "unsupported_params": list(entry.unsupported_params or []),
        "context_window": entry.context_window, "max_output": entry.max_output,
        "price_override": _price_override(entry), "status": _STATUS_TO_DESTINATION[entry.status],
    }


def credential_blob(credential: Optional[cm.Credential]) -> Optional[str]:
    """Lo que el almacén de la pasarela descifra por pedido: el JSON cifrado, o la referencia a
    variable del servidor (que solo resuelve el motor)."""
    if credential is None or credential.status != "active":
        return None
    return ENV_BLOB_PREFIX + credential.env_name if credential.kind == "env_ref" else credential.ciphertext


def catalog_destinations(db, tenant_id) -> tuple:
    """`(destinos, ofertas, credenciales)` del catálogo visibles para `tenant_id`, en la forma de la
    instantánea de la 068."""
    tid = uuid.UUID(str(tenant_id))
    dests, creds, offers = {}, {}, []
    for e in visible_entries(db, tid, operator=False, include_archived=True):
        cred = credential_of(db, e)
        dests[str(e.id)] = entry_to_destination(e, sheet_of(db, e.id), cred)
        blob = credential_blob(cred)
        if blob:
            creds[str(e.id)] = blob
        if e.tenant_id is None:
            for o in db.query(cm.CatalogOffer).filter(
                    cm.CatalogOffer.entry_id == e.id,
                    (cm.CatalogOffer.tenant_id == tid) | (cm.CatalogOffer.tenant_id.is_(None))):
                offers.append({"destination_id": str(e.id),
                               "tenant_id": _s(o.tenant_id) if o.tenant_id else "*",
                               "enabled_at": _iso(o.enabled_at)})
    return dests, offers, creds


# Roles que sirven a la redirección: las caras de la 068 son de chat/texto (E3: embeddings, imagen, audio y
# rerank se piden directo al motor por su id público y no pasan por reglas).
REDIRECT_ROLES = ("text",)


def redirect_destinations(db, tenant_id) -> list:
    """Los «destinos» que la redirección ofrece a `tenant_id` (069 E3): entradas **activas** del catálogo, de
    rol de texto, propias o de instalación ofrecidas a la organización. Mismo dict que la instantánea del plano
    de datos (`entry_to_destination`), así lo que se lista, lo que valida una regla y lo que sirve el motor sale
    de la misma lectura. Archivadas e inactivas no figuran; las bloqueadas por defecto sí (con su marca)."""
    out = []
    for e in visible_entries(db, tenant_id, operator=False):
        if e.status != "active" or e.role not in REDIRECT_ROLES:
            continue
        out.append(entry_to_destination(e, sheet_of(db, e.id), credential_of(db, e)))
    return out
