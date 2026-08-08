import uuid
from datetime import datetime
from sqlalchemy import Column, String, Boolean, JSON, Text, ForeignKey, DateTime
from sqlalchemy.dialects.postgresql import UUID
from ..database import Base
from .tenant import DEFAULT_TENANT_ID

class Guardian(Base):
    __tablename__ = "guardians"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False,
                       default=DEFAULT_TENANT_ID, index=True)
    name = Column(String, nullable=False)
    guardian_type = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)
    config = Column(JSON, default=dict)
    # issue #104: desempate DETERMINISTA cuando coexiste más de un guardián `pii_masking`
    # activo. Todos los lectores de la postura NLP ordenan por `(created_at, id)` — el mismo
    # criterio «determinismo puro» que `_IDENTITY_SQL` ya usa para el presupuesto (#76)— para
    # que los dos planos y `/health` elijan SIEMPRE la misma fila (la más antigua).
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    engine_guardrail_name = Column(String, nullable=True)   # internal name used by the AI engine
    fail_mode = Column(String, default="log")               # "block" | "log"
    apply_on = Column(String, default="pre_call")           # "pre_call" | "post_call" | "both"
    service_api_key_encrypted = Column(Text, nullable=True) # Fernet-encrypted API key for the guardrail service
