"""Precondiciones de la relajación del enmascarado forzado por destino (057 FR-031a; data-model §3; research R24).

Una relajación por destino solo vale mientras la ficha del destino tenga cargadas la jurisdicción de inferencia, la de
la entidad y la de control, la retención cero en `true` y, si el destino es un agregador, la lista de proveedores
permitidos. Este módulo calcula qué precondición falta y revoca (sin borrar la fila: queda el historial) las
relajaciones cuya ficha dejó de cumplirlas; la API de altas y bajas de relajaciones es de la residencia (T-E).

Una relajación se concede a **un destino** (a ese alojador, con esa ficha): si cambia el destino —proveedor, `api_base`,
modelo real, `is_aggregator` o la lista de proveedores permitidos de un agregador— la relajación se revoca en el mismo
cambio (`destino_modificado`; 057 H2 del QA de T-B): quien edita la entrada, que no es quien relaja, no puede apuntar el
destino a otro alojador sin perderla. Archivar la entrada también la revoca (`entrada_archivada`).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Optional

from sentinel.redirect import models as rm

REVOKE_REASON = "precondicion_incumplida"
REVOKE_REASON_DESTINO = "destino_modificado"
REVOKE_REASON_ARCHIVADA = "entrada_archivada"
IDENTITY_FIELDS = ("provider", "api_base", "real_model", "is_aggregator", "providers_allowlist")


def _loaded(code: Optional[str]) -> bool:
    return bool(code and str(code).strip() and str(code).strip().lower() != "unknown")


def unmet_preconditions(entry: Any, sheet: Any) -> list:
    """Nombres de las precondiciones que la ficha no cumple (vacío ⇒ la relajación puede regir)."""
    unmet = [f for f in ("inference_jurisdiction", "entity_jurisdiction", "control_jurisdiction")
             if not _loaded(getattr(sheet, f, None))]
    if getattr(sheet, "zero_data_retention", None) is not True:
        unmet.append("zero_data_retention")
    if getattr(entry, "is_aggregator", False) and not (getattr(entry, "provider_options", None) or {}).get(
            "providers_allowlist"):
        unmet.append("providers_allowlist")
    return unmet


def identity_of(entry: Any) -> dict:
    """La identidad del destino de una entrada: lo que, si cambia, es *otro* destino y no el que se relajó."""
    allow = (getattr(entry, "provider_options", None) or {}).get("providers_allowlist") or ()
    if isinstance(allow, str):
        allow = [allow]
    return {"provider": getattr(entry, "provider", None), "api_base": getattr(entry, "api_base", None),
            "real_model": getattr(entry, "real_model", None),
            "is_aggregator": bool(getattr(entry, "is_aggregator", False)),
            "providers_allowlist": sorted({str(p).strip().lower() for p in allow})}


def changed_identity(before: dict, entry: Any) -> list:
    """Nombres (nunca valores) de los campos de identidad que cambiaron respecto de `before`."""
    now = identity_of(entry)
    return [f for f in IDENTITY_FIELDS if before.get(f) != now[f]]


def _revoke_active(db, entry: Any, user: Any, reason: str, audit, after: dict) -> list:
    vigentes = (db.query(rm.RedirectMaskingRelaxation)
                .filter(rm.RedirectMaskingRelaxation.entry_id == entry.id,
                        rm.RedirectMaskingRelaxation.revoked_at.is_(None)).all())
    for r in vigentes:
        r.revoked_at, r.revoked_by, r.revoke_reason = datetime.now(timezone.utc), getattr(user, "id", None), reason
        if audit is not None:
            audit(entity="masking_relaxation", entity_id=r.id, action="revoke", tenant_id=r.tenant_id,
                  before={"entry_id": str(entry.id), "level": r.level}, after=after, reason=reason)
    return vigentes


def revoke_unmet(db, entry: Any, sheet: Any, user: Any = None, *,
                 audit: Optional[Callable[..., None]] = None) -> list:
    """Revoca las relajaciones vigentes de `entry` si su ficha ya no cumple las precondiciones. Devuelve las revocadas."""
    unmet = unmet_preconditions(entry, sheet)
    if not unmet:
        return []
    return _revoke_active(db, entry, user, REVOKE_REASON, audit, {"unmet": unmet})


def revoke_for_identity_change(db, entry: Any, before: dict, user: Any = None, *,
                               audit: Optional[Callable[..., None]] = None) -> list:
    """Revoca las relajaciones vigentes de `entry` si cambió su identidad respecto de `before` (`identity_of` tomada
    antes de aplicar el cambio). Devuelve las revocadas; sin cambio de identidad, no toca nada."""
    changed = changed_identity(before, entry)
    if not changed:
        return []
    return _revoke_active(db, entry, user, REVOKE_REASON_DESTINO, audit, {"changed": changed})


def revoke_for_archive(db, entry: Any, user: Any = None, *, audit: Optional[Callable[..., None]] = None) -> list:
    """Una entrada archivada ya no es un destino: sus relajaciones vigentes se revocan (queda el historial)."""
    return _revoke_active(db, entry, user, REVOKE_REASON_ARCHIVADA, audit, {"archived": True})
