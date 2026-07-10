import uuid
from sqlalchemy import Column, String, Boolean, JSON, Text, ForeignKey
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
    engine_guardrail_name = Column(String, nullable=True)   # internal name used by the AI engine
    fail_mode = Column(String, default="log")               # "block" | "log"
    apply_on = Column(String, default="pre_call")           # "pre_call" | "post_call" | "both"
    service_api_key_encrypted = Column(Text, nullable=True) # Fernet-encrypted API key for the guardrail service
