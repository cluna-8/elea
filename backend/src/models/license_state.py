"""Estado runtime de licencia (spec 021 US5 — FR-023/FR-028).

UNA fila por deployment (id=1, garantizado por CheckConstraint): el hash-head
y el contador monotónico de la cadena de eventos de licencia, la génesis
anclada al license_id (registrable en el onboarding) y la marca monotónica
anti-rollback de reloj. Es el "pequeño estado" que el plan anticipa — NO es
schema del dominio (eso vive intacto en la 013).

Escrituras SIEMPRE bajo ``SELECT … FOR UPDATE`` (audit_events._chain_extend):
serializa la cadena entre requests, el thread del scheduler y N workers.
"""
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, Column, DateTime, Integer, String

from ..database import Base


class LicenseRuntimeState(Base):
    __tablename__ = "license_runtime_state"

    id = Column(Integer, primary_key=True, autoincrement=False)  # SIEMPRE 1
    genesis_license_id = Column(String, nullable=True)   # ancla de la génesis (onboarding)
    # Si la génesis quedó 'unlicensed' (primer boot sin licencia), acá queda el
    # PRIMER license_id con firma válida — atado a la cadena por el evento
    # license_genesis_anchored (hardening post-review: sin esto, el primer
    # true-up acusaría de tamper a un deployment honesto).
    anchored_license_id = Column(String, nullable=True)
    hash_head = Column(String, nullable=True)            # hex del último evento encadenado
    event_counter = Column(BigInteger, nullable=False, default=0)  # seq del último evento
    monotonic_ts = Column(DateTime, nullable=True)       # marca anti-rollback (naive UTC, convención 013)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        CheckConstraint("id = 1", name="ck_license_runtime_state_singleton"),
    )
