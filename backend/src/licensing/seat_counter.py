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
from ..models.user import User


def count_active_seats(db, tenant_id) -> int:
    # expires_at es DateTime naive-UTC (convención del modelo 013)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    # Spec 043 (US4, T046): las llaves de cuentas de servicio (`svc.anythingllm-provider`,
    # `svc.rag-masking` — instaladas por el instalador, ver diagnostico.md §4 de la 043)
    # NO ocupan asiento. Dos pasos con SOLO `.filter()`/`.all()`/`.scalar()` a propósito —
    # ni `.outerjoin()` ni `.subquery()` — porque esta es LA fuente única de conteo
    # (docstring del módulo) y el doble de test de `test_license_wire_formats.py`
    # (`_FakeQuery`, solo implementa esos cuatro métodos) la ejercita con una sesión falsa;
    # una lista Python vacía (`.all()` del doble) es un `NOT IN ()` inofensivo.
    ids_cuentas_servicio = [
        row[0] for row in db.query(User.id).filter(User.account_type == "service").all()
    ]
    filtros = [
        APIKey.tenant_id == tenant_id,
        APIKey.is_active.is_(True),
        or_(APIKey.expires_at.is_(None), APIKey.expires_at > now),
    ]
    if ids_cuentas_servicio:
        filtros.append(or_(APIKey.user_id.is_(None),
                           ~APIKey.user_id.in_(ids_cuentas_servicio)))
    return (
        db.query(func.count(APIKey.id))
        .filter(*filtros)
        .scalar()
        or 0
    )
