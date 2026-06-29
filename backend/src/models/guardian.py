import uuid
from sqlalchemy import Column, String, Boolean, JSON
from sqlalchemy.dialects.postgresql import UUID
from ..database import Base

class Guardian(Base):
    __tablename__ = "guardians"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False)
    guardian_type = Column(String, nullable=False)  # "pii_masking", "secret_detection", "sensitive_routing"
    is_active = Column(Boolean, default=True)
    config = Column(JSON, default=dict)  # Stores type-specific configuration
