import uuid
from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from datetime import datetime
from ..database import Base
from .tenant import DEFAULT_TENANT_ID

class SecurityPolicy(Base):
    __tablename__ = "security_policies"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # tenant_id es el PRIMER paso hacia des-singletonizar entity_configs (spec 013);
    # la cascada client > group > tenant > default y el scope fino son spec 015.
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False,
                       default=DEFAULT_TENANT_ID, index=True)
    name = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)
    entity_configs = Column(JSONB, nullable=False) # e.g., {"PERSON": "MASK", "US_SSN": "BLOCK"}
    gdpr_mode = Column(Boolean, default=True)
    ai_act_mode = Column(Boolean, default=True)
    headroom_mode = Column(Boolean, default=False) # Deprecado: usar compression_mode (spec 012 US4)
    compression_mode = Column(Boolean, default=False) # Context optimization flag global (renombrado de headroom_mode)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
