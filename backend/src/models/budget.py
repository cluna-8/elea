import uuid
from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Numeric, BigInteger, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from datetime import datetime
from ..database import Base

class Budget(Base):
    __tablename__ = "budgets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    group_id = Column(UUID(as_uuid=True), ForeignKey("groups.id"), nullable=True)
    max_spend_usd = Column(Numeric(10, 4), nullable=False)
    current_spend_usd = Column(Numeric(10, 4), default=0.0000)
    max_tokens = Column(BigInteger, nullable=False)
    current_tokens = Column(BigInteger, default=0)
    reset_period = Column(String, nullable=False) # daily, weekly, monthly, never
    last_reset_at = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    user = relationship("User", back_populates="budgets")
    group = relationship("Group", back_populates="budgets")

class APIKey(Base):
    __tablename__ = "api_keys"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    key_hash = Column(String, unique=True, nullable=False, index=True)
    key_preview = Column(String, nullable=False)
    engine_key_token = Column(String, nullable=True, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    group_id = Column(UUID(as_uuid=True), ForeignKey("groups.id"), nullable=True)
    name = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)
    expires_at = Column(DateTime, nullable=True)
    rpm_limit = Column(Integer, default=60)
    tpm_limit = Column(Integer, default=100000)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    user = relationship("User", back_populates="api_keys")
    group = relationship("Group", back_populates="api_keys")
    audit_logs = relationship("AuditLog", back_populates="api_key")
