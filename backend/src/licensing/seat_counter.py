"""Definición ÚNICA de seat (spec 021 — [D-021], FR-013/FR-014).

seat = Connection ACTIVA (``APIKey.is_active``) y no expirada, contada POR
tenant — la misma definición de "activa" que respalda el índice parcial
``uq_api_keys_tenant_user_tool``. Esta función es LA fuente de verdad del
conteo: la usan el gate de creación (US2) y la reconciliación (US3); nunca
duplicar la query en otro lado.

Ortogonal a la gobernanza de uso (007): ``rpm_limit``/``tpm_limit``/
``max_budget`` no participan — un seat castigado a 0 rpm sigue siendo un
asiento (FR-012).
"""
from datetime import datetime, timezone

from sqlalchemy import func, or_

from ..models.budget import APIKey


def count_active_seats(db, tenant_id) -> int:
    # expires_at es DateTime naive-UTC (convención del modelo 013)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    return (
        db.query(func.count(APIKey.id))
        .filter(
            APIKey.tenant_id == tenant_id,
            APIKey.is_active.is_(True),
            or_(APIKey.expires_at.is_(None), APIKey.expires_at > now),
        )
        .scalar()
        or 0
    )
