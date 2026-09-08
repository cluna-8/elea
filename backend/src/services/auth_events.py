"""Eventos de auth → AuditLog inmutable existente (metadata-only), SIN cadena.

FR-016 parcial (spec 017/US1, T011): auditar los dos eventos de identidad que hoy
ocurren sin dejar rastro con actor — el bootstrap del primer admin y cada cambio de
rol de la matriz. Reusa el canal append-only de la 013 (mismo ``AuditLog``,
``model='auth'``) que ya usan las licencias, PERO sin la maquinaria de hash-chain de
``licensing/audit_events.py``: esto NO es evidencia facturable encadenada (eso es
licensing), es la bitácora de QUIÉN tocó a QUIÉN. Sin ``_locked_state``/``prev_hash``:
un evento de auth es una fila independiente, no un eslabón.

C1 — metadata-only: la entrada lleva SÓLO ids (str) y literales de rol. JAMÁS
password, texto libre ni PII. Es el mismo canal que audita PII (``models/audit.py``),
así que una fuga acá sería una regresión silenciosa del contrato de retención.
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

AUTH_BOOTSTRAP_ADMIN = "auth_bootstrap_admin"
AUTH_ROLE_CHANGED = "auth_role_changed"


def emit_auth_event(db, event_type: str, *, actor_user_id: Optional[str] = None,
                    target_user_id: Optional[str] = None,
                    old_role: Optional[str] = None, new_role: Optional[str] = None,
                    tenant_id=None) -> None:
    """Persiste UN evento de auth como fila de ``AuditLog`` (metadata-only), SIN cadena.

    NO commitea: el caller es dueño de la transacción, para que el evento viaje en la
    MISMA tx que la mutación que audita (el insert del bootstrap; el commit del cambio
    de rol). Espeja la construcción de fila de ``audit_events._append_chained``
    (``model='auth'``, contadores en 0, ``pii_detected=False``,
    ``compliance_status='passed'``) SIN ``seq``/``prev_hash``.

    Emisión fuera-de-request (bootstrap, pre-auth, sin GUC): el tenant de la fila cae a
    ``DEFAULT_TENANT_ID``, siguiendo el precedente de ``audit_events.emit_state_event``.
    Hoy ese INSERT pasa por la policy permisiva ``tenant_isolation_bootstrap`` de la 010;
    la 017/T020 la elimina — punto de coordinación, fuera del alcance de T011.
    """
    from ..models.audit import AuditLog
    from ..models.tenant import DEFAULT_TENANT_ID

    row_tenant = tenant_id or DEFAULT_TENANT_ID
    if isinstance(row_tenant, str):
        row_tenant = uuid.UUID(row_tenant)
    entry = {
        "event_type": event_type,
        "actor_user_id": actor_user_id,
        "target_user_id": target_user_id,
        "old_role": old_role,
        "new_role": new_role,
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    db.add(AuditLog(
        tenant_id=row_tenant,
        model="auth",
        prompt_tokens=0,
        completion_tokens=0,
        cost_usd=0,
        pii_detected=False,
        compliance_status="passed",
        latency_ms=0,
        guardian_events=[entry],
        # Spec 043 (US4, T047): tampoco es tráfico — mismo criterio que la 018 aplicó a
        # `model='license'`. `AuditLog.event_type` (columna) es un vocabulario distinto
        # del parámetro `event_type` de esta función (tipo de evento de auth).
        event_type="auth_evidence",
    ))
