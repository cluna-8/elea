"""Precondiciones de la relajación del enmascarado forzado por destino (057 FR-031a; data-model §3; research R24).

Una relajación por destino solo vale mientras la ficha del destino tenga cargadas la jurisdicción de inferencia, la de
la entidad y la de control, la retención cero en `true` y, si el destino es un agregador, la lista de proveedores
permitidos. Este módulo calcula qué precondición falta y revoca (sin borrar la fila: queda el historial) las
relajaciones cuya ficha dejó de cumplirlas; la API de altas y bajas de relajaciones es de la residencia (T-E).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Optional

from sentinel.redirect import models as rm

REVOKE_REASON = "precondicion_incumplida"


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


def revoke_unmet(db, entry: Any, sheet: Any, user: Any = None, *,
                 audit: Optional[Callable[..., None]] = None) -> list:
    """Revoca las relajaciones vigentes de `entry` si su ficha ya no cumple las precondiciones. Devuelve las revocadas."""
    unmet = unmet_preconditions(entry, sheet)
    if not unmet:
        return []
    vigentes = (db.query(rm.RedirectMaskingRelaxation)
                .filter(rm.RedirectMaskingRelaxation.entry_id == entry.id,
                        rm.RedirectMaskingRelaxation.revoked_at.is_(None)).all())
    for r in vigentes:
        r.revoked_at, r.revoked_by, r.revoke_reason = datetime.now(timezone.utc), getattr(user, "id", None), REVOKE_REASON
        if audit is not None:
            audit(entity="masking_relaxation", entity_id=r.id, action="revoke", tenant_id=r.tenant_id,
                  before={"entry_id": str(entry.id), "level": r.level}, after={"unmet": unmet}, reason=REVOKE_REASON)
    return vigentes
